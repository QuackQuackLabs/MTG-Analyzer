"""Heuristic battle/matchup simulator (Phase 9, Phase A: 1v1 + basic pod).

Abstracts each deck to a `BattleProfile` from existing analyze()/simulate() signals, then runs
a turn-based Monte-Carlo of game *dynamics* — win-attempt hazards, interaction trades, combat,
and (multiplayer) threat focusing. **Not a rules engine** (no stack/targeting/card resolution);
outputs are relative win rates with a sensitivity band. See docs/battle-simulator-design.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from mtg_analyzer.models.analysis import DeckReport
from mtg_analyzer.models.battle import BattleProfile, DeckWinStats, MatchResult
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.simulation import SimResult
from mtg_analyzer.simulation import battle_params as P


def _counts(report: DeckReport) -> dict[str, int]:
    return {c.category: c.count for c in report.categories}


def _creature_count(deck: ResolvedDeck) -> int:
    return sum(
        e.quantity
        for e in deck.mainboard
        if e.card
        and "creature" in (e.card.type_line or "").lower()
        and "land" not in (e.card.type_line or "").lower()
    )


def _archetype(
    creatures: int, online: float, combo_turn: float | None, counts: dict[str, int], has_combo: bool
) -> str:
    """Classify the deck's *primary* win plan. The combo is primary only when it assembles near the
    deck's natural tempo (combo_turn ≲ commander-online + a small gap) — measured from the goldfish,
    not guessed from creature count. A deck whose combo lands far later (e.g. a fast aristocrats deck
    that *can* combo) is classified by its faster plan instead."""
    control = counts.get("counterspell", 0) + counts.get("removal", 0)
    if has_combo and combo_turn is not None and combo_turn <= online + P.COMBO_PRIMARY_GAP:
        return "combo"
    if has_combo and combo_turn is None and creatures < 22:
        return "combo"  # no goldfish combo signal: fall back to the old creature-light heuristic
    if creatures >= 27 and online <= 4.5:
        return "aggro"
    if control >= 12 and online >= 5:
        return "control"
    if counts.get("draw", 0) >= 11 and online >= 5:
        return "grind"
    return "midrange"


def build_profile(
    name: str, deck: ResolvedDeck, report: DeckReport, sim: SimResult | None
) -> BattleProfile:
    """Map a deck's analysis + goldfish sim onto the battle levers (the only place we abstract)."""
    counts = _counts(report)
    online = (
        sim.commander_turn.mean
        if sim and sim.commander_turn and sim.commander_turn.mean is not None
        else 4.0
    )
    creatures = _creature_count(deck)
    has_combo = bool(report.combos)
    combo_turn = sim.combo_turn.mean if sim and sim.combo_turn and sim.combo_turn.mean is not None else None
    combo_count = sim.combo_count if sim else 0
    archetype = _archetype(creatures, online, combo_turn, counts, has_combo)

    off, sd = P.ARCHETYPE_CLOCK.get(archetype, P.DEFAULT_CLOCK)
    clock_mean = round(online + off, 2)

    # Combo-awareness (Layer 2): for non-aggro combo decks, ground the clock in the goldfish-measured
    # assembly turn (blended with the archetype estimate, since combo_turn assumes hardcasting), and
    # let combo redundancy tighten the variance. Aggro/cheat decks keep their faster combat clock —
    # the hardcast combo_turn would wrongly slow a blitzed/reanimated combo.
    if has_combo and combo_turn is not None and archetype != "aggro":
        clock_mean = round(P.COMBO_CLOCK_W * combo_turn + (1 - P.COMBO_CLOCK_W) * clock_mean, 2)
        sd = round(max(P.COMBO_MIN_SD, sd - P.COMBO_REDUNDANCY_SD * max(0, combo_count - 1)), 2)

    interaction = counts.get("counterspell", 0) + counts.get("removal", 0)
    tutors = counts.get("tutor", 0)
    card_adv = counts.get("draw", 0)

    # Threat: faster clock + combo + higher bracket = more of a target.
    speed = max(0.0, 12.0 - clock_mean)
    threat = (
        P.THREAT_BRACKET_W * report.bracket_estimate
        + P.THREAT_COMBO_W * (1.0 if has_combo else 0.0)
        + P.THREAT_SPEED_W * speed / 3.0
    )

    notes: list[str] = []
    if sim is None or sim.commander_turn is None:
        notes.append("no commander-online sim; clock estimated from default")
    return BattleProfile(
        name=name,
        archetype=archetype,
        clock_mean=clock_mean,
        clock_sd=sd,
        interaction=interaction,
        sweepers=counts.get("board_wipe", 0),
        card_advantage=card_adv,
        has_combo=has_combo,
        combo_count=combo_count,
        tutors=tutors,
        threat_level=round(threat, 2),
        notes=notes,
    )


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _argmax(xs: list[int], rng: np.random.Generator) -> int:
    """Index of the max, breaking ties UNIFORMLY (not by seat order). A deterministic seat-order
    tiebreak biases mirror matches — later seats win far more — so ties are resolved by `rng`."""
    top = max(xs)
    tied = [i for i, x in enumerate(xs) if x == top]
    return int(rng.choice(tied)) if len(tied) > 1 else tied[0]


def _play_match(
    profiles: list[BattleProfile], rng: np.random.Generator, answer_base: float
) -> tuple[int, int, str, int, list[int]]:
    """One game. Returns (winner, end_turn, method, first_eliminated or -1, archenemy-turns/deck)."""
    n = len(profiles)
    life = [float(P.START_LIFE)] * n
    reserve = [float(p.interaction) for p in profiles]
    sweepers = [p.sweepers for p in profiles]
    delay = [0.0] * n  # clock setback accumulated from answered attempts / sweepers
    alive = [True] * n
    first_out = -1
    archenemy_turns = [0] * n  # how many turns each deck was the table's consensus archenemy
    damage_from = [[0.0] * n for _ in range(n)]  # damage_from[k][p]: total k has dealt to p

    # A1 — stochastic grounding: draw each deck's REALIZED kill turn for THIS game from its clock
    # distribution, so attempts are correlated within the game instead of independent per-turn rolls.
    # Tutors shift the realized clock earlier (combo-assembly help, capped).
    game_clock = [
        max(1.0, float(rng.normal(
            p.clock_mean - min(P.TUTOR_CLOCK_SHIFT * p.tutors, P.TUTOR_CLOCK_SHIFT_CAP), p.clock_sd)))
        for p in profiles
    ]

    def answer_prob(j: int) -> float:
        return min(P.INTERACTION_ANSWER_MAX, answer_base + P.INTERACTION_ANSWER_PER_PT * profiles[j].interaction)

    def live_threat(j: int, turn: int) -> float:
        # Turn-by-turn threat: the table re-reads who is actually winning *right now* from board
        # development, resources, and life lead — not just a static pre-game power number. Keeps a
        # diluted static floor, then adds the dynamic signals that track the real leader. Uses the
        # deck's REALIZED clock this game (A1) so the table sees who's actually fast, not the average.
        p = profiles[j]
        eff = game_clock[j] + delay[j]
        # Board development: how far past its setup turn the deck is (online = board deployed),
        # amplified by its resource level (card advantage = more on the battlefield).
        online = _logistic((turn - eff) / P.THREAT_BOARD_DEV_STEEP)
        board = P.THREAT_BOARD_W * online * (1.0 + 0.08 * p.card_advantage)
        # Life lead over the rest of the living table → ahead-on-life players are bigger targets.
        living_life = [life[k] for k in range(n) if alive[k]]
        avg_life = sum(living_life) / len(living_life) if living_life else life[j]
        life_lead = P.THREAT_LIFE_W * (life[j] - avg_life)
        # Proximity to their own kill turn (about to win) still spikes fear.
        prox = max(0.0, P.THREAT_PROXIMITY_WINDOW - abs(turn - eff))
        # An online combo deck threatens a sudden table-wide loss → it draws the heat (gated by
        # board development, so it's "about to combo off", not a flat "fastest = scariest").
        combo_imminence = P.THREAT_COMBO_IMMINENCE_W * online if p.has_combo else 0.0
        return (
            P.THREAT_STATIC_W * p.threat_level
            + P.THREAT_CARDADV_W * p.card_advantage
            + board
            + life_lead
            + P.THREAT_PROXIMITY_W * prox
            + combo_imminence
        )

    def assess(turn: int) -> tuple[list[int], int]:
        """Each living player privately scores opponents and votes its #1 threat; the politicking
        engine returns (per-player vote, consensus archenemy for this turn). Reads share a power
        baseline but diverge by who's been damaging the assessor + a small individual read, so the
        table doesn't always agree."""
        votes = [-1] * n
        tally = [0] * n
        for p in range(n):
            if not alive[p]:
                continue
            best, best_score = -1, -1e9
            for k in range(n):
                if k == p or not alive[k]:
                    continue
                score = (live_threat(k, turn)
                         + P.DAMAGE_FEAR_W * damage_from[k][p]
                         + rng.normal(0.0, P.PERCEPTION_NOISE))
                if score > best_score:
                    best_score, best = score, k
            votes[p] = best
            if best >= 0:
                tally[best] += 1
        archenemy = _argmax(tally, rng) if any(tally) else -1
        return votes, archenemy

    for turn in range(1, P.MAX_TURNS + 1):
        votes, archenemy = assess(turn)
        if archenemy >= 0:
            archenemy_turns[archenemy] += 1

        for i in range(n):
            if not alive[i]:
                continue
            reserve[i] = min(P.INTERACTION_CAP, reserve[i] + profiles[i].card_advantage * P.CARD_ADVANTAGE_REFILL)

            # A1: sharp ramp around the REALIZED kill turn (between-game variance already lives in
            # game_clock). Once a deck reaches its assembled turn it tries to win; answers push it back
            # via `delay`. No per-turn re-rolling of "did I draw the combo" — that's fixed per game.
            eff_clock = game_clock[i] + delay[i]
            p_attempt = min(P.ATTEMPT_CAP, _logistic(P.INGAME_ATTEMPT_STEEPNESS * (turn - eff_clock)))
            if rng.random() >= p_attempt:
                continue

            # A win ATTEMPT is a visible lethal threat (esp. under A1, where decks go off once at their
            # realized clock rather than telegraphing over many turns): the table coordinates answers
            # against it — up to ARCHENEMY_ANSWERERS best-equipped opponents pitch in. If the attacker
            # was the *pre-identified* archenemy the table was ready (higher rate); a surprise attacker
            # (not the consensus threat) is still answered, but less effectively.
            equipped = sorted((j for j in range(n) if j != i and alive[j] and reserve[j] >= 1.0),
                              key=lambda j: reserve[j], reverse=True)
            designated = equipped[:P.ARCHENEMY_ANSWERERS]
            politics = P.POLITICS_ARCHENEMY_ANSWER if i == archenemy else P.POLITICS_NONARCH_ANSWER
            answered = False
            for j in designated:
                if rng.random() < answer_prob(j) * politics:
                    reserve[j] -= 1.0
                    delay[i] += P.ANSWER_CLOCK_PENALTY
                    answered = True
                    break
            if answered:
                continue

            # Unanswered. Combo decks win outright; others swing at the biggest threat.
            if profiles[i].has_combo:
                return i, turn, "combo", first_out, archenemy_turns
            foes = [j for j in range(n) if j != i and alive[j]]
            # Final rng key breaks threat/life ties uniformly, else identical foes all get
            # focus-fired onto the lowest seat (a systematic seat-order bias).
            target = max(foes, key=lambda j: (live_threat(j, turn), -life[j], rng.random()))
            if sweepers[target] > 0 and rng.random() < P.SWEEPER_BLUNT_P:
                sweepers[target] -= 1
                delay[i] += P.SWEEPER_DELAY
                continue
            dmg = P.ALPHA_STRIKE_FRACTION * P.START_LIFE
            life[target] -= dmg
            damage_from[i][target] += dmg  # the target now fears i more next assessment
            if life[target] <= 0:
                alive[target] = False
                if first_out == -1:
                    first_out = target
                if sum(alive) == 1:
                    return i, turn, "beatdown", first_out, archenemy_turns

    # Game went long: inevitability decides among the living — *probabilistically*, weighted by
    # each deck's grind score, so it isn't a deterministic winner-take-all collapse.
    w = P.INEVITABILITY_WEIGHTS

    def inevitability(i: int) -> float:
        return (
            w["card_advantage"] * profiles[i].card_advantage
            + w["combo"] * (1.0 if profiles[i].has_combo else 0.0)
            + w["interaction"] * profiles[i].interaction
        )

    living = [i for i in range(n) if alive[i]]
    scores = np.array([max(0.1, inevitability(i)) for i in living], dtype=float)
    winner = int(rng.choice(living, p=scores / scores.sum()))
    return winner, P.MAX_TURNS, "inevitability", first_out, archenemy_turns


@dataclass
class _RunTally:
    wins: list[int]
    turns_by_winner: list[list[int]]
    methods: list[dict[str, int]]
    first_out: list[int]
    archenemy_share: list[float]  # summed per-game turn-share each deck was the consensus archenemy
    avg_len: float


def _run(profiles: list[BattleProfile], games: int, seed: int, answer_base: float) -> _RunTally:
    """Run `games` matches at a given interaction-answer base. Returns raw tallies."""
    n = len(profiles)
    rng = np.random.default_rng(seed)
    wins = [0] * n
    turns_by_winner: list[list[int]] = [[] for _ in range(n)]
    methods: list[dict[str, int]] = [{} for _ in range(n)]
    first_out = [0] * n
    archenemy_share = [0.0] * n  # accumulated per-game fraction of turns each deck was archenemy
    total_turns = 0
    for _ in range(games):
        wi, turn, method, fo, ae_turns = _play_match(profiles, rng, answer_base)
        wins[wi] += 1
        turns_by_winner[wi].append(turn)
        methods[wi][method] = methods[wi].get(method, 0) + 1
        if fo >= 0:
            first_out[fo] += 1
        ae_total = sum(ae_turns) or 1
        for i in range(n):
            archenemy_share[i] += ae_turns[i] / ae_total
        total_turns += turn
    return _RunTally(wins, turns_by_winner, methods, first_out, archenemy_share, total_turns / games)


def _ranks(values: list[float], *, ascending: bool) -> list[int]:
    """Ordinal 1-based ranks (1 = best). ascending=True ranks lowest-first (clock: fast = rank 1);
    ascending=False ranks highest-first (equity: most wins = rank 1). Ties broken by seat order."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=not ascending)
    rank = [0] * len(values)
    for r, i in enumerate(order, 1):
        rank[i] = r
    return rank


def _rank_shift_phrase(shift: int) -> str:
    if shift == 0:
        return "on pace"
    return f"{'+' if shift > 0 else '−'}{abs(shift)} {'over' if shift > 0 else 'under'} speed"


def _explain(
    prof: BattleProfile, clock_rank: int, equity_rank: int, shift: int,
    methods: dict[str, float], archenemy_rate: float, died_first_rate: float, n: int,
) -> str:
    """One-line attribution: where raw speed (clock) landed vs. realized equity, plus the politics
    pressure and dominant win method that moved it."""
    parts = [f"clock #{clock_rank} → equity #{equity_rank} ({_rank_shift_phrase(shift)})"]
    if n > 2:
        if archenemy_rate >= P.EXPLAIN_ARCHENEMY_HI:
            parts.append(f"drew the table's answers (archenemy {archenemy_rate:.0%} of turns)")
        elif died_first_rate >= P.EXPLAIN_DIED_FIRST_HI:
            parts.append(f"folds early (died-first {died_first_rate:.0%})")
    if methods:
        method, frac = max(methods.items(), key=lambda kv: kv[1])
        parts.append(f"wins mostly by {method} ({frac:.0%})")
    return "; ".join(parts)


def simulate_match(
    profiles: list[BattleProfile], *, games: int = 2000, seed: int = 1
) -> MatchResult:
    """Simulate a 1v1 (2 decks) or pod (3–4) match; report banded win rates + metrics."""
    n = len(profiles)
    # Base run + sensitivity runs (interaction-answer base scaled +/- SENSITIVITY).
    base = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE)
    lo = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE * (1 - P.SENSITIVITY))
    hi = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE * (1 + P.SENSITIVITY))

    # Explainability ranks: raw goldfish speed (clock) vs. realized equity (wins). The gap between
    # them is exactly what interaction + politics added on top of raw speed (design §5).
    clock_rank = _ranks([p.clock_mean for p in profiles], ascending=True)
    equity_rank = _ranks([float(base.wins[i]) for i in range(n)], ascending=False)

    decks: list[DeckWinStats] = []
    for i, prof in enumerate(profiles):
        rates = sorted([base.wins[i] / games, lo.wins[i] / games, hi.wins[i] / games])
        method_total = sum(base.methods[i].values()) or 1
        methods = {k: round(v / method_total, 2) for k, v in base.methods[i].items()}
        shift = clock_rank[i] - equity_rank[i]
        archenemy_rate = round(base.archenemy_share[i] / games, 3) if n > 2 else 0.0
        died_first_rate = round(base.first_out[i] / games, 3)
        decks.append(
            DeckWinStats(
                name=prof.name,
                win_rate=round(base.wins[i] / games, 3),
                win_rate_low=round(rates[0], 3),
                win_rate_high=round(rates[2], 3),
                avg_win_turn=round(float(np.mean(base.turns_by_winner[i])), 1)
                if base.turns_by_winner[i] else None,
                methods=methods,
                archenemy_rate=archenemy_rate,
                died_first_rate=died_first_rate,
                clock_mean=prof.clock_mean,
                clock_rank=clock_rank[i],
                equity_rank=equity_rank[i],
                rank_shift=shift,
                explain=_explain(prof, clock_rank[i], equity_rank[i], shift,
                                 methods, archenemy_rate, died_first_rate, n),
            )
        )

    assumptions = [
        f"interaction-answer base {P.INTERACTION_ANSWER_BASE:.2f} (band ±{int(P.SENSITIVITY*100)}%), "
        f"start life {P.START_LIFE}, max {P.MAX_TURNS} turns",
        "clock = goldfish commander-online turn + archetype offset; combo decks can win on an "
        "unanswered attempt; non-combo decks win by attrition/last-standing",
    ]
    notes = [
        "Heuristic dynamics model, NOT a rules engine — relative win rates only, banded by the "
        "interaction assumption. Does not model specific cards, stax, or silver-bullet hate.",
    ]
    if n > 2:
        notes.append("Pod politics: each turn every player privately assesses threats (power level + "
                     "who's near winning + who's been hitting them) and votes; the most-voted deck is "
                     "the consensus archenemy and its voters commit the answers. Archenemy = avg share "
                     "of turns a deck held that role.")
    # Clock-vs-equity insight: the biggest gap between raw-speed rank and finish rank is the
    # headline takeaway — it's the part of the result that goldfish speed alone can't explain.
    under = min(decks, key=lambda d: d.rank_shift)  # finished most below its speed
    over = max(decks, key=lambda d: d.rank_shift)   # finished most above its speed
    if under.name != over.name and (under.rank_shift <= -1 or over.rank_shift >= 1):
        notes.append(
            "Clock vs. equity — raw speed is not destiny: "
            f"{under.name} is faster than it finishes (clock #{under.clock_rank} → equity "
            f"#{under.equity_rank}), while {over.name} punches above its clock "
            f"(#{over.clock_rank} → #{over.equity_rank}). That gap is what interaction and politics "
            "added on top of goldfish speed."
        )
    return MatchResult(
        players=n, games=games, decks=decks, avg_game_length=round(base.avg_len, 1),
        assumptions=assumptions, notes=notes,
    )


@dataclass
class CalibrationRow:
    answer_base: float
    win_rates: list[float]
    avg_len: float
    inevitability_share: float  # fraction of games decided by the turn-cap tiebreak (model health)


def calibrate_match(
    profiles: list[BattleProfile], *, games: int = 1500, seed: int = 1
) -> list[CalibrationRow]:
    """Sweep the interaction-answer base; report per-deck win-rate ranges + how often games resolve
    mid-game vs. fall to the inevitability tiebreak. A high inevitability share = unhealthy model
    (pods stalling); the sweep makes the parameter sensitivity and that health visible."""
    n = len(profiles)
    rows: list[CalibrationRow] = []
    for ab in (0.18, 0.24, 0.30, 0.36, 0.42):
        t = _run(profiles, games, seed, ab)
        inev = sum(t.methods[i].get("inevitability", 0) for i in range(n)) / games
        rows.append(CalibrationRow(ab, [t.wins[i] / games for i in range(n)], t.avg_len, inev))
    return rows

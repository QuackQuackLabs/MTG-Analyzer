"""Heuristic battle/matchup simulator (Phase 9, Phase A: 1v1 + basic pod).

Abstracts each deck to a `BattleProfile` from existing analyze()/simulate() signals, then runs
a turn-based Monte-Carlo of game *dynamics* — win-attempt hazards, interaction trades, combat,
and (multiplayer) threat focusing. **Not a rules engine** (no stack/targeting/card resolution);
outputs are relative win rates with a sensitivity band. See docs/battle-simulator-design.md.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from mtg_analyzer.models.analysis import DeckReport
from mtg_analyzer.models.battle import BattleProfile, DeckWinStats, MatchResult
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.simulation import SimResult
from mtg_analyzer.simulation import battle_params as P

# F4 — protection: cards that shield the controller's own win attempt (and thereby cancel an opponent's
# answer ~1:1) — free counters, hexproof/shroud/ward grantors, "can't be countered", indestructible/
# protection grantors. Scanned directly from oracle text here (battle-module-local; no analysis-pipeline
# category change). Deliberately narrow to keep it a protection signal, not a generic-keyword count.
_RE_PROTECTION = re.compile(
    r"can't be countered|hexproof|\bshroud\b|\bward\b|protection from|"
    r"gain (hexproof|shroud|indestructible|protection)|"
    r"gains? (hexproof|shroud|indestructible|protection)|"
    r"(creatures? you control|permanents? you control|target permanent you control).{0,40}indestructible",
    re.S,
)


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


def _protection_count(deck: ResolvedDeck) -> int:
    """F4: cards that protect the controller's own play (cancel an opponent's answer ~1:1)."""
    return sum(
        e.quantity
        for e in deck.mainboard
        if e.card and _RE_PROTECTION.search((e.card.oracle_text or "").lower())
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

    # Combo-awareness (Layer 2 + Stage 0.1): for a combo-PRIMARY deck, ground the attempt clock in the
    # goldfish-measured assembly turn (blended with the archetype estimate, since combo_turn assumes
    # hardcasting) and let combo redundancy tighten the variance — its attempt IS the combo. A non-combo
    # archetype that merely *contains* a combo keeps its (faster) archetype clock as the attempt clock;
    # its combo is a strictly-later backup line tracked separately in `combo_clock` (set below), so it
    # wins by beatdown at clock_mean and only by combo once the game actually reaches the assembly turn.
    if has_combo and combo_turn is not None and archetype == "combo":
        clock_mean = round(P.COMBO_CLOCK_W * combo_turn + (1 - P.COMBO_CLOCK_W) * clock_mean, 2)
        sd = round(max(P.COMBO_MIN_SD, sd - P.COMBO_REDUNDANCY_SD * max(0, combo_count - 1)), 2)

    # Stage 0.1 — the decoupled win-clock. Only an INCIDENTAL combo (carried by a non-combo archetype)
    # needs a separate, later combo_clock; a combo-primary deck leaves it None (its attempt clock already
    # IS its combo turn), as do synthetic/legacy profiles — both fall back to clock_mean in the match.
    combo_clock = combo_turn if (has_combo and combo_turn is not None and archetype != "combo") else None

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
        combo_clock=combo_clock,
        interaction=interaction,
        sweepers=counts.get("board_wipe", 0),
        card_advantage=card_adv,
        has_combo=has_combo,
        combo_count=combo_count,
        tutors=tutors,
        threat_level=round(threat, 2),
        visibility=P.ARCHETYPE_VISIBILITY.get(archetype, P.DEFAULT_VISIBILITY),
        protection=_protection_count(deck),
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
    reputation = [0.0] * n  # F1: lightning-rod heat that accrues while a deck holds the archenemy role

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

    def perceived_threat(j: int, turn: int) -> float:
        # F1 — perception split: the table targets off PERCEIVED, not true, threat. The standing
        # live-threat read is scaled by archetype visibility (combo/ramp under-read = "quiet shark"),
        # then lightning-rod reputation is added: a deck that's been the archenemy keeps drawing heat
        # semi-independent of board state, plus a small static term for the visibly-strongest deck.
        # This collapses the highest-perceived deck's win rate below fair share (the 11% archenemy).
        return (
            live_threat(j, turn) * profiles[j].visibility
            + P.REPUTATION_W * reputation[j]
            + P.REPUTATION_STATIC_W * profiles[j].threat_level
            # Stage 3c — metagame-knowledge prior (default off): the table also targets off who is KNOWN
            # to win, fed back from the sim's own win rates via the fictitious-play loop in
            # `simulate_metagame`. A positive prior (a proven winner like Sauron) draws standing heat
            # even through the quiet-shark visibility discount; a negative prior (a never-wins aggro deck
            # like Frodo) is left alone at game start, while the dynamic board/proximity terms above still
            # flag it if it actually takes off mid-game.
            + P.WINRATE_PRIOR_W * profiles[j].win_prior
        )

    def assess(turn: int) -> tuple[list[int], int]:
        """Each living player privately scores opponents and votes its #1 threat; the politicking
        engine returns (per-player vote, consensus archenemy for this turn). Reads share a perceived-
        threat baseline (F1: true equity × visibility + reputation) but diverge by who's been damaging
        the assessor + a small individual read, so the table doesn't always agree."""
        votes = [-1] * n
        tally = [0] * n
        for p in range(n):
            if not alive[p]:
                continue
            best, best_score = -1, -1e9
            for k in range(n):
                if k == p or not alive[k]:
                    continue
                score = (perceived_threat(k, turn)
                         + P.DAMAGE_FEAR_W * damage_from[k][p]
                         + rng.normal(0.0, P.PERCEPTION_NOISE))
                if score > best_score:
                    best_score, best = score, k
            votes[p] = best
            if best >= 0:
                tally[best] += 1
        archenemy = _argmax(tally, rng) if any(tally) else -1
        return votes, archenemy

    def grind_equity(j: int) -> float:
        # Stage 1.1 — capacity to win the long game by attrition: out-answer the table (interaction,
        # weighted heaviest), refuel (card advantage), and survive disruption (protection + combo
        # redundancy). This is the resource axis the clock ignores — what makes a slow control deck good.
        p = profiles[j]
        base = (
            P.GRIND_INTERACTION_W * p.interaction
            + P.GRIND_CARDADV_W * p.card_advantage
            + P.GRIND_RESILIENCE_W * (p.protection + max(0, p.combo_count - 1))
        )
        # The lightning-rod deck is spending everything under fire — it can't ALSO grind the table out.
        # Discount grind capacity by the heat (reputation) it's currently drawing, so the table's
        # perennial archenemy loses the long game to the quiet resource deck (the "fish that's a shark").
        return base / (1.0 + P.GRIND_HEAT_W * reputation[j])

    for turn in range(1, P.MAX_TURNS + 1):
        votes, archenemy = assess(turn)
        # F1 — lightning-rod reputation: heat decays each turn, then the current consensus archenemy
        # gets bumped. A deck that stays the archenemy compounds heat toward BUMP/(1−DECAY), keeping
        # the table on it even as the board moves — the mechanism that pushes its win rate below 1/N.
        for k in range(n):
            reputation[k] *= P.REPUTATION_DECAY
        if archenemy >= 0:
            archenemy_turns[archenemy] += 1
            reputation[archenemy] += P.REPUTATION_BUMP

        for i in range(n):
            if not alive[i]:
                continue
            reserve[i] = min(P.INTERACTION_CAP, reserve[i] + profiles[i].card_advantage * P.CARD_ADVANTAGE_REFILL)

            # A1: sharp ramp around the REALIZED kill turn (between-game variance already lives in
            # game_clock). Once a deck reaches its assembled turn it tries to win; answers push it back
            # via `delay`. No per-turn re-rolling of "did I draw the combo" — that's fixed per game.
            eff_clock = game_clock[i] + delay[i]
            p_attempt = min(P.ATTEMPT_CAP, _logistic(P.INGAME_ATTEMPT_STEEPNESS * (turn - eff_clock)))
            # F3 — go-first penalty / standoff: going off while opponents still hold open answers gets
            # you answered, so a savvy deck waits. Suppress the attempt in proportion to the table's
            # open interaction; attrition (F2) drains it over time, breaking the standoff so someone is
            # eventually forced to commit (and is the one who gets answered — the go-first penalty).
            open_answers = sum(reserve[j] for j in range(n) if j != i and alive[j])
            scale = max(1.0, (sum(alive) - 1) * P.STANDOFF_OPEN_REF)
            caution = P.GO_FIRST_CAUTION * min(1.0, open_answers / scale)
            # Impatience breaks the standoff: the longer a deck sits past its clock the less it waits,
            # so caution decays to 0 and someone is eventually forced to commit (and gets answered) —
            # otherwise low attempts keep reserves high, which keeps caution high, deadlocking the game.
            impatience = min(1.0, max(0.0, turn - eff_clock) / P.GO_FIRST_IMPATIENCE)
            p_attempt *= 1.0 - caution * (1.0 - impatience)
            if rng.random() >= p_attempt:
                continue

            # Stage 0.1 — is THIS attempt a combo kill or a beatdown swing? A combo deck (or a synthetic/
            # legacy profile with no separate combo_clock) attempts AS its combo, so combo_clock falls back
            # to clock_mean and it's online by definition. A deck carrying an incidental combo only combos
            # once the game reaches that combo's (later) assembly turn; until then this attempt is a
            # beatdown swing — which the table answers less hard and protection does not shield.
            cc = profiles[i].combo_clock
            combo_clock = cc if cc is not None else profiles[i].clock_mean
            is_combo_attempt = profiles[i].has_combo and turn >= combo_clock - P.COMBO_ONLINE_SLACK

            # F2 — table-wide answer check with equity-gated, free-rider-discounted willingness. The win
            # attempt is a visible lethal threat; opponents are polled most-invested-first and the first
            # to commit stops it (the rest free-ride — exactly the bystander effect: each defers hoping
            # another acts, and if all decline the threat RESOLVES). Per-defender willingness =
            #   capability (answer_prob) × own-equity gate × lethal gate × table coordination.
            # The own-equity gate makes a leader snap off a threat to its lead while a trailing player
            # shrugs ("not my problem"); the lethal gate answers a combo/archenemy harder than a
            # beatdown swing; coordination is the flat free-rider/diffusion factor (the §3.6 knob).
            lethal = P.ANSWER_LETHAL_COMBO if is_combo_attempt else P.ANSWER_LETHAL_BEATDOWN
            if i == archenemy:
                lethal = min(1.0, lethal * P.ANSWER_ARCHENEMY_MULT)
            # Baseline = the DEFENDERS' average equity (exclude the attacker, whose lethal-threat spike
            # would otherwise drag every defender below average and floor the gate). A defender ahead of
            # its peers snaps the threat off; one behind shrugs.
            peer_eq = [max(0.0, live_threat(k, turn)) for k in range(n) if alive[k] and k != i]
            avg_eq = sum(peer_eq) / len(peer_eq) if peer_eq else 0.0

            def equity_gate(j: int) -> float:
                g = 1.0 + P.ANSWER_EQUITY_SLOPE * (max(0.0, live_threat(j, turn)) - avg_eq)
                return min(P.ANSWER_EQUITY_MAX, max(P.ANSWER_EQUITY_MIN, g))

            # F3 — spoiler: the table's LEADER (highest current equity) is denied by out-of-contention
            # seats. A clearly-trailing seat, late game, spends interaction to stop the frontrunner even
            # though it can't win — overriding the own-equity gate that would say "not my problem".
            total_eq = sum(max(0.0, live_threat(k, turn)) for k in range(n) if alive[k]) or 1.0
            leader = max((k for k in range(n) if alive[k]), key=lambda k: live_threat(k, turn))

            def is_spoiler(j: int) -> bool:
                return (turn >= P.SPOILER_MIN_TURN and j != leader
                        and max(0.0, live_threat(j, turn)) / total_eq < P.SPOILER_SHARE_MAX)

            able = sorted((j for j in range(n) if j != i and alive[j] and reserve[j] >= 1.0),
                          key=lambda j: live_threat(j, turn), reverse=True)  # most-invested answers first
            # F4 — protection cancels answers ~1:1, but per-attempt PROBABILISTIC (you only sometimes
            # hold a protection piece). Each landed answer is still SPENT (attrition) but fizzles with
            # `cancel_p`; the win is stopped by the first answer that ISN'T cancelled. A protection-dense
            # combo can survive the whole table — "a win must survive three defenders, free counters
            # cancel them 1:1".
            cancel_p = (min(P.PROT_CANCEL_CAP, P.PROT_CANCEL_PER_PIECE * profiles[i].protection)
                        if is_combo_attempt else 0.0)  # protection shields a combo win, not a beatdown swing
            answered = False
            for j in able[:P.ARCHENEMY_ANSWERERS]:
                willing = min(1.0, answer_prob(j) * equity_gate(j) * lethal) * P.ANSWER_COORDINATION
                if i == leader and is_spoiler(j):
                    willing = min(1.0, willing * P.SPOILER_ANSWER_BONUS)
                if rng.random() < willing:
                    reserve[j] -= 1.0
                    if cancel_p == 0.0 or rng.random() >= cancel_p:  # answer lands (not protected)
                        delay[i] += P.ANSWER_CLOCK_PENALTY
                        answered = True
                        break
            if answered:
                continue

            # Unanswered. An online combo wins outright; everything else (incl. a combo deck whose combo
            # isn't assembled yet) swings at the biggest threat.
            if is_combo_attempt:
                return i, turn, "combo", first_out, archenemy_turns
            foes = [j for j in range(n) if j != i and alive[j]]
            # Attacker swings at the biggest PERCEIVED threat (F1), so combat heat tracks the same
            # lightning-rod the table answers on. Final rng key breaks threat/life ties uniformly,
            # else identical foes all get focus-fired onto the lowest seat (a seat-order bias).
            target = max(foes, key=lambda j: (perceived_threat(j, turn), -life[j], rng.random()))
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

        # Stage 1.1 — mid-game attrition: once developed, a resource-dominant deck can grind the table
        # out before anyone's clock resolves, weighted by grind-equity so the answer/value leader (a
        # slow control deck) finally has a win path the clock alone never gave it. Fires rarely per turn
        # so it decides the games that genuinely stall into a grind, not the ones a fast clock closes.
        if turn >= P.ATTRITION_MIN_TURN:
            living = [i for i in range(n) if alive[i]]
            if len(living) >= 2:
                eq = sorted(((grind_equity(i), i) for i in living), reverse=True)
                # Margin vs the FIELD MEAN (not the runner-up): large when the leader towers over the
                # table average — even if a second strong deck is present — but ≈0 when everyone is
                # resource-even (mirror / a fast deck racing an equal deck), which keeps anchors safe.
                margin = eq[0][0] - sum(e for e, _ in eq) / len(eq)
                p_fire = P.ATTRITION_RATE * _logistic((margin - P.ATTRITION_MARGIN_REF) / P.ATTRITION_MARGIN_STEEP)
                if rng.random() < p_fire:
                    gw = np.array([max(0.1, e) ** P.GRIND_POWER for e, _ in eq], dtype=float)
                    winner = int(rng.choice([i for _, i in eq], p=gw / gw.sum()))
                    return winner, turn, "attrition", first_out, archenemy_turns

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
    profiles: list[BattleProfile], *, games: int = 2000, seed: int = 1, preset: str | None = None
) -> MatchResult:
    """Simulate a 1v1 (2 decks) or pod (3–4) match; report banded win rates + metrics.

    `preset` (F5) applies a power-level bundle of social/format knobs (casual | mid | cedh) from
    `battle_params.POWER_PRESETS` for the duration of the runs."""
    n = len(profiles)
    if preset is not None and preset not in P.POWER_PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose from {sorted(P.POWER_PRESETS)}")
    overrides = P.POWER_PRESETS[preset] if preset else {}
    saved = {k: getattr(P, k) for k in overrides}
    # Base run + sensitivity runs (interaction-answer base scaled +/- SENSITIVITY), under the preset's
    # coordination/perception overrides if one was given (restored immediately after the runs).
    try:
        for k, v in overrides.items():
            setattr(P, k, v)
        base = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE)
        lo = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE * (1 - P.SENSITIVITY))
        hi = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE * (1 + P.SENSITIVITY))
    finally:
        for k, v in saved.items():
            setattr(P, k, v)

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
    if preset:
        ov = ", ".join(f"{k}={v}" for k, v in P.POWER_PRESETS[preset].items())
        assumptions.append(f"power preset '{preset}': {ov} (pacing emerges from the decks' own clocks)")
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
class DeckMetagameStats:
    name: str
    power_rank: int          # 1 = strongest (by the learned power level — the headline ranking)
    power_level: float       # the learned metagame-knowledge prior (win_rate − 1/pod_size); >0 = above fair
    win_rate: float          # avg win rate across every pod (POLICED outcome when informed=True)
    archenemy_rate: float    # avg share of turns the deck was the table's consensus archenemy


@dataclass
class MetagameResult:
    decks: list[DeckMetagameStats]   # sorted strongest → weakest by power_level
    pod_size: int
    pods: int                        # number of distinct pods averaged over
    iterations: int                  # loop passes actually run
    converged: bool                  # True if win rates stabilized within tolerance before the cap
    informed: bool                   # True = win/archenemy are from the informed-table reporting pass


def _meta_sweep(
    by: dict[str, BattleProfile], pods: list[tuple[str, ...]], names: list[str], games: int, seed: int,
) -> tuple[dict[str, float], dict[str, float]]:
    """One full pass over every pod at the current `WINRATE_PRIOR_W`/priors → (win rates, archenemy rates)."""
    wsum = {n: 0.0 for n in names}
    aesum = {n: 0.0 for n in names}
    appear = {n: 0 for n in names}
    for pod in pods:
        res = simulate_match([by[n] for n in pod], games=games, seed=seed)
        for ds in res.decks:
            wsum[ds.name] += ds.win_rate
            aesum[ds.name] += ds.archenemy_rate
            appear[ds.name] += 1
    return ({n: wsum[n] / appear[n] for n in names}, {n: aesum[n] / appear[n] for n in names})


def simulate_metagame(
    profiles: list[BattleProfile], *, pod_size: int = 4, games: int = 2000, seed: int = 1,
    weight: float | None = None, damp: float | None = None, iterations: int | None = None,
    tol: float = 0.01, informed: bool = True, informed_weight: float | None = None,
) -> MetagameResult:
    """Self-consistent metagame via a DAMPED fictitious-play loop (Stage 3c). Each pass simulates every
    `pod_size`-deck pod over the pool, then feeds each deck's realized win rate back as its standing
    threat prior (`win_prior = win_rate − 1/pod_size`) so the table targets PROVEN winners, not the
    static pre-game power scalar. Damping prevents the undamped overshoot/oscillation. The converged
    priors are the learned **power levels** — the headline strength ranking.

    `informed=True` (the default, Stage 3d) then runs ONE reporting pass at the much stronger
    `informed_weight`, modelling a table that KNOWS those power levels and targets accordingly: the
    archenemy ranking tracks power (the strongest deck is correctly ganged up on) and win rates compress
    toward parity (the policed outcome — the 2nd/3rd under-the-radar decks inherit). `informed=False`
    reports the convergence pass's own win/archenemy instead (win rate ≈ power, archenemy still flash-led).

    Restores `WINRATE_PRIOR_W` and every profile's `win_prior` on exit, so it has no global side effects.
    """
    w = P.METAGAME_PRIOR_WEIGHT if weight is None else weight
    d = P.METAGAME_DAMP if damp is None else damp
    iters = P.METAGAME_ITERS if iterations is None else iterations
    iw = P.METAGAME_INFORMED_WEIGHT if informed_weight is None else informed_weight
    pod_size = min(pod_size, len(profiles))
    if pod_size < 2:
        raise ValueError("need at least 2 decks for a pod")
    names = [p.name for p in profiles]
    by = {p.name: p for p in profiles}
    pods = list(combinations(names, pod_size))
    fair = 1.0 / pod_size

    saved_w = P.WINRATE_PRIOR_W
    saved_priors = {p.name: p.win_prior for p in profiles}
    wr: dict[str, float] = {n: 0.0 for n in names}
    aer: dict[str, float] = {n: 0.0 for n in names}
    used = 0
    converged = False
    try:
        # Phase 1 — learn the power levels (damped fictitious play at the stable weight).
        P.WINRATE_PRIOR_W = w
        prev: dict[str, float] | None = None
        for it in range(max(1, iters)):
            used = it + 1
            wr, aer = _meta_sweep(by, pods, names, games, seed)
            for p in profiles:
                p.win_prior = d * p.win_prior + (1.0 - d) * (wr[p.name] - fair)
            if prev is not None and max(abs(wr[n] - prev[n]) for n in names) < tol:
                converged = True
                break
            prev = dict(wr)
        power = {p.name: p.win_prior for p in profiles}
        # Phase 2 — informed table: KNOW the power levels and target by them (one strong reporting pass).
        if informed:
            P.WINRATE_PRIOR_W = iw
            wr, aer = _meta_sweep(by, pods, names, games, seed)
    finally:
        P.WINRATE_PRIOR_W = saved_w
        for p in profiles:
            p.win_prior = saved_priors[p.name]

    order = sorted(names, key=lambda n: power[n], reverse=True)
    rank = {n: i + 1 for i, n in enumerate(order)}
    decks = [
        DeckMetagameStats(n, rank[n], round(power[n], 3), round(wr[n], 3), round(aer[n], 3))
        for n in order
    ]
    return MetagameResult(decks=decks, pod_size=pod_size, pods=len(pods),
                          iterations=used, converged=converged, informed=informed)


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

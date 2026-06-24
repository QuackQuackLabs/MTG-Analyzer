"""Stage 2 PROTOTYPE — searched decisions over an explicit, resumable, card-agnostic forward model.

The Stage-0/1 engine in `battle.py` makes every in-game decision by a fixed heuristic (the go-first
caution formula, the equity-gated answer check). The research synthesis
([docs/simulator-research-2026-06.md](../../../docs/simulator-research-2026-06.md)) says the strongest
imperfect-information card-game results come from **determinization + a cheap stochastic rollout**:
sample the hidden future, roll it out under a light policy, and pick the action that wins more — NOT a
hand-tuned threshold. This module is the **2.1 gate**: an explicit `BattleState` + `step` over the same
abstract resources (life, realized clock, answers-in-hand, board/grind capacity — never cards), made
*resumable* so a decision can be evaluated by rolling the rest of the game out.

It is a **prototype**, deliberately separate from the production engine: the heuristic playout
faithfully ports `battle.py`'s ranking-driving mechanics (clock race, equity-gated answers, attrition +
heat discount, archenemy reputation) so we can prove the abstract model **reproduces the Stage-1
ranking** before trusting search built on it; then `search_decide_attempt` makes the one highest-leverage
reactive decision — the go-first / hold-up commit — by determinized rollout instead of the caution knob.

NOT a rules engine (golden rule #5): the state is abstract resources only; `step` never resolves a card.
Full UCB-tree IS-MCTS is the documented next increment — this prototype uses flat determinized search
(evaluate each action by averaging K rollouts), which the literature notes is dominated by rollout
quality anyway, so it is the honest first rung.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np

from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.simulation import battle_params as P


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class BattleState:
    """The abstract, card-agnostic game state — copyable so a decision can be rolled out."""

    profiles: list[BattleProfile]  # static deck levers (shared; never mutated)
    turn: int
    life: list[float]
    game_clock: list[float]  # each deck's REALIZED kill turn this determinization
    delay: list[float]
    reserve: list[float]  # answers in hand
    sweepers: list[int]
    alive: list[bool]
    reputation: list[float]
    damage_from: list[list[float]]
    first_out: int = -1
    archenemy_turns: list[int] = field(default_factory=list)

    def copy(self) -> BattleState:
        # profiles are immutable/shared; deep-copy only the mutable per-game arrays.
        return replace(
            self,
            life=list(self.life),
            game_clock=list(self.game_clock),
            delay=list(self.delay),
            reserve=list(self.reserve),
            sweepers=list(self.sweepers),
            alive=list(self.alive),
            reputation=list(self.reputation),
            damage_from=[row[:] for row in self.damage_from],
            archenemy_turns=list(self.archenemy_turns),
        )


def initial_state(profiles: list[BattleProfile], rng: np.random.Generator) -> BattleState:
    n = len(profiles)
    game_clock = [
        max(1.0, float(rng.normal(
            p.clock_mean - min(P.TUTOR_CLOCK_SHIFT * p.tutors, P.TUTOR_CLOCK_SHIFT_CAP), p.clock_sd)))
        for p in profiles
    ]
    return BattleState(
        profiles=profiles, turn=1, life=[float(P.START_LIFE)] * n, game_clock=game_clock,
        delay=[0.0] * n, reserve=[float(p.interaction) for p in profiles],
        sweepers=[p.sweepers for p in profiles], alive=[True] * n, reputation=[0.0] * n,
        damage_from=[[0.0] * n for _ in range(n)], first_out=-1, archenemy_turns=[0] * n,
    )


# --- abstract signals (faithful ports of battle.py) -----------------------------------------------

def live_threat(st: BattleState, j: int) -> float:
    p = st.profiles[j]
    n = len(st.profiles)
    eff = st.game_clock[j] + st.delay[j]
    online = _logistic((st.turn - eff) / P.THREAT_BOARD_DEV_STEEP)
    board = P.THREAT_BOARD_W * online * (1.0 + 0.08 * p.card_advantage)
    living_life = [st.life[k] for k in range(n) if st.alive[k]]
    avg_life = sum(living_life) / len(living_life) if living_life else st.life[j]
    life_lead = P.THREAT_LIFE_W * (st.life[j] - avg_life)
    prox = max(0.0, P.THREAT_PROXIMITY_WINDOW - abs(st.turn - eff))
    combo_imminence = P.THREAT_COMBO_IMMINENCE_W * online if p.has_combo else 0.0
    return (P.THREAT_STATIC_W * p.threat_level + P.THREAT_CARDADV_W * p.card_advantage
            + board + life_lead + P.THREAT_PROXIMITY_W * prox + combo_imminence)


def perceived_threat(st: BattleState, j: int) -> float:
    base = (live_threat(st, j) * st.profiles[j].visibility
            + P.REPUTATION_W * st.reputation[j] + P.REPUTATION_STATIC_W * st.profiles[j].threat_level)
    # Stage 3b — standing-strength recognition (default off). The quiet-shark visibility discount makes
    # the table under-read a resource/inevitability-dominant control deck, so the genuinely strongest deck
    # in a pod is never ganged up on and keeps a win rate far above fair share. This adds a term that
    # draws heat to whoever is OUT-RESOURCING the field (grind-equity lead over the living mean) and
    # PARTLY bypasses the visibility discount — modelling a table that eventually recognises "that quiet
    # deck is the real threat" and coordinates against it, compressing the win-rate spread toward 1/N.
    if P.THREAT_DOMINANCE_W:
        living = [k for k in range(len(st.profiles)) if st.alive[k]]
        mean_ge = sum(grind_equity(st, k) for k in living) / len(living) if living else 0.0
        base += P.THREAT_DOMINANCE_W * max(0.0, grind_equity(st, j) - mean_ge)
    # Stage 3c — metagame-knowledge prior: the table targets off who is KNOWN to win (fed back from the
    # sim's own win rates), not the static pre-game power scalar. A positive prior (over-performer like
    # Sauron) draws standing heat even through the quiet-shark discount; a negative prior (a never-wins
    # aggro deck like Frodo) is left alone at game start. The dynamic board/proximity terms in
    # live_threat are untouched, so a low-prior deck that actually takes off mid-game still draws heat.
    base += P.WINRATE_PRIOR_W * st.profiles[j].win_prior
    return base


def grind_equity(st: BattleState, j: int) -> float:
    p = st.profiles[j]
    base = (P.GRIND_INTERACTION_W * p.interaction + P.GRIND_CARDADV_W * p.card_advantage
            + P.GRIND_RESILIENCE_W * (p.protection + max(0, p.combo_count - 1)))
    return base / (1.0 + P.GRIND_HEAT_W * st.reputation[j])


def _argmax_rng(xs: list[int], rng: np.random.Generator) -> int:
    top = max(xs)
    tied = [i for i, x in enumerate(xs) if x == top]
    return int(rng.choice(tied)) if len(tied) > 1 else tied[0]


def _assess(st: BattleState, rng: np.random.Generator) -> int:
    """Consensus archenemy for the turn (the politicking vote)."""
    n = len(st.profiles)
    tally = [0] * n
    for p in range(n):
        if not st.alive[p]:
            continue
        best, best_score = -1, -1e9
        for k in range(n):
            if k == p or not st.alive[k]:
                continue
            score = (perceived_threat(st, k) + P.DAMAGE_FEAR_W * st.damage_from[k][p]
                     + rng.normal(0.0, P.PERCEPTION_NOISE))
            if score > best_score:
                best_score, best = score, k
        if best >= 0:
            tally[best] += 1
    return _argmax_rng(tally, rng) if any(tally) else -1


def attempt_p(st: BattleState, i: int) -> float:
    """The raw (caution-adjusted) probability deck i goes for the win this turn — the quantity the
    heuristic policy thresholds and the search policy REPLACES with a rolled-out decision."""
    n = len(st.profiles)
    eff_clock = st.game_clock[i] + st.delay[i]
    p_attempt = min(P.ATTEMPT_CAP, _logistic(P.INGAME_ATTEMPT_STEEPNESS * (st.turn - eff_clock)))
    open_answers = sum(st.reserve[j] for j in range(n) if j != i and st.alive[j])
    scale = max(1.0, (sum(st.alive) - 1) * P.STANDOFF_OPEN_REF)
    caution = P.GO_FIRST_CAUTION * min(1.0, open_answers / scale)
    impatience = min(1.0, max(0.0, st.turn - eff_clock) / P.GO_FIRST_IMPATIENCE)
    return p_attempt * (1.0 - caution * (1.0 - impatience))


def _resolve_attempt(st: BattleState, i: int, archenemy: int, rng: np.random.Generator) -> int | None:
    """Deck i commits its win attempt: run the table-wide answer check; on success return the winner
    (terminal), else mutate `delay`/board and return None. A faithful port of battle.py's answer step."""
    n = len(st.profiles)
    cc = st.profiles[i].combo_clock
    combo_clock = cc if cc is not None else st.profiles[i].clock_mean
    is_combo_attempt = st.profiles[i].has_combo and st.turn >= combo_clock - P.COMBO_ONLINE_SLACK

    lethal = P.ANSWER_LETHAL_COMBO if is_combo_attempt else P.ANSWER_LETHAL_BEATDOWN
    if i == archenemy:
        lethal = min(1.0, lethal * P.ANSWER_ARCHENEMY_MULT)
    peer_eq = [max(0.0, live_threat(st, k)) for k in range(n) if st.alive[k] and k != i]
    avg_eq = sum(peer_eq) / len(peer_eq) if peer_eq else 0.0
    total_eq = sum(max(0.0, live_threat(st, k)) for k in range(n) if st.alive[k]) or 1.0
    leader = max((k for k in range(n) if st.alive[k]), key=lambda k: live_threat(st, k))

    def equity_gate(j: int) -> float:
        g = 1.0 + P.ANSWER_EQUITY_SLOPE * (max(0.0, live_threat(st, j)) - avg_eq)
        return min(P.ANSWER_EQUITY_MAX, max(P.ANSWER_EQUITY_MIN, g))

    def is_spoiler(j: int) -> bool:
        return (st.turn >= P.SPOILER_MIN_TURN and j != leader
                and max(0.0, live_threat(st, j)) / total_eq < P.SPOILER_SHARE_MAX)

    def answer_prob(j: int) -> float:
        return min(P.INTERACTION_ANSWER_MAX,
                   P.INTERACTION_ANSWER_BASE + P.INTERACTION_ANSWER_PER_PT * st.profiles[j].interaction)

    able = sorted((j for j in range(n) if j != i and st.alive[j] and st.reserve[j] >= 1.0),
                  key=lambda j: live_threat(st, j), reverse=True)
    cancel_p = (min(P.PROT_CANCEL_CAP, P.PROT_CANCEL_PER_PIECE * st.profiles[i].protection)
                if is_combo_attempt else 0.0)
    polled = able[:P.ARCHENEMY_ANSWERERS]
    # Stage 3 — grounded opponent-model coordination (CICERO-lite bystander effect). Each defender's
    # intrinsic willingness (capability × own-equity × lethal) is discounted by the EXPECTED answering
    # capacity of the OTHER polled defenders: the more the rest of the table could cover the threat, the
    # more this defender defers, so a threat everyone *could* stop sometimes resolves anyway. It depends
    # only on others (no self-referential fixed point), so it is stable where the naive version collapsed.
    intrinsic = {j: min(1.0, answer_prob(j) * equity_gate(j) * lethal) for j in polled}
    for j in polled:
        if P.GROUNDED_COORDINATION:
            others = sum(intrinsic[k] for k in polled if k != j)
            coord = 1.0 - P.FREE_RIDER_STRENGTH * _logistic((others - P.FREE_RIDER_REF) / P.FREE_RIDER_STEEP)
        else:
            coord = P.ANSWER_COORDINATION
        willing = intrinsic[j] * coord
        if i == leader and is_spoiler(j):
            willing = min(1.0, willing * P.SPOILER_ANSWER_BONUS)
        if rng.random() < willing:
            st.reserve[j] -= 1.0
            if cancel_p == 0.0 or rng.random() >= cancel_p:
                st.delay[i] += P.ANSWER_CLOCK_PENALTY
                return None  # answered
    # Unanswered.
    if is_combo_attempt:
        return i  # combo wins outright
    foes = [j for j in range(n) if j != i and st.alive[j]]
    target = max(foes, key=lambda j: (perceived_threat(st, j), -st.life[j], rng.random()))
    if st.sweepers[target] > 0 and rng.random() < P.SWEEPER_BLUNT_P:
        st.sweepers[target] -= 1
        st.delay[i] += P.SWEEPER_DELAY
        return None
    dmg = P.ALPHA_STRIKE_FRACTION * P.START_LIFE
    st.life[target] -= dmg
    st.damage_from[i][target] += dmg
    if st.life[target] <= 0:
        st.alive[target] = False
        if st.first_out == -1:
            st.first_out = target
        if sum(st.alive) == 1:
            return i
    return None


# A decision policy: given the state, the active deck i, the turn's consensus archenemy, and the rng,
# decide whether i COMMITS its win attempt this turn. The heuristic policy thresholds the caution knob;
# the search policy rolls the rest of the game out under each action and picks the better.
DecidePolicy = Callable[[BattleState, int, int, np.random.Generator], bool]


def heuristic_decide(st: BattleState, i: int, archenemy: int, rng: np.random.Generator) -> bool:
    """Stage-1 policy: commit iff a coin-flip clears the caution-adjusted attempt probability."""
    return rng.random() < attempt_p(st, i)


def step_turn(st: BattleState, rng: np.random.Generator, decide: DecidePolicy) -> tuple[int, str] | None:
    """Advance one full turn in place. Returns (winner, method) if the game ends, else None."""
    n = len(st.profiles)
    archenemy = _assess(st, rng)
    for k in range(n):
        st.reputation[k] *= P.REPUTATION_DECAY
    if archenemy >= 0:
        st.archenemy_turns[archenemy] += 1
        st.reputation[archenemy] += P.REPUTATION_BUMP

    for i in range(n):
        if not st.alive[i]:
            continue
        st.reserve[i] = min(P.INTERACTION_CAP,
                            st.reserve[i] + st.profiles[i].card_advantage * P.CARD_ADVANTAGE_REFILL)
        if not decide(st, i, archenemy, rng):
            continue
        cc = st.profiles[i].combo_clock
        combo_clock = cc if cc is not None else st.profiles[i].clock_mean
        is_combo = st.profiles[i].has_combo and st.turn >= combo_clock - P.COMBO_ONLINE_SLACK
        winner = _resolve_attempt(st, i, archenemy, rng)
        if winner is not None:
            return winner, ("combo" if is_combo else "beatdown")

    # Stage 1.1 attrition.
    if st.turn >= P.ATTRITION_MIN_TURN:
        living = [i for i in range(n) if st.alive[i]]
        if len(living) >= 2:
            eq = sorted(((grind_equity(st, i), i) for i in living), reverse=True)
            margin = eq[0][0] - sum(e for e, _ in eq) / len(eq)
            p_fire = P.ATTRITION_RATE * _logistic((margin - P.ATTRITION_MARGIN_REF) / P.ATTRITION_MARGIN_STEEP)
            if rng.random() < p_fire:
                gw = np.array([max(0.1, e) ** P.GRIND_POWER for e, _ in eq], dtype=float)
                winner = int(rng.choice([i for _, i in eq], p=gw / gw.sum()))
                return winner, "attrition"
    return None


def play_from(st: BattleState, rng: np.random.Generator, decide: DecidePolicy) -> tuple[int, int, str]:
    """Finish the game from `st.turn` under `decide`. Returns (winner, end_turn, method)."""
    while st.turn <= P.MAX_TURNS:
        out = step_turn(st, rng, decide)
        if out is not None:
            return out[0], st.turn, out[1]
        st.turn += 1
    # Inevitability tiebreak (game went long).
    living = [i for i in range(len(st.profiles)) if st.alive[i]]
    scores = np.array([max(0.1, grind_equity(st, i)) for i in living], dtype=float)
    return int(rng.choice(living, p=scores / scores.sum())), P.MAX_TURNS, "inevitability"


def make_search_decide(determinizations: int, rollout_seed_rng: np.random.Generator) -> DecidePolicy:
    """A decision policy that REPLACES the go-first caution coin-flip with determinized lookahead: for
    the active deck, roll the rest of the game out K times under COMMIT vs WAIT and commit only if doing
    so wins more often. This is the research's determinization + cheap-rollout in its simplest (flat)
    form — the hold-up / go-first decision becomes searched, not a tuned threshold."""

    def decide(st: BattleState, i: int, archenemy: int, rng: np.random.Generator) -> bool:
        # Only the decks actually near their clock face a real decision; far-from-clock decks pass
        # cheaply (matches the heuristic, and keeps search cost focused on live decisions).
        if attempt_p(st, i) < 0.02:
            return False
        commit_wins = wait_wins = 0
        for _ in range(determinizations):
            # COMMIT: resolve i's attempt on a copy now, then play out heuristically.
            sc = st.copy()
            r1 = np.random.default_rng(int(rollout_seed_rng.integers(0, 2**63 - 1)))
            w = _resolve_attempt(sc, i, archenemy, r1)
            if w is None:
                sc.turn += 1
                w, _, _ = play_from(sc, r1, heuristic_decide)
            if w == i:
                commit_wins += 1
            # WAIT: skip i this turn, play out heuristically.
            sw = st.copy()
            r2 = np.random.default_rng(int(rollout_seed_rng.integers(0, 2**63 - 1)))
            sw.turn += 1
            w2, _, _ = play_from(sw, r2, heuristic_decide)
            if w2 == i:
                wait_wins += 1
        return commit_wins >= wait_wins

    return decide


def simulate_match_search(
    profiles: list[BattleProfile], *, games: int = 800, seed: int = 1, determinizations: int = 12
) -> dict[str, float]:
    """Run `games` matches choosing the win-attempt commit by determinized search; return win rates."""
    n = len(profiles)
    rng = np.random.default_rng(seed)
    wins = [0] * n
    for _ in range(games):
        st = initial_state(profiles, rng)
        decide = make_search_decide(determinizations, rng)
        w, _, _ = play_from(st, rng, decide)
        wins[w] += 1
    return {profiles[i].name: wins[i] / games for i in range(n)}


def simulate_match_heuristic(
    profiles: list[BattleProfile], *, games: int = 800, seed: int = 1
) -> dict[str, float]:
    """Same engine, heuristic policy — the 2.1 reproduction baseline (should match Stage-1 ranking)."""
    n = len(profiles)
    rng = np.random.default_rng(seed)
    wins = [0] * n
    for _ in range(games):
        st = initial_state(profiles, rng)
        w, _, _ = play_from(st, rng, heuristic_decide)
        wins[w] += 1
    return {profiles[i].name: wins[i] / games for i in range(n)}

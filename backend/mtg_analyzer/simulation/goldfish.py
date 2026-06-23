"""Monte-Carlo goldfish simulator (no opponent) for deck consistency metrics.

Deliberately simple and honestly approximate (see notes in SimResult):
  * Mana is modeled as a single pool (1 per land + 1 per ramp permanent); colored-mana
    requirements and utility lands that don't tap for mana are NOT modeled.
  * Ramp helps from the *next* turn (conservative); rituals are treated like rocks.
  * London mulligan with a simple "keep 2–5 lands" policy.

It gives reliable *relative* consistency (keep%, screw rate, turn-to-commander) and pairs
with the exact hypergeometric land odds. Engine (draw/turn loop) is separate from policy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mtg_analyzer.analysis.categorize import RAMP, TUTOR, categorize
from mtg_analyzer.models.combo import Combo
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.simulation import CommanderTurnStats, SimResult
from mtg_analyzer.simulation import probability


@dataclass
class DeckProfile:
    is_land: np.ndarray  # bool[N]
    is_ramp: np.ndarray  # bool[N] (nonland mana sources)
    is_tutor: np.ndarray  # bool[N] (a tutor can stand in for a missing combo piece)
    cmc: np.ndarray  # int[N]
    oracle_ids: list[str]  # parallel to the arrays: each card-copy's oracle_id
    commander_cmc: int | None

    @property
    def size(self) -> int:
        return int(self.is_land.size)

    @property
    def land_count(self) -> int:
        return int(self.is_land.sum())

    @property
    def ramp_count(self) -> int:
        return int(self.is_ramp.sum())

    @classmethod
    def from_resolved(cls, deck: ResolvedDeck) -> DeckProfile:
        is_land: list[bool] = []
        is_ramp: list[bool] = []
        is_tutor: list[bool] = []
        cmc: list[int] = []
        oracle_ids: list[str] = []
        for e in deck.mainboard:
            if e.card is None:
                continue
            land = "land" in (e.card.type_line or "").lower()
            cats = categorize(e.card)
            for _ in range(e.quantity):
                is_land.append(land)
                is_ramp.append((not land) and (RAMP in cats))
                is_tutor.append(TUTOR in cats)
                cmc.append(int(e.card.cmc))
                oracle_ids.append(e.card.oracle_id or "")
        cmds = [e.card.cmc for e in deck.commanders if e.card]
        commander_cmc = int(min(cmds)) if cmds else None
        return cls(np.array(is_land, dtype=bool), np.array(is_ramp, dtype=bool),
                   np.array(is_tutor, dtype=bool), np.array(cmc, dtype=int),
                   oracle_ids, commander_cmc)


@dataclass
class ComboSpec:
    """A combo compiled for assembly tracking: the non-commander piece oracle_ids that must be
    drawn (or tutored), whether a commander piece is required, and the most expensive single
    piece's CMC (the mana gate — cheaper pieces are deployed on earlier turns)."""

    piece_oracles: frozenset[str]
    needs_commander: bool
    max_piece_cmc: int


def _compile_combos(
    deck: ResolvedDeck, combos: list[Combo], commander_cmc: int | None
) -> list[ComboSpec]:
    """Turn detected combos into assembly specs. Commander pieces start in the command zone, so
    they're not 'drawn'; generic `requires` templates are treated as already-satisfied (the
    analyzer only reports combos whose templates the deck can meet)."""
    cmc_by_oracle: dict[str, int] = {}
    for e in deck.mainboard:
        if e.card and e.card.oracle_id:
            cmc_by_oracle[e.card.oracle_id] = int(e.card.cmc)

    specs: list[ComboSpec] = []
    for combo in combos:
        pieces: set[str] = set()
        needs_cmd = False
        cmcs: list[int] = []
        for use in combo.uses:
            if use.must_be_commander:
                needs_cmd = True
                cmcs.append(commander_cmc or 0)
            elif use.oracle_id:
                pieces.add(use.oracle_id)
                cmcs.append(cmc_by_oracle.get(use.oracle_id, 0))
        specs.append(ComboSpec(frozenset(pieces), needs_cmd, max(cmcs, default=0)))
    return specs


def simulate(
    deck: ResolvedDeck,
    *,
    combos: list[Combo] | None = None,
    games: int = 10_000,
    seed: int = 0,
    on_play: bool = True,
    max_turns: int = 15,
    keep_min: int = 2,
    keep_max: int = 5,
    max_mulligans: int = 3,
) -> SimResult:
    profile = DeckProfile.from_resolved(deck)
    n = profile.size
    rng = np.random.default_rng(seed)
    notes: list[str] = []
    if n < 50:
        notes.append(f"Only {n} mainboard cards resolved — results are rough.")
    specs = _compile_combos(deck, combos, profile.commander_cmc) if combos else []

    opening_lands = np.empty(games, dtype=int)
    mulls = np.empty(games, dtype=int)
    screwed = np.zeros(games, dtype=bool)
    commander_turns: list[int] = []
    combo_turns: list[int] = []
    never = 0
    combo_never = 0

    for g in range(games):
        order = rng.permutation(n)
        # Record the *first* 7 (before any mulligan) for opening-hand stats.
        opening_lands[g] = int(profile.is_land[order[:7]].sum())
        m = 0
        while m < max_mulligans:
            if keep_min <= profile.is_land[order[:7]].sum() <= keep_max:
                break
            order = rng.permutation(n)
            m += 1
        mulls[g] = m

        out = _play_out(profile, specs, order, m, on_play, max_turns)
        screwed[g] = out.screw_t3
        if out.commander_turn is None:
            never += 1
        else:
            commander_turns.append(out.commander_turn)
        if specs:
            if out.combo_turn is None:
                combo_never += 1
            else:
                combo_turns.append(out.combo_turn)

    ct_stats = _turn_stats(commander_turns, never, games) if profile.commander_cmc is not None else None
    combo_stats = _turn_stats(combo_turns, combo_never, games) if specs else None

    return SimResult(
        games=games, on_play=on_play, land_count=profile.land_count,
        ramp_count=profile.ramp_count, commander_cmc=profile.commander_cmc,
        avg_lands_in_opening=round(float(opening_lands.mean()), 2),
        p_keepable_hand=round(float(((opening_lands >= keep_min) & (opening_lands <= keep_max))
                                    .mean()), 3),
        p_three_plus_lands_exact=round(probability.p_at_least(profile.land_count, 7, 3,
                                                              deck_size=n), 3),
        avg_mulligans=round(float(mulls.mean()), 2),
        flood_rate=round(float((opening_lands >= 6).mean()), 3),
        screw_rate=round(float(screwed.mean()), 3),
        commander_turn=ct_stats, combo_turn=combo_stats, combo_count=len(specs), notes=notes,
    )


def _turn_stats(turns: list[int], never: int, games: int) -> CommanderTurnStats:
    arr = np.array(turns) if turns else np.array([])
    return CommanderTurnStats(
        mean=round(float(arr.mean()), 2) if arr.size else None,
        median=int(np.median(arr)) if arr.size else None,
        p90=int(np.percentile(arr, 90)) if arr.size else None,
        never_pct=round(never / games * 100, 1),
    )


@dataclass
class _PlayOut:
    commander_turn: int | None
    combo_turn: int | None
    screw_t3: bool


def _play_out(
    profile: DeckProfile, specs: list[ComboSpec], order: np.ndarray, mulligans: int,
    on_play: bool, max_turns: int
) -> _PlayOut:
    """Play one goldfish game; return turn-to-commander, turn-to-combo, and the screw flag."""
    hand = list(order[:7])
    draw_pile = list(order[7:])
    # London: bottom one card per mulligan — prefer dumping surplus lands, else a nonland.
    for _ in range(mulligans):
        if not hand:
            break
        lands = [i for i in hand if profile.is_land[i]]
        drop = lands[-1] if len(lands) > 3 else hand[-1]
        hand.remove(drop)
        draw_pile.append(drop)

    seen: set[str] = {profile.oracle_ids[i] for i in hand}  # oracle_ids that have entered hand
    tutors_seen = sum(1 for i in hand if profile.is_tutor[i])
    lands_in_play = 0
    ramp_mana = 0
    commander_turn: int | None = None
    combo_turn: int | None = None
    screw_t3 = False

    for turn in range(1, max_turns + 1):
        if not (on_play and turn == 1) and draw_pile:
            drawn = draw_pile.pop(0)
            hand.append(drawn)
            seen.add(profile.oracle_ids[drawn])
            if profile.is_tutor[drawn]:
                tutors_seen += 1

        land = next((i for i in hand if profile.is_land[i]), None)
        if land is not None:
            hand.remove(land)
            lands_in_play += 1

        mana = lands_in_play + ramp_mana  # available this turn (ramp helps from next turn)

        # Deploy affordable ramp (cheapest first); it accelerates future turns.
        spend = mana
        for i in sorted([c for c in hand if profile.is_ramp[c]], key=lambda i: profile.cmc[i]):
            if profile.cmc[i] <= spend:
                spend -= int(profile.cmc[i])
                ramp_mana += 1
                hand.remove(i)

        if (profile.commander_cmc is not None and commander_turn is None
                and mana >= profile.commander_cmc):
            commander_turn = turn
        if combo_turn is None and specs and _combo_ready(specs, seen, tutors_seen, mana, commander_turn):
            combo_turn = turn
        if turn == 3:
            screw_t3 = lands_in_play < 2

    return _PlayOut(commander_turn=commander_turn, combo_turn=combo_turn, screw_t3=screw_t3)


def _combo_ready(
    specs: list[ComboSpec], seen: set[str], tutors: int, mana: int, commander_turn: int | None
) -> bool:
    """True if ANY combo is assemblable now: its non-commander pieces are drawn (tutors covering
    the gap), its commander piece (if any) is castable, and there's mana for the priciest piece
    (cheaper pieces deployed on earlier turns). Drawing the pieces is the real bottleneck."""
    for spec in specs:
        if spec.needs_commander and commander_turn is None:
            continue
        missing = len(spec.piece_oracles - seen)
        if missing <= tutors and mana >= spec.max_piece_cmc:
            return True
    return False

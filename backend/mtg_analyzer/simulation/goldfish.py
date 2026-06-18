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

from mtg_analyzer.analysis.categorize import RAMP, categorize
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.simulation import CommanderTurnStats, SimResult
from mtg_analyzer.simulation import probability


@dataclass
class DeckProfile:
    is_land: np.ndarray  # bool[N]
    is_ramp: np.ndarray  # bool[N] (nonland mana sources)
    cmc: np.ndarray  # int[N]
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
        cmc: list[int] = []
        for e in deck.mainboard:
            if e.card is None:
                continue
            land = "land" in (e.card.type_line or "").lower()
            ramp = (not land) and (RAMP in categorize(e.card))
            for _ in range(e.quantity):
                is_land.append(land)
                is_ramp.append(ramp)
                cmc.append(int(e.card.cmc))
        cmds = [e.card.cmc for e in deck.commanders if e.card]
        commander_cmc = int(min(cmds)) if cmds else None
        return cls(np.array(is_land, dtype=bool), np.array(is_ramp, dtype=bool),
                   np.array(cmc, dtype=int), commander_cmc)


def simulate(
    deck: ResolvedDeck,
    *,
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

    opening_lands = np.empty(games, dtype=int)
    mulls = np.empty(games, dtype=int)
    screwed = np.zeros(games, dtype=bool)
    commander_turns: list[int] = []
    never = 0

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

        cturn = _play_out(profile, order, m, on_play, max_turns)
        screwed[g] = cturn.screw_t3
        if cturn.commander_turn is None:
            never += 1
        else:
            commander_turns.append(cturn.commander_turn)

    ct_stats: CommanderTurnStats | None = None
    if profile.commander_cmc is not None:
        arr = np.array(commander_turns) if commander_turns else np.array([])
        ct_stats = CommanderTurnStats(
            mean=round(float(arr.mean()), 2) if arr.size else None,
            median=int(np.median(arr)) if arr.size else None,
            p90=int(np.percentile(arr, 90)) if arr.size else None,
            never_pct=round(never / games * 100, 1),
        )

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
        commander_turn=ct_stats, notes=notes,
    )


@dataclass
class _PlayOut:
    commander_turn: int | None
    screw_t3: bool


def _play_out(
    profile: DeckProfile, order: np.ndarray, mulligans: int, on_play: bool, max_turns: int
) -> _PlayOut:
    """Play one goldfish game; return the turn the commander becomes castable + screw flag."""
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

    lands_in_play = 0
    ramp_mana = 0
    commander_turn: int | None = None
    screw_t3 = False

    for turn in range(1, max_turns + 1):
        if not (on_play and turn == 1) and draw_pile:
            hand.append(draw_pile.pop(0))

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
        if turn == 3:
            screw_t3 = lands_in_play < 2

    return _PlayOut(commander_turn=commander_turn, screw_t3=screw_t3)

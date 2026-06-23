"""Models for the heuristic battle/matchup simulator (Phase 9).

A `BattleProfile` abstracts a deck to the few levers that decide a game's *dynamics* —
clock, interaction, card advantage, combo potential, threat — all derived from signals we
already compute (DeckReport + SimResult). The simulator is NOT a rules engine; see
docs/battle-simulator-design.md.
"""

from __future__ import annotations

from pydantic import BaseModel


class BattleProfile(BaseModel):
    name: str
    archetype: str  # combo | aggro | midrange | control | grind
    clock_mean: float  # ~turn the deck can win, goldfishing
    clock_sd: float
    interaction: int  # answer budget = counters + spot removal
    sweepers: int  # board wipes
    card_advantage: int  # draw-engine density (refuels interaction/threats)
    has_combo: bool
    combo_count: int = 0  # number of distinct combos (redundancy; from the goldfish combo scan)
    tutors: int
    threat_level: float  # 0..~10 scalar for target/answer focusing
    notes: list[str] = []


class DeckWinStats(BaseModel):
    name: str
    win_rate: float  # point estimate (fraction of games)
    win_rate_low: float  # sensitivity band (interaction assumption +/-)
    win_rate_high: float
    avg_win_turn: float | None
    methods: dict[str, float]  # win method -> fraction of THIS deck's wins
    archenemy_rate: float  # 4-player: avg share of turns this deck was the table's consensus archenemy
    died_first_rate: float  # multiplayer: fraction of games eliminated first
    # Explainability — how much interaction/politics reshaped raw goldfish speed.
    clock_mean: float  # the raw-speed input that drives clock_rank (lower = faster)
    clock_rank: int  # 1 = fastest clock at the table
    equity_rank: int  # 1 = highest win rate
    rank_shift: int  # clock_rank − equity_rank: + = finished above its speed, − = punished for it
    explain: str  # one-line attribution (clock→equity, politics pressure, dominant win method)


class MatchResult(BaseModel):
    players: int
    games: int
    decks: list[DeckWinStats]
    avg_game_length: float  # avg turn the game ended
    assumptions: list[str]
    notes: list[str]

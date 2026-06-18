"""Models for goldfish simulation results."""

from __future__ import annotations

from pydantic import BaseModel


class CommanderTurnStats(BaseModel):
    mean: float | None
    median: int | None
    p90: int | None  # 90% of games cast the commander by this turn
    never_pct: float  # % of games that couldn't cast it within the simulated turns


class SimResult(BaseModel):
    games: int
    on_play: bool
    land_count: int
    ramp_count: int
    commander_cmc: int | None

    avg_lands_in_opening: float
    p_keepable_hand: float  # fraction of opening 7s with 2–5 lands
    p_three_plus_lands_exact: float  # hypergeometric P(>=3 lands in 7)
    avg_mulligans: float
    flood_rate: float  # opening 7 with >=6 lands
    screw_rate: float  # < 2 lands in play through turn 3

    commander_turn: CommanderTurnStats | None
    notes: list[str]

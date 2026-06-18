"""Models for deck upgrade recommendations (cuts, adds, and a shopping list)."""

from __future__ import annotations

from pydantic import BaseModel


class AddSuggestion(BaseModel):
    name: str
    oracle_id: str | None = None
    category: str | None = None  # which gap it fills (ramp/draw/removal/board_wipe/…)
    synergy: float | None = None  # EDHREC synergy (commander-specific fit)
    inclusion_rate: float | None = None  # fraction of this commander's decks that run it
    price_usd: float | None = None
    owned: bool = False
    reason: str = ""


class CutSuggestion(BaseModel):
    name: str
    oracle_id: str | None = None
    inclusion_rate: float | None = None  # play-rate in this commander's decks (None = below cutoff)
    reason: str = ""


class Recommendations(BaseModel):
    commander: str
    adds: list[AddSuggestion]
    cuts: list[CutSuggestion]
    buy_cost: float  # total USD for not-owned adds
    notes: list[str]

"""Models for a constructed deck (Phase 6: build from inventory + buy list)."""

from __future__ import annotations

from pydantic import BaseModel


class BuildCard(BaseModel):
    name: str
    quantity: int = 1
    category: str | None = None  # land / ramp / draw / removal / board_wipe / payoff
    owned: bool = False
    price_usd: float | None = None


class BuiltDeck(BaseModel):
    commander: str
    identity: str
    cards: list[BuildCard]  # the 99 (includes lands + basics)
    total_cards: int  # commander + 99
    owned_count: int  # owned cards used (excl. basics)
    buy_count: int
    buy_cost: float
    category_counts: dict[str, int]
    notes: list[str]

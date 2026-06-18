"""Models for a deck analysis report (validation + composition + curve + bracket)."""

from __future__ import annotations

from pydantic import BaseModel


class Validation(BaseModel):
    legal: bool
    card_count: int  # commander(s) + mainboard, summed by quantity
    commander_identity: str  # e.g. "BGUW" ("C" if colorless)
    issues: list[str]  # human-readable rule violations (empty when legal)
    warnings: list[str]  # non-fatal notes (unresolved cards, no commander, companion, …)


class CategoryCount(BaseModel):
    category: str
    count: int
    target: int
    gap: int  # max(0, target - count)


class CurveBucket(BaseModel):
    cmc: int  # 7 means "7+"
    count: int


class DeckReport(BaseModel):
    name: str | None
    commanders: list[str]
    identity: str
    validation: Validation
    categories: list[CategoryCount]
    curve: list[CurveBucket]
    game_changers: list[str]
    bracket_estimate: int  # 1–5 (approximate; refined by combo data in Phase 4)
    bracket_rationale: str

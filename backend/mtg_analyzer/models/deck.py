"""Models for parsed and resolved decklists.

A decklist is parsed into raw `DeckEntry` lines, then *resolved* against the local
card DB to attach the real `Card` (gameplay identity). Resolution is by name
(reliable, offline); the `(SET) #` suffix is kept for reference/printing display but
gameplay identity comes from the card name → oracle_id.
"""

from __future__ import annotations

from pydantic import BaseModel

from mtg_analyzer.models.card import Card

# Decklist sections. "main" is the 99 (plus the commander, which is called out separately).
SECTIONS = frozenset({"main", "commander", "sideboard", "maybeboard", "companion"})


class DeckEntry(BaseModel):
    """One raw decklist line before resolution."""

    quantity: int = 1
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    section: str = "main"
    category: str | None = None  # raw Archidekt category tag, if present


class ParsedDeck(BaseModel):
    name: str | None = None
    source_format: str | None = None  # "archidekt" | "arena" | "plain" | ...
    entries: list[DeckEntry]


class ResolvedEntry(BaseModel):
    quantity: int
    section: str
    requested_name: str
    card: Card | None = None  # None when the name couldn't be resolved

    @property
    def resolved(self) -> bool:
        return self.card is not None


class ResolvedDeck(BaseModel):
    name: str | None = None
    entries: list[ResolvedEntry]

    @property
    def commanders(self) -> list[ResolvedEntry]:
        return [e for e in self.entries if e.section == "commander"]

    @property
    def mainboard(self) -> list[ResolvedEntry]:
        return [e for e in self.entries if e.section == "main"]

    @property
    def unresolved(self) -> list[ResolvedEntry]:
        return [e for e in self.entries if not e.resolved]

    def card_total(self, sections: tuple[str, ...] = ("commander", "main")) -> int:
        """Total card count (sum of quantities) across the given sections."""
        return sum(e.quantity for e in self.entries if e.section in sections)

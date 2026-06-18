"""Models for rules / interaction Q&A.

These gather *grounded source material* (card text, official rulings, Comprehensive
Rules sections, glossary, combos) for a card or interaction. The actual natural-language
answer is synthesized from this material (by Claude, in chat) — the engine's job is to
retrieve the authoritative grounding so answers are never made up.
"""

from __future__ import annotations

from pydantic import BaseModel

from mtg_analyzer.models.rules import GlossaryEntry, Rule


class Ruling(BaseModel):
    source: str
    published_at: str
    comment: str


class CardKnowledge(BaseModel):
    name: str
    type_line: str | None
    text: str
    keywords: list[str]
    rulings: list[Ruling]
    rules: list[Rule]  # CR rules relevant to the card's keywords
    glossary: list[GlossaryEntry]
    combos: list[str]  # combos involving this card (filled by the caller; needs network)


class RulesSearch(BaseModel):
    query: str
    rules: list[Rule]
    glossary: list[GlossaryEntry]


class Interaction(BaseModel):
    cards: list[CardKnowledge]
    rules: list[Rule]  # rules relevant to the combined keywords
    glossary: list[GlossaryEntry]
    combos: list[str]  # combos formed by these cards (filled by the caller)
    notes: list[str]

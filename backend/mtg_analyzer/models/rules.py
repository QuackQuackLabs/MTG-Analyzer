"""Domain models for the Comprehensive Rules corpus."""

from __future__ import annotations

from pydantic import BaseModel


class Rule(BaseModel):
    """A single entry from the Comprehensive Rules.

    ``kind`` distinguishes structural headers from actual rules:
      * ``section``  — e.g. number="1",      text="Game Concepts"
      * ``category`` — e.g. number="100",    text="General"
      * ``rule``     — e.g. number="100.1",  text="These Magic rules apply to…"
                       or  number="100.1a", text="A two-player game is…"
    """

    number: str
    kind: str  # "section" | "category" | "rule"
    text: str
    section: str | None = None  # owning section number, e.g. "1"
    parent: str | None = None  # owning rule/category, e.g. "100" or "100.1"


class GlossaryEntry(BaseModel):
    term: str
    definition: str


class RulesDocument(BaseModel):
    """A parsed Comprehensive Rules file."""

    effective_date: str | None  # human text, e.g. "February 27, 2026"
    rules: list[Rule]
    glossary: list[GlossaryEntry]

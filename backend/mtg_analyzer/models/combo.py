"""Domain models for Commander Spellbook combos ("variants").

A combo is built from specific cards (``uses``) plus optional generic card
templates (``requires``, e.g. "a permanent that can be cast using {C}") and
produces one or more results (``produces``, e.g. "Infinite colorless mana").
Cards carry their Scryfall ``oracle_id`` so combos join to our card DB.

These models keep only the fields we need; ``Combo.from_api`` trims the large
Commander Spellbook variant object (which also carries per-card image URLs etc.).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ComboCard(BaseModel):
    oracle_id: str | None
    name: str
    must_be_commander: bool = False

    @classmethod
    def from_api(cls, entry: dict[str, Any]) -> ComboCard:
        card = entry.get("card", {})
        return cls(
            oracle_id=card.get("oracleId"),
            name=card.get("name", ""),
            must_be_commander=bool(entry.get("mustBeCommander", False)),
        )


class ComboTemplate(BaseModel):
    """A generic requirement satisfied by any card matching a Scryfall query."""

    name: str
    scryfall_query: str | None = None

    @classmethod
    def from_api(cls, entry: dict[str, Any]) -> ComboTemplate:
        tpl = entry.get("template", {})
        return cls(name=tpl.get("name", ""), scryfall_query=tpl.get("scryfallQuery"))


class Combo(BaseModel):
    id: str
    produces: list[str]  # feature names, e.g. ["Infinite colorless mana"]
    identity: str  # color identity, e.g. "WUG" or "C"
    uses: list[ComboCard]
    requires: list[ComboTemplate]
    mana_needed: str = ""
    description: str = ""
    prerequisites: str = ""
    popularity: int | None = None
    bracket_tag: str | None = None
    status: str = ""
    commander_legal: bool = False
    prices: dict[str, str | None] = {}

    @classmethod
    def from_api(cls, v: dict[str, Any]) -> Combo:
        prereq = " ".join(
            p for p in (v.get("easyPrerequisites"), v.get("notablePrerequisites")) if p
        ).strip()
        return cls(
            id=str(v["id"]),
            produces=[p["feature"]["name"] for p in v.get("produces", []) if p.get("feature")],
            identity=v.get("identity", ""),
            uses=[ComboCard.from_api(u) for u in v.get("uses", [])],
            requires=[ComboTemplate.from_api(r) for r in v.get("requires", [])],
            mana_needed=v.get("manaNeeded", "") or "",
            description=v.get("description", "") or "",
            prerequisites=prereq,
            popularity=v.get("popularity"),
            bracket_tag=v.get("bracketTag"),
            status=v.get("status", "") or "",
            commander_legal=bool((v.get("legalities") or {}).get("commander", False)),
            prices=v.get("prices", {}) or {},
        )

    def use_oracle_ids(self) -> set[str]:
        return {c.oracle_id for c in self.uses if c.oracle_id}


class DeckCombos(BaseModel):
    """Result of analyzing a decklist for combos (mirrors find-my-combos buckets)."""

    identity: str = ""
    included: list[Combo] = []
    almost_included: list[Combo] = []  # one card short
    included_by_changing_commanders: list[Combo] = []
    almost_included_by_adding_colors: list[Combo] = []

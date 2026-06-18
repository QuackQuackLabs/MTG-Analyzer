"""Classify a card into functional categories for deck-composition analysis.

Heuristic, in priority order: explicit hint (e.g. an Archidekt category) → type line →
oracle-text regex. A card can have several categories (a card that draws and ramps).
This is intentionally a v1 — good enough for gap analysis; Phase 3 can later swap in
Scryfall Tagger `otag:` data for higher precision (see the mtg-data-ecosystem skill).
"""

from __future__ import annotations

import re

from mtg_analyzer.models.card import Card

# Template categories we score against (see commander-format skill for targets).
LAND = "land"
RAMP = "ramp"
DRAW = "draw"
REMOVAL = "removal"
BOARD_WIPE = "board_wipe"
TUTOR = "tutor"
COUNTER = "counterspell"

# Map common Archidekt/Moxfield category tags to our canonical categories.
_HINT_MAP = {
    "land": LAND, "lands": LAND, "ramp": RAMP, "mana": RAMP, "rocks": RAMP, "dork": RAMP,
    "draw": DRAW, "card draw": DRAW, "card advantage": DRAW, "cantrip": DRAW,
    "removal": REMOVAL, "spot removal": REMOVAL, "interaction": REMOVAL, "burn": REMOVAL,
    "board wipe": BOARD_WIPE, "boardwipe": BOARD_WIPE, "wipe": BOARD_WIPE, "wrath": BOARD_WIPE,
    "tutor": TUTOR, "tutors": TUTOR, "counter": COUNTER, "counterspell": COUNTER,
}

# Mana production: "add {C}{C}", "add one mana of any color", "add two mana", "add {G}", …
_RE_ADD_MANA = re.compile(r"\badd\b[^.\n]{0,30}?(mana|\{[wubrgcs])", re.S)
_RE_RAMP_LAND = re.compile(r"search your library for .{0,40}land", re.S)
_RE_DRAW = re.compile(r"draw [a-z]+ cards?|draws? (a|two|three|x) card", re.S)
_RE_REMOVAL = re.compile(
    r"(destroy|exile) target|deals? \d+ damage to (target|any target)|"
    r"target (creature|permanent) gets [-−]", re.S
)
_RE_WIPE = re.compile(
    r"destroy all|exile all|destroy each|all creatures get [-−]|"
    r"each player sacrifices|destroy the rest", re.S
)
_RE_TUTOR = re.compile(r"search your library for (a|an|up to|two|three|that)", re.S)
_RE_COUNTER = re.compile(r"counter target", re.S)


def categorize(card: Card, hint: str | None = None) -> set[str]:
    cats: set[str] = set()
    type_line = (card.type_line or "").lower()
    text = card.get_oracle_text().lower()

    if hint and (mapped := _HINT_MAP.get(hint.strip().lower())):
        cats.add(mapped)

    if "land" in type_line:
        cats.add(LAND)
        return cats  # lands aren't also counted as ramp/draw/etc.

    # Mana rocks/dorks, rituals, and land ramp. (Lands already returned above.)
    if _RE_ADD_MANA.search(text) or _RE_RAMP_LAND.search(text):
        cats.add(RAMP)
    if _RE_DRAW.search(text):
        cats.add(DRAW)
    if _RE_COUNTER.search(text):
        cats.add(COUNTER)
    if _RE_WIPE.search(text):
        cats.add(BOARD_WIPE)
    elif _RE_REMOVAL.search(text):
        cats.add(REMOVAL)
    # A non-land tutor that fetches a card (land tutors already counted as ramp).
    if _RE_TUTOR.search(text) and not _RE_RAMP_LAND.search(text):
        cats.add(TUTOR)
    return cats

"""Parse decklist text from Archidekt / Moxfield / MTGA / MTGO / plain exports.

Handles one tolerant line grammar:  ``[SB:] <qty>[x] <name> [(SET) [num]] [*F*] [[Category]]``
plus section headers (Deck/Commander/Sideboard/Companion/Maybeboard), ``//``/``#``
comments, and blank lines. The commander is taken from a Commander section header or
an Archidekt ``[Commander]`` category tag.

Gameplay identity comes from the card *name* (resolved later); the ``(SET) #`` suffix
is captured for reference only. See the mtg-data-ecosystem skill for format details.
"""

from __future__ import annotations

import re

from mtg_analyzer.models.deck import DeckEntry, ParsedDeck

_HEADER_TO_SECTION = {
    "deck": "main", "mainboard": "main", "main": "main", "maindeck": "main",
    "commander": "commander", "commanders": "commander",
    "sideboard": "sideboard", "companion": "companion",
    "maybeboard": "maybeboard", "maybe board": "maybeboard",
}
_IGNORE_HEADERS = {"about", "tokens", "token"}

_QTY_RE = re.compile(r"^(\d+)\s*[xX]?\s+(.*)$")
_CATEGORY_RE = re.compile(r"\s*\[([^\]]*)\]\s*$")  # Archidekt trailing [Category]
_FOIL_RE = re.compile(r"\s*\*[A-Za-z]\*\s*$")  # Moxfield *F* / *E*
# Trailing "(SET) [collector]" — set code is short and space-free, so a card name with
# parentheses and spaces (e.g. "Erase (Not the Urza's Legacy One)") is NOT misparsed.
_SET_RE = re.compile(r"\s*\(([0-9A-Za-z]{1,6})\)\s*([0-9A-Za-z★\-]+)?\s*$")


def parse_decklist(text: str) -> ParsedDeck:
    entries: list[DeckEntry] = []
    section = "main"
    saw_category = saw_foil = saw_set = False

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue

        header = line.rstrip(":").lower()
        if header in _HEADER_TO_SECTION:
            section = _HEADER_TO_SECTION[header]
            continue
        if header in _IGNORE_HEADERS:
            continue

        sideboard = False
        if line.lower().startswith("sb:"):
            sideboard = True
            line = line[3:].strip()

        m = _QTY_RE.match(line)
        if not m:
            continue  # not a card line (stray metadata/title) — skip
        quantity, rest = int(m.group(1)), m.group(2).strip()

        category: str | None = None
        if cm := _CATEGORY_RE.search(rest):
            category = cm.group(1).strip()
            rest = rest[: cm.start()].strip()
            saw_category = True
        if _FOIL_RE.search(rest):
            rest = _FOIL_RE.sub("", rest).strip()
            saw_foil = True
        set_code = collector = None
        if sm := _SET_RE.search(rest):
            set_code, collector = sm.group(1), sm.group(2)
            rest = rest[: sm.start()].strip()
            saw_set = True

        name = rest
        if not name:
            continue

        entry_section = section
        if sideboard:
            entry_section = "sideboard"
        elif category and "commander" in category.lower():
            entry_section = "commander"

        entries.append(DeckEntry(quantity=quantity, name=name, set_code=set_code,
                                 collector_number=collector, section=entry_section,
                                 category=category))

    source = (
        "archidekt" if saw_category
        else "moxfield" if saw_foil
        else "arena" if saw_set
        else "plain"
    )
    return ParsedDeck(entries=entries, source_format=source)

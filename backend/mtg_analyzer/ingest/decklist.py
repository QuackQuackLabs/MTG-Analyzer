"""Parse decklist text from Archidekt / Moxfield / MTGA / MTGO / plain exports.

Handles one tolerant line grammar:  ``[SB:] <qty>[x] <name> [(SET) [num]] [*F*] [[Category]]``
plus section headers (Deck/Commander/Sideboard/Companion/Maybeboard), ``//``/``#``
comments, and blank lines. The commander is taken from a Commander section header or
an Archidekt ``[Commander]`` category tag.

Gameplay identity comes from the card *name* (resolved later); the ``(SET) #`` suffix
is captured for reference only. See the mtg-data-ecosystem skill for format details.
"""

from __future__ import annotations

import csv
import io
import re

from mtg_analyzer.ingest.inventory import fix_mojibake
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
        if not line:
            # A blank line ends a (short) commander block — ManaBox writes
            # "// COMMANDER", the commander, a blank line, then the unmarked mainboard.
            if section == "commander":
                section = "main"
            continue

        # Comment OR a comment-style section marker (ManaBox uses "// COMMANDER" etc.).
        if line.startswith(("//", "#")):
            marker = line.lstrip("/#").strip().rstrip(":").lower()
            if marker in _HEADER_TO_SECTION:
                section = _HEADER_TO_SECTION[marker]
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

        name = fix_mojibake(rest)
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


# --- Archidekt CSV deck export --------------------------------------------
# Headerless, positional. Column layout observed from real exports:
#   0 qty · 1 name · 2 set name · 3 set code · 4 category · 5 label · 6 deck-section
#   · 7 finish · 8 collector# · 9 modifier · 10 color · 11 mv · 12 rarity
#   · 13 Scryfall id · 14 type · 15 price · 16 ownership · 17 oracle text
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-", re.ASCII)
_ARCHIDEKT_MIN_COLS = 14
_COL = {"qty": 0, "name": 1, "set": 3, "category": 4, "section": 6, "collector": 8, "uuid": 13}


def looks_like_archidekt_csv(text: str) -> bool:
    """True if the text is a headerless Archidekt deck CSV (qty,name,…,uuid,…)."""
    for line in text.lstrip("﻿").splitlines():
        if not line.strip():
            continue
        try:
            row = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            return False
        return (
            len(row) >= _ARCHIDEKT_MIN_COLS
            and row[_COL["qty"]].strip().isdigit()
            and bool(_UUID_RE.match(row[_COL["uuid"]].strip()))
        )
    return False


def parse_archidekt_csv(text: str) -> ParsedDeck:
    entries: list[DeckEntry] = []
    for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
        if len(row) < _ARCHIDEKT_MIN_COLS or not row[_COL["qty"]].strip().isdigit():
            continue
        category = row[_COL["category"]].strip() or None
        sec_hint = row[_COL["section"]].strip().lower() if len(row) > _COL["section"] else ""
        if category and category.lower() == "commander":
            section = "commander"
        elif sec_hint in {"maybeboard", "sideboard"}:
            section = sec_hint
        else:
            section = "main"
        entries.append(DeckEntry(
            quantity=int(row[_COL["qty"]]),
            name=fix_mojibake(row[_COL["name"]].strip()),
            set_code=row[_COL["set"]].strip() or None,
            collector_number=row[_COL["collector"]].strip() or None,
            section=section,
            category=category,
        ))
    return ParsedDeck(entries=entries, source_format="archidekt-csv")


def parse_deck(text: str) -> ParsedDeck:
    """Parse a decklist in any supported format (auto-detects Archidekt CSV vs text)."""
    return parse_archidekt_csv(text) if looks_like_archidekt_csv(text) else parse_decklist(text)

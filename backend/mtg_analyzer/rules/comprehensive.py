"""Download and parse the official Magic Comprehensive Rules text file.

WotC publishes the Comprehensive Rules as a plain-text file at media.wizards.com,
linked from magic.wizards.com/en/rules. The URL embeds the effective date and
changes with every update, so we *discover* the current link from the rules page
rather than hard-coding it (with a known-good fallback).

The file is UTF-8 (BOM), CRLF, with one rule/subrule per line, a Contents block, a
numbered-rules body, then a Glossary and Credits. See parse_rules_text for the grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from mtg_analyzer import config
from mtg_analyzer.models.rules import GlossaryEntry, Rule, RulesDocument

RULES_PAGE_URL = "https://magic.wizards.com/en/rules"
# Fallback if discovery fails (update if it 404s; discovery normally supersedes it).
FALLBACK_RULES_URL = "https://media.wizards.com/2026/downloads/MagicCompRules%2020260417.txt"

_URL_RE = re.compile(
    r"https://media\.wizards\.com/\d+/downloads/MagicCompRules[%\s]?20\d{6}\.txt"
)
_DATE_RE = re.compile(r"(20\d{6})\.txt")
_EFFECTIVE_RE = re.compile(r"effective as of ([^.]+)\.")

# Line grammar (after BOM strip + CRLF normalize):
_RULE_RE = re.compile(r"^(\d{3}\.\d+[a-z]?)\.?\s+(.+)$")  # 100.1.  or  100.1a
_CATEGORY_RE = re.compile(r"^(\d{3})\.\s+(\S.*)$")  # 100. General
_SECTION_RE = re.compile(r"^(\d)\.\s+(\S.*)$")  # 1. Game Concepts


@dataclass(frozen=True)
class RulesFile:
    path: Path
    date: str  # YYYYMMDD from the URL
    url: str


def discover_rules_url(*, client: httpx.Client | None = None) -> str:
    """Scrape the official rules page for the current Comprehensive Rules .txt URL.

    Returns a fetch-ready (space-encoded) URL, or the fallback if discovery fails.
    """
    http = client or httpx.Client(headers=config.DEFAULT_HEADERS, timeout=30, follow_redirects=True)
    try:
        resp = http.get(RULES_PAGE_URL)
        resp.raise_for_status()
        match = _URL_RE.search(resp.text)
        return match.group(0).replace(" ", "%20") if match else FALLBACK_RULES_URL
    except httpx.HTTPError:
        return FALLBACK_RULES_URL
    finally:
        if client is None:
            http.close()


def download_rules(dest_dir: Path | None = None, *, url: str | None = None) -> RulesFile:
    """Download the Comprehensive Rules text to ``dest_dir`` (discovering the URL if needed)."""
    dest_dir = dest_dir or config.DATA_DIR / "rules"
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = url or discover_rules_url()
    date_match = _DATE_RE.search(url)
    date = date_match.group(1) if date_match else "unknown"
    dest = dest_dir / f"comprehensive_rules_{date}.txt"

    resp = httpx.get(url, headers=config.DEFAULT_HEADERS, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    dest.write_text(resp.text, encoding="utf-8")
    return RulesFile(path=dest, date=date, url=url)


def parse_rules_text(raw: str) -> RulesDocument:
    """Parse the Comprehensive Rules text into structured rules + glossary."""
    text = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    effective = _EFFECTIVE_RE.search(text)
    effective_date = effective.group(1).strip() if effective else None

    # The literal "Glossary"/"Credits" headers appear once in Contents and once as the
    # real section; the real ones are the LAST occurrences.
    glossary_idx = _last_index(lines, "Glossary")
    credits_idx = _last_index(lines, "Credits")
    body_end = glossary_idx if glossary_idx is not None else len(lines)

    # The Contents block lists section/category titles that also match our header
    # regexes. Skip it: the body proper starts at the first real rule line, minus the
    # section/category headers contiguously above it (the Contents list sits before a
    # plain "Glossary"/"Credits"/intro line, which halts the walk-back).
    body_start = _body_start(lines, body_end)
    rules = _parse_rules(lines[body_start:body_end])
    glossary: list[GlossaryEntry] = []
    if glossary_idx is not None:
        end = credits_idx if credits_idx is not None else len(lines)
        glossary = _parse_glossary(lines[glossary_idx + 1 : end])

    return RulesDocument(effective_date=effective_date, rules=rules, glossary=glossary)


def _parse_rules(lines: list[str]) -> list[Rule]:
    rules: list[Rule] = []
    section: str | None = None
    category: str | None = None
    current: Rule | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if m := _RULE_RE.match(stripped):
            number = m.group(1)
            parent = category
            # A subrule (letter suffix) is parented to its base rule, e.g. 100.1a -> 100.1
            if number[-1].isalpha():
                parent = number[:-1]
            current = Rule(number=number, kind="rule", text=m.group(2),
                           section=section, parent=parent)
            rules.append(current)
        elif m := _CATEGORY_RE.match(stripped):
            category = m.group(1)
            current = Rule(number=category, kind="category", text=m.group(2), section=section)
            rules.append(current)
        elif m := _SECTION_RE.match(stripped):
            section = m.group(1)
            category = None
            current = Rule(number=section, kind="section", text=m.group(2))
            rules.append(current)
        elif current is not None:
            # Defensive: fold a stray continuation line into the current entry.
            current.text = f"{current.text}\n{stripped}"

    return rules


def _parse_glossary(lines: list[str]) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    block: list[str] = []

    def flush() -> None:
        if len(block) >= 2:
            entries.append(GlossaryEntry(term=block[0].strip(),
                                         definition="\n".join(block[1:]).strip()))

    for line in lines:
        if line.strip():
            block.append(line)
        else:
            flush()
            block = []
    flush()
    return entries


def _body_start(lines: list[str], body_end: int) -> int:
    """Index where the numbered-rules body begins (skipping the Contents listing)."""
    first_rule = next(
        (i for i in range(body_end) if _RULE_RE.match(lines[i].strip())), None
    )
    if first_rule is None:
        return 0
    j = first_rule - 1
    while j >= 0 and (
        not lines[j].strip()
        or _SECTION_RE.match(lines[j].strip())
        or _CATEGORY_RE.match(lines[j].strip())
    ):
        j -= 1
    return j + 1


def _last_index(lines: list[str], target: str) -> int | None:
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == target:
            return i
    return None

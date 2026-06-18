"""EDHREC client — per-commander card recommendations from json.edhrec.com.

Unofficial endpoint: throttle, back off on 429, cache, and never redistribute (see
the mtg-data-ecosystem skill). Candidates are matched to our card DB by *name*.

Structure (verified 2026-06): container.json_dict.cardlists[] → each has a `header`
and `cardviews[]` with name / synergy / inclusion / num_decks / potential_decks.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel

from mtg_analyzer import config

EDHREC_JSON_BASE = "https://json.edhrec.com"
_MIN_DELAY = 0.34
_SLUG_STRIP = re.compile(r"[^a-z0-9 ]")


class EdhrecCard(BaseModel):
    name: str
    synergy: float | None = None
    inclusion: int | None = None
    potential_decks: int | None = None
    header: str | None = None  # the EDHREC list it came from

    @property
    def inclusion_rate(self) -> float | None:
        if self.inclusion and self.potential_decks:
            return self.inclusion / self.potential_decks
        return None


def slugify(commander_name: str) -> str:
    """'Sauron, the Dark Lord' -> 'sauron-the-dark-lord'."""
    cleaned = _SLUG_STRIP.sub("", commander_name.lower())
    return re.sub(r"\s+", "-", cleaned.strip())


def commander_slug(names: list[str]) -> str:
    """Single commander, or partner pair joined alphabetically (EDHREC convention)."""
    return "-".join(sorted(slugify(n) for n in names if n))


class EdhrecClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=EDHREC_JSON_BASE, headers=config.DEFAULT_HEADERS, timeout=30
        )
        self._owns_client = client is None
        self._last_request = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> EdhrecClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def commander_cards(self, commander_names: list[str]) -> list[EdhrecCard]:
        """All recommended cards for a commander, deduped by name (best synergy kept).

        Returns [] if the commander page isn't found (cold-start / bad slug).
        """
        slug = commander_slug(commander_names)
        if not slug:
            return []
        delay = _MIN_DELAY - (time.monotonic() - self._last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            resp = await self._client.get(f"/pages/commanders/{slug}.json")
            self._last_request = time.monotonic()
            if resp.status_code != 200:
                return []
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return []
        return _parse_cardlists(data)


def _parse_cardlists(data: dict[str, Any]) -> list[EdhrecCard]:
    cardlists = (((data.get("container") or {}).get("json_dict") or {}).get("cardlists")) or []
    best: dict[str, EdhrecCard] = {}
    for cardlist in cardlists:
        header = cardlist.get("header")
        for cv in cardlist.get("cardviews", []):
            name = cv.get("name")
            if not name:
                continue
            card = EdhrecCard(
                name=name,
                synergy=cv.get("synergy"),
                inclusion=cv.get("inclusion"),
                potential_decks=cv.get("potential_decks"),
                header=header,
            )
            prev = best.get(name.lower())
            # keep the entry with the higher synergy (lists overlap)
            if prev is None or (card.synergy or -1) > (prev.synergy or -1):
                best[name.lower()] = card
    return list(best.values())

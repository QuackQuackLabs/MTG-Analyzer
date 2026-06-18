"""EDHREC client — per-commander card recommendations from json.edhrec.com.

Unofficial endpoint: throttle, back off on 429, cache, and never redistribute (see
the mtg-data-ecosystem skill). Candidates are matched to our card DB by *name*.

Structure (verified 2026-06): container.json_dict.cardlists[] → each has a `header`
and `cardviews[]` with name / synergy / inclusion / num_decks / potential_decks.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from mtg_analyzer import config

EDHREC_JSON_BASE = "https://json.edhrec.com"
_MIN_DELAY = 0.34
_SLUG_STRIP = re.compile(r"[^a-z0-9 ]")
_DEFAULT_TTL = 86_400  # 24h — EDHREC refreshes daily; cache to avoid re-hitting it


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


class EdhrecCache:
    """Local cache of EDHREC commander results in app.db (TTL-based, default 24h)."""

    def __init__(self, db_path: Path | None = None, *, ttl_seconds: int = _DEFAULT_TTL) -> None:
        self.path = db_path or config.DB_PATH
        self.ttl = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS edhrec_cache "
            "(slug TEXT PRIMARY KEY, fetched_at REAL NOT NULL, cards_json TEXT NOT NULL)"
        )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> EdhrecCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, slug: str) -> list[EdhrecCard] | None:
        row = self.conn.execute(
            "SELECT fetched_at, cards_json FROM edhrec_cache WHERE slug = ?", (slug,)
        ).fetchone()
        if row is None or time.time() - row[0] > self.ttl:
            return None  # miss or stale
        return [EdhrecCard.model_validate(d) for d in json.loads(row[1])]

    def put(self, slug: str, cards: list[EdhrecCard]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO edhrec_cache (slug, fetched_at, cards_json) VALUES (?,?,?)",
            (slug, time.time(), json.dumps([c.model_dump() for c in cards])),
        )
        self.conn.commit()


class EdhrecClient:
    def __init__(
        self, client: httpx.AsyncClient | None = None, *, cache: EdhrecCache | None = None
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=EDHREC_JSON_BASE, headers=config.DEFAULT_HEADERS, timeout=30
        )
        self._owns_client = client is None
        self._cache = cache
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
        if self._cache is not None and (hit := self._cache.get(slug)) is not None:
            return hit  # fresh cache (includes cached empty results for cold-start commanders)

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
        cards = _parse_cardlists(data)
        if self._cache is not None:
            self._cache.put(slug, cards)
        return cards


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

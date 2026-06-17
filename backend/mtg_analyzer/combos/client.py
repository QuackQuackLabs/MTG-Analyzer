"""Async Commander Spellbook client (combos / "variants").

Two capabilities:
  * find_my_combos — POST a decklist, get combos present + "almost there" with
    template requirements resolved server-side (authoritative deck analysis).
  * iter_variants — page the full variant database for a local cache.

Commander Spellbook is MIT-licensed and open; no key required. It publishes no
rate limit, so we throttle politely and cache (see the mtg-data-ecosystem skill).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from mtg_analyzer import config
from mtg_analyzer.models.combo import Combo, DeckCombos

_PAGE_LIMIT = 100  # server caps limit at 100
# Commander Spellbook rate-limits more aggressively than Scryfall and publishes no
# documented limit, so pace conservatively (~3 req/s) and back off hard on 429.
_MIN_DELAY = 0.34
_MAX_RETRIES = 6


class CommanderSpellbookClient:
    def __init__(
        self, client: httpx.AsyncClient | None = None, *, min_delay: float = _MIN_DELAY
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=config.COMMANDER_SPELLBOOK_BASE,
            headers=config.DEFAULT_HEADERS,
            timeout=60,
        )
        self._owns_client = client is None
        self._min_delay = min_delay
        self._last_request = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> CommanderSpellbookClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        delay = self._min_delay - (time.monotonic() - self._last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        backoff = 1.0
        for _ in range(_MAX_RETRIES):
            resp = await self._client.request(method, url, **kwargs)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                # Honor Retry-After if given, else exponential backoff (capped).
                wait = float(resp.headers.get("Retry-After", backoff))
                await asyncio.sleep(min(wait, 30.0))
                backoff = min(backoff * 2, 30.0)
                continue
            return resp
        return resp

    async def total_variants(self, *, commander_only: bool = True) -> int:
        params = {"limit": 1, "count": "true"}
        if commander_only:
            params["q"] = "legal:commander"
        resp = await self._request("GET", "/variants/", params=params)
        resp.raise_for_status()
        return int(resp.json().get("count") or 0)

    async def combos_for_card(self, card_name: str, *, max_results: int = 200) -> list[Combo]:
        """All combos that use a given card (single filtered query, politely paginated).

        On-demand alternative to mirroring the whole DB — one small request per card.
        """
        out: list[Combo] = []
        params: dict[str, Any] | None = {
            "q": f'card:"{card_name}"', "ordering": "-popularity", "limit": _PAGE_LIMIT,
        }
        url: str | None = "/variants/"
        while url and len(out) < max_results:
            resp = await self._request("GET", url, params=params)
            resp.raise_for_status()
            body = resp.json()
            out.extend(Combo.from_api(v) for v in body.get("results", []))
            url = body.get("next")
            params = None  # next URL carries its own query
        return out[:max_results]

    async def iter_variants(self, *, commander_only: bool = True) -> AsyncIterator[Combo]:
        """Yield every variant, following pagination. Commander-legal only by default."""
        first: dict[str, Any] = {"limit": _PAGE_LIMIT, "ordering": "-popularity"}
        if commander_only:
            first["q"] = "legal:commander"
        params: dict[str, Any] | None = first
        url: str | None = "/variants/"
        while url:
            resp = await self._request("GET", url, params=params)
            resp.raise_for_status()
            body = resp.json()
            for v in body.get("results", []):
                yield Combo.from_api(v)
            url = body.get("next")
            # `next` is a full URL with its query baked in. Pass params=None (NOT {})
            # so httpx leaves that query intact — an empty dict would strip it and loop.
            params = None

    async def find_my_combos(
        self, main: Sequence[str], commanders: Sequence[str] = ()
    ) -> DeckCombos:
        """Authoritative combo analysis of a decklist (cards given by name)."""
        payload = {
            "main": [{"card": name} for name in main],
            "commanders": [{"card": name} for name in commanders],
        }
        resp = await self._request("POST", "/find-my-combos", json=payload)
        resp.raise_for_status()
        results = resp.json().get("results", {})

        def bucket(key: str) -> list[Combo]:
            return [Combo.from_api(v) for v in results.get(key, [])]

        return DeckCombos(
            identity=results.get("identity", ""),
            included=bucket("included"),
            almost_included=bucket("almostIncluded"),
            included_by_changing_commanders=bucket("includedByChangingCommanders"),
            almost_included_by_adding_colors=bucket("almostIncludedByAddingColors"),
        )

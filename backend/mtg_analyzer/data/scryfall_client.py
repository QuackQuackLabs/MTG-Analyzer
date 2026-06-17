"""Async Scryfall live-API client for ad-hoc lookups.

Used only for things bulk data can't serve well: autocomplete, fuzzy single-card
resolution, ad-hoc search, and batch decklist resolution. Bulk-first remains the
rule for inventory-scale work (see the ``scryfall-api`` skill).

Enforces the required headers, a ~100 ms throttle, and 429 backoff.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from itertools import islice
from typing import Any

import httpx

from mtg_analyzer import config
from mtg_analyzer.models.card import Card

_COLLECTION_BATCH = 75  # Scryfall hard limit per /cards/collection request


class ScryfallClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=config.SCRYFALL_API_BASE,
            headers=config.DEFAULT_HEADERS,
            timeout=30,
        )
        self._owns_client = client is None
        self._last_request = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> ScryfallClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- core request with throttle + 429 backoff ---------------------------
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        delay = config.REQUEST_DELAY_SECONDS - (time.monotonic() - self._last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        for attempt in range(3):
            resp = await self._client.request(method, url, **kwargs)
            self._last_request = time.monotonic()
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.headers.get("Retry-After", "1")) + attempt)
                continue
            return resp
        return resp

    # --- endpoints ----------------------------------------------------------
    async def named(
        self, *, exact: str | None = None, fuzzy: str | None = None, set_code: str | None = None
    ) -> Card | None:
        """Resolve a single card by exact or fuzzy name. Returns None on 404/ambiguous."""
        if (exact is None) == (fuzzy is None):
            raise ValueError("Provide exactly one of `exact` or `fuzzy`.")
        params = {"exact": exact} if exact is not None else {"fuzzy": fuzzy}
        if set_code:
            params["set"] = set_code
        resp = await self._request("GET", "/cards/named", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return Card.model_validate(resp.json())

    async def autocomplete(self, query: str) -> list[str]:
        resp = await self._request("GET", "/cards/autocomplete", params={"q": query})
        resp.raise_for_status()
        return list(resp.json().get("data", []))

    async def search(self, query: str, *, order: str = "name", unique: str = "cards") -> list[Card]:
        """First page (≤175) of a Scryfall search. Returns [] when nothing matches."""
        resp = await self._request(
            "GET", "/cards/search", params={"q": query, "order": order, "unique": unique}
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [Card.model_validate(c) for c in resp.json().get("data", [])]

    async def collection(self, identifiers: Sequence[dict[str, Any]]) -> tuple[list[Card], list[dict]]:
        """Batch-resolve identifiers (auto-chunked to 75). Returns (found, not_found)."""
        found: list[Card] = []
        not_found: list[dict] = []
        it = iter(identifiers)
        while batch := list(islice(it, _COLLECTION_BATCH)):
            resp = await self._request("POST", "/cards/collection", json={"identifiers": batch})
            resp.raise_for_status()
            body = resp.json()
            found.extend(Card.model_validate(c) for c in body.get("data", []))
            not_found.extend(body.get("not_found", []))
        return found, not_found

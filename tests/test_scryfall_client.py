"""Scryfall client tests using a mocked transport (no network)."""

from __future__ import annotations

import httpx
import pytest

from mtg_analyzer import config
from mtg_analyzer.data.scryfall_client import ScryfallClient


def _card(name: str, oid: str) -> dict:
    return {"id": oid, "oracle_id": oid, "name": name, "layout": "normal", "cmc": 1.0}


def make_client(handler) -> ScryfallClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url=config.SCRYFALL_API_BASE, headers=config.DEFAULT_HEADERS,
                             transport=transport)
    return ScryfallClient(client=http)


async def test_named_sends_required_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=_card("Sol Ring", "abc"))

    async with make_client(handler) as client:
        card = await client.named(exact="Sol Ring")
    assert card is not None and card.name == "Sol Ring"
    assert seen["user-agent"].startswith("MTGAnalyzer/")
    assert seen["accept"] == "application/json"


async def test_named_404_returns_none() -> None:
    async with make_client(lambda r: httpx.Response(404, json={"object": "error"})) as client:
        assert await client.named(fuzzy="zzzzz") is None


async def test_named_requires_exactly_one_arg() -> None:
    async with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            await client.named()


async def test_collection_chunks_by_75() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        ids = json.loads(request.content)["identifiers"]
        batch_sizes.append(len(ids))
        data = [_card(f"Card {i}", f"id-{i}") for i in range(len(ids))]
        return httpx.Response(200, json={"data": data, "not_found": []})

    identifiers = [{"name": f"Card {i}"} for i in range(160)]
    async with make_client(handler) as client:
        found, not_found = await client.collection(identifiers)

    assert batch_sizes == [75, 75, 10]  # auto-chunked
    assert len(found) == 160
    assert not_found == []


async def test_429_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": ["Sol Ring", "Soul Warden"]})

    async with make_client(handler) as client:
        names = await client.autocomplete("so")
    assert calls["n"] == 2
    assert names == ["Sol Ring", "Soul Warden"]

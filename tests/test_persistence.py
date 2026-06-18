"""Tests for the EDHREC cache and the saved-deck library."""

from pathlib import Path

import httpx
import pytest

from mtg_analyzer import config
from mtg_analyzer.data.deck_library import DeckLibrary, load_deck_text
from mtg_analyzer.recommend.edhrec import EDHREC_JSON_BASE, EdhrecCache, EdhrecClient

_PAGE = {"container": {"json_dict": {"cardlists": [
    {"header": "Top Cards", "cardviews": [
        {"name": "Sol Ring", "synergy": 0.1, "inclusion": 50, "potential_decks": 100}]},
]}}}


# --- EDHREC cache ----------------------------------------------------------
async def test_cache_avoids_refetch(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_PAGE)

    cache = EdhrecCache(tmp_path / "c.db")

    def client() -> EdhrecClient:
        http = httpx.AsyncClient(base_url=EDHREC_JSON_BASE, transport=httpx.MockTransport(handler))
        return EdhrecClient(client=http, cache=cache)

    async with client() as c:
        first = await c.commander_cards(["Sauron, the Dark Lord"])
    async with client() as c:
        second = await c.commander_cards(["Sauron, the Dark Lord"])

    assert calls["n"] == 1  # second call served from cache
    assert [x.name for x in first] == [x.name for x in second] == ["Sol Ring"]
    cache.close()


def test_cache_respects_ttl(tmp_path: Path) -> None:
    cache = EdhrecCache(tmp_path / "c.db", ttl_seconds=86_400)
    from mtg_analyzer.recommend.edhrec import EdhrecCard

    cache.put("slug", [EdhrecCard(name="Sol Ring")])
    assert cache.get("slug") is not None
    # age the entry past the TTL
    cache.conn.execute("UPDATE edhrec_cache SET fetched_at = 0 WHERE slug = 'slug'")
    cache.conn.commit()
    assert cache.get("slug") is None  # stale → miss
    cache.close()


# --- deck library ----------------------------------------------------------
def test_deck_library_roundtrip(tmp_path: Path) -> None:
    lib = DeckLibrary(tmp_path / "decks")
    lib.save("My Sauron Deck", "// COMMANDER\n1 Sol Ring (LTC) 284\n")
    assert "my-sauron-deck" in lib.names()
    assert "Sol Ring" in (lib.get("My Sauron Deck") or "")  # name or slug both resolve
    assert "Sol Ring" in (lib.get("my-sauron-deck") or "")
    assert lib.remove("my-sauron-deck") is True
    assert lib.names() == []


def test_load_deck_text_path_and_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "deck.txt"
    f.write_text("1 Sol Ring\n")
    assert "Sol Ring" in load_deck_text(str(f))  # resolves a file path

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # saved decks land under tmp
    DeckLibrary().save("saved", "1 Counterspell\n")
    assert "Counterspell" in load_deck_text("saved")  # resolves a saved name

    with pytest.raises(FileNotFoundError):
        load_deck_text("nope-not-a-deck")

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from mtg_analyzer import config
from mtg_analyzer.combos.client import CommanderSpellbookClient
from mtg_analyzer.combos.store import ComboStore
from mtg_analyzer.models.combo import Combo

FIXTURES = Path(__file__).parent / "fixtures"
VARIANTS = json.loads((FIXTURES / "combo_variants_sample.json").read_text())


# --- model -----------------------------------------------------------------
def test_combo_from_api_parses_fields() -> None:
    combo = Combo.from_api(VARIANTS[0])
    assert combo.id == "comboA"
    assert combo.produces == ["Infinite mana"]
    assert combo.use_oracle_ids() == {"oid-x", "oid-y"}
    assert combo.commander_legal is True
    assert combo.requires == []

    b = Combo.from_api(VARIANTS[1])
    assert b.requires[0].name == "Permanent that taps for mana"
    assert "control a creature" in b.prerequisites


# --- store -----------------------------------------------------------------
@pytest.fixture
def store(tmp_path: Path) -> Iterator[ComboStore]:
    s = ComboStore(tmp_path / "combos.db")
    s.replace_all([Combo.from_api(v) for v in VARIANTS])
    yield s
    s.close()


def test_store_count(store: ComboStore) -> None:
    assert store.combo_count() == 2


def test_combos_using_orders_by_popularity(store: ComboStore) -> None:
    combos = store.combos_using("oid-x")
    assert [c.id for c in combos] == ["comboA", "comboB"]  # popularity 100 before 50


def test_find_in_deck_included_and_almost(store: ComboStore) -> None:
    result = store.find_in_deck({"oid-x", "oid-y"})
    assert [c.id for c in result.included] == ["comboA"]  # all uses present, no template
    assert [c.id for c in result.almost_included] == ["comboB"]  # missing oid-z


def test_find_in_deck_template_combo_not_included_offline(store: ComboStore) -> None:
    # comboB's uses are all present, but it needs a template — not confirmable offline.
    result = store.find_in_deck({"oid-x", "oid-z"})
    assert [c.id for c in result.included] == []
    assert "comboB" not in [c.id for c in result.almost_included]  # 0 missing, not "almost"


def test_find_in_deck_empty(store: ComboStore) -> None:
    assert store.find_in_deck(set()).included == []


# --- client (mocked) -------------------------------------------------------
def make_client(handler) -> CommanderSpellbookClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(base_url=config.COMMANDER_SPELLBOOK_BASE,
                             headers=config.DEFAULT_HEADERS, transport=transport)
    return CommanderSpellbookClient(client=http)


async def test_find_my_combos_parses_buckets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["main"] == [{"card": "Card X"}, {"card": "Card Y"}]  # objects, not strings
        return httpx.Response(200, json={"results": {
            "identity": "U",
            "included": [VARIANTS[0]],
            "almostIncluded": [VARIANTS[1]],
        }})

    async with make_client(handler) as client:
        result = await client.find_my_combos(main=["Card X", "Card Y"])
    assert result.identity == "U"
    assert [c.id for c in result.included] == ["comboA"]
    assert [c.id for c in result.almost_included] == ["comboB"]


def test_store_add_is_upsert(tmp_path: Path) -> None:
    s = ComboStore(tmp_path / "c.db")
    s.add([Combo.from_api(VARIANTS[0])])
    s.add([Combo.from_api(VARIANTS[0])])  # same id again
    assert s.combo_count() == 1
    # combo_cards not duplicated
    n = s.conn.execute("SELECT COUNT(*) FROM combo_cards WHERE combo_id='comboA'").fetchone()[0]
    assert n == 2  # the two `uses` cards, not 4
    s.add([Combo.from_api(VARIANTS[1])])  # different id coexists
    assert s.combo_count() == 2
    s.close()


async def test_combos_for_card_query_and_pagination() -> None:
    seen_q: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_q.append(str(request.url))
        if "offset=1" in str(request.url):
            return httpx.Response(200, json={"results": [VARIANTS[1]], "next": None})
        return httpx.Response(200, json={
            "results": [VARIANTS[0]],
            "next": f"{config.COMMANDER_SPELLBOOK_BASE}/variants/?offset=1",
        })

    async with make_client(handler) as client:
        combos = await client.combos_for_card("Card X")
    assert [c.id for c in combos] == ["comboA", "comboB"]
    assert 'card:"Card X"' in seen_q[0] or "card%3A%22Card+X%22" in seen_q[0]


async def test_iter_variants_follows_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "offset=1" in str(request.url):
            return httpx.Response(200, json={"results": [VARIANTS[1]], "next": None})
        return httpx.Response(200, json={
            "results": [VARIANTS[0]],
            "next": f"{config.COMMANDER_SPELLBOOK_BASE}/variants/?offset=1",
        })

    async with make_client(handler) as client:
        ids = [c.id async for c in client.iter_variants()]
    assert ids == ["comboA", "comboB"]

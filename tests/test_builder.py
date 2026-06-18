from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.card import Card
from mtg_analyzer.recommend.builder import LAND_TARGET, build_deck
from mtg_analyzer.recommend.edhrec import EdhrecCard

FIXTURES = Path(__file__).parent / "fixtures"
SOL_RING = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CardDatabase]:
    database = CardDatabase(tmp_path / "test.db")
    database.ingest_cards(FIXTURES / "oracle_cards_sample.json")
    yield database
    database.close()


def commander(**kw: Any) -> Card:
    base = {"id": "cmd", "name": "Cmdr", "layout": "normal", "cmc": 3.0,
            "type_line": "Legendary Creature — Wizard", "oracle_text": "",
            "color_identity": ["U"], "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def _edhrec() -> list[EdhrecCard]:
    return [
        EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100),
        EdhrecCard(name="Llanowar Elves", synergy=0.5, inclusion=90, potential_decks=100),
        EdhrecCard(name="Delver of Secrets", synergy=0.2, inclusion=40, potential_decks=100),
    ]


def test_build_respects_identity_and_lands(db: CardDatabase) -> None:
    deck = build_deck(commander(), {SOL_RING}, db, _edhrec())
    names = {c.name for c in deck.cards}
    assert deck.identity == "U"
    assert "Llanowar Elves" not in names  # green, outside [U]
    assert "Sol Ring" in names
    assert any(n.startswith("Delver of Secrets") for n in names)  # DFC full name
    assert deck.commander not in names  # commander isn't in the 99
    lands = sum(c.quantity for c in deck.cards if c.category == "land")
    assert lands == LAND_TARGET
    assert all(c.name == "Island" for c in deck.cards if c.category == "land")  # mono-U basics


def test_build_marks_owned(db: CardDatabase) -> None:
    deck = build_deck(commander(), {SOL_RING}, db, _edhrec())
    sol = next(c for c in deck.cards if c.name == "Sol Ring")
    assert sol.owned is True and sol.category == "ramp"
    assert deck.owned_count >= 1


def test_build_owned_only_excludes_unowned(db: CardDatabase) -> None:
    deck = build_deck(commander(), {SOL_RING}, db, _edhrec(), owned_only=True)
    names = {c.name for c in deck.cards if c.category != "land"}
    assert "Sol Ring" in names  # owned
    assert not any(n.startswith("Delver of Secrets") for n in names)  # not owned
    assert deck.buy_count == 0
    assert any("owned-only" in n or "only" in n for n in deck.notes)


def test_build_budget_caps_buys(db: CardDatabase) -> None:
    deck = build_deck(commander(), set(), db, _edhrec(), budget=0.0)
    assert deck.buy_cost <= 0.0
    nonland = {c.name for c in deck.cards if c.category != "land"}
    assert "Sol Ring" not in nonland  # costs > $0, excluded by $0 budget
    assert not any(n.startswith("Delver of Secrets") for n in nonland)

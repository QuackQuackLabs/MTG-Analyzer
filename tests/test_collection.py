"""Tests for inventory locations, deck sync, availability, and guide composition."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mtg_analyzer.analysis.guide import build_guide
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.collection import sync_decks
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import DeckLibrary
from mtg_analyzer.data.inventory_store import InventoryStore
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry
from mtg_analyzer.models.inventory import AVAILABLE, InventoryItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CardDatabase]:
    database = CardDatabase(tmp_path / "cards.db")
    database.ingest_cards(FIXTURES / "oracle_cards_sample.json")
    yield database
    database.close()


def test_locations_and_availability(tmp_path: Path) -> None:
    store = InventoryStore(tmp_path / "inv.db")
    # 2 loose Sol Rings (Available) + 1 committed to deck "alpha"
    store.set_available([InventoryItem(name="Sol Ring", oracle_id="sol", quantity=2)])
    store.set_deck("alpha", [InventoryItem(name="Sol Ring", oracle_id="sol", quantity=1)])

    assert store.owned("sol") == 3
    assert store.locations("sol") == {AVAILABLE: 2, "alpha": 1}
    # Available for a different deck excludes alpha's copy but the loose ones count
    assert "sol" in store.available_oracles(for_deck="beta")
    # A card ONLY in another deck is not available
    store.set_deck("alpha", [InventoryItem(name="Sol Ring", oracle_id="sol", quantity=1),
                             InventoryItem(name="Locked", oracle_id="locked", quantity=1)])
    assert "locked" not in store.available_oracles(for_deck="beta")
    assert "locked" in store.available_oracles(for_deck="alpha")  # available to its own deck
    store.close()


def test_sync_decks_merges_deck_cards(db: CardDatabase, tmp_path: Path) -> None:
    library = DeckLibrary(tmp_path / "decks")
    library.save("mydeck", "1 Sol Ring (LTC) 284\n1 Llanowar Elves (M19) 314\n")
    store = InventoryStore(tmp_path / "inv.db")
    store.set_available([InventoryItem(name="Counterspell", oracle_id="cs", quantity=1)])

    counts = sync_decks(library, db, store)
    assert counts["mydeck"] == 2
    # Sol Ring is now committed to mydeck; Counterspell stays available
    assert store.total_quantity("Available") == 1
    sol = db.get_by_name("Sol Ring")
    assert sol and store.locations(sol.oracle_id) == {"mydeck": 1}
    store.close()


def make_card(name: str, **kw: Any) -> Card:
    base = {"id": name, "name": name, "layout": "normal", "cmc": 2.0,
            "type_line": "Creature", "oracle_text": "", "color_identity": ["U"],
            "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def test_build_guide_renders_sections() -> None:
    cmd = make_card("Cmdr", type_line="Legendary Creature", color_identity=["U"])
    deck = ResolvedDeck(name="my-deck", entries=[
        ResolvedEntry(quantity=1, section="commander", requested_name="Cmdr", card=cmd),
    ])
    report = analyze(deck)
    md = build_guide(deck, report, sim=None, combos=[], edhrec=[])
    assert "# My Deck — Pilot's Guide" in md
    assert "## Game plan" in md
    assert "## Mulligan" in md
    assert "## Win conditions" in md

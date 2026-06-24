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


def test_deck_library_resolves_human_named_files(tmp_path: Path) -> None:
    library = DeckLibrary(tmp_path / "decks")
    # A file dropped in with spaces/accents/caps, not the canonical slug form.
    (library.dir / "Frodo and Sam.txt").write_text("1 Sol Ring\n", encoding="utf-8")
    (library.dir / "Sméagol.txt").write_text("1 Llanowar Elves\n", encoding="utf-8")

    # Lookup works by display name, by slug, and round-trips through names().
    assert library.get("Frodo and Sam") == "1 Sol Ring\n"
    assert library.get("frodo-and-sam") == "1 Sol Ring\n"
    assert library.get("Sméagol") == "1 Llanowar Elves\n"
    assert "Frodo and Sam" in library.names()
    # save() overwrites the existing human-named file rather than creating a duplicate.
    library.save("Frodo and Sam", "1 Mox Diamond\n")
    assert sorted(p.name for p in library.dir.glob("*.txt")) == ["Frodo and Sam.txt", "Sméagol.txt"]
    assert library.get("Frodo and Sam") == "1 Mox Diamond\n"
    # Robust to Unicode normalization: file stored decomposed (NFD), looked up composed (NFC).
    import unicodedata
    (library.dir / unicodedata.normalize("NFD", "Café.txt")).write_text("1 Sol Ring\n", encoding="utf-8")
    assert library.get(unicodedata.normalize("NFC", "Café")) == "1 Sol Ring\n"


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


def test_guide_combo_engine_names_outlet() -> None:
    """An engine combo (infinite tokens) should name a payoff the deck runs."""
    from mtg_analyzer.models.combo import Combo, ComboCard

    cmd = make_card("Cmdr", type_line="Legendary Creature")
    piece_a = make_card("Token Engine", type_line="Enchantment")
    piece_b = make_card("Token Maker", type_line="Creature")
    hoof = make_card("Craterhoof Behemoth", type_line="Creature",
                     oracle_text="Creatures you control get +X/+X and gain trample.")
    deck = ResolvedDeck(name="combo-deck", entries=[
        ResolvedEntry(quantity=1, section="commander", requested_name="Cmdr", card=cmd),
        ResolvedEntry(quantity=1, section="main", requested_name="Token Engine", card=piece_a),
        ResolvedEntry(quantity=1, section="main", requested_name="Token Maker", card=piece_b),
        ResolvedEntry(quantity=1, section="main", requested_name="Craterhoof Behemoth", card=hoof),
    ])
    combo = Combo(id="1", produces=["Infinite creature tokens"], identity="G",
                  uses=[ComboCard(oracle_id=None, name="Token Engine"),
                        ComboCard(oracle_id=None, name="Token Maker")], requires=[])
    report = analyze(deck, included_combos=[combo])
    md = build_guide(deck, report, sim=None, combos=[combo], edhrec=[])
    assert "convert it with Craterhoof Behemoth" in md
    assert "Protect (kill-on-sight):** Token Engine, Token Maker" in md


def test_guide_combo_engine_flags_missing_outlet() -> None:
    """An engine combo with no payoff in the deck should be flagged as a gap."""
    from mtg_analyzer.models.combo import Combo, ComboCard

    cmd = make_card("Cmdr", type_line="Legendary Creature")
    a = make_card("Rock A", type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    b = make_card("Rock B", type_line="Artifact", oracle_text="{T}: Untap target artifact.")
    deck = ResolvedDeck(name="no-outlet", entries=[
        ResolvedEntry(quantity=1, section="commander", requested_name="Cmdr", card=cmd),
        ResolvedEntry(quantity=1, section="main", requested_name="Rock A", card=a),
        ResolvedEntry(quantity=1, section="main", requested_name="Rock B", card=b),
    ])
    combo = Combo(id="2", produces=["Infinite colorless mana"], identity="C",
                  uses=[ComboCard(oracle_id=None, name="Rock A"),
                        ComboCard(oracle_id=None, name="Rock B")], requires=[])
    report = analyze(deck, included_combos=[combo])
    md = build_guide(deck, report, sim=None, combos=[combo], edhrec=[])
    assert "no outlet in the deck" in md
    assert "mana sink" in md


def test_guide_noncombo_deck_recovers_win_plan() -> None:
    """A combo-less deck still gets real win conditions, an Engine lines section, and an
    archetype-shaped game plan (the depth no longer depends on a Spellbook combo)."""
    cmd = make_card("Cmdr", type_line="Legendary Creature")
    drain = make_card("Blood Artist Jr.", type_line="Creature",
                      oracle_text="Whenever a creature dies, each opponent loses 1 life.")
    body = make_card("Token Bat", type_line="Creature", oracle_text="Flying.")
    deck = ResolvedDeck(name="aristocrats", entries=[
        ResolvedEntry(quantity=1, section="commander", requested_name="Cmdr", card=cmd),
        ResolvedEntry(quantity=1, section="main", requested_name="Blood Artist Jr.", card=drain),
        ResolvedEntry(quantity=1, section="main", requested_name="Token Bat", card=body),
    ])
    report = analyze(deck)
    md = build_guide(deck, report, sim=None, combos=[], edhrec=[])
    assert "## Engine lines" in md
    assert "Drain / aristocrats" in md
    assert "Protect (kill-on-sight):** Blood Artist Jr." in md
    assert "aristocrats deck" in md  # archetype label flows into the game plan

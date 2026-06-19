"""Unify the collection: Available pool (imported extras) + every deck's cards.

The single ``data/inventory.csv`` is the canonical export, with a Location column
(``Available`` or a deck slug). Deck cards are merged in from the registered deck
files so the inventory always reflects the full collection and where each card lives.
"""

from __future__ import annotations

import csv
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import DeckLibrary
from mtg_analyzer.data.inventory_store import InventoryStore
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_card
from mtg_analyzer.models.inventory import InventoryItem


def deck_to_items(deck_text: str, db: CardDatabase) -> list[InventoryItem]:
    """A deck's commander + mainboard as resolved inventory items (location set by caller)."""
    parsed = parse_deck(deck_text)
    items: list[InventoryItem] = []
    for e in parsed.entries:
        if e.section not in ("commander", "main"):
            continue
        card = resolve_card(db, name=e.name, set_code=e.set_code, collector_number=e.collector_number)
        items.append(InventoryItem(
            name=card.name if card else e.name,
            quantity=e.quantity, set_code=e.set_code, collector_number=e.collector_number,
            oracle_id=card.oracle_id if card else None,
        ))
    return items


def sync_decks(library: DeckLibrary, db: CardDatabase, store: InventoryStore) -> dict[str, int]:
    """Re-merge every registered deck into the inventory (location = deck slug)."""
    store.clear_deck_locations()
    counts: dict[str, int] = {}
    for slug in library.names():
        text = library.get(slug) or ""
        counts[slug] = store.set_deck(slug, deck_to_items(text, db))
    return counts


def export_csv(store: InventoryStore, path: Path | None = None) -> Path:
    """Write the unified inventory (with locations) to data/inventory.csv."""
    path = path or (config.DATA_DIR / "inventory.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Name", "Set code", "Collector number", "Foil", "Quantity",
                    "Scryfall ID", "Condition", "Location"])
        for i in store.all_items():
            w.writerow([i.name, i.set_code or "", i.collector_number or "",
                        "foil" if i.foil else "normal", i.quantity, i.scryfall_id or "",
                        i.condition or "", i.location])
    return path

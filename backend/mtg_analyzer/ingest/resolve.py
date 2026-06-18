"""Resolve parsed decklist / inventory entries to local card identities.

Resolution priority (offline, against the local card DB):
  card name → Scryfall id → (set code + collector number).

Name first is deliberate: a card name maps uniquely to a gameplay identity (oracle_id),
which is all resolution needs — printing details (set/collector/foil/price) are stored
verbatim from the source. The bulk DB holds only ONE representative printing per card,
so an id / (set, collector) from an export usually misses, and when it *does* hit it can
match a *different* card's representative printing — so those are fallbacks for when the
name doesn't resolve, not the primary key. Unresolved entries are surfaced, not dropped.
"""

from __future__ import annotations

from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import ParsedDeck, ResolvedDeck, ResolvedEntry
from mtg_analyzer.models.inventory import Inventory, InventoryItem


def resolve_card(
    db: CardDatabase,
    *,
    name: str,
    set_code: str | None = None,
    collector_number: str | None = None,
    scryfall_id: str | None = None,
) -> Card | None:
    if card := db.get_by_name(name):
        return card
    if scryfall_id and (card := db.get_by_scryfall_id(scryfall_id)):
        return card
    if set_code and collector_number:
        return db.get_by_set_collector(set_code, collector_number)
    return None


def resolve_deck(db: CardDatabase, parsed: ParsedDeck) -> ResolvedDeck:
    entries = [
        ResolvedEntry(
            quantity=e.quantity,
            section=e.section,
            requested_name=e.name,
            category=e.category,
            card=resolve_card(db, name=e.name, set_code=e.set_code,
                              collector_number=e.collector_number),
        )
        for e in parsed.entries
    ]
    return ResolvedDeck(name=parsed.name, entries=entries)


def resolve_inventory(db: CardDatabase, items: list[InventoryItem]) -> Inventory:
    """Attach oracle_id to each item (in place) and wrap as an Inventory."""
    for item in items:
        card = resolve_card(db, name=item.name, set_code=item.set_code,
                            collector_number=item.collector_number, scryfall_id=item.scryfall_id)
        item.oracle_id = card.oracle_id if card else None
    return Inventory(items=items)

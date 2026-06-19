"""Models for a card inventory (collection).

One `InventoryItem` per printing row in the source export (e.g. a ManaBox CSV line),
keyed for gameplay by `oracle_id` once resolved. Quantity is aggregated by card for
deck-building ("do I own a Sol Ring?"), while printing details (set, foil, condition,
price) are retained for value and display.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel


AVAILABLE = "Available"  # location for loose cards not committed to a deck


class InventoryItem(BaseModel):
    name: str
    quantity: int = 1
    set_code: str | None = None
    collector_number: str | None = None
    foil: bool = False
    condition: str | None = None
    language: str | None = None
    scryfall_id: str | None = None
    purchase_price: float | None = None
    oracle_id: str | None = None  # filled in by resolution
    location: str = AVAILABLE  # "Available" or a deck slug it's committed to


class Inventory(BaseModel):
    items: list[InventoryItem]

    def owned_by_oracle(self) -> dict[str, int]:
        """Total quantity owned per gameplay identity (resolved items only)."""
        totals: dict[str, int] = defaultdict(int)
        for item in self.items:
            if item.oracle_id:
                totals[item.oracle_id] += item.quantity
        return dict(totals)

    def owned(self, oracle_id: str) -> int:
        return self.owned_by_oracle().get(oracle_id, 0)

    @property
    def unresolved(self) -> list[InventoryItem]:
        return [i for i in self.items if not i.oracle_id]

    @property
    def distinct_cards(self) -> int:
        return len({i.oracle_id for i in self.items if i.oracle_id})

    @property
    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)

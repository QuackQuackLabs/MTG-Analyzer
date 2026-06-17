"""Parse a collection/inventory CSV export into InventoryItems.

Targets ManaBox first (has Scryfall ID + set code + collector number + foil), but is
header-driven so it also reads Moxfield / Deckbox / Archidekt collection CSVs — columns
are matched by normalized header name, not position. See the mtg-data-ecosystem skill.
"""

from __future__ import annotations

import csv
import io

from mtg_analyzer.models.inventory import InventoryItem

_FOIL_TRUE = {"foil", "etched", "true", "yes", "1"}


def parse_inventory_csv(text: str) -> list[InventoryItem]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    # map normalized-header -> original field name
    norm = {f.strip().lower(): f for f in reader.fieldnames}

    def col(row: dict[str, str], *headers: str) -> str | None:
        for h in headers:
            field = norm.get(h)
            if field is not None:
                value = (row.get(field) or "").strip()
                if value:
                    return value
        return None

    items: list[InventoryItem] = []
    for row in reader:
        name = col(row, "name")
        if not name:
            continue
        qty_raw = col(row, "quantity", "count", "qty")
        items.append(
            InventoryItem(
                name=name,
                quantity=int(qty_raw) if qty_raw and qty_raw.isdigit() else 1,
                set_code=col(row, "set code", "edition", "set", "set name"),
                collector_number=col(row, "collector number", "card number", "number"),
                foil=(col(row, "foil") or "").lower() in _FOIL_TRUE,
                condition=col(row, "condition"),
                language=col(row, "language", "lang"),
                scryfall_id=col(row, "scryfall id", "scryfall_id"),
                purchase_price=_to_float(col(row, "purchase price", "my price", "price")),
            )
        )
    return items


def _to_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.lstrip("$"))
    except ValueError:
        return None

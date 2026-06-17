"""Persist the user's card inventory in app.db.

One row per printing (preserving set/foil/condition/price), keyed for gameplay by
oracle_id. Quantity aggregates by oracle_id for deck-building queries.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.models.inventory import Inventory, InventoryItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    id               INTEGER PRIMARY KEY,
    oracle_id        TEXT,
    name             TEXT NOT NULL,
    set_code         TEXT,
    collector_number TEXT,
    foil             INTEGER NOT NULL DEFAULT 0,
    condition        TEXT,
    language         TEXT,
    scryfall_id      TEXT,
    quantity         INTEGER NOT NULL DEFAULT 1,
    purchase_price   REAL
);
CREATE INDEX IF NOT EXISTS idx_inventory_oracle ON inventory(oracle_id);
"""


class InventoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> InventoryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def replace(self, inventory: Inventory) -> int:
        """Replace the stored inventory. Returns the number of printing rows stored."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inventory")
        cur.executemany(
            "INSERT INTO inventory (oracle_id, name, set_code, collector_number, foil, "
            "condition, language, scryfall_id, quantity, purchase_price) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (i.oracle_id, i.name, i.set_code, i.collector_number, int(i.foil),
                 i.condition, i.language, i.scryfall_id, i.quantity, i.purchase_price)
                for i in inventory.items
            ],
        )
        self.conn.commit()
        return len(inventory.items)

    def owned(self, oracle_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE oracle_id = ?", (oracle_id,)
        ).fetchone()
        return int(row[0])

    def owned_by_oracle(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT oracle_id, SUM(quantity) q FROM inventory "
            "WHERE oracle_id IS NOT NULL GROUP BY oracle_id"
        ).fetchall()
        return {r["oracle_id"]: int(r["q"]) for r in rows}

    def distinct_cards(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT oracle_id) FROM inventory WHERE oracle_id IS NOT NULL"
        ).fetchone()
        return int(row[0])

    def total_quantity(self) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(quantity), 0) FROM inventory").fetchone()
        return int(row[0])

    def printings_for(self, oracle_id: str) -> list[InventoryItem]:
        rows = self.conn.execute(
            "SELECT * FROM inventory WHERE oracle_id = ? ORDER BY set_code", (oracle_id,)
        ).fetchall()
        return [
            InventoryItem(
                name=r["name"], quantity=r["quantity"], set_code=r["set_code"],
                collector_number=r["collector_number"], foil=bool(r["foil"]),
                condition=r["condition"], language=r["language"], scryfall_id=r["scryfall_id"],
                purchase_price=r["purchase_price"], oracle_id=r["oracle_id"],
            )
            for r in rows
        ]

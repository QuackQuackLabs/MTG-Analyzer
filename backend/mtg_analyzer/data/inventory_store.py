"""Persist the user's card inventory in app.db, with per-card *locations*.

A card copy is either ``Available`` (loose, usable for any deck) or committed to a
deck (located there, unavailable to other decks). The unified inventory = the
``Available`` pool (imported "extra" CSVs) + every registered deck's cards.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.models.inventory import AVAILABLE, Inventory, InventoryItem

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
    purchase_price   REAL,
    location         TEXT NOT NULL DEFAULT 'Available'
);
CREATE INDEX IF NOT EXISTS idx_inventory_oracle ON inventory(oracle_id);
"""

_INSERT = (
    "INSERT INTO inventory (oracle_id, name, set_code, collector_number, foil, condition, "
    "language, scryfall_id, quantity, purchase_price, location) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
)


def _row(i: InventoryItem) -> tuple:
    return (i.oracle_id, i.name, i.set_code, i.collector_number, int(i.foil), i.condition,
            i.language, i.scryfall_id, i.quantity, i.purchase_price, i.location)


class InventoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add the `location` column to inventory tables created before it existed."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(inventory)").fetchall()}
        if "location" not in cols:
            self.conn.execute(
                "ALTER TABLE inventory ADD COLUMN location TEXT NOT NULL DEFAULT 'Available'"
            )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory(location)"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> InventoryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- writes -------------------------------------------------------------
    def replace(self, inventory: Inventory) -> int:
        """Replace the entire inventory (all locations)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inventory")
        cur.executemany(_INSERT, [_row(i) for i in inventory.items])
        self.conn.commit()
        return len(inventory.items)

    def set_available(self, items: list[InventoryItem]) -> int:
        """Replace the Available pool (leaves deck-located cards untouched)."""
        for i in items:
            i.location = AVAILABLE
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inventory WHERE location = ?", (AVAILABLE,))
        cur.executemany(_INSERT, [_row(i) for i in items])
        self.conn.commit()
        return len(items)

    def set_deck(self, slug: str, items: list[InventoryItem]) -> int:
        """Replace one deck's committed cards (location = slug)."""
        for i in items:
            i.location = slug
        cur = self.conn.cursor()
        cur.execute("DELETE FROM inventory WHERE location = ?", (slug,))
        cur.executemany(_INSERT, [_row(i) for i in items])
        self.conn.commit()
        return len(items)

    def clear_deck_locations(self) -> None:
        self.conn.execute("DELETE FROM inventory WHERE location != ?", (AVAILABLE,))
        self.conn.commit()

    # --- queries ------------------------------------------------------------
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

    def available_oracles(self, for_deck: str | None = None) -> set[str]:
        """Oracle ids with at least one copy usable for `for_deck`.

        Usable = location 'Available', or already committed to `for_deck` itself.
        """
        locations = [AVAILABLE] + ([for_deck] if for_deck else [])
        placeholders = ",".join("?" * len(locations))
        rows = self.conn.execute(
            f"SELECT DISTINCT oracle_id FROM inventory "
            f"WHERE oracle_id IS NOT NULL AND location IN ({placeholders})",
            tuple(locations),
        ).fetchall()
        return {r["oracle_id"] for r in rows}

    def locations(self, oracle_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT location, SUM(quantity) q FROM inventory WHERE oracle_id = ? GROUP BY location",
            (oracle_id,),
        ).fetchall()
        return {r["location"]: int(r["q"]) for r in rows}

    def distinct_cards(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT oracle_id) FROM inventory WHERE oracle_id IS NOT NULL"
        ).fetchone()
        return int(row[0])

    def total_quantity(self, location: str | None = None) -> int:
        if location is None:
            row = self.conn.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM inventory WHERE location = ?", (location,)
            ).fetchone()
        return int(row[0])

    def all_items(self) -> list[InventoryItem]:
        rows = self.conn.execute("SELECT * FROM inventory ORDER BY location, name").fetchall()
        return [
            InventoryItem(
                name=r["name"], quantity=r["quantity"], set_code=r["set_code"],
                collector_number=r["collector_number"], foil=bool(r["foil"]),
                condition=r["condition"], language=r["language"], scryfall_id=r["scryfall_id"],
                purchase_price=r["purchase_price"], oracle_id=r["oracle_id"], location=r["location"],
            )
            for r in rows
        ]

    def printings_for(self, oracle_id: str) -> list[InventoryItem]:
        return [i for i in self.all_items() if i.oracle_id == oracle_id]

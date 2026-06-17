"""Local SQLite cache of Commander Spellbook combos (in app.db).

Enables card-centric lookups ("what combos is this card in?") and offline deck
scanning by ``uses`` cards, joined to our card DB on ``oracle_id``. Combos that
also need generic templates (``requires``) can't be fully verified offline — for
authoritative deck analysis use the live find_my_combos (it resolves templates).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.models.combo import Combo, DeckCombos

SCHEMA = """
CREATE TABLE IF NOT EXISTS combos (
    id              TEXT PRIMARY KEY,
    identity        TEXT,
    popularity      INTEGER,
    commander_legal INTEGER NOT NULL DEFAULT 0,
    n_templates     INTEGER NOT NULL DEFAULT 0,
    json            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS combo_cards (
    combo_id          TEXT NOT NULL,
    oracle_id         TEXT,
    card_name         TEXT,
    must_be_commander INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_combo_cards_oracle ON combo_cards(oracle_id);
CREATE INDEX IF NOT EXISTS idx_combo_cards_combo ON combo_cards(combo_id);
"""

_BATCH = 1000


class ComboStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ComboStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- ingest -------------------------------------------------------------
    def replace_all(self, combos: Iterable[Combo]) -> int:
        """Replace the cached combos with a fresh set. Returns the count stored."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM combos")
        cur.execute("DELETE FROM combo_cards")
        count = 0
        combo_rows: list[tuple] = []
        card_rows: list[tuple] = []
        for c in combos:
            combo_rows.append((c.id, c.identity, c.popularity, int(c.commander_legal),
                               len(c.requires), c.model_dump_json()))
            card_rows.extend(
                (c.id, u.oracle_id, u.name, int(u.must_be_commander)) for u in c.uses
            )
            count += 1
            if len(combo_rows) >= _BATCH:
                self._flush(cur, combo_rows, card_rows)
                combo_rows, card_rows = [], []
        self._flush(cur, combo_rows, card_rows)
        self.conn.commit()
        return count

    def add(self, combos: Iterable[Combo]) -> int:
        """Upsert combos into the cache without clearing the rest (on-demand caching)."""
        cur = self.conn.cursor()
        combo_rows: list[tuple] = []
        card_rows: list[tuple] = []
        count = 0
        for c in combos:
            cur.execute("DELETE FROM combo_cards WHERE combo_id = ?", (c.id,))
            combo_rows.append((c.id, c.identity, c.popularity, int(c.commander_legal),
                               len(c.requires), c.model_dump_json()))
            card_rows.extend(
                (c.id, u.oracle_id, u.name, int(u.must_be_commander)) for u in c.uses
            )
            count += 1
        self._flush(cur, combo_rows, card_rows)
        self.conn.commit()
        return count

    @staticmethod
    def _flush(cur: sqlite3.Cursor, combos: list[tuple], cards: list[tuple]) -> None:
        if combos:
            cur.executemany(
                "INSERT OR REPLACE INTO combos "
                "(id, identity, popularity, commander_legal, n_templates, json) "
                "VALUES (?,?,?,?,?,?)",
                combos,
            )
        if cards:
            cur.executemany(
                "INSERT INTO combo_cards (combo_id, oracle_id, card_name, must_be_commander) "
                "VALUES (?,?,?,?)",
                cards,
            )

    # --- queries ------------------------------------------------------------
    def combo_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM combos").fetchone()[0])

    def _combo(self, row: sqlite3.Row) -> Combo:
        return Combo.model_validate(json.loads(row["json"]))

    def get_combo(self, combo_id: str) -> Combo | None:
        row = self.conn.execute("SELECT json FROM combos WHERE id = ?", (combo_id,)).fetchone()
        return self._combo(row) if row else None

    def combos_using(self, oracle_id: str, limit: int = 25) -> list[Combo]:
        """Combos that use the given card, most popular first."""
        rows = self.conn.execute(
            "SELECT c.json FROM combo_cards cc JOIN combos c ON c.id = cc.combo_id "
            "WHERE cc.oracle_id = ? ORDER BY c.popularity DESC LIMIT ?",
            (oracle_id, limit),
        ).fetchall()
        return [self._combo(r) for r in rows]

    def find_in_deck(self, oracle_ids: set[str]) -> DeckCombos:
        """Offline match by ``uses`` cards.

        included        — every ``uses`` card present AND no template requirement
        almost_included — exactly one ``uses`` card missing
        (Template-bearing combos are best confirmed via the live find_my_combos.)
        """
        if not oracle_ids:
            return DeckCombos()
        placeholders = ",".join("?" * len(oracle_ids))
        candidate_ids = [
            r["combo_id"]
            for r in self.conn.execute(
                f"SELECT DISTINCT combo_id FROM combo_cards WHERE oracle_id IN ({placeholders})",
                tuple(oracle_ids),
            ).fetchall()
        ]
        included: list[Combo] = []
        almost: list[Combo] = []
        for cid in candidate_ids:
            combo = self.get_combo(cid)
            if combo is None:
                continue
            missing = combo.use_oracle_ids() - oracle_ids
            if not missing and not combo.requires:
                included.append(combo)
            elif len(missing) == 1:
                almost.append(combo)
        included.sort(key=lambda c: c.popularity or 0, reverse=True)
        almost.sort(key=lambda c: c.popularity or 0, reverse=True)
        return DeckCombos(included=included, almost_included=almost)

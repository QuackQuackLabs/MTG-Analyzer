"""Local SQLite card database: schema, streaming ingest, and queries.

Two tables, per project-plan.md:
  * ``cards``     — one row per gameplay identity (``oracle_id``); the canonical
                    record everything joins to. Holds extracted columns for fast
                    filtering plus the full Scryfall JSON for faithful reconstruction.
  * ``printings`` — one row per specific printing (Scryfall ``id``) for price/set/image.
                    From the Oracle Cards bulk this is one printing per card; swapping
                    in Default Cards later populates all printings (same schema).

Plus a ``rulings`` table joined on ``oracle_id``. Ingest streams the bulk JSON with
ijson so memory stays bounded.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import ijson

from mtg_analyzer import config
from mtg_analyzer.models.card import Card, Ruling

# Non-gameplay layouts that pollute name lookups (art cards, tokens, emblems, etc.).
# Kept in the DB for fidelity but deprioritized so a name resolves to the real card.
NON_GAMEPLAY_LAYOUTS = frozenset(
    {"art_series", "token", "double_faced_token", "emblem", "vanguard", "scheme",
     "planar", "augment", "host", "sticker"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    oracle_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    front_name      TEXT NOT NULL,              -- name before ' // ' (for DFC lookups)
    cmc             REAL NOT NULL DEFAULT 0,
    ci_key          TEXT NOT NULL DEFAULT '',   -- sorted color identity, e.g. 'GU'
    type_line       TEXT,
    commander_legal INTEGER NOT NULL DEFAULT 0,
    game_changer    INTEGER NOT NULL DEFAULT 0,
    layout          TEXT,
    is_gameplay     INTEGER NOT NULL DEFAULT 1, -- 0 for art series / tokens / emblems
    json            TEXT NOT NULL               -- full Scryfall card object
);
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_front ON cards(front_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_ci ON cards(ci_key);
CREATE INDEX IF NOT EXISTS idx_cards_cmc ON cards(cmc);
CREATE INDEX IF NOT EXISTS idx_cards_legal ON cards(commander_legal);

CREATE TABLE IF NOT EXISTS printings (
    id               TEXT PRIMARY KEY,
    oracle_id        TEXT NOT NULL,
    set_code         TEXT,
    collector_number TEXT,
    rarity           TEXT,
    usd              REAL,
    image_normal     TEXT
);
CREATE INDEX IF NOT EXISTS idx_printings_oracle ON printings(oracle_id);

CREATE TABLE IF NOT EXISTS rulings (
    oracle_id    TEXT NOT NULL,
    source       TEXT,
    published_at TEXT,
    comment      TEXT
);
CREATE INDEX IF NOT EXISTS idx_rulings_oracle ON rulings(oracle_id);
"""

_BATCH = 1000


class CardDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> CardDatabase:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- ingest -------------------------------------------------------------
    def ingest_cards(self, bulk_path: Path) -> int:
        """Stream an Oracle/Default Cards bulk file into cards + printings."""
        count = 0
        cur = self.conn.cursor()
        card_rows: list[tuple] = []
        printing_rows: list[tuple] = []
        for card in _stream_cards(bulk_path):
            oracle_key = card.oracle_id or card.id
            ci_key = "".join(sorted(card.color_identity))
            card_rows.append(
                (
                    oracle_key,
                    card.name,
                    card.name.split(" // ")[0],
                    card.cmc,
                    ci_key,
                    card.type_line,
                    int(card.is_commander_legal()),
                    int(card.game_changer),
                    card.layout,
                    int(card.layout not in NON_GAMEPLAY_LAYOUTS),
                    card.model_dump_json(),
                )
            )
            printing_rows.append(
                (
                    card.id,
                    oracle_key,
                    card.set,
                    card.collector_number,
                    card.rarity,
                    card.usd_price(),
                    card.get_image("normal"),
                )
            )
            count += 1
            if len(card_rows) >= _BATCH:
                self._flush(cur, card_rows, printing_rows)
                card_rows, printing_rows = [], []
        self._flush(cur, card_rows, printing_rows)
        self.conn.commit()
        return count

    @staticmethod
    def _flush(cur: sqlite3.Cursor, cards: list[tuple], printings: list[tuple]) -> None:
        if cards:
            cur.executemany(
                "INSERT OR REPLACE INTO cards "
                "(oracle_id, name, front_name, cmc, ci_key, type_line, commander_legal, "
                " game_changer, layout, is_gameplay, json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                cards,
            )
        if printings:
            cur.executemany(
                "INSERT OR REPLACE INTO printings "
                "(id, oracle_id, set_code, collector_number, rarity, usd, image_normal) "
                "VALUES (?,?,?,?,?,?,?)",
                printings,
            )

    def ingest_rulings(self, bulk_path: Path) -> int:
        """Stream a Rulings bulk file into the rulings table (replaces existing)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM rulings")
        rows: list[tuple] = []
        count = 0
        with bulk_path.open("rb") as fh:
            for r in ijson.items(fh, "item"):
                rows.append((r.get("oracle_id"), r.get("source"), r.get("published_at"),
                             r.get("comment")))
                count += 1
                if len(rows) >= _BATCH:
                    cur.executemany("INSERT INTO rulings VALUES (?,?,?,?)", rows)
                    rows = []
        if rows:
            cur.executemany("INSERT INTO rulings VALUES (?,?,?,?)", rows)
        self.conn.commit()
        return count

    # --- queries ------------------------------------------------------------
    def card_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0])

    def _card_from_row(self, row: sqlite3.Row | None) -> Card | None:
        return Card.model_validate(json.loads(row["json"])) if row else None

    def get_by_oracle_id(self, oracle_id: str) -> Card | None:
        row = self.conn.execute(
            "SELECT json FROM cards WHERE oracle_id = ?", (oracle_id,)
        ).fetchone()
        return self._card_from_row(row)

    def get_by_name(self, name: str) -> Card | None:
        """Resolve a card by exact full name OR front-face name (case-insensitive).

        So "Delver of Secrets" resolves to the real transform card, not the
        same-named art-series object. Gameplay cards win over non-gameplay ones.
        """
        row = self.conn.execute(
            "SELECT json FROM cards WHERE name = ? COLLATE NOCASE OR front_name = ? COLLATE NOCASE "
            "ORDER BY is_gameplay DESC, length(name) LIMIT 1",
            (name, name),
        ).fetchone()
        return self._card_from_row(row)

    def search_by_name(self, fragment: str, limit: int = 25) -> list[Card]:
        """Substring search, gameplay cards first."""
        rows = self.conn.execute(
            "SELECT json FROM cards WHERE name LIKE ? COLLATE NOCASE "
            "ORDER BY is_gameplay DESC, name LIMIT ?",
            (f"%{fragment}%", limit),
        ).fetchall()
        return [c for r in rows if (c := self._card_from_row(r))]

    def get_rulings(self, oracle_id: str) -> list[Ruling]:
        rows = self.conn.execute(
            "SELECT oracle_id, source, published_at, comment FROM rulings "
            "WHERE oracle_id = ? ORDER BY published_at",
            (oracle_id,),
        ).fetchall()
        return [Ruling.model_validate(dict(r)) for r in rows]


def _stream_cards(bulk_path: Path) -> Iterator[Card]:
    with bulk_path.open("rb") as fh:
        for obj in ijson.items(fh, "item"):
            yield Card.model_validate(obj)

"""SQLite store for the Comprehensive Rules, with FTS5 full-text search.

Lives in the same ``app.db`` as the card data. Provides exact rule lookup by
number, subrule expansion (e.g. all of 702.19a…z under 702.19), and ranked
full-text search over both rules and the glossary — the basis for answering
"what rule governs this interaction?" during card/deck evaluation.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.models.rules import GlossaryEntry, Rule, RulesDocument

SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    number  TEXT PRIMARY KEY,
    kind    TEXT NOT NULL,             -- section | category | rule
    text    TEXT NOT NULL,
    section TEXT,
    parent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_rules_parent ON rules(parent);

CREATE TABLE IF NOT EXISTS glossary (
    term       TEXT PRIMARY KEY,
    definition TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules_meta (key TEXT PRIMARY KEY, value TEXT);

CREATE VIRTUAL TABLE IF NOT EXISTS rules_fts USING fts5(number UNINDEXED, text);
CREATE VIRTUAL TABLE IF NOT EXISTS glossary_fts USING fts5(term, definition);
"""

_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class RulesStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = db_path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> RulesStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- ingest -------------------------------------------------------------
    def ingest(self, doc: RulesDocument, *, source: str = "") -> tuple[int, int]:
        """Replace the rules + glossary with a parsed document. Returns (rules, glossary)."""
        cur = self.conn.cursor()
        for table in ("rules", "glossary", "rules_fts", "glossary_fts", "rules_meta"):
            cur.execute(f"DELETE FROM {table}")

        cur.executemany(
            "INSERT OR REPLACE INTO rules (number, kind, text, section, parent) VALUES (?,?,?,?,?)",
            [(r.number, r.kind, r.text, r.section, r.parent) for r in doc.rules],
        )
        cur.executemany(
            "INSERT INTO rules_fts (number, text) VALUES (?,?)",
            [(r.number, r.text) for r in doc.rules if r.kind == "rule"],
        )
        cur.executemany(
            "INSERT INTO glossary (term, definition) VALUES (?,?)",
            [(g.term, g.definition) for g in doc.glossary],
        )
        cur.executemany(
            "INSERT INTO glossary_fts (term, definition) VALUES (?,?)",
            [(g.term, g.definition) for g in doc.glossary],
        )
        meta = {"effective_date": doc.effective_date or "", "source": source}
        cur.executemany("INSERT INTO rules_meta (key, value) VALUES (?,?)", list(meta.items()))
        self.conn.commit()
        return len(doc.rules), len(doc.glossary)

    # --- queries ------------------------------------------------------------
    def effective_date(self) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM rules_meta WHERE key = 'effective_date'"
        ).fetchone()
        return row["value"] if row and row["value"] else None

    def rule_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM rules WHERE kind='rule'").fetchone()[0])

    def glossary_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0])

    def get_rule(self, number: str) -> Rule | None:
        row = self.conn.execute("SELECT * FROM rules WHERE number = ?", (number,)).fetchone()
        return _rule(row) if row else None

    def get_rule_with_subrules(self, number: str) -> list[Rule]:
        """Return the rule plus its lettered subrules, in order (e.g. 702.19, 702.19a…).

        Uses a GLOB letter-class so "702.19" matches 702.19a–z but NOT 702.190 (a
        sibling rule), which a LIKE prefix would wrongly include.
        """
        rows = self.conn.execute(
            "SELECT * FROM rules WHERE number = ? OR number GLOB ? ORDER BY number",
            (number, f"{number}[a-z]"),
        ).fetchall()
        return [_rule(r) for r in rows]

    def search_rules(self, query: str, limit: int = 10) -> list[Rule]:
        fts = _fts_query(query)
        if not fts:
            return []
        rows = self.conn.execute(
            "SELECT r.* FROM rules_fts f JOIN rules r ON r.number = f.number "
            "WHERE rules_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts, limit),
        ).fetchall()
        return [_rule(r) for r in rows]

    def get_glossary(self, term: str) -> GlossaryEntry | None:
        row = self.conn.execute(
            "SELECT term, definition FROM glossary WHERE term = ? COLLATE NOCASE", (term,)
        ).fetchone()
        return GlossaryEntry(term=row["term"], definition=row["definition"]) if row else None

    def search_glossary(self, query: str, limit: int = 10) -> list[GlossaryEntry]:
        fts = _fts_query(query)
        if not fts:
            return []
        rows = self.conn.execute(
            "SELECT term, definition FROM glossary_fts WHERE glossary_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts, limit),
        ).fetchall()
        return [GlossaryEntry(term=r["term"], definition=r["definition"]) for r in rows]


def _rule(row: sqlite3.Row) -> Rule:
    return Rule(number=row["number"], kind=row["kind"], text=row["text"],
                section=row["section"], parent=row["parent"])


def _fts_query(query: str) -> str:
    """Sanitize free text into a safe FTS5 expression.

    Joins terms with OR so natural-language queries still match; bm25 ``rank``
    ordering then surfaces the rules covering the most (and rarest) terms.
    """
    return " OR ".join(_FTS_TOKEN_RE.findall(query))

"""Command-line entry point: ``mtg <command>``.

A thin convenience wrapper over the engine for local maintenance and spot checks.
The web app (FastAPI) is the primary interface; this exists for data refresh and
quick lookups without a running server.
"""

from __future__ import annotations

import argparse
import sys

from mtg_analyzer import config
from mtg_analyzer.data.bulk import BulkDataManager
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.rules.comprehensive import download_rules, parse_rules_text
from mtg_analyzer.rules.store import RulesStore


def _cmd_data_refresh(args: argparse.Namespace) -> int:
    mgr = BulkDataManager()
    db = CardDatabase()
    try:
        print("Downloading Oracle Cards…")
        oracle = mgr.download(config.BULK_ORACLE_CARDS, force=args.force)
        print(f"  {oracle.path.name} (updated_at {oracle.updated_at})")
        print("Ingesting cards…")
        n_cards = db.ingest_cards(oracle.path)

        print("Downloading Rulings…")
        rulings = mgr.download(config.BULK_RULINGS, force=args.force)
        print(f"  {rulings.path.name} (updated_at {rulings.updated_at})")
        print("Ingesting rulings…")
        n_rulings = db.ingest_rulings(rulings.path)

        print(f"Done: {n_cards:,} cards, {n_rulings:,} rulings → {db.path}")
    finally:
        db.close()
    return 0


def _cmd_data_status(_: argparse.Namespace) -> int:
    db = CardDatabase()
    try:
        print(f"DB: {db.path}")
        print(f"  cards: {db.card_count():,}")
    finally:
        db.close()
    return 0


def _cmd_card(args: argparse.Namespace) -> int:
    db = CardDatabase()
    try:
        card = db.get_by_name(args.name) or next(iter(db.search_by_name(args.name, 1)), None)
        if card is None:
            print(f"No card found matching {args.name!r}.", file=sys.stderr)
            return 1
        print(f"{card.name}  {card.get_mana_cost()}  (MV {card.cmc:g})")
        print(f"  {card.type_line}")
        print(f"  identity: {''.join(card.color_identity) or 'C'}  "
              f"commander: {card.commander_legality()}")
        for line in card.get_oracle_text().splitlines():
            print(f"  {line}")
        if card.oracle_id:
            n = len(db.get_rulings(card.oracle_id))
            if n:
                print(f"  ({n} ruling(s) on file)")
    finally:
        db.close()
    return 0


def _cmd_rules_refresh(args: argparse.Namespace) -> int:
    print("Discovering + downloading Comprehensive Rules…")
    rf = download_rules(url=args.url)
    print(f"  {rf.path.name}  (from {rf.url})")
    doc = parse_rules_text(rf.path.read_text(encoding="utf-8"))
    store = RulesStore()
    try:
        n_rules, n_gloss = store.ingest(doc, source=rf.url)
        print(f"Done: {n_rules:,} rules, {n_gloss:,} glossary terms "
              f"(effective {doc.effective_date}) → {store.path}")
    finally:
        store.close()
    return 0


def _cmd_rules_get(args: argparse.Namespace) -> int:
    store = RulesStore()
    try:
        rules = store.get_rule_with_subrules(args.number)
        if not rules:
            print(f"No rule {args.number!r}. Try `mtg rules search`.", file=sys.stderr)
            return 1
        for r in rules:
            print(f"{r.number}  {r.text}" if r.kind != "rule" else f"{r.number} {r.text}")
    finally:
        store.close()
    return 0


def _cmd_rules_search(args: argparse.Namespace) -> int:
    store = RulesStore()
    try:
        hits = store.search_rules(args.query, limit=args.limit)
        if not hits:
            print("No matching rules.", file=sys.stderr)
            return 1
        for r in hits:
            print(f"{r.number} {r.text}\n")
    finally:
        store.close()
    return 0


def _cmd_rules_glossary(args: argparse.Namespace) -> int:
    store = RulesStore()
    try:
        entry = store.get_glossary(args.term)
        entries = [entry] if entry else store.search_glossary(args.term, limit=args.limit)
        if not entries:
            print(f"No glossary entry for {args.term!r}.", file=sys.stderr)
            return 1
        for e in entries:
            print(f"{e.term}\n  {e.definition}\n")
    finally:
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mtg", description="MTG Analyzer CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    data = sub.add_parser("data", help="manage local card data").add_subparsers(
        dest="data_command", required=True
    )
    refresh = data.add_parser("refresh", help="download + ingest Scryfall bulk data")
    refresh.add_argument("--force", action="store_true", help="re-download even if unchanged")
    refresh.set_defaults(func=_cmd_data_refresh)
    data.add_parser("status", help="show local data status").set_defaults(func=_cmd_data_status)

    card = sub.add_parser("card", help="look up a card by name")
    card.add_argument("name")
    card.set_defaults(func=_cmd_card)

    rules = sub.add_parser("rules", help="Comprehensive Rules lookup").add_subparsers(
        dest="rules_command", required=True
    )
    r_refresh = rules.add_parser("refresh", help="download + ingest the Comprehensive Rules")
    r_refresh.add_argument("--url", help="explicit rules .txt URL (else auto-discovered)")
    r_refresh.set_defaults(func=_cmd_rules_refresh)
    r_get = rules.add_parser("get", help="show a rule and its subrules, e.g. 702.19")
    r_get.add_argument("number")
    r_get.set_defaults(func=_cmd_rules_get)
    r_search = rules.add_parser("search", help="full-text search the rules")
    r_search.add_argument("query")
    r_search.add_argument("--limit", type=int, default=10)
    r_search.set_defaults(func=_cmd_rules_search)
    r_gloss = rules.add_parser("glossary", help="look up a glossary term")
    r_gloss.add_argument("term")
    r_gloss.add_argument("--limit", type=int, default=5)
    r_gloss.set_defaults(func=_cmd_rules_glossary)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

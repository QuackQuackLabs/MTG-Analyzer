"""Command-line entry point: ``mtg <command>``.

A thin convenience wrapper over the engine for local maintenance and spot checks.
The web app (FastAPI) is the primary interface; this exists for data refresh and
quick lookups without a running server.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.combos.client import CommanderSpellbookClient
from mtg_analyzer.combos.store import ComboStore
from mtg_analyzer.data.bulk import BulkDataManager
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.inventory_store import InventoryStore
from mtg_analyzer.ingest.decklist import parse_decklist
from mtg_analyzer.ingest.inventory import parse_inventory_csv
from mtg_analyzer.ingest.resolve import resolve_deck, resolve_inventory
from mtg_analyzer.models.combo import Combo
from mtg_analyzer.rules.comprehensive import download_rules, parse_rules_text
from mtg_analyzer.rules.store import RulesStore

# Minimal card-name extraction for the combos CLI (the full decklist parser is Phase 2):
# strips a leading quantity and a trailing "(SET) 123" printing suffix.
_DECK_LINE_RE = re.compile(r"^\s*(?:\d+x?\s+)?(.+?)(?:\s+\([0-9A-Za-z]+\)\s+\S+)?\s*$")
_SECTION_HEADERS = {"deck", "commander", "sideboard", "companion", "maybeboard"}


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


def _cmd_combos_card(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = ComboStore()
    try:
        card = db.get_by_name(args.name)
        name = card.name if card else args.name

        async def fetch() -> list[Combo]:
            async with CommanderSpellbookClient() as client:
                return await client.combos_for_card(name, max_results=args.limit)

        combos = asyncio.run(fetch())  # live, single filtered query
        store.add(combos)  # cache for offline reuse
        if not combos:
            print(f"No combos found that use {name}.")
            return 0
        print(f"{len(combos)} combo(s) using {name}:\n")
        for c in combos:
            others = [u.name for u in c.uses if u.name != name]
            templates = [t.name for t in c.requires]
            parts = others + [f"<{t}>" for t in templates]
            print(f"  [{c.id}] {' + '.join(c.produces) or 'combo'}")
            print(f"     with: {', '.join(parts) or '(none)'}")
    finally:
        store.close()
        db.close()
    return 0


def _extract_card_names(text: str) -> list[str]:
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#")) or line.rstrip(":").lower() in _SECTION_HEADERS:
            continue
        if m := _DECK_LINE_RE.match(line):
            names.append(m.group(1).strip())
    return names


def _cmd_combos_find(args: argparse.Namespace) -> int:
    names = _extract_card_names(Path(args.file).read_text(encoding="utf-8"))
    if not names:
        print("No card names found in file.", file=sys.stderr)
        return 1

    async def run() -> None:
        async with CommanderSpellbookClient() as client:
            result = await client.find_my_combos(main=names)
        print(f"Deck identity: {result.identity or 'C'}  ({len(names)} cards)")
        print(f"\nComplete combos in deck: {len(result.included)}")
        for c in result.included[:args.limit]:
            print(f"  [{c.id}] {' + '.join(c.produces)}  — {', '.join(u.name for u in c.uses)}")
        print(f"\nOne card away: {len(result.almost_included)}")
        for c in result.almost_included[:args.limit]:
            print(f"  [{c.id}] {' + '.join(c.produces)}")

    asyncio.run(run())
    return 0


def _cmd_deck_show(args: argparse.Namespace) -> int:
    parsed = parse_decklist(Path(args.file).read_text(encoding="utf-8"))
    db = CardDatabase()
    try:
        deck = resolve_deck(db, parsed)
    finally:
        db.close()
    print(f"Format: {parsed.source_format}  |  total cards: {deck.card_total()}")
    for c in deck.commanders:
        ci = "".join(c.card.color_identity) if c.card else "?"
        print(f"Commander: {c.requested_name}  [{ci or 'C'}]")
    counts: dict[str, int] = {}
    for e in deck.entries:
        counts[e.section] = counts.get(e.section, 0) + e.quantity
    print("Sections: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if deck.unresolved:
        print(f"\nUnresolved ({len(deck.unresolved)}):")
        for e in deck.unresolved:
            print(f"  {e.quantity}x {e.requested_name}")
    return 0


def _cmd_inventory_import(args: argparse.Namespace) -> int:
    items = parse_inventory_csv(Path(args.file).read_text(encoding="utf-8"))
    db = CardDatabase()
    try:
        inventory = resolve_inventory(db, items)
    finally:
        db.close()
    store = InventoryStore()
    try:
        rows = store.replace(inventory)
    finally:
        store.close()
    print(f"Imported {rows:,} rows: {inventory.distinct_cards:,} distinct cards, "
          f"{inventory.total_quantity:,} total. Unresolved: {len(inventory.unresolved)}")
    for item in inventory.unresolved[:10]:
        print(f"  ? {item.name} ({item.set_code} {item.collector_number})")
    return 0


def _cmd_inventory_show(args: argparse.Namespace) -> int:
    store = InventoryStore()
    db = CardDatabase()
    try:
        if args.card:
            card = db.get_by_name(args.card)
            if card is None or not card.oracle_id:
                print(f"No card found matching {args.card!r}.", file=sys.stderr)
                return 1
            print(f"{card.name}: owned {store.owned(card.oracle_id)}")
            for p in store.printings_for(card.oracle_id):
                foil = " foil" if p.foil else ""
                print(f"  {p.set_code} #{p.collector_number}{foil} x{p.quantity}")
        else:
            print(f"Inventory: {store.distinct_cards():,} distinct cards, "
                  f"{store.total_quantity():,} total copies")
    finally:
        db.close()
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

    combos = sub.add_parser("combos", help="Commander Spellbook combos").add_subparsers(
        dest="combos_command", required=True
    )
    c_card = combos.add_parser("card", help="combos that use a card (live query, cached)")
    c_card.add_argument("name")
    c_card.add_argument("--limit", type=int, default=25)
    c_card.set_defaults(func=_cmd_combos_card)
    c_find = combos.add_parser("find", help="find combos in a decklist file (live, authoritative)")
    c_find.add_argument("file")
    c_find.add_argument("--limit", type=int, default=20)
    c_find.set_defaults(func=_cmd_combos_find)

    deck = sub.add_parser("deck", help="decklist import").add_subparsers(
        dest="deck_command", required=True
    )
    d_show = deck.add_parser("show", help="parse + resolve a decklist file")
    d_show.add_argument("file")
    d_show.set_defaults(func=_cmd_deck_show)

    inv = sub.add_parser("inventory", help="card collection").add_subparsers(
        dest="inventory_command", required=True
    )
    i_import = inv.add_parser("import", help="import a collection CSV (e.g. ManaBox)")
    i_import.add_argument("file")
    i_import.set_defaults(func=_cmd_inventory_import)
    i_show = inv.add_parser("show", help="inventory stats, or owned count for --card")
    i_show.add_argument("--card", help="show owned count + printings for this card")
    i_show.set_defaults(func=_cmd_inventory_show)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

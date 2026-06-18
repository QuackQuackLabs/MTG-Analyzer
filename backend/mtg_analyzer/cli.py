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
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.inventory import parse_inventory_csv
from mtg_analyzer.ingest.resolve import resolve_deck, resolve_inventory
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.combo import Combo
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.recommend.builder import build_deck
from mtg_analyzer.recommend.edhrec import EdhrecClient
from mtg_analyzer.recommend.recommender import apply_swaps, build_recommendations
from mtg_analyzer.simulation.goldfish import simulate
from mtg_analyzer.models.qa import CardKnowledge
from mtg_analyzer.rules.comprehensive import download_rules, parse_rules_text
from mtg_analyzer.rules.qa import explain_card, explain_interaction, search_knowledge
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


def _print_card_knowledge(k: CardKnowledge) -> None:
    print(f"{k.name}  —  {k.type_line}")
    for line in k.text.splitlines():
        print(f"  {line}")
    if k.keywords:
        print(f"  keywords: {', '.join(k.keywords)}")
    for g in k.glossary:
        print(f"\n  [glossary] {g.term}: {g.definition}")
    for r in k.rules:
        print(f"\n  [rule {r.number}] {r.text}")
    if k.rulings:
        print(f"\n  Rulings ({len(k.rulings)}):")
        for ru in k.rulings:
            print(f"    • ({ru.published_at}) {ru.comment}")
    if k.combos:
        print(f"\n  Combos involving {k.name} ({len(k.combos)}):")
        for c in k.combos[:10]:
            print(f"    ⚡ {c}")


def _combo_descriptions(combos: list) -> list[str]:
    return [f"{' + '.join(c.produces) or 'combo'} — {', '.join(u.name for u in c.uses)}"
            for c in combos]


def _cmd_explain(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = RulesStore()
    try:
        card = db.get_by_name(args.query)
        if card is not None:
            knowledge = explain_card(args.query, db, store)
            assert knowledge is not None
            if not args.no_combos:
                async def fetch() -> list:
                    try:
                        async with CommanderSpellbookClient() as client:
                            return await client.combos_for_card(card.name, max_results=10)
                    except Exception:  # noqa: BLE001 — combos are best-effort
                        return []
                knowledge.combos = _combo_descriptions(asyncio.run(fetch()))
            _print_card_knowledge(knowledge)
        else:  # free-text → search the rules + glossary
            res = search_knowledge(args.query, store)
            if not res.rules and not res.glossary:
                print(f"No rules or glossary entries match {args.query!r}.")
                return 0
            print(f"Rules matching {args.query!r}:")
            for r in res.rules:
                print(f"  [{r.number}] {r.text}")
            for g in res.glossary:
                print(f"\n  [glossary] {g.term}: {g.definition}")
    finally:
        store.close()
        db.close()
    return 0


def _cmd_interaction(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = RulesStore()
    try:
        inter = explain_interaction(args.card_a, args.card_b, db, store)
        raw_combos: list = []
        if not args.no_combos and len(inter.cards) == 2:
            async def fetch() -> list:
                try:
                    async with CommanderSpellbookClient() as client:
                        result = await client.find_my_combos(main=[args.card_a, args.card_b])
                    return result.included
                except Exception:  # noqa: BLE001
                    return []
            raw_combos = asyncio.run(fetch())

        for k in inter.cards:
            print("=" * 4, k.name, "=" * 4)
            _print_card_knowledge(k)
            print()
        if raw_combos:
            print(f"Combo(s) formed by these cards ({len(raw_combos)}):")
            for c in raw_combos:
                print(f"  ⚡ Produces: {' + '.join(c.produces)}")
                if c.prerequisites:
                    print(f"     Prerequisites: {c.prerequisites}")
                if c.description:
                    for step in c.description.splitlines():
                        print(f"     {step}")
        elif len(inter.cards) == 2 and not args.no_combos:
            print("No known two-card combo between them (per Commander Spellbook).")
        for note in inter.notes:
            print(f"  • {note}")
    finally:
        store.close()
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
    parsed = parse_deck(Path(args.file).read_text(encoding="utf-8"))
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


def _cmd_deck_analyze(args: argparse.Namespace) -> int:
    parsed = parse_deck(Path(args.file).read_text(encoding="utf-8"))
    db = CardDatabase()
    try:
        deck = resolve_deck(db, parsed)
        combos = [] if args.no_combos else _find_deck_combos(deck)
        report = analyze(deck, included_combos=combos)
    finally:
        db.close()

    cmd = ", ".join(report.commanders) or "(none)"
    print(f"{report.name or parsed.source_format} — Commander: {cmd}  [{report.identity}]")
    v = report.validation
    print(f"\nLegality: {'LEGAL' if v.legal else 'ILLEGAL'}  ({v.card_count} cards)")
    for issue in v.issues:
        print(f"  ✗ {issue}")
    for warn in v.warnings:
        print(f"  ! {warn}")

    print("\nComposition (count / target):")
    for c in report.categories:
        flag = f"  ↑ need {c.gap}" if c.gap else ""
        tgt = f"/{c.target}" if c.target else ""
        print(f"  {c.category:12} {c.count}{tgt}{flag}")

    print("\nMana curve (nonland):")
    peak = max((b.count for b in report.curve), default=1) or 1
    for b in report.curve:
        label = f"{b.cmc}+" if b.cmc == 7 else str(b.cmc)
        print(f"  {label:>2}  {'█' * round(b.count / peak * 24)} {b.count}")

    if report.combos:
        print(f"\nCombos present ({len(report.combos)}):")
        for combo in report.combos:
            print(f"  ⚡ {combo}")

    print(f"\nBracket estimate: {report.bracket_estimate}  — {report.bracket_rationale}")
    if report.game_changers:
        print(f"Game Changers ({len(report.game_changers)}): {', '.join(report.game_changers)}")
    return 0


def _find_deck_combos(deck: ResolvedDeck) -> list[Combo]:
    """Fetch combos present in a resolved deck via Commander Spellbook (gracefully empty)."""
    main = [e.card.name for e in deck.mainboard if e.card]
    cmds = [e.card.name for e in deck.commanders if e.card]

    async def run() -> list[Combo]:
        try:
            async with CommanderSpellbookClient() as client:
                result = await client.find_my_combos(main=main, commanders=cmds)
            return result.included
        except Exception:  # noqa: BLE001 — combo lookup is best-effort; analysis works offline
            return []

    return asyncio.run(run())


def _cmd_deck_recommend(args: argparse.Namespace) -> int:
    parsed = parse_deck(Path(args.file).read_text(encoding="utf-8"))
    db = CardDatabase()
    store = InventoryStore()
    try:
        deck = resolve_deck(db, parsed)
        report = analyze(deck)
        owned = set(store.owned_by_oracle())

        async def fetch() -> list:
            async with EdhrecClient() as client:
                return await client.commander_cards(report.commanders)

        edhrec_cards = asyncio.run(fetch())
        before = None if args.no_sim else simulate(deck, games=args.games, seed=1)
        recs = build_recommendations(deck, report, edhrec_cards, db, owned=owned,
                                     budget=args.budget, sim=before)
        after = None if args.no_sim else simulate(apply_swaps(deck, recs, db),
                                                  games=args.games, seed=1)
    finally:
        store.close()
        db.close()

    print(f"Recommendations for {recs.commander}  [{report.identity}]")

    if recs.adds:
        print(f"\nADD — fills your gaps, synergy-ranked from EDHREC ({len(recs.adds)}):")
        for a in recs.adds:
            price = "owned" if a.owned else (f"${a.price_usd:.2f}" if a.price_usd else "price n/a")
            print(f"  + {a.name:30} [{price:>9}]  {a.reason}")

    if recs.cuts:
        print(f"\nCONSIDER CUTTING — lowest play-rate in {recs.commander} decks ({len(recs.cuts)}):")
        for c in recs.cuts:
            print(f"  − {c.name:30} {c.reason}")

    print(f"\nNet: swap ~{min(len(recs.adds), len(recs.cuts))} cards (deck stays 100). "
          f"Estimated buy cost: ${recs.buy_cost:.2f}")

    if before and after:
        print("\nProjected impact (goldfish sim, before → after):")
        _sim_delta("keepable hand", before.p_keepable_hand, after.p_keepable_hand, pct=True)
        _sim_delta("mana screw", before.screw_rate, after.screw_rate, pct=True, lower_better=True)
        if before.commander_turn and after.commander_turn:
            bt, at = before.commander_turn.median, after.commander_turn.median
            if bt is not None and at is not None:
                arrow = "↓ faster" if at < bt else ("↑ slower" if at > bt else "no change")
                print(f"  commander castable (median turn):  {bt} → {at}   {arrow}")

    for note in recs.notes:
        print(f"  • {note}")
    return 0


def _sim_delta(label: str, before: float, after: float, *, pct: bool = False,
               lower_better: bool = False, band: float = 0.02) -> None:
    """Print a before→after metric, treating sub-`band` moves as sim noise ('≈ same')."""
    fmt = (lambda x: f"{x:.0%}") if pct else (lambda x: f"{x:.2f}")
    if abs(after - before) <= band:
        tag = "  ≈ same"
    else:
        improved = (after < before) if lower_better else (after > before)
        tag = "  ✓ better" if improved else "  worse"
    print(f"  {label:33} {fmt(before)} → {fmt(after)}{tag}")


def _cmd_deck_simulate(args: argparse.Namespace) -> int:
    parsed = parse_deck(Path(args.file).read_text(encoding="utf-8"))
    db = CardDatabase()
    try:
        deck = resolve_deck(db, parsed)
    finally:
        db.close()
    r = simulate(deck, games=args.games, on_play=not args.draw)

    play = "on the play" if r.on_play else "on the draw"
    print(f"Goldfish simulation — {r.games:,} games ({play})")
    print(f"  deck: {r.land_count} lands, {r.ramp_count} ramp"
          + (f", commander MV {r.commander_cmc}" if r.commander_cmc is not None else ""))
    print("\nOpening hand:")
    print(f"  avg lands in 7:        {r.avg_lands_in_opening}")
    print(f"  keepable (2–5 lands):  {r.p_keepable_hand:.0%}")
    print(f"  P(>=3 lands) [exact]:  {r.p_three_plus_lands_exact:.0%}")
    print(f"  flood (>=6 lands):     {r.flood_rate:.0%}")
    print(f"  avg mulligans:         {r.avg_mulligans}")
    print(f"\nMana screw (<2 lands by turn 3): {r.screw_rate:.0%}")
    if r.commander_turn:
        ct = r.commander_turn
        print(f"\nTurn commander is castable: median {ct.median}, mean {ct.mean}, "
              f"90% by turn {ct.p90}")
        if ct.never_pct:
            print(f"  not cast within {15} turns: {ct.never_pct}%")
    for note in r.notes:
        print(f"  • {note}")
    print("\n(Approximate mana model: single mana pool, no colored-mana requirements.)")
    return 0


def _is_legal_commander_card(card: Card) -> bool:
    tl = (card.type_line or "").lower()
    return (("legendary" in tl and "creature" in tl)
            or "can be your commander" in card.get_oracle_text().lower())


def _cmd_deck_build(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = InventoryStore()
    try:
        commander = db.get_by_name(args.commander)
        if commander is None:
            print(f"No card named {args.commander!r}.", file=sys.stderr)
            return 1
        if not _is_legal_commander_card(commander):
            print(f"{commander.name} isn't a legal commander.", file=sys.stderr)
            return 1
        owned = set(store.owned_by_oracle())

        async def fetch() -> list:
            async with EdhrecClient() as client:
                return await client.commander_cards([commander.name])

        edhrec = asyncio.run(fetch())
        deck = build_deck(commander, owned, db, edhrec, budget=args.budget,
                          owned_only=args.owned_only)
    finally:
        store.close()
        db.close()

    print(f"Built deck for {deck.commander}  [{deck.identity}]  ({deck.total_cards}/100 cards)")
    print(f"Owned: {deck.owned_count} cards · To buy: {deck.buy_count} · Buy cost: ${deck.buy_cost:.2f}\n")
    order = ["land", "ramp", "draw", "removal", "board_wipe", "payoff"]
    by_cat: dict[str, list] = {}
    for c in deck.cards:
        by_cat.setdefault(c.category or "payoff", []).append(c)
    for cat in order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        n = sum(c.quantity for c in items)
        print(f"{cat.upper()} ({n}):")
        for c in sorted(items, key=lambda c: (not c.owned, c.name)):
            qty = f"{c.quantity}x " if c.quantity > 1 else ""
            mark = "✓ owned" if c.owned else (f"buy ${c.price_usd:.2f}" if c.price_usd else "buy")
            print(f"  {qty}{c.name:32} [{mark}]")
    if deck.buy_count:
        print(f"\nShopping list ({deck.buy_count} cards, ${deck.buy_cost:.2f}):")
        for c in sorted((c for c in deck.cards if not c.owned), key=lambda c: -(c.price_usd or 0)):
            print(f"  {c.name:32} ${c.price_usd:.2f}" if c.price_usd else f"  {c.name}")
    for note in deck.notes:
        print(f"  • {note}")
    return 0


def _cmd_deck_suggest_commanders(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = InventoryStore()
    try:
        owned = store.owned_by_oracle()
        commanders = [
            c for oid in owned if (c := db.get_by_oracle_id(oid)) and _is_legal_commander_card(c)
        ]
        commanders.sort(key=lambda c: c.edhrec_rank or 10**9)
        if not commanders:
            print("No potential commanders found in your collection. "
                  "Import a collection first: `mtg inventory import <csv>`.")
            return 0
        print(f"Potential commanders you own ({len(commanders)}):")
        for c in commanders[: args.limit]:
            print(f"  {c.name:32} [{''.join(c.color_identity) or 'C'}]  {c.type_line}")
    finally:
        store.close()
        db.close()
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

    explain = sub.add_parser("explain", help="explain a card (text+rulings+rules+combos) or search rules")
    explain.add_argument("query", help="a card name, or a free-text rules question")
    explain.add_argument("--no-combos", action="store_true")
    explain.set_defaults(func=_cmd_explain)

    interaction = sub.add_parser("interaction", help="grounding for how two cards interact")
    interaction.add_argument("card_a")
    interaction.add_argument("card_b")
    interaction.add_argument("--no-combos", action="store_true")
    interaction.set_defaults(func=_cmd_interaction)

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
    d_analyze = deck.add_parser("analyze", help="validate + analyze a decklist")
    d_analyze.add_argument("file")
    d_analyze.add_argument("--no-combos", action="store_true",
                           help="skip the live combo lookup (offline / faster)")
    d_analyze.set_defaults(func=_cmd_deck_analyze)
    d_rec = deck.add_parser("recommend", help="suggest cuts + adds (EDHREC-blended, sim-aware)")
    d_rec.add_argument("file")
    d_rec.add_argument("--budget", type=float, help="max USD to spend on not-owned adds")
    d_rec.add_argument("--games", type=int, default=6000, help="sim games for before/after")
    d_rec.add_argument("--no-sim", action="store_true", help="skip the before/after simulation")
    d_rec.set_defaults(func=_cmd_deck_recommend)
    d_sim = deck.add_parser("simulate", help="goldfish consistency simulation")
    d_sim.add_argument("file")
    d_sim.add_argument("--games", type=int, default=10_000)
    d_sim.add_argument("--draw", action="store_true", help="simulate on the draw (default: on the play)")
    d_sim.set_defaults(func=_cmd_deck_simulate)
    d_build = deck.add_parser("build", help="build a deck for a commander from your collection")
    d_build.add_argument("commander", help="commander name")
    d_build.add_argument("--budget", type=float, help="max USD for not-owned cards")
    d_build.add_argument("--owned-only", action="store_true", help="use only cards you own")
    d_build.set_defaults(func=_cmd_deck_build)
    deck.add_parser("suggest-commanders", help="legal commanders in your collection").set_defaults(
        func=_cmd_deck_suggest_commanders, limit=25
    )

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

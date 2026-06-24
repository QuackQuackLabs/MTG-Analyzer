"""Command-line entry point: ``mtg <command>``.

A thin convenience wrapper over the engine for local maintenance and spot checks.
The web app (FastAPI) is the primary interface; this exists for data refresh and
quick lookups without a running server.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import re
import sys
from collections import Counter
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

from mtg_analyzer import config
from mtg_analyzer.combos.client import CommanderSpellbookClient
from mtg_analyzer.combos.store import ComboStore
from mtg_analyzer.analysis.guide import build_guide
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.bulk import BulkDataManager
from mtg_analyzer.data.collection import export_csv, sync_decks
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import DeckLibrary, load_deck_text, slugify
from mtg_analyzer.data.inventory_store import InventoryStore
from mtg_analyzer.data.match_log import MatchLog
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.inventory import parse_inventory_csv
from mtg_analyzer.ingest.resolve import resolve_deck, resolve_inventory
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.combo import Combo, DeckCombos
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.match_log import WIN_METHODS, LoggedGame
from mtg_analyzer.recommend.builder import build_deck
from mtg_analyzer.recommend.edhrec import EdhrecCache, EdhrecClient
from mtg_analyzer.recommend.recommender import apply_swaps, build_recommendations
from mtg_analyzer.simulation.battle import build_profile, calibrate_match, simulate_match
from mtg_analyzer.simulation.goldfish import simulate
from mtg_analyzer.simulation.sensitivity import analyze_sensitivity
from mtg_analyzer.models.qa import CardKnowledge
from mtg_analyzer.rules.comprehensive import download_rules, parse_rules_text
from mtg_analyzer.rules.qa import explain_card, explain_interaction, search_knowledge
from mtg_analyzer.rules.store import RulesStore

# Minimal card-name extraction for the combos CLI (the full decklist parser is Phase 2):
# strips a leading quantity and a trailing "(SET) 123" printing suffix.
_DECK_LINE_RE = re.compile(r"^\s*(?:\d+x?\s+)?(.+?)(?:\s+\([0-9A-Za-z]+\)\s+\S+)?\s*$")
_SECTION_HEADERS = {"deck", "commander", "sideboard", "companion", "maybeboard"}
T = TypeVar("T")


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


def _run_network(make_coro: Callable[[], Coroutine[Any, Any, T]], default: T, label: str) -> T:
    """Run a best-effort network coroutine; on failure surface a clear note + return default."""
    try:
        return asyncio.run(make_coro())
    except Exception as e:  # noqa: BLE001 — network is best-effort; tool works offline
        print(f"  ! {label} unavailable — {type(e).__name__} (offline or rate-limited); skipped.",
              file=sys.stderr)
        return default


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
                    async with CommanderSpellbookClient() as client:
                        return await client.combos_for_card(card.name, max_results=10)
                knowledge.combos = _combo_descriptions(_run_network(fetch, [], "Combo lookup"))
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
                async with CommanderSpellbookClient() as client:
                    result = await client.find_my_combos(main=[args.card_a, args.card_b])
                return result.included
            raw_combos = _run_network(fetch, [], "Combo lookup")

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

        combos: list[Combo] = _run_network(fetch, [], "Commander Spellbook")  # live query
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
    names = _extract_card_names(load_deck_text(args.file))
    if not names:
        print("No card names found in file.", file=sys.stderr)
        return 1

    async def run() -> DeckCombos | None:
        async with CommanderSpellbookClient() as client:
            return await client.find_my_combos(main=names)

    result = _run_network(run, None, "Commander Spellbook")
    if result is None:
        return 1
    print(f"Deck identity: {result.identity or 'C'}  ({len(names)} cards)")
    print(f"\nComplete combos in deck: {len(result.included)}")
    for c in result.included[:args.limit]:
        print(f"  [{c.id}] {' + '.join(c.produces)}  — {', '.join(u.name for u in c.uses)}")
    print(f"\nOne card away: {len(result.almost_included)}")
    for c in result.almost_included[:args.limit]:
        print(f"  [{c.id}] {' + '.join(c.produces)}")
    return 0


def _cmd_deck_show(args: argparse.Namespace) -> int:
    parsed = parse_deck(load_deck_text(args.file))
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
    parsed = parse_deck(load_deck_text(args.file))
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
        async with CommanderSpellbookClient() as client:
            result = await client.find_my_combos(main=main, commanders=cmds)
        return result.included

    return _run_network(run, [], "Combo detection")


def _cmd_deck_recommend(args: argparse.Namespace) -> int:
    parsed = parse_deck(load_deck_text(args.file))
    db = CardDatabase()
    store = InventoryStore()
    cache = EdhrecCache()
    try:
        deck = resolve_deck(db, parsed)
        combos = _find_deck_combos(deck)  # best-effort; used to protect combo pieces from cuts
        report = analyze(deck, included_combos=combos)
        protected = {u.name for c in combos for u in c.uses if u.name}
        # Only cards Available (not committed to another deck) + this deck's own cards.
        slug = slugify(args.file) if DeckLibrary().get(args.file) else None
        owned = store.available_oracles(for_deck=slug)

        async def fetch() -> list:
            async with EdhrecClient(cache=cache) as client:
                return await client.commander_cards(report.commanders)

        edhrec_cards = asyncio.run(fetch())
        before = None if args.no_sim else simulate(deck, games=args.games, seed=1)
        recs = build_recommendations(deck, report, edhrec_cards, db, owned=owned,
                                     budget=args.budget, sim=before, protected=protected)
        after = None if args.no_sim else simulate(apply_swaps(deck, recs, db),
                                                  games=args.games, seed=1)
    finally:
        cache.close()
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
    parsed = parse_deck(load_deck_text(args.file))
    db = CardDatabase()
    try:
        deck = resolve_deck(db, parsed)
        combos = None if args.no_combos else _find_deck_combos(deck)
    finally:
        db.close()
    r = simulate(deck, combos=combos, games=args.games, on_play=not args.draw)

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
    if r.combo_turn:
        cb = r.combo_turn
        plural = "combo" if r.combo_count == 1 else f"{r.combo_count} combos"
        print(f"\nTurn a combo comes together ({plural}): median {cb.median}, mean {cb.mean}, "
              f"90% by turn {cb.p90}")
        if cb.never_pct:
            print(f"  not assembled within 15 turns: {cb.never_pct}%")
    for note in r.notes:
        print(f"  • {note}")
    print("\n(Approximate mana model: single mana pool, no colored-mana requirements.)")
    return 0


def _cmd_battle(args: argparse.Namespace) -> int:
    if args.metagame:
        if len(args.decks) <= args.pod_size:
            print(f"--metagame needs MORE than {args.pod_size} decks (the pool to draw pods from); "
                  f"got {len(args.decks)}.", file=sys.stderr)
            return 1
    elif not 2 <= len(args.decks) <= 4:
        print("Provide 2 decks (1v1) up to 4 decks (pod).", file=sys.stderr)
        return 1
    db = CardDatabase()
    profiles = []
    try:
        for name in args.decks:
            deck = resolve_deck(db, parse_deck(load_deck_text(name)))
            combos = [] if args.no_combos else _find_deck_combos(deck)
            report = analyze(deck, included_combos=combos)
            sim = simulate(deck, combos=combos, games=args.sim_games)
            profiles.append(build_profile(Path(name).stem, deck, report, sim))
    finally:
        db.close()

    if args.metagame:
        from mtg_analyzer.simulation.battle import simulate_metagame
        meta = simulate_metagame(profiles, pod_size=args.pod_size, games=args.games, seed=args.seed)
        status = (f"converged in {meta.iterations} passes" if meta.converged
                  else f"ran {meta.iterations} passes (not yet converged)")
        print(f"Metagame — all {meta.pods} {meta.pod_size}-deck pods, fictitious-play feedback ({status}).\n"
              "Assumes an INFORMED table that has learned each deck's power level and targets accordingly.\n"
              "Power = learned strength (the ranking); archenemy = who the table gangs up on; win rate =\n"
              "the POLICED outcome (it compresses, because the table correctly answers the strongest deck).\n")
        print(f"  #  {'Deck':18} {'power':>6}  {'archenemy%':>10}  {'win%':>5}")
        for d in meta.decks:
            print(f"  {d.power_rank}  {d.name:18} {d.power_level:>+6.2f}  {d.archenemy_rate:>10.0%}  {d.win_rate:>5.0%}")
        print(f"\n  (Fair share = {1/meta.pod_size:.0%}. Power >0 = above fair / a known threat the informed "
              "table gangs up on; <0 = a deck it leaves alone at game start. Under informed play the "
              "strongest deck draws the most heat and its win rate is policed toward parity — power lives "
              "in the ranking + archenemy column, NOT in raw win rate.)")
        return 0

    if args.calibrate:
        print("Calibration sweep — win rates vs. interaction-answer base "
              "(model health = low inevitability share):\n")
        header = "  ans_base  " + "".join(f"{p.name[:10]:>11}" for p in profiles) + "   avg_turn  inev%"
        print(header)
        for row in calibrate_match(profiles, games=max(800, args.games // 2), seed=args.seed):
            cells = "".join(f"{r:>10.0%} " for r in row.win_rates)
            print(f"  {row.answer_base:>6.2f}    {cells}  {row.avg_len:>6.1f}  {row.inevitability_share:>5.0%}")
        print("\n  (Spread across rows = how sensitive the result is to the interaction assumption.)")
        return 0

    if args.sensitivity:
        print("Global sensitivity — joint band over ALL tunable params (Latin Hypercube over priors),\n"
              "the honest uncertainty vs. the default interaction-only band:\n")
        sens = analyze_sensitivity(profiles, samples=args.sens_samples, games=max(400, args.games // 3),
                                   seed=args.seed)
        print(f"  Win-rate band [5th–95th pct] across {sens.samples} parameter draws:")
        for p in profiles:
            lo, mid, hi = sens.band[p.name]
            print(f"    {p.name:16} {mid:5.0%}  [{lo:.0%}–{hi:.0%}]")
        print("\n  Parameters driving the spread (|rank-corr| with the most-affected deck):")
        for name, imp in sens.importance[:6]:
            bar = "█" * int(round(imp * 20))
            print(f"    {name:26} {imp:.2f} {bar}")
        print("\n  (Parametric uncertainty under expert priors — NOT a calibrated prediction.)")
        return 0

    result = simulate_match(profiles, games=args.games, seed=args.seed, preset=args.preset)
    mode = "1v1" if result.players == 2 else f"{result.players}-player pod"
    print(f"Battle simulation — {mode}, {result.games:,} games (avg game ends ~turn "
          f"{result.avg_game_length})\n")
    print("Battle profiles (abstracted from analysis + goldfish sim):")
    for p in profiles:
        tag = "  COMBO" if p.has_combo else ""
        print(f"  {p.name:16} {p.archetype:9} clock~T{p.clock_mean:<4.1f} "
              f"interaction {p.interaction:<2} draw {p.card_advantage:<2} tutors {p.tutors}{tag}")

    print("\nWin rate  [interaction-only band — run --sensitivity for the honest joint band]:")
    for d in sorted(result.decks, key=lambda x: -x.win_rate):
        band = f"[{d.win_rate_low:.0%}–{d.win_rate_high:.0%}]"
        wt = f"win ~T{d.avg_win_turn}" if d.avg_win_turn is not None else ""
        methods = ", ".join(f"{k} {v:.0%}" for k, v in sorted(d.methods.items(), key=lambda x: -x[1]))
        print(f"  {d.name:16} {d.win_rate:5.0%}  {band:13} {wt:11} {methods}")
        if result.players > 2:
            print(f"  {'':16}        archenemy {d.archenemy_rate:.0%} · died-first {d.died_first_rate:.0%}")

    print("\nWhy — clock (raw goldfish speed) vs. equity (realized wins):")
    for d in sorted(result.decks, key=lambda x: x.equity_rank):
        arrow = "→" if d.rank_shift == 0 else ("↑" if d.rank_shift > 0 else "↓")
        print(f"  {d.name:16} {arrow} {d.explain}")

    print("\nAssumptions:")
    for a in result.assumptions:
        print(f"  • {a}")
    for note in result.notes:
        print(f"\n⚠ {note}")
    return 0


def _select_indices(raw: str, count: int) -> list[int]:
    """Parse a '1 3 4' / '1,3,4' selection into 0-based indices, validating range + duplicates.
    Pure + testable; raises ValueError with a human message the prompt loop echoes back."""
    tokens = raw.replace(",", " ").split()
    if not tokens:
        raise ValueError("enter at least one number")
    out: list[int] = []
    for tok in tokens:
        if not tok.isdigit():
            raise ValueError(f"{tok!r} isn't a number")
        i = int(tok)
        if not 1 <= i <= count:
            raise ValueError(f"{i} is out of range 1–{count}")
        if i - 1 in out:
            raise ValueError(f"{i} repeated")
        out.append(i - 1)
    return out


def _record_game(
    *, pod_names: list[str], winner: str, died_first: str | None, archenemy: str | None,
    end_turn: int | None, win_method: str | None, date: str | None, notes: str | None,
    sim_games: int, no_combos: bool,
) -> int:
    """Resolve saved-deck names → slugs, snapshot each deck's BattleProfile as-played, validate, and
    append the game. Shared by the flag-based `add` and the interactive `form`."""
    lib = DeckLibrary()
    texts: dict[str, str] = {}
    pod: list[str] = []
    for name in pod_names:
        text = lib.get(name)
        if text is None:
            print(f"Deck {name!r} isn't saved — save it first with `mtg deck save <name> <file>` "
                  "so logged games stay joinable.", file=sys.stderr)
            return 1
        slug = slugify(name)
        if slug in texts:
            print(f"Duplicate deck in the pod: {name!r}.", file=sys.stderr)
            return 1
        texts[slug] = text
        pod.append(slug)

    def in_pod(value: str | None, label: str) -> tuple[bool, str | None]:
        if value is None:
            return True, None
        slug = slugify(value)
        if slug not in texts:
            print(f"{label} {value!r} is not one of the pod decks {pod_names}.", file=sys.stderr)
            return False, None
        return True, slug

    ok_w, winner_slug = in_pod(winner, "winner")
    ok_d, died_slug = in_pod(died_first, "died-first")
    ok_a, arch_slug = in_pod(archenemy, "archenemy")
    if not (ok_w and ok_d and ok_a) or winner_slug is None:
        return 1

    # Snapshot each deck's BattleProfile as-played — drift insurance for the fit (9C).
    db = CardDatabase()
    profiles = {}
    try:
        for slug in pod:
            deck = resolve_deck(db, parse_deck(texts[slug]))
            combos = [] if no_combos else _find_deck_combos(deck)
            report = analyze(deck, included_combos=combos)
            sim = simulate(deck, games=sim_games)
            profiles[slug] = build_profile(slug, deck, report, sim)
    finally:
        db.close()

    game = LoggedGame(
        date=date or datetime.date.today().isoformat(),
        pod=pod, winner=winner_slug, died_first=died_slug, end_turn=end_turn,
        win_method=win_method, archenemy=arch_slug, profiles=profiles, notes=notes,
    )
    log = MatchLog()
    log.append(game)
    total = len(log.load().games)
    print(f"Logged {game.date}: {' · '.join(pod)} → winner {winner_slug}"
          + (f" (died-first {died_slug})" if died_slug else "")
          + (f", ended T{game.end_turn}" if game.end_turn else "") + ".")
    print(f"Corpus: {total} game(s) at {log.path}.")
    if total < 30:
        print(f"  ~{30 - total} more to reach a first directional fit (~30–45 games; ~60–80 for confidence).")
    return 0


def _cmd_matchlog_add(args: argparse.Namespace) -> int:
    return _record_game(
        pod_names=args.pod, winner=args.winner, died_first=args.died_first,
        archenemy=args.archenemy, end_turn=args.end_turn, win_method=args.win_method,
        date=args.date, notes=args.notes, sim_games=args.sim_games, no_combos=args.no_combos,
    )


def _collect_game_form(
    saved: list[str], read: Callable[[str], str], write: Callable[[str], None]
) -> dict[str, Any] | None:
    """Interactive 'fill-out form' run after a game — picks decks from a numbered list of saved
    decks and prompts field by field, re-asking on bad input. I/O is injected so it's testable.
    Returns the collected answers (deck display-names), or None if the user aborts at the pod step."""
    write("Saved decks:")
    for i, name in enumerate(saved, 1):
        write(f"  {i}. {name}")

    def ask_pod() -> list[str] | None:
        while True:
            raw = read("Which decks played? (numbers, 2–4, e.g. '1 3 4'; blank to cancel): ").strip()
            if not raw:
                return None
            try:
                idx = _select_indices(raw, len(saved))
            except ValueError as exc:
                write(f"  ↳ {exc}; try again.")
                continue
            if not 2 <= len(idx) <= 4:
                write("  ↳ pick 2–4 decks; try again.")
                continue
            return [saved[i] for i in idx]

    pod = ask_pod()
    if pod is None:
        return None
    write("Pod: " + ", ".join(f"{i}. {n}" for i, n in enumerate(pod, 1)))

    def ask_pod_member(prompt: str, *, optional: bool) -> str | None:
        while True:
            raw = read(prompt).strip()
            if not raw:
                if optional:
                    return None
                write("  ↳ required; pick a number.")
                continue
            try:
                idx = _select_indices(raw, len(pod))
            except ValueError as exc:
                write(f"  ↳ {exc}; try again.")
                continue
            if len(idx) != 1:
                write("  ↳ pick exactly one; try again.")
                continue
            return pod[idx[0]]

    winner = ask_pod_member("Who won? (number): ", optional=False)
    died_first = (ask_pod_member("Who died first? (number, blank to skip): ", optional=True)
                  if len(pod) > 2 else None)

    def ask_int(prompt: str) -> int | None:
        while True:
            raw = read(prompt).strip()
            if not raw:
                return None
            if raw.isdigit() and int(raw) >= 1:
                return int(raw)
            write("  ↳ enter a whole number ≥ 1, or blank to skip.")

    end_turn = ask_int("What turn did it end? (number, blank to skip): ")

    methods = sorted(WIN_METHODS)
    write("Win method — " + ", ".join(f"{i}. {m}" for i, m in enumerate(methods, 1)))

    def ask_method() -> str | None:
        while True:
            raw = read("How did it end? (number, blank to skip): ").strip()
            if not raw:
                return None
            try:
                idx = _select_indices(raw, len(methods))
            except ValueError as exc:
                write(f"  ↳ {exc}; try again.")
                continue
            if len(idx) != 1:
                write("  ↳ pick exactly one; try again.")
                continue
            return methods[idx[0]]

    win_method = ask_method()
    today = datetime.date.today().isoformat()
    date = read(f"Date played [{today}]: ").strip() or today
    return {
        "pod": pod, "winner": winner, "died_first": died_first, "end_turn": end_turn,
        "win_method": win_method, "date": date,
    }


def _cmd_matchlog_form(args: argparse.Namespace) -> int:
    saved = DeckLibrary().names()
    if len(saved) < 2:
        print("Need at least 2 saved decks to log a game. Save decks with `mtg deck save`.",
              file=sys.stderr)
        return 1
    answers = _collect_game_form(saved, input, print)
    if answers is None:
        print("Cancelled — nothing logged.")
        return 0
    summary = (f"\n{answers['date']}: {' · '.join(answers['pod'])} → winner {answers['winner']}"
               + (f", died-first {answers['died_first']}" if answers["died_first"] else "")
               + (f", T{answers['end_turn']}" if answers["end_turn"] else "")
               + (f", {answers['win_method']}" if answers["win_method"] else ""))
    print(summary)
    if input("Save this game? [Y/n]: ").strip().lower() in ("n", "no"):
        print("Discarded — nothing logged.")
        return 0
    return _record_game(
        pod_names=answers["pod"], winner=answers["winner"], died_first=answers["died_first"],
        archenemy=None, end_turn=answers["end_turn"], win_method=answers["win_method"],
        date=answers["date"], notes=None, sim_games=args.sim_games, no_combos=args.no_combos,
    )


def _cmd_matchlog_list(args: argparse.Namespace) -> int:
    res = MatchLog().load()
    if not res.games and not res.errors:
        print("No games logged yet. Record one with "
              "`mtg matchlog add <pod…> --winner <deck> [--died-first <deck>] [--end-turn N]`.")
        return 0
    print(f"{len(res.games)} logged game(s):\n")
    for g in res.games:
        extra = []
        if g.died_first:
            extra.append(f"died-first {g.died_first}")
        if g.end_turn:
            extra.append(f"T{g.end_turn}")
        if g.win_method:
            extra.append(g.win_method)
        tail = ("  [" + ", ".join(extra) + "]") if extra else ""
        print(f"  {g.date}  {' · '.join(g.pod)}  → {g.winner}{tail}")

    wins = Counter(g.winner for g in res.games)
    played = Counter(slug for g in res.games for slug in g.pod)
    print("\nObserved win rate (raw, uncalibrated):")
    for slug in sorted(played, key=lambda s: -wins[s] / played[s]):
        print(f"  {slug:18} {wins[slug]}/{played[slug]}  ({wins[slug] / played[slug]:.0%})")
    if res.errors:
        print(f"\n⚠ {len(res.errors)} malformed line(s) skipped (fix or delete in the file):")
        for err in res.errors:
            print(f"  {err}")
    return 0


def _cmd_deck_diff(args: argparse.Namespace) -> int:
    def counts(arg: str) -> dict[str, int]:
        parsed = parse_deck(load_deck_text(arg))
        c: dict[str, int] = {}
        for e in parsed.entries:
            if e.section in ("commander", "main"):
                c[e.name] = c.get(e.name, 0) + e.quantity
        return c

    a, b = counts(args.deck_a), counts(args.deck_b)
    added = {n: b[n] - a.get(n, 0) for n in b if b[n] > a.get(n, 0)}
    removed = {n: a[n] - b.get(n, 0) for n in a if a[n] > b.get(n, 0)}

    print(f"Diff: {args.deck_a} → {args.deck_b}")
    if not added and not removed:
        print("  (identical decklists)")
        return 0
    print(f"\nAdded ({sum(added.values())}):")
    for n in sorted(added):
        print(f"  + {f'{added[n]}x ' if added[n] > 1 else ''}{n}")
    print(f"\nRemoved ({sum(removed.values())}):")
    for n in sorted(removed):
        print(f"  − {f'{removed[n]}x ' if removed[n] > 1 else ''}{n}")
    return 0


def _cmd_deck_save(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    slug = DeckLibrary().save(args.name, text)
    db = CardDatabase()
    store = InventoryStore()
    try:
        sync_decks(DeckLibrary(), db, store)  # the deck's cards now appear in inventory
        export_csv(store)
    finally:
        store.close()
        db.close()
    print(f"Saved deck as {slug!r} and synced its cards into the inventory. "
          f"Use it by name, e.g. `mtg deck analyze {slug}`.")
    return 0


def _cmd_deck_guide(args: argparse.Namespace) -> int:
    library = DeckLibrary()
    names = library.names() if args.all else [args.name]
    if not names or (not args.all and args.name is None):
        print("Specify a deck name or --all.", file=sys.stderr)
        return 1
    guides_dir = config.DATA_DIR / "guides"
    guides_dir.mkdir(parents=True, exist_ok=True)
    db = CardDatabase()
    cache = EdhrecCache()
    try:
        for name in names:
            deck = resolve_deck(db, parse_deck(load_deck_text(name)))
            deck.name = name  # title the guide after the saved deck
            combos = _find_deck_combos(deck)
            report = analyze(deck, included_combos=combos)
            sim = simulate(deck, games=args.games)

            async def fetch() -> list:
                async with EdhrecClient(cache=cache) as client:
                    return await client.commander_cards(report.commanders)

            edhrec: list = _run_network(fetch, [], "EDHREC")
            md = build_guide(deck, report, sim, combos, edhrec)
            path = guides_dir / f"{slugify(name)}.md"
            path.write_text(md, encoding="utf-8")
            print(f"Wrote {path}")
    finally:
        cache.close()
        db.close()
    return 0


def _cmd_deck_list(_: argparse.Namespace) -> int:
    names = DeckLibrary().names()
    if not names:
        print("No saved decks. Save one: `mtg deck save <name> <file>`.")
        return 0
    print("Saved decks:")
    for name in names:
        print(f"  {name}")
    return 0


def _cmd_deck_remove(args: argparse.Namespace) -> int:
    if DeckLibrary().remove(args.name):
        print(f"Removed saved deck {args.name!r}.")
        return 0
    print(f"No saved deck named {args.name!r}.", file=sys.stderr)
    return 1


def _is_legal_commander_card(card: Card) -> bool:
    tl = (card.type_line or "").lower()
    return (("legendary" in tl and "creature" in tl)
            or "can be your commander" in card.get_oracle_text().lower())


def _cmd_deck_build(args: argparse.Namespace) -> int:
    db = CardDatabase()
    store = InventoryStore()
    cache = EdhrecCache()
    try:
        commander = db.get_by_name(args.commander)
        if commander is None:
            print(f"No card named {args.commander!r}.", file=sys.stderr)
            return 1
        if not _is_legal_commander_card(commander):
            print(f"{commander.name} isn't a legal commander.", file=sys.stderr)
            return 1
        owned = store.available_oracles()  # new deck → only loose/Available cards

        async def fetch() -> list:
            async with EdhrecClient(cache=cache) as client:
                return await client.commander_cards([commander.name])

        edhrec = asyncio.run(fetch())
        deck = build_deck(commander, owned, db, edhrec, budget=args.budget,
                          owned_only=args.owned_only)
    finally:
        cache.close()
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
    items = []
    for path in args.files:
        items.extend(parse_inventory_csv(Path(path).read_text(encoding="utf-8")))
    db = CardDatabase()
    store = InventoryStore()
    try:
        inventory = resolve_inventory(db, items)  # these are the loose "Available" pool
        store.set_available(inventory.items)
        deck_counts = sync_decks(DeckLibrary(), db, store)  # merge registered decks
        csv_path = export_csv(store)
    finally:
        store.close()
        db.close()
    print(f"Imported {len(items):,} loose rows ({inventory.distinct_cards:,} distinct). "
          f"Unresolved: {len(inventory.unresolved)}")
    print(f"Synced {len(deck_counts)} registered deck(s): {', '.join(deck_counts) or '(none)'}")
    print(f"Unified inventory written to {csv_path}")
    for item in inventory.unresolved[:10]:
        print(f"  ? {item.name} ({item.set_code} {item.collector_number})")
    return 0


def _cmd_inventory_sync(_: argparse.Namespace) -> int:
    db = CardDatabase()
    store = InventoryStore()
    try:
        deck_counts = sync_decks(DeckLibrary(), db, store)
        csv_path = export_csv(store)
    finally:
        store.close()
        db.close()
    print(f"Synced {len(deck_counts)} deck(s) into inventory → {csv_path}")
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
            locs = store.locations(card.oracle_id)
            print(f"{card.name}: owned {store.owned(card.oracle_id)}")
            for loc, qty in sorted(locs.items()):
                tag = "(available)" if loc == "Available" else f"(in deck: {loc})"
                print(f"  x{qty} {tag}")
        else:
            avail = store.total_quantity("Available")
            total = store.total_quantity()
            print(f"Inventory: {store.distinct_cards():,} distinct cards, {total:,} total copies")
            print(f"  available (loose): {avail:,}   ·   committed to decks: {total - avail:,}")
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
    d_save = deck.add_parser("save", help="save a decklist under a name")
    d_save.add_argument("name")
    d_save.add_argument("file")
    d_save.set_defaults(func=_cmd_deck_save)
    deck.add_parser("list", help="list saved decks").set_defaults(func=_cmd_deck_list)
    d_remove = deck.add_parser("remove", help="delete a saved deck")
    d_remove.add_argument("name")
    d_remove.set_defaults(func=_cmd_deck_remove)
    d_diff = deck.add_parser("diff", help="compare two decks (added/removed cards)")
    d_diff.add_argument("deck_a", help="deck file or saved name")
    d_diff.add_argument("deck_b", help="deck file or saved name")
    d_diff.set_defaults(func=_cmd_deck_diff)
    d_guide = deck.add_parser("guide", help="compose a pilot's strategy guide (markdown)")
    d_guide.add_argument("name", nargs="?", help="saved deck name or file (or use --all)")
    d_guide.add_argument("--all", action="store_true", help="generate guides for every saved deck")
    d_guide.add_argument("--games", type=int, default=8000)
    d_guide.set_defaults(func=_cmd_deck_guide)
    d_show = deck.add_parser("show", help="parse + resolve a deck (file or saved name)")
    d_show.add_argument("file", help="deck file path or saved deck name")
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
    d_sim.add_argument("--no-combos", action="store_true",
                       help="skip the live combo lookup / turn-to-combo metric (faster, offline)")
    d_sim.set_defaults(func=_cmd_deck_simulate)

    battle = sub.add_parser("battle", help="heuristic 1v1/4-player matchup sim (NOT a rules engine)")
    battle.add_argument("decks", nargs="+", help="2 decks = 1v1, 3–4 = pod (saved names or paths)")
    battle.add_argument("--games", type=int, default=2000, help="match games to simulate")
    battle.add_argument("--sim-games", type=int, default=1500,
                        help="goldfish games per deck for the clock estimate")
    battle.add_argument("--seed", type=int, default=1)
    battle.add_argument("--preset", choices=("casual", "mid", "cedh"),
                        help="power-level preset: table coordination + threat-read sharpness "
                             "(casual = poorly-coordinated; cedh = gangs the archenemy hard)")
    battle.add_argument("--no-combos", action="store_true",
                        help="skip live combo lookup (faster / offline)")
    battle.add_argument("--calibrate", action="store_true",
                        help="sweep the interaction assumption + show model health instead of one result")
    battle.add_argument("--sensitivity", action="store_true",
                        help="honest joint uncertainty band: global SA over ALL tunable params (priors)")
    battle.add_argument("--sens-samples", type=int, default=64,
                        help="Latin-Hypercube samples for --sensitivity")
    battle.add_argument("--metagame", action="store_true",
                        help="pass a POOL of >4 decks: simulate every pod and run the fictitious-play "
                             "feedback loop so the table targets decks known to win (self-consistent meta)")
    battle.add_argument("--pod-size", type=int, default=4,
                        help="pod size for --metagame (default 4)")
    battle.set_defaults(func=_cmd_battle)

    matchlog = sub.add_parser(
        "matchlog", help="record + review real games (the corpus the battle sim is fit against)"
    ).add_subparsers(dest="matchlog_command", required=True)
    m_add = matchlog.add_parser("add", help="log a real game's result")
    m_add.add_argument("pod", nargs="+", help="2–4 saved deck names that played")
    m_add.add_argument("--winner", required=True, help="saved deck name that won")
    m_add.add_argument("--died-first", help="saved deck eliminated first (multiplayer)")
    m_add.add_argument("--end-turn", type=int, help="turn the game ended")
    m_add.add_argument("--win-method", choices=sorted(WIN_METHODS),
                       help="optional: how the game ended")
    m_add.add_argument("--archenemy", help="optional: the deck the table most feared")
    m_add.add_argument("--date", help="ISO date the game was played (default: today)")
    m_add.add_argument("--notes", help="freeform notes")
    m_add.add_argument("--sim-games", type=int, default=800,
                       help="goldfish games for the profile snapshot")
    m_add.add_argument("--no-combos", action="store_true",
                       help="skip live combo lookup in the snapshot (offline / faster)")
    m_add.set_defaults(func=_cmd_matchlog_add)
    m_form = matchlog.add_parser(
        "form", help="interactive fill-out form to log a game (friendlier than `add`)"
    )
    m_form.add_argument("--sim-games", type=int, default=800,
                        help="goldfish games for the profile snapshot")
    m_form.add_argument("--no-combos", action="store_true",
                        help="skip live combo lookup in the snapshot (offline / faster)")
    m_form.set_defaults(func=_cmd_matchlog_form)
    matchlog.add_parser("list", help="list logged games + observed win rates").set_defaults(
        func=_cmd_matchlog_list
    )
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
    i_import = inv.add_parser("import", help="import collection CSV(s) (e.g. ManaBox)")
    i_import.add_argument("files", nargs="+", help="one or more collection CSV files")
    i_import.set_defaults(func=_cmd_inventory_import)
    inv.add_parser("sync", help="re-merge registered decks into the inventory").set_defaults(
        func=_cmd_inventory_sync
    )
    i_show = inv.add_parser("show", help="inventory stats, or locations for --card")
    i_show.add_argument("--card", help="show owned count + where each copy lives")
    i_show.set_defaults(func=_cmd_inventory_show)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

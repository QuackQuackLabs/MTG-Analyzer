"""Dump the raw goldfish/analysis signals feeding each LOTR BattleProfile to find the miscalibration."""
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import load_deck_text
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_deck
from mtg_analyzer.simulation.battle import build_profile, _creature_count
from mtg_analyzer.simulation.goldfish import simulate
from mtg_analyzer.cli import _find_deck_combos

LOTR = ["Sauron", "Tom Bombadil", "Galadriel", "Gandalf the White", "Sméagol", "Frodo and Sam"]

db = CardDatabase()
try:
    print(f"{'Deck':18} {'arche':8} {'cmdrT':>6} {'comboT':>7} {'ncombo':>6} {'creat':>6} "
          f"{'brkt':>5} {'clock':>6} {'combos':>7}")
    for name in LOTR:
        deck = resolve_deck(db, parse_deck(load_deck_text(name)))
        combos = _find_deck_combos(deck)
        report = analyze(deck, included_combos=combos)
        sim = simulate(deck, combos=combos, games=1500)
        prof = build_profile(name, deck, report, sim)
        cmdr = sim.commander_turn.mean if sim.commander_turn else None
        ct = sim.combo_turn.mean if sim.combo_turn else None
        cc = sim.combo_count
        creatures = _creature_count(deck)
        print(f"{name:18} {prof.archetype:8} "
              f"{cmdr if cmdr is None else round(cmdr,2):>6} "
              f"{ct if ct is None else round(ct,2):>7} "
              f"{cc:>6} {creatures:>6} {report.bracket_estimate:>5} "
              f"T{prof.clock_mean:<5.1f} {len(report.combos):>7}")
        # show the actual combos found (the win the sim assumes)
        for cb in report.combos[:4]:
            desc = getattr(cb, "description", None) or getattr(cb, "name", "")
            print(f"      combo: {str(desc)[:80]}")
finally:
    db.close()

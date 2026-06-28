# -*- coding: utf-8 -*-
"""Head-to-head 1v1 matrix across all C(N,2) deck pairs over the saved-deck library
→ per-deck matchup tendencies (favored / even / careful) grouped by opponent archetype.
Feeds the guides' 'Matchup tendencies (1v1)' section. Writes JSON next to this script.

Run from app/ with the venv active:  python docs/research-assets/run_h2h_matchups.py
"""
import json
import os
import time
from itertools import combinations

from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.cli import _find_deck_combos
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import DeckLibrary, load_deck_text
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_deck
from mtg_analyzer.simulation.battle import build_profile, simulate_match
from mtg_analyzer.simulation.goldfish import simulate

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h2h_matchups.json")
GAMES = 3000
SIM_GAMES = 1500
SEED = 1

db = CardDatabase()
names = DeckLibrary().names()
prof, arche = {}, {}
t0 = time.time()
for n in names:
    deck = resolve_deck(db, parse_deck(load_deck_text(n)))
    combos = _find_deck_combos(deck)
    report = analyze(deck, included_combos=combos)
    sim = simulate(deck, combos=combos, games=SIM_GAMES)
    p = build_profile(n, deck, report, sim)
    prof[n], arche[n] = p, p.archetype
db.close()
print(f"profiles built in {time.time()-t0:.1f}s", flush=True)

h2h = {a: {} for a in names}
for a, b in combinations(names, 2):
    by = {d.name: d.win_rate for d in simulate_match([prof[a], prof[b]], games=GAMES, seed=SEED).decks}
    h2h[a][b], h2h[b][a] = by[a], by[b]

out = {"games": GAMES, "seed": SEED, "decks": {}}
for a in names:
    opp = sorted(({"name": b, "archetype": arche[b], "win": round(h2h[a][b], 3)}
                  for b in names if b != a), key=lambda o: o["win"], reverse=True)
    by_arch = {}
    for o in opp:
        by_arch.setdefault(o["archetype"], []).append(o["win"])
    out["decks"][a] = {
        "archetype": arche[a],
        "avg_win": round(sum(o["win"] for o in opp) / len(opp), 3),
        "by_archetype": {k: round(sum(v) / len(v), 3) for k, v in by_arch.items()},
        "opponents": opp,
    }

json.dump(out, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(f"WROTE {OUT}\n")
for a in names:
    dd = out["decks"][a]
    fav = [o["name"].split()[0] for o in dd["opponents"] if o["win"] >= 0.55]
    care = [o["name"].split()[0] for o in dd["opponents"] if o["win"] <= 0.45]
    print(f"{a:26} ({dd['archetype']:8}) avg {dd['avg_win']:>4.0%} | "
          + " ".join(f"{k}:{v:.0%}" for k, v in sorted(dd["by_archetype"].items(), key=lambda x: -x[1]))
          + f"  | favored: {', '.join(fav) or '—'}")

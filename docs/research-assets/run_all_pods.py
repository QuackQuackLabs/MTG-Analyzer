"""Run every 4-deck pod (C(6,4)=15) of the LOTR decks through the battle simulator and summarize."""
from itertools import combinations
from pathlib import Path

from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import load_deck_text
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_deck
from mtg_analyzer.simulation.battle import build_profile, simulate_match
from mtg_analyzer.simulation.goldfish import simulate
from mtg_analyzer.cli import _find_deck_combos

LOTR = ["Frodo and Sam", "Galadriel", "Gandalf the White", "Sauron", "Sméagol", "Tom Bombadil"]
GAMES = 2000
SIM_GAMES = 1500
SEED = 1

# Build each deck's BattleProfile once (reuse across all pods).
db = CardDatabase()
profiles = {}
try:
    for name in LOTR:
        deck = resolve_deck(db, parse_deck(load_deck_text(name)))
        combos = _find_deck_combos(deck)
        report = analyze(deck, included_combos=combos)
        sim = simulate(deck, combos=combos, games=SIM_GAMES)
        profiles[name] = build_profile(name, deck, report, sim)
        p = profiles[name]
        print(f"  profiled {name:18} {p.archetype:9} clock~T{p.clock_mean:<4.1f} "
              f"int {p.interaction:<2} draw {p.card_advantage:<2} tutors {p.tutors} "
              f"{'COMBO' if p.has_combo else ''}")
finally:
    db.close()

# Run all 15 pods.
print(f"\nRunning {len(list(combinations(LOTR, 4)))} pods x {GAMES} games each...\n")
# per-deck aggregates
appearances = {n: 0 for n in LOTR}
winrate_sum = {n: 0.0 for n in LOTR}
winrates = {n: [] for n in LOTR}
archenemy_sum = {n: 0.0 for n in LOTR}
pod_rows = []

for pod in combinations(LOTR, 4):
    res = simulate_match([profiles[n] for n in pod], games=GAMES, seed=SEED)
    by_name = {d.name: d for d in res.decks}
    winner = max(res.decks, key=lambda d: d.win_rate)
    pod_rows.append((pod, by_name, winner, res.avg_game_length))
    for n in pod:
        d = by_name[n]
        appearances[n] += 1
        winrate_sum[n] += d.win_rate
        winrates[n].append(d.win_rate)
        archenemy_sum[n] += d.archenemy_rate

# ---- per-pod table ----
print("=" * 92)
print("PER-POD RESULTS (win% per deck; bold = pod winner)")
print("=" * 92)
for pod, by_name, winner, avglen in pod_rows:
    cells = []
    for n in pod:
        wr = by_name[n].win_rate
        mark = "*" if n == winner.name else " "
        cells.append(f"{n.split()[0][:9]:>9}{mark}{wr:>4.0%}")
    print(f"  T~{avglen:<4.1f} " + "  ".join(cells))

# ---- per-deck summary ----
print("\n" + "=" * 92)
print("PER-DECK SUMMARY (averaged over the 10 pods each deck appears in)")
print("=" * 92)
print(f"  {'Deck':18} {'pods':>4} {'avg win%':>9} {'min':>5} {'max':>5} {'avg archenemy%':>15} {'pod wins':>9}")
pod_win_count = {n: 0 for n in LOTR}
for pod, by_name, winner, _ in pod_rows:
    pod_win_count[winner.name] += 1
ranking = sorted(LOTR, key=lambda n: winrate_sum[n] / appearances[n], reverse=True)
for n in ranking:
    a = appearances[n]
    avg = winrate_sum[n] / a
    print(f"  {n:18} {a:>4} {avg:>8.0%} {min(winrates[n]):>5.0%} {max(winrates[n]):>5.0%} "
          f"{archenemy_sum[n]/a:>14.0%} {pod_win_count[n]:>9}")

# fair share in a 4-pod is 25%
print("\n  (Fair share in a 4-player pod = 25%. 'pod wins' = pods where this deck had the highest win%.)")

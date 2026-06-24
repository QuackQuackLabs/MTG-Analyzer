"""Experiment: does using the real combo-assembly turn as the clock (instead of commander-deploy
turn) move the 15-pod ranking toward Jacob's experiential ranking? No source edits — overrides the
profile clock in-memory."""
from itertools import combinations

from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import load_deck_text
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_deck
from mtg_analyzer.simulation.battle import build_profile, simulate_match
from mtg_analyzer.simulation.goldfish import simulate
from mtg_analyzer.cli import _find_deck_combos

LOTR = ["Frodo and Sam", "Galadriel", "Gandalf the White", "Sauron", "Sméagol", "Tom Bombadil"]
JACOB = ["Sauron", "Tom Bombadil", "Galadriel", "Gandalf the White", "Sméagol", "Frodo and Sam"]
GAMES, SIM_GAMES, SEED = 2000, 1500, 1

db = CardDatabase()
base, combo_turns = {}, {}
try:
    for name in LOTR:
        deck = resolve_deck(db, parse_deck(load_deck_text(name)))
        combos = _find_deck_combos(deck)
        report = analyze(deck, included_combos=combos)
        sim = simulate(deck, combos=combos, games=SIM_GAMES)
        base[name] = build_profile(name, deck, report, sim)
        combo_turns[name] = sim.combo_turn.mean if sim.combo_turn else None
finally:
    db.close()

def run_all(profiles):
    wr_sum = {n: 0.0 for n in LOTR}
    app = {n: 0 for n in LOTR}
    for pod in combinations(LOTR, 4):
        res = simulate_match([profiles[n] for n in pod], games=GAMES, seed=SEED)
        for d in res.decks:
            wr_sum[d.name] += d.win_rate
            app[d.name] += 1
    return {n: wr_sum[n] / app[n] for n in LOTR}

def show(title, avg):
    rank = sorted(LOTR, key=lambda n: avg[n], reverse=True)
    print(f"\n{title}")
    for i, n in enumerate(rank, 1):
        jrank = JACOB.index(n) + 1
        print(f"  {i}. {n:18} {avg[n]:>5.0%}   (Jacob #{jrank})")
    # Spearman-ish: sum of |rank diff|
    diff = sum(abs((i + 1) - (JACOB.index(n) + 1)) for i, n in enumerate(rank))
    print(f"   rank-distance from Jacob's order (sum |Δrank|, 0=perfect, 18=worst): {diff}")

# Variant A: current model (commander-deploy clock)
show("CURRENT (commander-deploy clock):", run_all(base))

# Variant B: clock = combo-assembly turn for every combo deck
varB = {}
for n in LOTR:
    p = base[n]
    ct = combo_turns[n]
    varB[n] = p.model_copy(update={"clock_mean": round(ct, 2)}) if (p.has_combo and ct) else p
show("EXPERIMENT B (clock = real combo-assembly turn):", run_all(varB))

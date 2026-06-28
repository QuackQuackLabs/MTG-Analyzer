# -*- coding: utf-8 -*-
"""Full-pool metagame: every C(N,4) four-deck pod across ALL saved decks.

Runs the naive pass and the Stage 3c/3d fictitious-play loop (mirrors
`simulation.battle.simulate_metagame`) over the whole saved-deck library, and
prints the per-deck power ranking + the naive/informed/range data used to write
each guide's `Pod matchup outlook (sim)` section.

Parallel + spawn-safe: every `BattleProfile` is built ONCE in the master (the
only place that touches the network for combo lookup) and shipped to workers via
a Pool initializer, so workers never rebuild or hit Commander Spellbook. A JSON
summary is written next to this script.

Run from `app/` with the venv active:  python docs/research-assets/run_all_pods_fullpool.py
"""
import json
import os
import time
from itertools import combinations
from multiprocessing import Pool

import mtg_analyzer.simulation.battle_params as P
from mtg_analyzer.simulation.battle import simulate_match

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fullpool_metagame.json")
GAMES = 1000
SIM_GAMES = 1500
SEED = 1
POD = 4
WORKERS = max(2, (os.cpu_count() or 4) - 2)

_PROFILES: dict = {}  # worker-global, set by the Pool initializer


def _init(profiles):
    global _PROFILES
    _PROFILES = profiles


def _task(arg):
    pod, priors, weight = arg
    P.WINRATE_PRIOR_W = weight
    profs = []
    for n in pod:
        pr = _PROFILES[n]
        pr.win_prior = priors[n]
        profs.append(pr)
    res = simulate_match(profs, games=GAMES, seed=SEED)
    return pod, {d.name: (d.win_rate, d.archenemy_rate) for d in res.decks}


def _deck_names():
    from mtg_analyzer.data.deck_library import DeckLibrary
    return DeckLibrary().names()


def build_profiles(names):
    from mtg_analyzer.analysis.report import analyze
    from mtg_analyzer.cli import _find_deck_combos
    from mtg_analyzer.data.db import CardDatabase
    from mtg_analyzer.data.deck_library import load_deck_text
    from mtg_analyzer.ingest.decklist import parse_deck
    from mtg_analyzer.ingest.resolve import resolve_deck
    from mtg_analyzer.simulation.battle import build_profile
    from mtg_analyzer.simulation.goldfish import simulate

    db = CardDatabase()
    profiles = {}
    t0 = time.time()
    for name in names:
        deck = resolve_deck(db, parse_deck(load_deck_text(name)))
        combos = _find_deck_combos(deck)
        report = analyze(deck, included_combos=combos)
        sim = simulate(deck, combos=combos, games=SIM_GAMES)
        profiles[name] = build_profile(name, deck, report, sim)
        p = profiles[name]
        print(f"  profiled {name:28} {p.archetype:9} clock~T{p.clock_mean:<4.1f} "
              f"int {p.interaction:<2} draw {p.card_advantage:<2} tutors {p.tutors} "
              f"combo={p.has_combo}", flush=True)
    db.close()
    print(f"profiles built in {time.time()-t0:.1f}s", flush=True)
    return profiles


def sweep(pool, names, pods, priors, weight):
    args = [(pod, priors, weight) for pod in pods]
    wsum = {n: 0.0 for n in names}
    aesum = {n: 0.0 for n in names}
    appear = {n: 0 for n in names}
    per_pod = {}
    for pod, d in pool.imap_unordered(_task, args, chunksize=8):
        per_pod[pod] = d
        for n in pod:
            wr, ae = d[n]
            wsum[n] += wr
            aesum[n] += ae
            appear[n] += 1
    return ({n: wsum[n] / appear[n] for n in names},
            {n: aesum[n] / appear[n] for n in names}, per_pod)


def main():
    names = _deck_names()
    profiles = build_profiles(names)
    names = list(profiles)
    pods = list(combinations(names, POD))
    fair = 1.0 / POD
    print(f"{len(pods)} pods x {GAMES} games", flush=True)

    pool = Pool(WORKERS, initializer=_init, initargs=(profiles,))

    # naive (no prior; table does not adapt)
    naive_wr, naive_ae, naive_pods = sweep(pool, names, pods, {n: 0.0 for n in names}, 0.0)
    pod_winner = {pod: max(d, key=lambda n: d[n][0]) for pod, d in naive_pods.items()}
    pod_wins = {n: 0 for n in names}
    for w in pod_winner.values():
        pod_wins[w] += 1
    naive_range = {}
    for n in names:
        rows = sorted(((pod, d[n][0]) for pod, d in naive_pods.items() if n in pod),
                      key=lambda r: r[1])
        worst, best = rows[0], rows[-1]
        naive_range[n] = {"min": worst[1], "min_pod": [x for x in worst[0] if x != n],
                          "max": best[1], "max_pod": [x for x in best[0] if x != n]}
    naive_rank = {n: i + 1 for i, n in enumerate(sorted(names, key=lambda n: naive_wr[n], reverse=True))}

    # metagame: damped fictitious play (learn power)
    priors = {n: profiles[n].win_prior for n in names}
    prev, converged, used = None, False, 0
    for it in range(P.METAGAME_ITERS):
        used = it + 1
        wr, _, _ = sweep(pool, names, pods, priors, P.METAGAME_PRIOR_WEIGHT)
        priors = {n: P.METAGAME_DAMP * priors[n] + (1 - P.METAGAME_DAMP) * (wr[n] - fair) for n in names}
        if prev is not None and max(abs(wr[n] - prev[n]) for n in names) < 0.01:
            converged = True
            break
        prev = dict(wr)
    power = dict(priors)

    # informed reporting pass (table KNOWS power)
    inf_wr, inf_ae, _ = sweep(pool, names, pods, power, P.METAGAME_INFORMED_WEIGHT)
    pool.close()
    pool.join()

    order = sorted(names, key=lambda n: power[n], reverse=True)
    power_rank = {n: i + 1 for i, n in enumerate(order)}
    out = {"games": GAMES, "pods": len(pods), "pod_size": POD, "seed": SEED,
           "iterations": used, "converged": converged, "fair": fair, "decks": {}}
    for n in names:
        pr = profiles[n]
        out["decks"][n] = {
            "archetype": pr.archetype, "clock_mean": pr.clock_mean, "has_combo": pr.has_combo,
            "interaction": pr.interaction, "card_advantage": pr.card_advantage, "tutors": pr.tutors,
            "naive_win": round(naive_wr[n], 4), "naive_rank": naive_rank[n],
            "naive_archenemy": round(naive_ae[n], 4), "pod_wins": pod_wins[n],
            "naive_min": round(naive_range[n]["min"], 4), "naive_min_pod": naive_range[n]["min_pod"],
            "naive_max": round(naive_range[n]["max"], 4), "naive_max_pod": naive_range[n]["max_pod"],
            "power_rank": power_rank[n], "power_level": round(power[n], 3),
            "informed_win": round(inf_wr[n], 4), "informed_archenemy": round(inf_ae[n], 4)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWROTE {OUT}")
    # Canonical simulation-results table (docs/sim-results-table-spec.md).
    from mtg_analyzer.simulation.battle import power_tier
    print(f"\n{len(pods)} {POD}-deck pods · {GAMES} games/pod · seed {SEED} · informed table · "
          "heuristic — relative, not predictive\n")
    print(f"  {'#':>2}  {'Deck':28} {'Tier':>4}  {'Naive':>6}  {'Informed':>8}  {'Arch%':>6}")
    for n in order:
        dd = out["decks"][n]
        print(f"  {dd['power_rank']:>2}  {n:28} {power_tier(dd['power_level']):>4}  "
              f"{dd['naive_win']:>6.0%}  {dd['informed_win']:>8.0%}  {dd['informed_archenemy']:>6.0%}")


if __name__ == "__main__":
    main()

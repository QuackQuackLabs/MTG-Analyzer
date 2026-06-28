# Simulation-results table — canonical format

The standard for **every** table that reports battle/metagame simulation results — the CLI
(`mtg battle --metagame`, single-pod `mtg battle`), the strategy-guide "Pod matchup outlook"
sections, and any future web view. One skeleton everywhere; surfaces show a consistent subset, never
a reordering. Researched + chosen 2026-06-25 (see project-plan.md status log).

## Why this shape (evidence)

- **Lead with one headline outcome, not every metric.** 17Lands surfaces the single least-biased
  win-rate stat and suppresses sub-sample-threshold values rather than dumping all variants
  ([17Lands](https://blog.17lands.com/posts/using-win-rate-data/)).
- **Tiers carry the ranking.** MTG metagame sites (MTGGoldfish, mtgdecks, Untapped) group decks into
  S/A/B or 1/2/3 tiers — a signed internal prior like `+0.12` means nothing to a player. Strength is a
  **tier**, kept distinct from the build-based **Bracket** (1–5) `analyze()` already computes.
- **Never a bare point estimate.** A win% without a band/baseline is misleading at finite sample
  ("55% over 200 games" could be 48–62%). We report **Naive vs Informed** — their gap *is* the honest
  band (the unpoliced ceiling vs. the policed, realistic outcome).
- **Table-design science:** right-align numerics, one fixed precision per column, sort by the headline
  metric with the rank reflecting it, bold the focal row
  ([Ström](https://medium.com/mission-log/design-better-data-tables-430a30a00d8c),
  [A List Apart](https://alistapart.com/article/web-typography-tables/)).

## Caption (always, one line, above the table)

```
‹N› ‹k›-deck pods · ‹G› games/pod · seed ‹s› · informed table · heuristic — relative, not predictive
```

For a single pod: `‹k›-player pod · ‹G› games · seed ‹s› · heuristic — relative, not predictive`.

## Columns

Core skeleton (in this order; numerics right-aligned, fixed precision; focal deck **bold**):

| Slot | Column | Notes |
|---|---|---|
| Identity | **#** | rank by the headline metric (learned power for aggregate; win% for single pod) |
| Identity | **Deck** | the only left-aligned column |
| Strength | **Tier** | S→D from learned meta strength (`power_tier`); *not* the build Bracket |
| Outcome | **Naive** | win% vs. an unadapting table (the unpoliced baseline) |
| Outcome | **Informed** | win% once the table targets known power — the realistic read |
| Role | **Arch%** | share of turns the table gangs this deck (multiplayer) |

Surface-specific context columns may be **appended** (never inserted/reordered):

- **Single pod** (no learned tier / naive-vs-informed): use `# · Deck · Win% · band · Arch% · Methods`,
  where `band` is the interaction-only or `--sensitivity` joint band and `Methods` is the
  win-condition mix (combo/beatdown/attrition).
- **Guides:** the full core table, this deck's row bold, followed by the deck-specific
  naive/informed/range/takeaway bullets.

## Tier thresholds (`power_tier`, in `simulation/battle.py`)

On the learned power level (`win_rate − 1/pod_size`, damped). Midpoint cutoffs so two decks that
*display* the same rounded power can't split across a boundary:

| Tier | Power level | Meaning |
|---|---|---|
| **S** | ≥ +0.085 | dominant — above fair even when targeted |
| **A** | +0.025 … +0.085 | strong |
| **B** | −0.025 … +0.025 | fair (≈ 1/N) |
| **C** | −0.085 … −0.025 | weak |
| **D** | < −0.085 | fringe |

## Reading note (include near every results table)

> **Tier/power = realized strength; win rate is the policed outcome.** A top-tier deck's *Informed*
> win compresses *because* it draws the heat (high Arch%); an under-the-radar deck can post a high
> Informed win without being strong (it inherits wins once the table targets the real powers). Read
> Tier and Informed together, not either alone.

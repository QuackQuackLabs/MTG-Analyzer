# LOTR Pod Validation — empirical finding: the battle sim ranks decks ~inverted (2026-06-22)

> **Status: diagnostic finding, not yet fixed.** Captures a validation run of the Phase 9 battle
> simulator against all six LOTR decks + an experienced-player ground-truth ranking. The headline:
> the sim's ranking is **near-perfectly inverted** vs. real-play experience, and the root cause is the
> already-documented-but-unshipped **workstream A4** (retire the creature-count archetype classifier;
> derive the clock from `combo_turn` vs `commander_turn`). See
> [simulator-realism-research.md](simulator-realism-research.md) §A4 and the Phase 9 tracker in
> [project-plan.md](../project-plan.md).

## What was run

All `C(6,4) = 15` four-player pods over the six saved LOTR decks (Frodo and Sam, Galadriel, Gandalf
the White, Sauron, Sméagol, Tom Bombadil), 2000 games/pod, seed 1, combos on. Each deck appears in 10
pods; reported win% is averaged over those 10. Fair share in a 4-pod = 25%.

## Result: sim vs. experienced-player ranking

| Player rank (experience) | Sim rank | Sim avg win% | Pod wins (of 10) |
|---|---|---|---|
| 1. Sauron        | 6th | 4%  | 0 |
| 2. Tom Bombadil  | 3rd | 21% | 1 |
| 3. Galadriel     | 4th | 17% | 0 |
| 4. Gandalf       | 5th | 5%  | 0 |
| 5. Sméagol       | 2nd | 28% | 4 |
| 6. Frodo and Sam | **1st** | **74%** | **10** |

Rank-distance (sum of |Δrank|, 0 = identical, 18 = perfectly inverted): **16/18.** The sim is pointing
almost exactly the wrong way.

## Root cause — the "clock" measures commander DEPLOY turn, not WIN turn

Raw signals dumped per deck (goldfish, 1500 games):

| Deck | Cmdr online | **Combo assembles** | Archetype (sim) | → Clock used | Sim win% |
|---|---|---|---|---|---|
| Frodo & Sam | T2.0 | T9.1  | aggro    | **T3.5** | 74% |
| Sméagol     | T3.3 | T10.9 | aggro    | T4.8 | 28% |
| Galadriel   | T5.1 | T8.8  | combo    | T7.7 | 17% |
| Tom Bombadil| T5.3 | T8.5  | combo    | T7.7 | 21% |
| Gandalf     | T5.0 | T9.6  | midrange | T8.4 | 5%  |
| Sauron      | T7.0 | T10.6 | combo    | T9.6 | 4%  |

Two compounding errors:

1. **The clock is dominated by how early the *commander* hits the table, not how fast the deck wins.**
   The real win speeds (combo-assembly turns) are all bunched **T8.5–T10.9** — the decks are nearly
   identical in kill-speed. But the clock that drives the whole sim ranges T3.5→T9.6, and that spread is
   almost entirely commander *deploy* turn. Decks with expensive commanders (Sauron T7, Tom T5.3) read
   as "slow = weak," which is backwards for resilient grind/value decks.

2. **Aggro decks with an incidental combo win *by combo* at their fast combat clock.** Frodo's commander
   lands T2 → classed `aggro` (the `creatures ≥ 27 → aggro` rule) → the combo-clock blend is *skipped*
   (the `archetype != "aggro"` gate in `build_profile`) → clock stays T3.5. But in `_play_match`, because
   `has_combo` is true, its first unanswered attempt is an **instant combo win at T3.5** — even though its
   combo can't actually assemble until T9. It gets aggro speed *and* combo lethality. This is exactly the
   Sméagol/Frodo mislabel that research workstream **A4** flagged.

## Experiment — fixing the clock source moves the ranking toward truth

Re-ran all 15 pods with one change: for combo decks, set the clock to the **real combo-assembly turn**
(`combo_turn`) instead of the commander-deploy-based clock. No other changes.

| | Current model | Clock = combo-assembly turn |
|---|---|---|
| Frodo & Sam | 74% | 36% |
| Tom Bombadil | 21% | 50% |
| Galadriel | 17% | 36% |
| Sméagol | 28% | 6% |
| Gandalf | 5% | 11% |
| Sauron | 4% | 12% |
| **Rank-distance from player ranking** | **16/18** | **10/18** |

The one change roughly halves the error: Frodo drops 74%→36%, Tom/Galadriel rise into the top, matching
the player's high ranks. **Residual error is diagnostic of the deeper problem:** Sauron (player #1) is
still near the bottom and Sméagol collapses — because the model is **monocausal on speed**. It treats
interaction (Sauron has 13), resilience, protection, card advantage, and inevitability as minor nudges
on a clock-determined outcome. The player's ranking rewards exactly those. Closing the rest of the gap
needs the architecture work in [simulator-realism-research.md](simulator-realism-research.md)
(intransitive matchups §B, honest multi-factor equity, politics §F) — not another parameter tweak.

## Recommended next steps (in priority order)

1. **Ship A4** — retire the `creatures ≥ 27 → aggro` classifier; derive archetype + clock from
   `combo_turn` vs `commander_turn`. Decouple "commander-online turn" (a *setup* signal) from "win
   turn" (the *clock*). Gate the combo-win path on `combo_turn`, so an aggro deck that merely contains a
   combo wins by *beatdown* at its combat clock, not by *combo* at that clock. *(biggest single fix —
   ~16→10 rank-distance on its own)*
2. **Re-weight equity away from pure speed** toward interaction density, resilience/protection, and
   inevitability — the spread of real win-speeds here is small, so the differentiator *should* be
   strategy, not clock. (Workstreams B + the multi-factor threat in the politics model.)
3. **Capture this player ranking as the first calibration anchor** (workstream H / Phase 9C is blocked
   on exactly this kind of ground truth). An ordinal "Sauron > Tom > Galadriel > Gandalf > Sméagol >
   Frodo" is a valid stylized-fact filter even without full game logs.

## Reproduce

Reproduction scripts archived in [research-assets/](research-assets/):
- [`run_all_pods.py`](research-assets/run_all_pods.py) — runs all 15 pods + the per-deck summary table.
- [`diagnose.py`](research-assets/diagnose.py) — dumps the raw goldfish signals (the clock-source table above).
- [`experiment.py`](research-assets/experiment.py) — the clock-source counterfactual (16→10 rank-distance).

Run from `app/` with the venv active: `python docs/research-assets/run_all_pods.py`. Equivalent CLI
spot-check: `mtg battle <four decks> --games 2000`.

# Battle Simulator — Real-Game Calibration & Fitting (Phase 9C, final item)

**Status:** planned (decisions locked 2026-06-20). **Depends on:** the shipped battle simulator
(`simulation/battle.py`, `battle_params.py`) and the anchor fixtures (`tests/test_battle.py`).
**Relationship:** completes Phase 9C — fits the hand-tuned `battle_params` to *observed* games so the
model's win rates reflect the user's actual table, not just "feels intuitive."

---

## 0. The problem

The simulator has ~20 free parameters, currently hand-tuned. "Fitting" = record real pod outcomes,
then adjust a **small subset** of params by maximum likelihood so the simulator assigns high
probability to the winners actually observed. The design (battle-simulator-design.md §4) calls this
the "lightweight logistic fit."

**The only blocker is data.** The logging infrastructure is not blocked and is built first, so the
user can start recording games immediately; the fit engine follows once a corpus exists.

## 1. Locked decisions (2026-06-20)

| Decision | Choice | Implication |
|---|---|---|
| Log granularity | **Standard** | Per game: pod + winner + died-first + end-turn. Optional rich fields tolerated but not required. Fit can target win rate AND elimination/length. |
| Fit aggressiveness | **Anchor-protected nudge** | Regularize toward current defaults; a fitted param set that breaks the 4 anchor fixtures is **rejected**. Sparse data nudges, never blows up calibration. Fitted params written to a reversible `data/`-local override. |

## 2. Work breakdown (dependency order)

### 9C-1 · Logging infrastructure — DONE (2026-06-20)
- `models/match_log.py` — `LoggedGame`: `date`, `pod: list[str]` (saved-deck slugs), `winner`,
  `died_first`, `end_turn`, optional `win_method`/`archenemy`, and the **full** `profiles:
  dict[str, BattleProfile]` snapshot as-played (upgraded from a hash → stores the whole profile, so
  the corpus survives deck drift AND mapper changes at zero user cost). Validates winner/died-first/
  archenemy ∈ pod, pod size 2–4, profile coverage, known win-method.
- `data/match_log.py` — append-only JSONL at `data/match_log.jsonl` (hand-editable, gitignored).
  `load()` validates every line and returns a `LoadResult(games, errors)`; malformed rows are
  surfaced with line numbers, never silently dropped.
- **Deck-drift detection (deferred to fit time)** — the full per-game profile snapshot is what makes
  this possible: 9C-2 compares it against a freshly-built profile and down-weights drifted games.
- CLI (named `matchlog`, not `battle log` — `battle` takes a positional deck list, so a nested
  subcommand would collide):
  - **`mtg matchlog form`** — the friendly path: an interactive fill-out form run after each game.
    Picks the pod from a numbered list of saved decks, prompts field by field, re-asks on bad input,
    shows a summary + confirm before writing. No flags/schema to remember. (Selection parsing is a
    pure `_select_indices`; I/O is injected so the flow is unit-tested without a TTY.)
  - **`mtg matchlog add <pod…> --winner <deck> [--died-first <deck>] [--end-turn N] [--win-method M]
    [--archenemy <deck>] [--no-combos]`** — the scriptable path (both share one `_record_game`).
  - **`mtg matchlog list`** — games + raw observed win rates + progress toward a fittable corpus.

### 9C-2 · Fit engine — needs the corpus
- **Loss:** negative log-likelihood of observed winners under simulated win-probabilities (proper
  scoring rule); + an auxiliary died-first NLL term when that field is present.
- **Fittable subset (~3–4 knobs, kept tiny to resist overfitting):** `INTERACTION_ANSWER_BASE`,
  `ANSWER_COORDINATION` (the F2 free-rider/coordination factor — superseded the old flat
  `POLITICS_ARCHENEMY_ANSWER`), `THREAT_PROXIMITY_W`, optionally the archetype clock offsets.
  Everything else stays fixed.
- **Optimizer:** derivative-free (scipy Nelder-Mead — already a dep). Each eval re-runs the sim over
  the logged pods. Regularization: penalty on deviation from current defaults (strength tuned to
  corpus size — thinner data → stronger pull to defaults).
- CLI: `mtg battle fit` → fitted values, before/after loss, and the win-rate shift on real pods.

### 9C-3 · Apply + guardrail
- **Anchor gate:** run the 4 anchor fixtures against any candidate fit; reject/​warn on failure.
- Write fitted params to a `data/`-local override loaded over the defaults (separable, reversible);
  never edit `battle_params.py` source.

## 3. What unblocks the work (user's part)

1. **Corpus size.** Fitting ~3 global params to a stable directional result needs ~**30–45** logged
   games; ~**60–80** for confidence. A fixed playgroup reaches this over a couple months; logging is
   one CLI command per game.
2. **Keep decks saved.** Fitting joins on saved-deck names — log games with decks registered via
   `mtg deck save`.
3. Record the **Standard** fields each game (pod + winner + died-first + end-turn).

## 4. Risks & mitigations

- **Overfitting sparse data** → tiny fittable subset + regularization toward current values.
- **Deck drift** → per-game profile-hash; stale games down-weighted.
- **Bad calibration** → anchor fixtures as a hard gate; report fit confidence; reversible override.

## 5. Phasing

- **9C-1** (logging infra) — buildable now; unblocks recording. ~1 session.
- **9C-2 + 9C-3** (fit engine + guardrail) — once ~30+ games are logged. ~1–2 sessions.

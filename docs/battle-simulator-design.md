# Battle Simulator — Design Scope (original design; largely shipped)

> **⚠ HISTORICAL DESIGN DOC.** This is the *original* Phase 9 design draft. Most of it shipped; its
> Phase A–D plan (§8) is **superseded** by the staged roadmap (Stages 0–3 + the A–H continuity map),
> which now lives in [project-plan.md](../project-plan.md) → Phase 9 — the single source of truth and
> live status. Kept for the *why* behind the BattleProfile abstraction, the match loop, and the
> calibration/honesty discipline — all still current. The research backing is
> [simulator-research.md](simulator-research.md).

**Relationship to existing sim:** extends `simulation/goldfish.py` (single-deck consistency) into a
heuristic **deck-vs-deck match** model for **1v1** and **4-player** Commander.

---

## 0. The honest framing (read first)

This is a **heuristic, statistical** simulator, **not a rules engine**. It is bound by the project's
standing decision (plan §2, golden rule #5): *MTG is Turing-complete; a faithful engine is a
multi-year effort and, if ever needed, we reuse XMage (MIT) — not build our own.*

So the battle simulator **abstracts each deck to a parameter vector** ("BattleProfile") and simulates
the *dynamics* of a game — clock, interaction, card advantage, resilience, politics — **not** the
cards. It will never tell you "Swords killed Craterhoof." It estimates **relative match equity** the
way the goldfish sim estimates relative consistency: useful for comparison and tuning, **banded and
calibrated**, never a card-accurate oracle.

**Non-goals (explicit):**
- No stack, priority, targeting legality, or card-by-card resolution.
- Not card-accurate; abstracts archetypes, not silver bullets (a specific hatebear that wrecks one
  deck is invisible to it).
- Not a playtest replacement — a *relative-comparison and tuning* tool.

Every output ships with its **parameter assumptions** and a **sensitivity band**. We learned why in
testing: adding a single interaction check swung a deck from 86→53 wins. That swing **is** the point —
interaction dominates outcomes and is exactly what a goldfish sim omits. We model it explicitly and
report the uncertainty rather than a fake point-estimate winner.

---

## 1. BattleProfile — abstract a deck to numbers we already compute

Derived entirely from **existing** signals (no new external data): `analyze()` (DeckReport:
category counts, bracket, combos, identity), `simulate()` (SimResult: commander-online turn,
keepable%, screw), and `categorize()`.

| Field | Meaning | Derived from |
|---|---|---|
| `clock` (mean, sd) | turn the deck can *win* by, goldfishing | goldfish commander-online turn + archetype offset |
| `archetype` | combo / aggro / midrange / control / grind | creatures count, combos present, curve shape, bracket |
| `counters` | stack-interaction budget | `counterspell` category count |
| `spot_removal` | answers a threat/combo piece | `removal` count |
| `sweepers` | resets a go-wide board | `board_wipe` count |
| `protection` | resists disruption | Teferi's/Heroic/Grand Abolisher/hexproof-commander flags |
| `card_advantage` | refuel rate (replaces spent interaction/threats) | `draw` count + engine signals |
| `mana` | stability / explosiveness | ramp count + goldfish keepable/screw |
| `resilience` | rebuild after a wipe/disruption | combo redundancy, recursion, threat count |
| `combo` | P(assemble an instant-win once "online") | `combos` present + `tutor` count |
| `threat_level` | scalar for 4-player target selection | bracket + clock + combo |

The new module is a **mapper** (DeckReport+SimResult → BattleProfile) plus a **match loop**. The
mapping constants live in one documented file (`battle_params.py`) so they're tunable and auditable.

---

## 2. Match loop (heuristic, turn-based, abstract resources)

**Per-player state:** life (40 EDH / 20-ish for a 1v1 proxy), mana (sampled from the goldfish mana
model), `interaction_reserve` (counters+removal remaining, refilled by `card_advantage`),
`board_development` scalar, `online` flag (commander + key pieces out), `eliminated` flag.

**Each turn, in seat order:**
1. **Mana grows** — sample land drops/ramp from the deck's goldfish distribution.
2. **Develop** — advance `board_development`; refill `interaction_reserve` per `card_advantage`.
3. **Win attempt?** — probability rises as the turn nears the deck's `clock` mean and spikes once a
   combo is assembled (tutors raise per-turn assembly odds).
4. **Responses** — opponents may answer the win attempt from their `interaction_reserve`, gated by
   their `counters`/`spot_removal` and (4-player) threat assessment:
   - **4-player:** the table preferentially answers the current **archenemy** (highest
     `threat_level`/closest to its clock). Multiple opponents can chip in — models "you'll get got."
   - **1v1:** only the lone opponent responds; trades are 1:1, so **card advantage + inevitability**
     (longer games favor the grindier deck) matter more.
5. **Resolve** — unanswered win attempt ⇒ that player wins (combo) or lands a lethal alpha strike
   (combat). Record **win turn + method**.
6. **Attrition** — removal/sweepers can also set back a developed player between win attempts (lower
   `board_development`, delay their clock), modeling incremental interaction.
7. **Terminate** — last player standing wins; on a turn cap the game "goes long" and is resolved by
   **inevitability** = f(`card_advantage`, `resilience`).

---

## 3. Politics & threat assessment (4-player only)

- Each turn, score every live player's proximity-to-win; the table spends interaction on the **top
  threat** first. This reproduces archenemy dynamics — and explains why the fastest deck does **not**
  auto-win a pod (it draws the table's answers).
- A bounded **variance/kingmaker** term keeps it non-deterministic.
- All weights live in `battle_params.py`.

---

## 4. Calibration & validation (mandatory — this is what keeps it honest)

The model has free parameters; without discipline it's astrology. Guards:
- **Sanity invariants (tests):** faster `clock` ⇒ more 1v1 wins, all else equal; moving a fast-combo
  deck from 1v1 → 4-player **reduces** its win share; win rates sum to ~100%; a game with one player
  left terminates; seeded runs are deterministic.
- **Sensitivity bands:** every result re-runs with perturbed parameters; report the **band**
  (e.g., "Henzie 50–86%"), never a bare point.
- **Anchors:** a few hand-checked matchups documented as regression fixtures.
- **Stretch:** ingest real game results to fit parameters (lightweight logistic fit).
- **Output discipline:** always print the parameter assumptions + band; never a bare "Deck X wins."

---

## 5. Outputs / metrics (`MatchResult` pydantic model)

- Win rate per deck, **with a ± band** from sensitivity runs.
- Win-turn distribution (mean/median/spread).
- **Win-method breakdown** — combo / beatdown / inevitability(last-standing).
- 4-player: **archenemy rate** (how often each deck is the table's target) and **died-first rate**.
- **Clock-rank vs equity-rank gap** — surfaces how much interaction reshaped raw speed (the insight
  from this very analysis).

---

## 6. Surface area

- **CLI:** `mtg battle <deckA> <deckB> [<deckC> <deckD>] [--games 1000] [--seed 1] [--life 40]
  [--sensitivity]` — 2 decks ⇒ 1v1, 3–4 decks ⇒ pod.
- **Engine API:** `simulate_match(profiles: list[BattleProfile], *, players, games, seed) -> MatchResult`.
- **HTTP (later):** thin `/battle` FastAPI endpoint, mirroring the engine call.

---

## 7. Module layout (consistent with the repo)

```
backend/mtg_analyzer/
  simulation/
    battle.py          # BattleProfile mapper + match loop (reuses goldfish.simulate + analyze)
    battle_params.py   # ALL tunable constants (archetype offsets, interaction weights, politics)
  models/
    battle.py          # BattleProfile, MatchResult (pydantic)
tests/
  test_battle.py       # determinism + sanity invariants + anchor fixtures
```
CLI `battle` subcommand in `cli.py`; `/battle` endpoint in `api/app.py` (later).

---

## 8. Phasing

- **Phase A (MVP):** BattleProfile mapper + **1v1** loop (clock + interaction + card advantage).
  CLI `mtg battle A B`. Determinism + sanity tests. Sensitivity band output.
- **Phase B:** **4-player** pod + politics/threat assessment + archenemy/died-first metrics.
- **Phase C:** calibration harness (parameter sweeps; optional real-result fitting); richer
  board-wipe/recursion/inevitability modeling; win-method breakdown.
- **Phase D (optional):** FastAPI `/battle`; if true rules-accurate play is ever required, integrate
  **XMage** (MIT) — explicitly separate and out of this scope.

---

## 9. Risks & limitations (state plainly in every report)

- **Garbage-in:** only as good as the parameter mapping + calibration. Until calibrated against real
  games, treat outputs as **relative** and **banded**, like the goldfish sim.
- **Abstraction hides specifics** — silver-bullet hate, stax pieces, specific protection wars.
- **Politics is a heuristic** — real tables vary; expose knobs.
- **Never claim card-level accuracy** — it's a dynamics model, not a rules engine.

---

## 10. Effort estimate

- Phase A (1v1 MVP): ~1–2 focused sessions (mapper + loop + tests).
- Phase B (4-player + politics): ~1–2 sessions.
- Phase C (calibration + richer dynamics): ongoing; the bulk of getting numbers *trustworthy*.

The engineering is modest; the **calibration is the real work** — which is why the design front-loads
sensitivity bands and sanity invariants over a single confident win percentage.

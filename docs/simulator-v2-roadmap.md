# Simulator v2 — Research-Grounded Replan (2026-06-23)

> **This is the authoritative roadmap for evolving the battle simulator.** It supersedes the priority
> ordering and framing of the older A–H workstream tracker in
> [project-plan.md](../project-plan.md) → Phase 9 (the A–H *letters* are preserved and mapped to the
> new stages in §6 for continuity with shipped work). It is motivated by
> [simulator-research-2026-06.md](simulator-research-2026-06.md) (external literature) and
> [simulator-realism-research.md](simulator-realism-research.md) (balance/V&V/politics literature),
> and triggered by [lotr-sim-validation-findings.md](lotr-sim-validation-findings.md) (the validation
> that proved the current model ranks decks ~inverted).
>
> Status of every item is tracked in **project-plan.md** (single source of truth per CLAUDE.md); this
> doc holds the *plan and the why*.

## 0. Why replan

Two converging signals:
1. **Empirical:** a full 15-pod LOTR sweep ranks the decks **near-perfectly inverted** vs. experienced
   play (rank-distance 16/18). Root cause: the model is **monocausal on speed**, and its "clock"
   actually measures *commander-deploy* turn, not *win* turn ([validation findings](lotr-sim-validation-findings.md)).
2. **Theoretical:** the literature ([research synthesis](simulator-research-2026-06.md)) says realistic
   relative win rates in a strategic, hidden-info, multiplayer game come from **searched decisions over
   a stochastic-but-abstract state**, with politics as a **secondary opponent-modeling layer** — not
   from a single power/speed scalar nudged by hand-tuned knobs.

**The core architectural bet:** turn the existing fixed-policy turn-loop (`_play_match`) into a
proper **abstract, card-agnostic forward model** and drive decisions by **determinization +
IS-MCTS**, keeping the current loop as the cheap stochastic rollout. This respects golden-rule #5 (no
rules engine): the forward model operates on abstract resources (life, mana, board-development,
answers-held, combo-progress), never on cards/stack/targeting.

## 1. Guiding principles (from the research)

- **P1 — Strategy primary, politics secondary.** Tactics outweigh politicking ~14× in the best
  multiplayer-AI evidence. Politics *modulates who gets targeted*; it must not *determine outcomes*.
  (Our current model risks the opposite — heavily-tuned politics knobs on top of a thin tactical core.)
- **P2 — Realism lives in stochastic structure, not detail.** Resample hidden state every trial; a
  cheap randomized rollout beats an expensive deterministic one. Spend effort on faithful *variance*,
  not on modeling cards.
- **P3 — Search, don't hand-threshold.** "Hold vs. commit interaction," "who to answer," "go for the
  win now?" should be *searched* decisions so reactive play and answer-wars **emerge**.
- **P4 — Right tool, not the fanciest.** IS-MCTS, yes. CFR / full AlphaZero self-play, no.
- **P5 — Honesty over false precision.** Relative win rates with joint uncertainty bands, validated by
  *ordinal* stylized-facts (the literature does NOT support corpus-NLL fitting — see P6).
- **P6 — Calibrate on patterns, not (only) a corpus.** No literature backs fitting a heuristic sim to
  logged games; ordinal anchors (e.g. the LOTR ranking) are the workhorse. A corpus fit is
  *opportunistic*, never the critical path.

## 2. Staged roadmap

### Stage 0 — Stop the bleeding (correctness; days; no new theory) — ✅ **SHIPPED 2026-06-23**
The current output was demonstrably wrong; fixed before building anything on top.
- **0.1 — ✅ Decoupled the win-clock from the deploy/attempt clock.** Instead of literally deleting the
  `creatures ≥ 27 → aggro` classifier, fixed the bug at its true source: `BattleProfile` now carries a
  separate `combo_clock` (the goldfish combo-assembly turn) for any **incidental** combo (a non-combo
  archetype that merely contains one). `_play_match` gates the combo-win path — and the combo lethal-gate
  + protection-cancel — on the combo actually being **online** (`turn ≥ combo_clock − COMBO_ONLINE_SLACK`).
  So a fast aggro deck with a late backup combo now wins by **beatdown at its combat clock**, not by an
  instant turn-3 combo. The combo-clock *blend* was also narrowed to combo-**primary** decks only.
  Backward-compatible: synthetic/combo-primary profiles (`combo_clock=None`) fall back to `clock_mean`.
- **0.2 — ✅ Recorded the LOTR ordinal anchor** (`Sauron > Tom Bombadil > Galadriel > Gandalf > Sméagol >
  Frodo & Sam`) as `LOTR_RANKING` in the test suite + [lotr-sim-validation-findings.md](lotr-sim-validation-findings.md).
- **0.3 — ✅ Added `test_anchor_lotr_ordinal_ranking`** — sweeps all 15 four-pods over snapshotted deck
  profiles and gates rank-distance ≤ 12 (catches re-inversion; ratchets down as Stage 1 lands) + pins the
  exact bug (Frodo & Sam < 45% and not the strongest deck).
- **Result:** rank-distance **16 → 10** (Frodo & Sam 74% → 31%; resilient Tom/Galadriel rose to the top).
  131 tests pass, ruff + mypy clean. Residual (Sauron still under-ranked, Sméagol low) is the
  speed-monocausal weighting that **Stage 1** addresses — out of scope here by design.

### Stage 1 — Richer equity than a scalar clock (heuristic; no search yet) — ✅ **SHIPPED 2026-06-23**
Made "speed isn't destiny" true *before* paying for search — and it closed most of the gap cheaply.
- **1.1 — ✅ Mid-game attrition / inevitability win path.** The decisive structural fix. A param sweep
  proved re-weighting existing levers was inert (Sauron 10%→15%, rank-distance stuck at 10) because
  games end ~T9 and the old inevitability tiebreak only fired at turn 24. So a slow interaction-dense
  deck had **no win path** — its answers only delayed opponents. New: each turn past `ATTRITION_MIN_TURN`
  the game can resolve by **grind**, the winner drawn weighted by **grind-equity** (interaction-heavy +
  card advantage + resilience/protection + combo redundancy). Two refinements made it precise:
  - **Heat discount** — the perennial archenemy (Frodo, 98% archenemy) can't *also* win the grind; its
    grind-equity is divided by the reputation/lightning-rod heat it's drawing. This is what swaps the
    quiet resource deck (Sauron) above the focused aggro deck (Frodo).
  - **Margin gate** — attrition fires in proportion to how far the resource leader out-grinds the *field
    mean*, through a sharp logistic. Resource-even tables (mirror; a fast deck racing an equal deck)
    fire ≈0, protecting the speed/mirror anchors; lopsided pods fire hard. This let the turn threshold
    stay early enough to catch real pods without diluting fast 1v1s.
- **1.2 / 1.3 (hypergeometric answer-availability; intransitive matchup term)** — **deferred.** Stage 1.1
  alone hit the target (see result), so these move to a later polish pass rather than being needed now.
- **Result:** LOTR **rank-distance 10 → 4** (the metric started at **16** pre-Stage-0). Sauron rose from
  dead-last to **2nd**; Frodo & Sam fell from 1st to **last** — the original inversion is gone. Speed
  anchor holds at **0.905**, grind 0.90, mirror symmetric. The `pod_blunts_a_fast_deck` anchor was
  recalibrated (a lone control deck now grinds a glass-cannon combo to ~0.52 heads-up, down from 0.68 —
  the intended speed-isn't-destiny correction; the pod still crushes it to 0.06). 131 tests, ruff+mypy
  clean. Residual (Sauron #2 not #1; Gandalf/Galadriel mid-table swap) is finer strategic texture for
  **Stage 2** (search) / **Stage 3** (opponent modeling).
- **Decision gate outcome:** Stage 1 hit the anchor (dist 4) → **Stage 2 (search) is now optional polish,
  not a necessity** for the LOTR ordinal. Pursue it for the qualitative jump (emergent reactive play),
  not to fix a broken ranking.

### Stage 2 — Searched decisions: abstract forward model + IS-MCTS (the architectural bet) — ◐ **PROTOTYPED 2026-06-23; full build NOT committed (evidence-based)**
Built the make-or-break gate and a determinized-search prototype, measured it, and stopped at the
decision point — rather than committing the multi-week full engine — because the evidence says the
ranking is already solved. All in `simulation/battle_search.py` (separate from production `battle.py`,
which stays the default and untouched).
- **2.1 — ✅ Explicit, resumable, card-agnostic forward model + GATE PASSED.** `BattleState` (life,
  realized clock, delay, answers-in-hand, sweepers, reputation, damage matrix — abstract resources, no
  cards) with `step_turn` / `play_from(state, rng, decide)` resumable from any turn, and a `decide`
  **policy seam** for the win-attempt commit. The heuristic policy faithfully ports Stage-1's
  ranking-driving mechanics. **Gate result: the prototype reproduces production *exactly* — LOTR dist 4,
  identical win rates to the percent.** So the abstraction is expressive enough; search on it is trustworthy.
- **2.2 / 2.3 — ◐ determinized FLAT search prototyped** (not full UCB-tree IS-MCTS). `make_search_decide`
  replaces the go-first caution coin-flip with the research's determinization + cheap-rollout: for the
  active deck, roll the rest of the game out K times under COMMIT vs WAIT and pick the action that wins
  more. (Full UCB-tree IS-MCTS + visit-count ensembling = the documented next increment.)
- **2.4 — ✅ Rollout = the Stage-1 heuristic playout** (research: rollout quality dominates).
- **MEASURED VERDICT — search works but does NOT improve the ranking.** K=8 determinized search: LOTR
  **dist stays 4** (no ordinal gain). It *does* change dynamics sensibly — better win-timing shifts share
  toward optimal-play combo decks (Tom 42→48%, Galadriel 28→40%) and slightly *lowers* Sauron (34→29%),
  at ~4× compute. So search adds **skillful-play texture, not ranking accuracy**. Combined with Stage 1
  having already hit the anchor (dist 4), this **confirms the decision gate: do NOT commit the full
  IS-MCTS build for the ranking.** Reserve it for if/when "skillful timing realism" is specifically the
  goal; otherwise **Stage 3 (politics) is the higher-value next investment.** Prototype kept (tested,
  lint/mypy clean) as the validated foundation if the full build is later greenlit. NOT CFR, NOT full RL.

### Stage 3 — Politics as a secondary opponent-model module (CICERO-lite) — ◐ **AUDITED + PROTOTYPED 2026-06-23; existing politics CONFIRMED, no production rebalance needed**
The research both **validates** the existing workstream-F politics (CICERO-style voting + perception is
literature-backed) and prescribes two checks. Both done, evidence-based.
- **3.2 — ✅ Politics-weight AUDIT (the 14× "tactics dominate" guardrail).** Ablated each politics layer
  in the production engine over the 15 LOTR pods:
  - Tactical/resource fundamentals **alone** already rank well (ALL-politics-off → dist 6); politics
    *refines* to dist 4. So politics is **appropriately secondary** — it improves the ranking, it does
    not drive it. The 14× guardrail is respected; **no down-weighting needed.**
  - The refinement is almost entirely the **perception / lightning-rod** mechanism (remove it → dist 8,
    Frodo rebounds 8→21%, Sauron craters 33→22%) — the community-validated workstream-F piece doing real
    work. The **coordination free-rider, equity gate, and spoiler are near-inert on the ranking** (each
    removed individually → dist still 4). Flagged as candidates for a future simplification pass (they
    still encode workstream-F stylized-facts, so not removed here).
- **3.1 — ◐ Grounded opponent-model coordination prototyped** (`battle_search.py`, opt-in
  `GROUNDED_COORDINATION`, default OFF). Replaces the flat `ANSWER_COORDINATION` knob — which the code
  comment flagged as a deliberate simplification of an *unstable* bystander model — with the CICERO-lite
  version: each defender free-rides in proportion to the **expected answering capacity of the OTHER
  polled defenders** (depends only on others → no self-referential collapse → **stable**, fixing the
  documented instability). **Measured: at calibrated strength it reproduces the ranking exactly (dist 4);
  over-strong free-riding mildly degrades it (dist 6) as the archenemy slips through** — a sanity check.
  Per the audit it does not change outcomes, so it stays **opt-in** (a fidelity/principle improvement),
  not a production default.
- **3.3 — ✅ Human-regularization already present** (DiL-piKL idea): the model already plays near a
  "typical pilot" distribution rather than argmax, via `PERCEPTION_NOISE` + the elicited `PRIORS` — the
  research-confirmed approach. Sharpen against a logged corpus if/when one exists.
- **3b — ✅ Standing-strength targeting AUDITED (negative result).** Tried making the table gang up on the
  resource leader (grind-equity lead). It does **not** compress the win-rate spread — it *widens* it and
  scrambles the ranking, because grind-equity mis-predicts who actually wins, and a resource-dense deck
  *survives* being targeted (that's what makes it strong). Kept opt-in (`THREAT_DOMINANCE_W`, default 0)
  as a documented dead-end. Insight: **you cannot politics away a real power gap** — focusing the
  strongest deck just hands the win to the next-strongest in the same tier.
- **3c — ✅✅ METAGAME-KNOWLEDGE feedback loop — SHIPPED to production (the breakthrough).** Prompted by the
  user's insight: *target by who is KNOWN to win, not by static pre-game power.* The bug it fixes: a fast
  aggro deck has the highest static `threat_level` yet never wins (wrongly the turn-1 archenemy 84% of the
  time), while a quiet control deck wins most yet is never targeted (archenemy 0%). Fix: feed each deck's
  realized win rate back as a standing threat prior (`win_prior = win_rate − 1/pod_size`), bypassing the
  quiet-shark discount, via a **damped fictitious-play loop** (`simulate_metagame`, CLI
  `mtg battle --metagame`; `WINRATE_PRIOR_W`/`METAGAME_*`). Damping prevents the undamped overshoot
  (target winner → it loses → oscillate). **Result on the LOTR pool: converges in ~5 passes to rank-distance
  0 — a PERFECT match to the experienced-player ranking** (Sauron last→1st; Frodo's archenemy share
  84%→68% and its prior goes negative — "left alone at game start, flagged only if it takes off"; the real
  winners Tom/Gandalf now draw the heat; spread 33pp→27pp). The dynamic board/proximity terms are
  untouched, so a low-prior deck that *does* take off mid-game still draws heat. Opt-in (standing
  `WINRATE_PRIOR_W` default 0 → a one-off `mtg battle` is unchanged); side-effect-free. Tested + lint/mypy
  clean. **This is the first politics mechanism that improves the model on every axis — ranking,
  archenemy realism, and spread.**
- **3d — ✅✅ INFORMED-TABLE assumption — SHIPPED (the archenemy now tracks power).** Prompted by the user:
  *we can't assume players are fooled by the quiet shark — assume a table that understands power levels,
  which should drive the strongest deck (Sauron) near the top of the archenemy ranking.* Diagnosis:
  Sauron wins by **attrition**, which is invisible to the threat read (lowest `live_threat` at the table,
  5.8 vs Frodo's 19.2) — so even with its learned +0.10 prior it was the archenemy only ~4% of turns. The
  fix: after the loop LEARNS the power levels, run a final reporting pass at a much stronger
  `METAGAME_INFORMED_WEIGHT` so the table TARGETS by known power. Quantified the regime: casual table
  (low weight) → archenemy backwards (Frodo 66%, Sauron 6%), win rate tracks power; **informed table
  (high weight) → archenemy tracks power (Sauron near top, Frodo →5%), win rates COMPRESS toward parity
  (33pp→~10pp).** Key reframe, now baked into the output: **power level is the ranking + the archenemy
  column; win rate is the *policed outcome*** (a correctly-policed leader wins *less*, and the 2nd/3rd
  under-the-radar decks inherit — the empirical 11%-archenemy pattern). `simulate_metagame(informed=True)`
  is the default; `mtg battle --metagame` reports `#  deck  power  archenemy%  win%`. The cranked weight
  is applied ONLY in the reporting pass (convergence stays at the stable weight — high weight alone
  oscillates). Tested, lint/mypy clean.
- **VERDICT:** the baseline politics is research-confirmed and appropriately secondary (3.1/3.2 needed no
  rebalance) — but the **metagame feedback loop (3c) + the informed-table assumption (3d)** were the
  missing pieces. Together they give the **power ranking = the player's ordering** while making the
  **archenemy correctly track power** (the strongest deck is ganged up on, not the flashiest) and win
  rates compress under informed play. The user's two corrections (recognize the quiet winner; don't
  archenemy the never-wins aggro) and their power-level-drives-archenemy principle are all realized.
  **Data:** none required (the sim bootstraps its own metagame).

### Cross-cutting — Calibration & honesty (continuous)
- **X1 — POM ordinal stylized-facts are the PRIMARY validation** (was E; promoted). The LOTR anchor +
  more ordinal facts gate every change. (P6: literature does not support corpus-NLL.)
- **X2 — Keep 9C-1 logging; downgrade the 9C-2 NLL fit to opportunistic / anchor-gated** — off the
  critical path, not a blocker. Reframes "blocked on a corpus" as "not needed yet."
- **X3 — Honest joint uncertainty bands** (was D, shipped) extended with **docking (E3):** require the
  Stage-1 heuristic and the Stage-2 search models to agree *distributionally*; divergence localizes
  bugs and quantifies structural uncertainty.
- **X4 — Metagame / Nash-averaging evaluation layer** (was C): keep as an orthogonal calibration
  signal (sanity-check archetype shares vs. EDH meta intuition); low priority.

## 3. Sequencing

```
Stage 0  ──▶  Stage 1  ──▶  [decision gate: did Stage 1 hit the anchor?]
   now        heuristic          │
                                 ├─ yes ─▶ Stage 2 optional · go to Stage 3 / polish
                                 └─ no  ─▶ Stage 2 (search)  ──▶  Stage 3 (politics)
X1–X4 run continuously throughout.
```
Stages 0 and 1 are pure-heuristic, low-risk, and independently shippable. Stage 2 is the architectural
bet — gated on 2.1 proving the abstract state is expressive enough. Stage 3 depends on Stage 2.

## 4. Non-goals (research-reinforced)
- **No card-level rules engine** (golden-rule #5): no stack/priority/targeting/card resolution. The
  forward model is card-agnostic abstract resources only.
- **No CFR core solver** (wrong concept for 4-player non-zero-sum).
- **No full AlphaZero RL self-play** as the product (data/compute prohibitive; insufficient alone).
- **Politics never primary** (P1).

## 5. Key risks & open questions
- **R1 — Abstract-state expressiveness (Stage 2.1).** The whole search bet rests on it. *Mitigation:*
  validate against Stage-1 + the LOTR anchor before building MCTS.
- **R2 — 4-player tuning gap.** The MTG MCTS evidence is 1v1; determinization count + rollout-noise for
  a 4-player FFA are unproven. *Mitigation:* sweep them as parameters under the sensitivity harness.
- **R3 — Calibration without a corpus.** Lean on ordinal POM (X1); don't over-build the fit engine.
- **R4 — Politics over-weighting regression.** Re-auditing F may move shipped anchors. *Mitigation:*
  the ordinal anchor suite (0.3) catches regressions.

## 6. Old A–H workstreams → new stages (continuity map)
| Old WS | Was | Now |
|---|---|---|
| A — stochastic grounding | partial (A1, A4 claimed) | **A4 → Stage 0.1** (was NOT actually shipped); A2 → Stage 1.2; A1/A3 culminate in **Stage 2.2 determinization** |
| B — intransitive matchups | not started | **Stage 1.3** (promoted — the cheap monocausal-speed fix) |
| C — metagame Nash layer | not started | **X4** (kept, low priority) |
| D — honest uncertainty | shipped | **X3** (extend with docking) |
| E — POM validation | partial | **X1** (promoted to PRIMARY validation) |
| F — commander politics | shipped F1–F5 | **Stage 3** (restructure as opponent-model; re-weight secondary) |
| G — robustness probes | later | later (needs broader deck pool) |
| H — corpus fit | = 9C, blocked | **X2** (downgraded to opportunistic / anchor-gated) |
| **NEW** | — | **Stage 2 — searched decisions (determinization + IS-MCTS)** — the piece the research adds. **Prototyped** (`battle_search.py`): 2.1 forward-model gate passed; flat determinized search measured to add skill-texture but no ranking gain → full IS-MCTS build deferred |

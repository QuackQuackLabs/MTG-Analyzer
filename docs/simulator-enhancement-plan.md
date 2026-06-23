# Simulator Enhancement Plan — toward a better reflection of play

**Status:** proposed. **Scope:** improve the goldfish + battle simulators' *realism* and *honesty*
**without** real game-outcome data (which remains the ultimate update), grounded in simulation-science
and game-AI best practice. Companion to [battle-simulator-design.md](battle-simulator-design.md).

This plan is the product of a literature review across four areas — MTG/CCG game-AI engines,
card-game *balance* simulation, simulation V&V/calibration without ground truth, and multiplayer
free-for-all "politics" modeling. The references are collected at the end; key findings are cited
inline as `[n]`.

---

## 0. The thesis (what the research actually says)

Five findings recur across every source and reframe how we should spend effort:

1. **Realism lives in the *stochastic structure*, not the rule detail [1][5].** The strongest MTG-MCTS
   result is that *reduced rules + injected randomness + averaging over resampled hidden states* beats
   a detailed deterministic "expert" agent. Our no-rules-engine choice is validated; the leverage is
   in making per-game variance faithful, not in modeling cards.
2. **Derive parameters from deck math; don't hand-assert them [2][6].** Karsten/​hypergeometric +
   goldfishing turn "clock", "combo-assembly turn", and "answer available by turn T" into *distributions*
   computed from the actual list. We already do this for `commander_turn`/`combo_turn` — extend it.
3. **A single power/threat scalar cannot produce rock-paper-scissors [2].** Real games are a
   "spinning top": a transitive strength axis *plus* non-transitive cyclic layers. Aggro/control/combo
   must be able to form cycles — that needs a strength scalar **+ a small interaction term**, not one
   number.
4. **Evaluate the *metagame*, not just pairwise win-rate averages [2].** From a matchup matrix you can
   compute the Nash-equilibrium-of-the-meta (redundancy-invariant) and project archetype shares via
   replicator dynamics — a *free calibration signal today* (sanity-check vs. EDH meta intuition) with
   zero logged games.
5. **Honest uncertainty needs *global* sensitivity analysis, and validation needs *pattern* matching
   [3].** Our one-parameter band is exactly the "local OAT" anti-pattern the literature calls the most
   common way to misrepresent uncertainty. With ~12 coupled parameters and a few anchors,
   **equifinality** (many parameter sets fit equally) is near-certain — so we validate against a *suite
   of independent qualitative patterns*, not a few magnitudes.

**Guiding framing for every output, stated plainly:** *relative* win rates with a **joint-parametric
uncertainty band under documented expert priors**, validated by qualitative pattern-matching and
cross-model docking — **not** calibrated point predictions. (This is the honest position the V&V
literature prescribes when no operational data exists [3].)

---

## 1. Where we are vs. where this takes us

| Dimension | Today | After this plan |
|---|---|---|
| Deck → parameters | point estimates (one `clock_mean`, one `interaction` count) | per-game **distributions**, resampled each trial, derived from deck math |
| Interaction | a finite reserve counter | **hypergeometric availability**: P(holding an answer when a threat lands on turn T) |
| Matchups | ~transitive on clock | strength **+ interaction vector** → genuine rock-paper-scissors |
| Threat/politics | 6 hand-weighted terms, tuned to anchors | win-proximity-graded coalition + self-updating threat, fewer orthogonal terms |
| Uncertainty | band perturbs **1** of ~12 knobs | **global SA** (LHS/Morris/Sobol) → joint band; params are priors not points |
| Validation | a few magnitude "anchor" tests | **POM** suite of independent stylized facts + docking + held-out anchors |
| Meta | none | matchup matrix → Nash-averaging + replicator projection (free calibration) |

---

## 2. Workstreams

Each is independently shippable. Code targets are named so this is actionable.

### A. Stochastic grounding — *biggest realism gain, pure deck math* [1][2][6]
The battle sim consumes **point** estimates; the research says resample **every trial**.
- **A1. Parameters as per-game samples.** Have the goldfish emit *distributions* (it already simulates
  per-game); `BattleProfile` carries the distribution (mean+sd, or sampled quantiles) and `_play_match`
  **draws clock / combo-turn / opening interaction fresh each game** instead of using the mean. The win
  probability then emerges from the *interaction of two drawn distributions* (my clock vs. your
  answer-availability) — which is where Commander variance actually lives. *(goldfish.py → SimResult;
  battle.py `_play_match`)*
- **A2. Hypergeometric interaction availability.** Replace/augment the flat "reserve counter" with a
  draw-dependent curve: `P(≥1 answer in hand when a threat resolves on turn T)` from interaction
  density + cards seen by T (reuse `probability.py`). Interaction stops being a static budget and
  becomes "did you draw the answer in time" — the honest model. *(simulation/probability.py;
  battle.py answer step)*
- **A3. Decision noise, formalized.** Keep win-attempt and answer thresholds noisy per game (we partly
  do); the MCTS literature shows randomized reduced-rule rollouts beat deterministic ones [1]. Make the
  noise a documented parameter, not incidental.
- **A4. Derive archetype/clock from goldfish signals, retire the creature-count classifier.** Use
  `combo_turn` vs `commander_turn` (combo-is-the-real-plan when they're close) instead of "creatures ≥
  27 → aggro", which currently mislabels Sméagol/Frodo. *(battle.py `_archetype`/`build_profile`)*

### B. Intransitive matchups — *structural realism (RPS)* [2]
A clock-only model gives a strict pecking order; real metas cycle.
- **B1. Strength + interaction term.** Either (a) give each deck a low-rank interaction vector
  (blade-chest model [2]) added to the transitive clock comparison, or (b) — preferred, more grounded —
  make the *mechanics* produce the cycle: interaction is **more effective vs. combo** (a counter/answer
  stops the whole plan) than vs. **aggro** (redundant threats), while aggro's fast clock **races**
  control before its card-advantage engine dominates. Encode archetype-conditional answer effectiveness
  and clock pressure so aggro→control→combo→aggro emerges. *(battle.py answer + threat)*
- **B2. Skew-symmetry invariant.** In 1v1, `P(A beats B) + P(B beats A) ≈ 1` is a free correctness
  check [2] — add it to the test suite.

### C. Metagame evaluation layer — *free calibration signal NOW* [2]
- **C1. `mtg meta <decks…>`** runs the pairwise sim across a pool → a matchup matrix.
- **C2. Nash-averaging + replicator dynamics.** Compute the max-entropy Nash of the meta
  (redundancy-invariant power ranking [2]) and project archetype shares by replicator dynamics. Outputs
  we can **sanity-check against EDH meta intuition** (does combo/stax/aggro land where the format
  expects?) — a calibration loop that needs no logged games.
- **C3. Player-heterogeneity noise (Schmitz [2]).** Perturb matchup cells with Gaussian noise, recompute
  Nash per noisy matrix, average → realistic *diverse* play-rates (prevents declaring fringe-but-real
  decks dead). *(new: simulation/meta.py)*

### D. Honest uncertainty — *fixes the most misleading output* [3]
- **D1. Parameters become priors.** Convert each `battle_params` constant to an **expert-elicited
  distribution** (range + best guess) with a documented rationale (ODD-style [3]). *(battle_params.py)*
- **D2. Global sensitivity analysis.** Replace one-knob OAT with **Latin Hypercube** sampling over *all*
  params jointly; run **Morris screening** to find the ~3–5 that actually drive results and flag
  interactions; **Sobol'** indices (via a surrogate if runs are slow [3]) for the gold-standard
  variance decomposition. *(new: simulation/sensitivity.py)*
- **D3. Report the joint band.** The published band becomes the **quantile envelope from propagating the
  joint prior** — labeled as *parametric uncertainty under expert priors*, kept separate from
  Monte-Carlo noise (D-internal) and structural uncertainty. This replaces today's single-parameter
  band that "implies false precision."

### E. Validation harness (POM + V&V) — *overfitting defense* [3]
- **E1. Stylized-facts / POM filter suite.** Codify many *independent, ordinal* patterns the model must
  reproduce simultaneously (filters that *reject* parameter sets): monotonicity (more interaction → less
  combo-loss), symmetry (mirrors are fair), dominated-deck ordering, extreme-condition + degenerate
  tests (zero a mechanism → behavior degrades as theory predicts), win-shares-sum-to-1, skew-symmetry.
  POM is overfitting-resistant *because* the patterns are independent and qualitative [3].
- **E2. Ordinal over numeric anchors; hold-out; regularize.** Convert magnitude anchors (e.g.
  "0.18–0.42") to ordinal where possible; keep a **held-out** anchor subset never tuned against;
  regularize parameters toward their priors so uninformed knobs return to defaults [3].
- **E3. Docking.** Build an **independent simpler estimator** (a closed-form hypergeometric "race": my
  clock-distribution vs. your answer-availability) and require *distributional/relational* agreement
  with the full sim [3]. Divergence localizes bugs/assumptions.
- **E4. Internal-variance sizing.** Pick run counts so Monte-Carlo noise ≪ the effects we report; state
  it. *(tests/ + simulation/validation.py)*

### F. Politics realism — *grounded in multiplayer-AI theory* [4]
Our voting + perception-noise model is already *validated* by the literature (emergent alliances =
agreement of threat-votes [4, CICERO]; perception noise → realistic mis-targeting [4]). Upgrades:
- **F1. Win-proximity-graded paranoia.** Interpolate between *self-interested* (max^n) for trailing
  players and *whole-table-coalition* (paranoid) for the leader — the central result of multiplayer
  search [4]. This *principled* version replaces the hand-set `ARCHENEMY_ANSWERERS`/imminence knobs and
  should fix the "lone fast deck craters to 12%" over-focus.
- **F2. Self-updating threat (Threat-ADS [4]).** Threat becomes a ranked list with **decay**, bumped by
  threatening plays — not a fresh per-turn recompute. Yields shifting targets and "the quiet player gets
  ignored (and sometimes wins)" for free.
- **F3. Consolidate `live_threat`.** Collapse the 6 hand-weighted terms to **proximity-to-win relative
  to the table mean, dominated by hard board state** (CICERO's finding: position outweighs soft politics
  ~14× [4]). Fewer orthogonal terms → tunable + robust to the next edit (the current form broke twice
  under concurrent edits).
- **F4. Kingmaker/spoiler late game [4].** A player with no path to win switches to *spoiler*: spend
  remaining interaction to deny the leader, not act randomly.
- **F5. Anchor reactions to a human baseline (piKL [4]).** Keep each player's response near a "typical
  pilot" distribution rather than a pure argmax — prevents degenerate, over-optimized play.
- **F6. Reachability gate.** Don't spend interaction where it can't land (the table won't waste removal
  into hexproof / an uncrackable board). *(battle.py `live_threat`/`_play_match`)*

### G. Robustness probes — *for later* [2]
- **G1. Exploiter decks (AlphaStar idea [2]).** Auto-generate a parameter vector tuned to beat the
  current top archetype; if balance survives, it's robust.
- **G2. Spinning-top coverage.** Ensure the evaluation pool spans enough archetypes to cover the cyclic
  dimension — testing only vs. "the best deck" hides imbalance [2].

### H. Real-data calibration — *when data exists* [2]
Fit **Bradley-Terry/Elo** to map raw simulated win-rates → calibrated probabilities (Elo often
out-predicts more complex systems [2]); Bayesian-update the D1 priors with logged outcomes. This is the
existing "real-game fitting" item, now with a method.

---

## 3. Prioritized roadmap (no data required for 1–5)

Ordered by *(realism + honesty gained) ÷ effort*, given zero outcome data:

1. **D — Honest uncertainty (priors + global SA band).** Fixes the single most misleading output; the
   literature is unanimous this is the #1 fix [3]. Cheapest big honesty win.
2. **A — Stochastic grounding (per-game resampling + hypergeometric interaction).** The biggest
   *realism* gain, pure deck math [1][2]. "Realism lives in stochastic structure."
3. **E — POM validation harness.** Turns today's anchor-tuning into a principled, overfitting-resistant
   filter; cheap and protects everything downstream [3].
4. **F — Politics consolidation (win-proximity paranoia + Threat-ADS).** Fixes the maintainability and
   lone-fast-deck problems with a theory-grounded model [4].
5. **C — Metagame layer (Nash + replicator).** A *calibration signal available today* — validate the
   projected meta against format intuition [2].
6. **B — Intransitive matchups.** Structural realism (RPS); needed for the meta layer to be meaningful.
7. **G, H — Robustness probes & data calibration.** When the pool/data exist.

A natural first PR is **D1+D2+D3** (priors + LHS/Morris + joint band) and **A4** (retire the
creature-count classifier) — together they make the model both more honest and better-grounded without
touching the delicate politics tuning.

---

## 4. Non-goals (unchanged)
Still **not** a rules engine (golden rule #5): no stack/targeting/card resolution. Everything here keeps
the abstraction card-agnostic; it makes the *abstraction's statistics* faithful, which is exactly what
the game-AI literature says is the right place to spend effort [1].

---

## References
1. Cowling, Ward, Powley — *Ensemble Determinization in MCTS for the Imperfect-Information Card Game
   Magic: The Gathering.* (reduced rules + randomized rollouts + ensemble over hidden states)
2. Balduzzi et al., *Re-evaluating Evaluation* (Nash averaging); Czarnecki et al., *Real-World Games Look
   Like Spinning Tops* (transitive + cyclic structure); Chen & Joachims, *Modeling Intransitivity*
   (blade-chest); Koot, *Simulation of MTG metagame evolution* (matchup matrix + replicator); Karsten
   hypergeometric mana math; Bradley-Terry/Elo.
3. Sargent, *Verification & Validation of Simulation Models*; Grimm et al., *Pattern-Oriented Modeling*;
   Saltelli et al., *Global Sensitivity Analysis: The Primer* and *"Why so many published sensitivity
   analyses are false"*; Axtell et al., *Aligning Simulation Models* (docking); the ODD protocol.
4. Schadd & Winands, *Best-Reply Search*; Sturtevant, *Comparison of Algorithms for Multi-Player Games*
   (max^n / paranoid); Brown & Oommen, *Threat-ADS heuristic*; Meta AI, *CICERO* (piKL, intent
   prediction); kingmaker/spoiler design literature.
5. Forge / XMage AI architectures (phase-based static heuristics, no game-tree search) — validates the
   no-lookahead, heuristic-per-phase structure.

_(Full source URLs captured in the research briefs that produced this plan; see the session record.)_

# Simulator Research — Literature Reference

> **⚠ This is a RESEARCH REFERENCE, not a plan.** Status, the staged roadmap, and "what's next" live
> **only** in **[project-plan.md](../project-plan.md) → Phase 9** (the single source of truth per
> CLAUDE.md, which absorbed the former standalone v2 roadmap). This doc keeps the *why* — the literature
> thesis, per-workstream rationale + citations, and the non-goals. Where shipped work diverged from a
> proposal here, the project-plan tracker is authoritative.

This consolidates the two literature sweeps behind the battle simulator:

- **Part I — Balance, V&V & politics literature** (review of 2026-06-20): how to improve the goldfish +
  battle simulators' *realism* and *honesty* **without** real game-outcome data — grounded in
  simulation-science and game-AI best practice. Motivates the A–H workstreams.
- **Part II — Search & opponent-modeling literature** (synthesis of 2026-06-23): a deeper multi-source
  sweep on how a heuristic, NON-rules-engine 4-player FFA simulator should be *architected* — which
  named the one missing piece (searched decisions) and motivated the staged replan in
  [project-plan.md](../project-plan.md) → Phase 9.

Companion design spec: [battle-simulator-design.md](battle-simulator-design.md). Politics design spec:
[commander-politics-model.md](commander-politics-model.md).

---

## Shared non-goals (golden-rule #5, unchanged across both sweeps)

Still **not** a rules engine: no stack/priority/targeting/card resolution. Everything here keeps the
abstraction **card-agnostic**; it makes the *abstraction's statistics* faithful, which is exactly what
the game-AI literature says is the right place to spend effort. Specifically the research says **not** to
build:

- **No card-level rules engine.** Every cited MTG/CCG result runs over a *reduced* or *abstract* model,
  not full rules. The AlphaZero-style MageZero effort rides on XMage (an existing MIT engine) rather than
  a bespoke one.
- **No CFR / CFR+ core solver** — its Nash guarantee holds only for 2-player zero-sum; in a 4-player
  non-zero-sum FFA that guarantee is lost and the machinery is overkill (Part II §F2).
- **No full AlphaZero RL self-play** as the product — data/compute prohibitive for a local tool, and
  insufficient without human regularization (Part II §F3).

---

# Part I — Balance, V&V & politics literature

The product of a literature review across four areas — MTG/CCG game-AI engines, card-game *balance*
simulation, simulation V&V/calibration without ground truth, and multiplayer free-for-all "politics"
modeling. References are collected at the end of this part; key findings are cited inline as `[n]`.

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

## 1. Research rationale per workstream (the *why* behind project-plan's A–H tracker)

The literature mapped onto seven independent improvement areas (A–H). The descriptions below are the
**original research rationale + citations** for each — *why* the change matters and how the literature
motivates it. **Status, the staged roadmap, and what's next are NOT here** — they live in
[project-plan.md](../project-plan.md) → Phase 9 (the single source of truth).
Where shipped work diverged from the proposal below, that tracker wins.

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
> **⚠ SUPERSEDED (2026-06-22).** This early sketch was replaced by the community-strategy-grounded
> **[commander-politics-model.md](commander-politics-model.md)**, whose F1–F5 are now **shipped**.
> Mapping: the F1 "win-proximity paranoia" + F2 "Threat-ADS decay" ideas were realized as the
> perception/reputation split + equity-gated answering; F4 "kingmaker/spoiler" as the shipped
> spoiler-on-leader. Three ideas below were **not** adopted and survive only as optional future
> tweaks: **F3 consolidate `live_threat`** (perception was layered on top instead of collapsing the
> terms), **F5 piKL human-baseline anchoring** (perception noise partially covers it), and **F6
> reachability gate**. Do **not** build this section's F1–F6 as written — follow the politics-model doc.

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
existing "real-game fitting" item ([battle-calibration-fitting.md](battle-calibration-fitting.md)), now
with a method.

## Part I references
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
6. Karsten hypergeometric mana math (deck-derived distributions).

_(Full source URLs captured in the research briefs that produced this plan; see the session record.)_

---

# Part II — Search & opponent-modeling literature (2026-06-23)

> **What this is:** a cited synthesis of a deep, multi-source literature sweep (6 angles, 25 sources
> fetched, 115 claims extracted, 25 adversarially verified — 25/25 confirmed, only 1 non-unanimous).
> It answers: *how should a heuristic, NON-rules-engine simulator for a 4-player Commander free-for-all
> be architected to produce realistic relative win rates?* It is the **external-literature input** to
> the staged replan in [project-plan.md](../project-plan.md) → Phase 9. Findings are cited `[n]`;
> sources at the end of this part.

## 0. Headline

> **Evolve the speed-only sim along two axes: (1) replace fixed-threshold decisions with
> imperfect-information *search* — determinization + ensemble MCTS / IS-MCTS over an abstract,
> card-agnostic forward model; (2) make multiplayer politics an explicit *opponent-modeling* module
> (CICERO-style) — but keep strategy/tactics PRIMARY and politics secondary.** Do **not** reach for
> CFR (wrong solution concept for 4-player non-zero-sum) or full RL self-play (data/compute
> prohibitive, and insufficient alone).

This both **validates the project's existing bones** (heuristic abstraction + stochastic grounding +
politics module, no rules engine) and **names the one missing piece**: the engine of decisions should
be *search*, not hand-tuned thresholds.

## 1. Verified findings

### F1 — Determinization + ensemble MCTS, with a cheap stochastic rollout `[1][6]` (confidence: high, 3-0)
On Magic specifically, pooling **multiple independent determinized MCTS trees by visit count roughly
doubled win rate over a single tree (31% → 56%)** and matched an expert rule-based player in **under
one CPU-second** `[1]`. The decisive factor is the **rollout/playout policy**: a *cheap reduced-rules
policy with injected randomness beat a stronger deterministic "expert" policy in every experiment*
`[1][6]`. **Implication for us:** the current `_play_match` turn-loop is already a fixed-policy
rollout — keep it as the rollout (it's exactly the "cheap stochastic reduced-rules" policy the
literature wants), and add determinization + an MCTS layer of *decisions* on top.

### F2 — Prefer IS-MCTS; avoid CFR as the core solver `[2][6]` (high, 3-0)
**Information-Set MCTS (IS-MCTS)** beats naive *determinize-then-solve* wherever **strategy fusion /
non-locality** bite (demonstrated across Skat, Hanabi, Spades, and MTG) `[2]` — i.e. when an agent
would illegally "see" hidden info differently down different branches. **Do NOT use CFR / CFR+ as the
core solver:** its Nash guarantee holds only for **2-player zero-sum**; in a 4-player non-zero-sum FFA
that guarantee is lost and the machinery is overkill `[2]`.

### F3 — Model coalitions + co-player adaptation, but weight politics SECONDARY `[3][4][5]` (high; one sub-claim 2-1)
In **n>2 games, alliances confer real advantage** and **Nash / non-exploitability is the wrong
objective** `[3]`. The state-of-the-art architecture is **CICERO** (human-level Diplomacy): a
**separate planning engine + opponent-model** that predicts opponents' moves, recursively models
*their* model of the agent, and decides **cooperate-vs-defect** `[4][5]`. Two hard guardrails:
- **Tactics dominate politics.** In CICERO ablations, raw strategic strength outweighed communication
  by **~14×** (best-power agent won 20/24 games) `[4][5]`. → Politics must *modulate target selection*,
  not *determine outcomes*.
- **Human-regularize the opponent model** (DiL-piKL): keep agents near a "typical pilot" distribution
  rather than a pure argmax — **self-play RL alone is insufficient** and produces degenerate play
  `[5]`. Coalition-honoring is predictably modeled (a hypergame "rationalizability" metric beat a raw
  value model — the lone 2-1 claim `[3]`).

## 2. The central design tension (and its resolution)

The strongest technique (determinization + MCTS) **needs a forward model** — `step(state, action) →
state'` — which sounds like the forbidden rules engine. **Resolution:** define the forward model over
an **abstract, card-agnostic state** (per player: life, mana/ramp, board-development, cards-in-hand,
answers-held, combo-progress), never over cards/stack/targeting. This is *not* a rules engine under
golden-rule #5 — it is the existing dynamics abstraction made explicit and *searchable*. Validating
that this abstract state is expressive enough is the make-or-break step of the replan (see roadmap
Stage 2.1).

## 3. Honest limits of this research (from the verification caveats)

- The MTG MCTS numbers are a **2012, 1v1, reduced-rules** sweep — **not validated for 4-player
  Commander**. The determinization count and rollout-randomness that fit a 4-player FFA are an **open
  question**.
- Politics evidence is from **Diplomacy** (richer explicit negotiation than EDH table-talk); the 14×
  tactics-over-politics ratio comes from self-play with a comms confidence interval crossing zero —
  treat it as "politics is clearly secondary," not as a precise multiplier.
- **Calibration against a real logged-game corpus is the least-covered area** — *no* source directly
  addresses fitting a heuristic sim to logged outcomes. This is a strong signal to lean on
  **pattern-oriented / ordinal stylized-fact validation** (workstream E + the LOTR ordinal anchor)
  rather than gating progress on an NLL corpus fit.

## 4. Open questions carried into the roadmap

1. Determinization count + rollout-randomness for 4-player FFA vs. the 1v1 sweep.
2. How to weight the politics module against the strategy/search engine for Commander.
3. What corpus + fitting procedure (if any) calibrates the sim — given the literature gap.
4. Whether a human-regularized opponent model is achievable without a large Commander dataset.

## Part II references
1. Cowling, Ward & Powley, *Ensemble Determinization in MCTS for the Imperfect-Information Card Game
   Magic: The Gathering*, IEEE TCIAIG 2012 — determinized-tree pooling 31%→56%, rollout-policy
   dominance. <https://ieeexplore.ieee.org/document/6218176/>
2. Whitehouse, Powley et al., *Determinization and Information-Set MCTS* — IS-MCTS vs. determinize-
   then-solve; strategy fusion. <https://www.semanticscholar.org/paper/67e1f4795c461a5467d6009b1efdaa36aad03a40>
3. *Coalitions / many-player FFA game theory* — alliances confer advantage; Nash is the wrong
   objective; hypergame rationalizability. <https://arxiv.org/abs/2003.00799>,
   <https://www.ifaamas.org/Proceedings/aamas2025/pdfs/p1227.pdf>
4. Meta AI et al., *CICERO: Human-level play in Diplomacy by combining language models with strategic
   reasoning*, Science 2022 — planning+dialogue modules; tactics≈14×comms; 20/24 wins.
   <https://www.science.org/doi/10.1126/science.ade9097>, <https://ai.meta.com/research/cicero/>
5. *DiL-piKL / RL-DiL-piKL* (human-regularized planning) and *Diplodocus* — opponent modeling near a
   human baseline; self-play-alone insufficient. <https://arxiv.org/abs/2210.05492>,
   <https://arxiv.org/html/2406.04643v1>
6. Survey of MCTS for imperfect-information games (rollout policy quality dominates).
   <https://arxiv.org/pdf/1906.04439>

Prior-art also reviewed: MageZero (AlphaZero-on-XMage) <https://github.com/WillWroble/MageZero>;
peter1591/hearthstone-ai (MCTS Hearthstone bot); *RL for MTG* practitioner write-ups; CCG-balance and
ABM-calibration papers (see the task transcript for the full 25-source set).

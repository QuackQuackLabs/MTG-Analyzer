# Simulator Architecture — External Research Synthesis (2026-06-23)

> **What this is:** a cited synthesis of a deep, multi-source literature sweep (6 angles, 25 sources
> fetched, 115 claims extracted, 25 adversarially verified — 25/25 confirmed, only 1 non-unanimous).
> It answers: *how should a heuristic, NON-rules-engine simulator for a 4-player Commander free-for-all
> be architected to produce realistic relative win rates?* It is the **external-literature companion**
> to the existing [simulator-realism-research.md](simulator-realism-research.md) (which surveyed the
> game-balance / V&V / politics literature) and the input to
> [simulator-v2-roadmap.md](simulator-v2-roadmap.md) (the replan it motivates). Findings are cited
> `[n]`; sources at the end.

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

## 2. What the research says NOT to build (reinforces golden-rule #5)

- **No card-level rules engine.** Every cited MTG/CCG result runs over a *reduced* or *abstract*
  model, not full rules. The 2012 MTG sweep used reduced rules `[1]`; the AlphaZero-style MageZero
  effort rides on XMage (an existing MIT engine) rather than a bespoke one `[src: MageZero]`.
- **No CFR core** (F2). **No full AlphaZero self-play** as the product (data/compute prohibitive for a
  local tool; insufficient without human regularization, F3).

## 3. The central design tension (and its resolution)

The strongest technique (determinization + MCTS) **needs a forward model** — `step(state, action) →
state'` — which sounds like the forbidden rules engine. **Resolution:** define the forward model over
an **abstract, card-agnostic state** (per player: life, mana/ramp, board-development, cards-in-hand,
answers-held, combo-progress), never over cards/stack/targeting. This is *not* a rules engine under
golden-rule #5 — it is the existing dynamics abstraction made explicit and *searchable*. Validating
that this abstract state is expressive enough is the make-or-break step of the replan (see roadmap
Stage 2.1).

## 4. Honest limits of this research (from the verification caveats)

- The MTG MCTS numbers are a **2012, 1v1, reduced-rules** sweep — **not validated for 4-player
  Commander**. The determinization count and rollout-randomness that fit a 4-player FFA are an **open
  question**.
- Politics evidence is from **Diplomacy** (richer explicit negotiation than EDH table-talk); the 14×
  tactics-over-politics ratio comes from self-play with a comms confidence interval crossing zero —
  treat it as "politics is clearly secondary," not as a precise multiplier.
- **Calibration against a real logged-game corpus is the least-covered area** — *no* source directly
  addresses fitting a heuristic sim to logged outcomes. This is a strong signal to lean on
  **pattern-oriented / ordinal stylized-fact validation** (our existing workstream E + the LOTR
  ordinal anchor) rather than gating progress on an NLL corpus fit.

## 5. Open questions carried into the roadmap

1. Determinization count + rollout-randomness for 4-player FFA vs. the 1v1 sweep.
2. How to weight the politics module against the strategy/search engine for Commander.
3. What corpus + fitting procedure (if any) calibrates the sim — given the literature gap.
4. Whether a human-regularized opponent model is achievable without a large Commander dataset.

## References
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

# Commander Politics Model — grounding the sim in how EDH is actually played

**Status:** ✅ **shipped F1–F5** (workstream F; live status in
[project-plan.md](../project-plan.md) → Phase 9). This doc is the design spec + validation targets;
the research-rationale companion is [simulator-research.md](simulator-research.md) (Part I §F).
**Scope:** re-base the battle sim's threat-assessment, win-attempt, and "gang-up" mechanics on how real
Commander pods behave — casual/mid *and* cEDH — rather than generic multiplayer-AI theory. Grounded in
a two-track community-strategy review (sources at end).

---

## 0. The empirical anchor that drives everything

> In 50 logged 4-player games, the **archenemy seat won 11%** while tablemates won 31/28/26%.
> *(Commander's Herald, verified.)* Baseline is 1/N = 25%; **"to win more than 25% you must make your
> opponents spend resources against each other."** *(cEDH Field Guide.)*

**Target behavior:** the highest-*perceived*-threat deck wins **well below 1/N** (~0.11–0.20), and the
**second-biggest / under-the-radar deck inherits the win**. A model that lets the fastest/strongest
deck *lead* a pod is mis-tuned. This is both the design goal and a validation stylized-fact.

This directly resolves the open A1 question: A1 (realistic per-game timing) is right; it surfaced that
our gang-up was an artifact of the fast deck making many telegraphed attempts. The fix is to model the
*real* gang-up mechanism below, which pushes the fast deck back **below** fair share — not above it.

---

## 1. What real players actually do (findings → model levers)

**Threat is read first from pre-game priors (commander/archetype), then continuously from board
state — dominated by *engines and velocity*, not board size or life.** A player on Rhystic Study/The
One Ring outranks one with a big creature; "life total is a clock, not a scoreboard." `[1][2]`
→ *Lever:* threat = proximity-to-win (realized clock + card/mana advantage), **not** power/board/life.

**The table *identifies* the threat reliably but *coordinates* on it poorly.** Coordination breaks via
removal scarcity, grudge-holding, "do you *need* to kill it now?" politicking, and the **bystander
effect** (three players each assume someone else will answer). `[1]`
→ *Lever:* ganging-up is **probabilistic and uncoordinated** — each opponent independently decides to
commit interaction, discounted by a free-rider term. Wins slip through when everyone free-rides.

**A win attempt makes everyone a defender** — it triggers a *table-wide* answer check against the
union of all opponents' answers. `[2]`
→ *Lever:* resolve a win attempt against pooled willing answers (already moved to this).

**The winner spends the FEWEST answers; the game is a war of attrition.** Each spent answer drops
equity into the *uninvolved* seats' laps, so everyone prefers to wait; baiting/depleting the table
makes a **later** attempt resolve. `[2]`
→ *Lever:* finite depleting reserves (have them); win probability rises monotonically with prior
interaction spent; track "fewest answers spent" as the real win signal.

**Willingness to answer ∝ the defender's own equity.** "If I'm way ahead I snap it off; if I'm behind,
not my problem." `[2]`
→ *Lever:* each defender's answer probability scales with *its own* current win-equity, not a flat rate.

**The quiet ramp/engine/combo player is systematically *under*-targeted — "the fish that's actually a
shark."** Decks that durdle (ramp/draw) accrue real threat the table under-rates. `[1][2]`
→ *Lever:* model **perceived threat ≠ true threat**; combo/ramp archetypes get a perception discount,
so they're under-answered (realistic, and a tunable human blind spot).

**Being the obvious threat is dangerous; reputation/"lightning rod" targeting is a measurable
distortion** (the 11% archenemy). Optimal posture is "calibrated mediocrity"; under-the-radar wins work
**~once**, then reputation overrides board state. `[1]`
→ *Lever:* a `reputation/visibility` bias focuses the highest-*perceived* deck independent of board,
collapsing its win rate below 1/N.

**Going first in a standoff is penalized;** players outwait each other into stalls until someone is
forced to commit and gets answered. `[2]`
→ *Lever:* a go-first penalty; standoff is a stable state the sim can enter/exit.

**Protection beats removal because a win must survive THREE defenders** — free counters/Veil cancel
answers ~1:1. `[2]`
→ *Lever:* an attacker's protection count cancels pooled answers ~1:1 (a future profile field).

**Out-of-contention players turn spoiler** (deny the leader), by etiquette — and that denial is a major
reason the leader can't close. `[1]`
→ *Lever:* a dead-but-alive seat directs interaction at the current leader.

**Pacing.** Casual/mid ≈ **10–13 turns**, snowball inflection ~turn 6–7. cEDH ≈ **5 turns (σ≈2)**.
Interaction density shifts the win turn later. `[1][2]`
→ *Lever:* power-preset horizons (casual vs cEDH); interaction density already feeds the clock.

---

## 2. The model (synthesis)

Per player, per game: a **realized clock** (A1), a **depleting answer reserve**, a **true equity**
(proximity-to-win) and a **perceived threat** (= true equity × archetype-visibility, + reputation).

**Each turn:**
1. Players progress toward their realized clock (A1).
2. **Targeting / archenemy** keys off **perceived threat relative to the table** — the quiet shark is
   under-rated, the visible bomb over-rated; a reputation term over-focuses the top.
3. A player **attempts to win** at its realized clock, gated by a read of live interaction (open
   answers it perceives), with a **go-first penalty** in standoffs.
4. **Resolve via a table-wide answer check:** each opponent commits an answer with probability =
   f(threat-is-lethal, own equity, **free-rider discount** = P(someone else answers), reserve left),
   minus the attacker's protection. Coordination failure (all free-ride) lets it resolve.
5. **Attrition:** spent answers decrement reserves; later attempts succeed more. Out-of-contention seats
   spoiler the leader.
6. Winner = first unanswered win; ties/stalls → inevitability by remaining reserve + equity.

**Net emergent target:** highest-perceived deck wins **< 1/N**; the under-the-radar deck peaks; games
last the preset horizon; spending the fewest answers correlates with winning.

---

## 3. Validation stylized-facts (POM filters — workstream E)

The model must reproduce **all** of these *simultaneously* (independent, mostly ordinal — overfitting-
resistant):
1. **Archenemy < fair share:** the highest-perceived-threat deck wins **below 1/N** (target band
   ~0.11–0.20 in a coordinating pod).
2. **Second-threat peak:** the second-most-threatening / under-the-radar deck has the **highest** win
   rate.
3. **Quiet-shark over-performance:** a combo/ramp deck wins **more** than its visible board suggests.
4. **Attrition monotonicity:** the more interaction the table spent earlier, the **higher** the next
   attempt's success.
5. **Go-first penalty:** the first attempter in a standoff under-performs.
6. **Coordination knob:** raising table-coordination **lowers** the archenemy's win rate (casual <
   coordinated < cEDH focus).
7. **Pacing:** mean win turn matches the preset (~5 cEDH / ~10–13 casual).

---

## 4. Implementation phases
- **F1 — perception split + reputation bias.** ✅ *Shipped.* Targeting keys off
  `perceived_threat = live_threat × archetype-visibility + reputation` (the existing `live_threat` is
  the true-equity proxy). `BattleProfile.visibility` discounts combo (0.70) / grind (0.82); a
  lightning-rod `reputation` term accrues while a deck holds the consensus-archenemy role and decays
  (×0.80). Verified §3.1 (visible archenemy 0.19 < 1/N), §3.3 mechanism (under-perceived deck
  over-performs), §3.6 (coordination knob). The full per-archetype visibility table is deferred to F4.
- **F2 — equity-gated, free-rider-discounted answering.** ✅ *Shipped.* Replaced the flat `POLITICS_*`
  rates with a sequential, most-invested-first answer check; per-defender willingness = capability
  (`answer_prob`) × own-equity gate (peer-relative — protect a lead, shrug if behind) × lethal gate
  (combo/archenemy answered harder than a beatdown) × a flat `ANSWER_COORDINATION` factor (the §3.6
  knob). Note: the elegant "discount by P(someone else answers)" was tried and **rejected** — it is
  unstable (when every opponent is capable they all rationally defer and coordination collapses); a
  flat coordination factor is the robust stand-in. Verified §3.6 (coordination knob monotone) and the
  combo archenemy holds ~0.16–0.20 < 1/N. Attrition (§3.4) emerges from reserve depletion across
  repeated attempts. Protection canceling answers ~1:1 is deferred to F4.
- **F3 — go-first penalty + standoff; spoiler for out-of-contention seats.** ✅ *Shipped.* Attempting
  while opponents hold open answers is suppressed (`GO_FIRST_CAUTION` scaled by the table's open
  reserves) → decks wait out a standoff that attrition breaks (verified: more caution ⇒ longer games).
  A clearly-trailing, late-game seat (`SPOILER_SHARE_MAX`, `SPOILER_MIN_TURN`) answers the table's
  **leader** at boosted willingness (`SPOILER_ANSWER_BONUS`), overriding its own-equity gate → verified
  the leader's win rate drops when spoiler etiquette is active. NOTE: the `pod_blunts_a_fast_deck`
  anchor was converted to **ordinal** here (per enhancement-plan E2, which names this exact 0.18–0.42
  band) — the cumulative F1–F3 archenemy now finishes ~0.15 < 1/N, the design target.
- **F4 — protection count + full visibility table.** ✅ *Shipped.* `BattleProfile.protection` is
  scanned from oracle text (free counters / hexproof / ward / "can't be countered" / indestructible
  grantors) in the battle module (no analysis-pipeline category change). Each landed answer is spent
  (attrition) but fizzles with `cancel_p = PROT_CANCEL_PER_PIECE × protection` (capped) — PROBABILISTIC
  per attempt, since a flat 1:1 count made one piece protect forever. Verified monotone: combo pod win
  0.15 (0 prot) → 0.26 (1) → 0.62 (4) → 0.88 (8, cEDH-dense). Visibility table completed: combo 0.70 <
  grind 0.82 < control 0.92 < midrange 1.0 < aggro 1.10 (a wide board over-reads).
- **F5 — power presets + POM suite.** ✅ *Shipped.* `POWER_PRESETS` (casual | mid | cedh) bundle the
  social/format knobs — table coordination (§3.6 axis), perception sharpness, and go-first discipline
  (casual plays recklessly, cEDH waits) — applied via `simulate_match(preset=…)` and the CLI
  `--preset`. Pacing is reported, not forced: it emerges from the decks' own clocks (verified a fast
  cEDH pod resolves ~5–6 turns, a casual pod ~14, ordinal cEDH < casual). A standoff-impatience term
  (`GO_FIRST_IMPATIENCE`) was added so caution decays past a deck's clock — without it the go-first
  penalty deadlocked games (low attempts → high reserves → high caution → ∞). The §3 stylized-facts
  are now codified as ordinal POM tests (§3.1 archenemy<1/N, §3.2 second-threat inherits, §3.3 quiet
  shark, §3.4 = `interaction_helps_against_combo`, §3.5 standoff, §3.6 coordination/preset, §3.7
  pacing).

Each phase is validated against the §3 stylized-facts (not magnitude anchors), and its parameters enter
the §D global-sensitivity priors so the joint uncertainty band stays honest.

---

## References
`[1]` Casual/mid-power EDH politics — Draftsim & Card Kingdom & EDHREC threat-assessment guides;
Commander's Herald *"Am I the Bolas…"* (the 11% archenemy data) and the *Second-Biggest-Threat*
philosophy; mtgedh.com politics/kingmaking etiquette.
`[2]` cEDH — Sam Black, *When Should You Interact in cEDH?* (Topdeck); Commander's Herald *cEDH Field
Guide* (5-turn/σ2), *State of Control*, *Five Politicking Lessons*, *Winning at Instant Speed*;
Draftsim cEDH threat assessment; Labmaniacs cEDH 101.
_(Full URLs in the session research briefs.)_

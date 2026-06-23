# Commander Politics Model — grounding the sim in how EDH is actually played

**Status:** proposed (workstream F of the [enhancement plan](simulator-enhancement-plan.md)). **Scope:**
re-base the battle sim's threat-assessment, win-attempt, and "gang-up" mechanics on how real
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
- **F1 — perception split + reputation bias.** Add `perceived_threat = true_equity × visibility +
  reputation`; target off perceived. *Reproduces archenemy < 1/N* (fixes the A1 "fast deck leads").
- **F2 — equity-gated, free-rider-discounted answering.** Replace flat `POLITICS_*` rates with
  willingness = f(own equity, free-rider discount, lethal-only). *The core attrition/coordination model.*
- **F3 — go-first penalty + standoff; spoiler for out-of-contention seats.**
- **F4 — protection count** (attacker) canceling answers ~1:1; archetype visibility table.
- **F5 — power presets** (casual/cEDH horizons + coordination level) and the POM stylized-fact tests.

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

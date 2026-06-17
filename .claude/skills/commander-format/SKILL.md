---
name: commander-format
description: Use when writing or reviewing MTG Analyzer code for deck legality validation, color-identity checks, deck scoring/category analysis, power-level/bracket estimation, or game simulation — covers Commander (EDH) deck-construction rules, gameplay rules relevant to simulation, the comprehensive-rules structure, why a full rules engine is infeasible, statistical goldfishing math, archetypes, the bracket system, and deck-composition heuristics.
---

# Commander (EDH) format & rules reference

Official rules: **mtgcommander.net/index.php/rules** (Commander Format Panel) and
magic.wizards.com/en/formats/commander.

## Deck construction (validation logic)

- **Exactly 100 cards** = 99 + 1 commander.
- **Singleton:** no two cards share an English name, **except basic lands**.
- **Commander** must be a **legendary creature**, OR a card with "[Name] can be your commander"
  (some planeswalkers/legends). Partner / Background pairs allow two commanders (combine identities).
- **Color identity restriction (most important rule):** every card's `color_identity` must be a
  **subset** of the commander's color identity. Identity comes from all mana symbols on a card —
  cost *and* rules-text symbols — not the frame color. Use Scryfall's top-level `color_identity`.
- **Banned list** exists and changes — treat as **external versioned data**, never hard-code. Lives
  on the official rules page.
- **Companion** (edge case): a legal companion sits outside the 99 (effectively a 101st card) but
  must still obey color identity + singleton — flag it.
- Legality check = `legalities.commander == "legal"` AND `color_identity ⊆ commander identity` AND
  not on banned list.

## Gameplay rules relevant to simulation

- **Starting life: 40.** Default pod: **4-player free-for-all**, last player standing.
- **Commander damage:** 21+ combat damage from a **single** commander makes that player lose,
  independent of life. Track per-commander, per-player; persists across zone changes.
- **Command zone:** commander starts there (not in the 99's library); can be cast from there.
  On changing zones it may return to the command zone instead.
- **Commander tax:** +{2} generic per *prior* cast from the command zone (2nd cast +2, 3rd +4 …).
- **Mulligan: London** — always draw 7, then bottom one card per mulligan taken before keeping.
  Model this in opening-hand sims.

## Comprehensive Rules (why a full engine is out of scope)

The official Comprehensive Rules is a single living PDF (media.wizards.com/...) — 200+ pages,
hundreds of numbered rules, judge-oriented. Structure: **7 zones** (library, hand, battlefield,
graveyard, stack, exile, command); **turn = 5 phases** (Beginning: untap/upkeep/draw → pre-combat
main → Combat: begin/declare attackers/declare blockers/damage/end → post-combat main → Ending:
end step/cleanup); the **stack** (LIFO) + **priority**; **state-based actions** (checked before
priority — lethal damage, 0 toughness, 0 life, 21 commander damage, legend rule, empty-library draw);
the **layer system** (rule 613: 7 layers for continuous effects, resolved by timestamp + dependency).

**MTG is Turing-complete** (Churchill–Biderman–Herrick 2019) — a faithful, general rules engine is a
multi-year effort and formally cannot be "perfect." **Do not build one.** If true rules-enforced
play is ever required, reuse **XMage** (Java, **MIT** — most reuse-friendly) rather than Forge (GPL,
copyleft). Cockatrice has no rules enforcement. No mature Python engine exists.

## Statistical simulation (the pragmatic path)

"Simulation" in this project = **goldfishing**: measure consistency, no opponent, no full rules.

- **Hypergeometric** (closed-form, exact) for drawing without replacement — opening-hand land count,
  P(see a card / combo piece by turn N), mana-base tuning. Use `scipy.stats.hypergeom`; note scipy's
  param order is `hypergeom(M, n, N)` = (deck size, successes in deck, cards drawn). Model the
  library as **99 cards** (commander in command zone). `P(X ≥ k) = sf(k-1)`.
- **Monte-Carlo** for sequencing questions with no closed form: turns-to-assemble-combo, average
  turn to cast commander, mulligan keep%. Build deck once; per trial shuffle → draw → London-mulligan
  policy → step turns with simple land/ramp/cast heuristics. **Separate engine (shuffle/draw/turn
  loop) from policy (keep rule, what to cast).** Use `np.random.default_rng(seed)` over integer card
  IDs. Report **distributions/percentiles** (turn-to-combo is right-skewed), not just means.
- Frank Karsten's land/color-source counts are hypergeometric tails at ~90% thresholds — treat his
  tables as external data.

## Archetypes (for tagging/classification)

aggro · control · combo · ramp · stax (resource denial) · voltron (load up one creature, win via
commander damage) · aristocrats (sac for value/drain) · group hug.

## Bracket system (official since 2025) — for power-level estimation

Self-rating 1–5: **1 Exhibition** (ultra-casual) · **2 Core** (precon level) · **3 Upgraded**
(tuned, ≤3 Game Changers) · **4 Optimized** (high power, unrestricted short of cEDH) · **5 cEDH**
(fully competitive). **Game Changers** = a curated, evolving list of format-warping cards (~53 as of
Feb 2026) — brackets 1–2 allow none, 3 allows ≤3, 4+ unrestricted. Treat the Game-Changers list as
**external versioned data**; Scryfall exposes a `game_changer` boolean per card. Estimate bracket
from Game-Changer count + combo presence + tutor/fast-mana density.

## Deck-composition heuristics (scoring targets, not hard rules)

For a 99-card deck (Command Zone–style template):

- **Lands ~36–38** (lower with more ramp / lower curve)
- **Ramp ~10–12** (rocks/dorks/ramp spells)
- **Card draw / advantage ~10** (don't go below 10)
- **Spot removal ~10–12** (counterspells can count)
- **Board wipes ~3–4**
- **Remainder (~30+):** payoffs, synergy, and **≥2 clear, ideally redundant/protected win-cons**

Curve peaks around MV 2–3. Operationally, a "good" deck: hits land drops (land+ramp), ≥10 draw
sources, ≥~10 interaction pieces, redundant win-cons, adequate color fixing for its identity. Build a
`gap[category] = max(0, target − count)` vector to drive recommendations.

Sources: mtgcommander.net/index.php/rules · magic.wizards.com/en/formats/commander · Commander
Brackets (mtg.wiki/page/Commander_Brackets) · Comp Rules PDF · epicedh.com/commander-deck-building-template

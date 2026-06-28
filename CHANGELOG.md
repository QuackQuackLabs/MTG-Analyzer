# Changelog — MTG Analyzer

Archived status-log history from [project-plan.md](project-plan.md), which keeps only the current
frontier. Chronological, oldest first. For recent entries see project-plan.md §8 (Status log).

---

- **2026-06-17** — Project kickoff. Research completed (3 briefs). Decisions in §2 confirmed with
  user. Foundation scaffolding + skills + docs created.
- **2026-06-17** — **Phase 0 complete.** Targeted Python 3.11 (installed interpreter; 3.12 not
  needed). venv + `pip install -e ".[dev]"`; `ruff`/`mypy`/`pytest` green. FastAPI `/health` route
  with CORS; Vite + React-TS frontend scaffolded and shows live backend status (verified end-to-end).
- **2026-06-17** — **Phase 1 complete.** Card data layer built: bulk downloader (manifest-tracked),
  ijson streaming ingest into SQLite (cards/printings/rulings), Pydantic Card model with DFC
  handling, async Scryfall client (throttle/429/batch), CLI (`mtg data refresh`, `mtg card`).
  Added `ijson` dep, dropped `sqlite-utils` (stdlib sqlite3). 17 tests, ruff/mypy clean. Ingested
  38,178 cards + 76,805 rulings. Caught + fixed name-resolution bug (art-series cards shadowing real
  cards) — important for Phase 2 decklist parsing.
- **2026-06-17** — **Comprehensive Rules corpus added (Phase 4 item, pulled forward at user
  request)** so card/deck evaluation has the full, queryable game rules. Auto-discovers + downloads
  the official rules `.txt`, parses into rules/subrules/glossary, stores in SQLite + FTS5. Ingested
  3,294 rules + 730 glossary terms (effective 2026-04-17). Fixed two bugs found by spot-checking
  real data: subrule expansion (702.19 wrongly matched 702.190 via LIKE → switched to GLOB
  `[a-z]`), and search (term-AND too strict → bm25-ranked OR). 27 tests, ruff/mypy clean.
- **2026-06-17** — **Combo data folded in** (completes the rules/interaction layer): Commander
  Spellbook live find-my-combos + per-card search, cached locally (on-demand, not a full mirror —
  paging 90k tripped their rate limit). 37 tests.
- **2026-06-17** — **Phase 2 complete.** Decklist parser (Archidekt/Moxfield/Arena/MTGO),
  ManaBox-first header-driven inventory CSV parser, name-first resolution to oracle_id, inventory
  persistence (aggregate by card, keep printings). CLI `mtg deck show`, `mtg inventory import|show`.
  44 tests; ruff/mypy clean. Caught + fixed a resolution bug via real-data validation: set+collector
  tried before name could match a *different* card's representative printing (Sol Ring split into 2
  oracles) → switched to name-first + regression test. `samples/` added for real exports.
- **2026-06-17** — **Phase 2 hardened on real exports.** User provided a ManaBox `.txt` and an
  Archidekt `.csv` (both decks). Added ManaBox `// COMMANDER` marker handling + Archidekt headerless
  CSV deck parsing with auto-detection. Both parse to 100 cards, 0 unresolved.
- **2026-06-17** — **Phase 3a complete (analysis engine).** Validation + category/curve analysis +
  bracket estimate; CLI `mtg deck analyze`. 53 tests. Real-deck validation drove two fixes: Nazgûl
  singleton exemption (and Relentless Rats etc.) and broader ramp detection (signets).
- **2026-06-17** — **Phase 3b complete (recommender).** Blended EDHREC + local recommender: gap-
  filling synergy adds + lowest-play-rate cut candidates (commander/Game-Changer/theme protected),
  buy cost, owned-aware, budget cap. CLI `mtg deck recommend`. 58 tests. Building it surfaced + fixed
  a selection bug (general-upgrades loop dumped all candidates → suggested cutting the whole deck)
  and added cut protections.
- **2026-06-18** — **Combos wired into analysis** + **interface pivot to chat-first** (web UI deferred
  to publishing). `mtg deck analyze` now lists combos present and factors them into the bracket
  (Sauron → Fall of Cair Andros + Blasphemous Act).
- **2026-06-18** — **Phase 5 simulation built.** Hypergeometric module (scipy) + Monte-Carlo goldfish
  (numpy, seeded, London mulligan). CLI `mtg deck simulate`. 63 tests. Fixed a stats bug (opening-hand
  keepable% was measured post-mulligan → ~100%; now measured on the first 7). Sauron: 79% keepable,
  commander castable median T7. Mana model is intentionally approximate (single pool).
- **2026-06-18** — **Recommender is now sim-aware.** `mtg deck recommend` runs before/after goldfish
  sims around the proposed swaps and reports the delta; recommender boosts ramp when the sim shows a
  slow commander / screw. Added `apply_swaps`; noise band on deltas. 65 tests. Sauron swaps →
  commander median turn 7→6.
- **2026-06-18** — **Phase 6 complete (deck construction).** `mtg deck build "<commander>"` greedily
  builds a legal 100 from EDHREC staples ∪ owned cards (owned-first), filling category targets +
  manabase; decklist with owned/buy markers, shopping list, budget cap, `--owned-only`. Plus
  `mtg deck suggest-commanders`. 69 tests. Becomes fully owned-aware once a real collection is
  imported.
- **2026-06-18** — **Interaction/rules Q&A built (Phase 4 complete).** `mtg explain "<card|question>"`
  and `mtg interaction "<a>" "<b>"` retrieve grounded sources (card text + rulings + CR rules +
  glossary + combos); Claude synthesizes the answer in chat. 74 tests. **Core feature set
  (Phases 0–6) is now complete.** Remaining: Phase 7 polish (saved decks, caching) + web UI (publishing).
- **2026-06-18** — **Phase 7 progress: EDHREC caching + saved decks.** `EdhrecCache` (24h TTL in
  app.db) makes recommend/build reuse commander data (1.14s → 0.67s warm). `DeckLibrary` +
  `mtg deck save|list|remove`; deck commands accept a saved name or a path. 78 tests. Saved the two
  sample decks (`sauron`, `cowabunga`).
- **2026-06-18** — **Phase 7 complete.** Added `mtg deck diff`; routed all network calls through
  `_run_network` (explicit offline/rate-limit notes + graceful degradation); added pytest-cov (engine
  85–100% covered, 81 tests) + CLI smoke tests; perf check on the full DB (all ops <40 ms). **Phases
  0–7 complete — the tool is feature-complete for local, chat-driven use.** Only the deferred web UI
  (publishing, §7) remains.
- **2026-06-19** — **Phase 9 scoped (heuristic battle/matchup simulator).** Prompted by a 4-deck
  "who wins" request: confirmed the goldfish sim has no kill/combat/interaction model and can't run a
  true match (golden rule #5). Wrote a full design — `BattleProfile` abstraction from existing
  analyze/simulate signals, heuristic 1v1 + 4-player turn loop with interaction trades + politics,
  and a calibration/sensitivity-band plan — in `docs/battle-simulator-design.md`. Added Phase 9 to
  §4 (A: 1v1 MVP, B: 4-player politics, C: calibration).
- **2026-06-19** — **Phase 9 Phase A built.** `simulation/battle.py` (BattleProfile mapper + turn
  loop), `battle_params.py` (all tunables), `models/battle.py`, CLI `mtg battle`. Handles 1v1 + a
  preliminary pod with threat-focused interaction + archenemy/died-first metrics + sensitivity bands.
  6 invariant tests (95 total; ruff+mypy clean). End-to-end on the real decks: 1v1 Henzie/Sauron
  54–46 (interaction edges the faster combo heads-up); 4-pod Sauron 33 / Tom 26 / Henzie 22 /
  Galadriel 19 (Henzie the archenemy — fastest clock draws the table's answers). **Known gap:** a
  high share of pod games still resolve via the inevitability tiebreak → Phase C calibration target.
- **2026-06-19** — **Phase 9 B + C(partial).** Phase B: dynamic per-turn threat + archenemy-focused
  politics (table commits answers to the live leader, under-answers trailing players → kingmaking),
  per-game archenemy/died-first rates. Phase C: made interaction a **finite reserve** (low refill) so
  pods resolve mid-game — inevitability fallback fell from ~50% → **0–7%**, avg game ~T16 → ~T8;
  added `calibrate_match` + `mtg battle --calibrate` (sweeps the interaction assumption, reports
  per-deck win spread + model health). 8 battle tests (97 total; ruff+mypy clean). New 4-pod read:
  **Tom 38 / Sauron 28 / Galadriel 25 / Henzie 7** (stable across the calibration sweep). *Open
  (Phase C):* real-game fitting; the archenemy penalty on the fastest deck looks overtuned.
- **2026-06-20** — **Phase 9 politics retuned (per user direction: politicking + pre-game power
  awareness, not random).** Replaced pooled all-opponents answering (which crushed the archenemy to
  7%) with a coordinated model: the table commits up to `ARCHENEMY_ANSWERERS` answers to the
  pre-identified archenemy and one to a trailing attacker. Also gated the flat tutor attempt-bonus by
  readiness (it was letting 6-tutor Tom attempt a win on turn 1 → games ending ~T3). New, intuitive
  behavior: fast Henzie wins ~61% in 1v1 but ~19% as the 4-pod archenemy; pod now **Tom 32 /
  Galadriel 30 / Henzie 19 / Sauron 19**, avg game ~T6, 0% inevitability fallback. 97 tests, clean.
- **2026-06-20** — **Phase 9 decentralized threat assessment + politicking engine** (user direction).
  Replaced the single god's-eye archenemy with per-player assessment: each turn every living player
  scores opponents (power baseline `threat_level` + proximity-to-own-kill + `DAMAGE_FEAR_W`×damage
  taken + small `PERCEPTION_NOISE`) and votes; the most-voted is the consensus archenemy and *its
  voters* commit the (capped) answers. Weighted proximity up so the consensus tracks imminent wins,
  not abstract power. Archenemy metric switched to **avg turn-share** (a 4× Galadriel mirror rotates
  it 37/24/22/18, proving the assessment shifts; in the real pod it pins ~95% to Henzie because it's
  far the fastest — a faithful result). Real-deck pod: **Tom 30 / Galadriel 26 / Henzie 24 /
  Sauron 20**; 1v1 Henzie still ~67%. 97 tests, ruff+mypy clean.
- **2026-06-20** — **Plan review + housekeeping ahead of more planning.** Reconciled the plan with the
  working tree: documented **human-named deck files** (NFKD-tolerant `DeckLibrary` resolution) under
  Phase 7, fixed the header status (Phase 9 is the active frontier, not "only the web app remains"),
  and broke Phase 9 C's open work into concrete plannable items (real-game fitting, a validation
  harness beyond the 8 invariants, win/loss explainability). Fixed an ordering bug in a newly-added
  `test_collection.py` case (Café NFD file created after the glob assertion) → suite green at 97.
- **2026-06-20** — **End-to-end validation on real decks (no engine changes).** Exercised the full
  pipeline across the user's library: intake of 4 new decks surfaced + drove the two `DeckLibrary`
  fixes (human-named files, then the NFKD/Unicode `slugify` fix when "Sméagol" failed by-name);
  analyze/sim/guide/recommend used to review and tune every deck; combo detection found the decks'
  real lines (e.g. Sméagol's 8–10 Dúnedain-Rangers loops, Frodo & Sam's Exquisite Blood drains).
  Battle simulator validated end-to-end — a 5-deck LOTR 1v1 round-robin + all five 4-player pods
  produced **intuitive, format-dependent** results (speed wins 1v1: Frodo&Sam/Sméagol on top; pods
  reward grind/under-the-radar: Sméagol/Tom lead, slow Sauron last), confirming the politics + clock
  model behaves sensibly on real inputs. Suite green at 97; ruff+mypy clean across 48 source files.
- **2026-06-20** — **Phase 9 C explainability shipped** (clock-vs-equity gap + attribution). Added
  `clock_rank`/`equity_rank`/`rank_shift` + a one-line `explain` to `DeckWinStats`, a `_ranks` helper,
  and a headline "raw speed is not destiny" note; CLI prints a "Why" section. The rank gap is the
  design §5 metric that surfaces how much interaction + politics reshaped goldfish speed — e.g. the
  real LOTR pod shows Henzie fastest (clock #1) but 3rd in equity (drew the table, archenemy 62%)
  while slow Sauron finishes #1. 2 new battle tests (rank-shift conservation; politics attribution);
  99 total, ruff+mypy clean. Phase 9 C now has 2 open items left (real-game fitting, validation harness).
- **2026-06-20** — **Phase 9 C validation harness (anchor fixtures) + seat-bias fix.** Added 4 anchor
  tests that pin matchup *magnitudes* with tolerance bands (speed dominates 1v1, pod blunts a fast
  deck, 4-mirror symmetric, grind beats aggro) — magnitude regressions, not just A>B relations.
  Writing the mirror anchor immediately caught a real bug: deterministic seat-index tiebreaks gave a
  systematic seat-order advantage (last seat ~38% vs first ~15% among identical decks). Fixed by
  breaking target-selection and archenemy-consensus ties uniformly through the seeded RNG; mirror is
  now ~25%/seat and real (non-identical) pods are unchanged. 103 tests, ruff+mypy clean. **Phase 9 C
  has one open item left: real-game fitting (blocked on a logged-results corpus).**
- **2026-06-20** — **Phase 9 C real-game fitting planned; decisions locked.** Wrote
  [docs/battle-calibration-fitting.md](docs/battle-calibration-fitting.md): Standard logging (pod +
  winner + died-first + end-turn) and an anchor-protected nudge fit (regularize toward defaults,
  reject any fit that breaks the 4 anchors, reversible data/-local override). Split into 9C-1 logging
  infra (not blocked — build first to start recording), 9C-2 fit engine (NLL over ~3–4 knobs via
  Nelder-Mead; needs ~30–45+ games), 9C-3 apply + anchor guardrail.
- **2026-06-20** — **Phase 9 C-1 shipped (real-game logging infra).** `mtg matchlog add|list` +
  `LoggedGame` model + append-only `data/match_log.jsonl` that surfaces malformed rows. Each game
  snapshots the full `BattleProfile` of every pod deck as-played (drift insurance), with optional
  win-method/archenemy fields; `list` shows raw observed win rates + progress toward a fittable
  corpus. Named `matchlog` (not `battle log`) to avoid argparse collision with `battle`'s positional
  decks. 5 tests; 108 total, ruff+mypy clean. **The corpus clock is now running — recording games is
  one command. 9C-2 (the fit engine) unblocks at ~30+ logged games.**
- **2026-06-20** — **Phase 9 C-1 follow-up: interactive `matchlog form`** (user wanted a friendlier
  way to submit data than remembering flags). Run after a game: numbered saved-deck list → pick the
  pod → prompt winner/died-first/turn/method → summary + confirm → save. Shares `_record_game` with
  `add`; selection parsing factored into a pure `_select_indices` and the flow is unit-tested via
  injected I/O. 111 tests, ruff+mypy clean.
- **2026-06-20** — **Combo-awareness Layer 1 (turn-to-combo metric).** The battle sim only knew a
  binary `has_combo`; the goldfish knew nothing. Extended the goldfish to track combo *assembly*:
  `DeckProfile` now carries per-card `oracle_ids`+`is_tutor`; `_compile_combos` turns detected combos
  into specs (non-commander pieces to draw, commander-piece flag, mana gate); `_play_out` records the
  first turn a combo is assemblable (pieces drawn or tutored, commander castable, mana ≥ priciest
  piece). New `SimResult.combo_turn`/`combo_count`, shown by `mtg deck simulate`. Grounded + revealing:
  Tom ~T8 (6 tutors) vs Sméagol ~T11 — its 8 combos share the Dúnedain Rangers piece, so redundancy
  does not speed assembly (confirms the "variants of one engine" read). 3 tests (114 total); clean.
  Layer 2 — wire `combo_turn`/redundancy into the battle-sim clock — is the next step.
- **2026-06-20** — **Reconciled the dynamic-threat rework with the "pod blunts fast combo" invariant.**
  The new board/card-advantage/life live-threat model (good intent: react to the real leader) had
  diluted static threat so a fast combo was no longer the consensus archenemy → it won pods ~96-99%,
  breaking 2 anchor tests. Added `THREAT_COMBO_IMMINENCE_W` — an *online* combo deck (gated by board
  development, so "about to combo off", not flat "fastest = scariest") spikes as the archenemy — and
  raised `ARCHENEMY_ANSWERERS` 2→3 (an imminent lethal draws every able opponent, as the anchor's own
  comment intends). With the concurrent `THREAT_CARDADV_W` sweep (0.55→0.1), all 14 battle tests pass;
  anchor combo blunted to ~34%% (was 96%%); LOTR pod sensible (Galadriel 31 / Tom 29 / Sauron 24 /
  Henzie 17, Henzie the over-focused archenemy at ~90%%). 114 tests, ruff+mypy clean.
- **2026-06-20** — **Combo-awareness Layer 2 (combo-grounded battle clocks).** Wired the goldfish
  `combo_turn`/`combo_count` into `build_profile`: a non-aggro combo deck's clock is now blended
  toward its measured assembly turn (`COMBO_CLOCK_W=0.35`) and redundancy tightens `clock_sd`; aggro/
  cheat decks keep their faster combat clock (the hardcast `combo_turn` would wrongly slow a blitzed
  combo). Battle CLI passes combos to the goldfish; `BattleProfile.combo_count` added. Clocks now
  vary with real combo composition (Sauron 9.0→9.6, Tom 7.3→7.7, Galadriel 7.9→8.2; Sméagol stays
  T4.8). 1 mapper test (115 total; ruff+mypy clean). Open: the absolute scaling (combo_turn is
  hardcast-biased-late) and the lone-fast-deck focus harshness are both real-game-calibration items.
- **2026-06-20** — **Simulator enhancement plan (research-grounded).** Reviewed the full simulation,
  then ran a 4-track literature review (MTG/CCG game-AI, card-game balance simulation, simulation V&V/
  calibration without data, multiplayer "politics" modeling) and wrote
  `docs/simulator-enhancement-plan.md` (later renamed `docs/simulator-realism-research.md`). Thesis from
  the research: realism lives in *stochastic
  structure* not rule detail; derive parameters from deck math (hypergeometric) as *distributions*;
  a single power scalar cannot make rock-paper-scissors (need an interaction term); evaluate the
  *metagame* (Nash-averaging + replicator) as a free no-data calibration signal; and honest
  uncertainty needs *global* SA (LHS/Morris/Sobol), not the current one-knob band, plus
  Pattern-Oriented-Modeling validation to resist overfitting ~12 params to a few anchors. Roadmap
  (no data needed for 1–5): D honest-uncertainty → A stochastic-grounding → E POM harness → F
  politics-consolidation → C metagame-layer → B intransitivity → G/H robustness+data. Tracked as the
  Phase 9 → "Phase 10 (simulator realism & calibration)" frontier.
- **2026-06-20** — **Enhancement plan PR1: honest uncertainty + principled archetype.** (a) §D1:
  `battle_params.PRIORS` registry — the ~12 tunable constants now carry documented (low,high) prior
  ranges. (b) §D2: `simulation/sensitivity.py` — `param_overrides` context manager + Latin-Hypercube
  global SA over all priors → a JOINT win-rate band, with correlation-based screening of which params
  drive the spread (Morris/Sobol the documented next step). (c) §D3: `mtg battle --sensitivity` prints
  the honest joint band + top drivers; the default band is relabeled "interaction-only". (d) §A4:
  replaced the creature-count archetype classifier with a principled "combo is primary iff combo_turn
  <= commander-online + COMBO_PRIMARY_GAP" test (reclassifies post-overhaul Galadriel midrange→combo).
  Result: the LOTR pod joint band is far wider/honest (Henzie 22%% but [14%%–33%%] vs the old ~[16-19]),
  exposing real parametric uncertainty. 4 tests (118 total); ruff+mypy clean.
- **2026-06-20** — **Commander politics model (research-grounded, workstream F plan).** Two-track
  community-strategy review (casual/mid + cEDH) → `docs/commander-politics-model.md`. Headline
  empirical anchor (50 logged games): the **archenemy seat wins ~11%**, not the 25% fair share — the
  strong/fast deck should win *below* 1/N, and the under-the-radar deck inherits wins. This resolves
  the A1 question: A1 (realistic per-game timing) is correct but exposed that our gang-up was an
  artifact of many telegraphed attempts; the fix is the real EDH politics model — perceived-threat ≠
  true-equity, reputation/lightning-rod focus, table-wide answer check with equity-gated +
  free-rider-discounted willingness, attrition (winner spends fewest answers), go-first penalty,
  spoiler-on-leader, power-preset pacing (casual ~10-13 / cEDH ~5). Plan: F1 perception+reputation →
  F2 equity/free-rider answering → F3 standoff/spoiler → F4 protection → F5 presets+POM tests.
  A1 code change is staged uncommitted pending F1 (A1 alone makes the fast deck lead, which is wrong).
  *(Resolved 2026-06-22: F1–F5 shipped; A1's realized-clock logic is integrated in `battle.py` and the
  fast deck now correctly finishes below 1/N as the archenemy.)*
- **2026-06-22** — **Workstream F1 shipped (perception split + reputation/lightning-rod).** The table
  now targets off `perceived_threat = live_threat × archetype-visibility + reputation` instead of raw
  live-threat. `BattleProfile.visibility` (combo 0.70 / grind 0.82 / else 1.0; full table deferred to
  F4) under-reads durdle decks; a `reputation` accumulator bumps the consensus archenemy each turn and
  decays (×0.80), so the table stays fixated semi-independent of board state — collapsing the
  highest-perceived deck below fair share. Verified the F1 stylized-facts: archenemy < 1/N (visible
  fast combo **0.19** in a fair pod), the quiet-shark mechanism (identical decks, visibility-0.7 deck
  wins **0.62** vs ~0.13), and the coordination knob (archenemy win falls monotonically as answer-base
  rises). New continuous knobs (`REPUTATION_W/DECAY/STATIC_W`) added to `PRIORS` for global SA. 2
  ordinal POM tests added; the deliberately-pinned `pod_blunts_a_fast_deck` anchor still holds (no
  rewrite needed). 120 tests, ruff+mypy clean.
- **2026-06-22** — **Workstream F2 shipped (equity-gated, free-rider-discounted answering).** The flat
  `POLITICS_ARCHENEMY/NONARCH` answer multipliers are gone; a win attempt now fires a sequential,
  most-invested-first answer check where each opponent's willingness = capability × peer-relative
  own-equity gate × lethal gate (a combo/archenemy is answered harder than a beatdown swing) × a flat
  `ANSWER_COORDINATION` factor. Two dead-ends recorded: (1) a *parallel* over-commit drained reserves
  ~2× too fast; (2) the elegant "discount by P(someone else answers)" free-rider product is unstable —
  when all opponents are capable they rationally all defer and coordination collapses against the very
  threat the table reads clearest. The flat coordination factor is the robust stand-in and doubles as
  the §3.6 knob / F5 casual↔cEDH axis (verified monotone: combo win 0.31→0.10 as coordination
  0.65→0.90). A subtle bug — the equity-gate baseline initially included the attacker, whose lethal
  spike floored every defender's gate — was fixed by averaging over peers only. Both pre-F deck anchors
  (`pod_blunts_a_fast_deck`, `grind_out_values_aggro`) kept passing by setting the new beatdown
  lethal-gate to 0.65, so no anchor rewrite was needed while the archenemy still finishes < 1/N. 1 POM
  test; 121 total, ruff+mypy clean.
- **2026-06-22** — **Workstream F3 shipped (go-first penalty + standoffs + spoiler-on-leader).** Two
  mechanics from how real pods stall and police a frontrunner. Go-first: `p_attempt` is suppressed in
  proportion to the table's *open* answers (`GO_FIRST_CAUTION` × Σ opponent reserve / `STANDOFF_OPEN_REF`)
  — savvy decks wait rather than go first into a loaded table, and F2 attrition is what finally drains
  reserves and forces someone to commit (verified: more caution ⇒ longer games, 8.7→10.0 turns).
  Spoiler: a clearly-trailing, late-game seat (`SPOILER_SHARE_MAX`, `SPOILER_MIN_TURN`) answers the
  table **leader** at boosted willingness (`SPOILER_ANSWER_BONUS`), overriding the equity gate that
  would say "not my problem" (verified: leader win 0.255→0.214 with spoiler on). The cumulative F1–F3
  model now puts the visible archenemy at **~0.15 < 1/N**, exactly the design target — so the
  `pod_blunts_a_fast_deck` magnitude anchor was converted to **ordinal** (a research-led call: the
  enhancement plan's E2 explicitly names this "0.18–0.42" band as the kind to convert, and equifinality
  makes a pinned magnitude dishonest). The relations + a loose regression floor are retained. 2 POM
  tests; 123 total, ruff+mypy clean.
- **2026-06-22** — **Workstream F4 shipped (protection + full visibility table).** Added
  `BattleProfile.protection`, scanned from oracle text by a battle-module-local regex (free counters,
  hexproof/ward/shroud, "can't be countered", indestructible/protection grantors) — kept out of the
  analysis categorizer's `_REPORTED` set so `DeckReport` and its tests are untouched. In the answer
  check, each landed answer is still spent (attrition) but fizzles with `PROT_CANCEL_PER_PIECE ×
  protection` (capped at 0.75). First pass used a flat 1:1 cancel COUNT and blew up (one piece →
  combo 0.68, because the combo re-attempts every turn so one piece protected forever); the
  probabilistic per-attempt model is the fix and is monotone/graded: combo pod 0.15→0.26→0.62→0.88 as
  protection 0→1→4→8 (a cEDH-dense combo over-performs even as archenemy — "a win must survive three
  defenders, free counters cancel them 1:1"). Completed the archetype-visibility table
  (combo 0.70 < grind 0.82 < control 0.92 < midrange 1.0 < aggro 1.10). 3 POM tests; 26 battle / 126
  total, ruff+mypy clean.
- **2026-06-22** — **Workstream F5 shipped (power presets + POM suite) — workstream F complete.**
  `POWER_PRESETS` (casual | mid | cedh) bundle the social/format knobs: table coordination (the §3.6
  axis — casual coordinates poorly, cEDH gangs the archenemy), perception sharpness, and go-first
  discipline (casual plays recklessly, cEDH waits). Applied as temporary `battle_params` overrides by
  `simulate_match(preset=…)` and surfaced via CLI `mtg battle --preset`. Pacing is reported, not forced
  — it emerges from the decks' own goldfish clocks (verified: a fast cEDH pod resolves ~5–6 turns, a
  casual pod ~14; the POM test pins the ordinal cEDH<casual since magnitudes are deck-driven/equifinal).
  Fixed a go-first DEADLOCK (low attempts → high reserves → high caution → games pegged at the 24-turn
  cap) by adding `GO_FIRST_IMPATIENCE`: caution decays the longer a deck sits past its clock, so someone
  is eventually forced to commit (the doc's own standoff-resolution mechanism). All seven §3 stylized-
  facts are now codified as **ordinal POM tests** (archenemy<1/N; second-threat inherits; quiet shark;
  attrition = the existing interaction-helps invariant; standoff lengthening; coordination/preset
  ordering; pacing). 4 POM tests; **130 total, ruff+mypy clean. Workstream F (commander-politics realism)
  is fully shipped F1–F5.**
- **2026-06-22** — **Planning consolidated — one source of truth.** Folded the simulator-enhancement
  plan's *planning* (the workstream A–H tracker + prioritized roadmap) into this file under Phase 9 →
  *Simulator realism & calibration — research workstreams (A–H)*, with an at-a-glance status table
  (D ✅, F ✅; A ◐ A1/A4 only, E ◐, H ◐ = 9C; B/C/G ☐) and a **naming-collision note** distinguishing
  the research workstreams A–H from the Phase A/B/C *build* phases. `docs/simulator-enhancement-plan.md`
  is now a **research reference only** (renamed `docs/simulator-realism-research.md`: literature thesis,
  per-workstream rationale + citations, non-goals, references) with a banner pointing here for status;
  its today→future table and roadmap were
  removed (→ pointers). Updated the `commander-politics-model.md` status header (proposed → shipped,
  status lives here). Prompted by the §F drift caught earlier — two planning docs were the root cause.
  Docs-only; no code change (tests unchanged at 130).

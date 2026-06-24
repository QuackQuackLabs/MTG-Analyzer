# MTG Analyzer — Project Plan

> **Living document.** Every agent reads this before starting and updates status/checkboxes when
> finishing a unit of work. Last updated: **2026-06-23**.
>
> **Status: Phases 0–8 complete; Phase 9 (battle simulator) in progress (A+B shipped, C calibration
> open; politics workstream F1–F5 shipped).** Feature-complete for local, chat-driven use (analyze,
> recommend, simulate, build-from-collection, combo/interaction Q&A, **collection management + strategy
> guides**, and a heuristic **battle/matchup simulator** with **combo-aware clocks** and a
> **research-grounded commander-politics model** (perception/reputation, equity-gated answering,
> standoff/spoiler, protection, power presets); 131 tests, ruff+mypy clean). **Active work: Phase 9 was
> REPLANNED 2026-06-23** after validation showed the battle sim ranks decks ~inverted (speed-monocausal)
> — the new staged roadmap is **[docs/simulator-v2-roadmap.md](docs/simulator-v2-roadmap.md)**.
> **Stage 0 (correctness) SHIPPED 2026-06-23**: decoupled the win-clock from the deploy clock
> (`combo_clock`) so incidental-combo aggro decks no longer score instant turn-3 combo kills — LOTR
> rank-distance 16 → 10. **Stage 1 (richer equity) SHIPPED 2026-06-23**: a mid-game attrition/grind win
> path (interaction + resilience, heat-discounted for the archenemy, margin-gated to protect anchors)
> gives slow interaction-dense decks the win path the clock denied them — LOTR rank-distance **10 → 4**
> (Sauron last→2nd, Frodo 1st→last). **Stage 2 (search) PROTOTYPED 2026-06-23, full build NOT committed:**
> built the abstract resumable forward model (`battle_search.py`) — its 2.1 gate reproduces production
> exactly — and a determinized-search prototype; measured that search does NOT improve the ranking (dist
> stays 4, adds skillful-timing texture only), confirming the decision gate. **Stage 3 (politics)
> AUDITED + PROTOTYPED 2026-06-23:** ablation shows politics is appropriately *secondary* (fundamentals
> → dist 6, politics refines to 4) with impact concentrated in the validated perception/lightning-rod
> mechanism; prototyped a stable CICERO-grounded coordination model (opt-in) that reproduces the ranking.
> **Stage 3c (metagame-knowledge feedback loop) SHIPPED 2026-06-23 — the breakthrough:** the table now
> targets decks KNOWN to win (each deck's realized win rate fed back as a threat prior via a damped
> fictitious-play loop, `simulate_metagame` / `mtg battle --metagame`), fixing the bug where a never-wins
> aggro deck was the turn-1 archenemy and a quiet winner was never targeted. **Converges to LOTR
> rank-distance 0 — a perfect match to the experienced-player ranking** (Sauron last→1st, Frodo's
> archenemy 84%→68%, spread 33pp→27pp). Opt-in (one-off `mtg battle` unchanged). Deferred: the web app
> (publishing, §7). Primary interface is chat via Claude Code.

## 1. Vision

A local, single-user tool for **Magic: The Gathering Commander (EDH)** players that:

- Ingests the user's **card inventory** and **decklists**.
- Bundles MTG rules knowledge: the **Comprehensive Rules** + **card-specific rulings** (Scryfall),
  plus a live link to Scryfall for card lookups, combos, and interaction questions.
- **Validates and scores** decks (Commander legality, color identity, curve, category balance,
  combos present).
- **Simulates** games statistically and reports consistency analytics (opening hands, mulligans,
  turn-to-cast-commander, turn-to-combo).
- Produces **upgrade recommendations** and a **budget-aware shopping list** — both from simulation
  output *and* from static deck analysis without running the sim.
- **Constructs decks** from the inventory (+ a shopping list for the gaps).

**Operating context:** runs entirely on Jacob's Mac, one user, no auth, no hosting. Publishing is a
future item (§7), and the architecture keeps it reachable.

## 2. Confirmed decisions (2026-06-17)

| Decision | Choice | Rationale |
|---|---|---|
| Language / engine | **Python 3.11+** | Best fit for the data/analytics/simulation core; scipy/numpy; the data ecosystem (pyedhrec etc.) is Python. |
| Interface | **Chat-driven via Claude Code (primary)** — the engine is exercised through chat; Claude runs commands + interprets. **Web app (FastAPI + React) deferred** to the publishing phase (§7). | Updated 2026-06-17: user prefers chat over terminal/UI for personal use. Engine stays UI-agnostic so a web app can be added later for publishing. |
| First milestone | **Deck analysis + recommendations** (no simulator required) | User-chosen. Highest value per effort; works day one. |
| Card data | **Scryfall bulk data** ingested into local **SQLite**, keyed on `oracle_id`; live API only for autocomplete/fuzzy/ad-hoc search | Scryfall is the sanctioned, documented source; bulk is the right tool for inventory-scale work. |
| Simulation fidelity | **Statistical / heuristic goldfishing** (hypergeometric + Monte-Carlo). **No full rules engine.** | MTG is Turing-complete; a faithful engine is multi-year. Full rules-enforced play deferred to future (reuse XMage, MIT) — §7. |
| Combo detection | **Commander Spellbook** (MIT, open backend) via `/find-my-combos` + cached `/variants/` | Sanctioned open API; powers EDHREC's combo feature. |
| Recommendation data | **EDHREC** unofficial `json.edhrec.com` (via `pyedhrec`), cached nightly | De-facto Commander stats source; pair with Scryfall for all card data. |

## 3. Architecture

```
backend/mtg_analyzer/   Pure-Python engine (importable, testable without FastAPI)
  data/        Scryfall bulk download/refresh + local SQLite card DB
  models/      Pydantic: Card, Deck, Inventory, Ruling, Recommendation
  ingest/      Decklist + inventory parsers; resolve to Scryfall identity
  rules/       Commander legality; comprehensive-rules store; rulings lookup
  analysis/    Category + curve analysis; deck scoring
  combos/      Commander Spellbook client + matcher
  simulation/  hypergeometric (scipy) + Monte-Carlo (numpy) goldfish sim
  recommend/   recommender + deck construction + budget shopping list
  api/         FastAPI app (thin adapter over the engine)
frontend/      React + Vite + TypeScript SPA
data/          local card DB, bulk cache, rules text (gitignored, regenerable)
tests/         pytest
.claude/skills/ scryfall-api · commander-format · mtg-data-ecosystem
```

**Identity model:** every entity joins on Scryfall `oracle_id`. Resolution priority when parsing
files: `Scryfall ID → (set code + collector #) → (name + set) → name-only (flag ambiguous)`.

**Key data assets to treat as external + versioned (never hard-code):** Commander banned list,
"Game Changers" list (~53 cards as of Feb 2026), Frank Karsten color-source tables.

## 4. Phases & milestones

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Update inline as work completes.

### Phase 0 — Foundation  `[x]`
- [x] Research (Scryfall API, Commander rules + simulation feasibility, data ecosystem).
- [x] Repo init, directory skeleton, `pyproject.toml`, `.gitignore`, `CLAUDE.md`, this plan.
- [x] Domain skills authored (`scryfall-api`, `commander-format`, `mtg-data-ecosystem`).
- [x] Python venv (3.11) + `pip install -e ".[dev]"`; `pytest`/`ruff`/`mypy` run clean.
- [x] FastAPI app + `/health` route (CORS for Vite origin); Vite/React-TS app shows backend status.
- [x] Initial git commit.

### Phase 1 — Card data layer  `[x]`
- [x] `data/bulk.py`: `/bulk-data` poller → stream-download **Oracle Cards** + **Rulings**, manifest
      tracks `updated_at`, re-downloads only when it changes. (httpx decodes gzip → plain JSON on disk.)
- [x] `data/db.py`: streaming ijson ingest into SQLite. `cards` keyed on `oracle_id` (+ `printings`
      keyed on `id` for price/set/image, + `rulings`). Indexes on name, front_name, ci_key, cmc,
      commander legality. Non-gameplay layouts (art series/tokens/emblems) flagged + deprioritized.
- [x] `models/card.py` (Pydantic) — Card/CardFace/Ruling with DFC handling driven off `layout`.
- [x] `data/scryfall_client.py` (httpx async, custom UA/Accept, ~100 ms throttle, 429 backoff):
      `/cards/named` (fuzzy/exact), `/cards/autocomplete`, `/cards/search`, `POST /cards/collection`
      (auto-chunked ≤75).
- [x] Rulings lookup from bulk file, joined on `oracle_id`.
- [x] Tests (no network): ingest fixture, name/front-face resolution, DFC parsing, rulings join,
      client header/chunk/429 behavior via MockTransport. CLI `mtg data refresh` / `mtg card`.
- **Ingested 38,178 cards + 76,805 rulings locally (~9 s).** Name resolution verified on real data.

### Phase 2 — Ingest: decks & inventory  `[x]`
- [x] **Decklist parser** (`ingest/decklist.py`): tolerant `[SB:] N[x] Name [(SET) [#]] [*F*]
      [[Category]]` + section headers + `//`/`#` comments. Covers Archidekt-text, Moxfield/Arena/MTGO,
      and **ManaBox `.txt`** (`// COMMANDER` comment-markers + blank-line section reset). Card-name
      parens preserved (set group is space-free). `parse_deck` auto-detects **Archidekt CSV deck
      exports** (headerless, positional; commander via category, set/collector/section captured) vs
      text. *Validated on real exports: Sauron ManaBox txt → [BRU] 100 cards; Leonardo Archidekt csv
      → [BGRUW] 100 cards, 0 unresolved.*
- [x] **Inventory CSV parser** (`ingest/inventory.py`): ManaBox-first, header-driven (matches by
      normalized header, not position) → also reads Moxfield/Deckbox/Archidekt collection CSVs.
- [x] **Resolution** (`ingest/resolve.py`): **name-first** → oracle_id (reliable, unique), with
      scryfall_id / set+collector as fallbacks. Unresolved entries surfaced, not dropped.
      `data/inventory_store.py` persists inventory (per-printing rows, aggregate by oracle_id).
      Models: `models/deck.py`, `models/inventory.py`. CLI `mtg deck show`, `mtg inventory import|show`.
- [x] Tests (`test_ingest.py`): Archidekt/Arena parsing (foil, categories, the `Erase (Not the
      Urza's Legacy One)` name edge case), deck resolution, ManaBox CSV, inventory aggregation, and a
      regression for name-first (a mismatched set+collector must not override the name).
- **Validated on the real 38k-card DB:** Atraxa deck resolves to `[BGUW]`; a ManaBox CSV aggregates
  Sol Ring to owned 3 across 2 printings. Drop real exports in `samples/` to harden further.

### Phase 3 — Deck analysis & validation  `[~]` ← **first user-facing milestone**
Staged: **3a** analysis engine (this) → **3b** recommender + shopping list → **3c** FastAPI routes →
**3d** React views.
- [x] **3a — Analysis engine** (`analysis/`, `models/analysis.py`). **Validation:** exactly 100,
      singleton (basics + "any number / up to N named" cards like Nazgûl/Relentless Rats exempt),
      legal commander check, `color_identity ⊆ commander identity`, banned + Game-Changer via Scryfall
      per-card fields (no hard-coded lists). **Category analysis:** heuristic classifier (type line +
      oracle-regex, Archidekt category as a hint) → counts vs Command-Zone targets (37 land / 10 ramp
      / 10 draw / 10 removal / 3 wipes) → gaps. **Curve:** nonland CMC histogram. **Bracket estimate**
      (1–5) from Game-Changer + tutor density (combo-refined in Phase 4). CLI `mtg deck analyze`.
      Tests in `test_analysis.py`. *Validated on real decks: Sauron → LEGAL, bracket 4 (4 Game
      Changers); the Nazgûl/signet cases drove two real fixes.*
- [x] **3b — Recommendations (blended, no sim):** `recommend/edhrec.py` (EDHREC client, throttled,
      resolves candidates by name) + `recommend/recommender.py`. Adds = EDHREC synergy cards
      classified into the deck's gaps (ramp/draw/removal/wipe), respecting color identity / singleton
      / not-in-deck / budget. Cuts = deck's lowest play-rate cards, protecting commander / Game
      Changers / singleton-override theme cards / **combo pieces** (cards used by a combo present in
      the deck — `recommend` fetches the deck's combos and passes them as protected). Buy cost +
      owned-aware (inventory). CLI
      `mtg deck recommend --budget`. Tests in `test_recommender.py`. *Validated on Sauron: 8 gap-
      filling adds (~$4.86) + 8 cut candidates; protects Sol Ring / Nazgûl / Game Changers.*
- [~] **3b — Budget shopping list:** buy cost + owned vs not-owned via inventory done. TODO:
      functional cheaper-substitute suggestions (same role, lower price).
- [~] **3c/3d — Web app (FastAPI routes + React views): DEFERRED to publishing (§7).** Primary
      interface is now chat-driven. Keep the engine UI-agnostic so these can be added later. The
      existing `/health` FastAPI app + Vite scaffold remain as the seed.

### Phase 4 — Combo & interaction detection  `[x]`
- [x] **Comprehensive Rules corpus (pulled forward).** `rules/comprehensive.py` auto-discovers the
      current rules `.txt` from magic.wizards.com, downloads + parses it (sections / categories /
      rules / subrules + glossary). `rules/store.py` stores it in `app.db` with FTS5 search:
      exact rule lookup, subrule expansion (GLOB letter-class, not LIKE), ranked full-text search
      over rules + glossary. CLI `mtg rules refresh|get|search|glossary`. Tests in `test_rules.py`.
      *Ingested 3,294 rules + 730 glossary terms (effective 2026-04-17).*
- [x] **Commander Spellbook client** (`combos/client.py`): live `/find-my-combos` (authoritative —
      resolves `requires` templates server-side; returns included + almost-there buckets) and a
      per-card `/variants/?q=card:"…"` search. Conservative ~3 req/s pace + exponential 429 backoff.
      **On-demand, not a full mirror:** find-my-combos covers all ~90.5k commander-legal combos
      server-side (always current), so we query live + cache rather than scraping 900+ pages — which
      tripped the API's rate limit and is poor citizenship (their own guidance: self-host the MIT
      backend for true bulk; deferred to §7).
- [x] **Local combo cache** (`combos/store.py`): caches fetched combos in `app.db` (combos +
      combo_cards on `oracle_id`); `add` (cache-through upsert) + `combos_using` + offline
      `find_in_deck` (uses-based; template combos confirmed via the live endpoint). CLI
      `mtg combos card|find`. Tests in `test_combos.py` (incl. a regression for a pagination
      infinite-loop bug where an empty `params={}` stripped the `next` URL's query).
- [x] **Combos wired into deck analysis:** `mtg deck analyze` calls find-my-combos and lists combos
      present; the bracket estimate now factors combo count (a two-card combo → bracket 3+). Graceful
      offline degradation (`--no-combos`). *Sauron → detects Fall of Cair Andros + Blasphemous Act.*
- [ ] Suggest color-identity-legal combos to *add* (the live "almost included" bucket already
      provides one-card-away suggestions — surface them in recommendations).
- [x] **Interaction/ruling Q&A** (`rules/qa.py`, `models/qa.py`): `explain_card` (oracle text +
      official rulings + CR rules for the card's keywords + glossary + combos), `search_knowledge`
      (free-text FTS over rules + glossary), `explain_interaction` (both cards' grounding + combos
      between them). CLI `mtg explain "<card or question>"` and `mtg interaction "<a>" "<b>"`. The
      engine *retrieves grounded sources*; Claude synthesizes the answer in chat. Tests in
      `test_qa.py`. *Demo: Blasphemous Act → 4 rulings + 10 combos; the Fall of Cair Andros + Blasphemous
      Act interaction pulls the "excess damage = above lethal" ruling + Amass rule.*

### Phase 5 — Game simulation & analytics  `[~]`
- [x] **Hypergeometric module** (`simulation/probability.py`, scipy): exact P(≥k of a group in N
      draws), `cards_seen_by_turn`, `p_see_by_turn`. Models the 99-card library.
- [x] **Monte-Carlo goldfish** (`simulation/goldfish.py`, numpy seeded RNG): `DeckProfile.from_resolved`
      (land/ramp/cmc arrays), London-mulligan keep-2–5 policy, turn loop (land drop, ramp deploy,
      commander-castable check). Engine separate from policy. Honestly approximate: single mana pool,
      no colored requirements, ramp = +1 from next turn.
- [x] **Metrics** (`models/simulation.py`): avg opening lands, keepable%, exact P(≥3 lands),
      flood/screw rates, avg mulligans, commander-castable turn (median/mean/p90/never%). CLI
      `mtg deck simulate [--games --draw]`. Tests in `test_simulation.py` (incl. determinism).
      *Sauron: 79% keepable, 50% P(≥3 lands), 1% screw, commander castable median T7.*
- [x] **Feed sim into the recommender:** `mtg deck recommend` now simulates **before/after** the
      proposed swaps and shows the delta (keepable / screw / commander-turn), and the recommender
      weighs sim signals (slow commander or high screw → boosts ramp priority, with an explanatory
      note). `apply_swaps` builds the hypothetical post-swap deck. Sub-`band` deltas shown as "≈ same"
      to avoid labeling sim noise. *Sauron: swaps pull commander median turn 7 → 6.* `--no-sim` to skip.
- [x] **turn-to-combo metric** (combo-awareness Layer 1): the goldfish sim tracks the turn any combo
      assembles — pieces drawn (or tutored), commander pieces free from the command zone, redundancy =
      earliest across all combos, mana-gated by the priciest piece. `simulate(deck, combos=…)` →
      `SimResult.combo_turn`/`combo_count`; shown by `mtg deck simulate` (`--no-combos` to skip).
      Reveals real structure: Tom assembles ~T8 (6 tutors), while Sméagol's 8 *shared-piece* variants
      don't beat a clean 2-card combo (~T11). 3 tests.
- [x] **combo-awareness Layer 2**: `build_profile` now grounds a *non-aggro* combo deck's battle clock
      in its goldfish `combo_turn` (blended with the archetype estimate, since `combo_turn` assumes
      hardcasting; aggro/cheat decks keep their faster combat clock), and combo redundancy tightens
      `clock_sd`. `BattleProfile.combo_count` added; the battle CLI now passes combos to the goldfish.
      Clocks vary with actual combo composition instead of a flat archetype constant (Sauron 9.0→9.6,
      Tom 7.3→7.7, Sméagol stays T4.8). *Absolute scaling is the calibration target (real-game fit).*
- [ ] sim charts (deferred with the web UI).

### Phase 6 — Deck construction from inventory  `[x]`
- [x] **`recommend/builder.py`**: `build_deck(commander, owned, db, edhrec_cards, *, budget,
      owned_only)`. Greedy build over EDHREC recommendations ∪ owned cards (filtered to identity +
      Commander-legal): fills functional targets (37 land / 10 ramp / 10 draw / 10 removal / 3 wipe)
      owned-first then by synergy, then payoffs, then a manabase (owned nonbasic lands + basics split
      by color). `models/build.py`.
- [x] **Output:** decklist grouped by category with owned ✓ / buy $ markers + a shopping list and
      total cost. Budget cap (skips buys over budget, reports if short). `--owned-only` mode. Notes
      report category shortfalls.
- [x] **`mtg deck build "<commander>" [--budget] [--owned-only]`** + **`mtg deck suggest-commanders`**
      (legal commanders in your collection, by popularity). Tests in `test_builder.py`.
      *Demo: full 100-card Sauron list from EDHREC staples ($311 buy); $20-budget → 84/100; owned-only
      with the tiny test inventory → 40/100 with clear shortfall notes.*
- Seeds from EDHREC recommendations (∩ inventory via owned-first). Manabase upgrade
  (duals/fetches) is a future refinement.

### Phase 8 — Collection management & strategy guides  `[x]`
- [x] **Unified inventory with locations** (`data/inventory_store.py` + `data/collection.py`): one
      `data/inventory.csv` (master, with a **Location** column) + per-deck files in `data/decks/`.
      Imported "extra" CSVs = the **Available** pool; every registered deck's cards are merged in
      `Location = <deck slug>`. `mtg inventory import|sync|show`; `deck save` auto-syncs. Migration
      adds `location` to pre-existing inventory tables.
- [x] **Availability-gated recommend/build:** upgrades/building only use cards that are Available
      (or already in the target deck) — a card committed to another deck isn't suggested
      (basics/"any number" exempt). `inventory show --card` lists where each copy lives.
- [x] **Strategy guides** (`analysis/guide.py`): `mtg deck guide <name>|--all` composes a pilot's
      1-page markdown guide (game plan, win cons + combo lines, mulligan from sim, sequencing, key
      cards, at-a-glance) → `data/guides/<slug>.md`. Grounded in analysis + sim + Commander Spellbook.
- [x] **Win-condition analysis** (in `guide.py`): the Win conditions section now follows deck-primer
      best practice — names a **Primary** path and **Backups** (redundancy), and for each combo
      classifies its produced features as **terminal** (wins outright) vs. an **engine** that needs an
      outlet, then names the payoff card in the deck that converts it (or flags *no outlet — gap*).
      Adds a **kill-on-sight** line (combo pieces to protect). Near-duplicate combo variants are
      capped (top 6 by popularity, rest collapsed to a count) to keep guides to ~1 page.
- [x] **Combo-less decks get the same depth** (in `guide.py`): guides no longer collapse when a deck
      has no Spellbook combo. The win plan is recovered from the deck itself — deck-wide **finishers**
      detected from card text (drain/aristocrats, group-slug, overrun/anthem, combat-amplifier, burn,
      alt-win) reusing the outlet machinery; an **Engine lines** section parallel to Combo lines; a
      kill-on-sight line over the detected payoffs; and an **archetype label** (from real deck signals:
      creatures, instants/sorceries, token-makers, symmetric draw, +1/+1 counters, interaction, ramp)
      that tunes the Game plan + Sequencing prose. Fixes thin/mislabeled guides for precon-level decks
      (e.g. Bloomburrow Zoraline now reads as aristocrats with a Psychosis-Crawler/drain kill, not
      "Combat"). Same grounded-no-invented-strategy rule.
- *Validated on real data: 1,043 distinct cards imported (0 unresolved); Sol Ring tracked across
  Available + 3 decks; Henzie guide lists all 3 combos with steps; Galadriel's infinite-token engine
  correctly names Craterhoof Behemoth as its outlet.* 139 tests; ruff/mypy clean.

### Phase 7 — Polish & quality  `[x]`
- [x] **Saved deck library** (`data/deck_library.py`): `mtg deck save|list|remove|diff`; all deck
      commands accept a saved name *or* a file path (`load_deck_text`). Decks stored as text under
      `data/decks/` (gitignored). `deck diff` shows added/removed cards between two decks. *(Auto
      version-history snapshots deferred — diff covers the practical need.)*
  - [x] **Human-named deck files** (`slugify` via NFKD accent-strip + tolerant `_find`): a file
        dropped into `data/decks/` as `Frodo and Sam.txt` / `Sméagol.txt` resolves by display name,
        slug, or canonical form, robust to macOS NFD vs. NFC; `save` overwrites the existing file
        instead of creating a slug-named duplicate. Covered by `test_collection.py`.
- [x] **EDHREC caching** (`EdhrecCache`): 24h TTL in `app.db`; `recommend`/`build` reuse cached
      commander data (cold 1.14s → warm 0.67s, no network). Scryfall bulk refreshes via the manifest.
      *A scheduled nightly cron is an ops concern (run `mtg data refresh` + `mtg rules refresh`).*
- [x] **Error/offline handling:** all network calls (Commander Spellbook, EDHREC) route through
      `_run_network` — on failure they print a clear "unavailable (offline or rate-limited); skipped"
      note and degrade gracefully; unresolved cards are reported, never silently dropped.
- [x] **Quality pass:** 81 tests; ruff + mypy clean. Engine logic 85–100% covered (CLI/bulk
      downloader are thin glue, exercised via real runs). Perf on the full 38k-card DB: card lookup
      ~2 ms, parse+resolve a 100-card deck ~35 ms, analyze ~1 ms.

### Phase 9 — Heuristic battle/matchup simulator  `[~]` ← **REPLANNED 2026-06-23: see [docs/simulator-v2-roadmap.md](docs/simulator-v2-roadmap.md) (Stages 0–3 done → LOTR dist 16→4. S0+1 shipped to production; S2 search + S3 grounded coordination prototyped in `battle_search.py` — both measured as no-ranking-gain → kept opt-in, production unchanged; S3 audit confirms politics is appropriately secondary. The "A+B+F shipped, only 9C remains" framing below is historical)**

> **⚠ Active plan = [docs/simulator-v2-roadmap.md](docs/simulator-v2-roadmap.md).** Validation found the
> shipped model ranks decks ~inverted (speed-monocausal; clock = commander-deploy turn, not win turn).
> The research-grounded replan stages the fix: **0 ✅ SHIPPED** — decoupled deploy-clock from win-clock
> via `BattleProfile.combo_clock` (incidental combos gate the combo-win on actual assembly turn; aggro
> decks with a late combo win by beatdown, not instant combo), recorded the LOTR ordinal anchor +
> `test_anchor_lotr_ordinal_ranking` (rank-distance 16 → 10) → **1** multi-factor equity
> (resilience/interaction-availability/intransitive matchups) → **2** abstract forward model +
> determinization/IS-MCTS search → **3** CICERO-style opponent-model politics, weighted secondary. The
> A–H tracker and Phase A/B/C notes below are retained for history and mapped to stages in the roadmap.
Pod-aware **1v1 + 4-player** match simulator that abstracts each deck to a `BattleProfile` (clock,
interaction, card advantage, resilience, combo, threat) derived from existing `analyze()`/`simulate()`
signals, then runs a heuristic turn loop with interaction trades and (4-player) politics/threat
assessment. **Explicitly not a rules engine** (plan §2 / golden rule #5) — outputs are *relative* win
rates with **sensitivity bands**, never card-accurate. Full design, module layout, calibration plan,
and phasing: **[docs/battle-simulator-design.md](docs/battle-simulator-design.md)**.
- [x] Phase A — `BattleProfile` mapper (`simulation/battle.py`), match loop (1v1 + basic pod),
      tunable `battle_params.py`, `models/battle.py`, CLI `mtg battle <decks…> [--games --sim-games
      --seed --no-combos]`, sensitivity bands. 6 invariant tests (`test_battle.py`): determinism,
      faster-clock-wins-more, interaction-helps-vs-combo, pod-blunts-fast-combo, rates sum to 1.
- [x] Phase B — pod politics via a **decentralized assessment + voting engine**: each turn every
      player privately scores opponents (power level + proximity-to-kill + who's been damaging them +
      a small individual read) and votes its #1 threat; the most-voted deck is the **consensus
      archenemy**, and *its voters* are the ones who commit answers (coordinated, capped). Votes split
      by perspective, so the table doesn't always agree (verified: a 4× mirror rotates the archenemy
      37/24/22/18). Archenemy metric = avg share of turns a deck held the role; died-first tracked too.
- [~] Phase C — **resolution fixed**: interaction is now a *finite* reserve (low refill), so pods
      resolve mid-game — inevitability fallback dropped from ~50% to **0%**, avg game ~T16 → ~T6.
      **Calibration sweep** shipped (`calibrate_match` + `mtg battle --calibrate`). **Politics retuned**
      (user direction: politicking + pre-game power awareness, not random): the table *coordinates*
      against the pre-identified archenemy (up to `ARCHENEMY_ANSWERERS` pitch in) while trailing
      attackers face one answerer; flat tutor bonus gated by readiness (no turn-1 combo). Result is
      now intuitive — a fast deck wins ~60% heads-up but ~19% as the 4-pod archenemy.
      *(Superseded by workstream F: the flat `POLITICS_ARCHENEMY/NONARCH_ANSWER` multipliers described
      here were replaced by F2's equity-gated, free-rider-discounted answer check — see below.)*
- [x] Phase C — **explainability** (`clock_rank` vs. `equity_rank` gap + per-deck attribution):
      `DeckWinStats` now carries `clock_mean`/`clock_rank`/`equity_rank`/`rank_shift` and a one-line
      `explain` (clock→equity, politics pressure, dominant win method); the rank gap surfaces how much
      interaction + politics reshaped raw goldfish speed (design §5). CLI prints a "Why" section +
      a headline clock-vs-equity note. *Real pod: Henzie (fastest clock) finishes #3 — drew the table
      (archenemy 62%); slow Sauron punches to #1.* 2 tests (rank-shift conservation + politics
      attribution); 99 total, ruff+mypy clean.
- [x] Phase C — **validation harness (anchor fixtures)** + a seat-bias fix the harness caught.
      4 canonical matchups now pin behavior *magnitudes* with tolerance bands (not just A>B
      relations): speed dominates 1v1 (~0.99), a pod blunts a fast deck (~0.83 heads-up → ~0.29 pod,
      archenemy ~0.60), a 4-mirror is symmetric (~0.25 each), grind out-values aggro (~0.88). Writing
      the mirror anchor exposed a **seat-order bias** (deterministic seat-index tiebreaks → last seat
      won ~0.38 vs first ~0.15); fixed by resolving target-selection and archenemy-consensus ties
      uniformly via the seeded RNG (`_argmax(…, rng)` + an rng key on the alpha-strike target). Mirror
      now ~0.25/seat; real non-identical pods unchanged (Sauron 39 / Tom 37 / Henzie 20 / Galadriel 4).
      103 tests, ruff+mypy clean. *(Update: workstream F3 converted the `pod_blunts_a_fast_deck` anchor
      to ordinal — the F-model archenemy now finishes ~0.15 < 1/N, the design target, per the
      enhancement plan's E2 guidance; the other three anchors still hold as magnitudes.)*
- [~] Phase C — **real-game fitting** (the last 9C item; planned + decisions locked, see
      **[docs/battle-calibration-fitting.md](docs/battle-calibration-fitting.md)**). Locked: **Standard**
      logging (pod + winner + died-first + end-turn) and an **anchor-protected nudge** fit (regularize
      toward current defaults; reject any fit that breaks the 4 anchors; reversible `data/`-local
      override). Three sub-steps:
      - [x] **9C-1 logging infra** — `models/match_log.py` (`LoggedGame`, validated) +
            `data/match_log.py` (append-only JSONL, surfaces malformed rows) + CLI `mtg matchlog
            form|add|list` (named `matchlog`, not `battle log`, to avoid colliding with `battle`'s
            positional deck list). **`matchlog form`** is the friendly path — an interactive
            fill-out form (pick the pod from a numbered list, prompt field-by-field, re-ask on bad
            input, confirm before save); `add` is the scriptable equivalent (both share
            `_record_game`). Stores the **full** `BattleProfile` per deck as-played (drift insurance,
            upgraded from a hash at no user cost); optional `--win-method`/`--archenemy` ride along.
            `matchlog list` shows raw observed win rates + corpus progress. 8 tests (validation +
            JSONL round-trip + malformed-line surfacing + form parsing/flow); 111 total, ruff+mypy clean.
      - [ ] **9C-2 fit engine** (`mtg battle fit`): NLL of observed winners under simulated
            win-probabilities, ~3–4 fittable knobs (`INTERACTION_ANSWER_BASE`, `ANSWER_COORDINATION`
            — the F2 successor to the removed `POLITICS_ARCHENEMY_ANSWER` — `THREAT_PROXIMITY_W`),
            scipy Nelder-Mead, regularized. *Blocked on a corpus — ~30–45 games for a directional fit,
            ~60–80 for confidence.*
      - [ ] **9C-3 apply + guardrail** (the anchor fixtures as a hard gate — including the now-ordinal
            `pod_blunts_a_fast_deck` relations; write fitted params to a reversible `data/`-local
            override, never the source defaults).

#### Simulator realism & calibration — research workstreams (A–H)
*From the 2026-06-20 four-track literature review. **This is the authoritative status tracker.** The
research rationale (the stochastic-structure thesis, V&V/POM reasoning) and academic references live in
**[docs/simulator-research.md](docs/simulator-research.md)** (Part I) — a reference doc only, no
status.* **Naming note:** these letters are the *research workstreams* and are **distinct** from the
"Phase A/B/C" build phases above (e.g. workstream C = metagame layer, not the Phase C calibration work).
> **⚠ SUPERSEDED (2026-06-23) by [docs/simulator-v2-roadmap.md](docs/simulator-v2-roadmap.md).** A deep
> external-literature review ([docs/simulator-research.md](docs/simulator-research.md) Part II)
> + a 15-pod LOTR validation (roadmap Appendix A)
> re-prioritized this work into a staged roadmap (Stage 0 correctness → Stage 1 richer heuristic equity
> → Stage 2 determinization+IS-MCTS search → Stage 3 opponent-model politics; POM-ordinal validation
> primary). The A–H letters below are preserved and **mapped to the new stages in the roadmap §6**; the
> old priority order (`D → A → E → F → C → B → G/H`) is retired. **Two corrections the validation forced:**
> (a) **A4 was NOT actually shipped** — the `creatures ≥ 27 → aggro` classifier is still live and the
> clock still uses commander-*deploy* turn, which produces a ~inverted deck ranking (rank-distance
> 16/18); finishing it is **Stage 0.1**. (b) Real-game corpus fitting (H/9C-2) is **downgraded to
> opportunistic** — the literature does not support it; ordinal POM anchors are the workhorse.

| WS | Title | Status |
|----|-------|--------|
| **A** | Stochastic grounding (per-game resampling; hypergeometric interaction) | ◐ **partial** — A1 (realized per-game clock) shipped; **A4 NOT shipped** (creature-count classifier still mislabels Frodo/Sméagol → Stage 0.1); **A2** (hypergeometric answer-availability → Stage 1.2) and **A3** (decision-noise; → Stage 2.2 determinization) open |
| **B** | Intransitive matchups — RPS via a strength + interaction term | ☐ not started |
| **C** | Metagame layer — `mtg meta` → matchup matrix → Nash-averaging + replicator dynamics | ☐ not started (no `simulation/meta.py`) |
| **D** | Honest uncertainty — priors + global SA + joint band | ✅ **shipped** — D1 `PRIORS`, D2 `sensitivity.py` (LHS + correlation screening; Morris/Sobol' the documented next step), D3 `mtg battle --sensitivity` joint band |
| **E** | POM validation harness | ◐ **partial** — E1/E2 substantially shipped (independent ordinal stylized-fact tests + ordinal anchors); **E3** docking (an independent closed-form estimator) and a formal **held-out** anchor subset still open |
| **F** | Commander-politics realism | ✅ **shipped F1–F5** (detail below) |
| **G** | Robustness probes — exploiter decks; spinning-top coverage | ☐ later (needs a broader deck pool) |
| **H** | Real-data calibration — Bradley-Terry/Elo + Bayesian prior update | ◐ **= Phase 9C real-game fitting** above — 9C-1 logging shipped; 9C-2 fit + 9C-3 apply blocked on a logged corpus |

- [x] **Workstream F — commander-politics realism** (re-base threat/answer/gang-up on how real EDH
      pods play; spec **[docs/commander-politics-model.md](docs/commander-politics-model.md)**, validated
      against §3 ordinal stylized-facts, not magnitude anchors). Supersedes the older §F sketch in the
      enhancement plan. **Complete F1–F5.**
      - [x] **F1 — perception split + reputation/lightning-rod bias.** Targeting keys off
            `perceived_threat = live_threat × archetype-visibility + reputation` (not true equity).
            `BattleProfile.visibility` (combo 0.70 / grind 0.82 / else 1.0); a lightning-rod
            `reputation` accumulator bumps the consensus archenemy each turn and decays (×0.80),
            keeping the table on it semi-independent of board state. Reproduces **archenemy < 1/N**
            (visible fast combo 0.19 in a fair pod), the **quiet-shark** mechanism (identical decks:
            visibility-0.7 deck wins 0.62 vs ~0.13), and a **coordination knob** (archenemy win falls
            as answer-base rises). New knobs added to `PRIORS` for global SA. 2 ordinal POM tests;
            120 total, ruff+mypy clean.
      - [x] **F2 — equity-gated, free-rider-discounted answering.** Replaced the flat
            `POLITICS_ARCHENEMY/NONARCH` multipliers with a sequential, most-invested-first answer
            check: willingness = `answer_prob` × peer-relative own-equity gate × lethal gate
            (combo/archenemy > beatdown) × a flat `ANSWER_COORDINATION` factor (the §3.6 / casual↔cEDH
            knob). The naive "P(someone else answers)" free-rider product was tried and rejected
            (unstable — universal deferral collapses coordination); the flat factor is the robust
            stand-in. Coordination knob verified monotone; archenemy holds ~0.16–0.20 < 1/N; attrition
            emerges from reserve depletion. Both pre-F deck anchors kept passing by setting the new
            beatdown lethal-gate to 0.65 (no anchor rewrite). New knobs in `PRIORS`. 1 POM test; 121
            total, ruff+mypy clean.
      - [x] **F3 — go-first penalty + standoffs; spoiler-on-leader.** Attempts are suppressed while
            opponents hold open answers (`GO_FIRST_CAUTION` × table open-reserve) so decks wait out a
            standoff that F2 attrition breaks; an out-of-contention seat (trailing share, late game)
            answers the leader at boosted willingness (`SPOILER_ANSWER_BONUS`), overriding its equity
            gate. Verified: more caution ⇒ longer games; spoiler ⇒ leader win drops. The
            `pod_blunts_a_fast_deck` anchor was converted to ordinal here (research-led, per E2). 2 POM
            tests; 123 total, ruff+mypy clean.
      - [x] **F4 — protection cancels answers ~1:1; full archetype-visibility table.**
            `BattleProfile.protection` scanned from oracle text in the battle module (free counters /
            hexproof / ward / can't-be-countered / indestructible grantors — no analysis-pipeline
            change). Each landed answer is spent (attrition) but fizzles with probability
            `PROT_CANCEL_PER_PIECE × protection` (capped) — probabilistic per attempt, since a flat 1:1
            count made one piece protect forever (0.68!). Verified monotone (0.15→0.26→0.62→0.88 as
            protection rises). Visibility table completed: combo<grind<control<midrange<aggro. 3 POM
            tests; 26 battle tests, ruff+mypy clean.
      - [x] **F5 — power presets + POM stylized-fact suite.** `POWER_PRESETS` (casual | mid | cedh)
            bundle table coordination (§3.6), perception sharpness, and go-first discipline; applied
            via `simulate_match(preset=…)` + CLI `--preset`. Added `GO_FIRST_IMPATIENCE` so caution
            decays past a deck's clock (fixes a go-first deadlock that pegged slow pods at the turn
            cap). Pacing emerges from decks (cEDH pod ~5–6, casual ~14; ordinal cEDH < casual). All 7
            §3 stylized-facts codified as ordinal POM tests. 4 POM tests; 130 total, ruff+mypy clean.

## 5. Recommendation engine design (reference)

Four-stage funnel (full detail in the **`mtg-data-ecosystem`** skill):
1. **Candidate generation** — union of: EDHREC top/high-synergy cards for the commander;
   co-occurrence/CF neighbors from a decklist corpus; Scryfall theme/`otag` queries per category gap.
2. **Score** — weighted blend of EDHREC **lift** (primary "fit"), CF similarity, category-gap
   demand, curve-smoothing, theme match, owned-bonus, minus price penalty. α-blend fit↔theme for
   cold-start commanders.
3. **Hard filters** — color-identity legal, not banned, singleton, ≤ budget (unless owned).
4. **Rank + diversify** — category quotas / MMR so output fills gaps (not 15 mana rocks). Attach
   human-readable explanations ("+72% synergy, fills ramp gap 6/10, owned, $0").

## 6. Risks & open questions

- **Decklist corpus for CF** — EDHREC gives aggregate stats but not raw decklists for co-occurrence.
  Options: rely on EDHREC lift/synergy alone initially; optionally build a small local corpus from
  Archidekt search (tolerated, throttled) later. *Decision deferred to Phase 3/5.*
- **EDHREC/Archidekt are unofficial endpoints** — could change or lock down (Moxfield already did).
  Mitigation: cache nightly, isolate behind an adapter interface, degrade gracefully to
  Scryfall-only analysis.
- **Commander Spellbook bulk** — single-file dump was removed; page `/variants/` or self-host MIT
  backend. *Decide in Phase 4.*
- **Comprehensive Rules ingestion format** — parse the official PDF/txt into searchable sections;
  scope the granularity in Phase 4.
- **Frontend depth** — start minimal (import → report → charts); avoid over-building before the
  engine is proven.

## 7. Future / post-MVP

- **Publishing** — multi-user hosting, auth, accounts, persisted collections. Engine already
  separated from UI; FastAPI → containerize; React app → static host. Re-review Scryfall/EDHREC ToS
  for any non-local/commercial use.
- **Full rules-enforced simulation** — integrate **XMage** (MIT, Java) as a play engine if true
  game AI is ever needed, rather than building a rules engine.
- **Self-hosted Commander Spellbook backend** (MIT, Docker) — if a complete *offline* combo mirror
  is ever wanted, run their backend locally instead of scraping the public API's 900+ variant pages
  (which trips rate limits). Until then, live find-my-combos + per-card search + cache suffices.
- **Price tracking over time**, alternate formats (Brawl, Oathbreaker), playtest/draft modes.
- **Heuristic battle/matchup simulator (1v1 + 4-player)** — pod-aware multiplayer *dynamics* model
  (clock/interaction/card-advantage/politics), NOT a rules engine. Scoped in
  [docs/battle-simulator-design.md](docs/battle-simulator-design.md); tracked as **Phase 9** below.

## 8. Status log

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
- **2026-06-23** — **Validation + replan + Stage 0 shipped.** A full 15-pod LOTR sweep showed the battle
  sim ranks decks **~inverted** vs. experienced play (rank-distance 16/18) — root cause: the "clock"
  measured *commander-deploy* turn, not *win* turn, and an aggro deck merely *containing* a combo scored
  **instant turn-3 combo kills**. A deep external-literature review
  ([docs/simulator-research.md](docs/simulator-research.md) Part II) + the validation (roadmap
  Appendix A) drove a research-grounded
  **replan** ([docs/simulator-v2-roadmap.md](docs/simulator-v2-roadmap.md)): Stage 0 correctness → Stage 1
  multi-factor equity → Stage 2 determinization+IS-MCTS search → Stage 3 opponent-model politics (POM-
  ordinal validation primary; corpus-NLL fitting downgraded). **Stage 0 shipped:** `BattleProfile.combo_clock`
  decouples the win-clock from the deploy/attempt clock — an incidental combo only wins once *assembled*
  (`turn ≥ combo_clock − COMBO_ONLINE_SLACK`); aggro decks with a late combo now win by **beatdown** at
  their combat clock, and the combo blend was narrowed to combo-*primary* decks. Backward-compatible
  (synthetic/combo-primary profiles fall back to `clock_mean`). Added `test_anchor_lotr_ordinal_ranking`
  (the first POM ordinal ground-truth gate). **LOTR rank-distance 16 → 10** (Frodo & Sam 74% → 31%;
  resilient Tom/Galadriel rose to the top). 131 tests, ruff+mypy clean. *Open (Stage 1):* Sauron still
  under-ranked + Sméagol low — the speed-monocausal weighting the next stage fixes. Also corrected a
  stale **A4-shipped** marker in the A–H tracker (it was never actually shipped — it was this bug).
- **2026-06-23** — **Stage 1 shipped (richer equity — the speed-monocausal fix).** A param sweep first
  proved that re-weighting existing levers was inert (Sauron 10%→15%, rank-distance stuck at 10): games
  end ~T9 and the inevitability tiebreak only fired at turn 24, so a slow interaction-dense deck had **no
  win path**. Added a **mid-game attrition/grind win path** (`battle.py` `grind_equity` + the per-turn
  attrition draw; `battle_params` `ATTRITION_*`/`GRIND_*`): once past `ATTRITION_MIN_TURN` a game can
  resolve by grind, winner drawn weighted by grind-equity^GRIND_POWER (interaction-heaviest + card
  advantage + resilience/protection + combo redundancy). Two refinements make it precise: a **heat
  discount** (grind-equity ÷ accrued archenemy reputation, so the perennial lightning rod can't also win
  the grind — this swaps quiet Sauron above focused Frodo) and a **margin gate** (firing ∝ how far the
  leader out-grinds the field MEAN through a sharp logistic — ≈0 when resource-even, protecting the
  speed/mirror anchors; hard in a lopsided pod). **LOTR rank-distance 10 → 4** (Sauron last → 2nd, Frodo
  1st → last; the original inversion is gone). Tightened `test_anchor_lotr_ordinal_ranking` (gate 12 → 8,
  + a Sauron > Frodo assertion); recalibrated `test_anchor_pod_blunts_a_fast_deck` (a lone control deck
  now grinds a glass-cannon combo to ~0.52 heads-up — the intended correction; the pod still crushes it
  to 0.06). Anchors hold: speed 0.905, grind 0.90, mirror symmetric. 131 tests, ruff+mypy clean. *Open:*
  Sauron #2 not #1 + a Gandalf/Galadriel mid-table swap — finer strategic texture for Stage 2 (search)
  / Stage 3 (opponent modeling). Stage 1 hitting the anchor makes **Stage 2 optional polish**, not a fix.
- **2026-06-23** — **Stage 2 prototyped (searched decisions); full build NOT committed — evidence-based.**
  Built the make-or-break **2.1 gate** in a new `simulation/battle_search.py` (separate from production
  `battle.py`): an explicit, **resumable, card-agnostic forward model** (`BattleState` + `step_turn` /
  `play_from(state, rng, decide)`) with a `decide` **policy seam** for the win-attempt commit. The
  heuristic policy faithfully ports Stage-1's mechanics and **reproduces production exactly** (LOTR dist 4,
  identical win rates) — proving the abstraction is expressive enough that search on it is trustworthy.
  Then prototyped the research's **determinization + cheap-rollout** (`make_search_decide`: roll the rest
  of the game out K times under COMMIT vs WAIT, pick the winner) on the go-first/hold-up decision.
  **Measured: search does NOT improve the ranking** (K=8 → dist stays 4); it shifts share toward
  optimal-timing combo decks (Tom 42→48%, Galadriel 28→40%, Sauron 34→29%) at ~4× compute — skillful-play
  texture, not ordinal accuracy. With Stage 1 already at the anchor, this **confirms the decision gate: do
  not commit the multi-week full UCB-tree IS-MCTS build for the ranking; Stage 3 (politics) is higher
  value.** Prototype kept as the validated foundation (5 tests incl. the 2.1 gate; ruff+mypy clean).
  136 tests total. Full IS-MCTS + visit-count ensembling remains the documented next increment if
  "skillful-timing realism" is ever the explicit goal.
- **2026-06-23** — **Stage 3 politics audited + prototyped; existing politics CONFIRMED, no production
  rebalance.** The research validates the workstream-F politics (CICERO-style voting/perception is
  literature-backed) and prescribes two checks, both done evidence-based. **Audit (3.2 / the 14×
  "tactics dominate" guardrail):** ablating each politics layer over the 15 LOTR pods shows the
  tactical/resource fundamentals alone already rank well (ALL-politics-off → dist 6) and politics merely
  *refines* to dist 4 → politics is **appropriately secondary, no down-weighting needed**; that
  refinement is almost entirely the **perception/lightning-rod** mechanism (remove → dist 8, Frodo
  rebounds 8→21%), while the coordination/equity-gate/spoiler knobs are **near-inert on the ranking**
  (flagged for a future simplification pass). **Grounded opponent-model (3.1):** prototyped a stable
  CICERO-lite bystander model in `battle_search.py` (opt-in `GROUNDED_COORDINATION`, default off) — each
  defender free-rides on the OTHER defenders' answering capacity (depends only on others → no collapse,
  fixing the instability the flat-knob comment documented); measured to **reproduce the ranking exactly
  (dist 4)** at calibrated strength, over-strong free-riding mildly degrades it (dist 6, archenemy slips)
  — a fidelity/principle improvement, not an outcome change, so kept opt-in. **Human-regularization
  (3.3)** already present via `PERCEPTION_NOISE` + `PRIORS`. 137 tests, ruff+mypy clean.
- **2026-06-23** — **Stage 3b/3c (user-driven): metagame-knowledge feedback loop SHIPPED — LOTR
  rank-distance 4 → 0.** Re-running the full 15-pod sweep, the user observed the win-rate spread was too
  wide and the archenemy was wrong: a never-wins aggro deck (Frodo) was the turn-1 archenemy 84% of the
  time while the quiet winner (Sauron) was never targeted (0%). **3b (negative result):** tried ganging up
  on the static resource leader (`THREAT_DOMINANCE_W`) — it *widens* the spread and scrambles the ranking,
  because grind-equity mis-predicts winners and a resource-dense deck survives being targeted (you can't
  politics away a real power gap). Kept opt-in/default-off as a documented dead-end. **3c (the fix, the
  user's idea):** feed each deck's REALIZED win rate back as a standing threat prior (`win_prior =
  win_rate − 1/pod_size`, added to `perceived_threat` past the quiet-shark discount) via a **damped
  fictitious-play loop** — `simulate_metagame` + CLI `mtg battle --metagame` (`WINRATE_PRIOR_W` /
  `METAGAME_PRIOR_WEIGHT`/`DAMP`/`ITERS`; `BattleProfile.win_prior`). Damping kills the undamped overshoot
  (target winner → it loses → oscillate). **Converges in ~5 passes to LOTR rank-distance 0 — a perfect
  match to the experienced-player ranking**: Sauron last → 1st (prior +0.10, now drawn as a threat),
  Frodo's archenemy share 84% → 68% (prior −0.13, left alone at game start while the dynamic terms still
  flag it if it takes off), real winners Tom/Gandalf draw the heat, spread 33pp → 27pp. Opt-in
  (standing `WINRATE_PRIOR_W` default 0 → one-off `mtg battle` unchanged); `simulate_metagame` restores
  all global state. 1 new test (`test_metagame_feedback_*`). 138 tests, ruff+mypy clean. **First politics
  mechanism that improves the model on every axis — ranking, archenemy realism, and spread.**
- **2026-06-23** — **Stage 3d (user-driven): INFORMED-TABLE assumption — the archenemy now tracks power.**
  The user pushed: a 37%-win deck (Sauron) being the archenemy only ~4% of the time is wrong; assume
  players understand power levels, which should drive the strongest deck near the top of the archenemy
  ranking. Diagnosis confirmed: Sauron wins by **attrition**, which is invisible to the threat read (its
  `live_threat` is the LOWEST at the table, 5.8 vs Frodo's 19.2), and forcing the prior weight high enough
  to target it (a) oscillates and (b) over-suppresses (Sauron → 14% win, archenemy 56%). Resolution: the
  fictitious-play loop LEARNS power levels at the stable weight, then `simulate_metagame(informed=True)`
  runs ONE reporting pass at the strong `METAGAME_INFORMED_WEIGHT` (100) so the table targets by known
  power. Quantified the regime: casual → archenemy backwards; **informed → archenemy tracks power (Sauron
  near top, Frodo→5%), win rates compress toward parity.** Baked the reframe into the API/CLI output —
  **power = the ranking + archenemy column; win rate = the policed outcome** (the correctly-policed leader
  wins less; 2nd/3rd under-the-radar decks inherit, the empirical 11%-archenemy pattern). `MetagameResult`
  now reports `power_rank`/`power_level`/`archenemy_rate`/`win_rate`; CLI prints `# deck power archenemy%
  win%`. The cranked weight is applied only in the reporting pass (convergence stays stable). Metagame
  test updated to the power-ranking semantics. 138 tests, ruff+mypy clean.

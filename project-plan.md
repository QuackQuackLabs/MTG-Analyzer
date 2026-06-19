# MTG Analyzer — Project Plan

> **Living document.** Every agent reads this before starting and updates status/checkboxes when
> finishing a unit of work. Last updated: **2026-06-18**.
>
> **Status: Phases 0–8 complete** — feature-complete for local, chat-driven use (analyze, recommend,
> simulate, build-from-collection, combo/interaction Q&A, **collection management + strategy
> guides**; 86 tests, ruff+mypy clean). Only the deferred web app (publishing, §7) remains. Primary
> interface is chat via Claude Code.

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
- [ ] turn-to-combo metric; sim charts (deferred with the web UI).

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
- *Validated on real data: 1,043 distinct cards imported (0 unresolved); Sol Ring tracked across
  Available + 3 decks; Henzie guide lists all 3 combos with steps.* 86 tests; ruff/mypy clean.

### Phase 7 — Polish & quality  `[x]`
- [x] **Saved deck library** (`data/deck_library.py`): `mtg deck save|list|remove|diff`; all deck
      commands accept a saved name *or* a file path (`load_deck_text`). Decks stored as text under
      `data/decks/` (gitignored). `deck diff` shows added/removed cards between two decks. *(Auto
      version-history snapshots deferred — diff covers the practical need.)*
- [x] **EDHREC caching** (`EdhrecCache`): 24h TTL in `app.db`; `recommend`/`build` reuse cached
      commander data (cold 1.14s → warm 0.67s, no network). Scryfall bulk refreshes via the manifest.
      *A scheduled nightly cron is an ops concern (run `mtg data refresh` + `mtg rules refresh`).*
- [x] **Error/offline handling:** all network calls (Commander Spellbook, EDHREC) route through
      `_run_network` — on failure they print a clear "unavailable (offline or rate-limited); skipped"
      note and degrade gracefully; unresolved cards are reported, never silently dropped.
- [x] **Quality pass:** 81 tests; ruff + mypy clean. Engine logic 85–100% covered (CLI/bulk
      downloader are thin glue, exercised via real runs). Perf on the full 38k-card DB: card lookup
      ~2 ms, parse+resolve a 100-card deck ~35 ms, analyze ~1 ms.

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
- **Price tracking over time**, alternate formats (Brawl, Oathbreaker), playtest/draft modes,
  pod-aware multiplayer simulation.

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

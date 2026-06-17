# MTG Analyzer — Project Plan

> **Living document.** Every agent reads this before starting and updates status/checkboxes when
> finishing a unit of work. Last updated: **2026-06-17** (project kickoff).

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
| Interface | **Local web app** — FastAPI backend + **React/Vite/TS** SPA frontend | User-chosen. Natural for uploads, card images, charts, deck diffs; cleanest path to future publishing. |
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
      [[Category]]` + section headers + `//`/`#` comments. Covers Archidekt (category tags, commander
      via `[Commander]`), Moxfield/Arena/MTGO. Card-name parens preserved (set group is space-free).
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

### Phase 3 — Deck analysis & validation  `[ ]` ← **first user-facing milestone**
- [ ] **Legality validation:** 100 cards, singleton (basics exempt), commander is legal commander,
      every card's `color_identity ⊆ commander identity`, banned-list check, Game-Changer count
      (for bracket). Companion edge case flagged.
- [ ] **Category analysis:** classify each card (lands / ramp / card draw / spot removal / board
      wipe / tutor / protection / payoff / win-con) via Scryfall function tags (`otag:`) → oracle
      regex → type-line fallback. Compare to composition template (~36–38 land, ~10 ramp, ~10 draw,
      ~10 removal, ~3 wipes) → gap report.
- [ ] **Curve analysis:** CMC histogram; flag too-high curve vs ramp count.
- [ ] **Bracket estimate** (1–5) from Game-Changer count + combo presence + tutor/fast-mana density.
- [ ] **Recommendations (static, no sim):** rank candidate cards (see §5) to fill the biggest gaps;
      attach explanation strings; respect color identity, singleton, banlist, budget.
- [ ] **Budget shopping list:** owned (from inventory) vs to-buy, with Scryfall `prices.usd`
      (min across reprints) and functional cheaper-substitute suggestions.
- [ ] API routes + frontend views: import deck → validation report → category/curve charts →
      ranked recommendations → shopping list. Card images from Scryfall (cache locally).

### Phase 4 — Combo & interaction detection  `[~]`
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
- [ ] Surface combos/missing-pieces in the deck-analysis UI; suggest color-identity-legal combos to *add*
      (the live "almost included" bucket already provides one-card-away suggestions).
- [ ] Interaction/ruling Q&A: combine Scryfall rulings (Phase 1) + comprehensive-rules sections +
      combo data into a single "what happens / what governs this?" lookup.

### Phase 5 — Game simulation & analytics  `[ ]`
- [ ] Hypergeometric module (scipy): P(≥k lands in opening 7), P(see card/combo by turn N),
      P(≥1 of K ramp pieces), Karsten-style color-source checks. Model 99-card library.
- [ ] Monte-Carlo goldfish engine (numpy, seeded RNG over integer card IDs): London mulligan keep
      policy, turn loop with simple land/ramp/cast heuristics. Separate engine from policy.
- [ ] Metrics: keep%, avg/percentile turn-to-cast-commander, turn-to-assemble-combo, "dead hand" %,
      mana-screw/flood rates. Report distributions, not just means.
- [ ] Feed sim output back into the recommender (consistency-driven suggestions).
- [ ] Frontend: run-sim view with charts + before/after comparison for proposed swaps.

### Phase 6 — Deck construction from inventory  `[ ]`
- [ ] Given a commander (or "suggest commanders from my inventory"), build a legal 99 using owned
      cards first, filling category/curve targets via the recommender.
- [ ] Output: decklist + shopping list for gaps the inventory can't fill (budget cap aware).
- [ ] Optionally seed from EDHREC average deck for the commander, intersected with inventory.

### Phase 7 — Polish & quality  `[ ]`
- [ ] Save/load decks & analyses locally; deck version history / diffs.
- [ ] Caching layer + nightly refresh job for Scryfall bulk + EDHREC snapshots.
- [ ] Error states for unresolved cards, offline mode, rate-limit handling surfaced in UI.
- [ ] Test coverage pass; type-check clean; basic perf check on full card DB.

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
  Next: **Phase 3 — deck analysis & validation** (first user-facing milestone).

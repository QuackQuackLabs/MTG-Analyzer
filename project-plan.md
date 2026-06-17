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
| Language / engine | **Python 3.12+** | Best fit for the data/analytics/simulation core; scipy/numpy; the data ecosystem (pyedhrec etc.) is Python. |
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

### Phase 0 — Foundation  `[~]`
- [x] Research (Scryfall API, Commander rules + simulation feasibility, data ecosystem).
- [x] Repo init, directory skeleton, `pyproject.toml`, `.gitignore`, `CLAUDE.md`, this plan.
- [x] Domain skills authored (`scryfall-api`, `commander-format`, `mtg-data-ecosystem`).
- [ ] Python venv + `pip install -e ".[dev]"`; confirm `pytest`/`ruff`/`mypy` run clean on empty repo.
- [ ] FastAPI "hello" app + health route; Vite/React app scaffold that calls it. Wire CORS for local dev.
- [ ] Initial git commit (only when the user asks).

### Phase 1 — Card data layer  `[ ]`
- [ ] `data/`: `/bulk-data` poller → download **Oracle Cards** + **Rulings** (gzip), store metadata,
      refresh only when `updated_at` changes.
- [ ] Ingest bulk JSON into SQLite; schema keyed on `oracle_id` (+ a printings table keyed on `id`
      for price/set/image). Index name, color_identity, type_line, legalities.commander, cmc.
- [ ] `models/Card` (Pydantic) with DFC/`card_faces` handling driven off `layout`.
- [ ] Scryfall live client (httpx, custom UA/Accept, ~100 ms throttle, 429 backoff): `/cards/named`
      (fuzzy/exact), `/cards/autocomplete`, `/cards/search`, `POST /cards/collection` (≤75/batch).
- [ ] Rulings lookup (from bulk file, join on `oracle_id`).
- [ ] Tests: ingest a small fixture, identity resolution, DFC parsing.

### Phase 2 — Ingest: decks & inventory  `[ ]`
- [ ] Tolerant decklist parser: `[SB:] N[x] Name [(SET) Number]`, header/blank-line/`//` handling →
      covers Arena/Moxfield/Archidekt/MWS text. Designate commander(s).
- [ ] Inventory CSV parser — target **ManaBox** first (has set+collector# *and* Scryfall ID), then
      Deckbox / Moxfield / Archidekt collection CSVs (parse by header name, not position).
- [ ] Resolve every line to Scryfall identity; report unresolved/ambiguous lines.
- [ ] Tests with sample deck files + a ManaBox CSV fixture.

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

### Phase 4 — Combo & interaction detection  `[ ]`
- [ ] Commander Spellbook client: `/find-my-combos` (present + "almost there" by one card) and a
      cached `/variants/` mirror (page `?limit=1000`); consider self-hosting the MIT backend later.
- [ ] Surface combos in a deck, missing pieces, and color-identity-legal combos to *add*.
- [ ] Interaction/ruling Q&A: given a card or scenario, pull Scryfall rulings + relevant
      comprehensive-rules sections.

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
- **Price tracking over time**, alternate formats (Brawl, Oathbreaker), playtest/draft modes,
  pod-aware multiplayer simulation.

## 8. Status log

- **2026-06-17** — Project kickoff. Research completed (3 briefs). Decisions in §2 confirmed with
  user. Foundation scaffolding + skills + docs created. Next: Phase 0 env setup + FastAPI/Vite
  hello-world, then Phase 1 card data layer.

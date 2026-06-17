# CLAUDE.md

Guidance for Claude Code (and any agent) working in this repository.

## What this is

**MTG Analyzer** — a *local, single-user* tool for Magic: The Gathering **Commander (EDH)** deck
analysis. It ingests a card inventory and decklists, validates and scores decks, detects combos,
runs statistical game simulations, and produces upgrade recommendations and budget-aware shopping
lists. It can also build new decks from the user's inventory plus a buy list.

The authoritative, living description of scope, architecture, and progress is
**[project-plan.md](project-plan.md)** — read it before starting work and keep it updated.

## Golden rules

1. **Read [project-plan.md](project-plan.md) first.** It is the single source of truth for phases,
   decisions, and status. When you finish a unit of work, update the relevant checkbox / status note
   in that file in the same change.
2. **Key everything to Scryfall `oracle_id`.** Card identity across reprints, EDHREC stats, combo
   variants, decklists, and inventory all join on `oracle_id`. Never key analysis on a specific
   printing's `id` unless you specifically need printing-level data (price, set, image).
3. **Use the skills.** Domain knowledge is captured in `.claude/skills/` — invoke the relevant skill
   instead of re-researching or guessing API/rules details:
   - **`scryfall-api`** — Scryfall endpoints, headers, rate limits, bulk data, search syntax. Read
     before writing any code that touches Scryfall.
   - **`commander-format`** — Commander rules, deck legality, color identity, the bracket system,
     deck-composition heuristics. Read before writing validation/analysis/recommendation logic.
   - **`mtg-data-ecosystem`** — EDHREC, Commander Spellbook, deck/inventory file formats, and the
     recommendation algorithm design. Read before integrating external data or building the
     recommender.
4. **Respect external APIs.** Send a descriptive `User-Agent`
   (`MTGAnalyzer/0.1 (jacob@quackquacklabs.com)`) and an `Accept` header on every Scryfall request;
   throttle to ~10 req/s (≥100 ms gap); back off on HTTP 429. Prefer **bulk data + local DB** over
   live per-card calls. EDHREC / Archidekt / Commander Spellbook have *no* official rate limits —
   cache aggressively (refresh nightly, not per query) and never redistribute their bulk data.
5. **Do not build a full MTG rules engine.** MTG is Turing-complete; a faithful engine is a
   multi-year effort. "Simulation" here means **statistical/heuristic goldfishing** (hypergeometric
   math + Monte-Carlo draw/sequence sims). Full rules-enforced play, if ever needed, is a future item
   that should reuse XMage (MIT) — see the plan.

## Architecture (target)

```
backend/mtg_analyzer/        Pure-Python engine (the value lives here; UI is swappable)
  data/         Scryfall bulk ingest, refresh, local SQLite card DB
  models/       Pydantic domain models: Card, Deck, Inventory, Ruling
  ingest/       Decklist + inventory file parsers (Arena/Moxfield/Archidekt txt, ManaBox CSV)
  rules/        Commander legality, comprehensive-rules store, card rulings lookup
  analysis/     Category/curve analysis, deck scoring
  combos/        Commander Spellbook integration (combo / "almost there" detection)
  simulation/   Hypergeometric (scipy) + Monte-Carlo (numpy) goldfish simulator
  recommend/    Recommender + budget shopping-list / deck-construction engine
  api/          FastAPI app — thin layer over the engine
frontend/                    React + Vite + TypeScript SPA (later phase)
data/                        Local card DB, bulk cache, rules text (gitignored, regenerable)
tests/                       pytest
.claude/skills/              Project domain skills (see Golden rule 3)
```

**Stack:** Python 3.11+, FastAPI + uvicorn, SQLite, numpy/scipy, httpx, pydantic. Frontend is
React/Vite/TS. Keep the engine importable and testable independent of FastAPI — the API is a thin
adapter, so the interface stays swappable and publishable later.

## Conventions

- Source lives under `backend/` (see `pyproject.toml` → `tool.hatch` / `pytest pythonpath`).
- Install dev env: `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.
- Run API (once it exists): `uvicorn mtg_analyzer.api.app:app --reload`.
- Test / lint: `pytest`, `ruff check`, `mypy backend`.
- Type-hint everything; use Pydantic models for domain objects and API schemas.
- Card/rules data in `data/` is **regenerable** — never commit it; re-ingest from Scryfall bulk.

## Legal / data use

Card data and images come from Scryfall under WotC's Fan Content Policy — not CC0. This is a
non-commercial local tool, which is squarely allowed. Do **not** paywall/gate Scryfall data, crop
artist/copyright lines off images, or imply endorsement. Treat the Commander banned list and "Game
Changers" list as external, versioned data fetched at runtime — never hard-code them.

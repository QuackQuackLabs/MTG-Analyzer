# Contributing to MTG Analyzer

Thanks for improving MTG Analyzer! This is a local, single-user Commander tool driven through
[Claude Code](https://claude.com/claude-code). Most people just *use* it — but if you want to fix a
bug or add a feature and send it upstream, here's how.

## Read these first

1. **[project-plan.md](project-plan.md)** — the single source of truth for scope, architecture,
   phases, and current status. Read it before starting and update the relevant checkbox/status note
   in the same change.
2. **[CLAUDE.md](CLAUDE.md)** — the rules any agent (or human) must follow in this repo.
3. **`.claude/skills/`** — captured domain knowledge: `scryfall-api`, `commander-format`,
   `mtg-data-ecosystem`. Read the relevant one instead of re-researching API/rules details.

## Golden rules (from CLAUDE.md)

- **Key everything to Scryfall `oracle_id`.** Card identity joins on `oracle_id`, never a printing's
  `id` (unless you specifically need price/set/image).
- **Use the skills** rather than guessing at API or rules behavior.
- **Respect external APIs.** Descriptive `User-Agent` + `Accept` on every Scryfall request, throttle
  to ~10 req/s, back off on HTTP 429. Prefer bulk data + the local DB over live per-card calls.
- **Do not build a full MTG rules engine.** "Simulation" here is statistical/heuristic goldfishing,
  not rules-enforced play.

## Dev setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

Card data lives in `data/` and is regenerable — never commit it (`mtg data refresh` rebuilds it).

## Before you open a PR

Everything must be green:

```bash
pytest          # all tests pass
ruff check      # lint clean
mypy backend    # type-check clean
```

- Type-hint everything; use Pydantic models for domain objects.
- Add or update tests for any behavior change (tests run with **no network** — use fixtures/mocks).
- Keep the engine importable and testable independent of FastAPI — the API is a thin adapter.

## Workflow

This repository is published as a **template**. To contribute changes back:

1. **Fork** this repo on GitHub (the fork is for contributing code; your personal copy made via
   "Use this template" is for running the tool).
2. Create a branch: `git checkout -b my-change`.
3. Make the change; keep `pytest` / `ruff` / `mypy` green; update `project-plan.md`.
4. Commit and push to your fork, then open a Pull Request against this repo's `main` branch.

## Legal

By contributing, you agree your code is licensed under the project's [MIT License](LICENSE). Do not
contribute card data, images, or any external bulk data — those stay under their sources' terms (see
the README's Legal section).

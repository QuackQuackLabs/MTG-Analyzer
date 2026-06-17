# MTG Analyzer

A local, single-user tool for **Magic: The Gathering Commander (EDH)** deck analysis. Import your
collection and decklists, validate and score decks, detect combos, run statistical game simulations,
and get upgrade recommendations + budget shopping lists — or have it build a deck from your inventory.

Runs entirely on your machine. No account, no hosting required.

> **Status:** Phase 0 (foundation). See **[project-plan.md](project-plan.md)** for the full roadmap
> and current progress.

## Stack

- **Backend / engine:** Python 3.12+, FastAPI, SQLite, numpy/scipy, httpx, pydantic
- **Frontend:** React + Vite + TypeScript (later phase)
- **Data:** [Scryfall](https://scryfall.com/docs/api) (cards/rulings, bulk), Commander Spellbook
  (combos), EDHREC (recommendation stats)

## Quick start (dev)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest            # run tests
ruff check        # lint
# API (once it exists):
uvicorn mtg_analyzer.api.app:app --reload
```

## For contributors / agents

Read **[CLAUDE.md](CLAUDE.md)** and **[project-plan.md](project-plan.md)** first. Domain knowledge
lives in `.claude/skills/` (`scryfall-api`, `commander-format`, `mtg-data-ecosystem`).

## Legal

Card data and images are used under Wizards of the Coast's Fan Content Policy via Scryfall. This is a
non-commercial, local tool. Not affiliated with or endorsed by Wizards of the Coast or Scryfall.

# MTG Analyzer

A **local, single-user tool for Magic: The Gathering Commander (EDH)** that you drive by *chatting
with [Claude Code](https://claude.com/claude-code)*. Import your collection and decklists, validate
and score decks, detect combos, run statistical game and matchup simulations, get rule-grounded
interaction answers, and get upgrade recommendations, budget shopping lists, or a whole deck built
from cards you own.

Everything runs on your own machine. **No account, no server, no hosting** — your collection and
decks never leave your computer.

> **How you use it:** you don't memorize commands. You open this folder in Claude Code and ask in
> plain English — *"analyze my Sauron deck and tell me what to upgrade under $30."* Claude runs the
> tool for you and explains the results. The `mtg` commands below exist if you'd rather drive it
> directly.

---

## What you can do

- **Validate & score a deck** — exactly-100, singleton, color identity, legal commander, banned /
  Game-Changer flags, category balance (lands/ramp/draw/removal/wipes), mana curve, and a 1–5
  bracket estimate.
- **Find combos** — what combos your deck already contains and which are one card away (via
  Commander Spellbook).
- **Simulate consistency** — goldfish thousands of games: keepable opening hands, mana screw/flood,
  and what turn your commander comes down.
- **Simulate matchups** — a heuristic 1v1 or 4-player pod "who wins" model with politics and
  sensitivity bands (relative win rates, *not* a rules engine). Across a **pool** of decks it learns a
  power-level ranking (tiers + who gets ganged up on) and a head-to-head matrix of which deck types you
  beat vs. should fear.
- **Ask rules & interaction questions** — grounded in the Comprehensive Rules, official card
  rulings, and combo data, so the answer cites real sources.
- **Get upgrade recommendations** — gap-filling adds + lowest-impact cuts, EDHREC-blended,
  budget-aware, and aware of what you already own.
- **Build a deck from your collection** — pick a commander; get a legal 100 from cards you own plus
  a shopping list for the gaps.
- **Manage a collection** — one inventory with per-deck locations, so the tool knows which cards are
  free to use and which are committed elsewhere.

## Prerequisites

- **macOS or Linux** (Windows via WSL should work too).
- **Python 3.11+** and **git**.
- **[Claude Code](https://claude.com/claude-code)** installed, with a Claude account/subscription —
  this is the primary way you'll interact with the tool.
- **~500 MB free disk** for the local card database (regenerable; never committed).

## 1. Get your own copy

This repo is a **GitHub template**. On the repository page, click **"Use this template" → "Create a
new repository"** to get your own independent copy, then clone it:

```bash
git clone https://github.com/<your-username>/MTG-Analyzer.git
cd MTG-Analyzer
```

Your copy is yours: the decks and collection you load stay local and are gitignored, so you can keep
your repo private or public without exposing your card data.

## 2. One-time setup

```bash
python -m venv .venv && . .venv/bin/activate   # create + activate a virtual environment
pip install -e ".[dev]"                        # install the engine + the `mtg` command
```

Then load the data the tool reasons over (one time; refresh occasionally):

```bash
mtg data refresh     # Scryfall cards + rulings → local SQLite (downloads ~tens of MB)
mtg rules refresh    # the official Comprehensive Rules (auto-discovers the current version)
```

The first `mtg data refresh` downloads and ingests ~38,000 cards (a few seconds of processing after
the download). You're ready when `mtg data status` reports a card count.

## 3. Use it with Claude Code

Open this folder in Claude Code (`claude` in the project directory, or the VS Code extension) and
just ask. Claude automatically reads [CLAUDE.md](CLAUDE.md) and the domain skills, runs the right
`mtg` commands, and interprets the output for you. Example asks:

- *"Import my collection from `data/inventory.csv`."*
- *"Load the deck in `data/decks/MyDeck.txt`, analyze it, and tell me what to upgrade under $30."*
- *"Simulate my deck — how consistent are my opening hands and when does my commander land?"*
- *"Run a 4-player battle between these decks and explain who wins and why."*
- *"Rank all my decks by power level and tell me which deck types each one beats vs. should fear."*
- *"What happens when Card A and Card B interact? Cite the rulings."*
- *"Build me a deck around <commander> from cards I own, and a shopping list for the gaps."*
- *"After tonight's game, log the result so the matchup model learns from it."*

To bring your own data in, drop your exports into [`data/`](data/) — decklists from
Archidekt/Moxfield/Arena/MTGO as `.txt` in `data/decks/`; collections from ManaBox/Moxfield/Deckbox
as `.csv` (e.g. `data/inventory.csv`). Those files are gitignored and stay on your machine.

## 4. Command reference (optional — for driving it directly)

Claude runs these for you, but you can run any of them yourself. All deck commands accept a saved
deck name **or** a file path.

| Command | What it does |
|---|---|
| `mtg data refresh` / `status` | Download + ingest Scryfall cards & rulings; show DB status |
| `mtg rules refresh` / `get <n>` / `search <q>` / `glossary <t>` | Comprehensive Rules: refresh, look up a rule + subrules, full-text search, glossary |
| `mtg card "<name>"` | Look up a card (text, identity, rulings count) |
| `mtg explain "<card or question>"` | Card text + rulings + relevant rules + combos, or a free-text rules search |
| `mtg interaction "<a>" "<b>"` | Grounding for how two cards interact (+ any combo between them) |
| `mtg combos card "<name>"` / `find <deck>` | Combos that use a card; combos present + one-card-away in a deck |
| `mtg inventory import <csv…>` / `sync` / `show [--card "<name>"]` | Import collection CSV(s); re-merge decks; stats or per-card locations |
| `mtg deck show <deck>` | Parse + resolve a decklist, report unresolved cards |
| `mtg deck analyze <deck> [--no-combos]` | Validate + score (legality, categories, curve, bracket, combos) |
| `mtg deck simulate <deck> [--games N] [--draw]` | Goldfish consistency simulation |
| `mtg deck recommend <deck> [--budget $] [--no-sim]` | Cuts + adds, EDHREC-blended, sim-aware, budget-capped |
| `mtg deck build "<commander>" [--budget $] [--owned-only]` | Build a legal 100 from your collection + shopping list |
| `mtg deck suggest-commanders` | Legal commanders you own, by popularity |
| `mtg deck guide <deck> \| --all [--pod]` | Generate a pilot's strategy guide (markdown); `--pod` appends pod-matchup outlook + 1v1 tendencies (slow — sweeps all saved decks) |
| `mtg deck save <name> <file>` / `list` / `remove <name>` / `diff <a> <b>` | Manage saved decks; compare two decklists |
| `mtg battle <decks…> [--games N] [--preset casual\|mid\|cedh] [--calibrate] [--sensitivity]` | Heuristic 1v1/4-player matchup sim (2–4 decks) |
| `mtg battle <pool 5+…> --metagame` | Power-level ranking across every pod in a pool (tiers, archenemy %, naive vs. informed win rates) |
| `mtg matchlog add <pod…> --winner <deck>` / `form` / `list` | Record real game results (the corpus the battle sim learns from) |

Run any command with `--help` for its full options.

## Where your data lives & privacy

- Your card database, decks, collection, generated guides, and match log all live under `data/`,
  which is **gitignored** — none of it is committed or pushed.
- The card DB is fully regenerable: delete `data/` and run `mtg data refresh` + `mtg rules refresh`.
- Only synthetic test fixtures (under `tests/fixtures/`) are tracked — never real collections.

## Keeping up to date

Because you made your copy from a template (not a fork), pull in upstream improvements by adding this
repo as a second remote and merging when you want updates:

```bash
git remote add upstream https://github.com/QuackQuackLabs/MTG-Analyzer.git
git fetch upstream
git merge upstream/main      # review changes, then keep your local data untouched (it's gitignored)
```

## Contributing

Found a bug or want a feature in the shared tool? See **[CONTRIBUTING.md](CONTRIBUTING.md)**: fork →
branch → keep `pytest` / `ruff` / `mypy` green → open a PR against `main`. Read
[project-plan.md](project-plan.md) and [CLAUDE.md](CLAUDE.md) first — they're the source of truth for
scope and conventions.

## Tech & status

- **Engine:** Python 3.11+, SQLite, numpy/scipy, httpx, pydantic. The engine is UI-agnostic; all
  orchestration lives behind a service facade (`AnalyzerService`) that both the CLI and the coming web
  API call. A thin FastAPI app is the seed for that UI.
- **Data sources:** [Scryfall](https://scryfall.com/docs/api) (cards, rulings, bulk),
  [Commander Spellbook](https://commanderspellbook.com/) (combos), EDHREC (recommendation stats).
- **Status:** feature-complete for local, chat-driven use; the battle/matchup simulator has landed
  (validated against experienced-player rankings). A **web UI (Phase 10)** is the next frontier — the
  engine foundations for it are in place. Full roadmap in [project-plan.md](project-plan.md).

## Legal

Card data and images are used under **Wizards of the Coast's Fan Content Policy** via Scryfall, and
combo/recommendation data come from Commander Spellbook and EDHREC under their respective terms. This
is a **non-commercial, local** tool. It does not paywall or redistribute that data — it fetches it at
runtime for your personal use.

The MTG Analyzer **source code** is licensed under the [MIT License](LICENSE). That license covers
the code only — **not** the card data, rulings, or images, which remain under their sources' terms.

Magic: The Gathering is © Wizards of the Coast. MTG Analyzer is unofficial Fan Content and is **not
affiliated with or endorsed by** Wizards of the Coast or Scryfall.

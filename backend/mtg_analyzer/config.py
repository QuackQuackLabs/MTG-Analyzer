"""Central configuration: paths, headers, and Scryfall constants.

Paths default to the repo's ``data/`` directory but can be overridden with the
``MTG_DATA_DIR`` env var (useful for tests and alternate locations).
"""

from __future__ import annotations

import os
from pathlib import Path

from mtg_analyzer import __version__

# Repo root = three parents up from this file (backend/mtg_analyzer/config.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("MTG_DATA_DIR", _REPO_ROOT / "data"))
SCRYFALL_DIR = DATA_DIR / "scryfall"
DB_PATH = DATA_DIR / "app.db"

SCRYFALL_API_BASE = "https://api.scryfall.com"

# Required by Scryfall: a descriptive User-Agent and an explicit Accept header.
# (Requests without them are rejected — see the scryfall-api skill.)
USER_AGENT = f"MTGAnalyzer/{__version__} (jacob@quackquacklabs.com)"
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

# Politeness: Scryfall asks for <10 req/s; ~100 ms between requests is the safe value.
REQUEST_DELAY_SECONDS = 0.1

# Bulk-data types we ingest (see scryfall-api skill for the full catalog).
BULK_ORACLE_CARDS = "oracle_cards"
BULK_RULINGS = "rulings"


def ensure_dirs() -> None:
    """Create the local data directories if they don't exist."""
    SCRYFALL_DIR.mkdir(parents=True, exist_ok=True)

"""A small on-disk library of saved decklists (data/decks/<slug>.txt).

Lets the user refer to a deck by name ("analyze my sauron deck") instead of a file
path. Stores the original decklist text, so any supported format re-parses on load.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from mtg_analyzer import config

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    # Strip accents via NFKD so a name slugs identically whether the filesystem stored it
    # composed (NFC "é") or decomposed (macOS NFD "e"+◌́): "Sméagol" -> "smeagol" either way.
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SLUG_RE.sub("-", ascii_name.lower()).strip("-")


class DeckLibrary:
    def __init__(self, decks_dir: Path | None = None) -> None:
        self.dir = decks_dir or (config.DATA_DIR / "decks")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _find(self, name: str) -> Path | None:
        """Locate a deck file by name, tolerant of human-readable filenames.

        Matches a slugified file (the canonical form) first, then any existing
        ``*.txt`` whose stem slugifies to the same value — so "Frodo and Sam",
        "frodo-and-sam", and a dropped-in ``Frodo and Sam.txt`` all resolve.
        """
        target = slugify(name)
        direct = self.dir / f"{target}.txt"
        if direct.exists():
            return direct
        for path in self.dir.glob("*.txt"):
            if slugify(path.stem) == target:
                return path
        return None

    def _path(self, name: str) -> Path:
        return self.dir / f"{slugify(name)}.txt"

    def save(self, name: str, text: str) -> str:
        # Overwrite an existing (possibly human-named) file rather than create a duplicate.
        path = self._find(name) or self._path(name)
        path.write_text(text, encoding="utf-8")
        return path.stem

    def get(self, name: str) -> str | None:
        path = self._find(name)
        return path.read_text(encoding="utf-8") if path else None

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.txt"))

    def remove(self, name: str) -> bool:
        path = self._find(name)
        if path:
            path.unlink()
            return True
        return False


def load_deck_text(name_or_path: str) -> str:
    """Resolve a deck argument to its text: an existing file path, else a saved deck name."""
    path = Path(name_or_path)
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = DeckLibrary().get(name_or_path)
    if text is None:
        raise FileNotFoundError(
            f"No file or saved deck named {name_or_path!r}. "
            "Save one with `mtg deck save <name> <file>` or see `mtg deck list`."
        )
    return text

"""Append-only store for logged real games (data/match_log.jsonl).

One JSON object per line, hand-editable. Reads validate every line and **surface** malformed rows
(line number + reason) rather than silently dropping them — a corrupt entry is a data problem the
user should see, not lose. This is the corpus the battle fitter (Phase 9C-2) consumes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from mtg_analyzer import config
from mtg_analyzer.models.match_log import LoggedGame


@dataclass
class LoadResult:
    games: list[LoggedGame]
    errors: list[str] = field(default_factory=list)  # human-readable "line N: <reason>"


class MatchLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.DATA_DIR / "match_log.jsonl")

    def append(self, game: LoggedGame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(game.model_dump_json(exclude_none=True) + "\n")

    def load(self) -> LoadResult:
        if not self.path.exists():
            return LoadResult(games=[])
        games: list[LoggedGame] = []
        errors: list[str] = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                games.append(LoggedGame.model_validate_json(line))
            except (ValidationError, json.JSONDecodeError) as exc:
                first = str(exc).splitlines()[0]
                errors.append(f"line {n}: {first}")
        return LoadResult(games=games, errors=errors)

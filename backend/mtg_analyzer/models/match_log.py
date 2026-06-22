"""Model for a logged real-world game — the corpus the battle simulator is fit against (Phase 9C).

Each `LoggedGame` records one game actually played at the table: the pod (saved-deck slugs), who
won, and the *Standard* fields (died-first + end-turn). It also snapshots the full `BattleProfile`
of every deck **as it played that day**, so the fit stays faithful even after a deck is later
re-tuned (drift insurance). Optional rich fields (win method, archenemy read) ride along for free
and are used only once the corpus is large enough to exploit them.

See docs/battle-calibration-fitting.md.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from mtg_analyzer.models.battle import BattleProfile

# Recognized (optional) win methods — mirror the simulator's method labels so logged reality and
# simulated outcomes can be compared on the same vocabulary.
WIN_METHODS = {"combo", "beatdown", "grind", "stall", "other"}


class LoggedGame(BaseModel):
    date: str  # ISO date the game was played (YYYY-MM-DD)
    pod: list[str]  # saved-deck slugs, 2–4, in seat order when known
    winner: str  # slug; must be in pod
    died_first: str | None = None  # slug; multiplayer only
    end_turn: int | None = None  # turn the game ended
    win_method: str | None = None  # optional rich field (one of WIN_METHODS)
    archenemy: str | None = None  # optional rich field: the slug the table most feared
    # Full profile of each pod deck as-played — drift/version insurance (keyed by slug).
    profiles: dict[str, BattleProfile]
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> LoggedGame:
        if not 2 <= len(self.pod) <= 4:
            raise ValueError(f"pod must have 2–4 decks, got {len(self.pod)}")
        if len(set(self.pod)) != len(self.pod):
            raise ValueError(f"pod has duplicate decks: {self.pod}")
        pod = set(self.pod)
        for field in ("winner", "died_first", "archenemy"):
            val = getattr(self, field)
            if val is not None and val not in pod:
                raise ValueError(f"{field} {val!r} is not in the pod {self.pod}")
        missing = pod - set(self.profiles)
        if missing:
            raise ValueError(f"missing profile snapshot for {sorted(missing)}")
        if self.win_method is not None and self.win_method not in WIN_METHODS:
            raise ValueError(f"win_method {self.win_method!r} not in {sorted(WIN_METHODS)}")
        if self.end_turn is not None and self.end_turn < 1:
            raise ValueError(f"end_turn must be ≥ 1, got {self.end_turn}")
        return self

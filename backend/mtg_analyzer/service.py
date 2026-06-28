"""Application service layer — the single orchestration facade over the engine.

The engine modules (`analysis`, `simulation`, `recommend`, `rules`, …) are pure and return typed
models. The multi-step *wiring* that turns a deck NAME into those models — parse → resolve → fetch
combos → analyze → goldfish → battle-profile → … — used to live only inside the CLI handlers, so a
second front-end (the FastAPI web app) would have had to duplicate it. This module owns that wiring
once; both the CLI and the API call it and only format the returned models.

Design:
- `AnalyzerService` holds the shared resources (card DB, EDHREC cache, inventory store) and manages
  their lifecycle (context manager). Construct one per process/request-scope and reuse it.
- Every method returns engine **models** (or markdown for guides) — never prints.
- Network calls (Commander Spellbook, EDHREC) are **best-effort**: on failure the method returns the
  empty default and appends a human-readable line to `self.notes` for the caller to surface.
- Methods are synchronous (they run the async clients via `asyncio.run`), which suits the CLI and a
  sync API. An async API can wrap these in a threadpool; documented in the web-phase plan.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

from mtg_analyzer.analysis.guide import build_guide
from mtg_analyzer.analysis.pod_sections import render_matchup_tendencies, render_pod_outlook
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.combos.client import CommanderSpellbookClient
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.data.deck_library import load_deck_text, slugify
from mtg_analyzer.data.inventory_store import InventoryStore
from mtg_analyzer.ingest.decklist import parse_deck
from mtg_analyzer.ingest.resolve import resolve_deck
from mtg_analyzer.models.analysis import DeckReport
from mtg_analyzer.models.build import BuiltDeck
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.combo import Combo
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.recommendation import Recommendations
from mtg_analyzer.models.simulation import SimResult
from mtg_analyzer.recommend.builder import build_deck
from mtg_analyzer.recommend.edhrec import EdhrecCache, EdhrecClient
from mtg_analyzer.recommend.recommender import apply_swaps, build_recommendations
from mtg_analyzer.simulation.battle import (
    BattleProfile,
    MatchResult,
    MatchupStats,
    MetagameResult,
    build_profile,
    head_to_head,
    simulate_match,
    simulate_metagame,
)
from mtg_analyzer.simulation.goldfish import simulate

T = TypeVar("T")


def is_legal_commander_card(card: Card) -> bool:
    """A card that can head a Commander deck (legendary creature or explicit grant)."""
    tl = (card.type_line or "").lower()
    return (("legendary" in tl and "creature" in tl)
            or "can be your commander" in card.get_oracle_text().lower())


@dataclass
class DeckAnalysis:
    """A resolved deck plus its analysis report and detected combos (one parse/resolve)."""
    deck: ResolvedDeck
    report: DeckReport
    combos: list[Combo]


@dataclass
class PodAnalysis:
    """Pool-level battle results — the metagame ranking + the 1v1 matchup matrix — built from one set
    of profiles, so a batch of guides can share the (expensive) computation."""
    metagame: MetagameResult
    matchups: list[MatchupStats]


@dataclass
class RecommendationResult:
    """Recommendations plus the before/after goldfish sims that quantify the proposed swaps."""
    recommendations: Recommendations
    identity: str
    sim_before: SimResult | None
    sim_after: SimResult | None


class AnalyzerService:
    """Facade over the engine. Owns the card DB / EDHREC cache / inventory store; returns models."""

    def __init__(
        self,
        *,
        db: CardDatabase | None = None,
        cache: EdhrecCache | None = None,
        inventory: InventoryStore | None = None,
    ) -> None:
        self._db = db
        self._cache = cache
        self._inventory = inventory
        self._owns_db = db is None
        self._owns_cache = cache is None
        self._owns_inventory = inventory is None
        self.notes: list[str] = []

    # --- resource lifecycle (lazy; only opened when first used) ---------------------------------
    @property
    def db(self) -> CardDatabase:
        if self._db is None:
            self._db = CardDatabase()
        return self._db

    @property
    def cache(self) -> EdhrecCache:
        if self._cache is None:
            self._cache = EdhrecCache()
        return self._cache

    @property
    def inventory(self) -> InventoryStore:
        if self._inventory is None:
            self._inventory = InventoryStore()
        return self._inventory

    def close(self) -> None:
        if self._owns_db and self._db is not None:
            self._db.close()
            self._db = None
        if self._owns_cache and self._cache is not None:
            self._cache.close()
            self._cache = None
        if self._owns_inventory and self._inventory is not None:
            self._inventory.close()
            self._inventory = None

    def __enter__(self) -> AnalyzerService:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- best-effort network helper ------------------------------------------------------------
    def _best_effort(self, make_coro: Callable[[], Coroutine[Any, Any, T]], default: T,
                     label: str) -> T:
        try:
            return asyncio.run(make_coro())
        except Exception as e:  # noqa: BLE001 — network is best-effort; engine works offline
            self.notes.append(
                f"{label} unavailable — {type(e).__name__} (offline or rate-limited); skipped.")
            return default

    # --- deck loading + combos -----------------------------------------------------------------
    def resolve(self, name_or_path: str) -> ResolvedDeck:
        """Load a saved deck (by name) or a file path → a resolved deck titled by `name_or_path`."""
        deck = resolve_deck(self.db, parse_deck(load_deck_text(name_or_path)))
        deck.name = name_or_path
        return deck

    def find_combos(self, deck: ResolvedDeck) -> list[Combo]:
        """Commander Spellbook find-my-combos for a resolved deck (best-effort → [] offline)."""
        main = [e.card.name for e in deck.mainboard if e.card]
        cmds = [e.card.name for e in deck.commanders if e.card]

        async def run() -> list[Combo]:
            async with CommanderSpellbookClient() as client:
                result = await client.find_my_combos(main=main, commanders=cmds)
            return result.included

        return self._best_effort(run, [], "Combo detection")

    def edhrec_cards(self, commander_names: list[str]) -> list:
        async def run() -> list:
            async with EdhrecClient(cache=self.cache) as client:
                return await client.commander_cards(commander_names)

        return self._best_effort(run, [], "EDHREC")

    # --- analytical flows (each returns engine models) -----------------------------------------
    def analyze_deck(self, name: str, *, combos: bool = True) -> DeckAnalysis:
        deck = self.resolve(name)
        found = self.find_combos(deck) if combos else []
        return DeckAnalysis(deck=deck, report=analyze(deck, included_combos=found), combos=found)

    def simulate_deck(self, name: str, *, games: int = 10000, on_play: bool = True,
                      combos: bool = True) -> SimResult:
        deck = self.resolve(name)
        found = self.find_combos(deck) if combos else None
        return simulate(deck, combos=found, games=games, on_play=on_play)

    def profile(self, name: str, *, sim_games: int = 1500, combos: bool = True) -> BattleProfile:
        """Map a deck name onto its `BattleProfile` (analyze → goldfish → build_profile)."""
        deck = self.resolve(name)
        found = self.find_combos(deck) if combos else []
        report = analyze(deck, included_combos=found)
        sim = simulate(deck, combos=found, games=sim_games)
        return build_profile(name, deck, report, sim)

    def profiles(self, names: list[str], *, sim_games: int = 1500,
                 combos: bool = True) -> list[BattleProfile]:
        return [self.profile(n, sim_games=sim_games, combos=combos) for n in names]

    def battle(self, names: list[str], *, games: int = 2000, seed: int = 1,
               preset: str | None = None, sim_games: int = 1500,
               combos: bool = True) -> MatchResult:
        profs = self.profiles(names, sim_games=sim_games, combos=combos)
        return simulate_match(profs, games=games, seed=seed, preset=preset)

    def metagame(self, names: list[str], *, pod_size: int = 4, games: int = 1000, seed: int = 1,
                 sim_games: int = 1500, combos: bool = True) -> MetagameResult:
        profs = self.profiles(names, sim_games=sim_games, combos=combos)
        return simulate_metagame(profs, pod_size=pod_size, games=games, seed=seed)

    def head_to_head(self, names: list[str], *, games: int = 3000, seed: int = 1,
                     sim_games: int = 1500, combos: bool = True) -> list[MatchupStats]:
        profs = self.profiles(names, sim_games=sim_games, combos=combos)
        return head_to_head(profs, games=games, seed=seed)

    def pod_analysis(
        self, names: list[str], *, pod_size: int = 4, games: int = 1000, h2h_games: int = 3000,
        seed: int = 1, sim_games: int = 1500, combos: bool = True,
    ) -> PodAnalysis:
        """Build each deck's profile ONCE, then run both the metagame loop and the 1v1 matrix over the
        pool. The result feeds `guide(..., pod=...)` so guides carry the pod-matchup sections."""
        profs = self.profiles(names, sim_games=sim_games, combos=combos)
        meta = simulate_metagame(profs, pod_size=pod_size, games=games, seed=seed)
        matchups = head_to_head(profs, games=h2h_games, seed=seed)
        return PodAnalysis(metagame=meta, matchups=matchups)

    def guide(self, name: str, *, games: int = 10000, pod: PodAnalysis | None = None) -> str:
        """Pilot's guide markdown for a saved deck (analysis + sim + combos + EDHREC synergy). When
        `pod` (from `pod_analysis`) is supplied and contains this deck, the pod-matchup outlook +
        1v1 matchup-tendencies sections are appended."""
        deck = self.resolve(name)
        combos = self.find_combos(deck)
        report = analyze(deck, included_combos=combos)
        sim = simulate(deck, games=games)
        edhrec = self.edhrec_cards(report.commanders)
        extra: list[str] = []
        if pod is not None:
            extra = [s for s in (render_pod_outlook(name, pod.metagame),
                                 render_matchup_tendencies(name, pod.matchups)) if s]
        return build_guide(deck, report, sim, combos, edhrec, extra_sections=extra)

    def recommend(self, name: str, *, budget: float | None = None, sim: bool = True,
                  games: int = 10000) -> RecommendationResult:
        deck = self.resolve(name)
        combos = self.find_combos(deck)
        report = analyze(deck, included_combos=combos)
        protected = {u.name for c in combos for u in c.uses if u.name}
        # Only Available cards (+ this deck's own) — a card committed elsewhere isn't suggested.
        slug = slugify(name)
        owned = self.inventory.available_oracles(for_deck=slug)
        edhrec = self.edhrec_cards(report.commanders)
        before = simulate(deck, combos=combos, games=games, seed=1) if sim else None
        recs = build_recommendations(deck, report, edhrec, self.db, owned=owned, budget=budget,
                                     sim=before, protected=protected)
        after = simulate(apply_swaps(deck, recs, self.db), games=games, seed=1) if sim else None
        return RecommendationResult(recommendations=recs, identity=report.identity,
                                    sim_before=before, sim_after=after)

    def build(self, commander_name: str, *, budget: float | None = None,
              owned_only: bool = False) -> BuiltDeck:
        commander = self.db.get_by_name(commander_name)
        if commander is None:
            raise ValueError(f"No card named {commander_name!r}.")
        if not is_legal_commander_card(commander):
            raise ValueError(f"{commander.name} isn't a legal commander.")
        owned = self.inventory.available_oracles()
        edhrec = self.edhrec_cards([commander.name])
        return build_deck(commander, owned, self.db, edhrec, budget=budget, owned_only=owned_only)

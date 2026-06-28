"""Service-facade unit tests that don't need the card DB — focused on the orchestration logic
(cache-backed, offline-robust combo detection) and JSON-serializability of service returns."""
import json
from types import SimpleNamespace

import pytest

from mtg_analyzer.service import AnalyzerService, to_jsonable
from mtg_analyzer.simulation.battle import (
    DeckMetagameStats,
    MatchupStats,
    MetagameResult,
    OpponentMatchup,
)


def test_to_jsonable_serializes_battle_dataclasses() -> None:
    meta = MetagameResult(
        decks=[DeckMetagameStats("A", 1, 0.12, 0.2, 0.3, 0.4, pod_wins=2,
                                 naive_min=0.1, naive_min_pod=["B"], naive_max=0.6, naive_max_pod=["C"])],
        pod_size=4, pods=10, iterations=3, converged=True, informed=True)
    d = to_jsonable(meta)
    json.dumps(d)  # must not raise — API-serializable
    assert d["decks"][0]["tier"] == "S"          # derived field is present (power 0.12 → S)
    assert d["decks"][0]["naive_max_pod"] == ["C"]

    matchups = [MatchupStats("A", "combo", 0.6, {"combo": 0.5},
                             [OpponentMatchup("B", "aggro", 0.7)])]
    j = to_jsonable(matchups)
    json.dumps(j)
    assert j[0]["opponents"][0]["name"] == "B"


def _fake_deck() -> SimpleNamespace:
    card = SimpleNamespace(name="Thassa's Oracle", oracle_id="oid-1")
    entry = SimpleNamespace(card=card)
    return SimpleNamespace(mainboard=[entry], commanders=[], entries=[entry])


def test_find_combos_live_result_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    live = [object(), object()]
    added: list = []
    store = SimpleNamespace(
        add=lambda combos: added.extend(list(combos)),
        find_in_deck=lambda oids: SimpleNamespace(included=[]),
        close=lambda: None,
    )
    svc = AnalyzerService(combo_store=store)
    # live lookup succeeds → returns the combos and caches them through for offline determinism
    monkeypatch.setattr(svc, "_best_effort", lambda coro, default, label: live)
    out = svc.find_combos(_fake_deck())
    assert out == live
    assert added == live
    assert svc.notes == []


def test_find_combos_offline_falls_back_to_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cached = [object()]
    store = SimpleNamespace(
        add=lambda combos: None,
        find_in_deck=lambda oids: SimpleNamespace(included=cached),
        close=lambda: None,
    )
    svc = AnalyzerService(combo_store=store)
    # live lookup unavailable (best-effort returns the default None) → uses the local cache
    monkeypatch.setattr(svc, "_best_effort", lambda coro, default, label: default)
    out = svc.find_combos(_fake_deck())
    assert out == cached
    assert any("cached" in n for n in svc.notes)


def test_find_combos_offline_empty_cache_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SimpleNamespace(
        add=lambda combos: None,
        find_in_deck=lambda oids: SimpleNamespace(included=[]),
        close=lambda: None,
    )
    svc = AnalyzerService(combo_store=store)
    monkeypatch.setattr(svc, "_best_effort", lambda coro, default, label: default)
    assert svc.find_combos(_fake_deck()) == []  # no combos, no crash

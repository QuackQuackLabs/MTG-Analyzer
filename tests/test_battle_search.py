"""Tests for the Stage 2 prototype: the explicit, resumable abstract forward model + determinized
search (`simulation/battle_search.py`). The headline guarantee is the **2.1 gate** — the explicit model
under the heuristic policy must reproduce the production engine's ranking, so search built on it is
trustworthy. Search itself is exercised for determinism + sanity, not pinned to magnitudes (it is a
prototype, and the verdict is that it does not change the ordinal — see docs/simulator-v2-roadmap.md)."""

from __future__ import annotations

from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.simulation import battle_params as P
from mtg_analyzer.simulation.battle import simulate_match
from mtg_analyzer.simulation.battle_search import (
    initial_state,
    simulate_match_heuristic,
    simulate_match_search,
)


def prof(name: str, **kw: object) -> BattleProfile:
    base: dict[str, object] = {
        "name": name, "archetype": "midrange", "clock_mean": 7.0, "clock_sd": 1.4,
        "interaction": 6, "sweepers": 1, "card_advantage": 8, "has_combo": False,
        "tutors": 0, "threat_level": 5.0,
    }
    base.update(kw)
    return BattleProfile.model_validate(base)


def _pod() -> list[BattleProfile]:
    # A spread of archetypes with clearly different equity, so the ordering is unambiguous.
    return [
        prof("FastCombo", archetype="combo", clock_mean=6.0, has_combo=True, tutors=3, interaction=3),
        prof("Grind", archetype="grind", clock_mean=8.5, interaction=12, card_advantage=14, sweepers=3),
        prof("Mid", clock_mean=7.5, interaction=7, card_advantage=9),
        prof("Aggro", archetype="aggro", clock_mean=4.0, interaction=3, card_advantage=4),
    ]


def test_state_copy_is_independent() -> None:
    import numpy as np

    st = initial_state(_pod(), np.random.default_rng(0))
    clone = st.copy()
    clone.life[0] = -99.0
    clone.reserve[1] = 0.0
    clone.damage_from[0][1] = 5.0
    assert st.life[0] != -99.0 and st.reserve[1] != 0.0 and st.damage_from[0][1] == 0.0
    assert clone.profiles is st.profiles  # static profiles shared, not copied


def test_heuristic_engine_is_deterministic() -> None:
    pod = _pod()
    a = simulate_match_heuristic(pod, games=400, seed=7)
    b = simulate_match_heuristic(pod, games=400, seed=7)
    assert a == b


def test_search_engine_is_deterministic() -> None:
    pod = _pod()
    a = simulate_match_search(pod, games=60, seed=3, determinizations=4)
    b = simulate_match_search(pod, games=60, seed=3, determinizations=4)
    assert a == b


def test_21_gate_prototype_reproduces_production_ranking() -> None:
    # THE GATE: the explicit forward model (heuristic policy) must reproduce production's ranking, so
    # determinized search built on it is trustworthy. Pin the ORDERING (robust to small RNG-structure
    # differences) and require each deck's win rate to track production within a tolerance band.
    pod = _pod()
    proto = simulate_match_heuristic(pod, games=2000, seed=1)
    prod = {d.name: d.win_rate for d in simulate_match(pod, games=2000, seed=1).decks}
    proto_order = sorted(pod, key=lambda p: proto[p.name], reverse=True)
    prod_order = sorted(pod, key=lambda p: prod[p.name], reverse=True)
    assert [p.name for p in proto_order] == [p.name for p in prod_order], (proto, prod)
    for p in pod:
        assert abs(proto[p.name] - prod[p.name]) <= 0.06, (p.name, proto[p.name], prod[p.name])


def test_search_runs_and_returns_a_distribution() -> None:
    pod = _pod()
    res = simulate_match_search(pod, games=80, seed=1, determinizations=4)
    assert abs(sum(res.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in res.values())


def test_grounded_coordination_is_stable_and_preserves_ranking() -> None:
    # Stage 3 — the CICERO-grounded bystander model (each defender free-rides on the OTHER defenders'
    # answering capacity) must be STABLE (the naive self-referential version collapsed) and, at its
    # calibrated strength, must REPRODUCE the flat-knob ranking — it is a fidelity refinement, not an
    # outcome change (the audit found coordination near-inert on the ranking; see the roadmap).
    pod = _pod()
    flat = simulate_match_heuristic(pod, games=1500, seed=1)
    saved = (P.GROUNDED_COORDINATION, P.FREE_RIDER_STRENGTH)
    try:
        P.GROUNDED_COORDINATION = True
        P.FREE_RIDER_STRENGTH = 0.35
        grounded = simulate_match_heuristic(pod, games=1500, seed=1)
    finally:
        P.GROUNDED_COORDINATION, P.FREE_RIDER_STRENGTH = saved
    # Stable distribution (no collapse to all-defer / runaway).
    assert abs(sum(grounded.values()) - 1.0) < 1e-9
    # Same ordering as the flat knob, and no deck moved by more than a few points.
    assert sorted(flat, key=lambda k: flat[k]) == sorted(grounded, key=lambda k: grounded[k])
    assert all(abs(grounded[k] - flat[k]) <= 0.05 for k in flat), (flat, grounded)

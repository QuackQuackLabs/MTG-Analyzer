"""Tests for the heuristic battle simulator (Phase 9).

Two layers:
- **Invariants** — relations the model must always honor (determinism, faster-clock-wins-more,
  4-player blunts fast-combo dominance, rates sum to 1, explainability rank mechanics).
- **Anchor fixtures** (design §4) — canonical matchups whose *magnitudes* are pinned with tolerance
  bands, so a future parameter retune can't silently swing the calibrated behavior. Observed centers
  are recorded inline; bands absorb seed/sensitivity noise but catch a real regression.
"""

from __future__ import annotations

from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.simulation.battle import calibrate_match, simulate_match


def prof(name: str, **kw: object) -> BattleProfile:
    base: dict[str, object] = {
        "name": name, "archetype": "midrange", "clock_mean": 7.0, "clock_sd": 1.4,
        "interaction": 6, "sweepers": 1, "card_advantage": 8, "has_combo": False,
        "tutors": 0, "threat_level": 5.0,
    }
    base.update(kw)
    return BattleProfile.model_validate(base)


def test_deterministic_same_seed() -> None:
    decks = [prof("A", clock_mean=6.0), prof("B", clock_mean=8.0)]
    r1 = simulate_match(decks, games=500, seed=7)
    r2 = simulate_match(decks, games=500, seed=7)
    assert [d.win_rate for d in r1.decks] == [d.win_rate for d in r2.decks]


def test_win_rates_sum_to_one() -> None:
    decks = [prof("A"), prof("B"), prof("C"), prof("D")]
    r = simulate_match(decks, games=800, seed=1)
    assert abs(sum(d.win_rate for d in r.decks) - 1.0) < 0.02


def test_faster_clock_wins_more_1v1() -> None:
    # Identical decks except A is meaningfully faster — A must win the majority.
    fast = prof("Fast", clock_mean=5.0)
    slow = prof("Slow", clock_mean=9.0)
    r = simulate_match([fast, slow], games=2000, seed=3)
    by = {d.name: d.win_rate for d in r.decks}
    assert by["Fast"] > by["Slow"]
    assert by["Fast"] > 0.5


def test_interaction_helps_against_combo() -> None:
    # A fast combo vs a slower deck: more interaction on the defender raises its win share.
    combo = prof("Combo", archetype="combo", clock_mean=6.0, has_combo=True, tutors=4, interaction=2)
    low = prof("LowInt", clock_mean=8.0, interaction=2, card_advantage=4)
    high = prof("HighInt", clock_mean=8.0, interaction=12, card_advantage=12)
    r_low = simulate_match([combo, low], games=2000, seed=5)
    r_high = simulate_match([combo, high], games=2000, seed=5)
    win_low = {d.name: d.win_rate for d in r_low.decks}["LowInt"]
    win_high = {d.name: d.win_rate for d in r_high.decks}["HighInt"]
    assert win_high > win_low


def test_pod_blunts_fast_combo_vs_1v1() -> None:
    # The same fast combo deck should win a smaller SHARE in a 4-player pod than heads-up,
    # because three opponents pool interaction against the archenemy.
    combo = prof("Combo", archetype="combo", clock_mean=6.0, has_combo=True, tutors=3, interaction=3)
    others = [prof(f"Fair{i}", clock_mean=8.5, interaction=8, card_advantage=9) for i in range(3)]
    duel = simulate_match([combo, others[0]], games=2000, seed=2)
    pod = simulate_match([combo, *others], games=2000, seed=2)
    combo_duel = {d.name: d.win_rate for d in duel.decks}["Combo"]
    combo_pod = {d.name: d.win_rate for d in pod.decks}["Combo"]
    assert combo_pod < combo_duel
    # Archenemy flagged on the top threat in a pod.
    assert any(d.archenemy_rate > 0 for d in pod.decks)


def test_band_brackets_point_estimate() -> None:
    decks = [prof("A", clock_mean=6.0), prof("B", clock_mean=7.5)]
    r = simulate_match(decks, games=1000, seed=1)
    for d in r.decks:
        assert d.win_rate_low <= d.win_rate <= d.win_rate_high


def test_archenemy_rate_is_a_proper_distribution() -> None:
    # Phase B: archenemy is a per-game rate over the table (sums to ~1), and the scariest deck
    # (fastest combo + high threat) carries it most often.
    scary = prof("Scary", archetype="combo", clock_mean=5.0, has_combo=True, threat_level=9.0)
    others = [prof(f"D{i}", clock_mean=8.5, threat_level=4.0) for i in range(3)]
    r = simulate_match([scary, *others], games=1500, seed=4)
    by = {d.name: d.archenemy_rate for d in r.decks}
    assert abs(sum(by.values()) - 1.0) < 0.05
    assert by["Scary"] == max(by.values())


def test_clock_and_equity_ranks_are_permutations() -> None:
    # Explainability: both rankings are a proper 1..n permutation, the fastest clock holds rank 1,
    # and rank_shift is exactly the gap between them.
    decks = [prof("A", clock_mean=5.0), prof("B", clock_mean=6.5),
             prof("C", clock_mean=8.0), prof("D", clock_mean=9.5)]
    r = simulate_match(decks, games=800, seed=1)
    n = len(r.decks)
    assert sorted(d.clock_rank for d in r.decks) == list(range(1, n + 1))
    assert sorted(d.equity_rank for d in r.decks) == list(range(1, n + 1))
    by = {d.name: d for d in r.decks}
    assert by["A"].clock_rank == 1  # fastest clock
    for d in r.decks:
        assert d.rank_shift == d.clock_rank - d.equity_rank


def test_rank_shift_conserves_and_attributes_politics() -> None:
    # Explainability mechanics: clock_rank and equity_rank are permutations of 1..n, so the
    # rank_shifts (clock − equity) must sum to zero — a deck rising above its speed is exactly
    # balanced by another falling below it. And a heavily-targeted fast deck's attribution must
    # name the politics pressure (archenemy) that reshaped its raw speed.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    r = simulate_match([combo, *others], games=2000, seed=2)
    assert sum(d.rank_shift for d in r.decks) == 0  # conservation
    by = {d.name: d for d in r.decks}
    assert by["Combo"].archenemy_rate >= 0.40       # the fast combo draws the table
    assert "archenemy" in by["Combo"].explain        # ...and the attribution says so
    assert all("clock #" in d.explain and "equity #" in d.explain for d in r.decks)


def test_pods_resolve_mostly_mid_game() -> None:
    # Phase C health check: with finite interaction, a pod of combo decks should resolve mostly by
    # combo/beatdown, NOT collapse to the turn-cap inevitability tiebreak.
    decks = [prof(f"C{i}", archetype="combo", clock_mean=6.0 + i * 0.5, has_combo=True, tutors=2)
             for i in range(4)]
    rows = calibrate_match(decks, games=1000, seed=1)
    mid = next(row for row in rows if row.answer_base == 0.30)
    assert mid.inevitability_share < 0.5  # most games decided before the cap
    assert abs(sum(mid.win_rates) - 1.0) < 0.02


# ---------------------------------------------------------------------------
# Anchor fixtures (design §4) — canonical matchups whose *magnitudes* are pinned with tolerance
# bands, so a future parameter retune can't silently swing the calibrated behavior. Unlike the
# invariants above (which assert only relations like A>B), these document "how much". Bands are
# wide enough to absorb seed/sensitivity noise (~±0.03) but tight enough to catch a real regression.
# Observed centers recorded inline; seed fixed for reproducibility.
# ---------------------------------------------------------------------------

def test_anchor_speed_dominates_1v1() -> None:
    # A turn-5 tutored combo vs a turn-8 fair deck, heads-up: speed runs away with it (~0.99).
    fast = prof("FastCombo", archetype="combo", clock_mean=5.0, has_combo=True, tutors=3)
    fair = prof("FairMid", clock_mean=8.0)
    by = {d.name: d.win_rate for d in simulate_match([fast, fair], games=3000, seed=1).decks}
    assert by["FastCombo"] >= 0.88


def test_anchor_pod_blunts_a_fast_deck() -> None:
    # The canonical "pod blunts the fast deck" story with magnitudes: a moderately-fast combo wins
    # the clear majority heads-up (~0.83) but is dragged to a minority in a 4-pod (~0.29) where it
    # becomes the table's archenemy (~0.60 of turns) and three opponents coordinate answers.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    fair1v1 = prof("Fair", clock_mean=7.0, interaction=10, card_advantage=11)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    duel = {d.name: d for d in simulate_match([combo, fair1v1], games=3000, seed=1).decks}
    pod = {d.name: d for d in simulate_match([combo, *others], games=3000, seed=1).decks}
    assert 0.68 <= duel["Combo"].win_rate <= 0.95          # dominant heads-up
    assert 0.18 <= pod["Combo"].win_rate <= 0.42           # blunted in the pod
    assert pod["Combo"].win_rate < duel["Combo"].win_rate  # the pod cost it
    assert pod["Combo"].archenemy_rate >= 0.40             # ...because it drew the table


def test_anchor_mirror_is_symmetric() -> None:
    # Four IDENTICAL decks must each win ~0.25 with no seat-order advantage (regression guard for
    # the deterministic-tiebreak bias that had the last seat winning ~0.38 vs the first seat ~0.15).
    decks = [prof(f"M{i}") for i in range(4)]
    r = simulate_match(decks, games=3000, seed=1)
    for d in r.decks:
        assert 0.19 <= d.win_rate <= 0.31          # symmetric win share
        assert 0.18 <= d.archenemy_rate <= 0.32    # ...and symmetric archenemy pressure


def test_anchor_grind_out_values_aggro_1v1() -> None:
    # A slow, answer-and-draw-dense grind deck out-lasts a fast-but-shallow aggro deck heads-up,
    # winning the long game on interaction + card advantage (~0.88).
    aggro = prof("Aggro", archetype="aggro", clock_mean=6.0, interaction=3, card_advantage=4)
    grind = prof("Grind", archetype="grind", clock_mean=8.5, interaction=12, card_advantage=14,
                 sweepers=3)
    by = {d.name: d.win_rate for d in simulate_match([aggro, grind], games=3000, seed=1).decks}
    assert by["Grind"] >= 0.72

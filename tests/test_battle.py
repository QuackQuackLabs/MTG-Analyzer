"""Tests for the heuristic battle simulator (Phase 9).

Two layers:
- **Invariants** — relations the model must always honor (determinism, faster-clock-wins-more,
  4-player blunts fast-combo dominance, rates sum to 1, explainability rank mechanics).
- **Anchor fixtures** (design §4) — canonical matchups whose *magnitudes* are pinned with tolerance
  bands, so a future parameter retune can't silently swing the calibrated behavior. Observed centers
  are recorded inline; bands absorb seed/sensitivity noise but catch a real regression.
"""

from __future__ import annotations

from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.combo import Combo, ComboCard
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry
from mtg_analyzer.models.simulation import CommanderTurnStats, SimResult
from mtg_analyzer.simulation import battle_params as P
from mtg_analyzer.simulation.battle import (
    _archetype,
    _protection_count,
    build_profile,
    calibrate_match,
    simulate_match,
)
from mtg_analyzer.simulation.sensitivity import analyze_sensitivity, param_overrides


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


def _bp_card(name: str, **kw: object) -> Card:
    base: dict[str, object] = {"id": name, "oracle_id": name, "name": name, "layout": "normal",
                               "cmc": 2.0, "type_line": "Artifact", "oracle_text": "",
                               "color_identity": [], "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def _bp_inputs(combo_turn: float | None, combo_count: int) -> tuple[ResolvedDeck, object, SimResult]:
    cmd = _bp_card("Cmdr", type_line="Legendary Creature", cmc=5.0)
    deck = ResolvedDeck(name="d", entries=[
        ResolvedEntry(quantity=1, section="commander", requested_name="Cmdr", card=cmd),
        ResolvedEntry(quantity=60, section="main", requested_name="Rock", card=_bp_card("Rock")),
        ResolvedEntry(quantity=39, section="main", requested_name="Land",
                      card=_bp_card("Land", type_line="Land", cmc=0.0)),
    ])
    combo = Combo(id="c", produces=["Win"], identity="C", requires=[],
                  uses=[ComboCard(oracle_id="Rock", name="Rock")])
    report = analyze(deck, included_combos=[combo])
    cb = (CommanderTurnStats(mean=combo_turn, median=int(combo_turn), p90=int(combo_turn) + 2,
                             never_pct=0.0) if combo_turn is not None else None)
    sim = SimResult(games=1, on_play=True, land_count=39, ramp_count=0, commander_cmc=5,
                    avg_lands_in_opening=2.8, p_keepable_hand=0.8, p_three_plus_lands_exact=0.5,
                    avg_mulligans=0.2, flood_rate=0.05, screw_rate=0.05,
                    commander_turn=CommanderTurnStats(mean=5.0, median=5, p90=7, never_pct=0.0),
                    combo_turn=cb, combo_count=combo_count, notes=[])
    return deck, report, sim


def test_layer2_combo_clock_grounds_in_assembly() -> None:
    # A non-aggro combo deck's clock should be pulled toward its measured assembly turn, and combo
    # redundancy should tighten the variance.
    deck, report, sim_with = _bp_inputs(9.0, 3)
    _, _, sim_without = _bp_inputs(None, 0)
    p_with = build_profile("D", deck, report, sim_with)  # type: ignore[arg-type]
    p_without = build_profile("D", deck, report, sim_without)  # type: ignore[arg-type]
    assert p_with.archetype != "aggro"            # combo archetype (no creatures + combo present)
    assert p_with.clock_mean > p_without.clock_mean  # combo_turn (9) pulled the clock later than 5+2
    assert p_with.clock_sd < p_without.clock_sd      # 3 combos tightened the variance
    assert p_with.combo_count == 3


def test_archetype_combo_primary_only_when_assembled_on_curve() -> None:
    # A combo that assembles near the deck's tempo is the primary plan; one that lands far later is a
    # backup, so a creature-heavy fast deck is classified by its faster plan instead.
    assert _archetype(30, 3.0, combo_turn=4.0, counts={}, has_combo=True) == "combo"
    assert _archetype(30, 3.0, combo_turn=11.0, counts={}, has_combo=True) == "aggro"


def test_param_overrides_restores() -> None:
    before = P.THREAT_BOARD_W
    with param_overrides({"THREAT_BOARD_W": before + 5.0}):
        assert P.THREAT_BOARD_W == before + 5.0
    assert P.THREAT_BOARD_W == before  # restored on exit


def test_sensitivity_band_and_importance() -> None:
    decks = [prof("A", archetype="combo", clock_mean=6.0, has_combo=True, tutors=3),
             prof("B", clock_mean=8.0, interaction=10, card_advantage=10)]
    res = analyze_sensitivity(decks, samples=24, games=300, seed=1)
    for name in ("A", "B"):
        lo, mid, hi = res.band[name]
        assert lo <= mid <= hi          # well-formed band
        assert hi - lo > 0.0            # the joint prior produces real spread (not a point)
    assert len(res.importance) == len(P.PRIORS)            # every prior screened
    vals = [v for _, v in res.importance]
    assert vals == sorted(vals, reverse=True)              # ranked most-influential first


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


def test_f1_visible_archenemy_wins_below_fair_share() -> None:
    # F1 stylized-fact §3.1: the highest-PERCEIVED-threat deck (a visible fast combo) wins BELOW its
    # fair share (1/N = 0.25) while the under-the-radar fair decks inherit the wins. Ordinal: the
    # archenemy is the table's most-targeted seat yet finishes last in equity.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    r = simulate_match([combo, *others], games=2500, seed=1)
    by = {d.name: d for d in r.decks}
    assert by["Combo"].win_rate < 0.25                       # below fair share (the 11% archenemy)
    assert by["Combo"].archenemy_rate == max(d.archenemy_rate for d in r.decks)  # most targeted
    assert by["Combo"].win_rate == min(d.win_rate for d in r.decks)             # ...so it wins least


def test_f1_under_perceived_deck_overperforms() -> None:
    # F1 stylized-fact §3.3 (mechanism): among otherwise IDENTICAL decks, the one the table UNDER-reads
    # (lower visibility = the "quiet shark") is answered less and wins MORE. Isolates perception from
    # true equity — the decks differ only in how visible their threat is.
    hidden = prof("Hidden", visibility=0.7)
    siblings = [prof(f"V{i}") for i in range(3)]
    r = simulate_match([hidden, *siblings], games=2500, seed=1)
    by = {d.name: d for d in r.decks}
    assert by["Hidden"].win_rate == max(d.win_rate for d in r.decks)
    assert by["Hidden"].archenemy_rate == min(d.archenemy_rate for d in r.decks)


def test_f2_coordination_knob_lowers_archenemy_win() -> None:
    # F2 stylized-fact §3.6: raising the table's coordination (less free-riding) MONOTONICALLY lowers
    # the visible archenemy's win rate — casual (poor coordination) < coordinated < cEDH focus. This is
    # the attrition/coordination core and F5's power-preset axis.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    wins = []
    for coord in (0.65, 0.80, 0.92):
        with param_overrides({"ANSWER_COORDINATION": coord}):
            by = {d.name: d.win_rate for d in simulate_match([combo, *others], games=2000, seed=1).decks}
            wins.append(by["Combo"])
    assert wins[0] > wins[1] > wins[2]  # more coordination → archenemy wins less


def test_f3_spoiler_denies_the_leader() -> None:
    # F3 stylized-fact §3 (spoiler): an out-of-contention seat spends interaction to deny the table's
    # leader, so activating spoiler etiquette LOWERS the leader's win rate. A clear leader + 2 peers +
    # one weak, slow seat that can't win itself but can still hold up answers.
    leader = prof("Leader", archetype="combo", clock_mean=6.0, has_combo=True, tutors=3,
                  threat_level=9.0, interaction=3)
    peers = [prof(f"Peer{i}", clock_mean=7.5, interaction=9, card_advantage=10, threat_level=5.0)
             for i in range(2)]
    weak = prof("Weak", clock_mean=10.0, interaction=8, card_advantage=6, threat_level=3.0)
    pod = [leader, *peers, weak]
    with param_overrides({"SPOILER_ANSWER_BONUS": 1.0}):  # spoiler etiquette off (neutral multiplier)
        off = {d.name: d.win_rate for d in simulate_match(pod, games=2500, seed=1).decks}
    with param_overrides({"SPOILER_ANSWER_BONUS": 1.8}):  # spoiler etiquette strong
        on = {d.name: d.win_rate for d in simulate_match(pod, games=2500, seed=1).decks}
    assert on["Leader"] < off["Leader"]


def test_f3_go_first_caution_lengthens_standoffs() -> None:
    # F3 stylized-fact §3.5 (go-first penalty / standoff): with answers open on the table, decks wait
    # rather than go first and get answered — so more caution => longer games (a standoff the table
    # outwaits until attrition forces someone to commit).
    decks = [prof(f"C{i}", archetype="combo", clock_mean=6.0 + 0.3 * i, has_combo=True, tutors=2,
                  interaction=6) for i in range(4)]
    with param_overrides({"GO_FIRST_CAUTION": 0.0}):
        none = simulate_match(decks, games=1500, seed=1).avg_game_length
    with param_overrides({"GO_FIRST_CAUTION": 0.6}):
        cautious = simulate_match(decks, games=1500, seed=1).avg_game_length
    assert cautious > none


def test_f4_protection_raises_win_monotonic() -> None:
    # F4 stylized-fact: protection cancels answers ~1:1, so a more-protected combo wins MORE — a
    # protection-dense (cEDH) combo can over-perform even as the archenemy ("a win must survive three
    # defenders"). Ordinal/monotone across protection counts.
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    wins = []
    for pr in (0, 2, 5):
        combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                     interaction=2, threat_level=9.0, protection=pr)
        by = {d.name: d.win_rate for d in simulate_match([combo, *others], games=2000, seed=1).decks}
        wins.append(by["Combo"])
    assert wins[0] < wins[1] < wins[2]


def test_f4_visibility_table_is_complete_and_ordered() -> None:
    # F4 completed the archetype-visibility table: durdle decks (combo/grind) under-read, a wide aggro
    # board over-reads, midrange is the baseline 1.0. Guards the perception ordering F1/F4 depend on.
    v = P.ARCHETYPE_VISIBILITY
    assert set(v) == {"combo", "grind", "control", "midrange", "aggro"}
    assert v["combo"] < v["grind"] < v["control"] < v["midrange"] < v["aggro"]
    assert v["midrange"] == 1.0


def test_f4_protection_count_detects_protective_text() -> None:
    # F4 detector: cards that shield the controller's own play are counted; vanilla cards are not.
    protective = ResolvedDeck(name="p", entries=[
        ResolvedEntry(quantity=1, section="main", requested_name="Veil",
                      card=_bp_card("Veil", oracle_text="Your spells can't be countered this turn.")),
        ResolvedEntry(quantity=1, section="main", requested_name="Heroic",
                      card=_bp_card("Heroic", oracle_text="Permanents you control gain hexproof and "
                                                          "indestructible until end of turn.")),
        ResolvedEntry(quantity=1, section="main", requested_name="Bear",
                      card=_bp_card("Bear", oracle_text="")),
    ])
    assert _protection_count(protective) == 2


def test_f5_second_threat_inherits_the_win() -> None:
    # POM §3.2: with one clear top threat (a visible fast combo), the SECOND-most-threatening seat is
    # NOT the one that wins — the under-the-radar seats inherit. Concretely: the archenemy wins below
    # fair share, and the top win rate belongs to a deck that is not the most-targeted.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    decks = {d.name: d for d in simulate_match([combo, *others], games=2500, seed=1).decks}
    most_targeted = max(decks.values(), key=lambda d: d.archenemy_rate)
    top_winner = max(decks.values(), key=lambda d: d.win_rate)
    assert most_targeted.name == "Combo"          # the visible threat draws the heat
    assert top_winner.name != "Combo"             # ...and someone else inherits the win
    assert decks["Combo"].win_rate < 0.25         # below fair share


def test_f5_preset_coordination_orders_archenemy_win() -> None:
    # POM §3.6 via the power presets: a casual table (poor coordination, reckless) lets the archenemy
    # win MORE than a cEDH table that gangs it. casual > mid > cedh.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    wins = {}
    for pr in ("casual", "mid", "cedh"):
        by = {d.name: d.win_rate for d in simulate_match([combo, *others], games=2000, seed=1,
                                                         preset=pr).decks}
        wins[pr] = by["Combo"]
    assert wins["casual"] > wins["mid"] > wins["cedh"]


def test_f5_pacing_cedh_resolves_before_casual() -> None:
    # POM §3.7 (ordinal — magnitudes are deck-driven and equifinal, so we pin the relation): a fast
    # cEDH-clocked pod resolves in FEWER turns than a slow casual-clocked pod.
    cedh = [prof(f"C{i}", archetype="combo", clock_mean=4.5 + 0.3 * i, has_combo=True, tutors=4,
                 interaction=5, protection=3) for i in range(4)]
    casual = [prof("Mid1", clock_mean=7.5, interaction=6, card_advantage=7),
              prof("Mid2", clock_mean=8.0, interaction=7, card_advantage=8),
              prof("Combo", archetype="combo", clock_mean=7.0, has_combo=True, tutors=2, interaction=4),
              prof("Aggro", archetype="aggro", clock_mean=6.5, card_advantage=4, interaction=3)]
    cedh_len = simulate_match(cedh, games=2000, seed=1, preset="cedh").avg_game_length
    casual_len = simulate_match(casual, games=2000, seed=1, preset="casual").avg_game_length
    assert cedh_len < casual_len


def test_f5_unknown_preset_rejected() -> None:
    import pytest
    with pytest.raises(ValueError, match="unknown preset"):
        simulate_match([prof("A"), prof("B")], games=10, seed=1, preset="bogus")


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
    # The canonical "pod blunts the fast deck" story, ORDINAL (the precise pod win is coordination-
    # dependent and equifinal, so we pin *relations*). The opponent here is a dedicated CONTROL deck
    # (interaction 10, card-adv 11) vs a glass-cannon combo (interaction 2). NOTE (Stage 1): the 1v1 leg
    # is no longer a blowout — mid-game attrition lets a single control deck GRIND the fragile combo to
    # roughly even heads-up (~0.52, down from the old speed-monocausal ~0.68); against a *generic* deck
    # the combo still dominates ~0.77 (that clean "speed dominates with equal resources" fact is pinned
    # by test_anchor_speed_dominates_1v1). The point preserved here: a control POD CRUSHES the combo
    # (the three pooled answerers + the grind take it far below 1/N) while a lone control deck only
    # contests it — pod ≪ duel, and the under-the-radar decks inherit the wins.
    combo = prof("Combo", archetype="combo", clock_mean=6.5, has_combo=True, tutors=2,
                 interaction=2, threat_level=9.0)
    fair1v1 = prof("Fair", clock_mean=7.0, interaction=10, card_advantage=11)
    others = [prof(f"Fair{i}", clock_mean=7.0, interaction=10, card_advantage=11, threat_level=4.0)
              for i in range(3)]
    duel = {d.name: d for d in simulate_match([combo, fair1v1], games=3000, seed=1).decks}
    pod = {d.name: d for d in simulate_match([combo, *others], games=3000, seed=1).decks}
    assert duel["Combo"].win_rate >= 0.45                          # contested heads-up (control grinds it)
    assert 0.02 <= pod["Combo"].win_rate < 0.20                    # the pod crushes it, far below 1/N
    assert pod["Combo"].win_rate < duel["Combo"].win_rate - 0.2   # the pod cost it a LOT
    assert pod["Combo"].win_rate == min(d.win_rate for d in pod.values())  # under-radar decks inherit
    assert pod["Combo"].archenemy_rate >= 0.40                    # ...because it drew the table


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


# --- Stage 0.2/0.3 — LOTR ordinal anchor (real-deck ground truth) --------------------------------
# Jacob's experienced-play ranking of the six LOTR decks, strongest → weakest. This is the first POM
# *ordinal* ground-truth fixture (project-plan.md → Phase 9 Appendix A): the literature does not support
# fitting a heuristic sim to a logged corpus, so an ordinal ranking is the honest calibration signal.
LOTR_RANKING = ["Sauron", "Tom Bombadil", "Galadriel", "Gandalf the White", "Sméagol", "Frodo and Sam"]

# Abstracted BattleProfile SNAPSHOTS of the six decks as built by the analyze→goldfish→build_profile
# pipeline as of Stage 0.1. Snapshotted (not resolved live) so the gate is self-contained and portable —
# the decklists are user data and absent from the template repo. Re-snapshot when build_profile changes
# (e.g. Stage 1 multi-factor equity); the gate then ratchets DOWN as the model improves.
def _lotr_profiles() -> list[BattleProfile]:
    return [
        prof("Frodo and Sam", archetype="aggro", clock_mean=3.53, clock_sd=1.0, combo_clock=9.07,
             interaction=7, sweepers=2, card_advantage=6, has_combo=True, combo_count=3, tutors=3,
             threat_level=10.23, visibility=1.1, protection=6),
        prof("Galadriel", archetype="combo", clock_mean=7.69, clock_sd=1.3, combo_clock=None,
             interaction=7, sweepers=0, card_advantage=9, has_combo=True, combo_count=1, tutors=2,
             threat_level=8.15, visibility=0.7, protection=6),
        prof("Gandalf the White", archetype="midrange", clock_mean=7.79, clock_sd=1.4, combo_clock=9.59,
             interaction=11, sweepers=4, card_advantage=15, has_combo=True, combo_count=5, tutors=2,
             threat_level=8.11, visibility=1.0, protection=3),
        prof("Sauron", archetype="combo", clock_mean=9.56, clock_sd=1.2, combo_clock=None,
             interaction=13, sweepers=2, card_advantage=10, has_combo=True, combo_count=2, tutors=2,
             threat_level=7.22, visibility=0.7, protection=5),
        prof("Sméagol", archetype="aggro", clock_mean=4.76, clock_sd=1.0, combo_clock=10.86,
             interaction=7, sweepers=2, card_advantage=10, has_combo=True, combo_count=8, tutors=2,
             threat_level=9.62, visibility=1.1, protection=4),
        prof("Tom Bombadil", archetype="combo", clock_mean=7.73, clock_sd=1.3, combo_clock=None,
             interaction=9, sweepers=3, card_advantage=13, has_combo=True, combo_count=1, tutors=6,
             threat_level=8.13, visibility=0.7, protection=7),
    ]


def _rank_distance(sim_order: list[str], truth: list[str]) -> int:
    """Sum of |Δrank| between two orderings (0 = identical, n*n//2 = fully inverted)."""
    return sum(abs(sim_order.index(name) - truth.index(name)) for name in truth)


def test_anchor_lotr_ordinal_ranking() -> None:
    from itertools import combinations

    # Sweep all C(6,4)=15 four-pods; rank the decks by mean win% across the 10 pods each appears in.
    profiles = {p.name: p for p in _lotr_profiles()}
    names = list(profiles)
    wr_sum = {n: 0.0 for n in names}
    appear = {n: 0 for n in names}
    for pod in combinations(names, 4):
        for d in simulate_match([profiles[n] for n in pod], games=700, seed=1).decks:
            wr_sum[d.name] += d.win_rate
            appear[d.name] += 1
    avg = {n: wr_sum[n] / appear[n] for n in names}
    sim_order = sorted(names, key=lambda n: avg[n], reverse=True)

    # GATE — the model must not be ~inverted from real play. Pre-fix the ranking was inverted
    # (rank-distance 16/18); Stage 0 (win-clock decoupling) brought it to ~10; Stage 1 (mid-game attrition
    # + heat-discounted grind equity) brought it to ~4. Pin a ceiling that catches a regression toward the
    # inverted behavior; it ratchets DOWN as later stages (search, opponent modeling) land.
    dist = _rank_distance(sim_order, LOTR_RANKING)
    assert dist <= 8, f"LOTR ranking distance {dist} (>8) — sim drifting back toward inverted; {avg}"

    # The core inversion, fixed: the player's STRONGEST deck (Sauron — slow but the most interaction-dense
    # and resilient) must now out-rank the WEAKEST (Frodo & Sam — fast aggro with only an incidental, late
    # combo). Pre-fix this was exactly backwards (Sauron 4%, Frodo 74%).
    assert avg["Sauron"] > avg["Frodo and Sam"], f"Sauron {avg['Sauron']:.0%} ≤ Frodo {avg['Frodo and Sam']:.0%}"
    # Stage 0's specific bug-guard: the incidental-combo aggro deck must not dominate by turn-3 combo kills.
    assert avg["Frodo and Sam"] < 0.25, f"Frodo & Sam {avg['Frodo and Sam']:.0%} — incidental-combo bug back?"
    assert avg["Frodo and Sam"] < max(avg.values()), "Frodo & Sam should not be the strongest deck"
    # The resilient, interaction/value decks the player rates highly must clear the fast aggro decks.
    assert avg["Tom Bombadil"] > avg["Frodo and Sam"]
    assert avg["Galadriel"] > avg["Sméagol"]


def test_metagame_feedback_recognizes_winners_and_is_side_effect_free() -> None:
    # Stage 3c/3d — the fictitious-play loop LEARNS each deck's power level (win rate fed back as a
    # threat prior), then the INFORMED table targets by that learned power. Result: the POWER ranking
    # matches the player's ordering, the strongest deck (Sauron) is correctly ganged up on instead of
    # being the invisible quiet shark, and a never-wins aggro deck (Frodo) is NOT the turn-1 archenemy.
    from mtg_analyzer.simulation.battle import simulate_metagame

    profiles = _lotr_profiles()
    saved_w = P.WINRATE_PRIOR_W
    res = simulate_metagame(profiles, pod_size=4, games=300, seed=1, iterations=4)

    # No global side effects — the module weight and every profile's prior are restored.
    assert P.WINRATE_PRIOR_W == saved_w
    assert all(p.win_prior == 0.0 for p in profiles)
    assert res.pods == 15 and res.pod_size == 4 and res.informed

    by = {d.name: d for d in res.decks}
    # Learned POWER levels track realised strength: proven winner positive, never-wins aggro negative.
    assert by["Sauron"].power_level > 0
    assert by["Frodo and Sam"].power_level < 0 and by["Sméagol"].power_level < 0
    # The headline ranking is by power and matches the player's ordering closely.
    power_order = [d.name for d in res.decks]  # already sorted strongest → weakest
    assert _rank_distance(power_order, LOTR_RANKING) <= 2
    assert by["Sauron"].power_rank <= 2
    # Informed-table archenemy tracks POWER, not flash: the strongest decks draw far more heat than the
    # weak aggro decks (the old failure — Frodo as the 84% archenemy, Sauron at 0% — is gone).
    assert by["Sauron"].archenemy_rate > by["Frodo and Sam"].archenemy_rate
    assert max(by["Sauron"].archenemy_rate, by["Tom Bombadil"].archenemy_rate) > 0.25

from typing import Any

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry
from mtg_analyzer.simulation import probability
from mtg_analyzer.simulation.goldfish import DeckProfile, simulate


# --- hypergeometric --------------------------------------------------------
def test_p_at_least_bounds() -> None:
    assert probability.p_at_least(36, 7, 0) == 1.0  # >=0 is certain
    p = probability.p_at_least(36, 7, 3)  # >=3 lands in 7 from 99 w/ 36 lands
    assert 0.45 < p < 0.55
    assert probability.p_at_least(99, 7, 7) == 1.0  # all 99 are successes


def test_p_see_by_turn_increases() -> None:
    t3 = probability.p_see_by_turn(1, 3, on_play=True)
    t6 = probability.p_see_by_turn(1, 6, on_play=True)
    assert 0 < t3 < t6 < 1


# --- deck profile ----------------------------------------------------------
def _card(name: str, **kw: Any) -> Card:
    base = {"id": name, "name": name, "layout": "normal", "cmc": 3.0,
            "type_line": "Creature", "oracle_text": "", "color_identity": [],
            "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def _entry(card: Card, qty: int, section: str = "main") -> ResolvedEntry:
    return ResolvedEntry(quantity=qty, section=section, requested_name=card.name, card=card)


def _deck() -> ResolvedDeck:
    cmd = _card("Cmdr", type_line="Legendary Creature", cmc=3.0)
    land = _card("Waste", type_line="Basic Land — Waste", cmc=0.0)
    rock = _card("Rock", type_line="Artifact", cmc=2.0, oracle_text="{T}: Add {C}.")
    filler = _card("Filler", type_line="Creature", cmc=3.0)
    return ResolvedDeck(name="Sim", entries=[
        _entry(cmd, 1, "commander"), _entry(land, 40), _entry(rock, 9), _entry(filler, 50),
    ])


def test_deck_profile_counts() -> None:
    p = DeckProfile.from_resolved(_deck())
    assert p.size == 99
    assert p.land_count == 40
    assert p.ramp_count == 9
    assert p.commander_cmc == 3


# --- simulation ------------------------------------------------------------
def test_simulate_metrics_are_sane() -> None:
    r = simulate(_deck(), games=3000, seed=1)
    assert r.land_count == 40 and r.ramp_count == 9 and r.commander_cmc == 3
    # avg lands in opening 7 ~ 7 * 40/99 = 2.83
    assert 2.5 < r.avg_lands_in_opening < 3.2
    assert r.p_three_plus_lands_exact == round(
        probability.p_at_least(40, 7, 3, deck_size=99), 3
    )
    assert 0.0 <= r.p_keepable_hand <= 1.0
    assert r.commander_turn is not None
    # a 3-MV commander with 40 lands should land well before turn 15
    assert r.commander_turn.median is not None and r.commander_turn.median <= 5


def test_simulation_is_deterministic() -> None:
    assert simulate(_deck(), games=1000, seed=7) == simulate(_deck(), games=1000, seed=7)

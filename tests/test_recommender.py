"""Recommender tests — pure build_recommendations with injected EDHREC data (no network)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry
from mtg_analyzer.models.simulation import CommanderTurnStats, SimResult
from mtg_analyzer.recommend.edhrec import EdhrecCard, slugify
from mtg_analyzer.recommend.recommender import apply_swaps, build_recommendations

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CardDatabase]:
    database = CardDatabase(tmp_path / "test.db")
    database.ingest_cards(FIXTURES / "oracle_cards_sample.json")
    yield database
    database.close()


def make_card(name: str, **kw: Any) -> Card:
    base = {"id": name, "name": name, "layout": "normal", "cmc": 2.0,
            "type_line": "Creature", "oracle_text": "", "color_identity": ["R"],
            "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def entry(card: Card, *, section: str = "main") -> ResolvedEntry:
    return ResolvedEntry(quantity=1, section=section, requested_name=card.name, card=card)


def _deck() -> ResolvedDeck:
    cmd = make_card("Cmdr", type_line="Legendary Creature — Orc", color_identity=["R"])
    bomb = make_card("Bomb", game_changer=True)
    filler = make_card("Filler")
    return ResolvedDeck(name="Test", entries=[
        entry(cmd, section="commander"), entry(bomb), entry(filler),
    ])


def test_slugify() -> None:
    assert slugify("Sauron, the Dark Lord") == "sauron-the-dark-lord"
    assert slugify("Atraxa, Praetors' Voice") == "atraxa-praetors-voice"


def test_adds_fill_gaps_and_respect_identity(db: CardDatabase) -> None:
    deck = _deck()
    edhrec = [
        EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100),
        EdhrecCard(name="Llanowar Elves", synergy=0.5, inclusion=90, potential_decks=100),
    ]
    recs = build_recommendations(deck, analyze(deck), edhrec, db)
    add_names = [a.name for a in recs.adds]
    assert "Sol Ring" in add_names  # colorless ramp fills the ramp gap
    sol = next(a for a in recs.adds if a.name == "Sol Ring")
    assert sol.category == "ramp" and sol.price_usd == 1.49
    assert "Llanowar Elves" not in add_names  # green, outside the [R] commander identity


def test_cuts_protect_game_changers(db: CardDatabase) -> None:
    deck = _deck()
    edhrec = [EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100)]
    recs = build_recommendations(deck, analyze(deck), edhrec, db)
    cut_names = {c.name for c in recs.cuts}
    assert "Bomb" not in cut_names  # game_changer is protected
    assert recs.cuts  # Filler is a valid cut candidate


def test_budget_caps_buy_cost(db: CardDatabase) -> None:
    deck = _deck()
    edhrec = [EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100)]
    recs = build_recommendations(deck, analyze(deck), edhrec, db, budget=0.0)
    assert recs.buy_cost <= 0.0  # $1.49 Sol Ring dropped to fit a $0 budget
    assert "Sol Ring" not in [a.name for a in recs.adds]


def test_cold_start_no_edhrec_data(db: CardDatabase) -> None:
    deck = _deck()
    recs = build_recommendations(deck, analyze(deck), [], db)
    assert recs.adds == []  # no candidates without EDHREC data
    assert any("cold-start" in n for n in recs.notes)


def _sim(commander_cmc: int, median_turn: int) -> SimResult:
    return SimResult(
        games=100, on_play=True, land_count=37, ramp_count=8, commander_cmc=commander_cmc,
        avg_lands_in_opening=2.6, p_keepable_hand=0.8, p_three_plus_lands_exact=0.5,
        avg_mulligans=0.3, flood_rate=0.02, screw_rate=0.05,
        commander_turn=CommanderTurnStats(mean=float(median_turn), median=median_turn,
                                          p90=median_turn + 3, never_pct=1.0),
        notes=[],
    )


def test_sim_slow_commander_prioritizes_ramp(db: CardDatabase) -> None:
    deck = _deck()
    edhrec = [EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100)]
    recs = build_recommendations(deck, analyze(deck), edhrec, db, sim=_sim(commander_cmc=2,
                                                                          median_turn=6))
    assert any("prioritizing ramp" in n for n in recs.notes)  # lateness 4 -> boost + note


def test_apply_swaps_removes_cut_and_inserts_add(db: CardDatabase) -> None:
    deck = _deck()
    edhrec = [EdhrecCard(name="Sol Ring", synergy=0.3, inclusion=80, potential_decks=100)]
    recs = build_recommendations(deck, analyze(deck), edhrec, db)
    new_deck = apply_swaps(deck, recs, db)
    names = {e.card.name for e in new_deck.entries if e.card}
    assert "Sol Ring" in names  # add inserted
    cut_names = {c.name for c in recs.cuts}
    assert not (cut_names & {e.requested_name for e in new_deck.mainboard})  # cuts removed

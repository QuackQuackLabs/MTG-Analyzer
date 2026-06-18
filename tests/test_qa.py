from collections.abc import Iterator
from pathlib import Path

import pytest

from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.rules.comprehensive import parse_rules_text
from mtg_analyzer.rules.qa import explain_card, explain_interaction, search_knowledge
from mtg_analyzer.rules.store import RulesStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[CardDatabase]:
    database = CardDatabase(tmp_path / "cards.db")
    database.ingest_cards(FIXTURES / "oracle_cards_sample.json")
    database.ingest_rulings(FIXTURES / "rulings_sample.json")
    yield database
    database.close()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[RulesStore]:
    s = RulesStore(tmp_path / "rules.db")
    s.ingest(parse_rules_text((FIXTURES / "comp_rules_sample.txt").read_text()))
    yield s
    s.close()


def test_explain_card_gathers_text_and_rulings(db: CardDatabase, store: RulesStore) -> None:
    k = explain_card("Sol Ring", db, store)
    assert k is not None
    assert "Add" in k.text
    assert len(k.rulings) == 1
    assert "colorless mana" in k.rulings[0].comment
    assert k.combos == []  # filled later (network)


def test_explain_card_unknown_returns_none(db: CardDatabase, store: RulesStore) -> None:
    assert explain_card("Not A Real Card", db, store) is None


def test_search_knowledge_hits_rules_and_glossary(store: RulesStore) -> None:
    res = search_knowledge("trample combat damage", store)
    assert any(r.number == "702.19" for r in res.rules)
    assert any(g.term == "Trample" for g in res.glossary)


def test_explain_interaction_gathers_both_cards(db: CardDatabase, store: RulesStore) -> None:
    inter = explain_interaction("Sol Ring", "Delver of Secrets", db, store)
    assert {c.name for c in inter.cards} == {"Sol Ring", "Delver of Secrets // Insectile Aberration"}
    assert all(len(c.rulings) >= 1 for c in inter.cards)  # both have a fixture ruling
    assert not inter.notes  # both resolved


def test_explain_interaction_flags_missing_card(db: CardDatabase, store: RulesStore) -> None:
    inter = explain_interaction("Sol Ring", "Nonexistent", db, store)
    assert len(inter.cards) == 1
    assert inter.notes and "Nonexistent" in inter.notes[0]

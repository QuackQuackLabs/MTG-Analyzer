from collections.abc import Iterator
from pathlib import Path

import pytest

from mtg_analyzer.rules.comprehensive import parse_rules_text
from mtg_analyzer.rules.store import RulesStore

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "comp_rules_sample.txt").read_text(encoding="utf-8")


def test_parse_effective_date() -> None:
    doc = parse_rules_text(SAMPLE)
    assert doc.effective_date == "February 27, 2026"


def test_parse_skips_contents_block() -> None:
    doc = parse_rules_text(SAMPLE)
    # Section "1" and category "100" appear in BOTH the Contents list and the body;
    # they must be captured exactly once (Contents skipped).
    assert [r.number for r in doc.rules].count("1") == 1
    assert [r.number for r in doc.rules].count("100") == 1


def test_parse_rule_hierarchy() -> None:
    doc = parse_rules_text(SAMPLE)
    by_num = {r.number: r for r in doc.rules}

    assert by_num["1"].kind == "section" and by_num["1"].text == "Game Concepts"
    assert by_num["100"].kind == "category" and by_num["100"].text == "General"

    rule = by_num["100.1"]
    assert rule.kind == "rule"
    assert rule.text.startswith("These Magic rules apply")
    assert rule.section == "1" and rule.parent == "100"

    sub = by_num["100.1a"]
    assert sub.parent == "100.1"  # subrule parented to its base rule
    assert sub.section == "1"

    # Section context carries across categories
    assert by_num["702.19a"].section == "7"
    assert by_num["702.19a"].parent == "702.19"


def test_parse_glossary() -> None:
    doc = parse_rules_text(SAMPLE)
    terms = {g.term: g.definition for g in doc.glossary}
    assert set(terms) == {"Trample", "Commander"}
    assert "combat damage" in terms["Trample"]


@pytest.fixture
def store(tmp_path: Path) -> Iterator[RulesStore]:
    s = RulesStore(tmp_path / "rules.db")
    s.ingest(parse_rules_text(SAMPLE), source="fixture")
    yield s
    s.close()


def test_store_counts_and_meta(store: RulesStore) -> None:
    assert store.rule_count() == 6  # 100.1, 100.1a, 100.2, 100.10, 702.19, 702.19a
    assert store.glossary_count() == 2
    assert store.effective_date() == "February 27, 2026"


def test_store_get_rule_with_subrules(store: RulesStore) -> None:
    rules = store.get_rule_with_subrules("702.19")
    assert [r.number for r in rules] == ["702.19", "702.19a"]


def test_subrule_expansion_excludes_sibling_rules(store: RulesStore) -> None:
    # "100.1" must expand to 100.1 + 100.1a only — NOT 100.10 (a sibling) or 100.2.
    rules = store.get_rule_with_subrules("100.1")
    assert [r.number for r in rules] == ["100.1", "100.1a"]


def test_store_search_rules(store: RulesStore) -> None:
    hits = store.search_rules("trample combat damage")
    assert hits
    assert any("Trample" in r.text for r in hits)


def test_store_glossary_lookup_is_case_insensitive(store: RulesStore) -> None:
    entry = store.get_glossary("trample")
    assert entry is not None
    assert entry.term == "Trample"


def test_store_search_glossary(store: RulesStore) -> None:
    hits = store.search_glossary("legendary creature commander")
    assert any(h.term == "Commander" for h in hits)

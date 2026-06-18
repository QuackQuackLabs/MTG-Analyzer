from typing import Any

from mtg_analyzer.analysis.categorize import (
    BOARD_WIPE,
    COUNTER,
    DRAW,
    LAND,
    RAMP,
    REMOVAL,
    categorize,
)
from mtg_analyzer.analysis.report import analyze
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry


def make_card(name: str, **kw: Any) -> Card:
    base = {"id": name, "name": name, "layout": "normal", "cmc": 2.0,
            "type_line": "Creature", "oracle_text": "", "color_identity": [],
            "legalities": {"commander": "legal"}}
    base.update(kw)
    return Card.model_validate(base)


def entry(card: Card, *, section: str = "main", qty: int = 1) -> ResolvedEntry:
    return ResolvedEntry(quantity=qty, section=section, requested_name=card.name, card=card)


# --- categorize ------------------------------------------------------------
def test_categorize_by_oracle_text() -> None:
    assert RAMP in categorize(make_card("Rock", type_line="Artifact",
                                        oracle_text="{T}: Add {C}{C}."))
    assert RAMP in categorize(make_card("Signet", type_line="Artifact",
                                        oracle_text="{T}: Add one mana of any color."))
    assert DRAW in categorize(make_card("Draw", oracle_text="Draw two cards."))
    assert REMOVAL in categorize(make_card("Kill", oracle_text="Destroy target creature."))
    assert COUNTER in categorize(make_card("Stop", oracle_text="Counter target spell."))
    wipe = categorize(make_card("Wrath", oracle_text="Destroy all creatures."))
    assert BOARD_WIPE in wipe and REMOVAL not in wipe  # wipe is not also spot removal


def test_categorize_land_only() -> None:
    # A land that taps for mana is a land, not also ramp.
    cats = categorize(make_card("Tower", type_line="Land", oracle_text="{T}: Add one mana."))
    assert cats == {LAND}


# --- validation ------------------------------------------------------------
def _deck(entries: list[ResolvedEntry]) -> ResolvedDeck:
    return ResolvedDeck(name="Test", entries=entries)


def test_color_identity_violation_flagged() -> None:
    cmd = make_card("Cmdr", type_line="Legendary Creature — Elf", color_identity=["U", "B"])
    ok = make_card("Blue Card", color_identity=["U"])
    bad = make_card("Green Card", color_identity=["G"])
    report = analyze(_deck([entry(cmd, section="commander"), entry(ok), entry(bad)]))
    assert report.identity == "BU"
    assert any("Green Card" in i and "color identity" in i for i in report.validation.issues)
    assert not report.validation.legal


def test_singleton_violation_and_nazgul_exemption() -> None:
    cmd = make_card("Cmdr", type_line="Legendary Creature — Elf", color_identity=["B"])
    dup = make_card("Dark Ritual", oracle_text="Add {B}{B}{B}.")
    nazgul = make_card("Nazgûl", color_identity=["B"],
                       oracle_text="A deck can have up to nine cards named Nazgûl.")
    report = analyze(_deck([
        entry(cmd, section="commander"),
        entry(dup, qty=2),       # singleton violation
        entry(nazgul, qty=9),    # allowed by its own text
    ]))
    issues = " ".join(report.validation.issues)
    assert "dark ritual" in issues.lower()
    assert "nazgûl" not in issues.lower()  # exempted


def test_card_count_and_bracket() -> None:
    cmd = make_card("Cmdr", type_line="Legendary Creature — Elf", color_identity=["U"])
    gcs = [entry(make_card(f"GC{i}", color_identity=["U"], game_changer=True)) for i in range(4)]
    report = analyze(_deck([entry(cmd, section="commander"), *gcs]))
    assert report.validation.card_count == 5  # not 100 → illegal, but count is reported
    assert any("100" in i for i in report.validation.issues)
    assert report.bracket_estimate == 4  # 4 Game Changers
    assert len(report.game_changers) == 4


def test_curve_excludes_lands() -> None:
    cmd = make_card("Cmdr", type_line="Legendary Creature", color_identity=[])
    land = make_card("Waste", type_line="Land", cmc=0.0)
    three = make_card("Spell", cmc=3.0)
    report = analyze(_deck([entry(cmd, section="commander"), entry(land), entry(three)]))
    curve = {b.cmc: b.count for b in report.curve}
    assert curve[3] == 1 and curve[0] == 0  # land excluded from the curve

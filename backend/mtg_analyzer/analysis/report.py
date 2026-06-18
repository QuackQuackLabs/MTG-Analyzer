"""Build a DeckReport from a ResolvedDeck: validation + composition + curve + bracket.

Operates entirely on the local card data — Commander legality and the "Game Changer"
list come from each card's Scryfall fields (`legalities.commander`, `game_changer`), so
nothing is hard-coded. Combo-aware bracket refinement arrives with Phase 4.
"""

from __future__ import annotations

import re

from mtg_analyzer.analysis.categorize import (
    BOARD_WIPE,
    COUNTER,
    DRAW,
    LAND,
    RAMP,
    REMOVAL,
    TUTOR,
    categorize,
)
from mtg_analyzer.models.analysis import CategoryCount, CurveBucket, DeckReport, Validation
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry

# Command Zone–style targets (see commander-format skill). Tutor/counter are informational.
TARGETS: dict[str, int] = {LAND: 37, RAMP: 10, DRAW: 10, REMOVAL: 10, BOARD_WIPE: 3}
_REPORTED = [LAND, RAMP, DRAW, REMOVAL, BOARD_WIPE, COUNTER, TUTOR]

_BASIC_LAND_NAMES = {"plains", "island", "swamp", "mountain", "forest", "wastes"}
# Cards that override singleton ("A deck can have any number of / up to N cards named …"):
# Relentless Rats, Shadowborn Apostle, Persistent Petitioners, Dragon's Approach, Nazgûl,
# Seven Dwarves, etc.
_SINGLETON_OVERRIDE_RE = re.compile(r"a deck can have (any number of|up to \w+) cards named")


def _singleton_exempt(entry: ResolvedEntry) -> bool:
    """Basic lands and cards whose own text overrides the singleton rule."""
    card = entry.card
    if card and card.type_line and "basic" in card.type_line.lower():
        return True
    if card and _SINGLETON_OVERRIDE_RE.search(card.get_oracle_text().lower()):
        return True
    name = entry.requested_name.lower().removeprefix("snow-covered ")
    return name in _BASIC_LAND_NAMES


def _is_legal_commander(entry: ResolvedEntry) -> bool:
    card = entry.card
    if card is None:
        return False
    tl = (card.type_line or "").lower()
    text = card.get_oracle_text().lower()
    is_legendary_creature = "legendary" in tl and "creature" in tl
    return (is_legendary_creature or "can be your commander" in text) \
        and card.commander_legality() != "banned"


def analyze(deck: ResolvedDeck) -> DeckReport:
    commanders = deck.commanders
    main = deck.mainboard
    identity_set: set[str] = set()
    for c in commanders:
        if c.card:
            identity_set.update(c.card.color_identity)
    identity = "".join(sorted(identity_set)) or "C"

    issues, warnings = _validate(deck, commanders, main, identity_set)

    # --- composition ---
    counts: dict[str, int] = dict.fromkeys(_REPORTED, 0)
    for e in main:
        if e.card is None:
            continue
        for cat in categorize(e.card, hint=e.category):
            if cat in counts:
                counts[cat] += e.quantity
    categories = [
        CategoryCount(category=cat, count=counts[cat], target=TARGETS.get(cat, 0),
                      gap=max(0, TARGETS.get(cat, 0) - counts[cat]))
        for cat in _REPORTED
    ]

    # --- curve (nonland mainboard) ---
    curve_counts: dict[int, int] = dict.fromkeys(range(8), 0)
    for e in main:
        if e.card and "land" not in (e.card.type_line or "").lower():
            curve_counts[min(int(e.card.cmc), 7)] += e.quantity
    curve = [CurveBucket(cmc=i, count=curve_counts[i]) for i in range(8)]

    game_changers = sorted(
        e.card.name for e in (commanders + main) if e.card and e.card.game_changer
    )
    bracket, rationale = _estimate_bracket(len(game_changers), counts[TUTOR])

    return DeckReport(
        name=deck.name,
        commanders=[c.requested_name for c in commanders],
        identity=identity,
        validation=Validation(
            legal=not issues,
            card_count=deck.card_total(("commander", "main")),
            commander_identity=identity,
            issues=issues,
            warnings=warnings,
        ),
        categories=categories,
        curve=curve,
        game_changers=game_changers,
        bracket_estimate=bracket,
        bracket_rationale=rationale,
    )


def _validate(
    deck: ResolvedDeck,
    commanders: list[ResolvedEntry],
    main: list[ResolvedEntry],
    identity_set: set[str],
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []

    total = deck.card_total(("commander", "main"))
    if total != 100:
        issues.append(f"Deck has {total} cards (Commander requires exactly 100).")

    if not commanders:
        warnings.append("No commander identified — identity and legality can't be fully checked.")
    for c in commanders:
        if c.card and not _is_legal_commander(c):
            issues.append(f"{c.card.name} isn't a legal commander (not a legendary creature / "
                          "lacks 'can be your commander', or is banned).")

    # color identity ⊆ commander identity
    if commanders:
        for e in main:
            if e.card and not set(e.card.color_identity) <= identity_set:
                issues.append(f"{e.card.name} [{''.join(e.card.color_identity)}] is outside the "
                              f"commander's color identity [{''.join(sorted(identity_set)) or 'C'}].")

    # singleton (basics exempt)
    seen: dict[str, int] = {}
    for e in commanders + main:
        if _singleton_exempt(e):
            continue
        key = (e.card.name if e.card else e.requested_name).lower()
        seen[key] = seen.get(key, 0) + e.quantity
    for name, n in seen.items():
        if n > 1:
            issues.append(f"{n} copies of a nonbasic card ({name}) — Commander is singleton.")

    # banned
    for e in commanders + main:
        if e.card and e.card.commander_legality() == "banned":
            issues.append(f"{e.card.name} is banned in Commander.")

    if deck.unresolved:
        warnings.append(f"{len(deck.unresolved)} card(s) couldn't be resolved and were skipped "
                        "in analysis.")
    return issues, warnings


def _estimate_bracket(game_changers: int, tutors: int) -> tuple[int, str]:
    """Rough 1–5 bracket. Refined by combo detection in Phase 4."""
    if game_changers >= 4:
        return 4, f"{game_changers} Game Changers (bracket 4+ allows unrestricted Game Changers)."
    if game_changers >= 1:
        return 3, f"{game_changers} Game Changer(s) (bracket 3 allows up to 3)."
    if tutors >= 4:
        return 3, f"No Game Changers but {tutors} tutors — tuned consistency suggests bracket 3."
    return 2, "No Game Changers and few tutors — around precon/Core (bracket 2). Approximate; " \
              "combo detection (Phase 4) will refine this."

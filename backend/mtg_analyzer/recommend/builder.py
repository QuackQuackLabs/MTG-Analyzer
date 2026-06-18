"""Construct a Commander deck for a chosen commander, preferring owned cards.

Greedy build: pool = EDHREC recommendations (synergy) ∪ the user's owned cards, all
filtered to the commander's color identity + Commander-legal. Fill the functional
category targets (owned first, then synergy), then payoffs, then a manabase from owned
nonbasic lands + basics. Cards that aren't owned go on the buy list (budget-capped).

Lands are kept simple (owned nonbasics + basics); upgrading the manabase with
fetches/duals is a future refinement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_analyzer.analysis.categorize import (
    BOARD_WIPE,
    DRAW,
    LAND,
    RAMP,
    REMOVAL,
    categorize,
)
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.build import BuildCard, BuiltDeck
from mtg_analyzer.models.card import Card
from mtg_analyzer.recommend.edhrec import EdhrecCard

DECK_SIZE = 99
LAND_TARGET = 37
_CATEGORY_TARGETS = [(RAMP, 10), (DRAW, 10), (REMOVAL, 10), (BOARD_WIPE, 3)]
_BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


@dataclass
class _Cand:
    card: Card
    cats: set[str]
    synergy: float
    owned: bool
    price: float | None
    assigned: str | None = field(default=None)

    @property
    def is_land(self) -> bool:
        return LAND in self.cats

    @property
    def is_basic(self) -> bool:
        return "basic" in (self.card.type_line or "").lower()


def build_deck(
    commander: Card,
    owned: set[str],
    db: CardDatabase,
    edhrec_cards: list[EdhrecCard],
    *,
    budget: float | None = None,
    owned_only: bool = False,
) -> BuiltDeck:
    identity = set(commander.color_identity)
    notes: list[str] = []

    candidates: dict[str, _Cand] = {}

    def consider(card: Card | None, synergy: float) -> None:
        if card is None or not card.oracle_id or card.oracle_id in candidates:
            return
        if card.oracle_id == commander.oracle_id or not card.is_commander_legal():
            return
        if not set(card.color_identity) <= identity:
            return
        candidates[card.oracle_id] = _Cand(
            card=card, cats=categorize(card), synergy=synergy,
            owned=card.oracle_id in owned, price=db.min_usd(card.oracle_id),
        )

    for ec in edhrec_cards:
        consider(db.get_by_name(ec.name), ec.synergy or 0.0)
    for oid in owned:  # owned cards EDHREC didn't surface
        consider(db.get_by_oracle_id(oid), 0.0)

    chosen: list[_Cand] = []
    used: set[str] = set()
    buy_cost = 0.0

    def take(pool: list[_Cand], n: int, category: str) -> int:
        nonlocal buy_cost
        ranked = sorted(pool, key=lambda c: (c.owned, c.synergy), reverse=True)
        taken = 0
        for c in ranked:
            if taken >= n:
                break
            if c.card.oracle_id in used:
                continue
            if owned_only and not c.owned:
                continue
            if budget is not None and not c.owned and c.price and buy_cost + c.price > budget:
                continue
            used.add(c.card.oracle_id)  # type: ignore[arg-type]
            c.assigned = category
            chosen.append(c)
            taken += 1
            if not c.owned and c.price:
                buy_cost += c.price
        return taken

    # 1) functional categories
    for cat, target in _CATEGORY_TARGETS:
        pool = [c for c in candidates.values() if cat in c.cats and not c.is_land]
        got = take(pool, target, cat)
        if got < target:
            notes.append(f"{cat}: only {got}/{target} found"
                         + (" in your collection" if owned_only else ""))

    # 2) payoffs / synergy to fill the nonland slots
    nonland_slots = DECK_SIZE - LAND_TARGET
    payoff_pool = [c for c in candidates.values()
                   if not c.is_land and c.card.oracle_id not in used]
    take(payoff_pool, nonland_slots - len(chosen), "payoff")

    # 3) manabase: owned nonbasic lands, then basics
    cards = [
        BuildCard(name=c.card.name, category=c.assigned, owned=c.owned, price_usd=c.price)
        for c in chosen
    ]
    land_cards, land_notes = _build_manabase(candidates, used, identity, owned_only)
    cards.extend(land_cards)
    notes.extend(land_notes)

    total = sum(c.quantity for c in cards) + 1  # + commander
    if total < 100:
        notes.append(f"Deck is {total}/100 — not enough eligible cards"
                     + (" you own (try without --owned-only)." if owned_only else "."))

    category_counts: dict[str, int] = {}
    for c in cards:
        category_counts[c.category or "payoff"] = (
            category_counts.get(c.category or "payoff", 0) + c.quantity
        )

    basics = set(_BASICS.values()) | {"Wastes"}
    return BuiltDeck(
        commander=commander.name, identity="".join(sorted(identity)) or "C",
        cards=cards, total_cards=total,
        owned_count=sum(1 for c in cards if c.owned and c.name not in basics),
        buy_count=sum(1 for c in cards if not c.owned),
        buy_cost=round(buy_cost, 2), category_counts=category_counts, notes=notes,
    )


def _build_manabase(
    candidates: dict[str, _Cand], used: set[str], identity: set[str], owned_only: bool
) -> tuple[list[BuildCard], list[str]]:
    owned_lands = sorted(
        (c for c in candidates.values()
         if c.is_land and not c.is_basic and c.owned and c.card.oracle_id not in used),
        key=lambda c: c.synergy, reverse=True,
    )
    chosen_lands = owned_lands[:LAND_TARGET]
    cards = [BuildCard(name=c.card.name, category="land", owned=True, price_usd=c.price)
             for c in chosen_lands]

    remaining = LAND_TARGET - len(cards)
    notes: list[str] = []
    if remaining > 0:
        colors = sorted(identity) or ["C"]
        per = remaining // len(colors)
        extra = remaining % len(colors)
        for i, color in enumerate(colors):
            qty = per + (1 if i < extra else 0)
            if qty:
                cards.append(BuildCard(name=_BASICS.get(color, "Wastes"), quantity=qty,
                                       category="land", owned=True, price_usd=0.0))
        notes.append(f"Manabase: {len(chosen_lands)} owned nonbasic land(s) + {remaining} basics. "
                     "Upgrading with dual/fetch lands is a future refinement.")
    return cards, notes

"""Rules / interaction Q&A: retrieve grounded source material.

Pure (no network): combines the local card DB (oracle text + rulings) with the
Comprehensive Rules store (rule lookup + FTS + glossary). Combo data is added by the
caller (it needs the network). See models/qa.py for the design rationale.
"""

from __future__ import annotations

from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.qa import CardKnowledge, Interaction, RulesSearch, Ruling
from mtg_analyzer.rules.store import RulesStore


def explain_card(name: str, db: CardDatabase, store: RulesStore) -> CardKnowledge | None:
    card = db.get_by_name(name)
    if card is None:
        return None

    rulings = (
        [Ruling(source=r.source, published_at=r.published_at, comment=r.comment)
         for r in db.get_rulings(card.oracle_id)]
        if card.oracle_id else []
    )

    rules = []
    glossary = []
    seen: set[str] = set()
    for kw in card.keywords:
        for r in store.search_rules(kw, limit=1):
            if r.number not in seen:
                rules.append(r)
                seen.add(r.number)
        if (g := store.get_glossary(kw)) is not None:
            glossary.append(g)

    return CardKnowledge(
        name=card.name, type_line=card.type_line, text=card.get_oracle_text(),
        keywords=card.keywords, rulings=rulings, rules=rules, glossary=glossary, combos=[],
    )


def search_knowledge(query: str, store: RulesStore) -> RulesSearch:
    """Free-text search across the Comprehensive Rules and glossary."""
    return RulesSearch(query=query, rules=store.search_rules(query, limit=8),
                       glossary=store.search_glossary(query, limit=5))


def explain_interaction(
    name_a: str, name_b: str, db: CardDatabase, store: RulesStore
) -> Interaction:
    cards = [k for k in (explain_card(name_a, db, store), explain_card(name_b, db, store))
             if k is not None]
    notes: list[str] = []
    if len(cards) < 2:
        found = {k.name for k in cards}
        missing = [n for n in (name_a, name_b) if n not in found]
        notes.append(f"Couldn't resolve: {', '.join(missing)}.")

    # Rules relevant to the union of both cards' keywords.
    keywords = {kw for c in cards for kw in c.keywords}
    rules = store.search_rules(" ".join(keywords), limit=6) if keywords else []
    return Interaction(cards=cards, rules=rules, glossary=[], combos=[], notes=notes)

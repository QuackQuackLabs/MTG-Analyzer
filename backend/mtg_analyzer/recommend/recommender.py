"""Blended deck recommender: which cards to cut and what to add.

Adds come from EDHREC's commander recommendations (synergy/inclusion), resolved to our
card DB and classified into the deck's functional gaps (ramp/draw/removal/board_wipe).
Cuts are the deck's nonland cards with the lowest play-rate in this commander's decks
(per EDHREC) — data-driven candidates, not gospel (flavor/personal picks may be kept).

`build_recommendations` is pure (no network): it takes already-fetched EDHREC cards, so
it's fully unit-testable. The CLI/API fetches EDHREC and calls this.
"""

from __future__ import annotations

import re

from mtg_analyzer.analysis.categorize import BOARD_WIPE, DRAW, RAMP, REMOVAL, categorize
from mtg_analyzer.data.db import CardDatabase
from mtg_analyzer.models.analysis import DeckReport
from mtg_analyzer.models.deck import ResolvedDeck, ResolvedEntry
from mtg_analyzer.models.recommendation import AddSuggestion, CutSuggestion, Recommendations
from mtg_analyzer.models.simulation import SimResult
from mtg_analyzer.recommend.edhrec import EdhrecCard

_GAP_CATEGORIES = (RAMP, DRAW, REMOVAL, BOARD_WIPE)
_GENERAL_UPGRADES = 3  # high-synergy adds beyond strict gap-filling
# Never propose cutting these — they're intentional or format-defining.
_SINGLETON_OVERRIDE_RE = re.compile(r"a deck can have (any number of|up to \w+) cards named")


def build_recommendations(
    deck: ResolvedDeck,
    report: DeckReport,
    edhrec_cards: list[EdhrecCard],
    db: CardDatabase,
    *,
    owned: set[str] | None = None,
    budget: float | None = None,
    sim: SimResult | None = None,
) -> Recommendations:
    owned = owned or set()
    notes: list[str] = []
    ramp_boost = _consistency_ramp_boost(sim, report, notes)

    in_deck_names = {
        (e.card.name if e.card else e.requested_name).lower()
        for e in deck.entries if e.section in ("commander", "main")
    }
    in_deck_oracles = {e.card.oracle_id for e in deck.entries if e.card and e.card.oracle_id}
    identity = set(report.identity if report.identity != "C" else "")
    edhrec_by_name = {c.name.lower(): c for c in edhrec_cards}

    if not edhrec_cards:
        notes.append("No EDHREC data for this commander (cold-start) — add suggestions skipped. "
                     "Cuts fall back to gap analysis only.")

    gaps = {c.category: c.gap for c in report.categories
            if c.category in _GAP_CATEGORIES and c.gap > 0}

    # --- candidate adds: EDHREC cards not already in the deck, in color identity ---
    candidates: list[tuple[AddSuggestion, float]] = []  # (suggestion, score)
    for ec in edhrec_cards:
        if ec.name.lower() in in_deck_names:
            continue
        card = db.get_by_name(ec.name)
        if card is None or card.oracle_id in in_deck_oracles:
            continue
        if not set(card.color_identity) <= identity:
            continue
        cats = categorize(card)
        gap_cat = next((c for c in _GAP_CATEGORIES if c in cats and c in gaps), None)
        price = db.min_usd(card.oracle_id) if card.oracle_id else None
        is_owned = bool(card.oracle_id and card.oracle_id in owned)
        synergy = ec.synergy or 0.0
        # Score: gap demand dominates, then synergy, then popularity; owned is "free".
        # Consistency: when the sim shows a slow commander / screw, ramp is worth more.
        gap_demand = (gaps.get(gap_cat, 0) if gap_cat else 0) + (ramp_boost if gap_cat == RAMP else 0)
        score = (gap_demand * 2.0 if gap_cat else 0.0) + max(synergy, 0.0) * 3 \
            + (ec.inclusion_rate or 0.0) + (0.5 if is_owned else 0.0)
        reason_bits = []
        if gap_cat:
            reason_bits.append(f"fills {gap_cat} gap")
        if synergy > 0:
            reason_bits.append(f"+{synergy:.0%} synergy")
        if ec.inclusion_rate:
            reason_bits.append(f"{ec.inclusion_rate:.0%} of decks")
        candidates.append((
            AddSuggestion(
                name=card.name, oracle_id=card.oracle_id, category=gap_cat, synergy=synergy,
                inclusion_rate=ec.inclusion_rate, price_usd=price, owned=is_owned,
                reason=", ".join(reason_bits) or "popular in this archetype",
            ),
            score,
        ))

    candidates.sort(key=lambda t: t[1], reverse=True)

    # Select: fill each gap first, then a few general high-synergy upgrades.
    adds: list[AddSuggestion] = []
    picked: set[str] = set()
    for cat, gap in sorted(gaps.items(), key=lambda kv: kv[1], reverse=True):
        for sug, _ in candidates:
            if len([a for a in adds if a.category == cat]) >= gap:
                break
            if sug.category == cat and sug.name not in picked:
                adds.append(sug)
                picked.add(sug.name)
    general = 0  # a few top-synergy upgrades beyond strict gap-filling
    for sug, _ in candidates:
        if general >= _GENERAL_UPGRADES:
            break
        if sug.name not in picked:
            adds.append(sug)
            picked.add(sug.name)
            general += 1

    if budget is not None:
        adds = _fit_budget(adds, budget, notes)

    cuts = _pick_cuts(deck, edhrec_by_name, n=len(adds))
    buy_cost = round(sum(a.price_usd or 0.0 for a in adds if not a.owned), 2)
    if not owned:
        notes.append("Import your collection (`mtg inventory import`) for owned-aware suggestions "
                     "and an accurate buy list.")
    notes.append("Cuts are EDHREC play-rate signals — keep intentional flavor/personal picks.")

    return Recommendations(commander=", ".join(report.commanders) or "(unknown)",
                           adds=adds, cuts=cuts, buy_cost=buy_cost, notes=notes)


def _consistency_ramp_boost(
    sim: SimResult | None, report: DeckReport, notes: list[str]
) -> int:
    """Extra ramp priority derived from simulation (slow commander / mana screw)."""
    if sim is None:
        return 0
    boost = 0
    ct = sim.commander_turn
    if ct and ct.median is not None and sim.commander_cmc is not None:
        lateness = ct.median - sim.commander_cmc
        if lateness >= 2:
            boost += lateness
            notes.append(f"Simulation: commander lands ~turn {ct.median} (MV {sim.commander_cmc}) — "
                         "prioritizing ramp to deploy it sooner.")
    if sim.screw_rate > 0.12:
        boost += 1
        notes.append(f"Simulation: {sim.screw_rate:.0%} mana-screw rate — favoring ramp/fixing.")
    return boost


def apply_swaps(deck: ResolvedDeck, recs: Recommendations, db: CardDatabase) -> ResolvedDeck:
    """Return a new deck with the recommended cuts removed and adds inserted (for before/after sim)."""
    to_cut = {c.name.lower() for c in recs.cuts}
    cut_done: set[str] = set()
    kept: list[ResolvedEntry] = []
    for e in deck.entries:
        name = (e.card.name if e.card else e.requested_name).lower()
        if e.section == "main" and name in to_cut and name not in cut_done:
            cut_done.add(name)  # remove one copy (cut candidates are singleton nonbasics)
            continue
        kept.append(e)
    for a in recs.adds:
        card = db.get_by_name(a.name)
        if card:
            kept.append(ResolvedEntry(quantity=1, section="main", requested_name=a.name, card=card))
    return ResolvedDeck(name=deck.name, entries=kept)


def _fit_budget(adds: list[AddSuggestion], budget: float, notes: list[str]) -> list[AddSuggestion]:
    """Drop the lowest-priority not-owned adds until the buy cost fits the budget."""
    kept = list(adds)
    while sum(a.price_usd or 0.0 for a in kept if not a.owned) > budget and kept:
        # remove the most expensive not-owned add at the tail (lowest priority)
        for i in range(len(kept) - 1, -1, -1):
            if not kept[i].owned and kept[i].price_usd:
                removed = kept.pop(i)
                notes.append(f"Skipped {removed.name} (${removed.price_usd:.2f}) to fit budget.")
                break
        else:
            break
    return kept


def _pick_cuts(
    deck: ResolvedDeck, edhrec_by_name: dict[str, EdhrecCard], n: int
) -> list[CutSuggestion]:
    """The n nonland deck cards least played in this commander's EDHREC decks."""
    scored: list[tuple[float, CutSuggestion]] = []
    for e in deck.mainboard:
        card = e.card
        if card is None or "land" in (card.type_line or "").lower():
            continue
        # Protect bracket-defining and intentional-theme cards from cut suggestions.
        if card.game_changer or _SINGLETON_OVERRIDE_RE.search(card.get_oracle_text().lower()):
            continue
        ec = edhrec_by_name.get(card.name.lower())
        rate = ec.inclusion_rate if ec else None
        reason = (f"{rate:.0%} of {deck.name or 'similar'} decks run it"
                  if rate is not None else "below EDHREC's play-rate cutoff for this commander")
        scored.append((rate if rate is not None else -1.0,
                       CutSuggestion(name=card.name, oracle_id=card.oracle_id,
                                     inclusion_rate=rate, reason=reason)))
    scored.sort(key=lambda t: t[0])  # lowest play-rate first
    return [c for _, c in scored[:n]]

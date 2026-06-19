"""Compose a pilot's strategy guide (markdown) for a deck from its grounded data.

Pulls together the validation/composition analysis, combos present (with their lines),
the goldfish mulligan/curve stats, and the commander's top EDHREC-synergy cards that the
deck actually runs — then renders a practical 1-page guide. Facts are grounded; the
framing is templated from real signals (no invented strategy).
"""

from __future__ import annotations

from mtg_analyzer.models.analysis import DeckReport
from mtg_analyzer.models.combo import Combo
from mtg_analyzer.models.deck import ResolvedDeck
from mtg_analyzer.models.simulation import SimResult
from mtg_analyzer.recommend.edhrec import EdhrecCard


def build_guide(
    deck: ResolvedDeck,
    report: DeckReport,
    sim: SimResult | None,
    combos: list[Combo],
    edhrec: list[EdhrecCard],
) -> str:
    commanders = ", ".join(report.commanders) or "(no commander)"
    name = (deck.name.replace("-", " ").title() if deck.name
            else (report.commanders[0] if report.commanders else "Deck"))
    cats = {c.category: c.count for c in report.categories}
    creatures = sum(
        e.quantity for e in deck.mainboard
        if e.card and "creature" in (e.card.type_line or "").lower()
        and "land" not in (e.card.type_line or "").lower()
    )

    lines = [
        f"# {name} — Pilot's Guide",
        "",
        f"**Commander:** {commanders}  ·  **Colors:** {report.identity}  "
        f"·  **Bracket ~{report.bracket_estimate}**",
        f"_{report.bracket_rationale}_",
        "",
        "## Game plan",
        _game_plan(report, combos, creatures),
        "",
        "## Win conditions",
    ]
    if combos:
        lines.append("Assemble one of your combos (see lines below):")
        lines += [f"- **{' + '.join(c.produces)}** — {', '.join(u.name for u in c.uses)}"
                  for c in combos]
    if creatures >= 25:
        lines.append(f"- **Combat** — {creatures} creatures; close games by attacking with threats.")
    if not combos and creatures < 25:
        lines.append("- Grind incremental value and win with your strongest threats.")

    if combos:
        lines += ["", "## Combo lines"]
        for c in combos:
            lines.append(f"**{' + '.join(c.produces)}** — {', '.join(u.name for u in c.uses)}")
            if c.prerequisites:
                lines.append(f"- Setup: {c.prerequisites}")
            for step in (c.description or "").splitlines():
                lines.append(f"- {step}")
            lines.append("")

    lines += ["## Mulligan", _mulligan(report, sim, cats), "", "## Sequencing", _sequencing(report, sim)]

    key = _key_cards(deck, edhrec)
    if key:
        lines += ["", "## Key cards"]
        lines += [f"- **{n}**" + (f" — {s:+.0%} synergy" if s else "") for n, s in key]

    lines += [
        "", "## At a glance",
        f"- Lands {cats.get('land', 0)} · Ramp {cats.get('ramp', 0)} · Draw {cats.get('draw', 0)} "
        f"· Removal {cats.get('removal', 0)} · Wipes {cats.get('board_wipe', 0)}",
    ]
    if sim and sim.commander_turn and sim.commander_turn.median is not None:
        lines.append(f"- Commander online ~turn {sim.commander_turn.median}; "
                     f"keepable opening hands {sim.p_keepable_hand:.0%}; screw {sim.screw_rate:.0%}")
    lines.append("\n_Auto-generated from deck analysis, simulation, and Commander Spellbook combos._")
    return "\n".join(lines)


def _game_plan(report: DeckReport, combos: list[Combo], creatures: int) -> str:
    archetype = "combo" if combos else ("creature-based" if creatures >= 25 else "midrange value")
    plan = (f"A bracket-{report.bracket_estimate} {report.identity} {archetype} deck led by "
            f"{', '.join(report.commanders) or 'your commander'}. ")
    if combos:
        plan += ("Develop mana and card advantage, protect your pieces, and win once a combo comes "
                 "together. ")
    if creatures >= 25:
        plan += "You have a strong creature base to pressure the board and pivot to combat. "
    return plan.strip()


def _mulligan(report: DeckReport, sim: SimResult | None, cats: dict[str, int]) -> str:
    base = "Keep hands with **2–4 lands** plus a way to use your early turns "
    wants = []
    if cats.get("ramp", 0) >= 8:
        wants.append("ramp")
    if report.commanders:
        wants.append("a path to your commander")
    wants.append("an impactful spell")
    text = base + "(" + ", ".join(wants) + ")."
    if sim:
        text += (f" Sim: {sim.p_keepable_hand:.0%} of opening 7s are keepable, "
                 f"~{sim.screw_rate:.0%} get mana-screwed by turn 3.")
    return text


def _sequencing(report: DeckReport, sim: SimResult | None) -> str:
    turn = sim.commander_turn.median if sim and sim.commander_turn else None
    cmc = sim.commander_cmc if sim else None
    s = "Prioritize hitting land drops and deploying ramp early. "
    if turn and cmc:
        s += f"Your commander (MV {cmc}) is typically castable around **turn {turn}**. "
    s += "Hold interaction for key threats/combo attempts; deploy threats once you can protect them."
    return s


def _key_cards(deck: ResolvedDeck, edhrec: list[EdhrecCard], limit: int = 8) -> list[tuple[str, float]]:
    syn = {c.name.lower(): (c.synergy or 0.0) for c in edhrec}
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for e in deck.mainboard:
        if not e.card:
            continue
        s = syn.get(e.card.name.lower())
        if s is not None and e.card.name not in seen:
            out.append((e.card.name, s))
            seen.add(e.card.name)
    out.sort(key=lambda t: t[1], reverse=True)
    return out[:limit]

"""Compose a pilot's strategy guide (markdown) for a deck from its grounded data.

Pulls together the validation/composition analysis, combos present (with their lines),
the goldfish mulligan/curve stats, and the commander's top EDHREC-synergy cards that the
deck actually runs — then renders a practical 1-page guide. Facts are grounded; the
framing is templated from real signals (no invented strategy).
"""

from __future__ import annotations

from collections.abc import Callable

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
    ]
    # Many commanders surface a dozen near-identical combo variants (same engine,
    # swapped payoff). Show the most popular handful; note the rest as a count.
    shown = sorted(combos, key=lambda c: (c.popularity or 0), reverse=True)[:_MAX_COMBOS]
    hidden = len(combos) - len(shown)
    lines += _win_conditions(deck, shown, hidden, creatures)

    if shown:
        lines += ["", "## Combo lines"]
        for c in shown:
            lines.append(f"**{' + '.join(c.produces)}** — {', '.join(u.name for u in c.uses)}")
            if c.prerequisites:
                lines.append(f"- Setup: {c.prerequisites}")
            for step in (c.description or "").splitlines():
                lines.append(f"- {step}")
            lines.append("")
        if hidden:
            lines.append(f"_…and {hidden} more combo variant{'s' if hidden != 1 else ''} "
                         "with the same core engine — see Commander Spellbook for the full list._")

    lines += ["", "## Mulligan", _mulligan(report, sim, cats),
              "", "## Sequencing", _sequencing(report, sim)]

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
    # Collapse any accidental double blank lines between sections.
    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue
        out.append(ln)
    return "\n".join(out)


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


# --- Win conditions -------------------------------------------------------
#
# A combo that "produces" a resource is only a win when an *outlet* converts
# that resource into something lethal. Spellbook lists the produced features;
# we classify each as either *terminal* (ends the game on its own) or an
# *engine* resource that needs a payoff, then look in the deck for a card that
# can serve as that payoff. Naming the missing/​present outlet is the part most
# auto-generated guides leave out — and the part a pilot actually needs.

# Cap how many combo variants a guide details before collapsing the rest to a count.
_MAX_COMBOS = 6

# A produced feature is terminal if its text contains one of these. "mill" is
# terminal too (decks an opponent) *unless* it is self-mill, which needs a
# Laboratory-Maniac-style payoff to win.
_TERMINAL_HINTS = (
    "win the game", "wins the game", "lose the game", "loses the game",
    "damage", "loss of life", "life loss", "lifeloss", "lose life", "loses life",
    "drain", "poison", "infect", "decks", "each opponent loses",
)

# engine-resource tag -> list of (payoff label, predicate over a deck card).
# Predicates run on lowercased (name, oracle text, mana cost); they describe
# what a card *does*, so they generalise beyond a hard-coded card list.
_Pred = Callable[[str, str, str], bool]
_OUTLETS: dict[str, list[tuple[str, _Pred]]] = {
    "mana": [
        ("an X-cost mana sink",
         lambda n, t, m: "{x}" in m and any(k in t for k in (
             "damage", "draw", "loses", "life", "for each"))),
        ("a mana-sink finisher",
         lambda n, t, m: any(k in t for k in (
             "x damage to each", "deals x damage", "loses x life", "draw x cards"))),
        ("Aetherflux Reservoir", lambda n, t, m: n == "aetherflux reservoir"),
        ("Walking Ballista", lambda n, t, m: n == "walking ballista"),
    ],
    "token": [
        ("an anthem / overrun payoff",
         lambda n, t, m: "creatures you control get +" in t
         or "other creatures you control get +" in t),
        ("a go-wide finisher",
         lambda n, t, m: n in {"craterhoof behemoth", "overwhelming stampede",
                               "pathbreaker ibex", "end-raze forerunners"}),
    ],
    "etb": [
        ("an ETB damage/drain payoff",
         lambda n, t, m: "whenever" in t and "enters" in t
         and any(k in t for k in ("deals", "loses", "lose"))),
    ],
    "death": [
        ("an aristocrats drain payoff",
         lambda n, t, m: "whenever" in t and ("dies" in t or "another creature" in t)
         and any(k in t for k in ("loses", "lose ", "deals"))),
        ("a free sacrifice outlet",
         lambda n, t, m: "sacrifice a creature:" in t
         or "sacrifice another creature:" in t),
    ],
    "draw": [
        ("a draw-to-win payoff",
         lambda n, t, m: n in {"laboratory maniac", "jace, wielder of mysteries"}
         or "thassa's oracle" in n or "you win the game" in t),
    ],
    "cast": [
        ("a cast/storm payoff",
         lambda n, t, m: "whenever you cast" in t
         and any(k in t for k in ("deals", "create", "token", "copy"))),
    ],
}


def _is_terminal(fl: str) -> bool:
    """True if a produced feature ends the game on its own (lowercased input)."""
    if "self-mill" in fl or "self mill" in fl:
        return False  # decks *you*, not an opponent — needs a Lab-Man payoff
    if "damage" in fl and "to creature" in fl and not (
            "opponent" in fl or "player" in fl or "any target" in fl):
        return False  # damage to creatures is a board wipe, not a wincon
    if "mill" in fl:
        return True  # mills an opponent -> decks them
    return any(h in fl for h in _TERMINAL_HINTS)


def _classify_produces(produces: list[str]) -> tuple[list[str], set[str]]:
    """Split produced features into (terminal phrases, engine-resource tags)."""
    terminal: list[str] = []
    tags: set[str] = set()
    for f in produces:
        fl = f.lower()
        if _is_terminal(fl):
            terminal.append(f)
            continue
        if "mana" in fl or "untap" in fl:
            tags.add("mana")
        if "token" in fl:
            tags.add("token")
        if "etb" in fl or "enters the battlefield" in fl:
            tags.add("etb")
        if any(k in fl for k in ("death", "dies", "ltb", "sacrifice",
                                 "leaves the battlefield")):
            tags.add("death")
        if "draw" in fl or "self-mill" in fl or "self mill" in fl:
            tags.add("draw")
        if any(k in fl for k in ("storm", "cast", "spell", "magecraft")):
            tags.add("cast")
    return terminal, tags


def _find_outlets(deck: ResolvedDeck, tags: set[str], exclude: set[str]) -> list[str]:
    """Names of deck cards that can convert the given engine resources to a win."""
    found: list[str] = []
    seen: set[str] = set()
    for e in deck.mainboard:
        c = e.card
        if not c or c.name in exclude or c.name in seen:
            continue
        n, t = c.name.lower(), c.get_oracle_text().lower()
        m = (c.get_mana_cost() or "").lower()
        for tag in tags:
            if any(pred(n, t, m) for _label, pred in _OUTLETS.get(tag, [])):
                found.append(c.name)
                seen.add(c.name)
                break
    return found


def _combo_win_detail(deck: ResolvedDeck, combo: Combo) -> str:
    """One clause explaining how a combo actually closes the game."""
    terminal, tags = _classify_produces(combo.produces)
    if terminal:
        return "wins outright (" + ", ".join(sorted(set(terminal))).lower() + ")"
    if not tags:
        return "generates value — pair with your strongest threats to close"
    pieces = {u.name for u in combo.uses}
    outlets = _find_outlets(deck, tags, exclude=pieces)
    if outlets:
        return "engine — convert it with " + ", ".join(outlets[:3])
    want = {"mana": "a mana sink", "token": "a go-wide finisher",
            "etb": "an ETB payoff", "death": "an aristocrats drain",
            "draw": "a draw-to-win payoff", "cast": "a cast/storm payoff"}
    need = ", ".join(dict.fromkeys(want[t] for t in tags if t in want)) or "a payoff"
    return f"engine — **no outlet in the deck**; add {need} to make it lethal"


def _win_conditions(
    deck: ResolvedDeck, combos: list[Combo], hidden: int, creatures: int,
) -> list[str]:
    """Render the Win conditions section: primary/backup paths + per-combo outlets.

    ``combos`` is the (already capped) list to detail; ``hidden`` is how many more
    variants exist beyond it. Labels are the combo's *pieces* — the full produced
    feature list lives in the Combo lines section and is too long to headline.
    """
    paths: list[tuple[str, str]] = []  # (label, detail)
    for c in combos:
        paths.append((", ".join(u.name for u in c.uses), _combo_win_detail(deck, c)))
    if creatures >= 25:
        paths.append((f"Combat ({creatures} creatures)",
                      "swing with your threats to close"))
    if not paths:
        paths.append(("Grind value",
                      "out-resource the table and win with your strongest threats"))

    out = ["", "## Win conditions"]
    # Primary = first combo that wins outright, else first listed path.
    primary_idx = next(
        (i for i, (_, d) in enumerate(paths) if d.startswith("wins outright")), 0)
    p_label, p_detail = paths[primary_idx]
    out.append(f"**Primary:** {p_label} — {p_detail}.")

    backups = [lab for i, (lab, _) in enumerate(paths) if i != primary_idx]
    tail = backups[:3]
    if len(backups) > len(tail):
        tail.append(f"+{len(backups) - len(tail)} more")
    if hidden:
        tail.append(f"+{hidden} combo variant{'s' if hidden != 1 else ''}")
    if tail:
        out.append(f"**Backups:** {'; '.join(tail)}.")
    elif combos:
        out.append("_Only one real line — find or add a redundant/​backup win-con "
                   "so removal can't lock you out._")
    out.append("")
    for label, detail in paths:
        out.append(f"- **{label}** — {detail}.")

    # Kill-on-sight: the combo pieces a pilot must protect / opponents will target.
    pieces = list(dict.fromkeys(u.name for c in combos for u in c.uses))
    if pieces:
        out.append("")
        out.append("**Protect (kill-on-sight):** " + ", ".join(pieces[:8])
                   + " — hold interaction for these; losing a piece breaks the line.")
    return out


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

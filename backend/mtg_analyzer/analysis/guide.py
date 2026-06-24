"""Compose a pilot's strategy guide (markdown) for a deck from its grounded data.

Pulls together the validation/composition analysis, combos present (with their lines),
the goldfish mulligan/curve stats, and the commander's top EDHREC-synergy cards that the
deck actually runs — then renders a practical 1-page guide. Facts are grounded; the
framing is templated from real signals (no invented strategy).

Depth no longer depends on a deck having a Commander Spellbook combo: a combo-less deck's
win plan is recovered from the deck itself — terminal/engine *finishers* detected in the
card text (the same outlet machinery the combo path uses), an "Engine lines" section that
parallels "Combo lines", and an archetype label (derived from real deck signals) that
tunes the Game plan and Sequencing prose.
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
    # Non-combo win plan recovered from the deck, and an archetype label from real signals.
    finishers = _deck_finishers(deck)
    arch = _classify_archetype(deck, report, combos, creatures, finishers)

    lines = [
        f"# {name} — Pilot's Guide",
        "",
        f"**Commander:** {commanders}  ·  **Colors:** {report.identity}  "
        f"·  **Bracket ~{report.bracket_estimate}**",
        f"_{report.bracket_rationale}_",
        "",
        "## Game plan",
        _game_plan(report, arch, combos, creatures),
    ]
    # Many commanders surface a dozen near-identical combo variants (same engine,
    # swapped payoff). Show the most popular handful; note the rest as a count.
    shown = sorted(combos, key=lambda c: (c.popularity or 0), reverse=True)[:_MAX_COMBOS]
    hidden = len(combos) - len(shown)
    lines += _win_conditions(deck, shown, hidden, creatures, finishers)

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
    elif finishers:
        # The structural parallel to Combo lines for engine/aggro decks: how the deck's
        # detected payoffs convert board/resources into a win, plus the fuel that feeds them.
        lines += _engine_lines(finishers, creatures, cats)

    lines += ["", "## Mulligan", _mulligan(report, sim, cats),
              "", "## Sequencing", _sequencing(report, sim, arch)]

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


def _game_plan(report: DeckReport, arch: _Arch, combos: list[Combo], creatures: int) -> str:
    plan = (f"A bracket-{report.bracket_estimate} {report.identity} {arch.label} deck led by "
            f"{', '.join(report.commanders) or 'your commander'}. {arch.plan}")
    # Only add the generic combat note when the archetype prose hasn't already spoken to the board.
    if creatures >= 25 and arch.key in {"midrange", "big-mana", "control", "combo"}:
        plan += " You also have a deep creature base to pressure the board and pivot to combat."
    return plan.strip()


# --- Archetype (deck-signal classification → templated prose) --------------
#
# A small, *grounded* classifier: each branch fires on counts/text signals the deck
# actually exhibits, and maps to a (game-plan, sequencing) prose pair. This is what gives
# combo-less decks an archetype-shaped guide instead of one generic sentence.

class _Arch:
    __slots__ = ("key", "label", "plan", "seq")

    def __init__(self, key: str, label: str, plan: str, seq: str) -> None:
        self.key, self.label, self.plan, self.seq = key, label, plan, seq


# key -> (display label, game-plan prose, sequencing prose).
_ARCHETYPE_PROSE: dict[str, tuple[str, str, str]] = {
    "combo": ("combo",
              "Develop mana and card advantage, protect your pieces, and win once a combo comes "
              "together.",
              "Hold up protection for your combo turn and durdle safely until you can go off."),
    "group-hug": ("group-hug",
                  "Hand out resources to keep the table pointed elsewhere, out-draw everyone, then "
                  "flip the symmetry into a one-sided finish.",
                  "Deploy your draw/politics engines early, but commit your finisher only once you "
                  "can win that turn — you've been fueling opponents too."),
    "aristocrats": ("aristocrats",
                    "Build a wide, expendable board plus a sacrifice/drain engine, and convert "
                    "creature deaths and lifeswings into table-wide damage.",
                    "Get a drain payoff and a sac outlet onto the board; hold removal for anyone who "
                    "can exile your payoff."),
    "spellslinger": ("spellslinger",
                     "Chain cheap instants and sorceries to feed prowess/magecraft payoffs and burn "
                     "the table out.",
                     "Hold mana for instant-speed plays on other turns; sequence cantrips to keep "
                     "cards flowing into a payoff."),
    "voltron": ("voltron",
                "Suit up a single evasive threat and push lethal commander damage, protecting it "
                "through removal.",
                "Keep protection (hexproof/indestructible/boots) in hand before committing the "
                "threat; don't over-extend equipment into a wipe."),
    "tokens": ("go-wide tokens",
               "Flood the board with tokens and close with an anthem/overrun for a lethal alpha "
               "strike.",
               "Curve out token-makers; hold the overrun until a wipe is unlikely or you can "
               "rebuild fast."),
    "counters": ("+1/+1 counters",
                 "Stack +1/+1 counters across the board (and your commander) and overwhelm with "
                 "oversized, evasive threats.",
                 "Deploy counter engines early and protect your doublers and key payoffs from "
                 "removal."),
    "control": ("control",
                "Answer threats, grind card advantage, and win late with a compact threat once the "
                "table is exhausted.",
                "Trade efficiently and hold counters/removal for real threats; deploy your win late, "
                "behind interaction."),
    "big-mana": ("big-mana ramp",
                 "Ramp hard, then deploy threats and payoffs the table can't match on raw mana.",
                 "Prioritize ramp early, then sequence into your most impactful spell once you're "
                 "ahead on mana."),
    "aggro": ("aggro",
              "Pressure the board early and pivot to combat to close before slower decks set up.",
              "Curve out threats and hold just enough interaction to clear blockers and push "
              "damage."),
    "midrange": ("midrange value",
                 "Trade efficiently, grind incremental value, and win with your strongest threats.",
                 "Hit land drops, deploy value, and hold interaction for key threats."),
}


def _count(deck: ResolvedDeck, pred: Callable[[str, str], bool]) -> int:
    """Sum quantities of mainboard cards whose (type_line, oracle_text) satisfy ``pred``."""
    n = 0
    for e in deck.mainboard:
        c = e.card
        if c and pred((c.type_line or "").lower(), c.get_oracle_text().lower()):
            n += e.quantity
    return n


def _classify_archetype(
    deck: ResolvedDeck, report: DeckReport, combos: list[Combo], creatures: int,
    finishers: list[tuple[str, str, list[str]]],
) -> _Arch:
    cats = {c.category: c.count for c in report.categories}
    labels = {lab for lab, _d, _n in finishers}
    spells = _count(deck, lambda tl, t: "instant" in tl or "sorcery" in tl)
    equip_aura = _count(deck, lambda tl, t: "equipment" in tl or "aura" in tl)
    tokens = _count(deck, lambda tl, t: "create" in t and "token" in t)
    sym_draw = _count(deck, lambda tl, t: "each player draws" in t or "target opponent draws" in t
                      or "each opponent draws" in t)
    counters = _count(deck, lambda tl, t: "+1/+1 counter" in t)
    interaction = cats.get("removal", 0) + cats.get("counterspell", 0) + cats.get("board_wipe", 0)
    ramp = cats.get("ramp", 0)

    if combos:
        key = "combo"
    elif sym_draw >= 3:
        key = "group-hug"
    elif "Drain / aristocrats" in labels or "Group-slug" in labels:
        key = "aristocrats"
    elif spells >= 18:
        key = "spellslinger"
    elif creatures <= 14 and equip_aura >= 7:
        key = "voltron"
    elif tokens >= 8 or "Overrun / anthem" in labels:
        key = "tokens"
    elif counters >= 8:
        key = "counters"
    elif interaction >= 14 and creatures < 20:
        key = "control"
    elif ramp >= 14:
        key = "big-mana"
    elif creatures >= 27:
        key = "aggro"
    else:
        key = "midrange"
    label, plan, seq = _ARCHETYPE_PROSE[key]
    return _Arch(key, label, plan, seq)


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

# Deck-wide finishers (the non-combo parallel to a combo's produced features). Each is a
# (theme, one-line detail, predicate over lowercased name/text/mana). A card is filed under
# the first theme it matches, in this priority order; the *Primary* win-con is the first
# theme whose detail begins "wins outright", else the first listed.
_FINISHERS: list[tuple[str, str, _Pred]] = [
    ("Alt-win",
     "wins outright once its counter/threshold fills",
     lambda n, t, m: "you win the game" in t),
    ("Group-slug",
     "your card draw drains each opponent",
     lambda n, t, m: "whenever you draw" in t
     and any(k in t for k in ("each opponent loses", "loses 1 life", "loses life", "damage"))),
    ("Drain / aristocrats",
     "deaths and end-step triggers ping the whole table",
     lambda n, t, m: "each opponent loses" in t or "opponents lose" in t),
    ("Overrun / anthem",
     "go wide, then pump for a lethal alpha strike",
     lambda n, t, m: ("creatures you control get +" in t
                      and any(k in t for k in ("trample", "and gain", "haste")))
     or n in {"craterhoof behemoth", "overwhelming stampede", "pathbreaker ibex",
              "end-raze forerunners"}),
    ("Combat amplifier",
     "double strike / power-doubling turns the board lethal",
     lambda n, t, m: "double strike" in t
     or ("base power and toughness" in t and "twice" in t)),
    ("Burn payoff",
     "incidental damage triggers close from outside combat",
     lambda n, t, m: "deals damage equal to its power to any target" in t
     or ("whenever" in t and "enters" in t and "deals" in t
         and ("any target" in t or "each opponent" in t))),
]

# Themes that *enhance* an existing combat plan rather than win on their own. They rank
# below the base Combat path as a Primary win-con (a double-strike sword isn't the plan —
# the 30-creature board is; the sword just makes it lethal).
_AMPLIFIER_LABELS = {"Combat amplifier", "Burn payoff"}


def _deck_finishers(deck: ResolvedDeck) -> list[tuple[str, str, list[str]]]:
    """Detected win themes for the whole deck: [(theme, detail, [card names]), …].

    Each card is attributed to the first theme it matches (``_FINISHERS`` priority), so a
    card never double-counts. Returned in priority order, theme-empty entries dropped.
    """
    bucket: dict[str, list[str]] = {}
    seen: set[str] = set()
    for e in deck.mainboard:
        c = e.card
        if not c or c.name in seen:
            continue
        n, t = c.name.lower(), c.get_oracle_text().lower()
        m = (c.get_mana_cost() or "").lower()
        for label, _detail, pred in _FINISHERS:
            if pred(n, t, m):
                bucket.setdefault(label, []).append(c.name)
                seen.add(c.name)
                break
    out: list[tuple[str, str, list[str]]] = []
    for label, detail, _pred in _FINISHERS:
        if label in bucket:
            out.append((label, detail, bucket[label]))
    return out


def _engine_lines(
    finishers: list[tuple[str, str, list[str]]], creatures: int, cats: dict[str, int],
) -> list[str]:
    """The combo-less parallel to 'Combo lines': name each payoff and the fuel that feeds it."""
    out = ["", "## Engine lines",
           "Wins through an engine rather than a two-card combo — assemble and protect the payoff:"]
    for label, detail, names in finishers[:3]:
        head = ", ".join(names[:4]) + (f" (+{len(names) - 4} more)" if len(names) > 4 else "")
        out.append(f"**{label}** — {head}")
        out.append(f"- {detail}.")
    out.append(f"- Fuel on board: {creatures} creatures · ramp {cats.get('ramp', 0)} "
               f"· draw {cats.get('draw', 0)} · removal {cats.get('removal', 0)}.")
    return out


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
    finishers: list[tuple[str, str, list[str]]],
) -> list[str]:
    """Render the Win conditions section: primary/backup paths + per-combo outlets.

    ``combos`` is the (already capped) list to detail; ``hidden`` is how many more variants
    exist beyond it; ``finishers`` are deck-wide (non-combo) win themes. Combo decks list
    their combos first; combo-less decks fall back to the detected finishers, then combat,
    then a grind line — so the section is never just one generic sentence.
    """
    def _path(label: str, detail: str, names: list[str]) -> tuple[str, str]:
        shown = ", ".join(names[:3]) + (f", +{len(names) - 3} more" if len(names) > 3 else "")
        return (f"{label} ({shown})", detail)

    paths: list[tuple[str, str]] = []  # (label, detail)
    for c in combos:
        paths.append((", ".join(u.name for u in c.uses), _combo_win_detail(deck, c)))
    # Standalone win engines first; a base Combat plan next (when creature-heavy and not already
    # an overrun); pure *amplifiers* (double strike / burn) last, since they enhance combat rather
    # than win alone — so a go-wide deck reads "Primary: Combat", not "Primary: a double-strike sword".
    engines = [f for f in finishers if f[0] not in _AMPLIFIER_LABELS]
    amps = [f for f in finishers if f[0] in _AMPLIFIER_LABELS]
    for label, detail, names in engines:
        paths.append(_path(label, detail, names))
    if creatures >= 25 and not any(lab.startswith("Overrun") for lab, _ in paths):
        paths.append((f"Combat ({creatures} creatures)",
                      "swing with your threats to close"))
    for label, detail, names in amps:
        paths.append(_path(label, detail, names))
    if not paths:
        paths.append(("Grind value",
                      "out-resource the table and win with your strongest threats"))

    out = ["", "## Win conditions"]
    # Primary = first path that wins outright, else first listed path.
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

    # Kill-on-sight: pieces a pilot must protect / opponents will target. Combo pieces first;
    # otherwise the detected finisher payoffs (the deck's actual win).
    pieces = list(dict.fromkeys(u.name for c in combos for u in c.uses))
    if pieces:
        out.append("")
        out.append("**Protect (kill-on-sight):** " + ", ".join(pieces[:8])
                   + " — hold interaction for these; losing a piece breaks the line.")
    elif finishers:
        payoffs = list(dict.fromkeys(nm for _l, _d, names in finishers for nm in names))
        out.append("")
        out.append("**Protect (kill-on-sight):** " + ", ".join(payoffs[:6])
                   + " — these are your win; hold up protection and don't over-commit "
                   "them into a wipe.")
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


def _sequencing(report: DeckReport, sim: SimResult | None, arch: _Arch) -> str:
    turn = sim.commander_turn.median if sim and sim.commander_turn else None
    cmc = sim.commander_cmc if sim else None
    s = "Prioritize hitting land drops and deploying ramp early. "
    if turn and cmc:
        s += f"Your commander (MV {cmc}) is typically castable around **turn {turn}**. "
    s += arch.seq
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

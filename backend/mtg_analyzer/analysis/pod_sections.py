"""Render the pod-aware guide sections from battle-sim results.

Two markdown sections, data-driven (templated framing, no invented strategy), shared by the CLI and
the web app via the service:

- **Pod matchup outlook** — the canonical full-pool results table (`# · Deck · Tier · Naive ·
  Informed · Archenemy`, this deck's row bold; see docs/sim-results-table-spec.md) plus
  naive/informed/range/takeaway bullets, from a `MetagameResult`.
- **Matchup tendencies (1v1)** — by-opponent-archetype win%, favored/careful opponents, and a read,
  from `head_to_head` `MatchupStats`.

This replaces the one-off scratchpad scripts that previously generated the sections, so the shipped
engine (and any UI) can reproduce them.
"""
from __future__ import annotations

from mtg_analyzer.simulation.battle import (
    DeckMetagameStats,
    MatchupStats,
    MetagameResult,
    power_tier,
)

_FOOTER = "_Auto-generated from deck analysis, simulation, and Commander Spellbook combos._"
_FAVORED, _CAREFUL = 0.55, 0.45   # heads-up win thresholds
_CAP = 6                          # max opponents listed per favored/careful line


def _short(name: str) -> str:
    """Compact display name for opponent lists (first word, with a few multi-word keepers)."""
    keep = {"Ms. Bumbleflower"}
    if name in keep:
        return name
    first = name.split(",")[0]
    return first if " " not in first else first.split()[0]


def _pct(x: float) -> str:
    return f"{x:.0%}"


# ---- Pod matchup outlook -----------------------------------------------------------------------
def render_pod_outlook(name: str, meta: MetagameResult) -> str:
    me = next((d for d in meta.decks if d.name == name), None)
    if me is None:
        return ""
    fair = 1.0 / meta.pod_size
    lines = [
        "## Pod matchup outlook (sim)",
        f"_Full sweep of all **{meta.pods} {meta.pod_size}-deck pods** across {len(meta.decks)} decks "
        f"(seed 1). **Naive** = table doesn't adapt; **informed** = the table has learned each deck's "
        f"power level (damped fictitious play) and gangs the strongest, compressing win rates toward the "
        f"{fair:.0%} fair share. Heuristic — relative, not predictive._",
        "",
        "**Full-pool ranking** — **Tier** = learned meta strength (S→D; *not* the build Bracket); "
        "**Naive**/**Informed** = win% vs. an unadapting / power-aware table; **Archenemy** = how often "
        "the table gangs this deck. This deck's row is **bolded**:",
        "",
        "| # | Deck | Tier | Naive win | Informed win | Archenemy |",
        "|--:|------|:--:|----:|----:|----:|",
    ]
    for d in meta.decks:
        cells = [str(d.power_rank), d.name, power_tier(d.power_level),
                 _pct(d.naive_win), _pct(d.win_rate), _pct(d.archenemy_rate)]
        if d.name == name:
            cells = [f"**{c}**" for c in cells]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", _pod_bullets(me, meta)]
    return "\n".join(lines)


def _pod_bullets(me: DeckMetagameStats, meta: MetagameResult) -> str:
    pw = f"{me.pod_wins} pod win" + ("" if me.pod_wins == 1 else "s")
    best = ", ".join(_short(x) for x in me.naive_max_pod)
    worst = ", ".join(_short(x) for x in me.naive_min_pod)
    bullets = [
        f"**Naive (table doesn't adapt):** **{_pct(me.naive_win)}** win — **#{_naive_rank(me, meta)} "
        f"raw rate** of {len(meta.decks)}, {pw}; {_heat(me.archenemy_rate, naive=True)}.",
        f"**Informed (table targets known power):** **tier {me.tier}, learned power "
        f"{me.power_level:+.2f}**; informed win **{_pct(me.win_rate)}** — {_heat(me.archenemy_rate)}.",
        f"**Range:** best **{_pct(me.naive_max)}** vs {best}; worst **{_pct(me.naive_min)}** vs {worst}.",
        f"**Takeaway:** {_pod_takeaway(me)}",
    ]
    return "\n".join(f"- {b}" for b in bullets)


def _naive_rank(me: DeckMetagameStats, meta: MetagameResult) -> int:
    order = sorted(meta.decks, key=lambda d: d.naive_win, reverse=True)
    return next(i for i, d in enumerate(order, 1) if d.name == me.name)


def _heat(arch: float, *, naive: bool = False) -> str:
    where = "even from a naive table" if naive else "at an informed table"
    if arch >= 0.5:
        return f"draws heavy heat {where} (archenemy **{_pct(arch)}**)"
    if arch >= 0.25:
        return f"draws real heat (archenemy **{_pct(arch)}**)"
    if arch <= 0.06:
        return f"essentially ignored (archenemy **{_pct(arch)}**)"
    return f"modest heat (archenemy **{_pct(arch)}**)"


def _pod_takeaway(me: DeckMetagameStats) -> str:
    inherit = me.win_rate - me.naive_win
    if me.tier in ("S", "A"):
        if me.archenemy_rate >= 0.4:
            return ("a top-tier deck the informed table polices hard — your win rate compresses from "
                    f"{_pct(me.naive_win)} to {_pct(me.win_rate)} as you draw the heat. Lean on "
                    "resilience/interaction to win through the answers, and feast on softer pods.")
        return ("a genuine top-tier power that flies under the radar — strong without being the prime "
                "target. Develop freely while the table polices the louder threats.")
    if inherit >= 0.08:
        return ("an inherit-the-win deck: low standing power, but once the table spends its answers on "
                f"the real powers your win climbs from {_pct(me.naive_win)} (naive) to "
                f"{_pct(me.win_rate)} (informed). Stay quiet and cash in when the heat is elsewhere.")
    if me.archenemy_rate >= 0.4:
        return ("the lightning rod — a fast/visible clock paints the target and the table answers it. "
                "Go under the radar or add resilience; you fare best when a bigger threat is present.")
    return (f"a mid-pack deck (~{_pct(me.win_rate)} informed) — competitive in soft-to-mid pods but "
            "short of the top tier's power. Win on value while the table fights over the leaders.")


# ---- Matchup tendencies (1v1) ------------------------------------------------------------------
def render_matchup_tendencies(name: str, matchups: list[MatchupStats]) -> str:
    me = next((m for m in matchups if m.name == name), None)
    if me is None:
        return ""
    fav = [(o.name, o.win_rate) for o in me.opponents if o.win_rate >= _FAVORED]
    care = [(o.name, o.win_rate) for o in me.opponents if o.win_rate <= _CAREFUL]
    bytype = " · ".join(f"{k} **{_pct(v)}**"
                        for k, v in sorted(me.by_archetype.items(), key=lambda x: -x[1]))
    lines = [
        "## Matchup tendencies (1v1)",
        "_Heads-up win rate vs each other deck. Isolates the **pure matchup** — distinct from the pod "
        "outlook above, where politics can gang a deck that wins the duel (fast decks are the clearest "
        f"example). **Favored** ≥{_FAVORED:.0%} · **Careful** ≤{_CAREFUL:.0%}. Heuristic — relative._",
        "",
        f"- **By opponent type:** {bytype}  _(your avg heads-up win% vs that archetype)_",
        f"- **Favored against:** {_opplist(fav)}.",
        f"- **Careful against:** {_opplist(care)}.",
        f"- **Read:** {_matchup_read(me)}",
    ]
    return "\n".join(lines)


def _opplist(items: list[tuple[str, float]]) -> str:
    if not items:
        return "none in this pool"
    head = ", ".join(f"{_short(n)} {_pct(w)}" for n, w in items[:_CAP])
    return head + (f", +{len(items) - _CAP} more" if len(items) > _CAP else "")


def _matchup_read(me: MatchupStats) -> str:
    ranked = sorted(me.by_archetype.items(), key=lambda x: -x[1])
    best = ", ".join(k for k, _ in ranked[:1])
    worst = ", ".join(k for k, v in ranked if v < 0.45) or ranked[-1][0]
    parts = [f"favored into {best}; careful into {worst}"]
    combo = me.by_archetype.get("combo")
    if combo is not None and combo == min(me.by_archetype.values()) and combo < 0.45:
        parts.append("combo is the wall (you're a dog to it heads-up)")
    if me.avg_win >= 0.6:
        parts.append("a heads-up monster — but that same speed/consistency is what gets you ganged in a "
                     "pod, so the duel read overstates your 4-player equity")
    elif me.avg_win <= 0.35:
        parts.append("a duel underdog overall — your equity is in the pod (drawing little heat), not in "
                     "1v1s")
    return "; ".join(parts) + "."

"""Pod-aware guide sections render from battle-sim results (productized, no scratchpad scripts)."""
from mtg_analyzer.analysis.pod_sections import render_matchup_tendencies, render_pod_outlook
from mtg_analyzer.simulation.battle import (
    DeckMetagameStats,
    MatchupStats,
    MetagameResult,
    OpponentMatchup,
)


def _meta() -> MetagameResult:
    decks = [
        DeckMetagameStats("Alpha", 1, 0.12, 0.20, 0.57, 0.49, pod_wins=10,
                          naive_min=0.27, naive_min_pod=["Beta", "Gamma", "Delta"],
                          naive_max=0.76, naive_max_pod=["Echo", "Foxtrot", "Golf"]),
        DeckMetagameStats("Hotel", 2, -0.08, 0.30, 0.04, 0.10, pod_wins=1,
                          naive_min=0.01, naive_min_pod=["Alpha", "Beta", "Gamma"],
                          naive_max=0.32, naive_max_pod=["Echo", "Foxtrot", "Golf"]),
    ]
    return MetagameResult(decks=decks, pod_size=4, pods=715, iterations=5, converged=True,
                          informed=True)


def test_render_pod_outlook() -> None:
    md = render_pod_outlook("Alpha", _meta())
    assert md.startswith("## Pod matchup outlook (sim)")
    # canonical table header + this deck's row bolded with its tier (power +0.12 → S)
    assert "| # | Deck | Tier | Naive win | Informed win | Archenemy |" in md
    assert "**Alpha**" in md and "**S**" in md
    # bullets carry naive/informed/range/takeaway
    assert "Naive (table doesn't adapt):" in md and "20%" in md
    assert "best **76%**" in md and "worst **27%**" in md
    # an unknown deck renders nothing rather than crashing
    assert render_pod_outlook("Nobody", _meta()) == ""


def test_render_pod_outlook_inherit_takeaway() -> None:
    # Hotel: low tier (C) but informed (30%) >> naive (10%) → "inherit-the-win" framing.
    md = render_pod_outlook("Hotel", _meta())
    assert "inherit" in md.lower()


def test_render_matchup_tendencies() -> None:
    mu = [MatchupStats("Alpha", "combo", 0.66,
                       {"midrange": 0.72, "aggro": 0.62, "combo": 0.40},
                       [OpponentMatchup("Beta", "midrange", 0.72),
                        OpponentMatchup("Gamma", "aggro", 0.62),
                        OpponentMatchup("Hotel", "combo", 0.40)])]
    md = render_matchup_tendencies("Alpha", mu)
    assert md.startswith("## Matchup tendencies (1v1)")
    assert "By opponent type:" in md and "midrange **72%**" in md
    assert "Favored against:** Beta 72%, Gamma 62%" in md
    assert "Careful against:** Hotel 40%" in md
    assert "combo is the wall" in md  # combo is the lowest archetype and < 45%
    assert render_matchup_tendencies("Nobody", mu) == ""

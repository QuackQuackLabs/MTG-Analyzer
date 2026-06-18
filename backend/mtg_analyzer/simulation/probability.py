"""Exact draw probabilities via the hypergeometric distribution (scipy).

Commander is modeled as a 99-card library (the commander starts in the command zone).
These are closed-form and exact — the reliable complement to the Monte-Carlo goldfish.
See the commander-format skill for the scipy parameter mapping.
"""

from __future__ import annotations

from scipy.stats import hypergeom

LIBRARY = 99


def p_at_least(successes_in_deck: int, draws: int, k: int, *, deck_size: int = LIBRARY) -> float:
    """P(drawing >= k of a group), sampling `draws` cards without replacement.

    scipy hypergeom(M, n, N): M=deck size, n=successes in deck, N=cards drawn.
    P(X >= k) = sf(k-1).
    """
    if k <= 0:
        return 1.0
    return float(hypergeom.sf(k - 1, deck_size, successes_in_deck, draws))


def cards_seen_by_turn(turn: int, *, on_play: bool) -> int:
    """Opening 7 plus draws by the given turn (no draw on turn 1 when on the play)."""
    return 7 + (turn - 1 if on_play else turn)


def p_see_by_turn(
    copies_in_deck: int, turn: int, *, on_play: bool = True, deck_size: int = LIBRARY
) -> float:
    """P(seeing >=1 of a card with `copies_in_deck` copies by the given turn)."""
    return p_at_least(copies_in_deck, cards_seen_by_turn(turn, on_play=on_play), 1,
                      deck_size=deck_size)

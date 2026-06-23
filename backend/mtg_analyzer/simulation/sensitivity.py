"""Global sensitivity analysis for the battle simulator (enhancement plan §D2/§D3).

The legacy band in `simulate_match` perturbs ONE parameter (interaction-answer base), which the
sensitivity-analysis literature flags as the most common way to understate uncertainty. This module
samples ALL tunable parameters jointly (Latin Hypercube over `battle_params.PRIORS`) to produce an
honest **joint-parametric uncertainty band**, and screens which parameters actually drive the result
(correlation-based global SA — cheap because it reuses the LHS runs; Morris/Sobol' are the documented
next step). Outputs are parametric uncertainty under expert priors — NOT calibrated predictions.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
from scipy import stats

from mtg_analyzer.models.battle import BattleProfile
from mtg_analyzer.simulation import battle_params as P
from mtg_analyzer.simulation.battle import _run


@contextlib.contextmanager
def param_overrides(values: dict[str, float]) -> Iterator[None]:
    """Temporarily set `battle_params` module attributes, restoring them on exit. The battle loop
    reads `P.X` at call time, so overrides take effect for any sim run inside the block."""
    saved = {k: getattr(P, k) for k in values}
    try:
        for k, v in values.items():
            setattr(P, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(P, k, v)


def _latin_hypercube(rng: np.random.Generator, samples: int, dims: int) -> np.ndarray:
    """A samples×dims Latin Hypercube design in [0,1): one stratified draw per cell, shuffled per dim."""
    edges = np.linspace(0.0, 1.0, samples + 1)
    lo, hi = edges[:samples], edges[1:]
    out = np.empty((samples, dims))
    for j in range(dims):
        col = lo + rng.uniform(size=samples) * (hi - lo)
        rng.shuffle(col)
        out[:, j] = col
    return out


def _win_rates(profiles: list[BattleProfile], games: int, seed: int) -> list[float]:
    tally = _run(profiles, games, seed, P.INTERACTION_ANSWER_BASE)
    return [tally.wins[i] / games for i in range(len(profiles))]


@dataclass
class SensitivityResult:
    band: dict[str, tuple[float, float, float]]  # deck -> (p5, median, p95) win rate across the prior
    importance: list[tuple[str, float]]  # (param, |rank-corr| with the most-affected deck), desc
    samples: int
    games: int


def analyze_sensitivity(
    profiles: list[BattleProfile], *, samples: int = 64, games: int = 800, seed: int = 1
) -> SensitivityResult:
    """Propagate the joint prior over all tunable parameters into a win-rate band, and rank which
    parameters drive the spread. Reuses one LHS design for both (correlation-based screening)."""
    names = list(P.PRIORS)
    lows = np.array([P.PRIORS[k][0] for k in names])
    highs = np.array([P.PRIORS[k][1] for k in names])
    rng = np.random.default_rng(seed)
    unit = _latin_hypercube(rng, samples, len(names))
    design = lows + unit * (highs - lows)

    n = len(profiles)
    wins = np.empty((samples, n))
    for s in range(samples):
        with param_overrides({names[j]: float(design[s, j]) for j in range(len(names))}):
            wins[s] = _win_rates(profiles, games, seed)

    band = {
        profiles[i].name: (
            round(float(np.percentile(wins[:, i], 5)), 3),
            round(float(np.median(wins[:, i])), 3),
            round(float(np.percentile(wins[:, i], 95)), 3),
        )
        for i in range(n)
    }

    # Correlation-based screening: a parameter matters if moving it correlates with moving SOME deck's
    # win rate. Take the max |Spearman| across decks so a knob that swings one matchup still ranks.
    importance: list[tuple[str, float]] = []
    for j, name in enumerate(names):
        corrs = []
        for i in range(n):
            if np.ptp(wins[:, i]) < 1e-9:
                continue
            rho = stats.spearmanr(design[:, j], wins[:, i]).statistic
            if not np.isnan(rho):
                corrs.append(abs(float(rho)))
        importance.append((name, round(max(corrs), 3) if corrs else 0.0))
    importance.sort(key=lambda kv: kv[1], reverse=True)

    return SensitivityResult(band=band, importance=importance, samples=samples, games=games)

"""Tunable constants for the heuristic battle simulator (Phase 9, Phase A).

ALL free parameters live here so the model is auditable and calibratable. These are
*designer estimates*, not measured from real games — see docs/battle-simulator-design.md §4.
Outputs are **relative** and **banded**, never card-accurate. Do not scatter magic numbers
into battle.py; add them here with a comment.
"""

from __future__ import annotations

START_LIFE = 40
MAX_TURNS = 24

# Archetype -> (turns after the engine/commander is online until the deck can win, sd).
# Added on top of the goldfish "commander online" mean to get a kill-turn ("clock").
ARCHETYPE_CLOCK: dict[str, tuple[float, float]] = {
    "combo": (2.0, 1.3),
    "aggro": (1.5, 1.0),
    "midrange": (2.8, 1.4),
    "control": (3.6, 1.6),
    "grind": (3.6, 1.5),
}
DEFAULT_CLOCK: tuple[float, float] = (2.8, 1.4)

# Win-attempt hazard: logistic around the (delayed) clock mean.
ATTEMPT_STEEPNESS = 1.1
ATTEMPT_CAP = 0.97
COMBO_ASSEMBLY_PER_TUTOR = 0.04  # extra per-turn attempt prob per tutor, for combo decks

# Interaction: a *finite* reserve of "answers" (counters + spot removal), slowly refilled by card
# advantage. Refill is deliberately < ~1/turn so answers deplete in the late game — otherwise pods
# never resolve and every game falls to the inevitability tiebreak (the Phase A bug).
INTERACTION_CAP = 12.0
CARD_ADVANTAGE_REFILL = 0.045  # reserve regained per turn per unit of draw-count
INTERACTION_ANSWER_BASE = 0.30  # base P(a held answer stops a win attempt)
INTERACTION_ANSWER_PER_PT = 0.045  # +P per point of the answerer's interaction
INTERACTION_ANSWER_MAX = 0.85
ANSWER_CLOCK_PENALTY = 2.2  # turns a deck is set back when its win attempt is answered

# Politics (Phase B, tuned in Phase C): players politick with pre-game power awareness. Rather than
# the whole table dumping answers on every spell, ONE best-positioned opponent handles a given threat
# (coordinated, not random) while the rest conserve interaction. The table commits harder to the
# pre-identified archenemy than to a trailing player — focused, but not a death sentence.
POLITICS_ARCHENEMY_ANSWER = 0.85  # answer P multiplier when a defender flagged the attacker its #1
POLITICS_NONARCH_ANSWER = 0.5  # multiplier when a defender only reacts out of self-preservation
ARCHENEMY_ANSWERERS = 3  # cap on coordinated answerers: an imminent threat draws every able opponent
# Proximity dominates: the table fears whoever is *about to win* over abstract power, so the
# consensus archenemy shifts across the game as different decks approach their kill turns.
THREAT_PROXIMITY_W = 2.6  # how much being near your own kill-turn raises your live threat
THREAT_PROXIMITY_WINDOW = 4.0  # turns around the clock over which proximity-threat ramps

# Per-player threat assessment (the decentralized "politicking engine"). Each turn every player
# scores opponents and votes for its #1 threat; the most-voted is the table's consensus archenemy.
# Scores share a power-level baseline (live_threat) but diverge by personal perspective, so votes
# split and the table doesn't always perfectly coordinate.
DAMAGE_FEAR_W = 0.05  # added perceived threat per point of damage that opponent has dealt to you
PERCEPTION_NOISE = 0.4  # std of bounded individual-read variation (small: power level dominates)

# Combat (non-combo unanswered "alpha strike").
ALPHA_STRIKE_FRACTION = 0.45  # fraction of START_LIFE removed
SWEEPER_BLUNT_P = 0.5  # chance a sweeper-holder blunts an incoming alpha strike
SWEEPER_DELAY = 2.0  # clock setback to the attacker when blunted

# Inevitability tiebreak at MAX_TURNS (game "goes long").
INEVITABILITY_WEIGHTS: dict[str, float] = {"card_advantage": 1.0, "combo": 3.0, "interaction": 0.6}

# Threat scoring (4-player target/answer focusing; also reported as archenemy rate).
THREAT_BRACKET_W = 1.0
THREAT_COMBO_W = 2.0
THREAT_SPEED_W = 1.5  # weight on (how soon) the deck's clock is

# Dynamic (turn-by-turn) live-threat terms: the table re-reads who is actually winning each turn
# from current board/resources/life rather than a static pre-game power number. This is what makes
# politics gang up on the real leader instead of the (inverted) "fastest = scariest" heuristic.
THREAT_STATIC_W = 0.3      # how much the pre-game static threat_level still counts (diluted)
THREAT_CARDADV_W = 0.1     # tuned via sweep: real win-driver, but light so it does not invert
THREAT_BOARD_W = 2.0       # tuned via sweep: board development draws heat
THREAT_BOARD_DEV_STEEP = 1.5  # logistic steepness for the online/board-development proxy
THREAT_LIFE_W = 0.08       # tuned via sweep: ahead-on-life = bigger target
# A combo deck that is *online* (set up, past its clock) threatens a sudden table-wide loss, so it
# draws the heat — gated by board-development so it's "whoever's about to combo off", NOT a flat
# "fastest deck is always the archenemy". This is what keeps a pod ganging up on a fast combo.
THREAT_COMBO_IMMINENCE_W = 14.0

# Combo-awareness Layer 2: ground a combo deck's clock in its goldfish-measured assembly turn
# (`SimResult.combo_turn`) instead of a flat archetype offset. The goldfish assumes hardcasting +
# natural draw, so it's honest for SETUP/combo decks but overstates aggro/cheat decks (a blitzed or
# reanimated combo creature) — so we blend (not replace) and skip the "aggro" archetype entirely.
COMBO_CLOCK_W = 0.35  # weight on the grounded combo_turn vs. the archetype-offset estimate
COMBO_REDUNDANCY_SD = 0.1  # clock_sd reduction per extra combo line (more ways to assemble = steadier)
COMBO_MIN_SD = 0.9  # floor so redundancy can't make a deck implausibly deterministic

# Sensitivity band: re-run with the interaction-answer base scaled by +/- this fraction.
SENSITIVITY = 0.25

# Explainability thresholds: when a deck's per-line attribution should call out politics pressure.
EXPLAIN_ARCHENEMY_HI = 0.40  # held the archenemy role this share of turns → "drew the table"
EXPLAIN_DIED_FIRST_HI = 0.40  # eliminated first this often → "folds early"

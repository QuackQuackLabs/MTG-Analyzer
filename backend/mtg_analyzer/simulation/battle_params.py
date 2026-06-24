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

# Win-attempt model. A1 (stochastic grounding): each game draws the deck's REALIZED kill turn from
# its clock distribution (between-game variance), then a sharp in-game ramp fires the attempt at/after
# it — so attempts are correlated within a game ("you either assemble or you don't") instead of
# independent per-turn rolls that inflate late-game wins. Tutors shift the realized clock earlier.
ATTEMPT_CAP = 0.97
INGAME_ATTEMPT_STEEPNESS = 2.0  # sharpness of the per-game attempt ramp around the realized clock
TUTOR_CLOCK_SHIFT = 0.12  # turns earlier the realized clock moves per tutor (combo assembly help)
TUTOR_CLOCK_SHIFT_CAP = 1.5  # max turns earlier tutors can shift the clock
ATTEMPT_STEEPNESS = 1.1  # (legacy, retained for reference; superseded by the A1 in-game ramp)
COMBO_ASSEMBLY_PER_TUTOR = 0.04  # (legacy; tutor effect now folded into the realized-clock shift)

# Interaction: a *finite* reserve of "answers" (counters + spot removal), slowly refilled by card
# advantage. Refill is deliberately < ~1/turn so answers deplete in the late game — otherwise pods
# never resolve and every game falls to the inevitability tiebreak (the Phase A bug).
INTERACTION_CAP = 12.0
CARD_ADVANTAGE_REFILL = 0.045  # reserve regained per turn per unit of draw-count
INTERACTION_ANSWER_BASE = 0.30  # base P(a held answer stops a win attempt)
INTERACTION_ANSWER_PER_PT = 0.045  # +P per point of the answerer's interaction
INTERACTION_ANSWER_MAX = 0.85
ANSWER_CLOCK_PENALTY = 2.2  # turns a deck is set back when its win attempt is answered

# Politics answering (F2 — equity-gated, free-rider-discounted; supersedes the old flat POLITICS_*
# archenemy/nonarch multipliers). A win attempt fires a table-wide check: each able opponent INDEPEND-
# ENTLY decides whether to spend an answer, with no central coordinator. Willingness combines:
#  - capability: answer_prob(j) (does j hold an answer — reserve/interaction).
#  - own-equity gate: a defender protects a win it is near; a trailing player shrugs ("not my problem").
#  - lethal gate: a clear win attempt (combo / the consensus archenemy) is answered harder than a
#    non-lethal beatdown swing.
#  - free-rider discount (bystander effect): each defender holds back in proportion to how likely
#    SOMEONE ELSE answers, so a threat the whole table COULD handle sometimes resolves (all defer).
ARCHENEMY_ANSWERERS = 3  # (retained) hard cap on opponents polled to answer one attempt
ANSWER_LETHAL_COMBO = 0.92      # lethal-gate for a combo win attempt (a table-wide loss → answered hard)
ANSWER_LETHAL_BEATDOWN = 0.65   # lethal-gate for a non-combo alpha-strike (less existential than a combo)
ANSWER_ARCHENEMY_MULT = 1.15    # the consensus archenemy's attempt is taken more seriously (capped at 1)
ANSWER_EQUITY_SLOPE = 0.16      # willingness rises this much per unit of own live-equity above table avg
ANSWER_EQUITY_MIN = 0.45        # floor on the own-equity gate (even a trailing player sometimes answers)
ANSWER_EQUITY_MAX = 1.5         # ceiling (a runaway leader snaps off everything it can)
# Table coordination (the §3.6 knob, and F5's casual↔cEDH preset axis). Scales each defender's
# willingness: 1.0 = perfectly coordinated, lower = more free-riding/bystander diffusion → the
# archenemy slips through more often. A FLAT factor on purpose: the elegant "discount by P(someone
# else answers)" is unstable — when every opponent is individually capable it makes them all defer and
# coordination paradoxically collapses against the threat the table reads most clearly.
ANSWER_COORDINATION = 0.80

# Stage 3 (prototype, default OFF) — GROUNDED opponent-model coordination. The flat ANSWER_COORDINATION
# above is a deliberate simplification; the comment notes the "discount by P(someone else answers)"
# bystander model was unstable (when every opponent is capable, all defer and coordination collapses).
# This is the CICERO-grounded stable version (prototyped in battle_search.py): each defender free-rides
# in proportion to the EXPECTED answering capacity of the OTHER defenders (not a global fixed point, so
# no collapse) — diffusion of responsibility rises with the number of capable defenders, so a threat the
# whole table could handle sometimes slips through. Audited as near-inert on the ranking (see roadmap
# Stage 3), so it stays opt-in: a fidelity option, not a production default.
GROUNDED_COORDINATION = False
FREE_RIDER_STRENGTH = 0.35   # max willingness discount from believing others will answer
FREE_RIDER_REF = 1.0         # expected-others answering capacity at which the discount is half-strength
FREE_RIDER_STEEP = 0.6       # logistic steepness of the bystander discount

# Stage 3b (prototype, default OFF) — standing-strength threat recognition. Adds heat to whoever is
# out-resourcing the field (grind-equity lead over the living mean), partly bypassing the quiet-shark
# visibility discount, so the table coordinates against the genuinely strongest deck and the win-rate
# spread compresses toward 1/N. 0.0 = current behaviour (quiet shark stays under-read).
# NOTE (audited): on its own this does NOT compress the spread — grind-equity mis-predicts who wins, so
# it mis-targets and scrambles the ranking. The realized-win-rate prior below (3c) is the better signal.
THREAT_DOMINANCE_W = 0.0

# Stage 3c (prototype, default OFF) — METAGAME-KNOWLEDGE prior via a fictitious-play feedback loop. The
# static `threat_level` is a poor pre-game threat read (a fast aggro deck scores highest yet never wins,
# so it is wrongly the turn-1 archenemy; a quiet control deck wins most yet is never targeted). Instead,
# feed each deck's OWN realized win rate back in as its standing "everyone knows this deck wins" prior
# (`BattleProfile.win_prior`, set to win_rate − 1/N): over-performers draw heat, under-performers are
# left alone at game start — and because the DYNAMIC board/proximity terms are untouched, a weak deck
# that actually takes off mid-game still draws heat then. Iterating sim → priors → sim converges to a
# self-consistent metagame. WINRATE_PRIOR_W scales how strongly known win-rate drives targeting.
# Validated on the LOTR pool: the damped loop converges to dist 0 vs. the experienced-player ranking
# (Sauron last→1st, Frodo's archenemy share 84%→68%, spread 33pp→27pp). Shipped as opt-in via
# `simulate_metagame` (CLI `mtg battle --metagame`); the standing default below stays 0 so a one-off
# `mtg battle` is unchanged.
WINRATE_PRIOR_W = 0.0
# Defaults for `simulate_metagame`'s damped fictitious-play loop. WEIGHT is the WINRATE_PRIOR_W used
# DURING the loop; DAMP blends new prior with old (higher = smoother — prevents the undamped overshoot:
# target the winner → it loses → target someone else → oscillate); target prior = win_rate − 1/pod_size.
METAGAME_PRIOR_WEIGHT = 40.0
METAGAME_DAMP = 0.7
METAGAME_ITERS = 6
# Informed-table assumption: once the power levels are LEARNED (the converged priors above), assume the
# pod actually KNOWS them and targets accordingly — a much stronger weight used for one final reporting
# pass. This is what makes the archenemy ranking track POWER (the strongest deck is correctly ganged up
# on) instead of in-game flash, and compresses win rates toward parity (the informed table polices the
# leader, so the 2nd/3rd under-the-radar decks inherit). Power level → the prior/archenemy ranking; win
# rate → the policed outcome. Convergence stays at the lower weight (high weight alone oscillates).
METAGAME_INFORMED_WEIGHT = 100.0

# F3 — go-first penalty / standoffs + spoiler-on-leader.
#  - Go-first penalty: attempting to win while opponents still hold many OPEN answers gets you
#    answered, so a savvy deck WAITS. p_attempt is scaled down by how loaded the table's interaction
#    is; as attrition drains those reserves the standoff breaks and someone is finally forced to go.
#  - Spoiler: an out-of-contention seat (clearly trailing, late game) spends its remaining interaction
#    to deny the table's LEADER rather than act randomly — a big reason the frontrunner can't close.
GO_FIRST_CAUTION = 0.55       # max fraction p_attempt is suppressed when the table is fully loaded
STANDOFF_OPEN_REF = 6.0       # reference open-reserve per opponent for normalizing the caution
GO_FIRST_IMPATIENCE = 4.0     # turns past its clock over which a deck stops waiting (forced to commit) —
#                               this is what BREAKS a standoff: caution decays to 0, so games resolve
#                               instead of deadlocking (low attempts → high reserves → high caution → ∞)
SPOILER_MIN_TURN = 6          # spoiler etiquette only kicks in once the game is developed
SPOILER_SHARE_MAX = 0.15      # equity share below which a trailing seat turns spoiler (1/N≈0.25)
SPOILER_ANSWER_BONUS = 1.6    # willingness multiplier when a spoiler denies the leader (overrides equity)

# F4 — protection cancels answers ~1:1, but PROBABILISTICALLY per attempt (you only sometimes draw/hold
# a protection piece). Each landed answer is fizzled with prob = PROT_CANCEL_PER_PIECE × protection_count
# (capped). A protection-light casual combo gets a small bump; a protection-dense cEDH combo can survive
# the whole table — the "a win must survive THREE defenders, and free counters cancel them 1:1" story.
PROT_CANCEL_PER_PIECE = 0.11  # added chance an answer fizzles, per protection card in the deck
PROT_CANCEL_CAP = 0.75        # ceiling on per-answer fizzle chance (you can't be hexproof to everything)
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

# --- Stage 1.1 — mid-game attrition / inevitability win path ---------------------------------------
# The clock-only model gave a slow, interaction-dense deck NO way to win — its answers only delayed
# opponents, and the inevitability tiebreak only fired at MAX_TURNS (turn 24), which real games never
# reach (~T9). So a resilient "good-stuff" control deck (the kind experienced players rate highest)
# cratered. This adds the missing path: a deck that DOMINATES the resource war grinds the table out
# mid-game — a win driven by interaction + card advantage + resilience instead of raw speed. Each turn
# past ATTRITION_MIN_TURN the game resolves by grind with probability ATTRITION_RATE, the winner drawn
# weighted by grind-equity^GRIND_POWER among the living (so it favors — but doesn't guarantee — the
# resource leader). Interaction is weighted heaviest: out-answering the table IS the grind win.
ATTRITION_MIN_TURN = 6       # grind can't decide a game before it has developed
ATTRITION_RATE = 0.40        # MAX per-turn probability of an attrition finish (when the grind is lopsided)
# Margin gate — attrition fires in proportion to how much the resource LEADER out-grinds the field
# (leader's grind-equity minus the field MEAN), through a logistic. When the table is resource-even
# (a mirror, or a fast deck racing an equal-resource deck) the margin ≈ 0, so attrition stays out of the
# way and raw speed decides — protecting the speed/mirror anchors. A real control deck out-resourcing the
# pod gets a large margin and grinds it out. The gate (not the turn clock) is what suppresses attrition in
# even games, so MIN_TURN can stay early enough to catch real pods without diluting fast 1v1s. REF/STEEP
# were fit so margin≈0 fires rarely (speed anchor ~0.90) while a lopsided pod fires hard (LOTR dist 16→4).
ATTRITION_MARGIN_REF = 2.5   # grind-equity lead (over the field mean) at which firing hits half of ATTRITION_RATE
ATTRITION_MARGIN_STEEP = 1.5 # logistic steepness of the margin gate (sharp: near-zero firing when even)
GRIND_INTERACTION_W = 1.0    # answer density — the dominant grind-win driver
GRIND_CARDADV_W = 0.35       # card advantage refuels the grind
GRIND_RESILIENCE_W = 0.5     # protection + combo redundancy = survives disruption to reach the long game
GRIND_POWER = 2.5            # sharpens the weighted winner draw toward the resource leader
GRIND_HEAT_W = 0.80          # how much accrued archenemy heat (reputation) discounts a deck's grind-win
#                              capacity — the perennial lightning rod can't also win the war of attrition

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

# --- Workstream F (commander-politics-model.md) ----------------------------------------------------
# F1 — perception split + reputation/lightning-rod bias. The table targets off PERCEIVED threat, not
# true equity: perceived = live_threat × visibility + reputation. Two documented human distortions:
#  (1) VISIBILITY — combo/ramp ("durdle") decks are systematically UNDER-read while they set up (the
#      "fish that's actually a shark"), so they're under-answered; aggro/visible boards read at face
#      value. Multiplies the standing live-threat read. NOTE: live_threat's combo-imminence term is
#      large, so a *fast* combo still reads as the archenemy once it's about to go off — the discount
#      only hides a deck that is still durdling. F1 ships a combo/grind discount; F4 fills the full
#      per-archetype table (and folds in protection).
#  (2) REPUTATION / lightning-rod — once a deck is tagged the consensus archenemy the table keeps
#      focusing it semi-independent of board state, so the highest-perceived deck's win rate collapses
#      BELOW fair share (the empirical 11% archenemy). Accumulates while a deck holds the archenemy
#      role and decays slowly; a small static term gives the visibly-strongest deck standing heat.
# Full archetype-visibility table (F4 completed F1's combo/grind discount). Maps each archetype's
# perceived-vs-true threat distortion: combo/ramp are durdle decks the table under-reads ("the fish
# that's actually a shark"); a wide aggro board reads as scarier than its true equity (over-perceived
# lightning rod); control's reactive game is slightly under-read. midrange is the calibrated baseline.
ARCHETYPE_VISIBILITY: dict[str, float] = {
    "combo": 0.70,    # durdles toward a sudden win the table under-rates until it's imminent
    "grind": 0.82,    # ramp/draw engines accrue real threat quietly
    "control": 0.92,  # reactive, low-board game reads a touch under its true equity
    "midrange": 1.0,  # calibrated baseline
    "aggro": 1.10,    # a wide visible board over-reads as the scariest seat (lightning rod)
}
DEFAULT_VISIBILITY = 1.0
REPUTATION_BUMP = 1.0       # reputation gained each turn a deck is the consensus archenemy
REPUTATION_DECAY = 0.80     # per-turn multiplicative decay of accumulated reputation (fades slowly)
REPUTATION_W = 0.9          # weight of accumulated reputation in the perceived-threat score
REPUTATION_STATIC_W = 0.10  # pre-game lightning-rod: the visibly-strongest deck draws standing heat

# F5 — power presets: bundle the *social/format* knobs for a pod's power level. Coordination is the
# §3.6 axis (cEDH gangs the archenemy hard; a casual table coordinates poorly), and perception is
# sharper at higher power (tighter threat reads). PACING is reported, not forced — it emerges from the
# decks' own goldfish clocks (fast cEDH lists → ~5 turns; grindy casual decks → ~10–13), which is the
# model's deck-driven design (§1 pacing lever). "mid" equals the module defaults, so an un-preset run is
# unchanged. Applied as temporary `battle_params` overrides around a run by `simulate_match(preset=…)`.
# Casual tables also play more RECKLESSLY (less disciplined waiting), so go-first caution scales with
# power too — which is what keeps a loose casual pod from deadlocking into a stall the way a patient,
# answer-dense cEDH table would.
POWER_PRESETS: dict[str, dict[str, float]] = {
    "casual": {"ANSWER_COORDINATION": 0.68, "PERCEPTION_NOISE": 0.55, "GO_FIRST_CAUTION": 0.30},
    "mid": {"ANSWER_COORDINATION": 0.80, "PERCEPTION_NOISE": 0.40, "GO_FIRST_CAUTION": 0.55},
    "cedh": {"ANSWER_COORDINATION": 0.93, "PERCEPTION_NOISE": 0.22, "GO_FIRST_CAUTION": 0.65},
}

# Combo-awareness Layer 2: ground a combo deck's clock in its goldfish-measured assembly turn
# (`SimResult.combo_turn`) instead of a flat archetype offset. The goldfish assumes hardcasting +
# natural draw, so it's honest for SETUP/combo decks but overstates aggro/cheat decks (a blitzed or
# reanimated combo creature) — so we blend (not replace) and skip the "aggro" archetype entirely.
COMBO_CLOCK_W = 0.35  # weight on the grounded combo_turn vs. the archetype-offset estimate
COMBO_REDUNDANCY_SD = 0.1  # clock_sd reduction per extra combo line (more ways to assemble = steadier)
COMBO_MIN_SD = 0.9  # floor so redundancy can't make a deck implausibly deterministic

COMBO_PRIMARY_GAP = 4.0  # combo is the deck's PRIMARY plan if combo_turn <= commander-online + this

# Stage 0.1 — a deck's INCIDENTAL combo (carried by a non-combo archetype) counts as "online" / able to
# win only once the game reaches its goldfish assembly turn, within this slack (assembly variance). Until
# then the deck wins by beatdown at its (earlier) combat clock — NOT by an instant combo at it. This is
# the fix for fast aggro decks that merely *contain* a combo being scored as turn-3 combo kills.
COMBO_ONLINE_SLACK = 1.0

# Sensitivity band (legacy one-knob): re-run with the interaction-answer base scaled by +/- this.
# NOTE: this perturbs ONE parameter — it understates true uncertainty. The honest joint band comes
# from global SA over PRIORS below (simulation/sensitivity.py); the legacy band is kept only as a
# fast default and is labeled as interaction-only in the output.
SENSITIVITY = 0.25

# --- Expert-elicited priors for global sensitivity analysis (enhancement plan §D1) -----------------
# The module constants above are the *best-guess* point values; PRIORS gives each tunable parameter a
# plausible (low, high) range. Global SA (LHS/Morris) samples these jointly to produce an honest
# joint-parametric uncertainty band — instead of perturbing a single knob. Ranges are designer
# estimates (~±40% or domain-sensible), to be replaced by data-fit posteriors when outcomes exist.
# Discrete params (e.g. ARCHENEMY_ANSWERERS) are intentionally excluded from the continuous sweep.
PRIORS: dict[str, tuple[float, float]] = {
    "INTERACTION_ANSWER_BASE": (0.20, 0.42),
    "INTERACTION_ANSWER_PER_PT": (0.03, 0.06),
    "CARD_ADVANTAGE_REFILL": (0.02, 0.07),
    "ANSWER_CLOCK_PENALTY": (1.5, 3.0),
    "ANSWER_LETHAL_COMBO": (0.80, 1.0),
    "ANSWER_LETHAL_BEATDOWN": (0.40, 0.75),
    "ANSWER_EQUITY_SLOPE": (0.08, 0.28),
    "ANSWER_COORDINATION": (0.60, 0.95),
    "GO_FIRST_CAUTION": (0.30, 0.75),
    "SPOILER_ANSWER_BONUS": (1.2, 2.0),
    "THREAT_PROXIMITY_W": (1.5, 3.5),
    "THREAT_COMBO_IMMINENCE_W": (8.0, 18.0),
    "THREAT_CARDADV_W": (0.05, 0.30),
    "THREAT_BOARD_W": (1.0, 3.5),
    "THREAT_LIFE_W": (0.04, 0.12),
    "COMBO_CLOCK_W": (0.20, 0.50),
    # F1 perception/reputation knobs.
    "REPUTATION_W": (0.4, 1.4),
    "REPUTATION_DECAY": (0.65, 0.92),
    "REPUTATION_STATIC_W": (0.0, 0.25),
}

# Explainability thresholds: when a deck's per-line attribution should call out politics pressure.
EXPLAIN_ARCHENEMY_HI = 0.40  # held the archenemy role this share of turns → "drew the table"
EXPLAIN_DIED_FIRST_HI = 0.40  # eliminated first this often → "folds early"

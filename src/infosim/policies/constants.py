from __future__ import annotations


# --- thresholds (tunable; intentionally simple) -------------------------------
KING_LOW_GARRISON = 1000.0
KING_HIGH_UNREST = 50.0
KING_LOW_FOOD = 800.0
GOV_AUTONOMOUS_UNREST = 75.0     # governor acts alone above this
CMD_LOW_FOOD = 500.0             # commander sends urgent food cry below this
CMD_LOW_GARRISON = 600.0         # commander screams for reinforcement
SUPPRESS_DURATION = 12
SKIM_LOYALTY_THRESHOLD = 0.85    # smooth gate - only deeply virtuous never skim
SKIM_AMBITION_THRESHOLD = 0.3
SKIM_FRAC_MIN = 0.02              # baseline 2% of current stores per attempt
SKIM_FRAC_MAX = 0.06              # up to 6%, before disloyalty multiplier
KING_STRIKES_TO_DISMISS = 3       # consecutive bad reviews before sacking
# Single-sub fallback review thresholds.
KING_REVIEW_UNREST = 60.0
KING_REVIEW_GARRISON = 800.0
PEER_DEV_LOW = 1.0                # health below peer median by this much -> underperformance strike
PEER_DEV_HIGH = 0.8               # health above peer median by this much -> suspicion strike
REQUEST_DEADLINE = 60.0           # logical-time deadline for an INFO_REQUEST round-trip
REQUEST_TRUST_THRESHOLD = 0.5     # below this loyalty, the recipient may lie about a sub
# -----------------------------------------------------------------------------

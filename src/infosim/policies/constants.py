from __future__ import annotations


# Cross-genre institution mechanics. Genre-specific numbers (defense/supply/
# threat thresholds, review cutoffs) live in each scenario's RoleSpec.thresholds;
# only the genre-neutral tuning of corruption, suppression, review cadence, and
# the pull-based request protocol remains here.
SUPPRESS_DURATION = 12
SKIM_LOYALTY_THRESHOLD = 0.85    # smooth gate - only deeply virtuous never skim
SKIM_AMBITION_THRESHOLD = 0.3
SKIM_FRAC_MIN = 0.02              # baseline 2% of current stores per attempt
SKIM_FRAC_MAX = 0.06              # up to 6%, before disloyalty multiplier
KING_STRIKES_TO_DISMISS = 3       # consecutive bad reviews before sacking
PEER_DEV_LOW = 1.0                # health below peer median by this much -> underperformance strike
PEER_DEV_HIGH = 0.8               # health above peer median by this much -> suspicion strike
REQUEST_DEADLINE = 60.0           # logical-time deadline for an INFO_REQUEST round-trip
REQUEST_TRUST_THRESHOLD = 0.5     # below this loyalty, the recipient may lie about a sub
# -----------------------------------------------------------------------------

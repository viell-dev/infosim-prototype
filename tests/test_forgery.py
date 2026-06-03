from __future__ import annotations

from infosim.reports import forge_value
from infosim.scenarios.frontier import RULESET

STATS = RULESET.stats


def test_forge_inflates_positive_polarity() -> None:
    # garrison_strength polarity=+1 → forgery pushes value UP toward an implausibly rosy target.
    result = forge_value(true_belief=500.0, variable="garrison_strength", severity=0.5, stats=STATS)
    assert result > 500.0


def test_forge_understates_negative_polarity() -> None:
    # unrest polarity=-1 → forgery pushes value DOWN toward 0.
    result = forge_value(true_belief=80.0, variable="unrest", severity=0.5, stats=STATS)
    assert result < 80.0


def test_forge_severity_zero_is_truth() -> None:
    assert forge_value(true_belief=500.0, variable="garrison_strength", severity=0.0, stats=STATS) == 500.0


def test_forge_severity_one_reaches_target() -> None:
    # severity=1.0 fully replaces with target (2.5x for positive polarity).
    result = forge_value(true_belief=500.0, variable="garrison_strength", severity=1.0, stats=STATS)
    assert result == 500.0 * 2.5

from __future__ import annotations

import random

from infosim.actors import Actor, Traits
from infosim.reports import observe, relay


def _actor(**traits: float) -> Actor:
    return Actor(
        id="a",
        display_name="A",
        title="T",
        region="R",
        reports_to=None,
        traits=Traits(**traits),
    )


def test_perfect_actor_observes_close_to_truth() -> None:
    rng = random.Random(0)
    actor = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    report = observe(actor, "R.x", 1000.0, rng)
    # No observation_error variance (competence=1) and no fear bias.
    assert abs(report.estimated_value - 1000.0) < 1e-9
    assert report.confidence == 1.0


def test_fear_inflates_value() -> None:
    rng = random.Random(0)
    fearful = _actor(competence=1.0, honesty=1.0, fear=1.0, education=1.0)
    report = observe(fearful, "R.x", 1000.0, rng)
    # competence=1 -> no random noise; only fear bias remains.
    assert report.estimated_value > 1000.0


def test_relay_degrades_confidence() -> None:
    rng = random.Random(0)
    incoming_actor = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    report = observe(incoming_actor, "R.x", 500.0, rng)
    forwarder = _actor(competence=0.5, honesty=0.8, fear=0.0, education=0.5)
    relayed = relay(forwarder, report, rng)
    assert relayed.confidence < report.confidence
    assert relayed.source_chain == ["a", "a"]

from __future__ import annotations

import random

from infosim.actors import Actor, Traits
from infosim.reports import observe, relay


def _actor(**traits: float) -> Actor:
    return Actor(
        id="a",
        display_name="A",
        title="T",
        location="R",
        commander=None,
        traits=Traits(**traits),
    )


def test_perfect_actor_observes_truth_exactly() -> None:
    rng = random.Random(0)
    actor = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    report = observe(actor, "R.garrison_strength", 1000.0, rng)
    # competence=1 -> no observation noise; fear no longer applies at observation.
    assert abs(report.estimated_value - 1000.0) < 1e-9
    assert report.confidence == 1.0


def test_fear_does_not_affect_observation() -> None:
    rng = random.Random(0)
    fearful = _actor(competence=1.0, honesty=1.0, fear=1.0, education=1.0)
    report = observe(fearful, "R.garrison_strength", 1000.0, rng)
    # Fear bias has moved to relay() — observation should still be exact at competence=1.
    assert abs(report.estimated_value - 1000.0) < 1e-9


def test_fear_inflates_positive_polarity_at_relay() -> None:
    rng = random.Random(0)
    upstream = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    incoming = observe(upstream, "R.garrison_strength", 1000.0, rng)
    fearful_relay = _actor(competence=1.0, honesty=1.0, fear=1.0, education=1.0)
    relayed = relay(fearful_relay, incoming, rng)
    # garrison_strength polarity=+1 (low is bad) → fear pushes value up.
    assert relayed.estimated_value > 1000.0


def test_fear_understates_negative_polarity_at_relay() -> None:
    rng = random.Random(0)
    upstream = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    incoming = observe(upstream, "R.unrest", 100.0, rng)
    fearful_relay = _actor(competence=1.0, honesty=1.0, fear=1.0, education=1.0)
    relayed = relay(fearful_relay, incoming, rng)
    # unrest polarity=-1 (high is bad) → fear pushes value down.
    assert relayed.estimated_value < 100.0


def test_relay_degrades_confidence() -> None:
    rng = random.Random(0)
    upstream = _actor(competence=1.0, honesty=1.0, fear=0.0, education=1.0)
    report = observe(upstream, "R.garrison_strength", 500.0, rng)
    forwarder = _actor(competence=0.5, honesty=0.8, fear=0.0, education=0.5)
    relayed = relay(forwarder, report, rng)
    assert relayed.confidence < report.confidence
    assert relayed.source_chain == ["a", "a"]

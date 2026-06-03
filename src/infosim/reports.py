from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping

from .actors import Actor
from .ruleset import StatSpec


@dataclass
class Report:
    """A structured report. Mirrors blueprint §Information Transformation."""
    source_actor: str
    subject: str               # "<Region>.<variable>"
    estimated_value: float
    confidence: float          # 0..1
    urgency: float = 0.0       # 0..1, currently informational
    origin_time: float = 0.0
    source_chain: list[str] = field(default_factory=list)


def _variable_of(subject: str) -> str:
    return subject.split(".", 1)[1]


def forge_value(
    true_belief: float,
    variable: str,
    severity: float,
    stats: Mapping[str, StatSpec],
) -> float:
    """Replace a report value with a politically convenient lie.

    severity (0..1) scales how far the forged value moves from the actor's
    actual belief toward an "everything is fine" target. severity=1.0 means
    fully fabricated; severity=0.5 means a heavy lean.
    """
    polarity = stats[variable].polarity
    # "Fine" target: for positive polarity (garrison/food) push value high;
    # for negative polarity (unrest) push value low.
    if polarity == +1:
        target = max(true_belief, 1.0) * 2.5  # implausibly rosy
    else:
        target = 0.0
    return true_belief + (target - true_belief) * severity


def observe(actor: Actor, subject: str, true_value: float, rng: random.Random) -> Report:
    """Generate a fresh local observation. Competence-noise only — no fear/corruption here.

    Fear, interpretation, and corruption biases live in relay(): an actor's own perception
    is what it actually believes; the biases enter when that belief is *reported* upward.
    """
    err_scale = (1.0 - actor.traits.competence) * 0.25 * max(abs(true_value), 1.0)
    observation_error = rng.gauss(0.0, err_scale)
    confidence = 0.4 + 0.6 * actor.traits.competence
    return Report(
        source_actor=actor.id,
        subject=subject,
        estimated_value=true_value + observation_error,
        confidence=confidence,
        origin_time=0.0,
        source_chain=[actor.id],
    )


def relay(
    actor: Actor,
    incoming: Report,
    rng: random.Random,
    stats: Mapping[str, StatSpec],
) -> Report:
    """Apply this actor's transformation when forwarding a report upward."""
    val = incoming.estimated_value
    polarity = stats[_variable_of(incoming.subject)].polarity

    # interpretation_bias: low education -> noisier numbers
    interp_scale = (1.0 - actor.traits.education) * 0.05 * max(abs(val), 1.0)
    interpretation_bias = rng.gauss(0.0, interp_scale)

    # corruption_bias: low honesty -> shave value toward what a superior wants to hear,
    # i.e. toward the "good" direction for this variable.
    corruption_bias = polarity * (1.0 - actor.traits.honesty) * 0.08 * max(abs(val), 1.0)

    # fear_bias: suppress bad news. For polarity=+1 (low is bad) → inflate value.
    # For polarity=-1 (high is bad, e.g. unrest) → understate value.
    fear_bias = polarity * actor.traits.fear * 0.10 * max(abs(val), 1.0)

    # transmission_loss: confidence degrades per hop, but education softens the loss.
    new_confidence = max(0.05, incoming.confidence * (0.85 + 0.1 * actor.traits.education))

    new_value = val + interpretation_bias + corruption_bias + fear_bias

    return Report(
        source_actor=actor.id,
        subject=incoming.subject,
        estimated_value=new_value,
        confidence=new_confidence,
        urgency=incoming.urgency,
        origin_time=incoming.origin_time,
        source_chain=[*incoming.source_chain, actor.id],
    )

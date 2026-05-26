from __future__ import annotations

import random
from dataclasses import dataclass, field

from .actors import Actor


@dataclass
class Report:
    """A structured report. Mirrors blueprint §Information Transformation."""
    source_actor: str
    subject: str               # e.g. "Frontier.garrison_strength"
    estimated_value: float
    confidence: float          # 0..1
    urgency: float = 0.0       # 0..1, currently informational
    origin_tick: int = 0
    source_chain: list[str] = field(default_factory=list)


def observe(actor: Actor, subject: str, true_value: float, rng: random.Random) -> Report:
    """Generate a fresh local observation."""
    # observation_error scales inversely with competence
    err_scale = (1.0 - actor.traits.competence) * 0.25 * max(abs(true_value), 1.0)
    observation_error = rng.gauss(0.0, err_scale)
    # fear suppresses bad news (negative deviations from a presumed "good" baseline get understated)
    # For garrison strength: low = bad. So fear pushes value up.
    fear_bias = actor.traits.fear * 0.10 * max(abs(true_value), 1.0)

    estimated = true_value + observation_error + fear_bias
    confidence = 0.4 + 0.6 * actor.traits.competence
    return Report(
        source_actor=actor.id,
        subject=subject,
        estimated_value=estimated,
        confidence=confidence,
        origin_tick=0,
        source_chain=[actor.id],
    )


def relay(actor: Actor, incoming: Report, rng: random.Random) -> Report:
    """Apply this actor's transformation when forwarding a report upward."""
    val = incoming.estimated_value

    # interpretation_bias: low education -> rounder, noisier numbers
    interp_scale = (1.0 - actor.traits.education) * 0.05 * max(abs(val), 1.0)
    interpretation_bias = rng.gauss(0.0, interp_scale)

    # corruption_bias: low honesty -> shave value to flatter superior (assume superior wants "stable")
    # We model it as drift toward a comfortable baseline (the value already reported * 1.05).
    corruption_bias = (1.0 - actor.traits.honesty) * 0.08 * val

    # fear_bias: same direction as observation
    fear_bias = actor.traits.fear * 0.05 * max(abs(val), 1.0)

    # transmission_loss: confidence degrades per hop
    new_confidence = max(0.05, incoming.confidence * (0.85 + 0.1 * actor.traits.education))

    new_value = val + interpretation_bias + corruption_bias + fear_bias

    return Report(
        source_actor=actor.id,
        subject=incoming.subject,
        estimated_value=new_value,
        confidence=new_confidence,
        urgency=incoming.urgency,
        origin_tick=incoming.origin_tick,
        source_chain=[*incoming.source_chain, actor.id],
    )

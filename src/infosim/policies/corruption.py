from __future__ import annotations

from typing import TYPE_CHECKING

from .constants import (
    SKIM_AMBITION_THRESHOLD,
    SKIM_FRAC_MAX,
    SKIM_FRAC_MIN,
    SKIM_LOYALTY_THRESHOLD,
)

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


def _maybe_skim(sim: "Simulation", actor: "Actor", traits=None) -> None:
    """A disloyal, ambitious actor quietly extracts food from their own stats.

    Stochastic: probability per decide cycle is ``ambition * (1 - loyalty)^2``.
    Magnitude is a small random fraction of current stores, scaled by how
    disloyal the actor is. The actor's stats drop; their belief is NOT updated
    to match — the next observation surfaces the loss honestly, but if they
    forge their reports it never leaves them.

    ``traits`` defaults to the actor's own; for a vacant office governed by a
    regent it is the regent's traits (an honest regent never skims the seat).
    """
    traits = traits if traits is not None else actor.traits
    if traits.loyalty >= SKIM_LOYALTY_THRESHOLD:
        return
    if traits.ambition < SKIM_AMBITION_THRESHOLD:
        return
    available = actor.stats.get(sim.supply_stat, 0.0)
    if available <= 0:
        return

    # Smooth probability curve. (1 - loyalty)^2 means perfectly loyal -> 0,
    # mildly loyal still very rare, deeply disloyal frequent. Hard gates at
    # SKIM_LOYALTY_THRESHOLD and SKIM_AMBITION_THRESHOLD keep the very
    # virtuous immune so unit tests stay deterministic.
    disloyalty = 1.0 - traits.loyalty
    p = traits.ambition * disloyalty * disloyalty
    if sim.rng.random() >= p:
        return

    frac = sim.rng.uniform(SKIM_FRAC_MIN, SKIM_FRAC_MAX) * (1.0 + disloyalty)
    take = min(available, available * frac)
    if take <= 0:
        return
    actor.stats[sim.supply_stat] = available - take
    sim.event_log.emit(
        sim.now,
        "skim",
        f"[{actor.location}] {actor.title} {actor.display_name} skims {take:.0f} "
        f"{sim.supply_stat} ({available:.0f} → {actor.stats[sim.supply_stat]:.0f})",
        actor=actor.id,
        location=actor.location,
        amount=take,
        fraction=frac,
    )

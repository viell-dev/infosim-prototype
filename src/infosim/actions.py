from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .sim import Simulation


@dataclass
class ActionInFlight:
    """A physical action in progress (a marching column, a suppression campaign).

    Distinct from messages: these mutate true state on completion.
    """
    start_tick: int
    complete_tick: int
    actor_id: str
    description: str
    effect_fn: Callable[["Simulation"], None]


def transfer_garrison(
    sim: "Simulation",
    actor_id: str,
    src_region: str,
    dst_region: str,
    magnitude: float,
) -> ActionInFlight | None:
    """Subtract magnitude from src immediately, add to dst after travel ticks.

    Returns None if src doesn't have enough garrison to spare or src==dst.
    """
    if src_region == dst_region or magnitude <= 0:
        return None
    src = sim.world.regions[src_region]
    available = src.state.get("garrison_strength", 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.state["garrison_strength"] = available - moved
    sim.event_log.emit(
        sim.tick,
        "action_started",
        f"[{src_region}] {moved:.0f} troops depart for {dst_region} "
        f"(eta t={sim.tick + sim.world.travel_ticks(src_region, dst_region)})",
        actor=actor_id,
        kind_detail="transfer_garrison",
        src_region=src_region,
        dst_region=dst_region,
        magnitude=moved,
    )
    travel = sim.world.travel_ticks(src_region, dst_region)

    def arrive(s: "Simulation") -> None:
        dst = s.world.regions[dst_region]
        before = dst.state.get("garrison_strength", 0.0)
        dst.state["garrison_strength"] = before + moved
        s.event_log.emit(
            s.tick,
            "action_completed",
            f"[{dst_region}] {moved:.0f} reinforcements arrive "
            f"(garrison {before:.0f} → {dst.state['garrison_strength']:.0f})",
            actor=actor_id,
            kind_detail="transfer_garrison_arrive",
            region=dst_region,
            magnitude=moved,
        )

    return ActionInFlight(
        start_tick=sim.tick,
        complete_tick=sim.tick + travel,
        actor_id=actor_id,
        description=f"transfer {moved:.0f} garrison {src_region}→{dst_region}",
        effect_fn=arrive,
    )


def suppress_unrest(
    sim: "Simulation",
    actor_id: str,
    region: str,
    duration: int,
    competence: float,
    rng: random.Random,
) -> ActionInFlight:
    """Run a suppression campaign for `duration` ticks; outcome modulated by competence."""
    backlash_chance = max(0.0, 0.3 - 0.3 * competence)  # incompetent → backlash risk
    roll = rng.random()
    backfires = roll < backlash_chance

    sim.event_log.emit(
        sim.tick,
        "action_started",
        f"[{region}] suppression campaign begins (duration {duration}t, backlash risk {backlash_chance:.2f})",
        actor=actor_id,
        kind_detail="suppress_unrest",
        region=region,
        duration=duration,
    )

    def resolve(s: "Simulation") -> None:
        r = s.world.regions[region]
        before = r.state.get("unrest", 0.0)
        if backfires:
            delta = +15.0
            outcome = "backfired"
        else:
            delta = -25.0 * (0.5 + competence)
            outcome = "succeeded"
        after = max(0.0, before + delta)
        r.state["unrest"] = after
        s.event_log.emit(
            s.tick,
            "action_completed",
            f"[{region}] suppression {outcome}: unrest {before:.0f} → {after:.0f}",
            actor=actor_id,
            kind_detail="suppress_unrest_resolve",
            region=region,
            outcome=outcome,
            before=before,
            after=after,
        )

    return ActionInFlight(
        start_tick=sim.tick,
        complete_tick=sim.tick + duration,
        actor_id=actor_id,
        description=f"suppress unrest in {region}",
        effect_fn=resolve,
    )


def send_supplies(
    sim: "Simulation",
    actor_id: str,
    src_region: str,
    dst_region: str,
    magnitude: float,
) -> ActionInFlight | None:
    """Ship food from src to dst over travel ticks."""
    if src_region == dst_region or magnitude <= 0:
        return None
    src = sim.world.regions[src_region]
    available = src.state.get("food_stores", 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.state["food_stores"] = available - moved
    travel = sim.world.travel_ticks(src_region, dst_region)
    sim.event_log.emit(
        sim.tick,
        "action_started",
        f"[{src_region}] {moved:.0f} food shipped to {dst_region} "
        f"(eta t={sim.tick + travel})",
        actor=actor_id,
        kind_detail="send_supplies",
        src_region=src_region,
        dst_region=dst_region,
        magnitude=moved,
    )

    def arrive(s: "Simulation") -> None:
        dst = s.world.regions[dst_region]
        before = dst.state.get("food_stores", 0.0)
        dst.state["food_stores"] = before + moved
        s.event_log.emit(
            s.tick,
            "action_completed",
            f"[{dst_region}] {moved:.0f} food arrives "
            f"(stores {before:.0f} → {dst.state['food_stores']:.0f})",
            actor=actor_id,
            kind_detail="send_supplies_arrive",
            region=dst_region,
            magnitude=moved,
        )

    return ActionInFlight(
        start_tick=sim.tick,
        complete_tick=sim.tick + travel,
        actor_id=actor_id,
        description=f"send {moved:.0f} food {src_region}→{dst_region}",
        effect_fn=arrive,
    )

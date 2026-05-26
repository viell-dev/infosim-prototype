from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .scheduler import Event, EventKind

if TYPE_CHECKING:
    from .sim import Simulation


@dataclass
class ActionInFlight:
    """A physical action in progress (a marching column, a suppression campaign).

    Created and scheduled by policies; the scheduler delivers it as an
    ACTION_COMPLETE event at complete_time, at which point effect_fn(sim) runs.
    """
    start_time: float
    complete_time: float
    actor_id: str
    description: str
    effect_fn: Callable[["Simulation"], None]


def _schedule(sim: "Simulation", action: ActionInFlight) -> None:
    sim.scheduler.schedule(
        action.complete_time,
        Event(kind=EventKind.ACTION_COMPLETE, actor_id=action.actor_id, payload=action),
    )


def transfer_garrison(
    sim: "Simulation",
    actor_id: str,
    src_region: str,
    dst_region: str,
    magnitude: float,
) -> ActionInFlight | None:
    """Subtract magnitude from src immediately, add to dst after travel time."""
    if src_region == dst_region or magnitude <= 0:
        return None
    src = sim.world.regions[src_region]
    available = src.state.get("garrison_strength", 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.state["garrison_strength"] = available - moved
    travel = sim.world.travel_ticks(src_region, dst_region)
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{src_region}] {moved:.0f} troops depart for {dst_region} "
        f"(eta t={sim.now + travel:.0f})",
        actor=actor_id,
        kind_detail="transfer_garrison",
        src_region=src_region,
        dst_region=dst_region,
        magnitude=moved,
    )

    def arrive(s: "Simulation") -> None:
        dst = s.world.regions[dst_region]
        before = dst.state.get("garrison_strength", 0.0)
        dst.state["garrison_strength"] = before + moved
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{dst_region}] {moved:.0f} reinforcements arrive "
            f"(garrison {before:.0f} → {dst.state['garrison_strength']:.0f})",
            actor=actor_id,
            kind_detail="transfer_garrison_arrive",
            region=dst_region,
            magnitude=moved,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"transfer {moved:.0f} garrison {src_region}→{dst_region}",
        effect_fn=arrive,
    )
    _schedule(sim, action)
    return action


def suppress_unrest(
    sim: "Simulation",
    actor_id: str,
    region: str,
    duration: float,
    competence: float,
    rng: random.Random,
) -> ActionInFlight:
    """Run a suppression campaign for `duration` time; outcome modulated by competence."""
    backlash_chance = max(0.0, 0.3 - 0.3 * competence)
    roll = rng.random()
    backfires = roll < backlash_chance

    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{region}] suppression campaign begins (duration {duration:.0f}t, "
        f"backlash risk {backlash_chance:.2f})",
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
            s.now,
            "action_completed",
            f"[{region}] suppression {outcome}: unrest {before:.0f} → {after:.0f}",
            actor=actor_id,
            kind_detail="suppress_unrest_resolve",
            region=region,
            outcome=outcome,
            before=before,
            after=after,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + duration,
        actor_id=actor_id,
        description=f"suppress unrest in {region}",
        effect_fn=resolve,
    )
    _schedule(sim, action)
    return action


def send_supplies(
    sim: "Simulation",
    actor_id: str,
    src_region: str,
    dst_region: str,
    magnitude: float,
) -> ActionInFlight | None:
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
        sim.now,
        "action_started",
        f"[{src_region}] {moved:.0f} food shipped to {dst_region} "
        f"(eta t={sim.now + travel:.0f})",
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
            s.now,
            "action_completed",
            f"[{dst_region}] {moved:.0f} food arrives "
            f"(stores {before:.0f} → {dst.state['food_stores']:.0f})",
            actor=actor_id,
            kind_detail="send_supplies_arrive",
            region=dst_region,
            magnitude=moved,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"send {moved:.0f} food {src_region}→{dst_region}",
        effect_fn=arrive,
    )
    _schedule(sim, action)
    return action

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
    src_actor_id: str,
    dst_actor_id: str,
    magnitude: float,
) -> ActionInFlight | None:
    """Subtract magnitude from src actor's garrison, add to dst actor's after travel."""
    if src_actor_id == dst_actor_id or magnitude <= 0:
        return None
    src = sim.actors.get(src_actor_id)
    dst = sim.actors.get(dst_actor_id)
    if src is None or dst is None:
        return None
    available = src.stats.get("garrison_strength", 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.stats["garrison_strength"] = available - moved
    travel = sim.world.travel_ticks(src.location, dst.location)
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{src.location}] {moved:.0f} troops depart for {dst.location} "
        f"(eta t={sim.now + travel:.0f})",
        actor=actor_id,
        kind_detail="transfer_garrison",
        src_actor=src_actor_id,
        dst_actor=dst_actor_id,
        magnitude=moved,
    )

    def arrive(s: "Simulation") -> None:
        dst_now = s.actors.get(dst_actor_id)
        if dst_now is None:
            s.event_log.emit(
                s.now,
                "action_completed",
                f"{moved:.0f} reinforcements vanish — recipient {dst_actor_id} no longer in office",
                actor=actor_id,
                kind_detail="transfer_garrison_arrive",
                dst_actor=dst_actor_id,
                magnitude=moved,
            )
            return
        before = dst_now.stats.get("garrison_strength", 0.0)
        dst_now.stats["garrison_strength"] = before + moved
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{dst_now.location}] {moved:.0f} reinforcements arrive "
            f"(garrison {before:.0f} → {dst_now.stats['garrison_strength']:.0f})",
            actor=actor_id,
            kind_detail="transfer_garrison_arrive",
            dst_actor=dst_actor_id,
            magnitude=moved,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"transfer {moved:.0f} garrison {src_actor_id}→{dst_actor_id}",
        effect_fn=arrive,
    )
    _schedule(sim, action)
    return action


def suppress_unrest(
    sim: "Simulation",
    actor_id: str,
    target_actor_id: str,
    duration: float,
    competence: float,
    rng: random.Random,
) -> ActionInFlight:
    """Suppression campaign that modifies target actor's unrest stat after `duration`."""
    backlash_chance = max(0.0, 0.3 - 0.3 * competence)
    roll = rng.random()
    backfires = roll < backlash_chance

    target = sim.actors.get(target_actor_id)
    loc = target.location if target else "(absent)"
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{loc}] suppression campaign begins (duration {duration:.0f}t, "
        f"backlash risk {backlash_chance:.2f})",
        actor=actor_id,
        kind_detail="suppress_unrest",
        target_actor=target_actor_id,
        duration=duration,
    )

    def resolve(s: "Simulation") -> None:
        target_now = s.actors.get(target_actor_id)
        if target_now is None:
            return
        before = target_now.stats.get("unrest", 0.0)
        if backfires:
            delta = +15.0
            outcome = "backfired"
        else:
            delta = -25.0 * (0.5 + competence)
            outcome = "succeeded"
        after = max(0.0, before + delta)
        target_now.stats["unrest"] = after
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{target_now.location}] suppression {outcome}: unrest "
            f"{before:.0f} → {after:.0f}",
            actor=actor_id,
            kind_detail="suppress_unrest_resolve",
            target_actor=target_actor_id,
            outcome=outcome,
            before=before,
            after=after,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + duration,
        actor_id=actor_id,
        description=f"suppress unrest at {target_actor_id}",
        effect_fn=resolve,
    )
    _schedule(sim, action)
    return action


def send_supplies(
    sim: "Simulation",
    actor_id: str,
    src_actor_id: str,
    dst_actor_id: str,
    magnitude: float,
) -> ActionInFlight | None:
    if src_actor_id == dst_actor_id or magnitude <= 0:
        return None
    src = sim.actors.get(src_actor_id)
    dst = sim.actors.get(dst_actor_id)
    if src is None or dst is None:
        return None
    available = src.stats.get("food_stores", 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.stats["food_stores"] = available - moved
    travel = sim.world.travel_ticks(src.location, dst.location)
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{src.location}] {moved:.0f} food shipped to {dst.location} "
        f"(eta t={sim.now + travel:.0f})",
        actor=actor_id,
        kind_detail="send_supplies",
        src_actor=src_actor_id,
        dst_actor=dst_actor_id,
        magnitude=moved,
    )

    def arrive(s: "Simulation") -> None:
        dst_now = s.actors.get(dst_actor_id)
        if dst_now is None:
            return
        before = dst_now.stats.get("food_stores", 0.0)
        dst_now.stats["food_stores"] = before + moved
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{dst_now.location}] {moved:.0f} food arrives "
            f"(stores {before:.0f} → {dst_now.stats['food_stores']:.0f})",
            actor=actor_id,
            kind_detail="send_supplies_arrive",
            dst_actor=dst_actor_id,
            magnitude=moved,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"send {moved:.0f} food {src_actor_id}→{dst_actor_id}",
        effect_fn=arrive,
    )
    _schedule(sim, action)
    return action

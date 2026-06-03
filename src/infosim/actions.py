from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .scheduler import Event, EventKind

if TYPE_CHECKING:
    from .actors import Actor
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
    return transfer_stat(
        sim, actor_id, src_actor_id, dst_actor_id, sim.defense_stat,
        magnitude, "reinforcements", "transfer_garrison",
    )


def transfer_stat(
    sim: "Simulation",
    actor_id: str,
    src_actor_id: str,
    dst_actor_id: str,
    stat: str,
    magnitude: float,
    label: str | None = None,
    kind_detail: str = "transfer_stat",
) -> ActionInFlight | None:
    """Subtract a stat from one actor, then add it to another after travel."""
    if src_actor_id == dst_actor_id or magnitude <= 0:
        return None
    src = sim.actors.get(src_actor_id)
    dst = sim.actors.get(dst_actor_id)
    if src is None or dst is None:
        return None
    available = src.stats.get(stat, 0.0)
    moved = min(available, magnitude)
    if moved <= 0:
        return None
    src.stats[stat] = available - moved
    travel = sim.world.travel_ticks(src.location, dst.location)
    label = label or stat
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{src.location}] {moved:.0f} {label} depart for {dst.location} "
        f"(eta t={sim.now + travel:.0f})",
        actor=actor_id,
        kind_detail=kind_detail,
        src_actor=src_actor_id,
        dst_actor=dst_actor_id,
        stat=stat,
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
        before = dst_now.stats.get(stat, 0.0)
        dst_now.stats[stat] = before + moved
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{dst_now.location}] {moved:.0f} {label} arrive "
            f"({stat} {before:.0f} → {dst_now.stats[stat]:.0f})",
            actor=actor_id,
            kind_detail=f"{kind_detail}_arrive",
            dst_actor=dst_actor_id,
            stat=stat,
            magnitude=moved,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"transfer {moved:.0f} {stat} {src_actor_id}→{dst_actor_id}",
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
        before = target_now.stats.get(sim.threat_stat, 0.0)
        if backfires:
            delta = +15.0
            outcome = "backfired"
        else:
            delta = -25.0 * (0.5 + competence)
            outcome = "succeeded"
        after = max(0.0, before + delta)
        target_now.stats[sim.threat_stat] = after
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{target_now.location}] suppression {outcome}: {sim.threat_stat} "
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
    return transfer_stat(
        sim, actor_id, src_actor_id, dst_actor_id, sim.supply_stat,
        magnitude, sim.supply_stat, "send_supplies",
    )


def defend_location(sim: "Simulation", actor: "Actor") -> None:
    """Spend this actor's defense stat to reduce the worst threat at their
    current location. Genre-agnostic: defense_stat vs threat_stat from the
    ruleset (garrison vs unrest, ships vs alien_presence, …).
    """
    threat_stat = sim.threat_stat
    defense_stat = sim.defense_stat
    if threat_stat is None or defense_stat is None:
        return
    holders = [a for a in sim.actors.values() if a.location == actor.location]
    targets = [a for a in holders if a.stats.get(threat_stat, 0.0) > 0]
    if not targets:
        return
    target = max(targets, key=lambda a: a.stats.get(threat_stat, 0.0))
    before = target.stats.get(threat_stat, 0.0)
    defense = actor.stats.get(defense_stat, 0.0)
    reduction = min(before, defense * (4.0 + 8.0 * actor.traits.competence))
    if reduction <= 0:
        return
    target.stats[threat_stat] = before - reduction
    sim.event_log.emit(
        sim.now,
        "defense",
        f"[{actor.location}] {actor.title} {actor.display_name} defends with "
        f"{defense:.0f} {defense_stat}: {threat_stat} {before:.0f} → "
        f"{target.stats[threat_stat]:.0f}",
        actor=actor.id,
        target_actor=target.id,
        location=actor.location,
        stat=threat_stat,
        ships=defense,
        before=before,
        after=target.stats[threat_stat],
    )


def move_actor(
    sim: "Simulation",
    actor_id: str,
    target_location: str,
    assigned_commander: str | None = None,
) -> ActionInFlight | None:
    mover = sim.actors.get(actor_id)
    if mover is None or mover.location == target_location:
        return None
    if target_location not in sim.world.locations:
        return None
    travel = sim.world.travel_ticks(mover.location, target_location)
    origin = mover.location
    sim.event_log.emit(
        sim.now,
        "action_started",
        f"[{origin}] {mover.title} {mover.display_name} departs for {target_location} "
        f"(eta t={sim.now + travel:.0f})",
        actor=actor_id, kind_detail="move_actor",
        origin=origin, target_location=target_location,
        assigned_commander=assigned_commander,
    )

    def arrive(s: "Simulation") -> None:
        mover_now = s.actors.get(actor_id)
        if mover_now is None:
            return
        before_location = mover_now.location
        mover_now.location = target_location
        if assigned_commander is not None:
            mover_now.commander = assigned_commander
        s.event_log.emit(
            s.now,
            "action_completed",
            f"[{target_location}] {mover_now.title} {mover_now.display_name} arrives "
            f"from {before_location}",
            actor=actor_id, kind_detail="move_actor_arrive",
            origin=before_location, target_location=target_location,
            assigned_commander=assigned_commander,
        )

    action = ActionInFlight(
        start_time=sim.now,
        complete_time=sim.now + travel,
        actor_id=actor_id,
        description=f"move {actor_id} to {target_location}",
        effect_fn=arrive,
    )
    _schedule(sim, action)
    return action

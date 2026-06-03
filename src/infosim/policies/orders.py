from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import (
    defend_location,
    move_actor,
    send_supplies,
    suppress_unrest,
    transfer_garrison,
)
from ..orders import Order, OrderKind
from .constants import SUPPRESS_DURATION
from .hierarchy import _route_to_subordinate, _subordinates

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


def _dispatch_order(
    sim: "Simulation",
    issuer: "Actor",
    recipient: "Actor",
    kind: OrderKind,
    target_actor: str,
    magnitude: float,
    deadline_offset: int = 60,
    priority: int = 1,
    target_location: str | None = None,
    assigned_commander: str | None = None,
) -> None:
    travel = sim.world.travel_ticks(issuer.location, recipient.location)
    order = Order(
        id=next(sim._order_ids),
        issuer=issuer.id,
        recipient=recipient.id,
        kind=kind,
        target_actor=target_actor,
        magnitude=magnitude,
        issued_time=sim.now,
        deadline_time=sim.now + deadline_offset,
        priority=priority,
        target_location=target_location,
        assigned_commander=assigned_commander,
    )
    msg = sim.bus.dispatch_order(
        sender_actor=issuer.id,
        recipient_actor=recipient.id,
        origin_region=issuer.location,
        destination_region=recipient.location,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=order,
    )
    sim.event_log.emit(
        sim.now,
        "order_dispatched",
        f"[{issuer.location}] {issuer.title} {issuer.display_name} orders "
        f"{recipient.title} {recipient.display_name}: "
        f"{kind.value} {target_actor} (magnitude {magnitude:.0f}, eta t={msg.eta_time:.0f})",
        order_id=order.id,
        issuer=issuer.id,
        recipient=recipient.id,
        order_kind=kind.value,
        target_actor=target_actor,
        target_location=target_location,
        assigned_commander=assigned_commander,
        magnitude=magnitude,
        eta_time=msg.eta_time,
    )


def _handle_middle_order(sim: "Simulation", actor: "Actor", order: "Order") -> None:
    """Generic order handling at any middle rung.

    Targets self  -> execute locally.
    Targets a direct subordinate -> for SUPPRESS, delegate downward; for
        REINFORCE / SEND_SUPPLIES, transfer from own stats directly to them.
    Targets a deeper actor -> forward the order to whichever direct sub
        covers that target's chain (the deeper layer handles delivery from
        there). This is how arbitrary depth works without the engine knowing
        about it.
    Targets an unreachable actor -> drop with a log entry.
    """
    if order.target_actor == actor.id:
        if order.kind is OrderKind.SUPPRESS_UNREST:
            suppress_unrest(
                sim, actor.id, target_actor_id=actor.id,
                duration=SUPPRESS_DURATION,
                competence=actor.traits.competence, rng=sim.rng,
            )
        elif order.kind is OrderKind.MOVE_TO_LOCATION and order.target_location is not None:
            move_actor(sim, actor.id, order.target_location, order.assigned_commander)
        elif order.kind is OrderKind.DEFEND_LOCATION:
            defend_location(sim, actor)
        # REINFORCE / SEND_SUPPLIES targeted at self are a no-op - the
        # actor would be transferring from themselves to themselves.
        return

    direct_sub = next(
        (s for s in _subordinates(sim, actor) if s.id == order.target_actor),
        None,
    )
    if direct_sub is not None:
        if order.kind is OrderKind.REINFORCE:
            transfer_garrison(
                sim, actor.id, src_actor_id=actor.id,
                dst_actor_id=direct_sub.id, magnitude=order.magnitude,
            )
        elif order.kind is OrderKind.SEND_SUPPLIES:
            send_supplies(
                sim, actor.id, src_actor_id=actor.id,
                dst_actor_id=direct_sub.id, magnitude=order.magnitude,
            )
        elif order.kind is OrderKind.SUPPRESS_UNREST:
            _dispatch_order(
                sim, actor, direct_sub, OrderKind.SUPPRESS_UNREST,
                target_actor=direct_sub.id,
                magnitude=order.magnitude, priority=order.priority,
            )
        elif order.kind in (OrderKind.MOVE_TO_LOCATION, OrderKind.DEFEND_LOCATION):
            _dispatch_order(
                sim, actor, direct_sub, order.kind,
                target_actor=direct_sub.id,
                magnitude=order.magnitude, priority=order.priority,
                target_location=order.target_location,
                assigned_commander=order.assigned_commander,
            )
        return

    # Deeper target - forward to the direct sub on the path.
    routed_via = _route_to_subordinate(sim, actor, order.target_actor)
    if routed_via is None:
        sim.event_log.emit(
            sim.now, "order_unroutable",
            f"[{actor.location}] {actor.title} {actor.display_name} cannot route "
            f"{order.kind.value} {order.target_actor} — not in chain",
            actor=actor.id, order_id=order.id, target_actor=order.target_actor,
        )
        return
    _dispatch_order(
        sim, actor, routed_via, order.kind,
        target_actor=order.target_actor,
        magnitude=order.magnitude, priority=order.priority,
        target_location=order.target_location,
        assigned_commander=order.assigned_commander,
    )

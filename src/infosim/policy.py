from __future__ import annotations

from typing import TYPE_CHECKING

from .actions import send_supplies, suppress_unrest, transfer_garrison
from .orders import Order, OrderKind

if TYPE_CHECKING:
    from .actors import Actor
    from .sim import Simulation


# --- thresholds (tunable; intentionally simple) -------------------------------
KING_LOW_GARRISON = 1000.0
KING_HIGH_UNREST = 50.0
KING_LOW_FOOD = 800.0
GOV_AUTONOMOUS_UNREST = 75.0     # governor acts alone above this
CMD_LOW_FOOD = 500.0             # commander sends urgent food cry below this
CMD_LOW_GARRISON = 600.0         # commander screams for reinforcement
SUPPRESS_DURATION = 12
# -----------------------------------------------------------------------------


def _dispatch_order(
    sim: "Simulation",
    issuer: "Actor",
    recipient: "Actor",
    kind: OrderKind,
    target_region: str,
    magnitude: float,
    deadline_offset: int = 60,
    priority: int = 1,
) -> None:
    travel = sim.world.travel_ticks(issuer.region, recipient.region)
    order = Order(
        id=next(sim._order_ids),
        issuer=issuer.id,
        recipient=recipient.id,
        kind=kind,
        target_region=target_region,
        magnitude=magnitude,
        issued_tick=sim.tick,
        deadline_tick=sim.tick + deadline_offset,
        priority=priority,
    )
    msg = sim.bus.dispatch_order(
        sender_actor=issuer.id,
        recipient_actor=recipient.id,
        origin_region=issuer.region,
        destination_region=recipient.region,
        base_travel_ticks=travel,
        dispatch_tick=sim.tick,
        payload=order,
    )
    sim.event_log.emit(
        sim.tick,
        "order_dispatched",
        f"[{issuer.region}] {issuer.title} {issuer.display_name} orders "
        f"{recipient.title} {recipient.display_name}: "
        f"{kind.value} {target_region} (magnitude {magnitude:.0f}, eta t={msg.eta_tick})",
        order_id=order.id,
        issuer=issuer.id,
        recipient=recipient.id,
        order_kind=kind.value,
        target_region=target_region,
        magnitude=magnitude,
        eta_tick=msg.eta_tick,
    )


def _subordinates(sim: "Simulation", actor: "Actor") -> list["Actor"]:
    return [a for a in sim.actors.values() if a.reports_to == actor.id]


# --- king ---------------------------------------------------------------------
def decide_king(sim: "Simulation", actor: "Actor") -> None:
    """King issues orders based on his belief state.

    Targeting rules (M2 scope):
      - For a direct subordinate's own region: only SUPPRESS_UNREST is meaningful;
        the King has no chain to source reinforcement from.
      - For a region one level deeper (subordinate-of-subordinate): full menu —
        REINFORCE, SUPPRESS_UNREST, SEND_SUPPLIES — all routed through the
        intermediate subordinate, whose region acts as the source.
    """
    for sub in _subordinates(sim, actor):
        # Sub's own region — suppression only.
        _maybe_suppress(sim, actor, sub, sub.region)

        # Forward regions reachable via sub.
        for deeper in _subordinates(sim, sub):
            _maybe_reinforce(sim, actor, sub, deeper.region)
            _maybe_suppress(sim, actor, sub, deeper.region)
            _maybe_send_supplies(sim, actor, sub, deeper.region)


def _maybe_reinforce(sim: "Simulation", king: "Actor", routed_via: "Actor", target_region: str) -> None:
    belief = king.known.get(sim.subject_for(target_region, "garrison_strength"))
    if not belief or belief.value >= KING_LOW_GARRISON:
        return
    magnitude = (KING_LOW_GARRISON - belief.value) * 0.6
    _dispatch_order(sim, king, routed_via, OrderKind.REINFORCE, target_region,
                    magnitude=magnitude, priority=2)


def _maybe_suppress(sim: "Simulation", king: "Actor", routed_via: "Actor", target_region: str) -> None:
    belief = king.known.get(sim.subject_for(target_region, "unrest"))
    if not belief or belief.value <= KING_HIGH_UNREST:
        return
    _dispatch_order(sim, king, routed_via, OrderKind.SUPPRESS_UNREST, target_region,
                    magnitude=belief.value, priority=2)


def _maybe_send_supplies(sim: "Simulation", king: "Actor", routed_via: "Actor", target_region: str) -> None:
    belief = king.known.get(sim.subject_for(target_region, "food_stores"))
    if not belief or belief.value >= KING_LOW_FOOD:
        return
    magnitude = (KING_LOW_FOOD - belief.value) * 0.8
    _dispatch_order(sim, king, routed_via, OrderKind.SEND_SUPPLIES, target_region,
                    magnitude=magnitude, priority=1)


# --- governor -----------------------------------------------------------------
def decide_governor(sim: "Simulation", actor: "Actor") -> None:
    """Governor: process inbox, possibly forward to commander, possibly act autonomously."""
    subs = _subordinates(sim, actor)
    cmd = subs[0] if subs else None

    # 1. process inbox orders
    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.tick,
            "order_received",
            f"[{actor.region}] {actor.title} {actor.display_name} acts on "
            f"{order.kind.value} {order.target_region} from {order.issuer}",
            order_id=order.id,
            recipient=actor.id,
            order_kind=order.kind.value,
            target_region=order.target_region,
        )

        if order.kind == OrderKind.REINFORCE and order.target_region != actor.region:
            # send troops from our region toward the frontier
            action = transfer_garrison(
                sim, actor.id, actor.region, order.target_region, order.magnitude,
            )
            if action is not None:
                sim.actions_in_flight.append(action)
        elif order.kind == OrderKind.SUPPRESS_UNREST:
            if cmd is not None and order.target_region == cmd.region:
                # delegate to the commander
                _dispatch_order(
                    sim, actor, cmd, OrderKind.SUPPRESS_UNREST,
                    order.target_region, order.magnitude, priority=order.priority,
                )
            elif order.target_region == actor.region:
                # governor handles their own region
                action = suppress_unrest(
                    sim, actor.id, actor.region, SUPPRESS_DURATION,
                    competence=actor.traits.competence, rng=sim.rng,
                )
                sim.actions_in_flight.append(action)
        elif order.kind == OrderKind.SEND_SUPPLIES and order.target_region != actor.region:
            action = send_supplies(
                sim, actor.id, actor.region, order.target_region, order.magnitude,
            )
            if action is not None:
                sim.actions_in_flight.append(action)

    # 2. autonomous suppression if local unrest belief is severe
    own_unrest = actor.known.get(sim.subject_for(actor.region, "unrest"))
    if own_unrest and own_unrest.value > GOV_AUTONOMOUS_UNREST:
        sim.event_log.emit(
            sim.tick,
            "autonomous_action",
            f"[{actor.region}] {actor.title} {actor.display_name} acts on own initiative: "
            f"suppress unrest (believed {own_unrest.value:.0f})",
            actor=actor.id,
            region=actor.region,
        )
        action = suppress_unrest(
            sim, actor.id, actor.region, SUPPRESS_DURATION,
            competence=actor.traits.competence, rng=sim.rng,
        )
        sim.actions_in_flight.append(action)


# --- commander ----------------------------------------------------------------
def decide_commander(sim: "Simulation", actor: "Actor") -> None:
    """Commander: execute orders; autonomously raise the alarm on critical lows."""
    # 1. process inbox
    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.tick,
            "order_received",
            f"[{actor.region}] {actor.title} {actor.display_name} acts on "
            f"{order.kind.value} {order.target_region} from {order.issuer}",
            order_id=order.id,
            recipient=actor.id,
            order_kind=order.kind.value,
            target_region=order.target_region,
        )
        if order.kind == OrderKind.SUPPRESS_UNREST and order.target_region == actor.region:
            action = suppress_unrest(
                sim, actor.id, actor.region, SUPPRESS_DURATION,
                competence=actor.traits.competence, rng=sim.rng,
            )
            sim.actions_in_flight.append(action)
        # REINFORCE / SEND_SUPPLIES targeted at the commander's region are handled by
        # the governor (the one with the source region's resources); the commander has
        # nothing to do but wait.

    # 2. autonomous urgent reports — these jump cadence and go straight to the governor
    if actor.reports_to is None:
        return
    superior = sim.actors[actor.reports_to]

    own_food = actor.known.get(sim.subject_for(actor.region, "food_stores"))
    if own_food and own_food.value < CMD_LOW_FOOD:
        _emit_urgent_report(sim, actor, superior, own_food.value, "food_stores", own_food.confidence)

    own_garrison = actor.known.get(sim.subject_for(actor.region, "garrison_strength"))
    if own_garrison and own_garrison.value < CMD_LOW_GARRISON:
        _emit_urgent_report(
            sim, actor, superior, own_garrison.value, "garrison_strength", own_garrison.confidence,
        )


def _emit_urgent_report(
    sim: "Simulation",
    actor: "Actor",
    superior: "Actor",
    value: float,
    variable: str,
    confidence: float,
) -> None:
    from .reports import Report  # local import to avoid cycles

    subject = sim.subject_for(actor.region, variable)
    report = Report(
        source_actor=actor.id,
        subject=subject,
        estimated_value=value,
        confidence=confidence,
        urgency=1.0,
        origin_tick=sim.tick,
        source_chain=[actor.id],
    )
    travel = sim.world.travel_ticks(actor.region, superior.region)
    msg = sim.bus.dispatch(
        sender_actor=actor.id,
        recipient_actor=superior.id,
        origin_region=actor.region,
        destination_region=superior.region,
        base_travel_ticks=travel,
        dispatch_tick=sim.tick,
        payload=report,
    )
    sim.event_log.emit(
        sim.tick,
        "urgent_report",
        f"[{actor.region}] {actor.title} {actor.display_name} sends URGENT report to "
        f"{superior.region}: {variable} ≈ {value:.0f} (eta t={msg.eta_tick})",
        sender=actor.id,
        recipient=superior.id,
        subject=subject,
        value=value,
        eta_tick=msg.eta_tick,
    )


# --- dispatch -----------------------------------------------------------------
POLICY_BY_TITLE = {
    "King": decide_king,
    "Governor": decide_governor,
    "Commander": decide_commander,
}


def run_policy(sim: "Simulation", actor: "Actor") -> None:
    fn = POLICY_BY_TITLE.get(actor.title)
    if fn is None:
        return
    fn(sim, actor)

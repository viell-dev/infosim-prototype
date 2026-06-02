from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import suppress_unrest
from ..orders import OrderKind
from .constants import (
    CMD_LOW_FOOD,
    CMD_LOW_GARRISON,
    GOV_AUTONOMOUS_UNREST,
    KING_HIGH_UNREST,
    KING_LOW_FOOD,
    KING_LOW_GARRISON,
    SUPPRESS_DURATION,
)
from .corruption import _maybe_skim
from .hierarchy import _subordinates
from .info_requests import _process_request_inbox
from .orders import _dispatch_order, _handle_middle_order
from .review import _review_subordinate

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


def decide_king(sim: "Simulation", actor: "Actor") -> None:
    """King issues orders based on his belief state.

    Targeting rules:
      - For a direct subordinate (e.g. a Governor): only SUPPRESS_UNREST is
        meaningful — the King has no chain to source reinforcement from.
      - For an actor one level deeper (e.g. a Commander under that Governor):
        full menu — REINFORCE, SUPPRESS_UNREST, SEND_SUPPLIES — all routed
        through the intermediate subordinate whose stats act as the source.
    """
    for sub in _subordinates(sim, actor):
        # Subordinate themself — suppression only.
        _maybe_suppress(sim, actor, sub, sub.id)

        # Forward actors reachable via sub.
        for deeper in _subordinates(sim, sub):
            _maybe_reinforce(sim, actor, sub, deeper.id)
            _maybe_suppress(sim, actor, sub, deeper.id)
            _maybe_send_supplies(sim, actor, sub, deeper.id)

        # Performance review — strikes against this sub.
        _review_subordinate(sim, actor, sub)


def _maybe_reinforce(
    sim: "Simulation",
    king: "Actor",
    routed_via: "Actor",
    target_actor: str,
) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "garrison_strength"))
    if not belief or belief.value >= KING_LOW_GARRISON:
        return
    magnitude = (KING_LOW_GARRISON - belief.value) * 0.6
    _dispatch_order(sim, king, routed_via, OrderKind.REINFORCE, target_actor,
                    magnitude=magnitude, priority=2)


def _maybe_suppress(
    sim: "Simulation",
    king: "Actor",
    routed_via: "Actor",
    target_actor: str,
) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "unrest"))
    if not belief or belief.value <= KING_HIGH_UNREST:
        return
    _dispatch_order(sim, king, routed_via, OrderKind.SUPPRESS_UNREST, target_actor,
                    magnitude=belief.value, priority=2)


def _maybe_send_supplies(
    sim: "Simulation",
    king: "Actor",
    routed_via: "Actor",
    target_actor: str,
) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "food_stores"))
    if not belief or belief.value >= KING_LOW_FOOD:
        return
    magnitude = (KING_LOW_FOOD - belief.value) * 0.8
    _dispatch_order(sim, king, routed_via, OrderKind.SEND_SUPPLIES, target_actor,
                    magnitude=magnitude, priority=1)


def decide_governor(sim: "Simulation", actor: "Actor") -> None:
    """Governor: process inbox, possibly forward to commander, possibly act autonomously."""
    _maybe_skim(sim, actor)

    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.now,
            "order_received",
            f"[{actor.location}] {actor.title} {actor.display_name} acts on "
            f"{order.kind.value} {order.target_actor} from {order.issuer}",
            order_id=order.id,
            recipient=actor.id,
            order_kind=order.kind.value,
            target_actor=order.target_actor,
        )
        _handle_middle_order(sim, actor, order)

    # autonomous suppression if local unrest belief is severe
    own_unrest = actor.known.get(sim.subject_for(actor.id, "unrest"))
    if own_unrest and own_unrest.value > GOV_AUTONOMOUS_UNREST:
        sim.event_log.emit(
            sim.now,
            "autonomous_action",
            f"[{actor.location}] {actor.title} {actor.display_name} acts on own initiative: "
            f"suppress unrest (believed {own_unrest.value:.0f})",
            actor=actor.id,
            location=actor.location,
        )
        suppress_unrest(
            sim, actor.id, target_actor_id=actor.id,
            duration=SUPPRESS_DURATION,
            competence=actor.traits.competence, rng=sim.rng,
        )


# --- commander ----------------------------------------------------------------
def decide_commander(sim: "Simulation", actor: "Actor") -> None:
    """Commander: execute orders; autonomously raise the alarm on critical lows."""
    _maybe_skim(sim, actor)

    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.now,
            "order_received",
            f"[{actor.location}] {actor.title} {actor.display_name} acts on "
            f"{order.kind.value} {order.target_actor} from {order.issuer}",
            order_id=order.id,
            recipient=actor.id,
            order_kind=order.kind.value,
            target_actor=order.target_actor,
        )
        if order.kind == OrderKind.SUPPRESS_UNREST and order.target_actor == actor.id:
            suppress_unrest(
                sim, actor.id, target_actor_id=actor.id,
                duration=SUPPRESS_DURATION,
                competence=actor.traits.competence, rng=sim.rng,
            )
        # REINFORCE / SEND_SUPPLIES targeted at the commander are handled by
        # the governor (who has the stockpile); commander just waits.

    # autonomous urgent reports - jump cadence, straight to the superior
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return

    own_food = actor.known.get(sim.subject_for(actor.id, "food_stores"))
    if own_food and own_food.value < CMD_LOW_FOOD:
        _emit_urgent_report(
            sim, actor, superior, own_food.value, "food_stores", own_food.confidence,
        )

    own_garrison = actor.known.get(sim.subject_for(actor.id, "garrison_strength"))
    if own_garrison and own_garrison.value < CMD_LOW_GARRISON:
        _emit_urgent_report(
            sim, actor, superior, own_garrison.value, "garrison_strength", own_garrison.confidence,
        )


def _emit_urgent_report(
    sim: "Simulation",
    actor: "Actor",
    superior: "Actor",
    value: float,
    stat: str,
    confidence: float,
) -> None:
    from ..reports import Report  # local import to avoid cycles

    subject = sim.subject_for(actor.id, stat)
    report = Report(
        source_actor=actor.id,
        subject=subject,
        estimated_value=value,
        confidence=confidence,
        urgency=1.0,
        origin_time=sim.now,
        source_chain=[actor.id],
    )
    travel = sim.world.travel_ticks(actor.location, superior.location)
    msg = sim.bus.dispatch(
        sender_actor=actor.id,
        recipient_actor=superior.id,
        origin_region=actor.location,
        destination_region=superior.location,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=report,
    )
    sim.event_log.emit(
        sim.now,
        "urgent_report",
        f"[{actor.location}] {actor.title} {actor.display_name} sends URGENT report to "
        f"{superior.location}: {stat} ≈ {value:.0f} (eta t={msg.eta_time:.0f})",
        sender=actor.id,
        recipient=superior.id,
        subject=subject,
        value=value,
        eta_time=msg.eta_time,
    )


# --- dispatch -----------------------------------------------------------------
POLICY_BY_TITLE = {
    "King": decide_king,
    "Governor": decide_governor,
    "Commander": decide_commander,
}


def run_policy(sim: "Simulation", actor: "Actor") -> None:
    # All actors handle their request inbox first - replies are short-cycle
    # and independent of role-specific decisions.
    _process_request_inbox(sim, actor)
    fn = POLICY_BY_TITLE.get(actor.title)
    if fn is None:
        return
    fn(sim, actor)

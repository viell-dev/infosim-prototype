from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import defend_location, suppress_unrest, transfer_stat
from ..orders import OrderKind
from .constants import SUPPRESS_DURATION
from .corruption import _maybe_skim
from .hierarchy import _subordinates
from .info_requests import _process_request_inbox
from .orders import _dispatch_order, _handle_middle_order
from .review import _review_subordinate

if TYPE_CHECKING:
    from ..actors import Actor
    from ..ruleset import RoleSpec
    from ..sim import Simulation


# Generic, genre-agnostic behaviors. A scenario's RoleSpec lists which of these
# run, in what order, parameterised by the role's production/decay/tax specs and
# thresholds. The same engine drives a medieval King and a sci-fi Captain — only
# the data differs.


# --- corruption ---------------------------------------------------------------
def behavior_skim(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    _maybe_skim(sim, actor)


# --- resource economy ---------------------------------------------------------
def behavior_produce(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Generate resources from a driver stat, scaled by competence."""
    for spec in role.production:
        driver = actor.stats.get(spec.driver_stat, 0.0)
        produced = max(0.0, driver * spec.rate * (spec.competence_curve + actor.traits.competence))
        if produced <= 0:
            continue
        before = actor.stats.get(spec.output_stat, 0.0)
        actor.stats[spec.output_stat] = before + produced
        sim.event_log.emit(
            sim.now,
            "mining",
            f"[{actor.location}] {actor.title} {actor.display_name} produces "
            f"{produced:.0f} {spec.output_stat} from {driver:.0f} {spec.driver_stat} "
            f"({before:.0f} → {actor.stats[spec.output_stat]:.0f})",
            actor=actor.id,
            location=actor.location,
            stat=spec.output_stat,
            driver_stat=spec.driver_stat,
            ships=driver,
            amount=produced,
        )


def behavior_consume(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Natural decay / usage of a resource each decide cycle."""
    for spec in role.decay:
        before = actor.stats.get(spec.stat, 0.0)
        if spec.driver_stat is not None:
            driver = actor.stats.get(spec.driver_stat, 0.0)
            if driver <= 0:
                continue
            consumed = min(before, driver * spec.rate)
            driver_note = f" for {driver:.0f} {spec.driver_stat}"
            driver_field: float | None = driver
        else:
            consumed = min(before, before * spec.rate)
            driver_note = ""
            driver_field = None
        if consumed <= 0:
            continue
        actor.stats[spec.stat] = before - consumed
        sim.event_log.emit(
            sim.now,
            "consumption",
            f"[{actor.location}] {actor.title} {actor.display_name} consumes "
            f"{consumed:.0f} {spec.stat}{driver_note} "
            f"({before:.0f} → {actor.stats[spec.stat]:.0f})",
            actor=actor.id,
            location=actor.location,
            stat=spec.stat,
            population=driver_field,
            amount=consumed,
        )


def behavior_tax(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Transfer a fraction of a resource upward to the commander."""
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return
    for spec in role.tax:
        available = actor.stats.get(spec.stat, 0.0)
        amount = available * spec.fraction
        if amount <= 0:
            continue
        transfer_stat(
            sim, actor.id, actor.id, superior.id,
            spec.stat, amount, spec.stat, spec.label,
        )


# --- order execution ----------------------------------------------------------
def behavior_execute_orders(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Drain the inbox; each order is dispatched through the generic
    middle-rung handler, which executes locally, transfers to a direct sub, or
    forwards deeper as appropriate (depth-agnostic).
    """
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


# --- apex command -------------------------------------------------------------
def behavior_issue_orders(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Apex policy: for each subordinate (and one level deeper) issue
    reinforcement / suppression / supply orders against belief, then review.

    Targeting:
      - The subordinate themself — suppression only (no chain to source
        reinforcement from).
      - An actor one level deeper — full menu, routed through the intermediate
        subordinate whose stats act as the source.
    """
    low_defense = role.thresholds.get("low_defense")
    low_supply = role.thresholds.get("low_supply")
    high_threat = role.thresholds.get("high_threat")
    for sub in _subordinates(sim, actor):
        _maybe_suppress(sim, actor, sub, sub.id, high_threat)
        for deeper in _subordinates(sim, sub):
            _maybe_reinforce(sim, actor, sub, deeper.id, low_defense)
            _maybe_suppress(sim, actor, sub, deeper.id, high_threat)
            _maybe_send_supplies(sim, actor, sub, deeper.id, low_supply)
        _review_subordinate(sim, actor, sub)


def _maybe_reinforce(
    sim: "Simulation", king: "Actor", routed_via: "Actor",
    target_actor: str, low_defense: float | None,
) -> None:
    if low_defense is None or sim.defense_stat is None:
        return
    belief = king.known.get(sim.subject_for(target_actor, sim.defense_stat))
    if not belief or belief.value >= low_defense:
        return
    magnitude = (low_defense - belief.value) * 0.6
    _dispatch_order(sim, king, routed_via, OrderKind.REINFORCE, target_actor,
                    magnitude=magnitude, priority=2)


def _maybe_suppress(
    sim: "Simulation", king: "Actor", routed_via: "Actor",
    target_actor: str, high_threat: float | None,
) -> None:
    if high_threat is None or sim.threat_stat is None:
        return
    belief = king.known.get(sim.subject_for(target_actor, sim.threat_stat))
    if not belief or belief.value <= high_threat:
        return
    _dispatch_order(sim, king, routed_via, OrderKind.SUPPRESS_UNREST, target_actor,
                    magnitude=belief.value, priority=2)


def _maybe_send_supplies(
    sim: "Simulation", king: "Actor", routed_via: "Actor",
    target_actor: str, low_supply: float | None,
) -> None:
    if low_supply is None or sim.supply_stat is None:
        return
    belief = king.known.get(sim.subject_for(target_actor, sim.supply_stat))
    if not belief or belief.value >= low_supply:
        return
    magnitude = (low_supply - belief.value) * 0.8
    _dispatch_order(sim, king, routed_via, OrderKind.SEND_SUPPLIES, target_actor,
                    magnitude=magnitude, priority=1)


def behavior_apex_defense_orders(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Apex/regional defense ordering: order any Commander whose believed local
    threat is high to defend their post (routed through the intermediate sub
    when the Commander is not a direct report).
    """
    high_threat = role.thresholds.get("high_threat")
    if high_threat is None or sim.threat_stat is None:
        return
    for sub in _subordinates(sim, actor):
        for defender in [sub, *_subordinates(sim, sub)]:
            if defender.title != "Commander":
                continue
            threat = actor.known.get(sim.subject_for(defender.id, sim.threat_stat))
            if threat and threat.value > high_threat:
                _dispatch_order(
                    sim, actor,
                    sub if defender.commander != actor.id else defender,
                    OrderKind.DEFEND_LOCATION, defender.id,
                    magnitude=threat.value, priority=3,
                )


# --- middle autonomy ----------------------------------------------------------
def behavior_autonomous_suppress(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Act alone to suppress unrest when local threat belief is severe."""
    threshold = role.thresholds.get("autonomous_threat")
    if threshold is None or sim.threat_stat is None:
        return
    own_threat = actor.known.get(sim.subject_for(actor.id, sim.threat_stat))
    if own_threat and own_threat.value > threshold:
        sim.event_log.emit(
            sim.now,
            "autonomous_action",
            f"[{actor.location}] {actor.title} {actor.display_name} acts on own initiative: "
            f"suppress unrest (believed {own_threat.value:.0f})",
            actor=actor.id,
            location=actor.location,
        )
        suppress_unrest(
            sim, actor.id, target_actor_id=actor.id,
            duration=SUPPRESS_DURATION,
            competence=actor.traits.competence, rng=sim.rng,
        )


def behavior_local_defense_orders(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Order the strongest local Commander to defend (or move in to) this post
    when own true threat is high.
    """
    threshold = role.thresholds.get("autonomous_threat")
    if threshold is None or sim.threat_stat is None or sim.defense_stat is None:
        return
    threat = actor.stats.get(sim.threat_stat, 0.0)
    if threat <= threshold:
        return
    defenders = [
        s for s in _subordinates(sim, actor)
        if s.title == "Commander" and s.stats.get(sim.defense_stat, 0.0) > 0
    ]
    if not defenders:
        return
    defender = max(defenders, key=lambda a: a.stats.get(sim.defense_stat, 0.0))
    if defender.location != actor.location:
        _dispatch_order(
            sim, actor, defender, OrderKind.MOVE_TO_LOCATION, defender.id,
            magnitude=0.0, priority=3, target_location=actor.location,
            assigned_commander=actor.id,
        )
        return
    _dispatch_order(
        sim, actor, defender, OrderKind.DEFEND_LOCATION, defender.id,
        magnitude=threat, priority=3,
    )


# --- leaf behaviors -----------------------------------------------------------
def behavior_defend(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Spend defense on local threat when both are present."""
    if sim.threat_stat is None or sim.defense_stat is None:
        return
    if actor.stats.get(sim.threat_stat, 0.0) > 0 and actor.stats.get(sim.defense_stat, 0.0) > 0:
        defend_location(sim, actor)


def behavior_urgent_reports(sim: "Simulation", actor: "Actor", role: "RoleSpec") -> None:
    """Jump cadence with an urgent report when own supply/defense belief is
    critically low.
    """
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return

    low_supply = role.thresholds.get("leaf_low_supply")
    if low_supply is not None and sim.supply_stat is not None:
        own_supply = actor.known.get(sim.subject_for(actor.id, sim.supply_stat))
        if own_supply and own_supply.value < low_supply:
            _emit_urgent_report(
                sim, actor, superior, own_supply.value, sim.supply_stat, own_supply.confidence,
            )

    low_defense = role.thresholds.get("leaf_low_defense")
    if low_defense is not None and sim.defense_stat is not None:
        own_defense = actor.known.get(sim.subject_for(actor.id, sim.defense_stat))
        if own_defense and own_defense.value < low_defense:
            _emit_urgent_report(
                sim, actor, superior, own_defense.value, sim.defense_stat, own_defense.confidence,
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
BEHAVIORS = {
    "skim": behavior_skim,
    "produce": behavior_produce,
    "consume": behavior_consume,
    "tax": behavior_tax,
    "execute_orders": behavior_execute_orders,
    "issue_orders": behavior_issue_orders,
    "apex_defense_orders": behavior_apex_defense_orders,
    "autonomous_suppress": behavior_autonomous_suppress,
    "local_defense_orders": behavior_local_defense_orders,
    "defend": behavior_defend,
    "urgent_reports": behavior_urgent_reports,
}


def run_policy(sim: "Simulation", actor: "Actor") -> None:
    # All actors handle their request inbox first - replies are short-cycle and
    # independent of role-specific decisions.
    _process_request_inbox(sim, actor)
    role = sim.ruleset.roles.get(actor.title)
    if role is None:
        return
    for name in role.behaviors:
        behavior = BEHAVIORS.get(name)
        if behavior is not None:
            behavior(sim, actor, role)

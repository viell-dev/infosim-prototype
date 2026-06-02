from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import move_actor, suppress_unrest, transfer_stat
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
    belief = king.known.get(sim.subject_for(target_actor, sim.defense_stat))
    if not belief or belief.value >= sim.apex_low_defense:
        return
    magnitude = (sim.apex_low_defense - belief.value) * 0.6
    _dispatch_order(sim, king, routed_via, OrderKind.REINFORCE, target_actor,
                    magnitude=magnitude, priority=2)


def _maybe_suppress(
    sim: "Simulation",
    king: "Actor",
    routed_via: "Actor",
    target_actor: str,
) -> None:
    belief = king.known.get(sim.subject_for(target_actor, sim.threat_stat))
    if not belief or belief.value <= sim.apex_high_threat:
        return
    _dispatch_order(sim, king, routed_via, OrderKind.SUPPRESS_UNREST, target_actor,
                    magnitude=belief.value, priority=2)


def _maybe_send_supplies(
    sim: "Simulation",
    king: "Actor",
    routed_via: "Actor",
    target_actor: str,
) -> None:
    belief = king.known.get(sim.subject_for(target_actor, sim.supply_stat))
    if not belief or belief.value >= sim.apex_low_supply:
        return
    magnitude = (sim.apex_low_supply - belief.value) * 0.8
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
    own_unrest = actor.known.get(sim.subject_for(actor.id, sim.threat_stat))
    if own_unrest and own_unrest.value > sim.middle_autonomous_threat:
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
        elif order.kind == OrderKind.DEFEND_LOCATION and order.target_actor == actor.id:
            _defend_current_location(sim, actor)
        elif order.kind == OrderKind.MOVE_TO_LOCATION and order.target_location is not None:
            move_actor(sim, actor.id, order.target_location, order.assigned_commander)
        # REINFORCE / SEND_SUPPLIES targeted at the commander are handled by
        # the governor (who has the stockpile); commander just waits.

    # autonomous urgent reports - jump cadence, straight to the superior
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return

    own_food = actor.known.get(sim.subject_for(actor.id, sim.supply_stat))
    if own_food and own_food.value < sim.leaf_low_supply:
        _emit_urgent_report(
            sim, actor, superior, own_food.value, sim.supply_stat, own_food.confidence,
        )

    own_garrison = actor.known.get(sim.subject_for(actor.id, sim.defense_stat))
    if own_garrison and own_garrison.value < sim.leaf_low_defense:
        _emit_urgent_report(
            sim, actor, superior, own_garrison.value, sim.defense_stat, own_garrison.confidence,
        )

    if actor.stats.get(sim.threat_stat, 0.0) > 0 and actor.stats.get(sim.defense_stat, 0.0) > 0:
        _defend_current_location(sim, actor)


def decide_captain(sim: "Simulation", actor: "Actor") -> None:
    """Captain: mine ore from infinite sources and pay a portion upward."""
    _maybe_skim(sim, actor)
    ships = actor.stats.get("ships", actor.stats.get(sim.defense_stat, 0.0))
    mined = max(0.0, ships * 18.0 * (0.5 + actor.traits.competence))
    before = actor.stats.get("ore", 0.0)
    actor.stats["ore"] = before + mined
    sim.event_log.emit(
        sim.now,
        "mining",
        f"[{actor.location}] {actor.title} {actor.display_name} mines {mined:.0f} ore "
        f"with {ships:.0f} ships (ore {before:.0f} → {actor.stats['ore']:.0f})",
        actor=actor.id,
        location=actor.location,
        ships=ships,
        amount=mined,
    )
    _pay_tax_upward(sim, actor, fraction=0.25, label="ore_tax")


def decide_manager(sim: "Simulation", actor: "Actor") -> None:
    decide_governor(sim, actor)
    _consume_ore(sim, actor)
    _pay_tax_upward(sim, actor, fraction=0.10, label="manager_tax")
    _order_local_defense(sim, actor)


def decide_ceo(sim: "Simulation", actor: "Actor") -> None:
    decide_king(sim, actor)
    for sub in _subordinates(sim, actor):
        for defender in [sub, *_subordinates(sim, sub)]:
            if defender.title != "Commander":
                continue
            threat = actor.known.get(sim.subject_for(defender.id, sim.threat_stat))
            if threat and threat.value > sim.apex_high_threat:
                _dispatch_order(
                    sim, actor, sub if defender.commander != actor.id else defender,
                    OrderKind.DEFEND_LOCATION, defender.id,
                    magnitude=threat.value, priority=3,
                )


def _consume_ore(sim: "Simulation", actor: "Actor") -> None:
    population = actor.stats.get("population", 0.0)
    if population <= 0:
        return
    before = actor.stats.get("ore", 0.0)
    consumed = min(before, population * 0.08)
    actor.stats["ore"] = before - consumed
    sim.event_log.emit(
        sim.now,
        "consumption",
        f"[{actor.location}] {actor.title} {actor.display_name} consumes {consumed:.0f} ore "
        f"for {population:.0f} population (ore {before:.0f} → {actor.stats['ore']:.0f})",
        actor=actor.id,
        location=actor.location,
        population=population,
        amount=consumed,
    )


def _pay_tax_upward(sim: "Simulation", actor: "Actor", fraction: float, label: str) -> None:
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return
    available = actor.stats.get("ore", 0.0)
    amount = available * fraction
    if amount <= 0:
        return
    transfer_stat(sim, actor.id, actor.id, superior.id, "ore", amount, "ore", label)


def _order_local_defense(sim: "Simulation", actor: "Actor") -> None:
    threat = actor.stats.get(sim.threat_stat, 0.0)
    if threat <= sim.middle_autonomous_threat:
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


def _defend_current_location(sim: "Simulation", actor: "Actor") -> None:
    holders = [a for a in sim.actors.values() if a.location == actor.location]
    targets = [a for a in holders if a.stats.get(sim.threat_stat, 0.0) > 0]
    if not targets:
        return
    target = max(targets, key=lambda a: a.stats.get(sim.threat_stat, 0.0))
    before = target.stats.get(sim.threat_stat, 0.0)
    ships = actor.stats.get(sim.defense_stat, 0.0)
    reduction = min(before, ships * (4.0 + 8.0 * actor.traits.competence))
    if reduction <= 0:
        return
    target.stats[sim.threat_stat] = before - reduction
    sim.event_log.emit(
        sim.now,
        "defense",
        f"[{actor.location}] {actor.title} {actor.display_name} defends with {ships:.0f} ships: "
        f"{sim.threat_stat} {before:.0f} → {target.stats[sim.threat_stat]:.0f}",
        actor=actor.id,
        target_actor=target.id,
        location=actor.location,
        ships=ships,
        before=before,
        after=target.stats[sim.threat_stat],
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
    "CEO": decide_ceo,
    "Governor": decide_governor,
    "Manager": decide_manager,
    "Commander": decide_commander,
    "Captain": decide_captain,
}


def run_policy(sim: "Simulation", actor: "Actor") -> None:
    # All actors handle their request inbox first - replies are short-cycle
    # and independent of role-specific decisions.
    _process_request_inbox(sim, actor)
    fn = POLICY_BY_TITLE.get(actor.title)
    if fn is None:
        return
    fn(sim, actor)

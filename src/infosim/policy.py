from __future__ import annotations

from typing import TYPE_CHECKING

from .actions import send_supplies, suppress_unrest, transfer_garrison
from .orders import Order, OrderKind
from .personnel import appoint, dismiss, pick_replacement

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
SKIM_LOYALTY_THRESHOLD = 0.4
SKIM_AMBITION_THRESHOLD = 0.5
SKIM_FRAC_MIN = 0.02              # baseline 2% of current stores per attempt
SKIM_FRAC_MAX = 0.06              # up to 6%, before disloyalty multiplier
KING_STRIKES_TO_DISMISS = 3      # consecutive bad reviews before sacking
KING_REVIEW_UNREST = 60.0        # believed unrest above this counts as a strike
KING_REVIEW_GARRISON = 800.0     # believed garrison below this counts as a strike
# -----------------------------------------------------------------------------


def _maybe_skim(sim: "Simulation", actor: "Actor") -> None:
    """A disloyal, ambitious actor quietly extracts food from their own region.

    Stochastic: probability per decide cycle is ``ambition * (1 - loyalty)``.
    Magnitude is a small random fraction of current stores, scaled by how
    disloyal the actor is — so a mildly corrupt actor skims rarely and lightly
    while a deeply disloyal one skims often and harder. The region's true
    food drops; the actor's belief is NOT updated to match — so the next
    observation surfaces the loss honestly, but if they forge their reports
    it never leaves the region.

    The gating thresholds remain as a hard floor: very loyal or unambitious
    actors never skim at all.
    """
    if actor.traits.loyalty >= SKIM_LOYALTY_THRESHOLD:
        return
    if actor.traits.ambition < SKIM_AMBITION_THRESHOLD:
        return
    region = sim.world.regions.get(actor.region)
    if region is None:
        return
    available = region.state.get("food_stores", 0.0)
    if available <= 0:
        return

    p = actor.traits.ambition * (1.0 - actor.traits.loyalty)
    if sim.rng.random() >= p:
        return

    disloyalty = 1.0 - actor.traits.loyalty
    frac = sim.rng.uniform(SKIM_FRAC_MIN, SKIM_FRAC_MAX) * (1.0 + disloyalty)
    take = min(available, available * frac)
    if take <= 0:
        return
    region.state["food_stores"] = available - take
    sim.event_log.emit(
        sim.now,
        "skim",
        f"[{actor.region}] {actor.title} {actor.display_name} skims {take:.0f} food "
        f"(stores {available:.0f} → {region.state['food_stores']:.0f})",
        actor=actor.id,
        region=actor.region,
        amount=take,
        fraction=frac,
    )


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
        issued_time=sim.now,
        deadline_time=sim.now + deadline_offset,
        priority=priority,
    )
    msg = sim.bus.dispatch_order(
        sender_actor=issuer.id,
        recipient_actor=recipient.id,
        origin_region=issuer.region,
        destination_region=recipient.region,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=order,
    )
    sim.event_log.emit(
        sim.now,
        "order_dispatched",
        f"[{issuer.region}] {issuer.title} {issuer.display_name} orders "
        f"{recipient.title} {recipient.display_name}: "
        f"{kind.value} {target_region} (magnitude {magnitude:.0f}, eta t={msg.eta_time:.0f})",
        order_id=order.id,
        issuer=issuer.id,
        recipient=recipient.id,
        order_kind=kind.value,
        target_region=target_region,
        magnitude=magnitude,
        eta_time=msg.eta_time,
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

        # Performance review — strikes against this sub for regions in their span.
        _review_subordinate(sim, actor, sub)


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


def _review_subordinate(sim: "Simulation", king: "Actor", sub: "Actor") -> None:
    """Increment or clear a strike against this subordinate based on King's belief
    of all regions in the sub's chain of command. After enough strikes, dismiss
    and replace from the candidate pool.
    """
    regions = [sub.region] + [s.region for s in _subordinates(sim, sub)]
    bad_now = False
    for r in regions:
        unrest = king.known.get(sim.subject_for(r, "unrest"))
        if unrest and unrest.value > KING_REVIEW_UNREST:
            bad_now = True
        garrison = king.known.get(sim.subject_for(r, "garrison_strength"))
        if garrison and garrison.value < KING_REVIEW_GARRISON:
            bad_now = True

    prev = king.strikes.get(sub.id, 0)
    new = prev + 1 if bad_now else 0
    king.strikes[sub.id] = new
    if new == 0 and prev > 0:
        sim.event_log.emit(
            sim.now,
            "review_cleared",
            f"[{king.region}] {king.title} considers {sub.title} {sub.display_name} "
            f"redeemed (strikes reset)",
            actor=king.id,
            subordinate=sub.id,
        )
    elif new >= KING_STRIKES_TO_DISMISS:
        _dismiss_and_replace(sim, king, sub)


def _dismiss_and_replace(sim: "Simulation", king: "Actor", sub: "Actor") -> None:
    """Sack `sub` and appoint a replacement chosen by the King's trait profile."""
    region = sub.region
    title = sub.title
    reports_to = sub.reports_to
    report_every = sub.report_every
    observe_every = sub.observe_every
    decide_every = sub.decide_every
    deeper_subs = _subordinates(sim, sub)

    dismiss(sim, sub.id, reason=f"{KING_STRIKES_TO_DISMISS} consecutive bad reviews")
    king.strikes.pop(sub.id, None)

    candidate = pick_replacement(sim.candidate_pool, sim.used_candidates, king.traits)
    if candidate is None:
        sim.event_log.emit(
            sim.now,
            "appointment_failed",
            f"[{king.region}] no candidates available to replace {title} of {region}",
            actor=king.id,
            region=region,
        )
        return
    sim.used_candidates.add(candidate.id)
    new_actor = appoint(
        sim,
        new_id=candidate.id,
        display_name=candidate.display_name,
        title=title,
        region=region,
        reports_to=reports_to,
        traits=candidate.traits,
        report_every=report_every,
        observe_every=observe_every,
        decide_every=decide_every,
    )
    # rewire any subordinates of the dismissed actor to point at the new one
    for deeper in deeper_subs:
        deeper.reports_to = new_actor.id


# --- governor -----------------------------------------------------------------
def decide_governor(sim: "Simulation", actor: "Actor") -> None:
    """Governor: process inbox, possibly forward to commander, possibly act autonomously."""
    _maybe_skim(sim, actor)
    subs = _subordinates(sim, actor)
    cmd = subs[0] if subs else None

    # 1. process inbox orders
    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.now,
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
            transfer_garrison(
                sim, actor.id, actor.region, order.target_region, order.magnitude,
            )
        elif order.kind == OrderKind.SUPPRESS_UNREST:
            if cmd is not None and order.target_region == cmd.region:
                # delegate to the commander
                _dispatch_order(
                    sim, actor, cmd, OrderKind.SUPPRESS_UNREST,
                    order.target_region, order.magnitude, priority=order.priority,
                )
            elif order.target_region == actor.region:
                # governor handles their own region
                suppress_unrest(
                    sim, actor.id, actor.region, SUPPRESS_DURATION,
                    competence=actor.traits.competence, rng=sim.rng,
                )
        elif order.kind == OrderKind.SEND_SUPPLIES and order.target_region != actor.region:
            send_supplies(
                sim, actor.id, actor.region, order.target_region, order.magnitude,
            )

    # 2. autonomous suppression if local unrest belief is severe
    own_unrest = actor.known.get(sim.subject_for(actor.region, "unrest"))
    if own_unrest and own_unrest.value > GOV_AUTONOMOUS_UNREST:
        sim.event_log.emit(
            sim.now,
            "autonomous_action",
            f"[{actor.region}] {actor.title} {actor.display_name} acts on own initiative: "
            f"suppress unrest (believed {own_unrest.value:.0f})",
            actor=actor.id,
            region=actor.region,
        )
        suppress_unrest(
            sim, actor.id, actor.region, SUPPRESS_DURATION,
            competence=actor.traits.competence, rng=sim.rng,
        )


# --- commander ----------------------------------------------------------------
def decide_commander(sim: "Simulation", actor: "Actor") -> None:
    """Commander: execute orders; autonomously raise the alarm on critical lows."""
    _maybe_skim(sim, actor)
    # 1. process inbox
    while actor.inbox:
        order = actor.inbox.pop(0)
        sim.event_log.emit(
            sim.now,
            "order_received",
            f"[{actor.region}] {actor.title} {actor.display_name} acts on "
            f"{order.kind.value} {order.target_region} from {order.issuer}",
            order_id=order.id,
            recipient=actor.id,
            order_kind=order.kind.value,
            target_region=order.target_region,
        )
        if order.kind == OrderKind.SUPPRESS_UNREST and order.target_region == actor.region:
            suppress_unrest(
                sim, actor.id, actor.region, SUPPRESS_DURATION,
                competence=actor.traits.competence, rng=sim.rng,
            )
        # REINFORCE / SEND_SUPPLIES targeted at the commander's region are handled by
        # the governor (the one with the source region's resources); the commander has
        # nothing to do but wait.

    # 2. autonomous urgent reports — these jump cadence and go straight to the governor
    if actor.reports_to is None:
        return
    superior = sim.actors.get(actor.reports_to)
    if superior is None:
        # Superior was dismissed and no replacement was available — the
        # commander effectively has no chain of command. Skip urgent reports
        # rather than crashing; the next appointment will rewire upward.
        return

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
        origin_time=sim.now,
        source_chain=[actor.id],
    )
    travel = sim.world.travel_ticks(actor.region, superior.region)
    msg = sim.bus.dispatch(
        sender_actor=actor.id,
        recipient_actor=superior.id,
        origin_region=actor.region,
        destination_region=superior.region,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=report,
    )
    sim.event_log.emit(
        sim.now,
        "urgent_report",
        f"[{actor.region}] {actor.title} {actor.display_name} sends URGENT report to "
        f"{superior.region}: {variable} ≈ {value:.0f} (eta t={msg.eta_time:.0f})",
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
    fn = POLICY_BY_TITLE.get(actor.title)
    if fn is None:
        return
    fn(sim, actor)

from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from .actions import send_supplies, suppress_unrest, transfer_garrison
from .orders import Order, OrderKind
from .personnel import appoint, dismiss, pick_replacement
from .requests import InfoRequest, InfoResponse, PendingRequest
from .reports import forge_value
from .scheduler import Event, EventKind
from .world import VARIABLES

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
SKIM_LOYALTY_THRESHOLD = 0.85    # smooth gate — only deeply virtuous never skim
SKIM_AMBITION_THRESHOLD = 0.3
SKIM_FRAC_MIN = 0.02              # baseline 2% of current stores per attempt
SKIM_FRAC_MAX = 0.06              # up to 6%, before disloyalty multiplier
KING_STRIKES_TO_DISMISS = 3       # consecutive bad reviews before sacking
KING_REVIEW_UNREST = 60.0         # believed unrest above this counts as a strike (single-sub fallback)
KING_REVIEW_GARRISON = 800.0      # believed garrison below this counts as a strike (single-sub fallback)
PEER_DEV_LOW = 1.0                # health below peer median by this much -> underperformance strike
PEER_DEV_HIGH = 0.8               # health above peer median by this much -> suspicion strike
REQUEST_DEADLINE = 60.0           # logical-time deadline for an INFO_REQUEST round-trip
REQUEST_TRUST_THRESHOLD = 0.5     # below this loyalty, the recipient may lie about a sub
# -----------------------------------------------------------------------------


def _maybe_skim(sim: "Simulation", actor: "Actor") -> None:
    """A disloyal, ambitious actor quietly extracts food from their own stats.

    Stochastic: probability per decide cycle is ``ambition * (1 - loyalty)^2``.
    Magnitude is a small random fraction of current stores, scaled by how
    disloyal the actor is. The actor's stats drop; their belief is NOT updated
    to match — the next observation surfaces the loss honestly, but if they
    forge their reports it never leaves them.
    """
    if actor.traits.loyalty >= SKIM_LOYALTY_THRESHOLD:
        return
    if actor.traits.ambition < SKIM_AMBITION_THRESHOLD:
        return
    available = actor.stats.get("food_stores", 0.0)
    if available <= 0:
        return

    # Smooth probability curve. (1 - loyalty)^2 means perfectly loyal -> 0,
    # mildly loyal still very rare, deeply disloyal frequent. Hard gates at
    # SKIM_LOYALTY_THRESHOLD and SKIM_AMBITION_THRESHOLD keep the very
    # virtuous immune so unit tests stay deterministic.
    disloyalty = 1.0 - actor.traits.loyalty
    p = actor.traits.ambition * disloyalty * disloyalty
    if sim.rng.random() >= p:
        return

    frac = sim.rng.uniform(SKIM_FRAC_MIN, SKIM_FRAC_MAX) * (1.0 + disloyalty)
    take = min(available, available * frac)
    if take <= 0:
        return
    actor.stats["food_stores"] = available - take
    sim.event_log.emit(
        sim.now,
        "skim",
        f"[{actor.location}] {actor.title} {actor.display_name} skims {take:.0f} food "
        f"(stores {available:.0f} → {actor.stats['food_stores']:.0f})",
        actor=actor.id,
        location=actor.location,
        amount=take,
        fraction=frac,
    )


def _dispatch_order(
    sim: "Simulation",
    issuer: "Actor",
    recipient: "Actor",
    kind: OrderKind,
    target_actor: str,
    magnitude: float,
    deadline_offset: int = 60,
    priority: int = 1,
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
        magnitude=magnitude,
        eta_time=msg.eta_time,
    )


def _subordinates(sim: "Simulation", actor: "Actor") -> list["Actor"]:
    return [a for a in sim.actors.values() if a.commander == actor.id]


# --- king ---------------------------------------------------------------------
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


def _maybe_reinforce(sim: "Simulation", king: "Actor", routed_via: "Actor", target_actor: str) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "garrison_strength"))
    if not belief or belief.value >= KING_LOW_GARRISON:
        return
    magnitude = (KING_LOW_GARRISON - belief.value) * 0.6
    _dispatch_order(sim, king, routed_via, OrderKind.REINFORCE, target_actor,
                    magnitude=magnitude, priority=2)


def _maybe_suppress(sim: "Simulation", king: "Actor", routed_via: "Actor", target_actor: str) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "unrest"))
    if not belief or belief.value <= KING_HIGH_UNREST:
        return
    _dispatch_order(sim, king, routed_via, OrderKind.SUPPRESS_UNREST, target_actor,
                    magnitude=belief.value, priority=2)


def _maybe_send_supplies(sim: "Simulation", king: "Actor", routed_via: "Actor", target_actor: str) -> None:
    belief = king.known.get(sim.subject_for(target_actor, "food_stores"))
    if not belief or belief.value >= KING_LOW_FOOD:
        return
    magnitude = (KING_LOW_FOOD - belief.value) * 0.8
    _dispatch_order(sim, king, routed_via, OrderKind.SEND_SUPPLIES, target_actor,
                    magnitude=magnitude, priority=1)


def _chain_actors(sim: "Simulation", sub: "Actor") -> list[str]:
    """Sub plus their direct subordinates, by actor id."""
    return [sub.id] + [s.id for s in _subordinates(sim, sub)]


def _chain_health(sim: "Simulation", king: "Actor", sub: "Actor") -> float | None:
    """Scalar 'how healthy is this sub's span of command' from the King's
    beliefs. Higher = better. Returns None if the King has no relevant beliefs.

    Composition: normalised garrison + food, minus normalised unrest, summed
    over the sub and their subordinates. Units are arbitrary — what matters
    is consistent comparison across siblings.
    """
    score = 0.0
    saw_any = False
    for actor_id in _chain_actors(sim, sub):
        g = king.known.get(sim.subject_for(actor_id, "garrison_strength"))
        f = king.known.get(sim.subject_for(actor_id, "food_stores"))
        u = king.known.get(sim.subject_for(actor_id, "unrest"))
        if g is None and f is None and u is None:
            continue
        saw_any = True
        if g is not None:
            score += g.value / 1000.0
        if f is not None:
            score += f.value / 1000.0
        if u is not None:
            score -= u.value / 100.0
    return score if saw_any else None


def _review_subordinate(sim: "Simulation", king: "Actor", sub: "Actor") -> None:
    """Award or clear a strike against this subordinate.

    With ≥2 direct subordinates the review is *comparative* — chain-health
    vs. peer median, with separate strikes for "underperforming" and
    "suspiciously rosy." With a single sub, fall back to absolute thresholds.
    """
    peers = _subordinates(sim, king)
    reason: str | None = None

    if len(peers) >= 2:
        peer_scores: dict[str, float] = {}
        for p in peers:
            h = _chain_health(sim, king, p)
            if h is not None:
                peer_scores[p.id] = h
        my_score = peer_scores.get(sub.id)
        if my_score is None or len(peer_scores) < 2:
            bad_now = False
        else:
            others = [v for k, v in peer_scores.items() if k != sub.id]
            peer_median = statistics.median(others)
            if my_score < peer_median - PEER_DEV_LOW:
                bad_now = True
                reason = f"underperforming peers ({my_score:.2f} vs {peer_median:.2f})"
            elif my_score > peer_median + PEER_DEV_HIGH:
                bad_now = True
                reason = f"suspiciously rosy vs peers ({my_score:.2f} vs {peer_median:.2f})"
                # Suspicion -> ask sub about each of their deeper sub-of-subs.
                # The King is no longer passive: he's spending a courier to
                # request a fresh read on the corrupt-looking chain.
                for deeper in _subordinates(sim, sub):
                    maybe_initiate_audit(sim, king, sub, deeper)
            else:
                bad_now = False
    else:
        # Single-sub fallback — absolute thresholds.
        bad_now = False
        for actor_id in _chain_actors(sim, sub):
            unrest = king.known.get(sim.subject_for(actor_id, "unrest"))
            if unrest and unrest.value > KING_REVIEW_UNREST:
                bad_now = True
                reason = f"high believed unrest at {actor_id}"
            garrison = king.known.get(sim.subject_for(actor_id, "garrison_strength"))
            if garrison and garrison.value < KING_REVIEW_GARRISON:
                bad_now = True
                reason = f"low believed garrison at {actor_id}"

    prev = king.strikes.get(sub.id, 0)
    new = prev + 1 if bad_now else 0
    king.strikes[sub.id] = new
    if bad_now:
        sim.event_log.emit(
            sim.now,
            "review_strike",
            f"[{king.location}] {king.title} marks {sub.title} {sub.display_name} "
            f"({new}/{KING_STRIKES_TO_DISMISS}): {reason}",
            actor=king.id,
            subordinate=sub.id,
            strike=new,
            reason=reason,
        )
    elif prev > 0:
        sim.event_log.emit(
            sim.now,
            "review_cleared",
            f"[{king.location}] {king.title} considers {sub.title} {sub.display_name} "
            f"redeemed (strikes reset)",
            actor=king.id,
            subordinate=sub.id,
        )
    if new >= KING_STRIKES_TO_DISMISS:
        _dismiss_and_replace(sim, king, sub)


def _dismiss_and_replace(sim: "Simulation", king: "Actor", sub: "Actor") -> None:
    """Sack `sub` and appoint a replacement chosen by the King's trait profile."""
    title = sub.title
    location = sub.location
    commander = sub.commander
    report_every = sub.report_every
    observe_every = sub.observe_every
    decide_every = sub.decide_every
    inherited_stats = dict(sub.stats)
    deeper_subs = _subordinates(sim, sub)

    dismiss(sim, sub.id, reason=f"{KING_STRIKES_TO_DISMISS} consecutive bad reviews")
    king.strikes.pop(sub.id, None)

    candidate = pick_replacement(sim.candidate_pool, sim.used_candidates, king.traits)
    if candidate is None:
        sim.event_log.emit(
            sim.now,
            "appointment_failed",
            f"[{king.location}] no candidates available to replace {title} of {location}",
            actor=king.id,
            location=location,
        )
        return
    sim.used_candidates.add(candidate.id)
    new_actor = appoint(
        sim,
        new_id=candidate.id,
        display_name=candidate.display_name,
        title=title,
        location=location,
        commander=commander,
        traits=candidate.traits,
        stats=inherited_stats,
        report_every=report_every,
        observe_every=observe_every,
        decide_every=decide_every,
    )
    # rewire any subordinates of the dismissed actor to point at the new one
    for deeper in deeper_subs:
        deeper.commander = new_actor.id


# --- governor -----------------------------------------------------------------
def decide_governor(sim: "Simulation", actor: "Actor") -> None:
    """Governor: process inbox, possibly forward to commander, possibly act autonomously."""
    _maybe_skim(sim, actor)
    subs = _subordinates(sim, actor)

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

        target = sim.actors.get(order.target_actor)
        if order.kind == OrderKind.REINFORCE and order.target_actor != actor.id:
            transfer_garrison(
                sim, actor.id, src_actor_id=actor.id,
                dst_actor_id=order.target_actor, magnitude=order.magnitude,
            )
        elif order.kind == OrderKind.SUPPRESS_UNREST:
            if order.target_actor == actor.id:
                # governor handles their own unrest
                suppress_unrest(
                    sim, actor.id, target_actor_id=actor.id,
                    duration=SUPPRESS_DURATION,
                    competence=actor.traits.competence, rng=sim.rng,
                )
            elif target is not None and target.commander == actor.id:
                # delegate to the subordinate
                _dispatch_order(
                    sim, actor, target, OrderKind.SUPPRESS_UNREST,
                    target_actor=order.target_actor,
                    magnitude=order.magnitude, priority=order.priority,
                )
        elif order.kind == OrderKind.SEND_SUPPLIES and order.target_actor != actor.id:
            send_supplies(
                sim, actor.id, src_actor_id=actor.id,
                dst_actor_id=order.target_actor, magnitude=order.magnitude,
            )

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

    # autonomous urgent reports — jump cadence, straight to the superior
    if actor.commander is None:
        return
    superior = sim.actors.get(actor.commander)
    if superior is None:
        return

    own_food = actor.known.get(sim.subject_for(actor.id, "food_stores"))
    if own_food and own_food.value < CMD_LOW_FOOD:
        _emit_urgent_report(sim, actor, superior, own_food.value, "food_stores", own_food.confidence)

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
    from .reports import Report  # local import to avoid cycles

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
    # All actors handle their request inbox first — replies are short-cycle
    # and independent of role-specific decisions.
    _process_request_inbox(sim, actor)
    fn = POLICY_BY_TITLE.get(actor.title)
    if fn is None:
        return
    fn(sim, actor)


# =============================================================================
# Pull-based information primitive
# =============================================================================


def _dispatch_request(
    sim: "Simulation",
    sender: "Actor",
    recipient: "Actor",
    subjects: list[str],
    originator: str,
    note: str = "",
    parent_correlation_id: int | None = None,
    parent_from_actor: str | None = None,
) -> InfoRequest:
    """Build, dispatch, and bookkeep an INFO_REQUEST."""
    correlation_id = next(sim._request_ids)
    deadline = sim.now + REQUEST_DEADLINE
    req = InfoRequest(
        correlation_id=correlation_id,
        originator=originator,
        subjects=list(subjects),
        deadline_time=deadline,
        note=note,
    )
    travel = sim.world.travel_ticks(sender.location, recipient.location)
    msg = sim.bus.dispatch_request(
        sender_actor=sender.id,
        recipient_actor=recipient.id,
        origin_region=sender.location,
        destination_region=recipient.location,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=req,
    )
    sender.pending_requests[correlation_id] = PendingRequest(
        correlation_id=correlation_id,
        waiting_for=recipient.id,
        subjects=list(subjects),
        deadline_time=deadline,
        parent_correlation_id=parent_correlation_id,
        parent_from_actor=parent_from_actor,
    )
    sim.scheduler.schedule(
        deadline,
        Event(kind=EventKind.REQUEST_TIMEOUT, actor_id=sender.id, payload=correlation_id),
    )
    sim.event_log.emit(
        sim.now,
        "request_dispatched",
        f"[{sender.location}] {sender.title} {sender.display_name} asks "
        f"{recipient.title} {recipient.display_name}: INFO_REQUEST #{correlation_id} "
        f"about {subjects} (eta t={msg.eta_time:.0f}{', ' + note if note else ''})",
        actor=sender.id,
        recipient=recipient.id,
        correlation_id=correlation_id,
        subjects=subjects,
        originator=originator,
        eta_time=msg.eta_time,
        note=note,
    )
    return req


def _dispatch_response(
    sim: "Simulation",
    sender: "Actor",
    recipient_id: str,
    response: InfoResponse,
) -> None:
    recipient = sim.actors.get(recipient_id)
    if recipient is None:
        return  # vanished; the requester's timeout will clean up
    travel = sim.world.travel_ticks(sender.location, recipient.location)
    msg = sim.bus.dispatch_response(
        sender_actor=sender.id,
        recipient_actor=recipient.id,
        origin_region=sender.location,
        destination_region=recipient.location,
        base_travel_ticks=travel,
        dispatch_time=sim.now,
        payload=response,
    )
    sim.event_log.emit(
        sim.now,
        "response_dispatched",
        f"[{sender.location}] {sender.title} {sender.display_name} sends "
        f"INFO_RESPONSE #{response.correlation_id} to {recipient.title} "
        f"{recipient.display_name} "
        f"({'refused' if response.refused else f'{len(response.answers)} answers'}, "
        f"eta t={msg.eta_time:.0f})",
        actor=sender.id,
        recipient=recipient.id,
        correlation_id=response.correlation_id,
        refused=response.refused,
        n_answers=len(response.answers),
    )


def dispatch_refusal_to_parent(
    sim: "Simulation",
    actor: "Actor",
    pending: PendingRequest,
    reason: str,
) -> None:
    """Helper used by the engine when a downstream request times out.

    The relaying actor lets its upstream caller know the chain failed so the
    caller can clear its own pending entry.
    """
    if pending.parent_correlation_id is None or pending.parent_from_actor is None:
        return
    response = InfoResponse(
        correlation_id=pending.parent_correlation_id,
        refused=True,
        refusal_reason=reason,
    )
    _dispatch_response(sim, actor, pending.parent_from_actor, response)


def _split_subjects(actor: "Actor", subjects: list[str], sim: "Simulation") -> tuple[list[str], dict[str, list[str]]]:
    """Sort each subject into 'mine' or 'delegate to subordinate X'.

    Subjects keyed by an actor id this actor is responsible for (self or any
    transitive subordinate) get forwarded; everything else falls into 'mine'
    (answered from own beliefs even though the actor may not actually know,
    in which case the answer is omitted).
    """
    mine: list[str] = []
    delegate: dict[str, list[str]] = {}
    direct_subs = _subordinates(sim, actor)
    sub_by_id = {s.id: s for s in direct_subs}
    for s in subjects:
        target_id = s.split(".", 1)[0]
        if target_id == actor.id:
            mine.append(s)
        elif target_id in sub_by_id:
            # ask the direct subordinate themselves
            delegate.setdefault(target_id, []).append(s)
        else:
            # check if any direct sub *covers* this target (transitive)
            owner = None
            for sub in direct_subs:
                if target_id in {sub.id} | {ss.id for ss in _subordinates(sim, sub)}:
                    owner = sub.id
                    break
            if owner is not None:
                delegate.setdefault(owner, []).append(s)
            else:
                # We don't know who could answer this. Treat as 'mine' so we
                # respond with whatever cached belief we have (or empty).
                mine.append(s)
    return mine, delegate


def _answer_from_belief(actor: "Actor", subjects: list[str], rng) -> dict[str, tuple[float, float]]:
    """Build an answers dict from cached beliefs, applying the same forgery
    logic that report-time uses. If the actor is the *subject* of a
    question, they may lie about their own stats just as they would on a
    pushed report.
    """
    out: dict[str, tuple[float, float]] = {}
    disloyalty = 1.0 - actor.traits.loyalty
    forge_prob = actor.traits.ambition * disloyalty * disloyalty
    for subject in subjects:
        belief = actor.known.get(subject)
        if belief is None:
            continue
        value = belief.value
        if actor.traits.loyalty < 0.85:
            stat = subject.split(".", 1)[1]
            spec = VARIABLES.get(stat)
            if spec is not None:
                polarity = spec.polarity
                is_bad_news = (
                    (polarity == +1 and value < 1000.0) or
                    (polarity == -1 and value > 20.0)
                )
                if is_bad_news and rng.random() < forge_prob:
                    severity = max(0.0, min(1.0, disloyalty * rng.uniform(0.5, 1.5)))
                    value = forge_value(value, stat, severity)
        out[subject] = (value, belief.confidence)
    return out


def _process_request_inbox(sim: "Simulation", actor: "Actor") -> None:
    """Handle every queued INFO_REQUEST.

    For each request, the actor splits subjects into 'mine' (answer from own
    belief, possibly fabricated) and 'delegate' (forward to whichever
    subordinate covers the subject). When delegating, an answers-so-far
    response is sent immediately *and* a forwarded request goes out — the
    upstream asker gets a partial answer, then a follow-up when the
    forwarded reply arrives. For the prototype we only forward; partial
    pre-answer is deferred.

    Choice between honest forward / cached / fabricate is driven by the
    actor's loyalty:
      - loyalty >= REQUEST_TRUST_THRESHOLD: forward delegations honestly,
        answer 'mine' from belief.
      - loyalty <  REQUEST_TRUST_THRESHOLD: answer delegations from cache
        too (so the asker hears whatever the actor *believes* about the
        sub, with the actor's own forgery applied) — i.e. the disloyal
        relay protects their sub by not asking them.
    """
    if not actor.request_inbox:
        return
    pending_drain = actor.request_inbox
    actor.request_inbox = []
    for sender_id, req in pending_drain:
        mine, delegate = _split_subjects(actor, req.subjects, sim)

        if actor.traits.loyalty < REQUEST_TRUST_THRESHOLD:
            # Protective relay: fold delegations into 'mine' so we never
            # actually ask the subordinate; answer from our own (possibly
            # forged) beliefs about them.
            for subs in delegate.values():
                mine.extend(subs)
            delegate = {}

        if delegate:
            for sub_id, sub_subjects in delegate.items():
                sub = sim.actors[sub_id]
                _dispatch_request(
                    sim, sender=actor, recipient=sub,
                    subjects=sub_subjects,
                    originator=req.originator,
                    note=f"on behalf of {req.originator}",
                    parent_correlation_id=req.correlation_id,
                    parent_from_actor=sender_id,
                )
            if mine:
                answers = _answer_from_belief(actor, mine, sim.rng)
                response = InfoResponse(
                    correlation_id=req.correlation_id, answers=answers,
                )
                _dispatch_response(sim, actor, sender_id, response)
        else:
            answers = _answer_from_belief(actor, mine, sim.rng)
            response = InfoResponse(correlation_id=req.correlation_id, answers=answers)
            _dispatch_response(sim, actor, sender_id, response)


def handle_info_response(
    sim: "Simulation",
    recipient: "Actor",
    sender_actor_id: str,
    response: InfoResponse,
) -> None:
    """Called by sim._handle_message when an INFO_RESPONSE arrives.

    Two cases:
      - Recipient was the originator: integrate answers into their beliefs.
      - Recipient was a relayer: compose a new response upstream with the
        parent correlation id.
    """
    pending = recipient.pending_requests.pop(response.correlation_id, None)
    if pending is None:
        # Late or duplicate. Log and drop.
        sim.event_log.emit(
            sim.now,
            "response_orphan",
            f"[{recipient.location}] {recipient.title} {recipient.display_name} "
            f"received orphan INFO_RESPONSE #{response.correlation_id}",
            actor=recipient.id,
            correlation_id=response.correlation_id,
        )
        return

    if pending.parent_correlation_id is not None and pending.parent_from_actor is not None:
        # We were relaying. Compose a fresh response for the upstream asker.
        # An honest relayer forwards verbatim; a disloyal one may shade
        # values on the way back using the same forgery dynamic.
        relayed_answers: dict[str, tuple[float, float]] = {}
        disloyalty = 1.0 - recipient.traits.loyalty
        forge_prob = recipient.traits.ambition * disloyalty * disloyalty
        for subject, (val, conf) in response.answers.items():
            value = val
            if recipient.traits.loyalty < 0.85:
                stat = subject.split(".", 1)[1]
                spec = VARIABLES.get(stat)
                if spec is not None:
                    polarity = spec.polarity
                    is_bad_news = (
                        (polarity == +1 and value < 1000.0) or
                        (polarity == -1 and value > 20.0)
                    )
                    if is_bad_news and sim.rng.random() < forge_prob:
                        severity = max(0.0, min(1.0, disloyalty * sim.rng.uniform(0.5, 1.5)))
                        value = forge_value(value, stat, severity)
            relayed_answers[subject] = (value, conf)
        upstream_response = InfoResponse(
            correlation_id=pending.parent_correlation_id,
            answers=relayed_answers,
            refused=response.refused,
            refusal_reason=response.refusal_reason,
        )
        _dispatch_response(sim, recipient, pending.parent_from_actor, upstream_response)
        sim.event_log.emit(
            sim.now,
            "response_relayed",
            f"[{recipient.location}] {recipient.title} {recipient.display_name} relays "
            f"INFO_RESPONSE #{response.correlation_id} → #{pending.parent_correlation_id} "
            f"to {pending.parent_from_actor}",
            actor=recipient.id,
            in_correlation=response.correlation_id,
            out_correlation=pending.parent_correlation_id,
        )
        return

    # Originator path — integrate answers into beliefs.
    if response.refused:
        sim.event_log.emit(
            sim.now,
            "response_refused",
            f"[{recipient.location}] {recipient.title} {recipient.display_name} "
            f"got REFUSED response to #{response.correlation_id}: {response.refusal_reason}",
            actor=recipient.id,
            correlation_id=response.correlation_id,
            reason=response.refusal_reason,
        )
        return
    for subject, (value, conf) in response.answers.items():
        recipient.update_belief(
            subject,
            value,
            conf,
            sim.now,
            [sender_actor_id, recipient.id],
        )
    sim.event_log.emit(
        sim.now,
        "response_integrated",
        f"[{recipient.location}] {recipient.title} {recipient.display_name} integrates "
        f"INFO_RESPONSE #{response.correlation_id}: {len(response.answers)} subjects updated "
        f"(via {sender_actor_id})",
        actor=recipient.id,
        correlation_id=response.correlation_id,
        n_answers=len(response.answers),
    )


def maybe_initiate_audit(sim: "Simulation", king: "Actor", sub: "Actor", deeper: "Actor") -> None:
    """King-side initiation: ask `sub` about `deeper`'s stats if no audit
    is already pending for that deeper actor.
    """
    # Skip if we already have an outstanding request asking about any of the
    # subjects this audit would cover.
    targets = [sim.subject_for(deeper.id, s) for s in ("garrison_strength", "food_stores", "unrest")]
    already_pending = any(
        any(s in p.subjects for s in targets)
        for p in king.pending_requests.values()
    )
    if already_pending:
        return
    _dispatch_request(
        sim, sender=king, recipient=sub,
        subjects=targets,
        originator=king.id,
        note=f"audit of {deeper.display_name}",
    )

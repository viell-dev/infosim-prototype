from __future__ import annotations

from typing import TYPE_CHECKING

from ..requests import InfoRequest, InfoResponse, PendingRequest
from ..reports import forge_value
from ..scheduler import Event, EventKind
from .constants import REQUEST_DEADLINE, REQUEST_TRUST_THRESHOLD
from .hierarchy import _subordinates

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


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


def _split_subjects(
    actor: "Actor",
    subjects: list[str],
    sim: "Simulation",
) -> tuple[list[str], dict[str, list[str]]]:
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


def _maybe_forge_answer(sim: "Simulation", actor: "Actor", subject: str, value: float) -> float:
    """Apply the bad-news forgery dynamic to a single answer value, driven by
    the ruleset's stat polarity. Returns the (possibly fabricated) value.

    NOTE: the literal 1000/20 bad-news cutoffs are legacy medieval magic that
    step 2 replaces with the ruleset's per-stat bad_news_thresholds (which is a
    deliberate behavior change re-baselined there). Kept verbatim here so this
    relocation step changes no run output.
    """
    if actor.traits.loyalty >= 0.85:
        return value
    stat = subject.split(".", 1)[1]
    spec = sim.ruleset.stats.get(stat)
    if spec is None:
        return value
    is_bad_news = (
        (spec.polarity == +1 and value < 1000.0) or
        (spec.polarity == -1 and value > 20.0)
    )
    if not is_bad_news:
        return value
    disloyalty = 1.0 - actor.traits.loyalty
    forge_prob = actor.traits.ambition * disloyalty * disloyalty
    if sim.rng.random() < forge_prob:
        severity = max(0.0, min(1.0, disloyalty * sim.rng.uniform(0.5, 1.5)))
        return forge_value(value, stat, severity, sim.ruleset.stats)
    return value


def _answer_from_belief(sim: "Simulation", actor: "Actor", subjects: list[str]) -> dict[str, tuple[float, float]]:
    """Build an answers dict from cached beliefs, applying the same forgery
    logic that report-time uses. If the actor is the *subject* of a
    question, they may lie about their own stats just as they would on a
    pushed report.
    """
    out: dict[str, tuple[float, float]] = {}
    for subject in subjects:
        belief = actor.known.get(subject)
        if belief is None:
            continue
        value = _maybe_forge_answer(sim, actor, subject, belief.value)
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
                answers = _answer_from_belief(sim, actor, mine)
                response = InfoResponse(
                    correlation_id=req.correlation_id, answers=answers,
                )
                _dispatch_response(sim, actor, sender_id, response)
        else:
            answers = _answer_from_belief(sim, actor, mine)
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
        for subject, (val, conf) in response.answers.items():
            value = _maybe_forge_answer(sim, recipient, subject, val)
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
        sender=sender_actor_id,
        correlation_id=response.correlation_id,
        n_answers=len(response.answers),
        answers={
            subject: {"value": value, "confidence": conf}
            for subject, (value, conf) in response.answers.items()
        },
    )


def maybe_initiate_audit(sim: "Simulation", king: "Actor", sub: "Actor", deeper: "Actor") -> None:
    """King-side initiation: ask `sub` about `deeper`'s stats if no audit
    is already pending for that deeper actor.
    """
    # Skip if we already have an outstanding request asking about any of the
    # subjects this audit would cover.
    targets = [
        sim.subject_for(deeper.id, s)
        for s in (sim.defense_stat, sim.supply_stat, sim.threat_stat)
        if s is not None
    ]
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

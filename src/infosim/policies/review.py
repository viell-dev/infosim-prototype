from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from ..personnel import appoint, dismiss, pick_replacement
from .constants import (
    KING_REVIEW_GARRISON,
    KING_REVIEW_UNREST,
    KING_STRIKES_TO_DISMISS,
    PEER_DEV_HIGH,
    PEER_DEV_LOW,
)
from .hierarchy import _subordinates
from .info_requests import maybe_initiate_audit

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


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

    With >=2 direct subordinates the review is *comparative* — chain-health
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

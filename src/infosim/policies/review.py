from __future__ import annotations

import statistics
from typing import TYPE_CHECKING

from ..personnel import install_occupant, pick_replacement, vacate
from .constants import (
    KING_STRIKES_TO_DISMISS,
    PEER_DEV_HIGH,
    PEER_DEV_LOW,
)
from .hierarchy import _subordinates
from .info_requests import maybe_initiate_audit

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


def _combine(func, a: float | None, b: float | None) -> float | None:
    """max/min of two optional thresholds; whichever is set if only one is."""
    if a is None:
        return b
    if b is None:
        return a
    return func(a, b)


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
        g = king.known.get(sim.subject_for(actor_id, sim.defense_stat))
        f = king.known.get(sim.subject_for(actor_id, sim.supply_stat))
        u = king.known.get(sim.subject_for(actor_id, sim.threat_stat))
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
        # Single-sub fallback — absolute thresholds from the King's role. The
        # review cutoffs combine with the order-trigger thresholds: review fires
        # only on threat worse than both, or defense worse than both.
        role = sim.ruleset.roles.get(king.title)
        thresholds = role.thresholds if role is not None else {}
        review_threat = _combine(max, thresholds.get("review_threat"), thresholds.get("high_threat"))
        review_defense = _combine(min, thresholds.get("review_defense"), thresholds.get("low_defense"))
        bad_now = False
        for actor_id in _chain_actors(sim, sub):
            if review_threat is not None and sim.threat_stat is not None:
                unrest = king.known.get(sim.subject_for(actor_id, sim.threat_stat))
                if unrest and unrest.value > review_threat:
                    bad_now = True
                    reason = f"high believed {sim.threat_stat} at {actor_id}"
            if review_defense is not None and sim.defense_stat is not None:
                garrison = king.known.get(sim.subject_for(actor_id, sim.defense_stat))
                if garrison and garrison.value < review_defense:
                    bad_now = True
                    reason = f"low believed {sim.defense_stat} at {actor_id}"

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
    """Remove the occupant of office ``sub`` and install a replacement if one is
    available, otherwise leave the seat vacant under ``king`` as regent.

    The office is a stable node: its id, location, title, resources, and
    subordinates persist either way. Subordinates are never rewired (they work
    for the position, not the person). ``install_occupant`` / ``vacate`` reset
    the new occupant's own state and clear the superior's strikes so a successor
    is not punished for the predecessor.
    """
    reason = f"{KING_STRIKES_TO_DISMISS} consecutive bad reviews"
    candidate = pick_replacement(sim.candidate_pool, sim.used_candidates, king.traits)
    if candidate is None:
        # Already empty and no one to install — nothing to do (don't re-emit a
        # regency for a seat that's already vacant).
        if not sub.vacant:
            vacate(sim, sub, king, reason=reason)
        return
    # A candidate is available: install them (this also fills a vacant seat).
    sim.used_candidates.add(candidate.id)
    install_occupant(sim, sub, king, candidate, reason=reason)

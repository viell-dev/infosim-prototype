from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .actors import Actor, Traits

if TYPE_CHECKING:
    from .sim import Simulation


@dataclass
class Candidate:
    """A potential appointee living in the wings until summoned."""
    id: str
    display_name: str
    traits: Traits


def appoint(
    sim: "Simulation",
    new_id: str,
    display_name: str,
    title: str,
    location: str,
    commander: str | None,
    traits: Traits,
    report_every: float,
    observe_every: float,
    decide_every: float,
    stats: dict[str, float] | None = None,
) -> Actor:
    """Create a new actor, wire them into the hierarchy, and put them on the schedule.

    ``stats`` defaults to inheriting the dismissed actor's stockpile — the
    physical resources don't disappear with the office holder. Pass an
    explicit dict to override.
    """
    actor = Actor(
        id=new_id,
        display_name=display_name,
        title=title,
        location=location,
        commander=commander,
        traits=traits,
        stats=dict(stats) if stats else {},
        report_every=report_every,
        observe_every=observe_every,
        decide_every=decide_every,
        tenure_start_time=sim.now,
    )
    sim.actors[new_id] = actor
    sim.schedule_actor_cadences(actor)
    sim.event_log.emit(
        sim.now,
        "appointed",
        f"[{location}] {title} {display_name} takes office "
        f"(competence {traits.competence:.2f}, honesty {traits.honesty:.2f}, "
        f"loyalty {traits.loyalty:.2f})",
        actor=new_id,
        location=location,
        title=title,
        competence=traits.competence,
        honesty=traits.honesty,
        loyalty=traits.loyalty,
    )
    return actor


def dismiss(sim: "Simulation", actor_id: str, reason: str) -> Actor | None:
    """Remove an actor from office. Their inbox and beliefs are lost with them.

    Any subordinate who reported to them is left dangling; the caller is
    expected to immediately appoint a replacement and rewire reports_to.
    """
    actor = sim.actors.pop(actor_id, None)
    if actor is None:
        return None
    sim.event_log.emit(
        sim.now,
        "dismissed",
        f"[{actor.location}] {actor.title} {actor.display_name} dismissed: {reason}",
        actor=actor_id,
        location=actor.location,
        reason=reason,
        tenure_time=sim.now - actor.tenure_start_time,
    )
    # Wipe any belief the King held that came through this person — institutional
    # memory dies with the office holder. Beliefs whose source_chain ends with the
    # dismissed actor are cleared so the King knows they're now stale-by-definition.
    # Simpler approach: don't touch existing beliefs; just let the new appointee's
    # reports overwrite them as they arrive. Less drastic and the staleness is
    # honestly represented by age.
    return actor


def pick_replacement(
    pool: list[Candidate],
    used_ids: set[str],
    king_traits: Traits,
) -> Candidate | None:
    """Choose a candidate from the pool, biased by the King's own trait profile.

    A paranoid king (high fear) prioritises loyalty.
    A scholar king (high education) prioritises competence.
    A practical king (high honesty) prioritises honesty.
    Defaults to a balanced score.
    """
    available = [c for c in pool if c.id not in used_ids]
    if not available:
        return None

    def score(c: Candidate) -> float:
        w_comp = 0.1 + 1.5 * king_traits.education
        w_loy = 0.1 + 1.5 * king_traits.fear
        w_hon = 0.1 + 1.0 * king_traits.honesty
        return (
            w_comp * c.traits.competence
            + w_loy * c.traits.loyalty
            + w_hon * c.traits.honesty
        )

    return max(available, key=score)

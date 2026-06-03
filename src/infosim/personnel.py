from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .actors import Actor, Traits

if TYPE_CHECKING:
    from .sim import Simulation


@dataclass
class Candidate:
    """A potential occupant living in the wings until summoned to a seat."""
    id: str
    display_name: str
    traits: Traits


# An empty seat is minded by an honest caretaker staff: truthful (no forgery at
# loyalty >= the forgery gate), incorruptible (ambition 0 -> no skim), modestly
# competent. Decisions for the seat are made by the regent; this only governs the
# caretaker's own observe/report so the regent hears the seat honestly.
CARETAKER_TRAITS = Traits(
    competence=0.5, honesty=0.9, loyalty=1.0, ambition=0.0, fear=0.0, education=0.5,
)


def _reset_occupant_state(office: Actor) -> None:
    """Wipe everything that belongs to the *person*, not the *office*.

    Resources (``stats``), id, location, title, parent, subordinate links, and
    the superior's resource beliefs about this office all persist — only the
    occupant's own beliefs, queues, tenure, and the trust they held over their
    subordinates reset.
    """
    office.known = {}
    office.inbox = []
    office.request_inbox = []
    office.pending_requests = {}
    office.strikes = {}


def install_occupant(
    sim: "Simulation",
    office: Actor,
    superior: Actor,
    candidate: Candidate,
    reason: str,
) -> Actor:
    """Swap a new occupant into an existing office in place.

    The office keeps its id, location, title, parent, resources, subordinates,
    and the superior's resource beliefs about it. The person changes; trust
    resets so the successor is not judged for the predecessor (the superior's
    strikes against this office are cleared).
    """
    _dismiss_occupant(sim, office, reason)

    office.display_name = candidate.display_name
    office.title = office.title  # unchanged; the seat defines the role
    office.traits = candidate.traits
    office.occupant_id = candidate.id
    office.vacant = False
    office.regent = None
    office.tenure_start_time = sim.now
    _reset_occupant_state(office)
    superior.strikes.pop(office.id, None)

    sim.event_log.emit(
        sim.now,
        "occupant_installed",
        f"[{office.location}] {candidate.display_name} takes the {office.title} "
        f"office (competence {candidate.traits.competence:.2f}, "
        f"honesty {candidate.traits.honesty:.2f}, loyalty {candidate.traits.loyalty:.2f})",
        actor=office.id,
        location=office.location,
        title=office.title,
        display_name=candidate.display_name,
        occupant_id=candidate.id,
        competence=candidate.traits.competence,
        honesty=candidate.traits.honesty,
        loyalty=candidate.traits.loyalty,
        stats=dict(office.stats),
    )
    return office


def vacate(sim: "Simulation", office: Actor, superior: Actor, reason: str) -> Actor:
    """Leave an office empty under a regent (its superior governs it remotely).

    Same resets as a swap, but the seat is held by an honest caretaker so the
    regent hears it truthfully; the regent makes the actual decisions.
    """
    _dismiss_occupant(sim, office, reason)

    office.display_name = f"(vacant {office.title})"
    office.traits = CARETAKER_TRAITS
    office.occupant_id = None
    office.vacant = True
    office.regent = superior.id
    office.tenure_start_time = sim.now
    _reset_occupant_state(office)
    superior.strikes.pop(office.id, None)

    sim.event_log.emit(
        sim.now,
        "regency_started",
        f"[{office.location}] {office.title} office falls vacant; governed "
        f"remotely by {superior.display_name} ({superior.location})",
        actor=office.id,
        location=office.location,
        title=office.title,
        regent=superior.id,
        regent_name=superior.display_name,
    )
    return office


def _dismiss_occupant(sim: "Simulation", office: Actor, reason: str) -> None:
    """Log the outgoing occupant leaving the office (the office persists)."""
    sim.event_log.emit(
        sim.now,
        "occupant_dismissed",
        f"[{office.location}] {office.title} {office.display_name} dismissed: {reason}",
        actor=office.id,
        location=office.location,
        title=office.title,
        display_name=office.display_name,
        occupant_id=office.occupant_id,
        reason=reason,
        tenure_time=sim.now - office.tenure_start_time,
        stats=dict(office.stats),
    )


def pick_replacement(
    pool: list[Candidate],
    used_ids: set[str],
    king_traits: Traits,
) -> Candidate | None:
    """Choose a candidate from the pool, biased by the chooser's trait profile.

    A paranoid chooser (high fear) prioritises loyalty.
    A scholar (high education) prioritises competence.
    A practical chooser (high honesty) prioritises honesty.
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

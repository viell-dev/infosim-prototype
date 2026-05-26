from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orders import Order


@dataclass
class Traits:
    competence: float = 0.7   # 0..1, higher = more accurate observations
    honesty: float = 0.8      # 0..1, lower = deliberate distortion
    loyalty: float = 0.8      # 0..1, lower = forgery, skim, possible betrayal
    ambition: float = 0.3     # 0..1, lower = passive; higher = corrupt initiative
    fear: float = 0.2         # 0..1, higher = suppress bad news
    education: float = 0.6    # 0..1, affects report quality


@dataclass
class BeliefRecord:
    """One actor's current belief about one subject (region, variable)."""
    subject: str                # e.g. "Frontier.garrison_strength"
    value: float
    confidence: float           # 0..1
    last_updated_time: float
    source_chain: list[str] = field(default_factory=list)


@dataclass
class Actor:
    id: str
    display_name: str
    title: str                  # "King", "Governor", "Commander", ...
    region: str                 # the region they're physically in
    reports_to: str | None      # actor id of superior, or None
    traits: Traits = field(default_factory=Traits)
    # Intervals between scheduled events of each kind. No state about
    # "last fire time" — the scheduler is the source of truth.
    report_every: float = 10.0
    observe_every: float = 5.0
    decide_every: float = 10.0
    known: dict[str, BeliefRecord] = field(default_factory=dict)
    inbox: list["Order"] = field(default_factory=list)
    tenure_start_time: float = 0.0
    strikes: dict[str, int] = field(default_factory=dict)

    def update_belief(
        self,
        subject: str,
        value: float,
        confidence: float,
        now: float,
        source_chain: list[str],
    ) -> None:
        self.known[subject] = BeliefRecord(
            subject=subject,
            value=value,
            confidence=confidence,
            last_updated_time=now,
            source_chain=source_chain,
        )

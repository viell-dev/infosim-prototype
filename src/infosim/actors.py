from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orders import Order


@dataclass
class Traits:
    competence: float = 0.7   # 0..1, higher = more accurate observations
    honesty: float = 0.8      # 0..1, lower = deliberate distortion
    loyalty: float = 0.8      # 0..1, unused in M1 except as flavour
    ambition: float = 0.3     # 0..1, currently unused (M3)
    fear: float = 0.2         # 0..1, higher = suppress bad news
    education: float = 0.6    # 0..1, affects report quality


@dataclass
class BeliefRecord:
    """One actor's current belief about one subject (region, variable)."""
    subject: str                # e.g. "Frontier.garrison_strength"
    value: float
    confidence: float           # 0..1
    last_updated_tick: int
    source_chain: list[str] = field(default_factory=list)  # actor ids the report passed through


@dataclass
class Actor:
    id: str
    display_name: str
    title: str                  # "King", "Governor", "Commander", ...
    region: str                 # the region they're physically in
    reports_to: str | None      # actor id of superior, or None
    traits: Traits = field(default_factory=Traits)
    report_every: int = 10      # cadence in ticks for sending reports upward
    observe_every: int = 5      # cadence in ticks for sampling the local true state
    decide_every: int = 10      # cadence in ticks for running decision policy
    last_report_tick: int = -10_000   # so first cadence fires soon
    last_observe_tick: int = -10_000
    last_decide_tick: int = -10_000
    known: dict[str, BeliefRecord] = field(default_factory=dict)
    inbox: list["Order"] = field(default_factory=list)  # arrived orders awaiting decide()
    tenure_start_tick: int = 0
    strikes: dict[str, int] = field(default_factory=dict)  # superior's running grievance counters

    def update_belief(
        self,
        subject: str,
        value: float,
        confidence: float,
        tick: int,
        source_chain: list[str],
    ) -> None:
        self.known[subject] = BeliefRecord(
            subject=subject,
            value=value,
            confidence=confidence,
            last_updated_tick=tick,
            source_chain=source_chain,
        )

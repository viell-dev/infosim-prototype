from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orders import Order
    from .requests import InfoRequest, PendingRequest


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
    """One node in the hierarchy. Same shape at every depth.

    A king, a governor, a commander, a captain, a trader — all use this
    schema. They differ only in cadences, traits, the policy keyed on
    ``title``, and what stat keys they actually populate.
    """
    id: str
    display_name: str
    title: str                  # used by policy dispatch (POLICY_BY_TITLE)
    location: str               # node name in the World travel topology
    commander: str | None       # actor id of the superior, or None for the apex
    traits: Traits = field(default_factory=Traits)
    # Resources this actor directly controls (their authoritative numbers).
    # A commander's garrison/food/unrest; a trader's cargo/credits; a king's
    # treasury — all the same dict shape, different keys per genre/role.
    stats: dict[str, float] = field(default_factory=dict)
    # Intervals between scheduled events of each kind. No state about
    # "last fire time" — the scheduler is the source of truth.
    report_every: float = 10.0
    observe_every: float = 5.0
    decide_every: float = 10.0
    # Beliefs about anything addressable. Key shape: f"{actor_id}.{stat_name}".
    # Includes beliefs about self (built from OBSERVE) and beliefs about
    # subordinates / siblings / superior (built from received reports).
    known: dict[str, BeliefRecord] = field(default_factory=dict)
    inbox: list["Order"] = field(default_factory=list)
    # Pull-based information primitives. request_inbox holds tuples of
    # (immediate sender id, InfoRequest) so the recipient knows who to
    # reply to. pending_requests tracks outgoing requests still awaiting
    # a response.
    request_inbox: list[tuple[str, "InfoRequest"]] = field(default_factory=list)
    pending_requests: dict[int, "PendingRequest"] = field(default_factory=dict)
    tenure_start_time: float = 0.0
    strikes: dict[str, int] = field(default_factory=dict)

    # --- back-compat properties --------------------------------------------
    # Existing call sites use ``actor.region`` and ``actor.reports_to``.
    # Map them to the new field names so the rename can land incrementally.
    @property
    def region(self) -> str:
        return self.location

    @region.setter
    def region(self, value: str) -> None:
        self.location = value

    @property
    def reports_to(self) -> str | None:
        return self.commander

    @reports_to.setter
    def reports_to(self, value: str | None) -> None:
        self.commander = value

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

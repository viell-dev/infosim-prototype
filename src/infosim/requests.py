"""Pull-based information primitive.

INFO_REQUEST / INFO_RESPONSE ride the same MessageBus as reports and orders.
They give superiors a way to *ask* instead of waiting for ambient pushes —
and give every actor along the chain a fresh decision point where they can
investigate, forward, answer from cache, fabricate, or refuse.

The engine layer (this module + scheduler kind + sim handlers) only delivers
messages and tracks pending state. The 'should I lie?' decisions live in
``policy``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InfoRequest:
    """A pull-style request for current information about specific subjects.

    Subjects are the same f"{actor_id}.{stat}" keys used for beliefs.
    A single request can ask about multiple subjects at once.
    """
    correlation_id: int
    originator: str           # actor id who first started this chain of asking
    subjects: list[str]
    deadline_time: float
    note: str = ""            # human-readable reason; surfaces in logs


@dataclass
class InfoResponse:
    """A response to a specific InfoRequest, keyed by correlation_id."""
    correlation_id: int
    # subject -> (estimated_value, confidence). Empty when refused.
    answers: dict[str, tuple[float, float]] = field(default_factory=dict)
    refused: bool = False
    refusal_reason: str = ""


@dataclass
class PendingRequest:
    """Per-actor bookkeeping for one outgoing request awaiting response.

    ``parent_correlation_id`` is set when this request was made as a *relay*
    on behalf of someone upstream — when the answer eventually arrives, the
    relaying actor composes a new response with that correlation_id and
    sends it back to ``parent_from_actor``.
    """
    correlation_id: int
    waiting_for: str          # actor id we asked
    subjects: list[str]
    deadline_time: float
    parent_correlation_id: int | None = None
    parent_from_actor: str | None = None

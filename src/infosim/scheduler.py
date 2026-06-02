from __future__ import annotations

import enum
import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any


class EventKind(enum.Enum):
    OBSERVE = "OBSERVE"
    REPORT = "REPORT"
    DECIDE = "DECIDE"
    MESSAGE_ARRIVED = "MESSAGE_ARRIVED"
    ACTION_COMPLETE = "ACTION_COMPLETE"
    SCRIPTED = "SCRIPTED"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"


@dataclass
class Event:
    kind: EventKind
    actor_id: str | None = None  # whose action; None for scripted / global
    payload: Any = None          # message, action, callable, ...


@dataclass(order=True)
class _QueuedEvent:
    when: float
    seq: int
    event: Event = field(compare=False)


class Scheduler:
    """Single-threaded discrete-event scheduler.

    Drains events in (time, insertion-order) order. Same seed → same ordering,
    which is what determinism tests rely on. Ties are broken by insertion
    sequence so the heap is total-ordered without ever comparing Event objects.
    """

    def __init__(self) -> None:
        self._heap: list[_QueuedEvent] = []
        self._seq = itertools.count()
        self.now: float = 0.0

    def schedule(self, when: float, event: Event) -> None:
        # Clamp backwards-scheduling to now; an event firing "in the past" fires
        # immediately at current logical time. This keeps the model robust to
        # rounding without silently swallowing logic bugs further upstream.
        when = max(when, self.now)
        heapq.heappush(self._heap, _QueuedEvent(when, next(self._seq), event))

    def pop_next(self) -> tuple[float, Event] | None:
        if not self._heap:
            return None
        qe = heapq.heappop(self._heap)
        self.now = qe.when
        return qe.when, qe.event

    def peek_next_time(self) -> float | None:
        if not self._heap:
            return None
        return self._heap[0].when

    def __len__(self) -> int:
        return len(self._heap)

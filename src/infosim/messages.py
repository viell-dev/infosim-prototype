from __future__ import annotations

import enum
import heapq
import itertools
import random
from dataclasses import dataclass, field
from typing import Any, Iterator

from .orders import Order
from .reports import Report


class MessageKind(enum.Enum):
    REPORT = "REPORT"
    ORDER = "ORDER"


@dataclass(order=True)
class _QueuedMessage:
    eta_tick: int
    seq: int
    message: "Message" = field(compare=False)


@dataclass
class Message:
    id: int
    kind: MessageKind
    sender_actor: str
    recipient_actor: str
    origin_region: str
    destination_region: str
    dispatch_tick: int
    eta_tick: int
    payload: Any                 # Report or Order; switch on `kind`
    lost: bool = False


class MessageBus:
    """Priority-queued courier delivery with stochastic loss and jitter.

    Carries both upward reports and downward orders. The bus is payload-agnostic;
    callers tag each dispatch with a MessageKind and the sim branches on it at
    delivery.
    """

    def __init__(self, rng: random.Random, loss_prob: float = 0.05, jitter_frac: float = 0.2):
        self._heap: list[_QueuedMessage] = []
        self._counter = itertools.count()
        self._id_counter = itertools.count(1)
        self.rng = rng
        self.loss_prob = loss_prob
        self.jitter_frac = jitter_frac

    def _dispatch(
        self,
        kind: MessageKind,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: int,
        dispatch_tick: int,
        payload: Any,
    ) -> Message:
        jitter = int(round(self.rng.gauss(0.0, self.jitter_frac * base_travel_ticks)))
        travel = max(1, base_travel_ticks + jitter)
        lost = self.rng.random() < self.loss_prob
        msg = Message(
            id=next(self._id_counter),
            kind=kind,
            sender_actor=sender_actor,
            recipient_actor=recipient_actor,
            origin_region=origin_region,
            destination_region=destination_region,
            dispatch_tick=dispatch_tick,
            eta_tick=dispatch_tick + travel,
            payload=payload,
            lost=lost,
        )
        heapq.heappush(self._heap, _QueuedMessage(msg.eta_tick, next(self._counter), msg))
        return msg

    def dispatch(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: int,
        dispatch_tick: int,
        payload: Report,
    ) -> Message:
        return self._dispatch(
            MessageKind.REPORT, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_tick, payload,
        )

    def dispatch_order(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: int,
        dispatch_tick: int,
        payload: Order,
    ) -> Message:
        return self._dispatch(
            MessageKind.ORDER, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_tick, payload,
        )

    def deliver_due(self, now: int) -> Iterator[Message]:
        while self._heap and self._heap[0].eta_tick <= now:
            yield heapq.heappop(self._heap).message

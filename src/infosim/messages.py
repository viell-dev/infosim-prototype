from __future__ import annotations

import enum
import itertools
import random
from dataclasses import dataclass
from typing import Any

from .orders import Order
from .reports import Report
from .requests import InfoRequest, InfoResponse
from .scheduler import Event, EventKind, Scheduler


class MessageKind(enum.Enum):
    REPORT = "REPORT"
    ORDER = "ORDER"
    INFO_REQUEST = "INFO_REQUEST"
    INFO_RESPONSE = "INFO_RESPONSE"


@dataclass
class Message:
    id: int
    kind: MessageKind
    sender_actor: str
    recipient_actor: str
    origin_region: str
    destination_region: str
    dispatch_time: float
    eta_time: float
    payload: Any                 # Report or Order; switch on `kind`
    lost: bool = False


class MessageBus:
    """Courier dispatch — creates Message records and schedules their arrival.

    The bus owns the RNG draws that determine jitter and loss. Once a message
    is dispatched, the scheduler is solely responsible for delivering it; there
    is no polling and no internal queue.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        rng: random.Random,
        loss_prob: float = 0.05,
        jitter_frac: float = 0.2,
    ):
        self._scheduler = scheduler
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
        base_travel_ticks: float,
        dispatch_time: float,
        payload: Any,
    ) -> Message:
        jitter = self.rng.gauss(0.0, self.jitter_frac * base_travel_ticks)
        travel = max(1.0, base_travel_ticks + jitter)
        lost = self.rng.random() < self.loss_prob
        msg = Message(
            id=next(self._id_counter),
            kind=kind,
            sender_actor=sender_actor,
            recipient_actor=recipient_actor,
            origin_region=origin_region,
            destination_region=destination_region,
            dispatch_time=dispatch_time,
            eta_time=dispatch_time + travel,
            payload=payload,
            lost=lost,
        )
        self._scheduler.schedule(
            msg.eta_time,
            Event(kind=EventKind.MESSAGE_ARRIVED, actor_id=recipient_actor, payload=msg),
        )
        return msg

    def dispatch(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: float,
        dispatch_time: float,
        payload: Report,
    ) -> Message:
        return self._dispatch(
            MessageKind.REPORT, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_time, payload,
        )

    def dispatch_order(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: float,
        dispatch_time: float,
        payload: Order,
    ) -> Message:
        return self._dispatch(
            MessageKind.ORDER, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_time, payload,
        )

    def dispatch_request(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: float,
        dispatch_time: float,
        payload: InfoRequest,
    ) -> Message:
        return self._dispatch(
            MessageKind.INFO_REQUEST, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_time, payload,
        )

    def dispatch_response(
        self,
        sender_actor: str,
        recipient_actor: str,
        origin_region: str,
        destination_region: str,
        base_travel_ticks: float,
        dispatch_time: float,
        payload: InfoResponse,
    ) -> Message:
        return self._dispatch(
            MessageKind.INFO_RESPONSE, sender_actor, recipient_actor,
            origin_region, destination_region, base_travel_ticks, dispatch_time, payload,
        )

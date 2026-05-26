from __future__ import annotations

import random

from infosim.messages import MessageBus, MessageKind
from infosim.orders import Order, OrderKind
from infosim.scheduler import EventKind, Scheduler


def _stub_order() -> Order:
    return Order(
        id=1,
        issuer="king",
        recipient="gov",
        kind=OrderKind.REINFORCE,
        target_region="Frontier",
        magnitude=300.0,
        issued_time=10.0,
        deadline_time=80.0,
    )


def test_order_dispatch_schedules_arrival() -> None:
    sched = Scheduler()
    bus = MessageBus(scheduler=sched, rng=random.Random(0), loss_prob=0.0, jitter_frac=0.0)
    msg = bus.dispatch_order(
        sender_actor="king",
        recipient_actor="gov",
        origin_region="Capital",
        destination_region="Province",
        base_travel_ticks=4.0,
        dispatch_time=10.0,
        payload=_stub_order(),
    )
    assert msg.kind is MessageKind.ORDER
    assert msg.eta_time == 14.0
    popped = sched.pop_next()
    assert popped is not None
    when, event = popped
    assert when == 14.0
    assert event.kind is EventKind.MESSAGE_ARRIVED
    assert isinstance(event.payload.payload, Order)


def test_lost_order_marked_lost() -> None:
    sched = Scheduler()
    bus = MessageBus(scheduler=sched, rng=random.Random(0), loss_prob=1.0, jitter_frac=0.0)
    msg = bus.dispatch_order(
        sender_actor="king",
        recipient_actor="gov",
        origin_region="Capital",
        destination_region="Province",
        base_travel_ticks=3.0,
        dispatch_time=0.0,
        payload=_stub_order(),
    )
    assert msg.lost is True

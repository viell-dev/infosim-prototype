from __future__ import annotations

import random

from infosim.messages import MessageBus, MessageKind
from infosim.reports import Report
from infosim.scheduler import EventKind, Scheduler


def _stub_report() -> Report:
    return Report(
        source_actor="a",
        subject="x",
        estimated_value=10.0,
        confidence=0.5,
        origin_time=0.0,
        source_chain=["a"],
    )


def test_message_dispatch_schedules_arrival() -> None:
    sched = Scheduler()
    bus = MessageBus(scheduler=sched, rng=random.Random(0), loss_prob=0.0, jitter_frac=0.0)
    msg = bus.dispatch(
        sender_actor="a",
        recipient_actor="b",
        origin_region="A",
        destination_region="B",
        base_travel_ticks=5.0,
        dispatch_time=10.0,
        payload=_stub_report(),
    )
    assert msg.eta_time == 15.0
    popped = sched.pop_next()
    assert popped is not None
    when, event = popped
    assert when == 15.0
    assert event.kind is EventKind.MESSAGE_ARRIVED
    assert event.payload is msg
    assert event.payload.kind is MessageKind.REPORT


def test_loss_marks_message_lost() -> None:
    sched = Scheduler()
    bus = MessageBus(scheduler=sched, rng=random.Random(0), loss_prob=1.0, jitter_frac=0.0)
    msg = bus.dispatch(
        sender_actor="a",
        recipient_actor="b",
        origin_region="A",
        destination_region="B",
        base_travel_ticks=3.0,
        dispatch_time=0.0,
        payload=_stub_report(),
    )
    assert msg.lost is True
    # arrival event is still scheduled — the sim's handler logs it as courier_lost.
    popped = sched.pop_next()
    assert popped is not None
    when, event = popped
    assert event.kind is EventKind.MESSAGE_ARRIVED
    assert event.payload.lost is True

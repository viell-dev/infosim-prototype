from __future__ import annotations

import random

from infosim.messages import MessageBus
from infosim.reports import Report


def _stub_report() -> Report:
    return Report(
        source_actor="a",
        subject="x",
        estimated_value=10.0,
        confidence=0.5,
        origin_tick=0,
        source_chain=["a"],
    )


def test_message_delivered_after_eta() -> None:
    bus = MessageBus(rng=random.Random(0), loss_prob=0.0, jitter_frac=0.0)
    msg = bus.dispatch(
        sender_actor="a",
        recipient_actor="b",
        origin_region="A",
        destination_region="B",
        base_travel_ticks=5,
        dispatch_tick=10,
        payload=_stub_report(),
    )
    assert msg.eta_tick == 15
    assert list(bus.deliver_due(14)) == []
    delivered = list(bus.deliver_due(15))
    assert len(delivered) == 1
    assert delivered[0].id == msg.id


def test_loss_marks_message() -> None:
    bus = MessageBus(rng=random.Random(0), loss_prob=1.0, jitter_frac=0.0)
    bus.dispatch(
        sender_actor="a",
        recipient_actor="b",
        origin_region="A",
        destination_region="B",
        base_travel_ticks=3,
        dispatch_tick=0,
        payload=_stub_report(),
    )
    delivered = list(bus.deliver_due(10))
    assert len(delivered) == 1
    assert delivered[0].lost is True

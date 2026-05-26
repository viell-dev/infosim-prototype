from __future__ import annotations

import random

from infosim.messages import MessageBus, MessageKind
from infosim.orders import Order, OrderKind


def _stub_order() -> Order:
    return Order(
        id=1,
        issuer="king",
        recipient="gov",
        kind=OrderKind.REINFORCE,
        target_region="Frontier",
        magnitude=300.0,
        issued_tick=10,
        deadline_tick=80,
    )


def test_order_dispatched_arrives_after_eta() -> None:
    bus = MessageBus(rng=random.Random(0), loss_prob=0.0, jitter_frac=0.0)
    msg = bus.dispatch_order(
        sender_actor="king",
        recipient_actor="gov",
        origin_region="Capital",
        destination_region="Province",
        base_travel_ticks=4,
        dispatch_tick=10,
        payload=_stub_order(),
    )
    assert msg.kind is MessageKind.ORDER
    assert msg.eta_tick == 14
    assert list(bus.deliver_due(13)) == []
    delivered = list(bus.deliver_due(14))
    assert len(delivered) == 1
    assert delivered[0].kind is MessageKind.ORDER
    assert isinstance(delivered[0].payload, Order)


def test_lost_order_marked_lost() -> None:
    bus = MessageBus(rng=random.Random(0), loss_prob=1.0, jitter_frac=0.0)
    bus.dispatch_order(
        sender_actor="king",
        recipient_actor="gov",
        origin_region="Capital",
        destination_region="Province",
        base_travel_ticks=3,
        dispatch_tick=0,
        payload=_stub_order(),
    )
    delivered = list(bus.deliver_due(10))
    assert len(delivered) == 1
    assert delivered[0].lost is True
    assert delivered[0].kind is MessageKind.ORDER

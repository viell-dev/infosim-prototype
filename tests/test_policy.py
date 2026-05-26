from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, BeliefRecord, Traits
from infosim.logging_setup import EventLog
from infosim.orders import Order, OrderKind
from infosim.policy import decide_king
from infosim.scheduler import EventKind
from infosim.sim import Simulation
from infosim.world import Region, World


def _mini_world() -> tuple[World, dict[str, Actor]]:
    world = World()
    world.add_region(Region(name="Capital",
                            state={"garrison_strength": 1200, "food_stores": 3000, "unrest": 5}))
    world.add_region(Region(name="Province",
                            state={"garrison_strength": 800, "food_stores": 1800, "unrest": 20}))
    world.add_region(Region(name="Frontier",
                            state={"garrison_strength": 1500, "food_stores": 1500, "unrest": 20}))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)
    king = Actor(id="king", display_name="K", title="King", region="Capital",
                 reports_to=None, traits=Traits(honesty=1.0, fear=0.0))
    gov = Actor(id="gov", display_name="G", title="Governor", region="Province",
                reports_to="king", traits=Traits())
    cmd = Actor(id="cmd", display_name="C", title="Commander", region="Frontier",
                reports_to="gov", traits=Traits())
    return world, {"king": king, "gov": gov, "cmd": cmd}


def _sim(tmp_path: Path) -> Simulation:
    world, actors = _mini_world()
    rng = random.Random(0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(
        world=world, actors=actors, rng=rng, event_log=log,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )


def _scheduled_orders(sim: Simulation) -> list[Order]:
    return [
        qe.event.payload.payload
        for qe in sim.scheduler._heap
        if qe.event.kind is EventKind.MESSAGE_ARRIVED
        and isinstance(qe.event.payload.payload, Order)
    ]


def _belief(value: float) -> BeliefRecord:
    return BeliefRecord(
        subject="x", value=value, confidence=0.7,
        last_updated_time=0.0, source_chain=["gov", "king"],
    )


def test_king_issues_reinforce_when_belief_low(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.garrison_strength"] = _belief(400.0)
    decide_king(sim, king)
    assert any(o.kind is OrderKind.REINFORCE for o in _scheduled_orders(sim))


def test_king_silent_when_belief_healthy(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.garrison_strength"] = _belief(1500.0)
    king.known["Frontier.unrest"] = _belief(10.0)
    king.known["Frontier.food_stores"] = _belief(1500.0)
    decide_king(sim, king)
    assert _scheduled_orders(sim) == []


def test_king_orders_suppression_when_unrest_high(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.unrest"] = _belief(80.0)
    decide_king(sim, king)
    assert any(o.kind is OrderKind.SUPPRESS_UNREST for o in _scheduled_orders(sim))

from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, BeliefRecord, Traits
from infosim.logging_setup import EventLog
from infosim.messages import MessageBus, MessageKind
from infosim.orders import OrderKind
from infosim.policy import decide_king
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
    bus = MessageBus(rng=rng, loss_prob=0.0, jitter_frac=0.0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(world=world, actors=actors, bus=bus, rng=rng, event_log=log)


def _outbound_orders(sim: Simulation) -> list:
    return [m for m in (q.message for q in sim.bus._heap)
            if m.kind is MessageKind.ORDER]


def test_king_issues_reinforce_when_belief_low(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.garrison_strength"] = BeliefRecord(
        subject="Frontier.garrison_strength", value=400.0, confidence=0.7,
        last_updated_tick=0, source_chain=["gov", "king"],
    )
    decide_king(sim, king)
    orders = _outbound_orders(sim)
    kinds = [o.payload.kind for o in orders]
    assert OrderKind.REINFORCE in kinds


def test_king_silent_when_belief_healthy(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.garrison_strength"] = BeliefRecord(
        subject="Frontier.garrison_strength", value=1500.0, confidence=0.7,
        last_updated_tick=0, source_chain=["gov", "king"],
    )
    king.known["Frontier.unrest"] = BeliefRecord(
        subject="Frontier.unrest", value=10.0, confidence=0.7,
        last_updated_tick=0, source_chain=["gov", "king"],
    )
    king.known["Frontier.food_stores"] = BeliefRecord(
        subject="Frontier.food_stores", value=1500.0, confidence=0.7,
        last_updated_tick=0, source_chain=["gov", "king"],
    )
    decide_king(sim, king)
    assert _outbound_orders(sim) == []


def test_king_orders_suppression_when_unrest_high(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king = sim.actors["king"]
    king.known["Frontier.unrest"] = BeliefRecord(
        subject="Frontier.unrest", value=80.0, confidence=0.7,
        last_updated_tick=0, source_chain=["gov", "king"],
    )
    decide_king(sim, king)
    orders = _outbound_orders(sim)
    assert any(o.payload.kind is OrderKind.SUPPRESS_UNREST for o in orders)

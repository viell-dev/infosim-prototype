from __future__ import annotations

import random
from pathlib import Path

from infosim.actions import suppress_unrest, transfer_garrison
from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.messages import MessageBus
from infosim.sim import Simulation
from infosim.world import Region, World


def _sim(tmp_path: Path, seed: int = 0) -> Simulation:
    world = World()
    world.add_region(Region(name="Province",
                            state={"garrison_strength": 800, "food_stores": 1800, "unrest": 40}))
    world.add_region(Region(name="Frontier",
                            state={"garrison_strength": 500, "food_stores": 800, "unrest": 30}))
    world.connect("Province", "Frontier", travel_ticks=6)
    gov = Actor(id="gov", display_name="G", title="Governor", region="Province",
                reports_to=None, traits=Traits())
    rng = random.Random(seed)
    bus = MessageBus(rng=rng, loss_prob=0.0, jitter_frac=0.0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(world=world, actors={"gov": gov}, bus=bus, rng=rng, event_log=log)


def test_transfer_garrison_removes_then_adds(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    sim.tick = 10
    action = transfer_garrison(sim, "gov", "Province", "Frontier", 200.0)
    assert action is not None
    # immediate effect: src lost 200
    assert sim.world.regions["Province"].state["garrison_strength"] == 600
    assert sim.world.regions["Frontier"].state["garrison_strength"] == 500
    # apply completion
    sim.tick = 16
    action.effect_fn(sim)
    assert sim.world.regions["Frontier"].state["garrison_strength"] == 700


def test_suppress_unrest_competent_actor_lowers_unrest(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    sim.tick = 0
    rng = random.Random(0)
    action = suppress_unrest(sim, "gov", "Province", duration=10, competence=1.0, rng=rng)
    # competence=1.0 → backlash chance is 0; outcome is deterministic.
    sim.tick = 10
    action.effect_fn(sim)
    assert sim.world.regions["Province"].state["unrest"] < 40

from __future__ import annotations

import random
from pathlib import Path

from infosim.actions import suppress_unrest, transfer_garrison
from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.scenarios.frontier import RULESET
from infosim.sim import Simulation
from infosim.world import Location, World


def _sim(tmp_path: Path, seed: int = 0) -> Simulation:
    world = World()
    world.add_location(Location(name="Province"))
    world.add_location(Location(name="Frontier"))
    world.connect("Province", "Frontier", travel_ticks=6)
    gov = Actor(
        id="gov", display_name="G", title="Governor",
        location="Province", commander=None, traits=Traits(),
        stats={"garrison_strength": 800, "food_stores": 1800, "unrest": 40},
    )
    cmd = Actor(
        id="cmd", display_name="C", title="Commander",
        location="Frontier", commander="gov", traits=Traits(),
        stats={"garrison_strength": 500, "food_stores": 800, "unrest": 30},
    )
    rng = random.Random(seed)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(
        world=world, actors={"gov": gov, "cmd": cmd}, rng=rng, event_log=log,
        ruleset=RULESET,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )


def test_transfer_garrison_removes_then_adds(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    sim.scheduler.now = 10.0
    action = transfer_garrison(sim, "gov", "gov", "cmd", 200.0)
    assert action is not None
    # immediate effect: src lost 200
    assert sim.actors["gov"].stats["garrison_strength"] == 600
    assert sim.actors["cmd"].stats["garrison_strength"] == 500
    # apply completion
    sim.scheduler.now = 16.0
    action.effect_fn(sim)
    assert sim.actors["cmd"].stats["garrison_strength"] == 700


def test_suppress_unrest_competent_actor_lowers_unrest(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    sim.scheduler.now = 0.0
    rng = random.Random(0)
    action = suppress_unrest(sim, "gov", "gov", duration=10.0, competence=1.0, rng=rng)
    # competence=1.0 → backlash chance is 0; outcome is deterministic.
    sim.scheduler.now = 10.0
    action.effect_fn(sim)
    assert sim.actors["gov"].stats["unrest"] < 40

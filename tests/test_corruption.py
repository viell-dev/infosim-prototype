from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.policy import _maybe_skim
from infosim.sim import Simulation
from infosim.world import Region, World


def _sim(traits: Traits, tmp_path: Path) -> tuple[Simulation, Actor]:
    world = World()
    world.add_region(Region(name="Frontier",
                            state={"garrison_strength": 500, "food_stores": 1000, "unrest": 0}))
    actor = Actor(id="cmd", display_name="C", title="Commander", region="Frontier",
                  reports_to=None, traits=traits)
    rng = random.Random(0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    sim = Simulation(
        world=world, actors={"cmd": actor}, rng=rng, event_log=log,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )
    return sim, actor


def test_disloyal_ambitious_actor_skims(tmp_path: Path) -> None:
    # Skim is now stochastic — probability per decide is ambition*(1-loyalty).
    # At (0.2, 0.8) that's 0.64, so over 50 cycles the chance of zero skims is
    # vanishingly small (0.36**50 ≈ 1e-22). The test checks the population
    # behaviour, not a single deterministic call.
    sim, actor = _sim(Traits(loyalty=0.2, ambition=0.8), tmp_path)
    before = sim.world.regions["Frontier"].state["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert sim.world.regions["Frontier"].state["food_stores"] < before


def test_loyal_actor_does_not_skim(tmp_path: Path) -> None:
    # Hard gate at loyalty >= 0.4 — should never skim regardless of how many
    # cycles fire.
    sim, actor = _sim(Traits(loyalty=0.9, ambition=0.8), tmp_path)
    before = sim.world.regions["Frontier"].state["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert sim.world.regions["Frontier"].state["food_stores"] == before


def test_unambitious_actor_does_not_skim(tmp_path: Path) -> None:
    sim, actor = _sim(Traits(loyalty=0.1, ambition=0.2), tmp_path)
    before = sim.world.regions["Frontier"].state["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert sim.world.regions["Frontier"].state["food_stores"] == before

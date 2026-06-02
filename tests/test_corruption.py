from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.policies.corruption import _maybe_skim
from infosim.sim import Simulation
from infosim.world import Location, World


def _sim(traits: Traits, tmp_path: Path) -> tuple[Simulation, Actor]:
    world = World()
    world.add_location(Location(name="Frontier"))
    actor = Actor(
        id="cmd", display_name="C", title="Commander",
        location="Frontier", commander=None, traits=traits,
        stats={"garrison_strength": 500, "food_stores": 1000, "unrest": 0},
    )
    rng = random.Random(0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    sim = Simulation(
        world=world, actors={"cmd": actor}, rng=rng, event_log=log,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )
    return sim, actor


def test_disloyal_ambitious_actor_skims(tmp_path: Path) -> None:
    # Skim is stochastic; the disloyal+ambitious actor draws against probability
    # ambition * (1 - loyalty)^2 every cycle. Over 50 calls the chance of zero
    # skims is vanishingly small.
    sim, actor = _sim(Traits(loyalty=0.2, ambition=0.8), tmp_path)
    before = actor.stats["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert actor.stats["food_stores"] < before


def test_loyal_actor_does_not_skim(tmp_path: Path) -> None:
    # Hard gate at loyalty >= 0.85 — should never skim.
    sim, actor = _sim(Traits(loyalty=0.9, ambition=0.8), tmp_path)
    before = actor.stats["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert actor.stats["food_stores"] == before


def test_unambitious_actor_does_not_skim(tmp_path: Path) -> None:
    # Hard gate at ambition >= 0.3 — should never skim.
    sim, actor = _sim(Traits(loyalty=0.1, ambition=0.2), tmp_path)
    before = actor.stats["food_stores"]
    for _ in range(50):
        _maybe_skim(sim, actor)
    assert actor.stats["food_stores"] == before

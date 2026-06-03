from __future__ import annotations

import random
import sys
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.policies.roles import run_policy
from infosim.scenarios import frontier, space_miner
from infosim.sim import Simulation
from infosim.world import Location, World

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.map_run import (  # noqa: E402
    _infer_scenario,
    _read_events,
    _stats_in_state,
    build_checkpoints,
)


def test_captain_produces_and_taxes_upward(tmp_path: Path) -> None:
    """A space_miner Captain's role data alone (production + tax specs) drives
    mining ore from ships and paying a share upward — no captain-specific code
    in the core.
    """
    world = World()
    world.add_location(Location(name="Homeworld"))
    world.add_location(Location(name="Belt"))
    world.connect("Homeworld", "Belt", travel_ticks=5)
    # loyalty high enough to never skim, so the produce/tax effect is exact.
    boss = Actor(id="ceo", display_name="Boss", title="CEO",
                 location="Homeworld", commander=None,
                 traits=Traits(loyalty=0.95), stats={"ore": 0.0})
    captain = Actor(id="cap", display_name="Cap", title="Captain",
                    location="Belt", commander="ceo",
                    traits=Traits(competence=0.7, loyalty=0.95, ambition=0.3),
                    stats={"ships": 5.0, "ore": 100.0})
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    sim = Simulation(
        world=world, actors={"ceo": boss, "cap": captain},
        rng=random.Random(0), event_log=log, ruleset=space_miner.RULESET,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )

    run_policy(sim, captain)

    # Mining: 5 ships * 18 * (0.5 + 0.7 competence) = 108 ore produced.
    mined = 5.0 * 18.0 * (0.5 + 0.7)
    taxed = (100.0 + mined) * 0.25
    assert captain.stats["ore"] == 100.0 + mined - taxed
    assert any(
        ev["kind"] == "action_started" and ev.get("kind_detail") == "ore_tax"
        for ev in log.events
    )

    # The tax courier delivers the ore to the boss after travel.
    sim._bootstrapped = True
    sim.run_until(6.0)
    assert boss.stats["ore"] == taxed


def _run_stats(run_fn, seed: int, ticks: int, runs_dir: Path) -> set[str]:
    base = run_fn(seed=seed, ticks=ticks, runs_dir=runs_dir)
    jsonl = base.with_suffix(".jsonl")
    events = _read_events(jsonl)
    checkpoints = build_checkpoints(events, _infer_scenario(jsonl))
    return set(_stats_in_state(checkpoints[-1].state))


def test_genre_isolation(tmp_path: Path) -> None:
    """A frontier run only ever touches medieval stats; a space_miner run only
    ever touches sci-fi stats. The two genres share the core but not each
    other's resource vocabulary.
    """
    frontier_stats = _run_stats(frontier.run, 1, 120, tmp_path / "f")
    space_stats = _run_stats(space_miner.run, 2, 200, tmp_path / "s")

    assert frontier_stats == {"garrison_strength", "food_stores", "unrest"}
    assert space_stats == {"ore", "ships", "population", "alien_presence"}
    assert frontier_stats.isdisjoint(space_stats)

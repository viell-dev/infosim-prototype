from __future__ import annotations

import argparse
import datetime as dt
import random
from pathlib import Path

from ..actors import Actor, Traits
from ..logging_setup import EventLog
from ..messages import MessageBus
from ..sim import Simulation
from ..world import Region, World


def build() -> tuple[World, dict[str, Actor]]:
    world = World()
    world.add_region(Region(
        name="Capital",
        state={"garrison_strength": 1200, "food_stores": 3000, "unrest": 10},
    ))
    world.add_region(Region(
        name="Province",
        state={"garrison_strength": 800, "food_stores": 1800, "unrest": 25},
    ))
    world.add_region(Region(
        name="Frontier",
        state={"garrison_strength": 1500, "food_stores": 900, "unrest": 40},
    ))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)

    actors: dict[str, Actor] = {}

    def add(a: Actor) -> None:
        actors[a.id] = a

    # King: high education, low fear, mostly honest. Reports to no one.
    add(Actor(
        id="king",
        display_name="Halric III",
        title="King",
        region="Capital",
        reports_to=None,
        traits=Traits(competence=0.75, honesty=0.9, fear=0.05, education=0.9),
        report_every=999_999,
        observe_every=8,
    ))

    # Governor: politically cautious, moderately corrupt.
    add(Actor(
        id="gov_mira",
        display_name="Mira of Halen",
        title="Governor",
        region="Province",
        reports_to="king",
        traits=Traits(competence=0.6, honesty=0.55, fear=0.4, education=0.7, ambition=0.7),
        report_every=12,
        observe_every=6,
    ))

    # Frontier commander: competent observer but frightened of looking weak.
    add(Actor(
        id="cmd_aldric",
        display_name="Aldric Vale",
        title="Commander",
        region="Frontier",
        reports_to="gov_mira",
        traits=Traits(competence=0.8, honesty=0.7, fear=0.6, education=0.5),
        report_every=8,
        observe_every=4,
    ))

    return world, actors


def _bump(sim: Simulation, region: str, var: str, delta: float, cause: str) -> None:
    r = sim.world.regions[region]
    before = r.state[var]
    after = max(0.0, before + delta)
    r.state[var] = after
    sim.event_log.emit(
        sim.tick,
        "true_state_change",
        f"[{region}] {cause}: {var} {before:.0f} → {after:.0f}",
        region=region,
        variable=var,
        before=before,
        after=after,
        cause=cause,
    )


def scripted_events(sim: Simulation) -> None:
    """Wire scripted true-state shocks."""
    sim.schedule_event(40,  lambda s: _bump(s, "Frontier", "garrison_strength", -700, "raid"))
    sim.schedule_event(40,  lambda s: _bump(s, "Frontier", "unrest", +30, "raid_aftermath"))
    sim.schedule_event(80,  lambda s: _bump(s, "Frontier", "food_stores", -400, "supply_loss"))
    sim.schedule_event(120, lambda s: _bump(s, "Province", "garrison_strength", -200, "levy_dispatch"))
    sim.schedule_event(120, lambda s: _bump(s, "Province", "unrest", +15, "levy_resentment"))
    sim.schedule_event(160, lambda s: _bump(s, "Frontier", "garrison_strength", +300, "reinforcements"))
    sim.schedule_event(180, lambda s: _bump(s, "Frontier", "food_stores", +500, "supply_train"))


def run(seed: int, ticks: int, runs_dir: Path) -> Path:
    rng = random.Random(seed)
    world, actors = build()
    bus = MessageBus(rng=rng, loss_prob=0.08, jitter_frac=0.25)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"frontier-seed{seed}-{stamp}"
    log = EventLog(jsonl_path=base.with_suffix(".jsonl"), human_path=base.with_suffix(".log"))
    log.open()

    sim = Simulation(world=world, actors=actors, bus=bus, rng=rng, event_log=log)
    scripted_events(sim)
    try:
        sim.run(total_ticks=ticks)

        # Final snapshot: truth vs. King's belief, for every variable in every region.
        king = actors["king"]
        log.emit(sim.tick, "final_snapshot", "=== END OF RUN ===")
        for region in world.regions.values():
            for var, true_value in sorted(region.state.items()):
                subj = Simulation.subject_for(region.name, var)
                belief = king.known.get(subj)
                if belief is None:
                    summary = (
                        f"[{region.name}] {var}: truth={true_value:.0f}  "
                        f"king's belief: (none)"
                    )
                else:
                    age = sim.tick - belief.last_updated_tick
                    summary = (
                        f"[{region.name}] {var}: truth={true_value:.0f}  "
                        f"king ≈ {belief.value:.0f} (conf {belief.confidence:.2f}, "
                        f"age {age}t, chain {' → '.join(belief.source_chain) or '—'})"
                    )
                log.emit(sim.tick, "final_snapshot", summary, region=region.name, variable=var)
    finally:
        log.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=200)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    out = run(args.seed, args.ticks, args.runs_dir)
    print(f"Wrote {out}.jsonl and {out}.log")


if __name__ == "__main__":
    main()

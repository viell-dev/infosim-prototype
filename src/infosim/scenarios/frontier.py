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
    world.add_region(Region(name="Capital", garrison_strength=1200))
    world.add_region(Region(name="Province", garrison_strength=800))
    world.add_region(Region(name="Frontier", garrison_strength=1500))
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
    ))

    # Governor: politically cautious, moderately corrupt, reports to king every 12 ticks.
    add(Actor(
        id="gov_mira",
        display_name="Mira of Halen",
        title="Governor",
        region="Province",
        reports_to="king",
        traits=Traits(competence=0.6, honesty=0.55, fear=0.4, education=0.7, ambition=0.7),
        report_every=12,
    ))

    # Frontier commander: competent, frightened of looking weak, reports every 8 ticks.
    add(Actor(
        id="cmd_aldric",
        display_name="Aldric Vale",
        title="Commander",
        region="Frontier",
        reports_to="gov_mira",
        traits=Traits(competence=0.8, honesty=0.7, fear=0.6, education=0.5),
        report_every=8,
    ))

    return world, actors


def scripted_events(sim: Simulation) -> None:
    """Wire scripted true-state shocks. Logs are inside Simulation for the changes too."""

    def raid_frontier(s: Simulation) -> None:
        before = s.world.regions["Frontier"].garrison_strength
        s.world.regions["Frontier"].garrison_strength = max(0, before - 700)
        after = s.world.regions["Frontier"].garrison_strength
        s.event_log.emit(
            s.tick,
            "true_state_change",
            f"[Frontier] RAID — garrison {before} → {after}",
            region="Frontier",
            variable="garrison_strength",
            before=before,
            after=after,
            cause="raid",
        )

    def reinforcements(s: Simulation) -> None:
        before = s.world.regions["Frontier"].garrison_strength
        s.world.regions["Frontier"].garrison_strength = before + 300
        s.event_log.emit(
            s.tick,
            "true_state_change",
            f"[Frontier] reinforcements arrive — garrison {before} → "
            f"{s.world.regions['Frontier'].garrison_strength}",
            region="Frontier",
            variable="garrison_strength",
            before=before,
            after=s.world.regions["Frontier"].garrison_strength,
            cause="reinforcements",
        )

    def province_drain(s: Simulation) -> None:
        before = s.world.regions["Province"].garrison_strength
        s.world.regions["Province"].garrison_strength = max(0, before - 200)
        s.event_log.emit(
            s.tick,
            "true_state_change",
            f"[Province] levies sent away — garrison {before} → "
            f"{s.world.regions['Province'].garrison_strength}",
            region="Province",
            variable="garrison_strength",
            before=before,
            after=s.world.regions["Province"].garrison_strength,
            cause="levy_dispatch",
        )

    sim.schedule_event(40, raid_frontier)
    sim.schedule_event(120, province_drain)
    sim.schedule_event(160, reinforcements)


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

        # Final snapshot: truth vs. King's belief
        king = actors["king"]
        log.emit(
            sim.tick,
            "final_snapshot",
            "=== END OF RUN ===",
        )
        for region in world.regions.values():
            subj = Simulation.subject_for(region.name, "garrison_strength")
            belief = king.known.get(subj)
            if belief is None:
                summary = f"[{region.name}] truth={region.garrison_strength}  king's belief: (none)"
            else:
                age = sim.tick - belief.last_updated_tick
                summary = (
                    f"[{region.name}] truth={region.garrison_strength}  "
                    f"king believes ≈ {belief.value:.0f} (conf {belief.confidence:.2f}, "
                    f"age {age}t, chain {' → '.join(belief.source_chain) or '—'})"
                )
            log.emit(sim.tick, "final_snapshot", summary, region=region.name)
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

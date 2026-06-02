"""Four-level hierarchy validating the unified Actor schema at arbitrary depth.

      King (Capital)
        └─ General (HQ)
              └─ Colonel (Fort)
                    └─ Captain (Outpost)

No engine changes are needed beyond step-2's request primitive and step-3's
generalised order-routing. The same observe / report / decide / audit
machinery runs at each rung regardless of how many layers sit above or
below. The deepest Captain's stats reach the King through three relay hops;
the King's orders reach the Captain through three forwarding hops, each one
a fresh decision point at which the actor at that hop can answer/lie/
forward/refuse — same dynamics as the two-chain Frontier scenario, only
deeper.

Run:
    PYTHONPATH=src python3 -m infosim.scenarios.deep_chain --seed 1 --ticks 400
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
from pathlib import Path

from ..actors import Actor, Traits
from ..logging_setup import EventLog
from ..personnel import Candidate
from ..sim import Simulation
from ..world import Location, World


def build() -> tuple[World, dict[str, Actor]]:
    world = World()
    for loc in ("Capital", "HQ", "Fort", "Outpost"):
        world.add_location(Location(name=loc))
    world.connect("Capital", "HQ", travel_ticks=4)
    world.connect("HQ", "Fort", travel_ticks=4)
    world.connect("Fort", "Outpost", travel_ticks=4)

    actors: dict[str, Actor] = {}

    def add(a: Actor) -> None:
        actors[a.id] = a

    # King at the apex.
    add(Actor(
        id="king",
        display_name="Halric III",
        title="King",
        location="Capital",
        commander=None,
        traits=Traits(competence=0.8, honesty=0.9, fear=0.05, education=0.9),
        stats={"garrison_strength": 1500, "food_stores": 4000, "unrest": 5},
        report_every=999_999,
        observe_every=10,
        decide_every=20,
    ))

    # General — middle layer 1. Uses Governor policy (same shape as a
    # governor — receives orders, possibly forwards, has subordinates).
    add(Actor(
        id="gen_kallen",
        display_name="Kallen Voss",
        title="Governor",
        location="HQ",
        commander="king",
        traits=Traits(competence=0.7, honesty=0.7, loyalty=0.7,
                      fear=0.3, education=0.7, ambition=0.5),
        stats={"garrison_strength": 1200, "food_stores": 2500, "unrest": 15},
        report_every=12,
        observe_every=6,
        decide_every=10,
    ))

    # Colonel — middle layer 2. Same Governor policy applies; the engine
    # routes orders down through her without special-casing depth.
    add(Actor(
        id="col_renna",
        display_name="Renna Foss",
        title="Governor",
        location="Fort",
        commander="gen_kallen",
        traits=Traits(competence=0.65, honesty=0.6, loyalty=0.5,
                      fear=0.4, education=0.55, ambition=0.6),
        stats={"garrison_strength": 1000, "food_stores": 2000, "unrest": 20},
        report_every=10,
        observe_every=5,
        decide_every=10,
    ))

    # Captain — leaf. Same Commander policy as Aldric/Talen. Disloyal +
    # ambitious so we can watch forgery/skim propagate up three layers
    # back to the King.
    add(Actor(
        id="cap_dren",
        display_name="Dren Marcellus",
        title="Commander",
        location="Outpost",
        commander="col_renna",
        traits=Traits(competence=0.75, honesty=0.5, loyalty=0.3,
                      fear=0.6, education=0.5, ambition=0.7),
        stats={"garrison_strength": 1300, "food_stores": 900, "unrest": 35},
        report_every=8,
        observe_every=4,
        decide_every=8,
    ))

    return world, actors


def candidate_pool() -> list[Candidate]:
    return [
        Candidate(id="cand_alta", display_name="Alta of Marn",
                  traits=Traits(competence=0.7, honesty=0.8, loyalty=0.85,
                                fear=0.3, education=0.7, ambition=0.4)),
        Candidate(id="cand_bren", display_name="Bren Holt",
                  traits=Traits(competence=0.6, honesty=0.7, loyalty=0.7,
                                fear=0.3, education=0.6, ambition=0.5)),
    ]


def _bump(sim: Simulation, location: str, stat: str, delta: float, cause: str) -> None:
    holder = next((a for a in sim.actors.values() if a.location == location), None)
    if holder is None:
        return
    before = holder.stats.get(stat, 0.0)
    after = max(0.0, before + delta)
    holder.stats[stat] = after
    sim.event_log.emit(
        sim.now, "true_state_change",
        f"[{location}] {cause} hits {holder.display_name}: {stat} {before:.0f} → {after:.0f}",
        actor=holder.id, location=location, stat=stat,
        before=before, after=after, cause=cause,
    )


def scripted_events(sim: Simulation) -> None:
    sim.schedule_scripted(60.0,  lambda s: _bump(s, "Outpost", "garrison_strength", -500, "raid"))
    sim.schedule_scripted(60.0,  lambda s: _bump(s, "Outpost", "unrest", +25, "raid_aftermath"))
    sim.schedule_scripted(120.0, lambda s: _bump(s, "Outpost", "food_stores", -300, "supply_loss"))
    sim.schedule_scripted(180.0, lambda s: _bump(s, "Fort",    "unrest", +20, "tax_riot"))
    sim.schedule_scripted(240.0, lambda s: _bump(s, "Outpost", "unrest", +30, "unrest_spike"))


def run(seed: int, ticks: int, runs_dir: Path) -> Path:
    rng = random.Random(seed)
    world, actors = build()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"deepchain-seed{seed}-{stamp}"
    log = EventLog(jsonl_path=base.with_suffix(".jsonl"), human_path=base.with_suffix(".log"))
    log.open()
    sim = Simulation(
        world=world, actors=actors, rng=rng, event_log=log,
        candidate_pool=candidate_pool(),
        bus_loss_prob=0.08, bus_jitter_frac=0.25,
    )
    scripted_events(sim)
    try:
        sim.run_until(float(ticks))
        king = actors["king"]
        log.emit(sim.now, "final_snapshot", "=== END OF RUN ===")
        for actor in sorted(actors.values(), key=lambda a: a.id):
            for stat, true_value in sorted(actor.stats.items()):
                subj = Simulation.subject_for(actor.id, stat)
                belief = king.known.get(subj)
                tag = f"[{actor.location}] {actor.display_name}"
                if belief is None:
                    summary = f"{tag} {stat}: truth={true_value:.0f}  king's belief: (none)"
                else:
                    age = sim.now - belief.last_updated_time
                    summary = (
                        f"{tag} {stat}: truth={true_value:.0f}  "
                        f"king ≈ {belief.value:.0f} (conf {belief.confidence:.2f}, "
                        f"age {age:.0f}t, chain {' → '.join(belief.source_chain)})"
                    )
                log.emit(sim.now, "final_snapshot", summary, actor=actor.id, stat=stat)
    finally:
        log.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=400)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    out = run(args.seed, args.ticks, args.runs_dir)
    print(f"Wrote {out}.jsonl and {out}.log")


if __name__ == "__main__":
    main()

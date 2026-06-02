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
    """Two-chain topology so the King has siblings to compare.

        Capital  ──→ Province (Mira)   ──→ Frontier    (Aldric)   corrupt chain
                 └→ Marches  (Cassia)  ──→ Borderlands (Talen)    honest chain

    The two chains face similar (but not identical) shocks. Reports diverge
    not only because of distance and bias but because the *people* differ —
    one chain has a disloyal commander forging numbers and skimming food,
    the other has a loyal commander reporting honestly. The King's belief
    snapshot at end-of-run is the comparison artifact.
    """
    world = World()
    for loc_name in ("Capital", "Province", "Frontier", "Marches", "Borderlands"):
        world.add_location(Location(name=loc_name))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)
    world.connect("Capital", "Marches", travel_ticks=5)
    world.connect("Marches", "Borderlands", travel_ticks=5)

    actors: dict[str, Actor] = {}

    def add(a: Actor) -> None:
        actors[a.id] = a

    # King: high education, low fear, mostly honest. Reports to no one.
    add(Actor(
        id="king",
        display_name="Halric III",
        title="King",
        location="Capital",
        commander=None,
        traits=Traits(competence=0.75, honesty=0.9, fear=0.05, education=0.9),
        stats={"garrison_strength": 1200, "food_stores": 3000, "unrest": 10},
        report_every=999_999,
        observe_every=8,
        decide_every=20,
    ))

    # --- corrupt chain ---------------------------------------------------
    # Governor Mira: politically cautious, moderately corrupt.
    add(Actor(
        id="gov_mira",
        display_name="Mira of Halen",
        title="Governor",
        location="Province",
        commander="king",
        traits=Traits(competence=0.6, honesty=0.55, fear=0.4, education=0.7, ambition=0.7),
        stats={"garrison_strength": 800, "food_stores": 1800, "unrest": 25},
        report_every=12,
        observe_every=6,
        decide_every=10,
    ))
    # Frontier commander Aldric: competent observer but with loyalty issues
    # and serious ambition — the disloyalty engine of this scenario.
    add(Actor(
        id="cmd_aldric",
        display_name="Aldric Vale",
        title="Commander",
        location="Frontier",
        commander="gov_mira",
        traits=Traits(
            competence=0.8, honesty=0.5, loyalty=0.25, ambition=0.8,
            fear=0.6, education=0.5,
        ),
        stats={"garrison_strength": 1500, "food_stores": 900, "unrest": 40},
        report_every=8,
        observe_every=4,
        decide_every=8,
    ))

    # --- honest chain ----------------------------------------------------
    # Governor Cassia: loyal, honest, modest ambition. The foil to Mira.
    add(Actor(
        id="gov_cassia",
        display_name="Cassia of Reach",
        title="Governor",
        location="Marches",
        commander="king",
        traits=Traits(competence=0.65, honesty=0.85, loyalty=0.8,
                      fear=0.2, education=0.75, ambition=0.4),
        stats={"garrison_strength": 1000, "food_stores": 1800, "unrest": 20},
        report_every=12,
        observe_every=6,
        decide_every=10,
    ))
    # Commander Talen: loyal, honest, moderately competent. Foil to Aldric.
    add(Actor(
        id="cmd_talen",
        display_name="Talen Voss",
        title="Commander",
        location="Borderlands",
        commander="gov_cassia",
        traits=Traits(competence=0.7, honesty=0.8, loyalty=0.85,
                      fear=0.3, education=0.6, ambition=0.3),
        stats={"garrison_strength": 1500, "food_stores": 900, "unrest": 30},
        report_every=8,
        observe_every=4,
        decide_every=8,
    ))

    return world, actors


def candidate_pool() -> list[Candidate]:
    """Five reserve appointees with deliberately divergent profiles.

    Two-chain topology means dismissals can run through the pool faster, so
    the bench is wider. Each profile is intentionally lopsided on one or
    two axes so the King's pick reveals his own bias.
    """
    return [
        Candidate(
            id="cand_brennar",
            display_name="Brennar Holt",
            traits=Traits(competence=0.55, honesty=0.85, loyalty=0.9,
                          ambition=0.3, fear=0.3, education=0.6),
        ),
        Candidate(
            id="cand_iselle",
            display_name="Iselle Marn",
            traits=Traits(competence=0.9, honesty=0.7, loyalty=0.5,
                          ambition=0.6, fear=0.2, education=0.8),
        ),
        Candidate(
            id="cand_terrick",
            display_name="Terrick of Wynn",
            traits=Traits(competence=0.7, honesty=0.75, loyalty=0.7,
                          ambition=0.4, fear=0.3, education=0.8),
        ),
        Candidate(
            id="cand_orla",
            display_name="Orla of Stenmark",
            traits=Traits(competence=0.8, honesty=0.6, loyalty=0.4,
                          ambition=0.7, fear=0.25, education=0.7),
        ),
        Candidate(
            id="cand_vanek",
            display_name="Vanek the Younger",
            traits=Traits(competence=0.5, honesty=0.9, loyalty=0.95,
                          ambition=0.2, fear=0.45, education=0.5),
        ),
    ]


def _bump(sim: Simulation, location: str, stat: str, delta: float, cause: str) -> None:
    """Apply a scripted shock to whichever actor currently holds the post at
    ``location``. Resources are tied to the office, not the individual — if
    the original incumbent was dismissed and replaced, the replacement takes
    the hit. If the post is vacant (candidate pool exhausted), silently log.
    """
    holder = next((a for a in sim.actors.values() if a.location == location), None)
    if holder is None:
        sim.event_log.emit(
            sim.now, "true_state_change_skipped",
            f"scripted {cause} at {location} skipped — post vacant",
            location=location, stat=stat, cause=cause,
        )
        return
    before = holder.stats.get(stat, 0.0)
    after = max(0.0, before + delta)
    holder.stats[stat] = after
    sim.event_log.emit(
        sim.now,
        "true_state_change",
        f"[{location}] {cause} hits {holder.display_name}: "
        f"{stat} {before:.0f} → {after:.0f}",
        actor=holder.id,
        location=location,
        stat=stat,
        before=before,
        after=after,
        cause=cause,
    )


def scripted_events(sim: Simulation) -> None:
    """Wire scripted true-state shocks across both chains.

    Frontier (Aldric) and Borderlands (Talen) face comparable
    raids/unrest/supply shocks at staggered times. The two regions reach
    roughly similar *true* states — the divergence in the King's belief
    between them is then almost entirely the difference between Aldric
    (forging) and Talen (honest).
    """
    # corrupt chain
    sim.schedule_scripted(40.0,  lambda s: _bump(s, "Frontier",    "garrison_strength", -700, "raid"))
    sim.schedule_scripted(40.0,  lambda s: _bump(s, "Frontier",    "unrest", +30, "raid_aftermath"))
    sim.schedule_scripted(60.0,  lambda s: _bump(s, "Frontier",    "unrest", +25, "unrest_spike"))
    sim.schedule_scripted(80.0,  lambda s: _bump(s, "Frontier",    "food_stores", -400, "supply_loss"))
    sim.schedule_scripted(140.0, lambda s: _bump(s, "Province",    "unrest", +30, "tax_riot"))
    # honest chain — staggered so the log stays legible
    sim.schedule_scripted(70.0,  lambda s: _bump(s, "Borderlands", "garrison_strength", -600, "raid"))
    sim.schedule_scripted(70.0,  lambda s: _bump(s, "Borderlands", "unrest", +25, "raid_aftermath"))
    sim.schedule_scripted(120.0, lambda s: _bump(s, "Borderlands", "food_stores", -350, "supply_loss"))
    sim.schedule_scripted(180.0, lambda s: _bump(s, "Borderlands", "unrest", +20, "unrest_spike"))
    sim.schedule_scripted(220.0, lambda s: _bump(s, "Marches",     "unrest", +20, "tax_riot"))


def run(seed: int, ticks: int, runs_dir: Path) -> Path:
    rng = random.Random(seed)
    world, actors = build()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"frontier-seed{seed}-{stamp}"
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

        # Final snapshot: truth vs. King's belief per (actor, stat).
        king = actors["king"]
        log.emit(sim.now, "final_snapshot", "=== END OF RUN ===")
        for actor in sorted(actors.values(), key=lambda a: a.id):
            for stat, true_value in sorted(actor.stats.items()):
                subj = Simulation.subject_for(actor.id, stat)
                belief = king.known.get(subj)
                tag = f"[{actor.location}] {actor.display_name}"
                if belief is None:
                    summary = (
                        f"{tag} {stat}: truth={true_value:.0f}  king's belief: (none)"
                    )
                else:
                    age = sim.now - belief.last_updated_time
                    summary = (
                        f"{tag} {stat}: truth={true_value:.0f}  "
                        f"king ≈ {belief.value:.0f} (conf {belief.confidence:.2f}, "
                        f"age {age:.0f}t, chain {' → '.join(belief.source_chain) or '—'})"
                    )
                log.emit(sim.now, "final_snapshot", summary,
                         actor=actor.id, stat=stat)
    finally:
        log.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=200,
                        help="logical time units to advance")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    out = run(args.seed, args.ticks, args.runs_dir)
    print(f"Wrote {out}.jsonl and {out}.log")


if __name__ == "__main__":
    main()

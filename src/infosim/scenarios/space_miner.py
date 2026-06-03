from __future__ import annotations

import argparse
import datetime as dt
import random
from pathlib import Path

from ..actors import Actor, Traits
from ..logging_setup import EventLog
from ..orders import OrderKind
from ..personnel import Candidate
from ..policies.orders import _dispatch_order
from ..ruleset import (
    DecaySpec,
    ProductionSpec,
    RoleSpec,
    Ruleset,
    StatSpec,
    TaxSpec,
)
from ..sim import Simulation
from ..world import Location, World


# --- ruleset: the space-mining genre as data ---------------------------------
# ore / ships / population are "good news"; alien_presence is "bad news". The
# Captain mines ore from ships and taxes it upward; the Manager consumes ore by
# population and taxes a smaller share; defense spends ships against aliens.
RULESET = Ruleset(
    stats={
        "ore":            StatSpec("ore",            polarity=+1),
        "ships":          StatSpec("ships",          polarity=+1),
        "population":     StatSpec("population",     polarity=+1),
        "alien_presence": StatSpec("alien_presence", polarity=-1),
    },
    defense_stat="ships",
    supply_stat="ore",
    threat_stat="alien_presence",
    bad_news_thresholds={
        "ore": 500.0,
        "ships": 8.0,
        "alien_presence": 20.0,
    },
    roles={
        "CEO": RoleSpec(
            title="CEO",
            behaviors=("issue_orders", "apex_defense_orders"),
            thresholds={
                "low_defense": 7.0,
                "low_supply": 1200.0,
                "high_threat": 35.0,
                "review_threat": 60.0,
                "review_defense": 800.0,
            },
        ),
        "Manager": RoleSpec(
            title="Manager",
            behaviors=(
                "skim", "execute_orders", "autonomous_suppress",
                "consume", "tax", "local_defense_orders",
            ),
            decay=(DecaySpec(stat="ore", rate=0.08, driver_stat="population"),),
            tax=(TaxSpec(stat="ore", fraction=0.10, label="manager_tax"),),
            thresholds={"autonomous_threat": 25.0},
        ),
        "Captain": RoleSpec(
            title="Captain",
            behaviors=("skim", "produce", "tax"),
            production=(
                ProductionSpec(output_stat="ore", driver_stat="ships",
                               rate=18.0, competence_curve=0.5),
            ),
            tax=(TaxSpec(stat="ore", fraction=0.25, label="ore_tax"),),
        ),
        "Commander": RoleSpec(
            title="Commander",
            behaviors=("skim", "execute_orders", "urgent_reports", "defend"),
            thresholds={"leaf_low_supply": 150.0, "leaf_low_defense": 3.0},
        ),
    },
)


def build() -> tuple[World, dict[str, Actor]]:
    """Space-mining variant of frontier.

    The office hierarchy is CEO -> Manager -> Captain, while Commanders are
    mobile military posts. Stations carry population, ore stores, and local
    alien pressure; Captains mine infinite ore sources and pay tax upward.
    """
    world = World()
    for loc_name in (
        "Homeworld",
        "Lagrange Hub",
        "Ceres Station",
        "Europa Station",
        "Titan Foundry",
        "Kuiper Relay",
    ):
        world.add_location(Location(name=loc_name))
    world.connect("Homeworld", "Lagrange Hub", travel_ticks=5)
    world.connect("Lagrange Hub", "Ceres Station", travel_ticks=6)
    world.connect("Lagrange Hub", "Europa Station", travel_ticks=8)
    world.connect("Lagrange Hub", "Titan Foundry", travel_ticks=10)
    world.connect("Titan Foundry", "Kuiper Relay", travel_ticks=7)
    world.connect("Ceres Station", "Europa Station", travel_ticks=7)
    world.connect("Europa Station", "Titan Foundry", travel_ticks=6)
    world.connect("Homeworld", "Ceres Station", travel_ticks=10)
    world.connect("Homeworld", "Europa Station", travel_ticks=12)
    world.connect("Homeworld", "Titan Foundry", travel_ticks=14)

    actors: dict[str, Actor] = {}

    def add(a: Actor) -> None:
        actors[a.id] = a

    add(Actor(
        id="ceo",
        display_name="Director Vale",
        title="CEO",
        location="Homeworld",
        commander=None,
        traits=Traits(competence=0.75, honesty=0.85, loyalty=0.9, fear=0.15, education=0.9),
        stats={"ore": 8000, "population": 40000, "ships": 0, "alien_presence": 0},
        report_every=999_999,
        observe_every=10,
        decide_every=18,
    ))

    add(Actor(
        id="mgr_ceres",
        display_name="Mira Quell",
        title="Manager",
        location="Ceres Station",
        commander="ceo",
        traits=Traits(competence=0.62, honesty=0.55, loyalty=0.5, ambition=0.75,
                      fear=0.45, education=0.7),
        stats={"ore": 2200, "population": 9000, "ships": 0, "alien_presence": 0},
        report_every=12,
        observe_every=6,
        decide_every=9,
    ))
    add(Actor(
        id="mgr_europa",
        display_name="Cass Ren",
        title="Manager",
        location="Europa Station",
        commander="ceo",
        traits=Traits(competence=0.72, honesty=0.82, loyalty=0.8, ambition=0.35,
                      fear=0.25, education=0.78),
        stats={"ore": 1800, "population": 7600, "ships": 0, "alien_presence": 0},
        report_every=12,
        observe_every=6,
        decide_every=9,
    ))
    add(Actor(
        id="mgr_titan",
        display_name="Neria Sol",
        title="Manager",
        location="Titan Foundry",
        commander="ceo",
        traits=Traits(competence=0.66, honesty=0.7, loyalty=0.65, ambition=0.55,
                      fear=0.35, education=0.72),
        stats={"ore": 2600, "population": 12000, "ships": 0, "alien_presence": 0},
        report_every=12,
        observe_every=6,
        decide_every=9,
    ))

    add(Actor(
        id="cmd_orion",
        display_name="Orion Dray",
        title="Commander",
        location="Homeworld",
        commander="ceo",
        traits=Traits(competence=0.78, honesty=0.75, loyalty=0.7, ambition=0.45,
                      fear=0.25, education=0.65),
        stats={"ships": 10, "ore": 0, "alien_presence": 0},
        report_every=8,
        observe_every=4,
        decide_every=7,
    ))
    add(Actor(
        id="cmd_helix",
        display_name="Helix Marr",
        title="Commander",
        location="Ceres Station",
        commander="mgr_ceres",
        traits=Traits(competence=0.58, honesty=0.6, loyalty=0.45, ambition=0.7,
                      fear=0.55, education=0.5),
        stats={"ships": 6, "ore": 0, "alien_presence": 0},
        report_every=8,
        observe_every=4,
        decide_every=7,
    ))
    add(Actor(
        id="cmd_voss",
        display_name="Voss Kade",
        title="Commander",
        location="Titan Foundry",
        commander="mgr_titan",
        traits=Traits(competence=0.7, honesty=0.8, loyalty=0.85, ambition=0.3,
                      fear=0.2, education=0.6),
        stats={"ships": 8, "ore": 0, "alien_presence": 0},
        report_every=8,
        observe_every=4,
        decide_every=7,
    ))

    for actor_id, name, manager, station, ships, honesty, loyalty in (
        ("cap_iona", "Iona Pike", "mgr_ceres", "Ceres Station", 4, 0.62, 0.55),
        ("cap_sable", "Sable Noon", "mgr_ceres", "Ceres Station", 5, 0.72, 0.65),
        ("cap_ro", "Ro Lumen", "mgr_europa", "Europa Station", 6, 0.85, 0.82),
        ("cap_alen", "Alen Cross", "mgr_titan", "Titan Foundry", 7, 0.68, 0.58),
    ):
        add(Actor(
            id=actor_id,
            display_name=name,
            title="Captain",
            location=station,
            commander=manager,
            traits=Traits(competence=0.6 + ships * 0.03, honesty=honesty, loyalty=loyalty,
                          ambition=0.55, fear=0.3, education=0.5),
            stats={"ships": float(ships), "ore": 300.0, "alien_presence": 0.0},
            report_every=9,
            observe_every=5,
            decide_every=8,
        ))

    return world, actors


def candidate_pool() -> list[Candidate]:
    return [
        Candidate(
            id="cand_arden",
            display_name="Arden Kest",
            traits=Traits(competence=0.75, honesty=0.85, loyalty=0.85,
                          ambition=0.35, fear=0.25, education=0.7),
        ),
        Candidate(
            id="cand_tamsin",
            display_name="Tamsin Rue",
            traits=Traits(competence=0.9, honesty=0.65, loyalty=0.55,
                          ambition=0.65, fear=0.2, education=0.85),
        ),
    ]


def _station_holder(sim: Simulation, location: str) -> Actor | None:
    return next(
        (
            a for a in sim.actors.values()
            if a.location == location and a.title in {"Manager", "CEO"}
        ),
        None,
    )


def _alien(sim: Simulation, location: str, amount: float, cause: str) -> None:
    holder = _station_holder(sim, location)
    if holder is None:
        return
    before = holder.stats.get("alien_presence", 0.0)
    holder.stats["alien_presence"] = before + amount
    sim.event_log.emit(
        sim.now,
        "alien_contact",
        f"[{location}] {cause}: alien_presence {before:.0f} → "
        f"{holder.stats['alien_presence']:.0f}",
        actor=holder.id,
        location=location,
        stat="alien_presence",
        before=before,
        after=holder.stats["alien_presence"],
        cause=cause,
    )


def _mission_orders(sim: Simulation) -> None:
    ceo = sim.actors["ceo"]
    cmd = sim.actors["cmd_orion"]
    mgr_ceres = sim.actors["mgr_ceres"]
    _dispatch_order(
        sim, ceo, cmd, OrderKind.MOVE_TO_LOCATION, cmd.id,
        magnitude=0, priority=3, target_location="Ceres Station",
        assigned_commander=mgr_ceres.id,
    )


def _forward_orion(sim: Simulation) -> None:
    cmd = sim.actors.get("cmd_orion")
    current_superior = sim.actors.get(cmd.commander) if cmd is not None else None
    mgr_europa = _station_holder(sim, "Europa Station")
    if current_superior is None or cmd is None or mgr_europa is None:
        return
    _dispatch_order(
        sim, current_superior, cmd, OrderKind.MOVE_TO_LOCATION, cmd.id,
        magnitude=0, priority=3, target_location="Europa Station",
        assigned_commander=mgr_europa.id,
    )


def _recall_orion(sim: Simulation) -> None:
    ceo = sim.actors.get("ceo")
    cmd = sim.actors.get("cmd_orion")
    current_superior = sim.actors.get(cmd.commander) if cmd is not None else None
    if ceo is None or current_superior is None or cmd is None:
        return
    _dispatch_order(
        sim, current_superior, cmd, OrderKind.MOVE_TO_LOCATION, cmd.id,
        magnitude=0, priority=3, target_location="Homeworld",
        assigned_commander=ceo.id,
    )


def scripted_events(sim: Simulation) -> None:
    # Warnings come before peak contact so commanders can be shuffled.
    sim.schedule_scripted(70.0, lambda s: _alien(s, "Ceres Station", 28, "sensor ghosts"))
    sim.schedule_scripted(88.0, lambda s: _mission_orders(s))
    sim.schedule_scripted(112.0, lambda s: _alien(s, "Ceres Station", 70, "alien swarm"))
    sim.schedule_scripted(155.0, lambda s: _alien(s, "Europa Station", 30, "long-range warning"))
    sim.schedule_scripted(170.0, lambda s: _forward_orion(s))
    sim.schedule_scripted(195.0, lambda s: _alien(s, "Europa Station", 85, "alien swarm"))
    sim.schedule_scripted(250.0, lambda s: _alien(s, "Titan Foundry", 45, "outer pickets lost"))
    sim.schedule_scripted(285.0, lambda s: _alien(s, "Titan Foundry", 95, "alien swarm"))
    sim.schedule_scripted(190.0, lambda s: _recall_orion(s))
    sim.schedule_scripted(390.0, lambda s: _alien(s, "Homeworld", 55, "raider breakthrough"))


def run(seed: int, ticks: int, runs_dir: Path) -> Path:
    rng = random.Random(seed)
    world, actors = build()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"space_miner-seed{seed}-{stamp}"
    log = EventLog(jsonl_path=base.with_suffix(".jsonl"), human_path=base.with_suffix(".log"))
    log.open()

    sim = Simulation(
        world=world,
        actors=actors,
        rng=rng,
        event_log=log,
        ruleset=RULESET,
        candidate_pool=candidate_pool(),
        bus_loss_prob=0.06,
        bus_jitter_frac=0.25,
    )
    scripted_events(sim)
    try:
        sim.run_until(float(ticks))
        ceo = actors["ceo"]
        log.emit(sim.now, "final_snapshot", "=== END OF SPACE MINER RUN ===")
        for actor in sorted(actors.values(), key=lambda a: a.id):
            for stat, true_value in sorted(actor.stats.items()):
                subj = Simulation.subject_for(actor.id, stat)
                belief = ceo.known.get(subj)
                tag = f"[{actor.location}] {actor.display_name}"
                if belief is None:
                    summary = f"{tag} {stat}: truth={true_value:.0f}  CEO belief: (none)"
                else:
                    age = sim.now - belief.last_updated_time
                    summary = (
                        f"{tag} {stat}: truth={true_value:.0f}  "
                        f"CEO ≈ {belief.value:.0f} (conf {belief.confidence:.2f}, "
                        f"age {age:.0f}t, chain {' → '.join(belief.source_chain) or '—'})"
                    )
                log.emit(sim.now, "final_snapshot", summary, actor=actor.id, stat=stat)
    finally:
        log.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ticks", type=int, default=500,
                        help="logical time units to advance")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    out = run(args.seed, args.ticks, args.runs_dir)
    print(f"Wrote {out}.jsonl and {out}.log")


if __name__ == "__main__":
    main()

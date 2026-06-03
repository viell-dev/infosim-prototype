"""Generated 5x5 fantasy kingdom scenario.

The design source is ``docs/isekai-kingdom-scenario.md``. This module keeps the
current engine contract intact: generated world detail is logged as structured
setup events, while the stats that already have generic mechanics are fed into
the ruleset as normal actor resources.
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
from dataclasses import dataclass, field
from pathlib import Path

from ..actors import Actor, Traits
from ..logging_setup import EventLog
from ..personnel import Candidate, install_occupant, vacate
from ..ruleset import DecaySpec, ProductionSpec, RoleSpec, Ruleset, StatSpec, TaxSpec
from ..sim import Simulation
from ..world import Location, World


COLUMNS = ("A", "B", "C", "D", "E")
ROWS = (1, 2, 3, 4, 5)
REGIONS = tuple(f"{col}{row}" for row in ROWS for col in COLUMNS)
CAPITAL = "C3"
NORTH_PORT = "C1"
SOUTH_PORT = "C5"
RACES = ("human", "elf", "orc", "beast-man", "dwarf", "demon")
POP_STATS = tuple(f"{race.replace('-', '_')}_pops" for race in RACES)
SOLDIER_STATS = tuple(f"{race.replace('-', '_')}_soldiers" for race in RACES)
WARRIOR_STATS = tuple(f"{race.replace('-', '_')}_warriors" for race in RACES)

SETTLEMENT_CAPACITY = {
    "village": 420,
    "town": 1100,
    "city": 2600,
}
SETTLEMENT_UPGRADES = {
    "village": "town",
    "town": "city",
}
SETTLEMENT_UPGRADE_COSTS = {
    "town": {"lumber": 110.0, "ore": 45.0, "wares": 70.0, "money": 160.0},
    "city": {"lumber": 260.0, "ore": 160.0, "wares": 190.0, "money": 430.0},
}


RULESET = Ruleset(
    stats={
        "food_stores": StatSpec("food_stores", polarity=+1),
        "soldiers": StatSpec("soldiers", polarity=+1),
        "monster_pressure": StatSpec("monster_pressure", polarity=-1),
        "unrest": StatSpec("unrest", polarity=-1),
        "population": StatSpec("population", polarity=+1),
        "money": StatSpec("money", polarity=+1),
        "lumber": StatSpec("lumber", polarity=+1),
        "herbs": StatSpec("herbs", polarity=+1),
        "ore": StatSpec("ore", polarity=+1),
        "wares": StatSpec("wares", polarity=+1),
        "luxury_goods": StatSpec("luxury_goods", polarity=+1),
        "weapons": StatSpec("weapons", polarity=+1),
        "warriors": StatSpec("warriors", polarity=+1),
        "scouts": StatSpec("scouts", polarity=+1),
        "kingsguard": StatSpec("kingsguard", polarity=+1),
        "noble_distrust": StatSpec("noble_distrust", polarity=-1),
        "forest_tension": StatSpec("forest_tension", polarity=-1),
        "tax_multiplier": StatSpec("tax_multiplier", polarity=-1),
        "food_workers": StatSpec("food_workers", polarity=+1),
        "lumber_workers": StatSpec("lumber_workers", polarity=+1),
        "herb_workers": StatSpec("herb_workers", polarity=+1),
        "ore_workers": StatSpec("ore_workers", polarity=+1),
        "craft_workers": StatSpec("craft_workers", polarity=+1),
        "trade_workers": StatSpec("trade_workers", polarity=+1),
        **{stat: StatSpec(stat, polarity=+1) for stat in POP_STATS},
        **{stat: StatSpec(stat, polarity=+1) for stat in SOLDIER_STATS},
        **{stat: StatSpec(stat, polarity=+1) for stat in WARRIOR_STATS},
    },
    defense_stat="soldiers",
    supply_stat="food_stores",
    threat_stat="monster_pressure",
    bad_news_thresholds={
        "food_stores": 850.0,
        "soldiers": 180.0,
        "monster_pressure": 45.0,
        "unrest": 55.0,
        "money": 250.0,
        "wares": 80.0,
        "scouts": 2.0,
        "forest_tension": 50.0,
    },
    roles={
        "King": RoleSpec(
            title="King",
            behaviors=("issue_orders", "consume"),
            decay=(
                DecaySpec(stat="food_stores", rate=0.006, driver_stat="population"),
                DecaySpec(stat="money", rate=0.001),
                DecaySpec(stat="kingsguard", rate=0.001),
            ),
            thresholds={
                "low_defense": 240.0,
                "low_supply": 950.0,
                "high_threat": 48.0,
                "review_threat": 70.0,
                "review_defense": 140.0,
            },
            review_titles=("Noble", "Royal Noble"),
        ),
        "Noble": RoleSpec(
            title="Noble",
            behaviors=("skim", "execute_orders", "consume", "tax", "autonomous_suppress"),
            decay=(
                DecaySpec(stat="food_stores", rate=0.004, driver_stat="population"),
                DecaySpec(stat="money", rate=0.003),
                DecaySpec(stat="scouts", rate=0.010),
            ),
            tax=(
                TaxSpec(stat="food_stores", fraction=0.035, label="food_tax"),
                TaxSpec(stat="money", fraction=0.025, label="coin_tax"),
            ),
            thresholds={"autonomous_threat": 70.0},
        ),
        "Royal Noble": RoleSpec(
            title="Royal Noble",
            behaviors=("skim", "execute_orders", "consume", "tax", "autonomous_suppress"),
            decay=(
                DecaySpec(stat="food_stores", rate=0.004, driver_stat="population"),
                DecaySpec(stat="money", rate=0.003),
                DecaySpec(stat="scouts", rate=0.010),
            ),
            tax=(
                TaxSpec(stat="food_stores", fraction=0.025, label="royal_food_tax"),
                TaxSpec(stat="money", fraction=0.018, label="royal_coin_tax"),
            ),
            thresholds={"autonomous_threat": 74.0},
        ),
        "Mayor": RoleSpec(
            title="Mayor",
            behaviors=(
                "skim",
                "produce",
                "execute_orders",
                "consume",
                "tax",
                "autonomous_suppress",
                "urgent_reports",
            ),
            production=(
                ProductionSpec("food_stores", "food_workers", rate=0.12),
                ProductionSpec("lumber", "lumber_workers", rate=0.09),
                ProductionSpec("herbs", "herb_workers", rate=0.06),
                ProductionSpec("ore", "ore_workers", rate=0.10),
                ProductionSpec("wares", "craft_workers", rate=0.055),
                ProductionSpec("luxury_goods", "trade_workers", rate=0.020),
                ProductionSpec("money", "trade_workers", rate=0.08),
            ),
            decay=(
                DecaySpec(stat="food_stores", rate=0.026, driver_stat="population"),
                DecaySpec(stat="herbs", rate=0.002, driver_stat="population"),
                DecaySpec(stat="wares", rate=0.002, driver_stat="population"),
                DecaySpec(stat="monster_pressure", rate=0.010),
            ),
            tax=(
                TaxSpec(stat="food_stores", fraction=0.070, label="settlement_food_tax"),
                TaxSpec(stat="money", fraction=0.055, label="settlement_coin_tax"),
            ),
            thresholds={
                "autonomous_threat": 62.0,
                "leaf_low_supply": 520.0,
                "leaf_low_defense": 90.0,
            },
        ),
        "Guard Captain": RoleSpec(
            title="Guard Captain",
            behaviors=("skim", "consume", "urgent_reports", "defend"),
            decay=(
                DecaySpec(stat="food_stores", rate=0.24, driver_stat="soldiers"),
                DecaySpec(stat="weapons", rate=0.006),
            ),
            thresholds={"leaf_low_supply": 180.0, "leaf_low_defense": 70.0},
        ),
    },
)


@dataclass(frozen=True)
class Settlement:
    name: str
    size: str
    specialization: str | None
    focus: str | None
    defense_quality: float
    population: int


@dataclass(frozen=True)
class RegionProfile:
    coord: str
    owner_id: str
    developed: bool
    undeveloped_chance: float
    settlements: tuple[Settlement, ...]
    primary_economy: str
    race_pops: dict[str, int]
    stats: dict[str, float]
    geography: dict[str, float]


@dataclass(frozen=True)
class NobleProfile:
    id: str
    display_name: str
    race: str
    is_royal: bool
    holdings: tuple[str, ...]
    seat: str
    traits: Traits
    prejudice: tuple[str, ...]
    preference: tuple[str, ...]
    family_ties: tuple[str, ...] = ()


@dataclass(frozen=True)
class KingdomSetup:
    seed: int
    king_second_region: str
    nobles: dict[str, NobleProfile]
    regions: dict[str, RegionProfile]
    actors: dict[str, Actor]
    world: World


def undeveloped_probability(holding_count: int) -> float:
    """Chance that an eligible region starts undeveloped.

    This is intentionally monotonic: the more regions a Noble has, the more
    likely at least one holding is neglected at generation time.
    """
    return min(0.48, 0.08 + 0.075 * max(0, holding_count - 1))


def generate(seed: int = 1) -> KingdomSetup:
    rng = random.Random(seed)
    world = _build_world()
    ownership, king_second = _assign_ownership(rng)
    noble_profiles = _build_nobles(rng, ownership)
    regions = _build_regions(rng, ownership)
    actors = _build_actors(rng, noble_profiles, regions)
    return KingdomSetup(
        seed=seed,
        king_second_region=king_second,
        nobles=noble_profiles,
        regions=regions,
        actors=actors,
        world=world,
    )


def build(seed: int = 1) -> tuple[World, dict[str, Actor]]:
    setup = generate(seed)
    return setup.world, setup.actors


def candidate_pool() -> list[Candidate]:
    return [
        Candidate(
            id="cand_maris",
            display_name="Maris Aven",
            traits=Traits(competence=0.78, honesty=0.86, loyalty=0.82, ambition=0.35,
                          fear=0.22, education=0.72),
            identity="human",
            prejudice={"demon": 0.20},
            preference={"dwarf": 0.15},
        ),
        Candidate(
            id="cand_osric",
            display_name="Osric Bell",
            traits=Traits(competence=0.66, honesty=0.72, loyalty=0.92, ambition=0.25,
                          fear=0.36, education=0.58),
            identity="beast-man",
            prejudice={"demon": 0.10},
            preference={"human": 0.15},
        ),
        Candidate(
            id="cand_senna",
            display_name="Senna Voss",
            traits=Traits(competence=0.90, honesty=0.62, loyalty=0.58, ambition=0.70,
                          fear=0.18, education=0.88),
            identity="demon",
            prejudice={"orc": 0.18},
            preference={"human": 0.12},
        ),
        Candidate(
            id="cand_iora",
            display_name="Iora Dusk",
            traits=Traits(competence=0.70, honesty=0.80, loyalty=0.74, ambition=0.42,
                          fear=0.28, education=0.76),
            identity="elf",
            prejudice={"dwarf": 0.10},
            preference={"beast-man": 0.18},
        ),
        Candidate(
            id="cand_garron",
            display_name="Garron Pike",
            traits=Traits(competence=0.58, honesty=0.88, loyalty=0.96, ambition=0.18,
                          fear=0.50, education=0.46),
            identity="dwarf",
            prejudice={"elf": 0.16},
            preference={"dwarf": 0.10},
        ),
        Candidate(
            id="cand_velia",
            display_name="Velia Thorn",
            traits=Traits(competence=0.82, honesty=0.58, loyalty=0.48, ambition=0.76,
                          fear=0.24, education=0.80),
            identity="orc",
            prejudice={"demon": 0.12},
            preference={"orc": 0.15},
        ),
    ]


def _build_world() -> World:
    world = World()
    for coord in REGIONS:
        world.add_location(Location(name=coord))
    for a in REGIONS:
        ax, ay = _xy(a)
        for b in REGIONS:
            if a == b:
                continue
            bx, by = _xy(b)
            travel = max(abs(ax - bx), abs(ay - by)) * 3
            world.connect(a, b, travel_ticks=max(2, travel))
    return world


def _assign_ownership(rng: random.Random) -> tuple[dict[str, str], str]:
    second_region_candidates = [
        coord
        for coord in REGIONS
        if coord != CAPITAL
        and not _connected(coord, CAPITAL)
        and _row(coord) != 1
        and _col(coord) != "A"
        and (_row(coord) == 5 or (_geography(coord)["agriculture"] >= _geography(coord)["mining"]))
    ]
    king_second = _weighted_choice(
        rng,
        [
            (
                coord,
                0.2
                + _geography(coord)["agriculture"] * 5.0
                + _geography(coord)["coast"] * 6.0
                - _geography(coord)["mining"] * 1.5,
            )
            for coord in second_region_candidates
        ],
    )

    ownership = {CAPITAL: "king", king_second: "king"}
    remaining = [coord for coord in REGIONS if coord not in ownership]
    noble_count = rng.randint(7, 9)
    noble_ids = [f"noble_{idx + 1:02d}" for idx in range(noble_count)]

    for noble_id in noble_ids:
        coord = rng.choice(remaining)
        remaining.remove(coord)
        ownership[coord] = noble_id

    while remaining:
        holding_counts = {
            noble_id: sum(1 for owner in ownership.values() if owner == noble_id)
            for noble_id in noble_ids
        }
        min_holdings = min(holding_counts.values())
        if rng.random() < 0.88:
            candidates = [
                noble_id for noble_id in noble_ids
                if holding_counts[noble_id] == min_holdings
            ]
            noble_id = rng.choice(candidates)
        else:
            noble_id = rng.choice(noble_ids)
        frontier = [
            coord
            for coord in remaining
            if any(_connected(coord, held) for held, owner in ownership.items() if owner == noble_id)
        ]
        if frontier and rng.random() < 0.78:
            coord = rng.choice(frontier)
        else:
            coord = rng.choice(remaining)
        remaining.remove(coord)
        ownership[coord] = noble_id

    return ownership, king_second


def _build_nobles(rng: random.Random, ownership: dict[str, str]) -> dict[str, NobleProfile]:
    names = [
        "Alden Fen",
        "Brenna Vale",
        "Cassian Holt",
        "Dalia Reed",
        "Eron Kest",
        "Fara Mourn",
        "Galen Rusk",
        "Helena Cale",
        "Iven Ash",
        "Jora Wynn",
    ]
    rng.shuffle(names)
    non_king_ids = sorted({owner for owner in ownership.values() if owner != "king"})
    royal_count = rng.randint(0, 2)
    royal_ids = set(rng.sample(non_king_ids, k=royal_count))
    profiles: dict[str, NobleProfile] = {}

    for index, noble_id in enumerate(non_king_ids):
        holdings = tuple(sorted(coord for coord, owner in ownership.items() if owner == noble_id))
        seat = max(holdings, key=lambda c: _seat_score(c, holdings))
        family_ties: list[str] = []
        if rng.random() < 0.12 and len(royal_ids) < 2:
            family_ties.append("king")
            royal_ids.add(noble_id)
        previous = non_king_ids[:index]
        if previous and rng.random() < 0.30:
            relative = rng.choice(previous)
            family_ties.append(relative)
            if relative in royal_ids and len(royal_ids) < 2:
                royal_ids.add(noble_id)
        is_royal = noble_id in royal_ids
        race = rng.choice(RACES)
        prejudice = tuple(sorted(rng.sample([r for r in RACES if r != race], k=rng.randint(0, 2))))
        preference_pool = [r for r in RACES if r not in prejudice]
        preference = tuple(sorted(rng.sample(preference_pool, k=rng.randint(0, 1))))
        profiles[noble_id] = NobleProfile(
            id=noble_id,
            display_name=names[index],
            race=race,
            is_royal=is_royal,
            holdings=holdings,
            seat=seat,
            traits=_noble_traits(rng, is_royal, len(holdings)),
            prejudice=prejudice,
            preference=preference,
            family_ties=tuple(family_ties),
        )
    return profiles


def _build_regions(rng: random.Random, ownership: dict[str, str]) -> dict[str, RegionProfile]:
    holding_counts = {
        owner: sum(1 for region_owner in ownership.values() if region_owner == owner)
        for owner in set(ownership.values())
    }
    regions: dict[str, RegionProfile] = {}
    for coord in REGIONS:
        owner_id = ownership[coord]
        eligible_undeveloped = owner_id != "king" and coord not in {NORTH_PORT, SOUTH_PORT}
        chance = undeveloped_probability(holding_counts[owner_id]) if eligible_undeveloped else 0.0
        developed = not eligible_undeveloped or rng.random() >= chance
        geography = _geography(coord)
        settlements = _settlements_for(rng, coord, developed, geography)
        race_pops = _race_population(rng, coord, settlements, geography)
        stats, primary = _region_stats(rng, coord, settlements, race_pops, geography, developed)
        regions[coord] = RegionProfile(
            coord=coord,
            owner_id=owner_id,
            developed=developed,
            undeveloped_chance=chance,
            settlements=settlements,
            primary_economy=primary,
            race_pops=race_pops,
            stats=stats,
            geography=geography,
        )
    return regions


def _build_actors(
    rng: random.Random,
    nobles: dict[str, NobleProfile],
    regions: dict[str, RegionProfile],
) -> dict[str, Actor]:
    actors: dict[str, Actor] = {}

    def add(actor: Actor) -> None:
        actors[actor.id] = actor

    king_regions = [r for r in regions.values() if r.owner_id == "king"]
    king_population = sum(r.stats["population"] for r in king_regions)
    king_identity = rng.choice(RACES)
    king_prejudice = _affinity_map(rng.sample([r for r in RACES if r != king_identity], k=rng.randint(0, 1)))
    king_preference = _affinity_map(rng.sample([r for r in RACES if r not in king_prejudice], k=rng.randint(0, 1)))
    add(Actor(
        id="king",
        display_name="Aster Halric",
        title="King",
        location=CAPITAL,
        commander=None,
        traits=Traits(competence=0.78, honesty=0.84, loyalty=0.92, ambition=0.38,
                      fear=0.18, education=0.88),
        identity=king_identity,
        prejudice=king_prejudice,
        preference=king_preference,
        stats={
            "food_stores": 5000.0 + sum(r.stats["food_stores"] * 0.25 for r in king_regions),
            "soldiers": 1300.0,
            "monster_pressure": 4.0,
            "unrest": 10.0,
            "population": king_population,
            "money": 3600.0,
            "lumber": 900.0,
            "herbs": 500.0,
            "ore": 500.0,
            "wares": 700.0,
            "luxury_goods": 380.0,
            "weapons": 850.0,
            "warriors": 95.0,
            "scouts": 18.0,
            "kingsguard": 220.0,
            "noble_distrust": 8.0,
            "forest_tension": 0.0,
            "tax_multiplier": 1.0,
        },
        report_every=999_999,
        observe_every=10,
        decide_every=28,
    ))

    for noble in nobles.values():
        holding_stats = [regions[coord].stats for coord in noble.holdings]
        title = "Royal Noble" if noble.is_royal else "Noble"
        add(Actor(
            id=noble.id,
            display_name=noble.display_name,
            title=title,
            location=noble.seat,
            commander="king",
            traits=noble.traits,
            identity=noble.race,
            prejudice=_affinity_map(noble.prejudice),
            preference=_affinity_map(noble.preference),
            stats={
                "food_stores": 800.0 + sum(s["food_stores"] * 0.10 for s in holding_stats),
                "soldiers": 120.0 + 55.0 * len(noble.holdings) + rng.uniform(0, 160),
                "monster_pressure": max(s["monster_pressure"] for s in holding_stats) * 0.35,
                "unrest": sum(s["unrest"] for s in holding_stats) / len(holding_stats),
                "population": sum(s["population"] for s in holding_stats),
                "money": 520.0 + sum(s["money"] * 0.16 for s in holding_stats),
                "lumber": sum(s["lumber"] * 0.12 for s in holding_stats),
                "herbs": sum(s["herbs"] * 0.12 for s in holding_stats),
                "ore": sum(s["ore"] * 0.12 for s in holding_stats),
                "wares": sum(s["wares"] * 0.12 for s in holding_stats),
                "luxury_goods": sum(s["luxury_goods"] * 0.12 for s in holding_stats),
                "weapons": 160.0 + sum(s["weapons"] * 0.18 for s in holding_stats),
                "warriors": 8.0 + 4.0 * len(noble.holdings) + rng.uniform(0, 22),
                "scouts": sum(s["scouts"] * 0.30 for s in holding_stats) + rng.uniform(0.0, 8.0),
                "kingsguard": 0.0,
                "noble_distrust": rng.uniform(4.0, 18.0) - (3.0 if noble.is_royal else 0.0),
                "forest_tension": max(s["forest_tension"] for s in holding_stats),
                "tax_multiplier": rng.uniform(0.85, 1.25) - (0.08 if noble.is_royal else 0.0),
            },
            report_every=13,
            observe_every=7,
            decide_every=11,
        ))

    for region in regions.values():
        mayor_id = _mayor_id(region.coord)
        mayor_identity = _dominant_race(rng, region.race_pops)
        mayor_prejudice, mayor_preference = _local_affinity_maps(rng, mayor_identity, region)
        add(Actor(
            id=mayor_id,
            display_name=_mayor_name(rng, region.coord, region.developed),
            title="Mayor",
            location=region.coord,
            commander=region.owner_id,
            traits=_mayor_traits(rng, region),
            identity=mayor_identity,
            prejudice=mayor_prejudice,
            preference=mayor_preference,
            stats=dict(region.stats),
            report_every=9,
            observe_every=5,
            decide_every=8,
        ))
        guard_strength = _guard_strength(region)
        if guard_strength > 0:
            guard_identity = _dominant_race(rng, region.race_pops)
            guard_prejudice, guard_preference = _local_affinity_maps(rng, guard_identity, region)
            add(Actor(
                id=_guard_id(region.coord),
                display_name=f"Guard Captain {_surname(rng)}",
                title="Guard Captain",
                location=region.coord,
                commander=mayor_id,
                traits=_guard_traits(rng, region),
                identity=guard_identity,
                prejudice=guard_prejudice,
                preference=guard_preference,
                stats={
                    "food_stores": max(120.0, guard_strength * rng.uniform(1.5, 2.8)),
                    "soldiers": guard_strength,
                    "warriors": max(0.0, guard_strength * rng.uniform(0.03, 0.13)),
                    "scouts": max(0.0, guard_strength * rng.uniform(0.005, 0.030)),
                    "monster_pressure": region.stats["monster_pressure"] * rng.uniform(0.45, 0.90),
                    "unrest": region.stats["unrest"] * rng.uniform(0.20, 0.55),
                    "weapons": guard_strength * rng.uniform(0.75, 1.35),
                    "tax_multiplier": 0.0,
                },
                report_every=7,
                observe_every=4,
                decide_every=6,
            ))
    _ensure_actor_military_splits(rng, actors)
    return actors


def _settlements_for(
    rng: random.Random,
    coord: str,
    developed: bool,
    geography: dict[str, float],
) -> tuple[Settlement, ...]:
    if not developed:
        return ()
    if coord == CAPITAL:
        count = 3
    elif coord in {NORTH_PORT, SOUTH_PORT}:
        count = rng.choice((2, 3))
    else:
        count = rng.choices((1, 2, 3), weights=(3, 5, 2), k=1)[0]

    settlements: list[Settlement] = []
    mining_count = 0
    for idx in range(count):
        size = _settlement_size(rng, coord, geography, idx)
        spec = _specialization(rng, coord, geography, mining_count)
        if spec == "Mining":
            mining_count += 1
        focus = _focus_for(rng, spec, geography)
        defense = _defense_quality(rng, size, spec, geography)
        fill = rng.uniform(0.58, 0.92)
        if coord in {CAPITAL, NORTH_PORT, SOUTH_PORT}:
            fill = rng.uniform(0.72, 0.98)
        population = int(SETTLEMENT_CAPACITY[size] * fill)
        settlements.append(Settlement(
            name=f"{coord}-{idx + 1}",
            size=size,
            specialization=spec,
            focus=focus,
            defense_quality=defense,
            population=population,
        ))
    return tuple(settlements)


def _region_stats(
    rng: random.Random,
    coord: str,
    settlements: tuple[Settlement, ...],
    race_pops: dict[str, int],
    geography: dict[str, float],
    developed: bool,
) -> tuple[dict[str, float], str]:
    population = float(sum(race_pops.values()))
    spec_counts = _spec_counts(settlements)
    focus_counts = _focus_counts(settlements)
    primary = _primary_economy(coord, spec_counts, geography, developed)
    race_bonus = {
        "food": 1.0 + race_pops.get("orc", 0) / max(population, 1.0) * 0.20,
        "forest": 1.0 + race_pops.get("elf", 0) / max(population, 1.0) * 0.24,
        "ore": 1.0 + race_pops.get("dwarf", 0) / max(population, 1.0) * 0.30,
        "craft": 1.0 + race_pops.get("demon", 0) / max(population, 1.0) * 0.16,
        "trade": 1.0 + race_pops.get("human", 0) / max(population, 1.0) * 0.12,
    }

    food_workers = population * (0.07 + 0.17 * spec_counts["Agricultural"]) * geography["agriculture"]
    lumber_workers = population * (0.03 + 0.13 * focus_counts["lumber"]) * geography["forest"]
    herb_workers = population * (0.02 + 0.11 * focus_counts["herbs"]) * geography["forest"]
    ore_workers = population * (0.04 + 0.16 * spec_counts["Mining"]) * geography["mining"]
    craft_workers = population * (0.03 + 0.14 * spec_counts["Production"])
    trade_workers = population * (0.04 + 0.18 * spec_counts["Trade"]) * geography["trade"]

    pollution = max(0.0, spec_counts["Mining"] - 1) * 0.18
    food_stores = (
        350.0
        + food_workers * race_bonus["food"] * rng.uniform(2.6, 4.6)
        - population * 0.12
        - pollution * 900.0
    )
    if primary == "Agricultural":
        food_stores += 500.0
    if not developed:
        food_stores = rng.uniform(80.0, 280.0)

    soldiers = 35.0 + population * rng.uniform(0.015, 0.040)
    soldiers += spec_counts["Military"] * rng.uniform(110.0, 260.0)
    soldiers += sum(s.defense_quality for s in settlements) * 24.0
    if _row(coord) == 1:
        soldiers += 85.0 * geography["border_guard"]

    monster_pressure = rng.uniform(4.0, 20.0)
    monster_pressure += geography["forest"] * rng.uniform(4.0, 16.0)
    monster_pressure += geography["mining"] * rng.uniform(3.0, 14.0)
    monster_pressure += 20.0 if not developed else 0.0
    monster_pressure -= soldiers * 0.018

    unrest = rng.uniform(8.0, 28.0)
    unrest += pollution * 45.0
    unrest += 12.0 if not developed else 0.0
    unrest += max(0.0, population - sum(SETTLEMENT_CAPACITY[s.size] for s in settlements)) * 0.010

    stats = {
        "food_stores": max(0.0, food_stores),
        "soldiers": max(0.0, soldiers),
        "monster_pressure": max(0.0, monster_pressure),
        "unrest": max(0.0, unrest),
        "population": population,
        "money": max(30.0, 120.0 + trade_workers * race_bonus["trade"] * rng.uniform(1.5, 3.0)),
        "lumber": max(0.0, lumber_workers * race_bonus["forest"] * rng.uniform(1.2, 2.5)),
        "herbs": max(0.0, herb_workers * race_bonus["forest"] * rng.uniform(0.8, 1.9)),
        "ore": max(0.0, ore_workers * race_bonus["ore"] * rng.uniform(1.0, 2.4)),
        "wares": max(0.0, craft_workers * race_bonus["craft"] * rng.uniform(0.7, 1.6)),
        "luxury_goods": max(0.0, (trade_workers + craft_workers) * rng.uniform(0.05, 0.22)),
        "weapons": max(20.0, 40.0 + craft_workers * rng.uniform(0.20, 0.60) + ore_workers * 0.10),
        "warriors": max(0.0, soldiers * rng.uniform(0.015, 0.080)),
        "scouts": max(
            0.0,
            spec_counts["Military"] * rng.uniform(2.0, 6.0)
            + geography["forest"] * rng.uniform(0.0, 3.0)
            + geography["border_guard"] * rng.uniform(1.0, 4.0),
        ),
        "kingsguard": 0.0,
        "noble_distrust": 0.0,
        "forest_tension": max(
            0.0,
            geography["forest"] * (lumber_workers + herb_workers) * 0.035
            - race_pops.get("elf", 0) * 0.010,
        ),
        "tax_multiplier": 1.0,
        "food_workers": max(0.0, food_workers),
        "lumber_workers": max(0.0, lumber_workers),
        "herb_workers": max(0.0, herb_workers),
        "ore_workers": max(0.0, ore_workers),
        "craft_workers": max(0.0, craft_workers),
        "trade_workers": max(0.0, trade_workers),
    }
    for race in RACES:
        stats[f"{race.replace('-', '_')}_pops"] = float(race_pops.get(race, 0))
    _split_military_stats(stats, race_pops, rng)
    return stats, primary


def _race_population(
    rng: random.Random,
    coord: str,
    settlements: tuple[Settlement, ...],
    geography: dict[str, float],
) -> dict[str, int]:
    total = sum(s.population for s in settlements)
    if total <= 0:
        return {race: 0 for race in RACES}
    weights = {
        "human": 1.00,
        "elf": 0.42 + 0.85 * geography["forest"],
        "orc": 0.48 + 0.25 * geography["agriculture"],
        "beast-man": 0.42 + 0.30 * geography["border_guard"],
        "dwarf": 0.34 + 0.95 * geography["mining"],
        "demon": 0.25 + 0.35 * geography["trade"],
    }
    if any(s.size == "city" for s in settlements):
        weights["demon"] += 0.28
        weights["human"] += 0.20
    raw = {race: rng.random() * weight for race, weight in weights.items()}
    raw_total = sum(raw.values())
    pops = {race: int(total * raw[race] / raw_total) for race in RACES}
    pops["human"] += total - sum(pops.values())
    return pops


def _geography(coord: str) -> dict[str, float]:
    x, y = _xy(coord)
    dist_c1 = max(abs(x - 2), abs(y - 0))
    dist_c5 = max(abs(x - 2), abs(y - 4))
    forest = max(0.0, 1.25 - x * 0.25)
    mining = max(0.0, 0.45 + x * 0.18)
    agriculture = 0.75 + (0.24 if y == 4 else 0.0) + (0.10 if 1 <= x <= 3 else 0.0)
    trade = 0.30 + max(0.0, 1.20 - dist_c1 * 0.28) + max(0.0, 1.15 - dist_c5 * 0.26)
    border_guard = max(0.0, 1.05 - abs(x - 2) * 0.25) if y == 0 else 0.0
    if coord == CAPITAL:
        trade += 0.40
        agriculture += 0.15
    return {
        "forest": forest,
        "mining": mining,
        "agriculture": agriculture,
        "trade": trade,
        "border_guard": border_guard,
        "coast": 1.0 if y == 4 else 0.0,
    }


def _emit_setup(log: EventLog, setup: KingdomSetup) -> None:
    log.emit(
        0.0,
        "scenario_setup",
        f"Isekai kingdom seed {setup.seed}: King holds {CAPITAL} and "
        f"{setup.king_second_region}; {len(setup.nobles)} non-crown Nobles",
        scenario="isekai_kingdom",
        seed=setup.seed,
        king_second_region=setup.king_second_region,
        noble_count=len(setup.nobles),
    )
    for noble in sorted(setup.nobles.values(), key=lambda n: n.id):
        log.emit(
            0.0,
            "noble_setup",
            f"{noble.display_name} ({'Royal ' if noble.is_royal else ''}Noble, "
            f"{noble.race}) holds {', '.join(noble.holdings)} from {noble.seat}",
            actor=noble.id,
            display_name=noble.display_name,
            race=noble.race,
            is_royal=noble.is_royal,
            holdings=list(noble.holdings),
            seat=noble.seat,
            prejudice=list(noble.prejudice),
            preference=list(noble.preference),
            family_ties=list(noble.family_ties),
        )
    for actor in sorted(setup.actors.values(), key=lambda a: a.id):
        log.emit(
            0.0,
            "actor_identity_setup",
            f"{actor.title} {actor.display_name} identity={actor.identity or 'none'} "
            f"prejudice={sorted(actor.prejudice)} preference={sorted(actor.preference)}",
            actor=actor.id,
            title=actor.title,
            display_name=actor.display_name,
            identity=actor.identity,
            prejudice=dict(actor.prejudice),
            preference=dict(actor.preference),
        )
    for region in sorted(setup.regions.values(), key=lambda r: r.coord):
        settlement_bits = [
            {
                "name": s.name,
                "size": s.size,
                "specialization": s.specialization,
                "focus": s.focus,
                "defense_quality": s.defense_quality,
                "population": s.population,
            }
            for s in region.settlements
        ]
        status = "developed" if region.developed else "undeveloped"
        log.emit(
            0.0,
            "region_setup",
            f"[{region.coord}] {status} {region.primary_economy} region owned by "
            f"{region.owner_id}: {len(region.settlements)} settlements, "
            f"undeveloped chance {region.undeveloped_chance:.2f}",
            location=region.coord,
            owner=region.owner_id,
            developed=region.developed,
            undeveloped_chance=region.undeveloped_chance,
            primary_economy=region.primary_economy,
            race_pops=region.race_pops,
            settlements=settlement_bits,
            geography=region.geography,
        )


def scripted_events(sim: Simulation, setup: KingdomSetup) -> None:
    scripted: list[tuple[float, str, str, float, str]] = []

    for region in setup.regions.values():
        if not region.developed:
            scripted.append((
                45.0 + _coord_index(region.coord) * 3.0,
                _mayor_id(region.coord),
                "monster_pressure",
                24.0,
                "monsters nest in unused land",
            ))
        if _col(region.coord) == "A" and (
            region.stats["lumber_workers"] + region.stats["herb_workers"] > 120.0
        ):
            scripted.append((
                70.0 + _row(region.coord) * 9.0,
                _mayor_id(region.coord),
                "monster_pressure",
                18.0,
                "forest elf warning misread as raids",
            ))
            scripted.append((
                78.0 + _row(region.coord) * 9.0,
                _mayor_id(region.coord),
                "unrest",
                10.0,
                "forest border panic",
            ))
        if _col(region.coord) == "E" and region.stats["ore_workers"] > 160.0:
            scripted.append((
                95.0 + _row(region.coord) * 8.0,
                _mayor_id(region.coord),
                "monster_pressure",
                26.0,
                "mine tunnel breach",
            ))
        if region.stats["ore_workers"] > 260.0 and region.stats["food_workers"] < 150.0:
            scripted.append((
                135.0 + _coord_index(region.coord),
                _mayor_id(region.coord),
                "food_stores",
                -420.0,
                "mining pollution hurts farms",
            ))

    scripted.extend([
        (60.0, _mayor_id(NORTH_PORT), "money", 600.0, "friendly empire caravan season"),
        (86.0, _mayor_id(NORTH_PORT), "soldiers", -90.0, "border guard rotation"),
        (72.0, _mayor_id(SOUTH_PORT), "money", 520.0, "ocean convoy arrives"),
        (125.0, _mayor_id(SOUTH_PORT), "food_stores", -520.0, "coastal granary fire"),
        (150.0, _mayor_id(CAPITAL), "unrest", 18.0, "capital rumor wave"),
    ])

    for when, actor_id, stat, delta, cause in scripted:
        sim.schedule_scripted(when, lambda s, a=actor_id, st=stat, d=delta, c=cause: _bump(s, a, st, d, c))


KINGDOM_STATE_KEY = "isekai_kingdom"
KINGDOM_TURN_INTERVAL = 16.0
DEATH_CHANCE_BY_TITLE = {
    "King": 0.006,
    "Royal Noble": 0.010,
    "Noble": 0.011,
    "Mayor": 0.003,
    "Guard Captain": 0.002,
}


def schedule_kingdom_systems(sim: Simulation, setup: KingdomSetup) -> None:
    _init_kingdom_state(sim, setup)
    sim.schedule_scripted(
        KINGDOM_TURN_INTERVAL,
        lambda s: _kingdom_turn(s, setup, KINGDOM_TURN_INTERVAL),
    )


def _init_kingdom_state(sim: Simulation, setup: KingdomSetup) -> None:
    if KINGDOM_STATE_KEY in sim.scenario_state:
        return
    regions: dict[str, dict] = {}
    for profile in setup.regions.values():
        owner = sim.actors[profile.owner_id]
        exempt_identity = None
        if owner.preference and sim.rng.random() < 0.45:
            exempt_identity = max(owner.preference, key=owner.preference.get)
        settlements = [
            {
                "name": s.name,
                "size": s.size,
                "specialization": s.specialization,
                "focus": s.focus,
                "defense_quality": s.defense_quality,
                "population": float(s.population),
                "pending_specialization": None,
            }
            for s in profile.settlements
        ]
        regions[profile.coord] = {
            "owner_id": profile.owner_id,
            "settlements": settlements,
            "race_pops": dict(profile.race_pops),
            "hidden_monsters": profile.stats["monster_pressure"] * sim.rng.uniform(0.35, 0.90),
            "recent_attacks": 0.0,
            "forest_tension": profile.stats["forest_tension"],
            "tax_exempt_identity": exempt_identity,
            "last_tax_multiplier": profile.stats.get("tax_multiplier", 1.0),
            "last_specialization_time": -999.0,
            "last_upgrade_time": -999.0,
            "last_aid_time": -999.0,
            "last_tax_forgiven_time": -999.0,
            "last_army_aid_time": -999.0,
        }
        mayor = sim.actors.get(_mayor_id(profile.coord))
        if mayor is not None:
            mayor.stats["tax_multiplier"] = profile.stats.get("tax_multiplier", 1.0)
        sim.event_log.emit(
            0.0,
            "tax_policy",
            f"[{profile.coord}] starting tax multiplier "
            f"{profile.stats.get('tax_multiplier', 1.0):.2f}"
            + (f", exemption leaning toward {exempt_identity}" if exempt_identity else ""),
            location=profile.coord,
            owner=profile.owner_id,
            tax_multiplier=profile.stats.get("tax_multiplier", 1.0),
            exempt_identity=exempt_identity,
        )
    for actor in sorted(setup.actors.values(), key=lambda a: a.id):
        chance = DEATH_CHANCE_BY_TITLE.get(actor.title, 0.0)
        if chance <= 0.0:
            continue
        sim.event_log.emit(
            0.0,
            "mortality_setup",
            f"{actor.title} {actor.display_name} has per-turn death risk {chance:.3f}",
            actor=actor.id,
            title=actor.title,
            death_chance=chance,
        )
    for noble in setup.nobles.values():
        if noble.family_ties:
            sim.event_log.emit(
                0.0,
                "family_tie_setup",
                f"{noble.display_name} has family ties to {', '.join(noble.family_ties)}",
                actor=noble.id,
                family_ties=list(noble.family_ties),
                is_royal=noble.is_royal,
            )
    sim.event_log.emit(
        0.0,
        "kingsguard_setup",
        f"Kingsguard starts at {sim.actors['king'].stats.get('kingsguard', 0.0):.0f}",
        actor="king",
        kingsguard=sim.actors["king"].stats.get("kingsguard", 0.0),
    )
    sim.scenario_state[KINGDOM_STATE_KEY] = {
        "regions": regions,
        "revoked_regions": {},
        "dead_occupants": [],
    }


def _kingdom_turn(sim: Simulation, setup: KingdomSetup, interval: float) -> None:
    state = sim.scenario_state[KINGDOM_STATE_KEY]
    for coord in REGIONS:
        region_state = state["regions"][coord]
        mayor = sim.actors.get(_mayor_id(coord))
        if mayor is None:
            continue
        profile = setup.regions[coord]
        _sync_region_pops(mayor, region_state)
        _update_tax_policy(sim, setup, coord, region_state, mayor)
        _maybe_found_or_refocus_settlement(sim, profile, region_state, mayor)
        _settlement_input_output(sim, profile, region_state, mayor)
        _settlement_upgrade_step(sim, profile, region_state, mayor)
        _migration_step(sim, setup, coord, region_state, mayor)
        _trade_step(sim, setup, coord, region_state, mayor)
        _military_training_step(sim, coord, mayor)
        _monster_step(sim, setup, coord, region_state, mayor)
        _forest_elf_step(sim, setup, coord, region_state, mayor)
        region_state["recent_attacks"] = max(0.0, region_state["recent_attacks"] - 0.25)
    _king_military_step(sim)
    _king_aid_step(sim)
    _revocation_step(sim, setup)
    _mortality_step(sim, setup)
    sim.schedule_scripted(
        sim.now + interval,
        lambda s: _kingdom_turn(s, setup, interval),
    )


def _sync_region_pops(mayor: Actor, region_state: dict) -> None:
    total = 0.0
    for race in RACES:
        stat = f"{race.replace('-', '_')}_pops"
        value = max(0.0, mayor.stats.get(stat, float(region_state["race_pops"].get(race, 0))))
        region_state["race_pops"][race] = int(value)
        mayor.stats[stat] = value
        total += value
    mayor.stats["population"] = total


def _region_capacity(region_state: dict) -> float:
    return sum(SETTLEMENT_CAPACITY[s["size"]] for s in region_state["settlements"])


def _neighbor_coords(coord: str) -> list[str]:
    x, y = _xy(coord)
    out = []
    for other in REGIONS:
        if other == coord:
            continue
        ox, oy = _xy(other)
        if max(abs(x - ox), abs(y - oy)) == 1:
            out.append(other)
    return out


def _update_tax_policy(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    region_state: dict,
    mayor: Actor,
) -> None:
    owner = sim.actors.get(region_state["owner_id"])
    if owner is None:
        return
    population = max(1.0, mayor.stats.get("population", 0.0))
    food_pressure = 1.0 if mayor.stats.get("food_stores", 0.0) < population * 0.30 else 0.0
    threat_pressure = min(1.0, mayor.stats.get("monster_pressure", 0.0) / 90.0)
    multiplier = owner.stats.get("tax_multiplier", 1.0)
    if food_pressure or threat_pressure > 0.5:
        multiplier -= 0.10 * owner.traits.honesty
        multiplier += 0.08 * owner.traits.ambition
    if mayor.identity and mayor.identity in owner.preference:
        multiplier -= 0.08 * owner.preference[mayor.identity]
        region_state["tax_exempt_identity"] = mayor.identity
    if mayor.identity and mayor.identity in owner.prejudice:
        multiplier += 0.10 * owner.prejudice[mayor.identity]
    multiplier = max(0.35, min(1.65, multiplier))
    if abs(multiplier - region_state["last_tax_multiplier"]) >= 0.08:
        sim.event_log.emit(
            sim.now,
            "tax_policy",
            f"[{coord}] {owner.display_name} sets tax multiplier "
            f"{region_state['last_tax_multiplier']:.2f} -> {multiplier:.2f}",
            actor=owner.id,
            location=coord,
            previous=region_state["last_tax_multiplier"],
            tax_multiplier=multiplier,
            exempt_identity=region_state.get("tax_exempt_identity"),
        )
    mayor.stats["tax_multiplier"] = multiplier
    region_state["last_tax_multiplier"] = multiplier


def _maybe_found_or_refocus_settlement(
    sim: Simulation,
    profile: RegionProfile,
    region_state: dict,
    mayor: Actor,
) -> None:
    settlements = region_state["settlements"]
    if not settlements and mayor.stats.get("money", 0.0) >= 80.0 and sim.rng.random() < 0.28:
        mayor.stats["money"] -= 80.0
        settlement = {
            "name": f"{profile.coord}-{len(settlements) + 1}",
            "size": "village",
            "specialization": None,
            "focus": None,
            "defense_quality": 0.05,
            "population": 0.0,
            "pending_specialization": None,
        }
        settlements.append(settlement)
        sim.event_log.emit(
            sim.now,
            "settlement_founded",
            f"[{profile.coord}] a new empty village is founded",
            actor=mayor.id,
            location=profile.coord,
            settlement=settlement["name"],
        )
        return

    if not settlements or sim.now - region_state["last_specialization_time"] < 48.0:
        return
    population = max(1.0, mayor.stats.get("population", 0.0))
    needs_food = mayor.stats.get("food_stores", 0.0) < population * 0.35
    needs_wares = mayor.stats.get("wares", 0.0) < population * 0.05
    wants_trade = profile.coord in {NORTH_PORT, SOUTH_PORT} and mayor.stats.get("money", 0.0) < 500.0
    target_spec: str | None = None
    target_focus: str | None = None
    if needs_food:
        target_spec, target_focus = "Agricultural", "food"
    elif needs_wares:
        target_spec, target_focus = "Production", "wares"
    elif wants_trade:
        target_spec, target_focus = "Trade", "money"
    if target_spec is None:
        return
    if target_spec == "Agricultural" and sum(1 for s in settlements if s["specialization"] == "Mining") >= 2:
        return
    settlement = min(settlements, key=lambda s: s["population"])
    before = settlement["specialization"]
    if before is None:
        settlement["specialization"] = target_spec
        settlement["focus"] = target_focus
        settlement["pending_specialization"] = None
    elif before != target_spec:
        settlement["specialization"] = None
        settlement["focus"] = None
        settlement["pending_specialization"] = (target_spec, target_focus)
    else:
        settlement["focus"] = target_focus
    region_state["last_specialization_time"] = sim.now
    sim.event_log.emit(
        sim.now,
        "settlement_refocus",
        f"[{profile.coord}] {settlement['name']} shifts {before or 'None'} -> "
        f"{settlement['specialization'] or 'None'}"
        + (f" toward {target_spec}" if settlement["pending_specialization"] else ""),
        actor=mayor.id,
        location=profile.coord,
        settlement=settlement["name"],
        before=before,
        after=settlement["specialization"],
        pending=settlement["pending_specialization"],
    )


def _settlement_input_output(
    sim: Simulation,
    profile: RegionProfile,
    region_state: dict,
    mayor: Actor,
) -> None:
    for settlement in region_state["settlements"]:
        if settlement["pending_specialization"] and settlement["specialization"] is None:
            target_spec, target_focus = settlement["pending_specialization"]
            if sim.rng.random() < 0.35:
                settlement["specialization"] = target_spec
                settlement["focus"] = target_focus
                settlement["pending_specialization"] = None
                sim.event_log.emit(
                    sim.now,
                    "settlement_refocus",
                    f"[{profile.coord}] {settlement['name']} completes refocus to {target_spec}",
                    actor=mayor.id,
                    location=profile.coord,
                    settlement=settlement["name"],
                    after=target_spec,
                )
        spec = settlement["specialization"]
        focus = settlement["focus"]
        population = settlement["population"]
        if spec == "Production" and focus in {"wares", "weapons", "luxury goods"}:
            lumber = mayor.stats.get("lumber", 0.0)
            ore = mayor.stats.get("ore", 0.0)
            inputs = min(lumber, ore, max(1.0, population * 0.018))
            if inputs <= 0:
                mayor.stats["unrest"] = mayor.stats.get("unrest", 0.0) + 1.5
                continue
            mayor.stats["lumber"] = lumber - inputs
            mayor.stats["ore"] = ore - inputs
            output_stat = "luxury_goods" if focus == "luxury goods" else focus
            produced = inputs * (1.2 + mayor.traits.competence)
            before = mayor.stats.get(output_stat, 0.0)
            mayor.stats[output_stat] = before + produced
            sim.event_log.emit(
                sim.now,
                "craft_production",
                f"[{profile.coord}] {settlement['name']} turns lumber+ore into "
                f"{produced:.0f} {output_stat}",
                actor=mayor.id,
                location=profile.coord,
                settlement=settlement["name"],
                stat=output_stat,
                amount=produced,
            )
    population = mayor.stats.get("population", 0.0)
    for stat, rate in (("herbs", 0.004), ("wares", 0.003)):
        before = mayor.stats.get(stat, 0.0)
        consumed = min(before, population * rate)
        if consumed > 0:
            mayor.stats[stat] = before - consumed
            sim.event_log.emit(
                sim.now,
                "settlement_consumption",
                f"[{profile.coord}] settlements consume {consumed:.0f} {stat}",
                actor=mayor.id,
                location=profile.coord,
                stat=stat,
                amount=consumed,
            )
        elif population > 0:
            mayor.stats["unrest"] = mayor.stats.get("unrest", 0.0) + 1.0


def _settlement_upgrade_step(
    sim: Simulation,
    profile: RegionProfile,
    region_state: dict,
    mayor: Actor,
) -> None:
    if sim.now - region_state["last_upgrade_time"] < 80.0:
        return
    candidates = []
    for settlement in region_state["settlements"]:
        next_size = SETTLEMENT_UPGRADES.get(settlement["size"])
        if next_size is None:
            continue
        capacity = SETTLEMENT_CAPACITY[settlement["size"]]
        pressure = settlement["population"] / max(1.0, capacity)
        if pressure < 0.86:
            continue
        costs = SETTLEMENT_UPGRADE_COSTS[next_size]
        if any(mayor.stats.get(stat, 0.0) < amount for stat, amount in costs.items()):
            continue
        candidates.append((pressure, settlement, next_size, costs))
    if not candidates:
        return
    pressure, settlement, next_size, costs = max(candidates, key=lambda item: item[0])
    chance = min(0.42, 0.10 + (pressure - 0.86) * 0.55 + mayor.traits.ambition * 0.08)
    if sim.rng.random() >= chance:
        return
    for stat, amount in costs.items():
        mayor.stats[stat] -= amount
    before_size = settlement["size"]
    before_defense = settlement["defense_quality"]
    settlement["size"] = next_size
    settlement["defense_quality"] = _upgrade_defense_quality(
        sim,
        profile,
        region_state,
        mayor,
        settlement,
        before_defense,
    )
    region_state["last_upgrade_time"] = sim.now
    sim.event_log.emit(
        sim.now,
        "settlement_upgraded",
        f"[{profile.coord}] {settlement['name']} upgrades {before_size} -> {next_size} "
        f"with defense {before_defense:.2f} -> {settlement['defense_quality']:.2f}",
        actor=mayor.id,
        location=profile.coord,
        settlement=settlement["name"],
        before_size=before_size,
        after_size=next_size,
        before_defense=before_defense,
        after_defense=settlement["defense_quality"],
    )


def _upgrade_defense_quality(
    sim: Simulation,
    profile: RegionProfile,
    region_state: dict,
    mayor: Actor,
    settlement: dict,
    previous: float,
) -> float:
    production_count = sum(1 for s in region_state["settlements"] if s["specialization"] == "Production")
    dwarf_share = mayor.stats.get("dwarf_pops", 0.0) / max(1.0, mayor.stats.get("population", 0.0))
    resource_bonus = min(
        0.22,
        (
            mayor.stats.get("lumber", 0.0) / 1800.0
            + mayor.stats.get("ore", 0.0) / 1400.0
            + mayor.stats.get("wares", 0.0) / 1100.0
            + mayor.stats.get("money", 0.0) / 3000.0
        ),
    )
    builder_bonus = dwarf_share * 0.20 + production_count * 0.035
    if settlement["specialization"] == "Production":
        builder_bonus += 0.05
    competence_bonus = mayor.traits.competence * 0.10
    geography_bonus = profile.geography["mining"] * 0.025 + profile.geography["trade"] * 0.015
    roll = sim.rng.uniform(0.02, 0.12)
    return min(1.0, max(previous, previous + roll + resource_bonus + builder_bonus + competence_bonus + geography_bonus))


def _migration_step(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    region_state: dict,
    mayor: Actor,
) -> None:
    capacity = _region_capacity(region_state)
    population = mayor.stats.get("population", 0.0)
    free_capacity = max(0.0, capacity - population)
    empty_pull = any(s["population"] <= 0 for s in region_state["settlements"])
    if empty_pull and free_capacity > 80.0 and sim.rng.random() < 0.40:
        race = mayor.identity or "human"
        amount = min(free_capacity, sim.rng.uniform(35.0, 120.0))
        _add_race_pops(mayor, region_state, race, amount)
        region_state["settlements"][0]["population"] += amount
        sim.event_log.emit(
            sim.now,
            "migration",
            f"[{coord}] {amount:.0f} {race} migrants fill empty settlement space",
            actor=mayor.id,
            location=coord,
            race=race,
            amount=amount,
            direction="in",
            reason="empty_settlement_pull",
        )
        return
    push = 0.0
    if capacity > 0 and population > capacity:
        push += (population - capacity) / capacity
    if mayor.stats.get("food_stores", 0.0) < population * 0.25:
        push += 0.45
    if mayor.stats.get("monster_pressure", 0.0) > 45.0:
        push += 0.35
    if mayor.stats.get("tax_multiplier", 1.0) > 1.20:
        push += 0.25
    if push <= 0.45 or population <= 0:
        return
    targets = []
    for neighbor in _neighbor_coords(coord):
        neighbor_state = sim.scenario_state[KINGDOM_STATE_KEY]["regions"][neighbor]
        neighbor_mayor = sim.actors.get(_mayor_id(neighbor))
        if neighbor_mayor is None:
            continue
        n_capacity = _region_capacity(neighbor_state)
        n_free = n_capacity - neighbor_mayor.stats.get("population", 0.0)
        if n_free <= 0:
            continue
        pull = n_free / max(n_capacity, 1.0)
        pull += setup.regions[neighbor].geography["trade"] * 0.10
        pull -= neighbor_mayor.stats.get("monster_pressure", 0.0) / 160.0
        pull -= max(0.0, neighbor_mayor.stats.get("tax_multiplier", 1.0) - 1.0) * 0.20
        targets.append((pull, neighbor, neighbor_state, neighbor_mayor, n_free))
    if not targets:
        mayor.stats["unrest"] = mayor.stats.get("unrest", 0.0) + 2.0
        return
    pull, target_coord, target_state, target_mayor, n_free = max(targets, key=lambda item: item[0])
    if pull <= 0:
        return
    race = _migration_race(mayor, region_state)
    amount = min(population * 0.035 * (1.0 + push), n_free, mayor.stats.get(f"{race.replace('-', '_')}_pops", 0.0))
    if amount <= 1:
        return
    _add_race_pops(mayor, region_state, race, -amount)
    _add_race_pops(target_mayor, target_state, race, amount)
    _assign_migrants_to_settlement(target_state, amount)
    sim.event_log.emit(
        sim.now,
        "migration",
        f"{amount:.0f} {race} migrants leave {coord} for {target_coord}",
        actor=mayor.id,
        location=coord,
        target_location=target_coord,
        race=race,
        amount=amount,
        direction="out",
        reason="push_pull",
    )


def _migration_race(mayor: Actor, region_state: dict) -> str:
    candidates = []
    for race in RACES:
        pops = region_state["race_pops"].get(race, 0)
        pressure = pops
        pressure *= 1.0 + mayor.prejudice.get(race, 0.0)
        pressure *= 1.0 - min(0.8, mayor.preference.get(race, 0.0))
        candidates.append((pressure, race))
    return max(candidates)[1]


def _add_race_pops(actor: Actor, region_state: dict, race: str, amount: float) -> None:
    key = f"{race.replace('-', '_')}_pops"
    actor.stats[key] = max(0.0, actor.stats.get(key, 0.0) + amount)
    region_state["race_pops"][race] = int(max(0.0, region_state["race_pops"].get(race, 0) + amount))
    actor.stats["population"] = max(0.0, actor.stats.get("population", 0.0) + amount)


def _assign_migrants_to_settlement(region_state: dict, amount: float) -> None:
    for settlement in region_state["settlements"]:
        free = SETTLEMENT_CAPACITY[settlement["size"]] - settlement["population"]
        if free <= 0:
            continue
        take = min(free, amount)
        settlement["population"] += take
        amount -= take
        if amount <= 0:
            return


def _trade_step(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    region_state: dict,
    mayor: Actor,
) -> None:
    profile = setup.regions[coord]
    trade_settlements = [s for s in region_state["settlements"] if s["specialization"] == "Trade"]
    if coord in {NORTH_PORT, SOUTH_PORT} or trade_settlements:
        external = profile.geography["trade"] * (1.0 + 0.35 * len(trade_settlements))
        money = external * sim.rng.uniform(18.0, 42.0)
        luxury = external * sim.rng.uniform(2.0, 8.0)
        mayor.stats["money"] = mayor.stats.get("money", 0.0) + money
        mayor.stats["luxury_goods"] = mayor.stats.get("luxury_goods", 0.0) + luxury
        sim.event_log.emit(
            sim.now,
            "trade",
            f"[{coord}] trade brings {money:.0f} money and {luxury:.0f} luxury goods",
            actor=mayor.id,
            location=coord,
            money=money,
            luxury_goods=luxury,
            external=coord in {NORTH_PORT, SOUTH_PORT},
        )
    for resource in ("food_stores", "herbs", "wares"):
        population = max(1.0, mayor.stats.get("population", 0.0))
        if mayor.stats.get(resource, 0.0) > population * 0.12:
            continue
        sellers = []
        for neighbor in _neighbor_coords(coord):
            other = sim.actors.get(_mayor_id(neighbor))
            if other is None:
                continue
            surplus = other.stats.get(resource, 0.0) - other.stats.get("population", 0.0) * 0.25
            if surplus > 30.0:
                sellers.append((surplus, neighbor, other))
        if not sellers or mayor.stats.get("money", 0.0) <= 0:
            continue
        surplus, seller_coord, seller = max(sellers, key=lambda item: item[0])
        amount = min(surplus * 0.25, mayor.stats["money"] * 0.8, 160.0)
        price = amount * 0.7
        seller.stats[resource] -= amount
        mayor.stats[resource] = mayor.stats.get(resource, 0.0) + amount
        mayor.stats["money"] -= price
        seller.stats["money"] = seller.stats.get("money", 0.0) + price
        sim.event_log.emit(
            sim.now,
            "trade",
            f"{coord} buys {amount:.0f} {resource} from {seller_coord}",
            actor=mayor.id,
            location=coord,
            seller=seller.id,
            seller_location=seller_coord,
            stat=resource,
            amount=amount,
            money=price,
        )


def _military_training_step(sim: Simulation, coord: str, mayor: Actor) -> None:
    threat = mayor.stats.get("monster_pressure", 0.0)
    if threat < 25.0 and mayor.stats.get("soldiers", 0.0) > 160.0:
        return
    weapons = mayor.stats.get("weapons", 0.0)
    if weapons <= 5.0:
        return
    race = max(RACES, key=lambda r: mayor.stats.get(f"{r.replace('-', '_')}_pops", 0.0))
    pop_key = f"{race.replace('-', '_')}_pops"
    train = min(weapons * 0.18, mayor.stats.get(pop_key, 0.0) * 0.015, 35.0)
    if train <= 1.0:
        return
    soldier_key = f"{race.replace('-', '_')}_soldiers"
    mayor.stats["weapons"] -= train
    mayor.stats[pop_key] -= train
    mayor.stats["population"] = max(0.0, mayor.stats.get("population", 0.0) - train)
    mayor.stats["soldiers"] = mayor.stats.get("soldiers", 0.0) + train
    mayor.stats[soldier_key] = mayor.stats.get(soldier_key, 0.0) + train
    sim.event_log.emit(
        sim.now,
        "soldier_training",
        f"[{coord}] trains {train:.0f} {race} soldiers",
        actor=mayor.id,
        location=coord,
        race=race,
        amount=train,
    )
    emergence = mayor.stats.get(soldier_key, 0.0) * 0.003 * sim.rng.random()
    if emergence > 0.5:
        warrior_key = f"{race.replace('-', '_')}_warriors"
        mayor.stats["warriors"] = mayor.stats.get("warriors", 0.0) + emergence
        mayor.stats[warrior_key] = mayor.stats.get(warrior_key, 0.0) + emergence
        sim.event_log.emit(
            sim.now,
            "warrior_emergence",
            f"[{coord}] {emergence:.1f} {race} soldiers become warriors",
            actor=mayor.id,
            location=coord,
            race=race,
            amount=emergence,
        )


def _monster_step(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    region_state: dict,
    mayor: Actor,
) -> None:
    profile = setup.regions[coord]
    hidden = region_state["hidden_monsters"]
    hidden += 1.2 + (5.0 if not region_state["settlements"] else 0.0)
    hidden += profile.geography["forest"] * 0.9 + profile.geography["mining"] * 0.7
    region_state["hidden_monsters"] = hidden
    guard = sim.actors.get(_guard_id(coord))
    scout_power = mayor.stats.get("scouts", 0.0)
    if guard is not None:
        scout_power += guard.stats.get("scouts", 0.0) * 0.45 + guard.stats.get("soldiers", 0.0) * 0.003
    reveal = min(region_state["hidden_monsters"], scout_power * sim.rng.uniform(0.5, 1.4))
    if reveal > 1.0:
        region_state["hidden_monsters"] -= reveal
        before = mayor.stats.get("monster_pressure", 0.0)
        mayor.stats["monster_pressure"] = before + reveal
        sim.event_log.emit(
            sim.now,
            "monster_detected",
            f"[{coord}] scouts detect {reveal:.0f} monster pressure",
            actor=mayor.id,
            location=coord,
            amount=reveal,
            scouts=scout_power,
            before=before,
            after=mayor.stats["monster_pressure"],
        )
    if region_state["hidden_monsters"] > 35.0 and sim.rng.random() < 0.20:
        target = sim.rng.choice(_neighbor_coords(coord))
        moved = region_state["hidden_monsters"] * 0.25
        region_state["hidden_monsters"] -= moved
        sim.scenario_state[KINGDOM_STATE_KEY]["regions"][target]["hidden_monsters"] += moved
        sim.event_log.emit(
            sim.now,
            "monster_moved",
            f"monsters drift from {coord} toward {target}",
            location=coord,
            target_location=target,
            amount=moved,
        )
    visible = mayor.stats.get("monster_pressure", 0.0)
    if visible > 65.0 or region_state["hidden_monsters"] > 80.0:
        attack = min(visible + region_state["hidden_monsters"] * 0.4, sim.rng.uniform(30.0, 90.0))
        region_state["hidden_monsters"] = max(0.0, region_state["hidden_monsters"] - attack * 0.45)
        mayor.stats["monster_pressure"] = max(0.0, visible - attack * 0.55)
        pop_loss = min(mayor.stats.get("population", 0.0) * 0.04, attack * 1.6)
        food_loss = min(mayor.stats.get("food_stores", 0.0), attack * 4.0)
        soldier_loss = min(mayor.stats.get("soldiers", 0.0), attack * 0.55)
        mayor.stats["population"] = max(0.0, mayor.stats.get("population", 0.0) - pop_loss)
        mayor.stats["food_stores"] = max(0.0, mayor.stats.get("food_stores", 0.0) - food_loss)
        mayor.stats["soldiers"] = max(0.0, mayor.stats.get("soldiers", 0.0) - soldier_loss)
        mayor.stats["unrest"] = mayor.stats.get("unrest", 0.0) + attack * 0.25
        region_state["recent_attacks"] += 1.0
        sim.event_log.emit(
            sim.now,
            "monster_attack",
            f"[{coord}] monsters attack: pop -{pop_loss:.0f}, food -{food_loss:.0f}, "
            f"soldiers -{soldier_loss:.0f}",
            actor=mayor.id,
            location=coord,
            amount=attack,
            population_loss=pop_loss,
            food_loss=food_loss,
            soldier_loss=soldier_loss,
        )


def _forest_elf_step(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    region_state: dict,
    mayor: Actor,
) -> None:
    if _col(coord) != "A":
        return
    owner = sim.actors.get(region_state["owner_id"])
    elf_factor = mayor.stats.get("elf_pops", 0.0) / max(1.0, mayor.stats.get("population", 0.0))
    exploitation = (mayor.stats.get("lumber_workers", 0.0) + mayor.stats.get("herb_workers", 0.0)) * 0.015
    tension = region_state["forest_tension"] + exploitation - 1.8 * elf_factor
    if owner is not None:
        tension += owner.prejudice.get("elf", 0.0) * 10.0
        tension += owner.traits.ambition * 1.1
    tension = max(0.0, tension)
    region_state["forest_tension"] = tension
    mayor.stats["forest_tension"] = tension
    if tension < 55.0 or sim.rng.random() > 0.35:
        return
    lumber_loss = min(mayor.stats.get("lumber", 0.0), tension * 1.8)
    herb_loss = min(mayor.stats.get("herbs", 0.0), tension * 0.9)
    mayor.stats["lumber"] -= lumber_loss
    mayor.stats["herbs"] -= herb_loss
    mayor.stats["unrest"] = mayor.stats.get("unrest", 0.0) + 8.0
    region_state["forest_tension"] *= 0.55
    sim.event_log.emit(
        sim.now,
        "forest_elf_incident",
        f"[{coord}] forest elves disrupt extraction: lumber -{lumber_loss:.0f}, "
        f"herbs -{herb_loss:.0f}",
        actor=mayor.id,
        location=coord,
        lumber_loss=lumber_loss,
        herb_loss=herb_loss,
        forest_tension=tension,
        owner=owner.id if owner is not None else None,
    )
    if owner is None:
        return
    misread_chance = owner.prejudice.get("elf", 0.0) * 0.9 + owner.traits.ambition * 0.18
    if sim.rng.random() >= min(0.72, misread_chance):
        return
    false_pressure = tension * sim.rng.uniform(0.18, 0.42)
    mayor.stats["monster_pressure"] = mayor.stats.get("monster_pressure", 0.0) + false_pressure
    sim.event_log.emit(
        sim.now,
        "forest_elf_misreported",
        f"[{coord}] {owner.display_name} frames forest-elf warnings as monster activity",
        actor=owner.id,
        location=coord,
        mayor=mayor.id,
        false_monster_pressure=false_pressure,
        owner_prejudice=owner.prejudice.get("elf", 0.0),
    )


def _king_military_step(sim: Simulation) -> None:
    king = sim.actors.get("king")
    if king is None:
        return
    if king.stats.get("weapons", 0.0) > 20.0 and king.stats.get("soldiers", 0.0) > 50.0:
        train = min(king.stats["weapons"] * 0.04, king.stats["soldiers"] * 0.015, 12.0)
        if train > 0:
            king.stats["weapons"] -= train
            king.stats["soldiers"] -= train
            king.stats["kingsguard"] = king.stats.get("kingsguard", 0.0) + train
            sim.event_log.emit(
                sim.now,
                "kingsguard_training",
                f"[{king.location}] {train:.0f} soldiers join the Kingsguard",
                actor=king.id,
                amount=train,
            )
    for actor in sim.actors.values():
        if actor.title != "Royal Noble":
            continue
        if actor.stats.get("monster_pressure", 0.0) > 45.0 and king.stats.get("kingsguard", 0.0) > 0:
            aid = min(king.stats["kingsguard"] * 0.06, 18.0)
            king.stats["kingsguard"] -= aid
            actor.stats["soldiers"] = actor.stats.get("soldiers", 0.0) + aid
            actor.stats["noble_distrust"] = max(0.0, actor.stats.get("noble_distrust", 0.0) - 2.0)
            sim.event_log.emit(
                sim.now,
                "kingsguard_aid",
                f"Kingsguard lends {aid:.0f} soldiers to Royal Noble {actor.display_name}",
                actor=king.id,
                recipient=actor.id,
                amount=aid,
            )
def _king_aid_step(sim: Simulation) -> None:
    king = sim.actors.get("king")
    if king is None:
        return
    state = sim.scenario_state[KINGDOM_STATE_KEY]
    for coord, region_state in state["regions"].items():
        mayor = sim.actors.get(_mayor_id(coord))
        if mayor is None:
            continue
        owner = sim.actors.get(region_state["owner_id"])
        if (
            owner is not None
            and owner.id != "king"
            and mayor.stats.get("monster_pressure", 0.0) > 48.0
            and king.stats.get("soldiers", 0.0) > 260.0
            and sim.now - region_state["last_army_aid_time"] >= 64.0
        ):
            amount = min(king.stats["soldiers"] * 0.035, 38.0)
            king.stats["soldiers"] -= amount
            owner.stats["soldiers"] = owner.stats.get("soldiers", 0.0) + amount
            owner.stats["noble_distrust"] = max(0.0, owner.stats.get("noble_distrust", 0.0) - 1.5)
            region_state["last_army_aid_time"] = sim.now
            sim.event_log.emit(
                sim.now,
                "national_army_lent",
                f"[{coord}] King lends {amount:.0f} standing soldiers to {owner.display_name}",
                actor=king.id,
                recipient=owner.id,
                location=coord,
                amount=amount,
            )
        population = max(1.0, mayor.stats.get("population", 0.0))
        if sim.now - region_state["last_aid_time"] >= 48.0:
            for stat, reserve_factor, amount_factor in (
                ("food_stores", 0.20, 0.14),
                ("herbs", 0.014, 0.024),
                ("wares", 0.020, 0.026),
            ):
                if mayor.stats.get(stat, 0.0) >= population * reserve_factor:
                    continue
                available = king.stats.get(stat, 0.0)
                if available <= population * amount_factor:
                    continue
                amount = min(available * 0.035, population * amount_factor, 220.0)
                if amount <= 1.0:
                    continue
                king.stats[stat] -= amount
                mayor.stats[stat] = mayor.stats.get(stat, 0.0) + amount
                if owner is not None:
                    owner.stats["noble_distrust"] = max(
                        0.0,
                        owner.stats.get("noble_distrust", 0.0) - 0.8,
                    )
                region_state["last_aid_time"] = sim.now
                sim.event_log.emit(
                    sim.now,
                    "crown_aid",
                    f"[{coord}] crown sends {amount:.0f} {stat}",
                    actor=king.id,
                    recipient=mayor.id,
                    location=coord,
                    stat=stat,
                    amount=amount,
                )
                break
        if sim.now - region_state["last_tax_forgiven_time"] < 64.0:
            continue
        shortage = (
            mayor.stats.get("food_stores", 0.0) < population * 0.18
            or mayor.stats.get("wares", 0.0) < population * 0.016
        )
        if (
            not shortage
            or mayor.stats.get("tax_multiplier", 1.0) <= 0.78
            or sim.rng.random() > 0.45 + king.traits.honesty * 0.25
        ):
            continue
        old_tax = mayor.stats["tax_multiplier"]
        new_tax = max(0.45, old_tax - 0.18)
        mayor.stats["tax_multiplier"] = new_tax
        region_state["last_tax_multiplier"] = new_tax
        region_state["last_tax_forgiven_time"] = sim.now
        sim.event_log.emit(
            sim.now,
            "tax_forgiven",
            f"[{coord}] King forgives arrears and lowers local tax {old_tax:.2f} -> {new_tax:.2f}",
            actor=king.id,
            recipient=mayor.id,
            location=coord,
            previous=old_tax,
            tax_multiplier=new_tax,
        )


def _revocation_step(sim: Simulation, setup: KingdomSetup) -> None:
    state = sim.scenario_state[KINGDOM_STATE_KEY]
    revoked_regions: dict[str, dict] = state["revoked_regions"]
    _reassign_revoked_regions(sim, setup, revoked_regions)
    if sim.now < 80.0:
        return
    candidates = []
    king = sim.actors["king"]
    for actor in sim.actors.values():
        if actor.id == "king" or actor.title not in {"Noble", "Royal Noble"} or actor.vacant:
            continue
        held = [
            coord for coord, region_state in state["regions"].items()
            if region_state["owner_id"] == actor.id
        ]
        if len(held) <= 1:
            continue
        worst_coord = max(
            held,
            key=lambda c: (
                sim.actors[_mayor_id(c)].stats.get("monster_pressure", 0.0)
                + sim.actors[_mayor_id(c)].stats.get("unrest", 0.0)
                - sim.actors[_mayor_id(c)].stats.get("food_stores", 0.0) / 250.0
                + state["regions"][c].get("recent_attacks", 0.0) * 18.0
            ),
        )
        mayor = sim.actors[_mayor_id(worst_coord)]
        stress = (
            mayor.stats.get("monster_pressure", 0.0)
            + mayor.stats.get("unrest", 0.0)
            + state["regions"][worst_coord].get("recent_attacks", 0.0) * 22.0
        )
        shortage = mayor.stats.get("food_stores", 0.0) < mayor.stats.get("population", 0.0) * 0.22
        political = actor.traits.ambition * 18.0 + (1.0 - actor.traits.loyalty) * 20.0
        review_pressure = king.strikes.get(actor.id, 0) * 18.0
        score = stress + political + review_pressure + (16.0 if shortage else 0.0)
        if actor.title == "Royal Noble":
            score -= 14.0
        candidates.append((score, actor, worst_coord))
    if not candidates:
        return
    score, noble, coord = max(candidates, key=lambda item: item[0])
    chance = min(0.45, max(0.0, (score - 76.0) / 180.0))
    if chance <= 0.0 or sim.rng.random() >= chance:
        return
    region_state = state["regions"][coord]
    mayor = sim.actors[_mayor_id(coord)]
    region_state["owner_id"] = "king"
    mayor.commander = "king"
    mayor.regent = None
    revoked_regions[coord] = {
        "former_owner": noble.id,
        "revoked_at": sim.now,
        "reassign_after": sim.now + sim.rng.uniform(32.0, 72.0),
        "kept_warning_at": None,
    }
    distrust_gain = 6.0 + noble.traits.ambition * 8.0
    _raise_noble_distrust(sim, distrust_gain, exempt_id=noble.id)
    king.stats["noble_distrust"] = king.stats.get("noble_distrust", 0.0) + distrust_gain * 0.35
    sim.event_log.emit(
        sim.now,
        "title_revoked",
        f"[{coord}] King revokes {noble.display_name}'s title over the region",
        actor="king",
        noble=noble.id,
        location=coord,
        stress_score=score,
        distrust_gain=distrust_gain,
    )


def _reassign_revoked_regions(
    sim: Simulation,
    setup: KingdomSetup,
    revoked_regions: dict[str, dict],
) -> None:
    for coord, revoked in list(revoked_regions.items()):
        if sim.now < revoked["reassign_after"]:
            continue
        king = sim.actors["king"]
        keep_bias = king.traits.ambition - king.traits.honesty * 0.35
        if keep_bias > 0.18 and sim.rng.random() < min(0.65, keep_bias):
            if revoked["kept_warning_at"] is None or sim.now - revoked["kept_warning_at"] >= 48.0:
                revoked["kept_warning_at"] = sim.now
                revoked["reassign_after"] = sim.now + 48.0
                _raise_noble_distrust(sim, 5.0)
                king.stats["noble_distrust"] = king.stats.get("noble_distrust", 0.0) + 5.0
                sim.event_log.emit(
                    sim.now,
                    "revoked_region_kept",
                    f"[{coord}] King keeps revoked land in crown hands, alarming Nobles",
                    actor="king",
                    location=coord,
                    former_owner=revoked["former_owner"],
                    noble_distrust=king.stats["noble_distrust"],
                )
                continue
        recipient = _choose_region_recipient(sim, setup, coord, revoked["former_owner"])
        if recipient is None:
            revoked["reassign_after"] = sim.now + 48.0
            continue
        region_state = sim.scenario_state[KINGDOM_STATE_KEY]["regions"][coord]
        mayor = sim.actors[_mayor_id(coord)]
        region_state["owner_id"] = recipient.id
        mayor.commander = recipient.id
        recipient.stats["noble_distrust"] = max(0.0, recipient.stats.get("noble_distrust", 0.0) - 3.0)
        sim.event_log.emit(
            sim.now,
            "region_reassigned",
            f"[{coord}] King reassigns revoked region to {recipient.display_name}",
            actor="king",
            recipient=recipient.id,
            location=coord,
            former_owner=revoked["former_owner"],
        )
        del revoked_regions[coord]


def _choose_region_recipient(
    sim: Simulation,
    setup: KingdomSetup,
    coord: str,
    former_owner: str,
) -> Actor | None:
    candidates = []
    king = sim.actors["king"]
    for actor in sim.actors.values():
        if actor.id in {"king", former_owner} or actor.title not in {"Noble", "Royal Noble"}:
            continue
        if actor.vacant:
            continue
        holdings = sum(
            1 for region_state in sim.scenario_state[KINGDOM_STATE_KEY]["regions"].values()
            if region_state["owner_id"] == actor.id
        )
        adjacency = any(
            _connected(coord, other)
            for other, region_state in sim.scenario_state[KINGDOM_STATE_KEY]["regions"].items()
            if region_state["owner_id"] == actor.id
        )
        score = (
            actor.traits.loyalty * 1.8
            + actor.traits.competence * 1.4
            + actor.traits.honesty
            - holdings * 0.35
            - actor.stats.get("noble_distrust", 0.0) / 80.0
            + (0.45 if actor.title == "Royal Noble" else 0.0)
            + (0.65 if adjacency else 0.0)
            + king.affinity_for(actor.identity) * 0.55
        )
        candidates.append((score, actor))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _raise_noble_distrust(sim: Simulation, amount: float, exempt_id: str | None = None) -> None:
    for actor in sim.actors.values():
        if actor.id == exempt_id or actor.title not in {"Noble", "Royal Noble"}:
            continue
        actor.stats["noble_distrust"] = actor.stats.get("noble_distrust", 0.0) + amount


def _mortality_step(sim: Simulation, setup: KingdomSetup) -> None:
    for actor in sorted(sim.actors.values(), key=lambda a: a.id):
        if actor.vacant:
            continue
        chance = DEATH_CHANCE_BY_TITLE.get(actor.title, 0.0)
        if chance <= 0.0:
            continue
        tenure = sim.now - actor.tenure_start_time
        if tenure < KINGDOM_TURN_INTERVAL * 2:
            continue
        danger = 1.0
        if actor.title in {"Mayor", "Guard Captain"}:
            danger += actor.stats.get("monster_pressure", 0.0) / 220.0
            danger += actor.stats.get("unrest", 0.0) / 350.0
        elif actor.title in {"Noble", "Royal Noble"}:
            danger += actor.stats.get("noble_distrust", 0.0) / 300.0
        if sim.rng.random() >= chance * danger:
            continue
        _handle_actor_death(sim, setup, actor)


def _handle_actor_death(sim: Simulation, setup: KingdomSetup, actor: Actor) -> None:
    sim.scenario_state[KINGDOM_STATE_KEY]["dead_occupants"].append({
        "actor": actor.id,
        "display_name": actor.display_name,
        "title": actor.title,
        "time": sim.now,
    })
    sim.event_log.emit(
        sim.now,
        "actor_death",
        f"[{actor.location}] {actor.title} {actor.display_name} dies unexpectedly",
        actor=actor.id,
        title=actor.title,
        display_name=actor.display_name,
        location=actor.location,
    )
    if actor.id == "king":
        _handle_king_succession(sim, setup, actor)
        return
    superior = sim.actors.get(actor.commander) or sim.actors["king"]
    candidate = _generated_successor_candidate(sim, actor)
    install_occupant(sim, actor, superior, candidate, reason="random death")
    sim.event_log.emit(
        sim.now,
        "office_succession",
        f"[{actor.location}] {candidate.display_name} succeeds to {actor.title}",
        actor=actor.id,
        title=actor.title,
        successor_name=candidate.display_name,
        successor_identity=candidate.identity,
    )


def _handle_king_succession(sim: Simulation, setup: KingdomSetup, king: Actor) -> None:
    successor = _choose_royal_successor(sim, setup)
    if successor is None:
        candidate = _generated_successor_candidate(sim, king)
        score = 0.0
        source_title = "emergency council"
        source_actor = None
    else:
        candidate = _candidate_from_actor(successor, f"succession_{successor.id}_{int(sim.now)}")
        score = _succession_score(sim, setup, successor)
        source_title = successor.title
        source_actor = successor.id
    install_occupant(sim, king, king, candidate, reason="king died")
    sim.event_log.emit(
        sim.now,
        "succession",
        f"{candidate.display_name} succeeds to the crown from {source_title}",
        actor="king",
        successor=source_actor,
        successor_name=candidate.display_name,
        successor_identity=candidate.identity,
        source_title=source_title,
        strength_score=score,
    )
    if successor is not None and successor.id != "king" and not successor.vacant:
        vacate(sim, successor, king, reason=f"{candidate.display_name} succeeded to the crown")


def _choose_royal_successor(sim: Simulation, setup: KingdomSetup) -> Actor | None:
    nobles = [
        actor for actor in sim.actors.values()
        if actor.title in {"Royal Noble", "Noble"} and not actor.vacant
    ]
    if not nobles:
        return None
    royals = [actor for actor in nobles if actor.title == "Royal Noble"]
    pool = royals if royals else nobles
    return max(pool, key=lambda actor: _succession_score(sim, setup, actor))


def _succession_score(sim: Simulation, setup: KingdomSetup, actor: Actor) -> float:
    state = sim.scenario_state[KINGDOM_STATE_KEY]
    holdings = [
        coord for coord, region_state in state["regions"].items()
        if region_state["owner_id"] == actor.id
    ]
    profile = setup.nobles.get(actor.id)
    family_pull = 0.0
    if profile is not None:
        family_pull += 18.0 if "king" in profile.family_ties else 0.0
        family_pull += 5.0 * len(profile.family_ties)
    army = actor.stats.get("soldiers", 0.0) + actor.stats.get("warriors", 0.0) * 4.0
    stockpiles = (
        actor.stats.get("food_stores", 0.0) / 120.0
        + actor.stats.get("money", 0.0) / 160.0
        + actor.stats.get("weapons", 0.0) / 80.0
    )
    support = (
        actor.traits.loyalty * 12.0
        + actor.traits.competence * 10.0
        + actor.traits.honesty * 8.0
        - actor.stats.get("noble_distrust", 0.0) * 0.45
    )
    return (
        (25.0 if actor.title == "Royal Noble" else 0.0)
        + len(holdings) * 16.0
        + army / 32.0
        + stockpiles
        + family_pull
        + support
    )


def _candidate_from_actor(actor: Actor, candidate_id: str) -> Candidate:
    return Candidate(
        id=candidate_id,
        display_name=actor.display_name,
        traits=actor.traits,
        identity=actor.identity,
        prejudice=dict(actor.prejudice),
        preference=dict(actor.preference),
    )


def _generated_successor_candidate(sim: Simulation, office: Actor) -> Candidate:
    identity = office.identity or sim.rng.choice(RACES)
    prejudice = dict(office.prejudice)
    preference = dict(office.preference)
    if sim.rng.random() < 0.35:
        prejudice = _affinity_map(
            sim.rng.sample([race for race in RACES if race != identity], k=sim.rng.randint(0, 1))
        )
    if sim.rng.random() < 0.35:
        preference = _affinity_map(
            sim.rng.sample([race for race in RACES if race not in prejudice], k=sim.rng.randint(0, 1))
        )
    base = office.traits
    traits = Traits(
        competence=max(0.25, min(0.95, base.competence + sim.rng.uniform(-0.16, 0.16))),
        honesty=max(0.25, min(0.98, base.honesty + sim.rng.uniform(-0.16, 0.16))),
        loyalty=max(0.20, min(0.98, base.loyalty + sim.rng.uniform(-0.18, 0.18))),
        ambition=max(0.05, min(0.95, base.ambition + sim.rng.uniform(-0.18, 0.18))),
        fear=max(0.05, min(0.90, base.fear + sim.rng.uniform(-0.14, 0.14))),
        education=max(0.20, min(0.95, base.education + sim.rng.uniform(-0.16, 0.16))),
    )
    title_word = {
        "King": "Heir",
        "Royal Noble": "Heir",
        "Noble": "Heir",
        "Mayor": "Deputy",
        "Guard Captain": "Lieutenant",
    }.get(office.title, "Successor")
    return Candidate(
        id=f"generated_{office.id}_{int(sim.now)}",
        display_name=f"{title_word} {_surname(sim.rng)}",
        traits=traits,
        identity=identity,
        prejudice=prejudice,
        preference=preference,
    )


def run(seed: int, ticks: int, runs_dir: Path) -> Path:
    rng = random.Random(seed)
    setup = generate(seed)

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_dir / f"isekai_kingdom-seed{seed}-{stamp}"
    log = EventLog(jsonl_path=base.with_suffix(".jsonl"), human_path=base.with_suffix(".log"))
    log.open()

    sim = Simulation(
        world=setup.world,
        actors=setup.actors,
        rng=rng,
        event_log=log,
        ruleset=RULESET,
        candidate_pool=candidate_pool(),
        bus_loss_prob=0.07,
        bus_jitter_frac=0.25,
    )
    _emit_setup(log, setup)
    schedule_kingdom_systems(sim, setup)
    scripted_events(sim, setup)
    try:
        sim.run_until(float(ticks))
        king = setup.actors["king"]
        log.emit(sim.now, "final_snapshot", "=== END OF ISEKAI KINGDOM RUN ===")
        for actor in sorted(setup.actors.values(), key=lambda a: (a.location, a.id)):
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
                        f"age {age:.0f}t, chain {' -> '.join(belief.source_chain) or '-'})"
                    )
                log.emit(sim.now, "final_snapshot", summary, actor=actor.id, stat=stat)
    finally:
        log.close()
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=None,
                        help="random each run unless given; pass to reproduce a run")
    parser.add_argument("--ticks", type=int, default=400,
                        help="logical time units to advance")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    out = run(seed, args.ticks, args.runs_dir)
    print(f"seed={seed}")
    print(f"Wrote {out}.jsonl and {out}.log")


def _bump(sim: Simulation, actor_id: str, stat: str, delta: float, cause: str) -> None:
    actor = sim.actors.get(actor_id)
    if actor is None:
        sim.event_log.emit(
            sim.now,
            "true_state_change_skipped",
            f"scripted {cause} for {actor_id} skipped - office absent",
            actor=actor_id,
            stat=stat,
            cause=cause,
        )
        return
    before = actor.stats.get(stat, 0.0)
    after = max(0.0, before + delta)
    actor.stats[stat] = after
    sim.event_log.emit(
        sim.now,
        "true_state_change",
        f"[{actor.location}] {cause}: {stat} {before:.0f} -> {after:.0f}",
        actor=actor.id,
        location=actor.location,
        stat=stat,
        before=before,
        after=after,
        cause=cause,
    )


def _affinity_map(identities: tuple[str, ...] | list[str]) -> dict[str, float]:
    return {identity: 0.20 for identity in identities}


def _dominant_race(rng: random.Random, race_pops: dict[str, int]) -> str:
    total = sum(race_pops.values())
    if total <= 0:
        return rng.choice(RACES)
    mark = rng.randrange(total)
    acc = 0
    for race in RACES:
        acc += race_pops.get(race, 0)
        if mark < acc:
            return race
    return RACES[-1]


def _local_affinity_maps(
    rng: random.Random,
    identity: str,
    region: RegionProfile,
) -> tuple[dict[str, float], dict[str, float]]:
    prejudice_pool = [race for race in RACES if race != identity]
    prejudice: dict[str, float] = {}
    preference: dict[str, float] = {}
    if rng.random() < 0.55:
        target = rng.choice(prejudice_pool)
        prejudice[target] = rng.uniform(0.10, 0.35)
    if rng.random() < 0.45:
        likely = [
            race for race, pops in region.race_pops.items()
            if race != identity and pops > 0 and race not in prejudice
        ]
        target = rng.choice(likely or [race for race in RACES if race not in prejudice])
        preference[target] = rng.uniform(0.10, 0.28)
    return prejudice, preference


def _split_military_stats(stats: dict[str, float], race_pops: dict[str, int], rng: random.Random) -> None:
    total_pops = sum(race_pops.values())
    if total_pops <= 0:
        for race in RACES:
            key = race.replace("-", "_")
            stats[f"{key}_soldiers"] = 0.0
            stats[f"{key}_warriors"] = 0.0
        return
    military_bias = {
        "human": 1.0,
        "elf": 0.72,
        "orc": 1.35,
        "beast-man": 1.12,
        "dwarf": 1.18,
        "demon": 1.08,
    }
    weighted = {
        race: race_pops.get(race, 0) * military_bias[race] * rng.uniform(0.85, 1.15)
        for race in RACES
    }
    denom = sum(weighted.values()) or 1.0
    warrior_weighted = {
        race: weighted[race] * (1.2 if race in {"orc", "dwarf", "demon"} else 1.0)
        for race in RACES
    }
    warrior_denom = sum(warrior_weighted.values()) or 1.0
    soldiers = stats.get("soldiers", 0.0)
    warriors = stats.get("warriors", 0.0)
    for race in RACES:
        key = race.replace("-", "_")
        share = weighted[race] / denom
        stats[f"{key}_soldiers"] = soldiers * share
        stats[f"{key}_warriors"] = warriors * warrior_weighted[race] / warrior_denom


def _ensure_actor_military_splits(rng: random.Random, actors: dict[str, Actor]) -> None:
    for actor in actors.values():
        if any(stat in actor.stats for stat in SOLDIER_STATS):
            continue
        soldiers = actor.stats.get("soldiers", 0.0)
        warriors = actor.stats.get("warriors", 0.0)
        if soldiers <= 0 and warriors <= 0:
            continue
        weights = {race: rng.uniform(0.6, 1.2) for race in RACES}
        if actor.identity in weights:
            weights[actor.identity] *= 2.2
        denom = sum(weights.values()) or 1.0
        for race in RACES:
            key = race.replace("-", "_")
            share = weights[race] / denom
            actor.stats[f"{key}_soldiers"] = soldiers * share
            actor.stats[f"{key}_warriors"] = warriors * share


def _noble_traits(rng: random.Random, royal: bool, holdings: int) -> Traits:
    return Traits(
        competence=_clamp(rng.uniform(0.48, 0.84) + (0.05 if royal else 0.0)),
        honesty=_clamp(rng.uniform(0.45, 0.86) - 0.015 * max(0, holdings - 2)),
        loyalty=_clamp(rng.uniform(0.38, 0.86) + (0.08 if royal else 0.0)),
        ambition=_clamp(rng.uniform(0.30, 0.82) + 0.035 * holdings),
        fear=_clamp(rng.uniform(0.12, 0.58)),
        education=_clamp(rng.uniform(0.45, 0.82) + (0.06 if royal else 0.0)),
    )


def _mayor_traits(rng: random.Random, region: RegionProfile) -> Traits:
    pressure = 0.10 if not region.developed else 0.0
    pressure += min(0.18, region.stats["monster_pressure"] / 320.0)
    return Traits(
        competence=_clamp(rng.uniform(0.42, 0.82) - pressure * 0.3),
        honesty=_clamp(rng.uniform(0.48, 0.86)),
        loyalty=_clamp(rng.uniform(0.42, 0.88)),
        ambition=_clamp(rng.uniform(0.22, 0.72)),
        fear=_clamp(rng.uniform(0.18, 0.66) + pressure),
        education=_clamp(rng.uniform(0.38, 0.74)),
    )


def _guard_traits(rng: random.Random, region: RegionProfile) -> Traits:
    threat = min(0.18, region.stats["monster_pressure"] / 280.0)
    return Traits(
        competence=_clamp(rng.uniform(0.50, 0.86)),
        honesty=_clamp(rng.uniform(0.55, 0.86)),
        loyalty=_clamp(rng.uniform(0.45, 0.88)),
        ambition=_clamp(rng.uniform(0.18, 0.58)),
        fear=_clamp(rng.uniform(0.16, 0.54) + threat),
        education=_clamp(rng.uniform(0.34, 0.66)),
    )


def _settlement_size(
    rng: random.Random,
    coord: str,
    geography: dict[str, float],
    index: int,
) -> str:
    if coord == CAPITAL and index == 0:
        return "city"
    if coord in {NORTH_PORT, SOUTH_PORT} and index == 0:
        return "city"
    city_weight = 0.45 + geography["trade"] * 0.45
    town_weight = 2.2 + geography["trade"] * 0.45
    return rng.choices(("village", "town", "city"), weights=(4.4, town_weight, city_weight), k=1)[0]


def _specialization(
    rng: random.Random,
    coord: str,
    geography: dict[str, float],
    mining_count: int,
) -> str | None:
    options: list[tuple[str | None, float]] = [
        (None, 0.80),
        ("Agricultural", 1.10 * geography["agriculture"]),
        ("Mining", 1.05 * geography["mining"]),
        ("Military", 0.45 + geography["border_guard"] * 0.70),
        ("Production", 0.65 + geography["mining"] * 0.25),
        ("Trade", 0.55 + geography["trade"] * 0.90),
    ]
    if coord == CAPITAL:
        options.extend([("Trade", 1.1), ("Production", 0.9), ("Military", 0.7)])
    if coord in {NORTH_PORT, SOUTH_PORT}:
        options.extend([("Trade", 2.4), ("Production", 0.6)])
    if mining_count >= 2:
        options = [(spec, weight) for spec, weight in options if spec != "Agricultural"]
    return _weighted_choice(rng, options)


def _focus_for(rng: random.Random, spec: str | None, geography: dict[str, float]) -> str | None:
    if spec is None:
        return None
    if spec == "Agricultural":
        return _weighted_choice(rng, [
            ("food", geography["agriculture"] + 1.0),
            ("lumber", geography["forest"]),
            ("herbs", geography["forest"] * 0.85),
        ])
    if spec == "Mining":
        return "ore"
    if spec == "Military":
        return _weighted_choice(rng, [("soldiers", 3.0), ("scouts", 1.0)])
    if spec == "Production":
        return _weighted_choice(rng, [("wares", 1.4), ("weapons", 1.1), ("luxury goods", 0.8)])
    if spec == "Trade":
        return _weighted_choice(rng, [("money", 1.4), ("luxury goods", 0.9), ("balanced", 1.1)])
    raise AssertionError(f"unknown specialization: {spec}")


def _defense_quality(
    rng: random.Random,
    size: str,
    spec: str | None,
    geography: dict[str, float],
) -> float:
    base = {"village": 0.15, "town": 0.42, "city": 0.76}[size]
    base += 0.10 if spec in {"Production", "Military"} else 0.0
    base += 0.04 * geography["mining"]
    return _clamp(rng.gauss(base, 0.12))


def _guard_strength(region: RegionProfile) -> float:
    if not any(s.size in {"town", "city"} for s in region.settlements):
        return 0.0
    fixed_defense = sum(s.defense_quality for s in region.settlements)
    military_bonus = sum(1 for s in region.settlements if s.specialization == "Military") * 90.0
    return max(40.0, region.stats["soldiers"] * 0.65 + fixed_defense * 35.0 + military_bonus)


def _spec_counts(settlements: tuple[Settlement, ...]) -> dict[str, int]:
    specs = ("Agricultural", "Mining", "Military", "Production", "Trade")
    return {spec: sum(1 for settlement in settlements if settlement.specialization == spec) for spec in specs}


def _focus_counts(settlements: tuple[Settlement, ...]) -> dict[str, int]:
    focuses = ("food", "lumber", "herbs", "ore", "wares", "weapons", "money")
    return {focus: sum(1 for settlement in settlements if settlement.focus == focus) for focus in focuses}


def _primary_economy(
    coord: str,
    spec_counts: dict[str, int],
    geography: dict[str, float],
    developed: bool,
) -> str:
    if not developed:
        return "Undeveloped"
    scores = {
        "Agricultural": spec_counts["Agricultural"] * 2.0 + geography["agriculture"],
        "Mining": spec_counts["Mining"] * 2.0 + geography["mining"],
        "Military": spec_counts["Military"] * 2.0 + geography["border_guard"],
        "Production": spec_counts["Production"] * 2.0,
        "Trade": spec_counts["Trade"] * 2.0 + geography["trade"],
    }
    if coord in {NORTH_PORT, SOUTH_PORT}:
        scores["Trade"] += 2.0
    if coord == CAPITAL:
        scores["Trade"] += 1.0
        scores["Production"] += 1.0
    return max(scores, key=scores.get)


def _seat_score(coord: str, holdings: tuple[str, ...]) -> float:
    geo = _geography(coord)
    neighbor_bonus = sum(1.0 for other in holdings if other != coord and _connected(coord, other))
    return geo["trade"] + geo["agriculture"] * 0.4 + neighbor_bonus


def _weighted_choice[T](rng: random.Random, options: list[tuple[T, float]]) -> T:
    total = sum(max(0.0, weight) for _value, weight in options)
    if total <= 0:
        return options[0][0]
    mark = rng.random() * total
    acc = 0.0
    for value, weight in options:
        acc += max(0.0, weight)
        if mark <= acc:
            return value
    return options[-1][0]


def _connected(a: str, b: str) -> bool:
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return max(abs(ax - bx), abs(ay - by)) == 1


def _xy(coord: str) -> tuple[int, int]:
    return COLUMNS.index(coord[0]), int(coord[1]) - 1


def _col(coord: str) -> str:
    return coord[0]


def _row(coord: str) -> int:
    return int(coord[1])


def _coord_index(coord: str) -> int:
    x, y = _xy(coord)
    return y * len(COLUMNS) + x


def _mayor_id(coord: str) -> str:
    return f"mayor_{coord.lower()}"


def _guard_id(coord: str) -> str:
    return f"guard_{coord.lower()}"


def _mayor_name(rng: random.Random, coord: str, developed: bool) -> str:
    title = "Mayor" if developed else "Caretaker"
    return f"{title} {_surname(rng)} of {coord}"


def _surname(rng: random.Random) -> str:
    return rng.choice((
        "Ash", "Bell", "Cale", "Dorn", "Elder", "Fen", "Gale", "Holt",
        "Iris", "Jade", "Kest", "Lark", "Morn", "Nell", "Orr", "Pike",
        "Quell", "Reed", "Stane", "Thorn", "Vale", "Wynn",
    ))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


if __name__ == "__main__":
    main()

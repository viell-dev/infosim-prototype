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
from ..personnel import Candidate
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

SETTLEMENT_CAPACITY = {
    "village": 420,
    "town": 1100,
    "city": 2600,
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
        "weapons": StatSpec("weapons", polarity=+1),
        "warriors": StatSpec("warriors", polarity=+1),
        "food_workers": StatSpec("food_workers", polarity=+1),
        "lumber_workers": StatSpec("lumber_workers", polarity=+1),
        "herb_workers": StatSpec("herb_workers", polarity=+1),
        "ore_workers": StatSpec("ore_workers", polarity=+1),
        "craft_workers": StatSpec("craft_workers", polarity=+1),
        "trade_workers": StatSpec("trade_workers", polarity=+1),
        **{stat: StatSpec(stat, polarity=+1) for stat in POP_STATS},
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
    },
    roles={
        "King": RoleSpec(
            title="King",
            behaviors=("issue_orders", "consume"),
            decay=(
                DecaySpec(stat="food_stores", rate=0.006, driver_stat="population"),
                DecaySpec(stat="money", rate=0.001),
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
                ProductionSpec("money", "trade_workers", rate=0.08),
            ),
            decay=(
                DecaySpec(stat="food_stores", rate=0.026, driver_stat="population"),
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
        ),
        Candidate(
            id="cand_osric",
            display_name="Osric Bell",
            traits=Traits(competence=0.66, honesty=0.72, loyalty=0.92, ambition=0.25,
                          fear=0.36, education=0.58),
        ),
        Candidate(
            id="cand_senna",
            display_name="Senna Voss",
            traits=Traits(competence=0.90, honesty=0.62, loyalty=0.58, ambition=0.70,
                          fear=0.18, education=0.88),
        ),
        Candidate(
            id="cand_iora",
            display_name="Iora Dusk",
            traits=Traits(competence=0.70, honesty=0.80, loyalty=0.74, ambition=0.42,
                          fear=0.28, education=0.76),
        ),
        Candidate(
            id="cand_garron",
            display_name="Garron Pike",
            traits=Traits(competence=0.58, honesty=0.88, loyalty=0.96, ambition=0.18,
                          fear=0.50, education=0.46),
        ),
        Candidate(
            id="cand_velia",
            display_name="Velia Thorn",
            traits=Traits(competence=0.82, honesty=0.58, loyalty=0.48, ambition=0.76,
                          fear=0.24, education=0.80),
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
    add(Actor(
        id="king",
        display_name="Aster Halric",
        title="King",
        location=CAPITAL,
        commander=None,
        traits=Traits(competence=0.78, honesty=0.84, loyalty=0.92, ambition=0.38,
                      fear=0.18, education=0.88),
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
            "weapons": 850.0,
            "warriors": 95.0,
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
                "weapons": 160.0 + sum(s["weapons"] * 0.18 for s in holding_stats),
                "warriors": 8.0 + 4.0 * len(noble.holdings) + rng.uniform(0, 22),
            },
            report_every=13,
            observe_every=7,
            decide_every=11,
        ))

    for region in regions.values():
        mayor_id = _mayor_id(region.coord)
        add(Actor(
            id=mayor_id,
            display_name=_mayor_name(rng, region.coord, region.developed),
            title="Mayor",
            location=region.coord,
            commander=region.owner_id,
            traits=_mayor_traits(rng, region),
            stats=dict(region.stats),
            report_every=9,
            observe_every=5,
            decide_every=8,
        ))
        guard_strength = _guard_strength(region)
        if guard_strength > 0:
            add(Actor(
                id=_guard_id(region.coord),
                display_name=f"Guard Captain {_surname(rng)}",
                title="Guard Captain",
                location=region.coord,
                commander=mayor_id,
                traits=_guard_traits(rng, region),
                stats={
                    "food_stores": max(120.0, guard_strength * rng.uniform(1.5, 2.8)),
                    "soldiers": guard_strength,
                    "warriors": max(0.0, guard_strength * rng.uniform(0.03, 0.13)),
                    "monster_pressure": region.stats["monster_pressure"] * rng.uniform(0.45, 0.90),
                    "unrest": region.stats["unrest"] * rng.uniform(0.20, 0.55),
                    "weapons": guard_strength * rng.uniform(0.75, 1.35),
                },
                report_every=7,
                observe_every=4,
                decide_every=6,
            ))
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
        "weapons": max(20.0, 40.0 + craft_workers * rng.uniform(0.20, 0.60) + ore_workers * 0.10),
        "warriors": max(0.0, soldiers * rng.uniform(0.015, 0.080)),
        "food_workers": max(0.0, food_workers),
        "lumber_workers": max(0.0, lumber_workers),
        "herb_workers": max(0.0, herb_workers),
        "ore_workers": max(0.0, ore_workers),
        "craft_workers": max(0.0, craft_workers),
        "trade_workers": max(0.0, trade_workers),
    }
    for race in RACES:
        stats[f"{race.replace('-', '_')}_pops"] = float(race_pops.get(race, 0))
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

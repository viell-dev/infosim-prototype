from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StatSpec:
    """Metadata for a stat tracked on actors.

    polarity:
      +1 — higher values are "good news" (garrison_strength, food_stores, ships, ore)
      -1 — higher values are "bad news" (unrest, alien_presence)

    Fear bias uses polarity to push reports in the comforting direction.
    """
    name: str
    polarity: int


# Stat schema. Genre-specific replacements (ore, credits, morale, …) plug in here.
STATS: dict[str, StatSpec] = {
    "garrison_strength": StatSpec("garrison_strength", polarity=+1),
    "food_stores":       StatSpec("food_stores",       polarity=+1),
    "unrest":            StatSpec("unrest",            polarity=-1),
    "ships":             StatSpec("ships",             polarity=+1),
    "ore":               StatSpec("ore",               polarity=+1),
    "population":        StatSpec("population",        polarity=+1),
    "alien_presence":    StatSpec("alien_presence",    polarity=-1),
}
# Backwards-compatible alias used in older references.
VARIABLES = STATS


@dataclass
class Location:
    """A node in the travel topology. Holds no game state — actors do."""
    name: str


@dataclass
class World:
    """Topology only. Actors carry their own state (see actors.Actor.stats)."""
    locations: dict[str, Location] = field(default_factory=dict)
    edges: dict[str, dict[str, int]] = field(default_factory=dict)

    # Back-compat alias so existing call sites that say `world.regions[name]`
    # keep working. The object stored is still a Location.
    @property
    def regions(self) -> dict[str, Location]:
        return self.locations

    def add_location(self, location: Location) -> None:
        self.locations[location.name] = location
        self.edges.setdefault(location.name, {})

    # Back-compat alias.
    def add_region(self, region: Location) -> None:
        self.add_location(region)

    def connect(self, a: str, b: str, travel_ticks: int) -> None:
        self.edges[a][b] = travel_ticks
        self.edges[b][a] = travel_ticks

    def travel_ticks(self, a: str, b: str) -> int:
        if a == b:
            return 0
        return self.edges[a][b]


# Back-compat alias: existing code uses `Region(name=...)`. State is now ignored.
def Region(name: str, state: dict[str, float] | None = None) -> Location:  # noqa: N802
    return Location(name=name)

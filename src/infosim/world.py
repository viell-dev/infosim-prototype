from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VariableSpec:
    """Metadata for a tracked region variable.

    polarity:
      +1 — higher values are "good news" (garrison_strength, food_stores)
      -1 — higher values are "bad news" (unrest)

    Fear bias uses polarity to push reports in the comforting direction.
    """
    name: str
    polarity: int


VARIABLES: dict[str, VariableSpec] = {
    "garrison_strength": VariableSpec("garrison_strength", polarity=+1),
    "food_stores":       VariableSpec("food_stores",       polarity=+1),
    "unrest":            VariableSpec("unrest",            polarity=-1),
}


@dataclass
class Region:
    name: str
    state: dict[str, float] = field(default_factory=dict)


@dataclass
class World:
    regions: dict[str, Region] = field(default_factory=dict)
    # adjacency: region_name -> {neighbour_name: base_travel_ticks}
    edges: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_region(self, region: Region) -> None:
        self.regions[region.name] = region
        self.edges.setdefault(region.name, {})

    def connect(self, a: str, b: str, travel_ticks: int) -> None:
        self.edges[a][b] = travel_ticks
        self.edges[b][a] = travel_ticks

    def travel_ticks(self, a: str, b: str) -> int:
        return self.edges[a][b]

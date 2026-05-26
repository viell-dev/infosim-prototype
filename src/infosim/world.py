from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Region:
    name: str
    garrison_strength: int


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

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Location:
    """A node in the travel topology. Holds no game state — actors do."""
    name: str


@dataclass
class World:
    """Topology only. Actors carry their own state (see actors.Actor.stats)."""
    locations: dict[str, Location] = field(default_factory=dict)
    edges: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_location(self, location: Location) -> None:
        self.locations[location.name] = location
        self.edges.setdefault(location.name, {})

    def connect(self, a: str, b: str, travel_ticks: int) -> None:
        self.edges[a][b] = travel_ticks
        self.edges[b][a] = travel_ticks

    def travel_ticks(self, a: str, b: str) -> int:
        if a == b:
            return 0
        return self.edges[a][b]

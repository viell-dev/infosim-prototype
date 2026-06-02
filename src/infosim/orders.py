from __future__ import annotations

import enum
from dataclasses import dataclass


class OrderKind(enum.Enum):
    REINFORCE = "REINFORCE"              # move garrison toward target_actor's command
    SUPPRESS_UNREST = "SUPPRESS_UNREST"  # run a suppression campaign for target_actor
    SEND_SUPPLIES = "SEND_SUPPLIES"      # ship food to target_actor
    MOVE_TO_LOCATION = "MOVE_TO_LOCATION"  # move target_actor to target_location
    DEFEND_LOCATION = "DEFEND_LOCATION"    # reduce the threat stat at target_actor/location


@dataclass
class Order:
    id: int
    issuer: str                  # actor id of the originator
    recipient: str               # actor id of the immediate addressee
    kind: OrderKind
    target_actor: str            # actor id whose stats this order ultimately affects
    magnitude: float             # interpretation depends on kind (troop count, food amount, ...)
    issued_time: float
    deadline_time: float         # advisory; actors may still execute past it
    priority: int = 1            # higher = more urgent
    target_location: str | None = None
    assigned_commander: str | None = None

    # Back-compat: older code reads `order.target_region`. The semantics
    # changed; this property returns the *location* of target_actor when the
    # caller has access to the sim, but for log purposes the id is fine too.
    @property
    def target_region(self) -> str:
        return self.target_actor

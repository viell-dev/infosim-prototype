from __future__ import annotations

import enum
from dataclasses import dataclass


class OrderKind(enum.Enum):
    REINFORCE = "REINFORCE"              # move garrison toward target_region
    SUPPRESS_UNREST = "SUPPRESS_UNREST"  # run a suppression campaign in target_region
    SEND_SUPPLIES = "SEND_SUPPLIES"      # ship food to target_region


@dataclass
class Order:
    id: int
    issuer: str                  # actor id of the originator
    recipient: str               # actor id of the immediate addressee
    kind: OrderKind
    target_region: str
    magnitude: float             # interpretation depends on kind (troop count, food amount, ...)
    issued_tick: int
    deadline_tick: int           # advisory; actors may still execute past it
    priority: int = 1            # higher = more urgent

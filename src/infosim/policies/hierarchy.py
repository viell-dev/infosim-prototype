from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..actors import Actor
    from ..sim import Simulation


def _subordinates(sim: "Simulation", actor: "Actor") -> list["Actor"]:
    return [a for a in sim.actors.values() if a.commander == actor.id]


def _transitive_subs(sim: "Simulation", actor: "Actor") -> set[str]:
    """All descendant actor ids reachable through the commander chain."""
    seen: set[str] = set()
    stack: list["Actor"] = list(_subordinates(sim, actor))
    while stack:
        s = stack.pop()
        if s.id in seen:
            continue
        seen.add(s.id)
        stack.extend(_subordinates(sim, s))
    return seen


def _route_to_subordinate(sim: "Simulation", actor: "Actor", target_id: str) -> "Actor | None":
    """Find the direct subordinate of `actor` whose chain covers `target_id`."""
    for sub in _subordinates(sim, actor):
        if sub.id == target_id or target_id in _transitive_subs(sim, sub):
            return sub
    return None

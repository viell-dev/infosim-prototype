"""Scenario-owned ruleset: the only place genre knowledge lives.

The engine (`sim`, `policies`, `reports`, `actions`) is genre-agnostic. A
scenario builds a :class:`Ruleset` describing its stat schema and, per actor
*title*, that role's resources, production, natural decay (usage), upward
taxation, and decision thresholds — all as data. Medieval garrison/food/unrest
and sci-fi ore/ships/alien_presence are then two configurations of the same
core, each including only the behaviors it uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class StatSpec:
    """Metadata for a stat tracked on actors.

    polarity:
      +1 — higher values are "good news" (garrison_strength, food_stores, ships, ore)
      -1 — higher values are "bad news" (unrest, alien_presence)

    Fear bias and forgery use polarity to push reports in the comforting
    direction.
    """
    name: str
    polarity: int


@dataclass(frozen=True)
class ProductionSpec:
    """A role generating a resource each decide cycle.

    Amount produced = ``driver_stat * rate * (competence_curve + competence)``.
    Models a captain mining ore proportional to ships, scaled by competence.
    """
    output_stat: str
    driver_stat: str
    rate: float
    competence_curve: float = 0.5


@dataclass(frozen=True)
class DecaySpec:
    """Natural decay / usage of a resource each decide cycle.

    If ``driver_stat`` is set, consumed = ``driver_stat * rate`` (e.g. a station
    consuming ore proportional to population). Otherwise consumed =
    ``stat * rate`` (a flat fraction of the stat itself).
    """
    stat: str
    rate: float
    driver_stat: str | None = None


@dataclass(frozen=True)
class TaxSpec:
    """Transfer a fraction of a resource upward to the commander each decide."""
    stat: str
    fraction: float
    label: str = "tax"


@dataclass(frozen=True)
class RoleSpec:
    """Everything that distinguishes one actor title from another.

    ``behaviors`` is an ordered tuple of generic-behavior names (see
    ``policies.behaviors.BEHAVIORS``). The remaining fields parameterise those
    behaviors with this role's economy and decision thresholds.

    Well-known ``thresholds`` keys:
      low_defense / low_supply / high_threat — apex order triggers
      autonomous_threat                      — middle autonomous suppression
      leaf_low_supply / leaf_low_defense     — leaf urgent-report triggers
      review_threat / review_defense         — single-sub review fallback
    """
    title: str
    behaviors: tuple[str, ...]
    production: tuple[ProductionSpec, ...] = ()
    decay: tuple[DecaySpec, ...] = ()
    tax: tuple[TaxSpec, ...] = ()
    thresholds: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Ruleset:
    """A scenario's complete rule configuration handed to the Simulation."""
    stats: Mapping[str, StatSpec]
    roles: Mapping[str, RoleSpec]
    defense_stat: str | None = None
    supply_stat: str | None = None
    threat_stat: str | None = None
    bad_news_thresholds: Mapping[str, float] = field(default_factory=dict)

    def role(self, title: str) -> RoleSpec | None:
        return self.roles.get(title)

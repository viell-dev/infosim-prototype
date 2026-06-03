from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, BeliefRecord, Traits
from infosim.logging_setup import EventLog
from infosim.personnel import Candidate, install_occupant, vacate
from infosim.scenarios.frontier import RULESET
from infosim.sim import Simulation
from infosim.world import Location, World


def _sim(tmp_path: Path) -> Simulation:
    world = World()
    for n in ("Capital", "Province", "Frontier"):
        world.add_location(Location(name=n))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)
    king = Actor(id="king", display_name="K", title="King", location="Capital",
                 commander=None, traits=Traits(), stats={})
    gov = Actor(id="gov", display_name="Mira", title="Governor", location="Province",
                commander="king", traits=Traits(loyalty=0.2, ambition=0.8),
                stats={"garrison_strength": 800, "food_stores": 1800, "unrest": 25},
                occupant_id="gov")
    cmd = Actor(id="cmd", display_name="Aldric", title="Commander", location="Frontier",
                commander="gov", traits=Traits(), stats={"garrison_strength": 1500})
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(world=world, actors={"king": king, "gov": gov, "cmd": cmd},
                      rng=random.Random(0), event_log=log, ruleset=RULESET)


def test_replacement_keeps_office_resets_person(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king, gov = sim.actors["king"], sim.actors["gov"]
    # Occupant's own belief, the King's resource belief about the office, and the
    # King's accumulated distrust of this office.
    gov.known["gov.food_stores"] = BeliefRecord("gov.food_stores", 1800, 0.9, 0.0, ["gov"])
    king.known["gov.food_stores"] = BeliefRecord("gov.food_stores", 9999, 0.5, 0.0, ["gov", "king"])
    king.strikes["gov"] = 2
    stats_before = dict(gov.stats)

    install_occupant(sim, gov, king, Candidate("cand_iselle", "Iselle", Traits(loyalty=0.9)),
                     reason="corruption")

    # Office persists.
    assert "gov" in sim.actors and sim.actors["gov"] is gov
    assert gov.location == "Province" and gov.title == "Governor"
    assert gov.stats == stats_before                      # resources stay
    assert sim.actors["cmd"].commander == "gov"           # subordinate not rewired
    assert king.known["gov.food_stores"].value == 9999    # superior's resource belief stays
    # Person resets.
    assert gov.display_name == "Iselle" and gov.occupant_id == "cand_iselle"
    assert gov.traits.loyalty == 0.9
    assert gov.known == {}                                # new occupant starts blind
    assert "gov" not in king.strikes                      # trust reset; no instant re-fire


def test_vacate_installs_caretaker_regency(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king, gov = sim.actors["king"], sim.actors["gov"]
    king.strikes["gov"] = 3
    stats_before = dict(gov.stats)

    vacate(sim, gov, king, reason="no candidates")

    assert gov.vacant is True
    assert gov.regent == "king"
    assert gov.occupant_id is None
    assert gov.traits.loyalty >= 0.85           # honest caretaker -> no forgery
    assert gov.traits.ambition == 0.0           # incorruptible -> no skim
    assert gov.stats == stats_before            # resources stay
    assert sim.actors["cmd"].commander == "gov"  # subtree intact
    assert "gov" not in king.strikes

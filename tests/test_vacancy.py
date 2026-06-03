from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.orders import Order, OrderKind
from infosim.personnel import vacate
from infosim.policies.roles import run_policy
from infosim.scenarios.frontier import RULESET
from infosim.sim import Simulation
from infosim.world import Location, World


def _sim(tmp_path: Path) -> Simulation:
    world = World()
    for n in ("Capital", "Province", "Frontier"):
        world.add_location(Location(name=n))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)
    # The long, direct hop a remote regent must use to reach the Frontier when
    # the Province seat between them is empty.
    world.connect("Capital", "Frontier", travel_ticks=10)
    king = Actor(id="king", display_name="K", title="King", location="Capital",
                 commander=None,
                 traits=Traits(competence=0.8, honesty=1.0, loyalty=1.0, fear=0.0, education=0.9),
                 stats={"garrison_strength": 1200, "food_stores": 3000, "unrest": 5})
    gov = Actor(id="gov", display_name="G", title="Governor", location="Province",
                commander="king", traits=Traits(),
                stats={"garrison_strength": 800, "food_stores": 1800, "unrest": 25})
    cmd = Actor(id="cmd", display_name="C", title="Commander", location="Frontier",
                commander="gov", traits=Traits(),
                stats={"garrison_strength": 1500, "food_stores": 900, "unrest": 40})
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    return Simulation(world=world, actors={"king": king, "gov": gov, "cmd": cmd},
                      rng=random.Random(0), event_log=log, ruleset=RULESET,
                      bus_loss_prob=0.0, bus_jitter_frac=0.0)


def test_regent_governs_vacant_office_from_its_own_seat(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king, gov, cmd = sim.actors["king"], sim.actors["gov"], sim.actors["cmd"]
    vacate(sim, gov, king, reason="no candidates")
    assert gov.vacant and gov.regent == "king"
    # The subordinate still belongs to the (now vacant) office.
    assert cmd.commander == "gov"

    # The King, governing the empty Province seat, has an order to pass down to
    # the Frontier commander; place it in the office inbox as if it just arrived.
    gov.inbox.append(Order(
        id=1, issuer="king", recipient="gov", kind=OrderKind.SUPPRESS_UNREST,
        target_actor="cmd", magnitude=40, issued_time=0.0, deadline_time=60.0, priority=2,
    ))
    run_policy(sim, gov)

    dispatched = [
        ev for ev in sim.event_log.events
        if ev["kind"] == "order_dispatched" and ev.get("recipient") == "cmd"
    ]
    assert dispatched, "the vacant office should forward the King's order downward"
    ev = dispatched[-1]
    # Issued by the King and carried Capital->Frontier (10) — the remote regent's
    # real distance — not Province->Frontier (6) as if a governor were present.
    assert ev["issuer"] == "king"
    assert abs(float(ev["eta_time"]) - 10.0) < 1e-6

    # The honest caretaker / honest regent never skims the empty seat.
    assert not any(
        e["kind"] == "skim" and e.get("actor") == "gov" for e in sim.event_log.events
    )


def test_vacant_seat_reports_resources_honestly_to_regent(tmp_path: Path) -> None:
    sim = _sim(tmp_path)
    king, gov = sim.actors["king"], sim.actors["gov"]
    vacate(sim, gov, king, reason="no candidates")
    # Drive the caretaker's observe + report cadences; the King should learn the
    # seat's true-ish resources (no forgery from a loyal caretaker).
    sim.run_until(40.0)
    belief = king.known.get(sim.subject_for("gov", "garrison_strength"))
    assert belief is not None, "regent should hear the vacant seat via its caretaker"
    # Honest caretaker: belief tracks the real 800, not an inflated forgery.
    assert belief.value < 1200

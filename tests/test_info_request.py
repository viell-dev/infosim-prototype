from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.policy import maybe_initiate_audit
from infosim.sim import Simulation
from infosim.world import Location, World


def _three_chain(tmp_path: Path, gov_loyalty: float = 0.9, cmd_loyalty: float = 0.9) -> Simulation:
    world = World()
    for n in ("Capital", "Province", "Frontier"):
        world.add_location(Location(name=n))
    world.connect("Capital", "Province", travel_ticks=4)
    world.connect("Province", "Frontier", travel_ticks=6)
    # Perfect observers so the test can isolate the request/response path
    # from observation/relay noise. Loyalty is varied per-test.
    king = Actor(id="king", display_name="K", title="King",
                 location="Capital", commander=None,
                 traits=Traits(competence=1.0, honesty=1.0, loyalty=1.0,
                               fear=0.0, education=1.0),
                 stats={"garrison_strength": 1200, "food_stores": 3000, "unrest": 5})
    gov = Actor(id="gov", display_name="G", title="Governor",
                location="Province", commander="king",
                traits=Traits(competence=1.0, honesty=1.0, loyalty=gov_loyalty,
                              fear=0.0, education=1.0),
                stats={"garrison_strength": 800, "food_stores": 1800, "unrest": 20})
    cmd = Actor(id="cmd", display_name="C", title="Commander",
                location="Frontier", commander="gov",
                traits=Traits(competence=1.0, honesty=1.0, loyalty=cmd_loyalty,
                              fear=0.0, education=1.0),
                stats={"garrison_strength": 700, "food_stores": 800, "unrest": 30})
    rng = random.Random(0)
    log = EventLog(jsonl_path=tmp_path / "x.jsonl", human_path=tmp_path / "x.log")
    log.open()
    sim = Simulation(
        world=world, actors={"king": king, "gov": gov, "cmd": cmd},
        rng=rng, event_log=log,
        bus_loss_prob=0.0, bus_jitter_frac=0.0,
    )
    return sim


def test_audit_round_trip_loyal_chain(tmp_path: Path) -> None:
    sim = _three_chain(tmp_path, gov_loyalty=0.9, cmd_loyalty=0.95)
    # Seed Aldric's belief about himself so he has something to answer with.
    cmd = sim.actors["cmd"]
    cmd.update_belief("cmd.garrison_strength", 700.0, 1.0, 0.0, ["cmd"])
    king = sim.actors["king"]
    gov = sim.actors["gov"]

    maybe_initiate_audit(sim, king, gov, cmd)
    assert len(king.pending_requests) == 1

    # Pre-deadline cutoff so ambient REPORT cadence doesn't overwrite the
    # audited belief before we inspect it. Cmd's first DECIDE processes the
    # forwarded request; gov's next DECIDE relays it back; king integrates.
    sim.run_until(30.0)

    belief = king.known.get("cmd.garrison_strength")
    assert belief is not None
    # Loyal chain, perfect actors: end-to-end audit returns truth.
    assert abs(belief.value - 700.0) < 1e-6
    assert king.pending_requests == {}


def test_disloyal_relay_does_not_forward(tmp_path: Path) -> None:
    # Governor loyalty 0.2 → below REQUEST_TRUST_THRESHOLD → protective mode:
    # answers from own cache instead of forwarding to the commander.
    sim = _three_chain(tmp_path, gov_loyalty=0.2, cmd_loyalty=0.95)
    king = sim.actors["king"]
    gov = sim.actors["gov"]
    cmd = sim.actors["cmd"]

    maybe_initiate_audit(sim, king, gov, cmd)
    # Drive past gov's first decide cycle so the inbox processes.
    sim.run_until(15.0)

    # Inspect the JSONL: there should be exactly one request_dispatched
    # event (king→gov, the original audit), no forwarded gov→cmd request.
    forwarded = [
        ev for ev in sim.event_log.events
        if ev["kind"] == "request_dispatched" and ev["actor"] == "gov"
    ]
    assert forwarded == []
    # And the original audit got a response (king's pending entry cleared).
    assert king.pending_requests == {}


def test_loyal_relay_does_forward(tmp_path: Path) -> None:
    sim = _three_chain(tmp_path, gov_loyalty=0.9, cmd_loyalty=0.95)
    king = sim.actors["king"]
    gov = sim.actors["gov"]
    cmd = sim.actors["cmd"]

    maybe_initiate_audit(sim, king, gov, cmd)
    sim.run_until(15.0)

    # Loyal gov forwarded to cmd.
    forwarded = [
        ev for ev in sim.event_log.events
        if ev["kind"] == "request_dispatched" and ev["actor"] == "gov"
        and ev.get("recipient") == "cmd"
    ]
    assert len(forwarded) == 1


def test_request_timeout_triggers_when_no_response(tmp_path: Path) -> None:
    sim = _three_chain(tmp_path, gov_loyalty=0.9)
    king = sim.actors["king"]
    gov = sim.actors["gov"]
    cmd = sim.actors["cmd"]

    # Remove the gov from the actor map mid-flight to simulate "no response".
    # We initiate, then dismiss the recipient before they can answer.
    maybe_initiate_audit(sim, king, gov, cmd)
    correlation_id = next(iter(king.pending_requests))
    del sim.actors["gov"]

    # Advance well past the deadline.
    sim.run_until(200.0)
    assert correlation_id not in king.pending_requests

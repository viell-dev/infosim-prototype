from __future__ import annotations

import random
from pathlib import Path

from infosim.actors import Actor, Traits
from infosim.logging_setup import EventLog
from infosim.policies.info_requests import maybe_initiate_audit
from infosim.scenarios.frontier import RULESET
from infosim.scheduler import EventKind
from infosim.sim import Simulation
from infosim.world import Location, World


def _silence_push_channel(sim: Simulation) -> None:
    """Bootstrap actor DECIDE cadences but suppress ambient REPORT/OBSERVE so
    the audit channel can be tested in isolation. Without this, cmd's t=0
    push report would reach gov at t=6 and overwrite the very cached
    belief we want gov's audit reply to reflect.
    """
    import heapq
    sim._bootstrap_actor_cadences()
    sim._bootstrapped = True
    sim.scheduler._heap = [
        qe for qe in sim.scheduler._heap
        if qe.event.kind not in (EventKind.REPORT, EventKind.OBSERVE)
    ]
    heapq.heapify(sim.scheduler._heap)


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
        ruleset=RULESET,
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


def test_disloyal_relay_protects_subordinate(tmp_path: Path) -> None:
    """A disloyal relay (loyalty < REQUEST_TRUST_THRESHOLD) must:
      1. NOT forward the audit to the subordinate (protective mode), AND
      2. answer the king from its own cached belief about that subordinate,
         which can be politically inflated relative to the truth on the
         ground.

    Push channel suppressed so cmd's t=0 report can't seep into gov's cache
    before the audit fires. We seed gov's cache with a deliberately-inflated
    value to model "Mira has been told a comfortable story for weeks."
    """
    sim = _three_chain(tmp_path, gov_loyalty=0.2, cmd_loyalty=0.95)
    king = sim.actors["king"]
    gov = sim.actors["gov"]
    cmd = sim.actors["cmd"]

    # gov "knows" cmd's garrison is enormous; the actual truth (cmd.stats)
    # is 700.
    gov.update_belief("cmd.garrison_strength", 2000.0, 0.5, 0.0, ["cmd", "gov"])

    maybe_initiate_audit(sim, king, gov, cmd)
    _silence_push_channel(sim)
    sim.run_until(20.0)

    # (1) gov did not forward.
    forwarded = [
        ev for ev in sim.event_log.events
        if ev["kind"] == "request_dispatched" and ev["actor"] == "gov"
    ]
    assert forwarded == [], f"disloyal gov should not forward, got {forwarded}"

    # (2) king ended up with gov's inflated cache value (or a value forged
    #     even higher) — definitely NOT close to the truth of 700.
    belief = king.known.get("cmd.garrison_strength")
    assert belief is not None, "king should have received a response"
    assert belief.value >= 2000.0 - 1e-6, (
        f"king's belief {belief.value:.1f} should reflect gov's inflated "
        f"cache (2000) — protective relay failed"
    )
    # Truth is 700; gov said 2000+. The king is now sitting on a +185%
    # over-estimate, with no idea he was lied to.
    assert belief.value > 1500.0  # double-check the divergence is real


def test_loyal_relay_does_forward(tmp_path: Path) -> None:
    """A loyal relay should forward the audit downstream rather than
    answering from its own (potentially stale) cache. Exactly one forwarded
    request from gov to cmd should appear in the log.
    """
    sim = _three_chain(tmp_path, gov_loyalty=0.9, cmd_loyalty=0.95)
    king = sim.actors["king"]
    gov = sim.actors["gov"]
    cmd = sim.actors["cmd"]

    maybe_initiate_audit(sim, king, gov, cmd)
    sim.run_until(15.0)

    forwarded = [
        ev for ev in sim.event_log.events
        if ev["kind"] == "request_dispatched" and ev["actor"] == "gov"
        and ev.get("recipient") == "cmd"
    ]
    assert len(forwarded) == 1, f"expected 1 forwarded request, got {len(forwarded)}"


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

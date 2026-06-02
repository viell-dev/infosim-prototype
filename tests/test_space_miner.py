from __future__ import annotations

from infosim.scenarios.space_miner import run
from tools.map_run import _read_events


def test_space_miner_exercises_mining_tax_movement_and_defense(tmp_path) -> None:
    base = run(seed=1, ticks=230, runs_dir=tmp_path)
    events = _read_events(base.with_suffix(".jsonl"))
    kinds = {str(ev["kind"]) for ev in events}

    assert "mining" in kinds
    assert "consumption" in kinds
    assert "alien_contact" in kinds
    assert "defense" in kinds

    tax_events = [
        ev for ev in events
        if ev["kind"] == "action_started" and ev.get("kind_detail") in {"ore_tax", "manager_tax"}
    ]
    assert tax_events

    arrivals = [
        ev for ev in events
        if ev["kind"] == "action_completed"
        and ev.get("kind_detail") == "move_actor_arrive"
        and ev.get("actor") == "cmd_orion"
    ]
    assert arrivals
    assert any(ev.get("assigned_commander") == "mgr_ceres" for ev in arrivals)
    assert any(ev.get("target_location") == "Europa Station" for ev in arrivals)
    assert any(ev.get("assigned_commander") == "ceo" for ev in arrivals)

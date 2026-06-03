from __future__ import annotations

from infosim.scenarios.space_miner import run
from tools.map_run import _infer_scenario, _read_events, build_checkpoints, render_html


def test_space_miner_exercises_mining_tax_movement_and_defense(tmp_path) -> None:
    # seed 2: a run where the full orion mission (out to Ceres/Europa then the
    # t=190 recall) survives courier loss. At some seeds the recall courier is
    # lost — a realistic outcome, but not what this capability test checks.
    base = run(seed=2, ticks=230, runs_dir=tmp_path)
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


def test_space_miner_map_infers_and_replays_mobile_commanders(tmp_path) -> None:
    base = run(seed=2, ticks=230, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")
    events = _read_events(jsonl_path)
    scenario = _infer_scenario(jsonl_path)
    checkpoints = build_checkpoints(events, scenario)
    html = render_html(checkpoints, jsonl_path)

    assert scenario == "space_miner"
    assert "Director Vale" in html
    assert "Orion Dray" in html
    assert checkpoints[-1].state.actors["cmd_orion"].location == "Homeworld"
    assert checkpoints[-1].state.actors["cmd_orion"].commander == "ceo"

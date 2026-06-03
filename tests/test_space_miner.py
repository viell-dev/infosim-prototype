from __future__ import annotations

from infosim.scenarios.space_miner import run
from tools.map_run import _infer_scenario, _read_events, build_checkpoints, render_html


def _orion_moves(events: list[dict]) -> list[dict]:
    return [
        ev for ev in events
        if ev.get("kind") == "action_completed"
        and ev.get("kind_detail") == "move_actor_arrive"
        and ev.get("actor") == "cmd_orion"
    ]


def test_space_miner_core_mechanics_hold_across_seeds(tmp_path) -> None:
    """Core economy / defense / mobility must show up in *every* run, not one
    lucky seed. The t=190 recall to Homeworld rides a courier through a lossy
    bus, so it is only required to land in most seeds, not all.
    """
    seeds = range(1, 6)
    recalled = 0
    for seed in seeds:
        base = run(seed=seed, ticks=230, runs_dir=tmp_path / f"s{seed}")
        events = _read_events(base.with_suffix(".jsonl"))
        kinds = {str(ev["kind"]) for ev in events}

        assert {"mining", "consumption", "alien_contact", "defense"} <= kinds, seed
        assert any(
            ev["kind"] == "action_started"
            and ev.get("kind_detail") in {"ore_tax", "manager_tax"}
            for ev in events
        ), f"expected tax flows (seed {seed})"

        moves = _orion_moves(events)
        assert moves, f"orion should be mobile (seed {seed})"
        # The forward leg to Europa happens well before the lossy recall and
        # lands reliably across seeds.
        assert any(ev.get("target_location") == "Europa Station" for ev in moves), seed
        if any(ev.get("assigned_commander") == "ceo" for ev in moves):
            recalled += 1

    assert recalled >= 3, f"recall only landed in {recalled}/{len(list(seeds))} seeds"


def test_space_miner_map_replays_mobile_commander(tmp_path) -> None:
    """The replay tool must reconstruct a mobile commander's final post from the
    log alone — whatever it is for this particular run. This tests map_run, not
    a specific seed's narrative, so it does not depend on the recall succeeding.
    """
    base = run(seed=2, ticks=230, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")
    events = _read_events(jsonl_path)
    scenario = _infer_scenario(jsonl_path)
    checkpoints = build_checkpoints(events, scenario)
    html = render_html(checkpoints, jsonl_path)

    assert scenario == "space_miner"
    assert "Director Vale" in html and "Orion Dray" in html

    moves = _orion_moves(events)
    assert moves, "expected orion to move at least once"
    last = moves[-1]
    final = checkpoints[-1].state.actors["cmd_orion"]
    assert final.location == last["target_location"]
    if last.get("assigned_commander") is not None:
        assert final.commander == last["assigned_commander"]

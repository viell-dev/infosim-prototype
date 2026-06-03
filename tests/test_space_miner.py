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
    """Split into what is *universal* vs *usually true*, measured over a seed
    sweep (a 100-seed probe informed these rates):

      - Economy/defense (mining, consumption, alien_contact, defense) and tax
        flows appear in EVERY run — asserted per seed.
      - Commander mobility is courier- and survival-dependent (couriers drop on
        a lossy bus; a commander can be dismissed mid-mission), so the move /
        Europa-leg / Homeworld-recall outcomes are only required to hold in the
        large majority of seeds, not every one.
    """
    seeds = range(1, 13)
    n = len(seeds)
    moved = europa = recalled = 0
    for seed in seeds:
        base = run(seed=seed, ticks=230, runs_dir=tmp_path / f"s{seed}")
        events = _read_events(base.with_suffix(".jsonl"))
        kinds = {str(ev["kind"]) for ev in events}

        # Universal — must hold for every seed.
        assert {"mining", "consumption", "alien_contact", "defense"} <= kinds, seed
        assert any(
            ev["kind"] == "action_started"
            and ev.get("kind_detail") in {"ore_tax", "manager_tax"}
            for ev in events
        ), f"expected tax flows (seed {seed})"

        moves = _orion_moves(events)
        moved += bool(moves)
        europa += any(ev.get("target_location") == "Europa Station" for ev in moves)
        recalled += any(ev.get("assigned_commander") == "ceo" for ev in moves)

    # Usually true — thresholds sit well under the observed rates (~96% moved,
    # ~86% Europa, ~79% recall) with margin for between-window variance, so the
    # test confirms the mobility machinery executes without being seed-fragile.
    assert moved >= (n * 3) // 4, f"orion moved in only {moved}/{n} seeds"
    assert europa >= n // 3, f"reached Europa in only {europa}/{n} seeds"
    assert recalled >= n // 4, f"recall landed in only {recalled}/{n} seeds"


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

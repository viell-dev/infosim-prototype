from __future__ import annotations

import sys
from pathlib import Path

from infosim.scenarios.isekai_kingdom import (
    CAPITAL,
    NORTH_PORT,
    REGIONS,
    SOUTH_PORT,
    _col,
    _connected,
    _mayor_id,
    _row,
    generate,
    run,
    undeveloped_probability,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.map_run import _infer_scenario, _infer_seed, _read_events, build_checkpoints


def test_kingdom_generation_honors_map_and_ownership_constraints() -> None:
    setup = generate(seed=11)

    assert set(setup.regions) == set(REGIONS)
    assert setup.regions[CAPITAL].owner_id == "king"
    assert setup.king_second_region != CAPITAL
    assert setup.regions[setup.king_second_region].owner_id == "king"
    assert not _connected(setup.king_second_region, CAPITAL)
    assert _row(setup.king_second_region) != 1
    assert _col(setup.king_second_region) != "A"
    assert setup.regions[setup.king_second_region].geography["coast"] > 0.0

    assert 0 <= sum(1 for noble in setup.nobles.values() if noble.is_royal) <= 2
    assert all(noble.holdings for noble in setup.nobles.values())
    assert {r.coord for r in setup.regions.values() if r.owner_id == "king"} == {
        CAPITAL,
        setup.king_second_region,
    }

    assert setup.regions[NORTH_PORT].developed
    assert setup.regions[SOUTH_PORT].developed
    assert all(
        setup.regions[coord].developed
        for coord in (CAPITAL, setup.king_second_region)
    )

    eligible = [
        region for region in setup.regions.values()
        if region.owner_id != "king" and region.coord not in {NORTH_PORT, SOUTH_PORT}
    ]
    assert eligible
    assert all(region.undeveloped_chance > 0.0 for region in eligible)
    assert undeveloped_probability(1) < undeveloped_probability(3) < undeveloped_probability(6)


def test_kingdom_run_emits_setup_economy_politics_and_shocks(tmp_path) -> None:
    base = run(seed=1, ticks=130, runs_dir=tmp_path)
    events = _read_events(base.with_suffix(".jsonl"))
    kinds = {str(ev["kind"]) for ev in events}

    assert {
        "scenario_setup",
        "noble_setup",
        "region_setup",
        "observation",
        "dispatch",
        "receive",
        "mining",
        "consumption",
        "action_started",
        "action_completed",
        "true_state_change",
        "final_snapshot",
    } <= kinds
    assert any(ev["kind"] == "report_forged" for ev in events)
    assert any(ev["kind"] == "skim" for ev in events)
    assert any(
        ev["kind"] == "action_started" and "tax" in str(ev.get("kind_detail"))
        for ev in events
    )
    assert any(
        ev["kind"] == "true_state_change"
        and ev.get("cause") in {"coastal granary fire", "mine tunnel breach"}
        for ev in events
    )


def test_kingdom_map_replay_uses_seeded_initial_state(tmp_path) -> None:
    base = run(seed=3, ticks=90, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")
    events = _read_events(jsonl_path)

    scenario = _infer_scenario(jsonl_path)
    seed = _infer_seed(jsonl_path)
    checkpoints = build_checkpoints(events, scenario, seed=seed)
    start_state = checkpoints[0].state

    setup = generate(seed=3)
    assert scenario == "isekai_kingdom"
    assert seed == 3
    assert set(start_state.actors) == set(setup.actors)
    second = setup.king_second_region
    assert start_state.actors[_mayor_id(second)].commander == "crown_demesne"

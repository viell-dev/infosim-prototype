from __future__ import annotations

import sys
from pathlib import Path

from infosim.scenarios.frontier import run

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.map_run import build_checkpoints, render_html, _read_events


def test_map_run_renders_checkpoints_and_replacement_lineage(tmp_path) -> None:
    base = run(seed=1, ticks=80, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")

    events = _read_events(jsonl_path)
    checkpoints = build_checkpoints(events, "frontier")
    html = render_html(checkpoints, jsonl_path)

    assert [checkpoint.label for checkpoint in checkpoints] == [
        "Start",
        "25%",
        "50%",
        "75%",
        "End",
    ]
    assert "Self known" in html
    assert "King known" in html
    assert "c</strong> is confidence" in html
    assert "t</strong> is the simulation time" in html
    assert "via</strong> is the source chain" in html
    assert "Aldric Vale" in html
    assert "Office: Mira of Halen -&gt; Iselle Marn" in html


def test_map_run_renders_vacant_offices_after_candidate_pool_exhaustion(tmp_path) -> None:
    base = run(seed=1, ticks=200, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")

    events = _read_events(jsonl_path)
    regencies = [ev for ev in events if ev["kind"] == "regency_started"]
    assert regencies, "expected at least one office to fall vacant by t=200"

    checkpoints = build_checkpoints(events, "frontier")
    html = render_html(checkpoints, jsonl_path)
    end_state = checkpoints[-1].state

    office_id = str(regencies[0]["actor"])
    office = end_state.actors[office_id]
    # The office is a stable node: it persists, now vacant under its regent...
    assert office.active
    assert office.vacant
    assert office.regent == regencies[0]["regent"]
    # ...and its subordinates still point at it (never rewired to the regent).
    subs = [a for a in end_state.actors.values() if a.commander == office_id]
    assert subs, "a vacant office should keep its subordinates"
    assert "Vacant — governed by" in html

from __future__ import annotations

from infosim.scenarios.frontier import run
from tools.visualizer import EventIndex, ReplayStore


def test_visualizer_indexes_and_serves_frame_windows(tmp_path) -> None:
    base = run(seed=1, ticks=80, runs_dir=tmp_path)
    jsonl_path = base.with_suffix(".jsonl")
    index = EventIndex(jsonl_path)
    try:
        store = ReplayStore(index, "frontier", seed=1)

        assert len(index.records) > 0
        assert index.event_times
        assert index.choice_times
        assert index.seek_time(0.0, mode="event", direction="next") > 0.0

        frame = store.frame_at(40.0, window=8.0, max_stats=2)

        assert frame["eventCount"] == len(index.records)
        assert frame["time"] == 40.0
        assert len(frame["state"]["statsSchema"]) <= 2
        assert frame["state"]["actors"]
        assert all(
            len(actor["stats"]) <= 2
            for actor in frame["state"]["actors"]
        )
        assert frame["events"]
    finally:
        index.close()

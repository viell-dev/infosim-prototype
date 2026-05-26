from __future__ import annotations

import hashlib
from pathlib import Path

from infosim.scenarios.frontier import run


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_seed_same_jsonl(tmp_path: Path) -> None:
    a = run(seed=42, ticks=100, runs_dir=tmp_path / "a")
    b = run(seed=42, ticks=100, runs_dir=tmp_path / "b")
    assert _hash(a.with_suffix(".jsonl")) == _hash(b.with_suffix(".jsonl"))


def test_different_seed_different_jsonl(tmp_path: Path) -> None:
    a = run(seed=1, ticks=100, runs_dir=tmp_path / "a")
    b = run(seed=2, ticks=100, runs_dir=tmp_path / "b")
    assert _hash(a.with_suffix(".jsonl")) != _hash(b.with_suffix(".jsonl"))

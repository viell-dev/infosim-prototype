from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO


@dataclass
class EventLog:
    """Dual-sink event logger: JSONL (machine) + human-readable text."""
    jsonl_path: Path
    human_path: Path
    _jsonl_fp: TextIO | None = None
    _human_fp: TextIO | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def open(self) -> None:
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._jsonl_fp = self.jsonl_path.open("w", encoding="utf-8")
        self._human_fp = self.human_path.open("w", encoding="utf-8")

    def close(self) -> None:
        if self._jsonl_fp:
            self._jsonl_fp.close()
        if self._human_fp:
            self._human_fp.close()

    def emit(self, tick: int, kind: str, human: str, **fields: Any) -> None:
        event = {"tick": tick, "kind": kind, **fields}
        self.events.append(event)
        if self._jsonl_fp:
            self._jsonl_fp.write(json.dumps(event, sort_keys=True) + "\n")
        line = f"t={tick:04d}  {human}\n"
        if self._human_fp:
            self._human_fp.write(line)

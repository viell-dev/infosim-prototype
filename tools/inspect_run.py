#!/usr/bin/env python3
"""Quick filter over a run's JSONL event stream.

Examples:
    python3 tools/inspect_run.py runs/frontier-seed1-*.jsonl --actor king
    python3 tools/inspect_run.py runs/frontier-seed1-*.jsonl --region Frontier
    python3 tools/inspect_run.py runs/frontier-seed1-*.jsonl --kind dispatch
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--actor")
    p.add_argument("--region")
    p.add_argument("--kind")
    p.add_argument("--subject")
    p.add_argument("--from-time", type=float, default=None)
    p.add_argument("--to-time", type=float, default=None)
    args = p.parse_args()

    if not args.path.exists():
        print(f"no such file: {args.path}", file=sys.stderr)
        sys.exit(1)

    with args.path.open() as fp:
        for line in fp:
            ev = json.loads(line)
            if args.actor and args.actor not in (
                ev.get("actor"), ev.get("sender"), ev.get("recipient")
            ):
                continue
            if args.region and ev.get("region") != args.region:
                continue
            if args.kind and ev.get("kind") != args.kind:
                continue
            if args.subject and ev.get("subject") != args.subject:
                continue
            t = ev.get("time")
            if args.from_time is not None and t is not None and t < args.from_time:
                continue
            if args.to_time is not None and t is not None and t > args.to_time:
                continue
            print(json.dumps(ev, sort_keys=True))


if __name__ == "__main__":
    main()

"""Minimal stdlib-only test runner so we don't depend on pytest.

Discovers `test_*` functions in `tests/test_*.py`, supplies a `tmp_path` if the
function asks for it, and reports pass/fail.

Usage:
    PYTHONPATH=src python3 tests/_runner.py
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
import traceback
from pathlib import Path


def _load(module_path: Path):
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent
    sys.path.insert(0, str(repo_root / "src"))

    files = sorted(tests_dir.glob("test_*.py"))
    failures: list[tuple[str, str]] = []
    total = 0
    for f in files:
        mod = _load(f)
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            total += 1
            params = inspect.signature(fn).parameters
            kwargs = {}
            tmp_ctx = None
            if "tmp_path" in params:
                tmp_ctx = tempfile.TemporaryDirectory()
                kwargs["tmp_path"] = Path(tmp_ctx.name)
            try:
                fn(**kwargs)
                print(f"PASS  {f.stem}::{name}")
            except Exception:
                tb = traceback.format_exc()
                failures.append((f"{f.stem}::{name}", tb))
                print(f"FAIL  {f.stem}::{name}")
            finally:
                if tmp_ctx is not None:
                    tmp_ctx.cleanup()

    print()
    if failures:
        for name, tb in failures:
            print(f"--- {name} ---")
            print(tb)
        print(f"{len(failures)} of {total} failed")
        return 1
    print(f"All {total} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

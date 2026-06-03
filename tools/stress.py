"""Stress-dial sweep: how does the system behave at parameter extremes?

Runs the scenario under several preset profiles (pristine → broken) and
prints a comparison table. Tells us whether the dynamics are tuned in a
sensitive range or whether the current "default" sits on a cliff edge.

Each profile mutates:
  - bus_loss_prob and bus_jitter_frac (courier reliability)
  - integrity_scale: 0 = everyone perfect (loyalty/honesty → 1, fear → 0);
                     1 = scenario default (no mutation);
                     >1 = amplify the gap from perfect.

Usage:
    PYTHONPATH=src python3 tools/stress.py --seeds 50 --ticks 300
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from infosim.actors import Traits  # noqa: E402
from infosim.logging_setup import EventLog  # noqa: E402
from infosim.scenarios.frontier import (  # noqa: E402
    RULESET,
    build,
    candidate_pool,
    scripted_events,
)
from infosim.sim import Simulation  # noqa: E402


@dataclass(frozen=True)
class Profile:
    name: str
    loss: float
    jitter: float
    integrity: float  # 0=perfect, 1=default, >1=amplified
    note: str


PROFILES = (
    Profile("pristine", loss=0.00, jitter=0.00, integrity=0.0,
            note="everyone honest+loyal, perfect couriers"),
    Profile("low",      loss=0.02, jitter=0.10, integrity=0.5,
            note="trait gaps halved, light loss"),
    Profile("default",  loss=0.08, jitter=0.25, integrity=1.0,
            note="scenario defaults"),
    Profile("high",     loss=0.20, jitter=0.40, integrity=1.5,
            note="trait gaps 1.5x, heavy loss"),
    Profile("broken",   loss=0.40, jitter=0.60, integrity=2.5,
            note="trait gaps 2.5x, half of couriers lost"),
)


def _scale_traits(t: Traits, integrity: float) -> Traits:
    """Mutate a Traits dataclass toward perfect (integrity=0) or worse
    (integrity>1). Positive traits (loyalty, honesty) approach 1 as
    integrity → 0; negative (fear) approaches 0. Default ambition is
    intentionally left untouched — it isn't a moral axis.
    """
    def toward_perfect(default: float, perfect: float) -> float:
        gap = perfect - default
        return max(0.0, min(1.0, default + gap * (1.0 - integrity)))

    return replace(
        t,
        loyalty=toward_perfect(t.loyalty, 1.0),
        honesty=toward_perfect(t.honesty, 1.0),
        fear=toward_perfect(t.fear, 0.0),
    )


def _null_log() -> EventLog:
    devnull = Path("/dev/null")
    return EventLog(jsonl_path=devnull, human_path=devnull)


def run_one(seed: int, ticks: int, profile: Profile) -> dict:
    rng = random.Random(seed)
    world, actors = build()
    for a in actors.values():
        a.traits = _scale_traits(a.traits, profile.integrity)
    log = _null_log()
    sim = Simulation(
        world=world, actors=actors, rng=rng, event_log=log,
        ruleset=RULESET,
        candidate_pool=candidate_pool(),
        bus_loss_prob=profile.loss, bus_jitter_frac=profile.jitter,
    )
    scripted_events(sim)
    sim.run_until(float(ticks))

    king = actors["king"]
    out = {"counts": {"report_forged": 0, "skim": 0, "dismissed": 0,
                      "courier_lost": 0, "urgent_report": 0}}
    for ev in log.events:
        if ev["kind"] in out["counts"]:
            out["counts"][ev["kind"]] += 1

    out["beliefs"] = {}
    for a in actors.values():
        for stat, truth in a.stats.items():
            subj = Simulation.subject_for(a.id, stat)
            belief = king.known.get(subj)
            out["beliefs"][subj] = {
                "truth": float(truth),
                "belief": belief.value if belief else None,
            }
    return out


def _signed_pct(truth: float, belief: float | None) -> float | None:
    if belief is None or truth == 0:
        return None
    return (belief - truth) / abs(truth) * 100.0


def _stat(values: list[float]) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    return statistics.fmean(values), statistics.fmean(abs(v) for v in values)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=50)
    p.add_argument("--ticks", type=int, default=300)
    p.add_argument("--seed-start", type=int, default=1)
    args = p.parse_args()

    # Two parallel subjects to highlight the comparison.
    compare_subjects = (
        "cmd_aldric.garrison_strength",
        "cmd_talen.garrison_strength",
        "cmd_aldric.food_stores",
        "cmd_talen.food_stores",
        "cmd_aldric.unrest",
        "cmd_talen.unrest",
    )

    print(f"\n=== Stress dial: {len(PROFILES)} profiles × "
          f"{args.seeds} seeds × {args.ticks} ticks ===\n")

    results: dict[str, dict[str, list[float]]] = {p.name: {} for p in PROFILES}
    counts: dict[str, dict[str, list[int]]] = {p.name: {} for p in PROFILES}

    for prof in PROFILES:
        per_subject: dict[str, list[float]] = {s: [] for s in compare_subjects}
        per_count: dict[str, list[int]] = {}
        for i in range(args.seeds):
            r = run_one(args.seed_start + i, args.ticks, prof)
            for s in compare_subjects:
                row = r["beliefs"].get(s)
                if row is None:
                    continue
                err = _signed_pct(row["truth"], row["belief"])
                if err is not None:
                    per_subject[s].append(err)
            for k, v in r["counts"].items():
                per_count.setdefault(k, []).append(v)
        results[prof.name] = per_subject
        counts[prof.name] = per_count

    print(f"{'profile':10s}  {'loss':>5s}  {'jit':>4s}  {'integ':>5s}  note")
    for prof in PROFILES:
        print(f"{prof.name:10s}  {prof.loss:>5.2f}  {prof.jitter:>4.2f}  "
              f"{prof.integrity:>5.2f}  {prof.note}")

    print("\nKing's belief vs truth — signed mean % error  /  mean |error|:\n")
    header = f"{'subject':30s}"
    for prof in PROFILES:
        header += f"  {prof.name:>14s}"
    print(header)
    for s in compare_subjects:
        row = f"{s:30s}"
        for prof in PROFILES:
            vals = results[prof.name][s]
            mean, abs_mean = _stat(vals)
            row += f"  {mean:>+6.1f}/{abs_mean:>5.1f}"
        print(row)

    print("\nEvent counts (mean per seed):\n")
    kinds = ("report_forged", "skim", "dismissed", "courier_lost", "urgent_report")
    header = f"{'kind':20s}"
    for prof in PROFILES:
        header += f"  {prof.name:>10s}"
    print(header)
    for k in kinds:
        row = f"{k:20s}"
        for prof in PROFILES:
            vs = counts[prof.name].get(k, [])
            mean = statistics.fmean(vs) if vs else 0.0
            row += f"  {mean:>10.1f}"
        print(row)


if __name__ == "__main__":
    main()

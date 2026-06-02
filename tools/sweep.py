"""Multi-seed sweep of the Frontier scenario.

Runs N seeds end-to-end (in-memory event log, no files written) and aggregates:

  - per (region, variable): King's final belief vs truth — signed % error,
    distribution across seeds.
  - counts per seed: forgeries, skims, dismissals, lost couriers, undeliverable
    couriers, urgent autonomous reports, orders dispatched, actions completed.

The point is to find out whether the dramatic single-seed narratives we have
been reading are typical or lucky, before we commit to a language port.

Usage:
    PYTHONPATH=src python3 tools/sweep.py --seeds 100 --ticks 300
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from infosim.logging_setup import EventLog  # noqa: E402
from infosim.scenarios.frontier import (  # noqa: E402
    build,
    candidate_pool,
    scripted_events,
)
from infosim.sim import Simulation  # noqa: E402


COUNT_KINDS = (
    "report_forged",
    "skim",
    "dismissed",
    "appointed",
    "courier_lost",
    "courier_undeliverable",
    "urgent_report",
    "order_dispatched",
    "action_completed",
)


def _null_log() -> EventLog:
    """An EventLog that keeps events in memory but writes no files."""
    devnull = Path("/dev/null")
    log = EventLog(jsonl_path=devnull, human_path=devnull)
    # Don't call .open() — keep _jsonl_fp and _human_fp as None so emit()
    # appends to .events but writes nothing.
    return log


def run_one(seed: int, ticks: int) -> dict:
    rng = random.Random(seed)
    world, actors = build()
    log = _null_log()
    sim = Simulation(
        world=world, actors=actors, rng=rng, event_log=log,
        candidate_pool=candidate_pool(),
        bus_loss_prob=0.08, bus_jitter_frac=0.25,
    )
    scripted_events(sim)
    sim.run_until(float(ticks))

    king = actors["king"]
    truth_vs_belief: dict[str, dict[str, float | None]] = {}
    for region in world.regions.values():
        for var, true_value in region.state.items():
            subj = Simulation.subject_for(region.name, var)
            belief = king.known.get(subj)
            truth_vs_belief[subj] = {
                "truth": float(true_value),
                "belief": (belief.value if belief else None),
                "belief_age": (sim.now - belief.last_updated_time) if belief else None,
            }

    counts = {k: 0 for k in COUNT_KINDS}
    for ev in log.events:
        if ev["kind"] in counts:
            counts[ev["kind"]] += 1

    return {
        "seed": seed,
        "now": sim.now,
        "truth_vs_belief": truth_vs_belief,
        "counts": counts,
    }


def _signed_pct_error(truth: float, belief: float) -> float | None:
    """Belief vs truth as signed % of truth. +20 = belief is 20% above truth."""
    if truth == 0:
        # Use absolute error when truth is zero — % undefined.
        return None
    return (belief - truth) / abs(truth) * 100.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _fmt(x: float) -> str:
    if math.isnan(x):
        return "  —  "
    return f"{x:+7.1f}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=100)
    p.add_argument("--ticks", type=int, default=300)
    p.add_argument("--seed-start", type=int, default=1)
    args = p.parse_args()

    runs = [run_one(args.seed_start + i, args.ticks) for i in range(args.seeds)]

    # --- Divergence per (region, variable) -------------------------------
    subjects = sorted(runs[0]["truth_vs_belief"].keys())
    print(f"\n=== Frontier sweep: {args.seeds} seeds × {args.ticks} ticks ===\n")
    print("King's belief vs truth (signed % error, end-of-run):")
    print(f"{'subject':38s}  {'mean':>7}  {'med':>7}  {'p10':>7}  {'p90':>7}  "
          f"{'|mean|':>7}  {'n/a':>4}")
    for subj in subjects:
        errs = []
        zero_truths = 0
        no_belief = 0
        for r in runs:
            row = r["truth_vs_belief"][subj]
            if row["belief"] is None:
                no_belief += 1
                continue
            err = _signed_pct_error(row["truth"], row["belief"])
            if err is None:
                zero_truths += 1
                continue
            errs.append(err)
        if errs:
            mean = statistics.fmean(errs)
            med = statistics.median(errs)
            p10 = _percentile(errs, 0.10)
            p90 = _percentile(errs, 0.90)
            abs_mean = statistics.fmean(abs(e) for e in errs)
        else:
            mean = med = p10 = p90 = abs_mean = math.nan
        n_na = zero_truths + no_belief
        print(f"{subj:38s}  {_fmt(mean)}  {_fmt(med)}  {_fmt(p10)}  {_fmt(p90)}  "
              f"{_fmt(abs_mean)}  {n_na:4d}")
    print("\n  n/a = seeds where King had no belief or truth was 0 "
          "(% error undefined).")

    # --- Event counts ----------------------------------------------------
    print("\nEvent counts per seed:")
    print(f"{'kind':30s}  {'mean':>7}  {'med':>5}  {'min':>5}  {'max':>5}  "
          f"{'seeds≥1':>7}")
    for k in COUNT_KINDS:
        vals = [r["counts"][k] for r in runs]
        nz = sum(1 for v in vals if v > 0)
        print(f"{k:30s}  {statistics.fmean(vals):7.1f}  "
              f"{int(statistics.median(vals)):5d}  "
              f"{min(vals):5d}  {max(vals):5d}  {nz:7d}")

    # --- Narrative-interestingness heuristic -----------------------------
    print("\nNarrative interestingness per seed:")
    interesting = 0
    pure_silent = 0
    for r in runs:
        c = r["counts"]
        had_forgery = c["report_forged"] > 0
        had_dismissal = c["dismissed"] > 0
        had_skim = c["skim"] > 0
        large_divergence = False
        for subj, row in r["truth_vs_belief"].items():
            if row["belief"] is None or row["truth"] == 0:
                continue
            if abs(_signed_pct_error(row["truth"], row["belief"])) >= 25.0:
                large_divergence = True
                break
        if had_forgery and (had_dismissal or large_divergence or had_skim):
            interesting += 1
        if not (had_forgery or had_dismissal or had_skim or large_divergence):
            pure_silent += 1
    print(f"  {interesting}/{args.seeds} seeds had forgery AND "
          "(dismissal OR ≥25% divergence OR skim)")
    print(f"  {pure_silent}/{args.seeds} seeds had no forgery, no skim, no "
          "dismissal, and no ≥25% divergence")


if __name__ == "__main__":
    main()

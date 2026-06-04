#!/usr/bin/env python3
"""Serve an on-demand run visualizer for an InfoSim JSONL file.

Unlike ``tools/map_run.py``, this does not generate a giant self-contained HTML
artifact. The JSONL stays on disk, the server builds a light event index, and
the browser requests the current state plus a small event window as the user
slides through time.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

try:
    from tools.map_run import (  # type: ignore  # noqa: E402
        CHECKPOINTS,
        CHOICE_EVENT_KINDS,
        Progress,
        ReplayState,
        _actor_sort_key,
        _apply_event,
        _copy_state,
        _event_summary,
        _event_time,
        _infer_scenario,
        _infer_seed,
        _initial_state,
        _sample_evenly,
    )
except ModuleNotFoundError:
    from map_run import (  # type: ignore  # noqa: E402
        CHECKPOINTS,
        CHOICE_EVENT_KINDS,
        Progress,
        ReplayState,
        _actor_sort_key,
        _apply_event,
        _copy_state,
        _event_summary,
        _event_time,
        _infer_scenario,
        _infer_seed,
        _initial_state,
        _sample_evenly,
    )


DEFAULT_WINDOW = 10.0
DEFAULT_MAX_STATS = 12
REPLAY_CACHE_STRIDE = 25_000
MAX_REPLAY_CACHES = 10


@dataclass(frozen=True)
class EventRecord:
    index: int
    offset: int
    time: float
    kind: str


class EventIndex:
    def __init__(self, path: Path, progress: Progress | None = None) -> None:
        self.path = path
        self.records: list[EventRecord] = []
        self.times: list[float] = []
        self.event_times: list[float] = []
        self.choice_times: list[float] = []
        self.kind_counts: dict[str, int] = {}
        self._build(progress)
        self._fp = self.path.open("rb")

    def close(self) -> None:
        self._fp.close()

    @property
    def start_time(self) -> float:
        return self.times[0] if self.times else 0.0

    @property
    def end_time(self) -> float:
        return self.times[-1] if self.times else 0.0

    @property
    def checkpoint_times(self) -> list[float]:
        return [self.end_time * fraction for _label, fraction in CHECKPOINTS]

    def _build(self, progress: Progress | None) -> None:
        unique_event_times: set[float] = set()
        unique_choice_times: set[float] = set()
        with self.path.open("rb") as fp:
            while True:
                offset = fp.tell()
                line = fp.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                event = json.loads(line)
                time_value = _event_time(event)
                kind = str(event.get("kind", "event"))
                index = len(self.records)
                self.records.append(EventRecord(index, offset, time_value, kind))
                self.times.append(time_value)
                self.kind_counts[kind] = self.kind_counts.get(kind, 0) + 1
                if kind != "observation":
                    unique_event_times.add(time_value)
                if kind in CHOICE_EVENT_KINDS:
                    unique_choice_times.add(time_value)
                if progress is not None:
                    progress.update("Indexing events", len(self.records))
        self.event_times = sorted(unique_event_times)
        self.choice_times = sorted(unique_choice_times)
        if progress is not None:
            progress.done("Indexing events", len(self.records))

    def event_at(self, index: int) -> dict[str, Any]:
        record = self.records[index]
        self._fp.seek(record.offset)
        return json.loads(self._fp.readline())

    def position_for_time(self, time_value: float) -> int:
        return bisect.bisect_right(self.times, time_value)

    def events_between(self, start: float, end: float, limit: int = 240) -> list[dict[str, Any]]:
        left = bisect.bisect_left(self.times, start)
        right = bisect.bisect_right(self.times, end)
        indexes = list(range(left, right))
        if limit > 0 and len(indexes) > limit:
            indexes = sorted(_sample_evenly([float(i) for i in indexes], limit))
            return [self.event_at(int(i)) for i in indexes]
        return [self.event_at(i) for i in indexes]

    def seek_time(self, current: float, mode: str, direction: str) -> float:
        if mode == "checkpoint":
            times = self.checkpoint_times
        elif mode == "choice":
            times = self.choice_times
        else:
            times = self.event_times
        if not times:
            return current
        if direction == "prev":
            index = bisect.bisect_left(times, current) - 1
            return times[max(0, index)]
        index = bisect.bisect_right(times, current)
        return times[min(len(times) - 1, index)]


class ReplayStore:
    def __init__(self, index: EventIndex, scenario: str, seed: int | None) -> None:
        self.index = index
        self.scenario = scenario
        self.seed = seed
        self._lock = threading.Lock()
        initial = _initial_state(scenario, seed=seed)
        self._state = initial
        self._position = 0
        self._cache: list[tuple[int, ReplayState]] = [(0, _copy_state(initial))]

    def frame_at(
        self,
        time_value: float,
        window: float = DEFAULT_WINDOW,
        max_stats: int = DEFAULT_MAX_STATS,
    ) -> dict[str, Any]:
        target = max(self.index.start_time, min(self.index.end_time, time_value))
        with self._lock:
            self._replay_to(target)
            state = _copy_state(self._state)
        events = self.index.events_between(target - window / 2.0, target + window / 2.0)
        summaries = [
            {
                "time": _event_time(event),
                "kind": str(event.get("kind", "event")),
                "summary": _event_summary(event, state),
            }
            for event in events
            if event.get("kind") != "observation"
        ]
        return {
            "time": target,
            "position": self.index.position_for_time(target),
            "eventCount": len(self.index.records),
            "events": summaries,
            "state": _state_payload(state, max_stats=max_stats),
        }

    def _replay_to(self, time_value: float) -> None:
        target_position = self.index.position_for_time(time_value)
        if target_position < self._position:
            cache_position, cache_state = max(
                (item for item in self._cache if item[0] <= target_position),
                key=lambda item: item[0],
            )
            self._state = _copy_state(cache_state)
            self._position = cache_position

        while self._position < target_position:
            _apply_event(self._state, self.index.event_at(self._position))
            self._position += 1

        nearest_cache = max(pos for pos, _state in self._cache if pos <= self._position)
        if self._position - nearest_cache >= REPLAY_CACHE_STRIDE:
            self._cache.append((self._position, _copy_state(self._state)))
            if len(self._cache) > MAX_REPLAY_CACHES:
                # Keep the initial reset point and the most recent sparse checkpoints.
                self._cache = [self._cache[0], *self._cache[-(MAX_REPLAY_CACHES - 1):]]


def _selected_stats(state: ReplayState, max_stats: int) -> list[str]:
    counts: dict[str, int] = {}
    for actor in state.actors.values():
        for stat in actor.stats:
            counts[stat] = counts.get(stat, 0) + 1
    stats = sorted(counts, key=lambda stat: (-counts[stat], stat))
    if max_stats > 0:
        stats = stats[:max_stats]
    return sorted(stats)


def _state_payload(state: ReplayState, max_stats: int) -> dict[str, Any]:
    stats_schema = _selected_stats(state, max_stats)
    selected_stats = set(stats_schema)
    roots = [
        actor
        for actor in state.actors.values()
        if actor.active and actor.commander is None
    ]
    apex_id = "king" if "king" in state.actors else "ceo" if "ceo" in state.actors else None
    if apex_id is None and roots:
        apex_id = sorted(roots, key=_actor_sort_key)[0].id

    def displayed_known(actor_id: str, known: dict[str, Any]) -> dict[str, Any]:
        if actor_id == apex_id:
            allowed_subjects = {
                f"{other.id}.{stat}"
                for other in state.actors.values()
                for stat in selected_stats
            }
        else:
            allowed_subjects = {f"{actor_id}.{stat}" for stat in selected_stats}
        return {
            subject: {
                "value": belief.value,
                "confidence": belief.confidence,
                "updatedAt": belief.updated_at,
                "sourceChain": belief.source_chain,
            }
            for subject, belief in known.items()
            if subject in allowed_subjects
        }

    return {
        "statsSchema": stats_schema,
        "actors": [
            {
                "id": actor.id,
                "displayName": actor.display_name,
                "title": actor.title,
                "location": actor.location,
                "commander": actor.commander,
                "stats": {
                    stat: value
                    for stat, value in actor.stats.items()
                    if stat in selected_stats
                },
                "known": displayed_known(actor.id, actor.known),
                "active": actor.active,
                "vacant": actor.vacant,
                "regent": actor.regent,
                "regentName": actor.regent_name,
                "lineage": state.office_lineages.get(actor.id, []),
            }
            for actor in sorted(state.actors.values(), key=_actor_sort_key)
        ],
    }


def _html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InfoSim Visualizer</title>
<style>
body { margin: 0; font-family: system-ui, sans-serif; background: #f6f6f4; color: #171717; }
header { position: sticky; top: 0; z-index: 2; background: #fffffb; border-bottom: 1px solid #c9c6bd; padding: 12px 16px; }
h1 { margin: 0; font-size: 22px; }
h2 { margin: 0 0 8px; font-size: 17px; }
button, input { font: inherit; }
button { border: 1px solid #aaa; border-radius: 4px; background: #fff; padding: 5px 8px; cursor: pointer; }
button:hover { background: #f0f0ed; }
.source, .meta, .muted, .conf, .chain, #status { color: #66615a; font-size: 12px; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
#timeSlider { min-width: 260px; flex: 1 1 440px; }
#timeInput, #windowInput, #statsInput { width: 78px; }
main { display: grid; grid-template-columns: minmax(300px, 34%) minmax(620px, 1fr); gap: 16px; padding: 16px; }
.event { border-bottom: 1px solid #e3e0d8; padding: 7px 0; }
.event-kind { color: #65513b; font-size: 11px; text-transform: uppercase; }
.state { min-width: 0; overflow-x: auto; }
.actor { min-width: 680px; border-left: 2px solid #8c8678; margin: 8px 0 0; padding-left: 10px; background: #fffffb; }
.actor-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.lineage { color: #7a4a00; font-size: 12px; margin-bottom: 4px; }
.children { margin-left: 24px; padding-left: 10px; border-left: 1px dotted #bbb; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 6px; }
th, td { border-top: 1px solid #ddd; padding: 4px 6px; text-align: left; vertical-align: top; }
th { width: 22%; }
td { width: 26%; }
.chain { overflow-wrap: anywhere; }
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>InfoSim Visualizer</h1>
  <div id="source" class="source"></div>
  <div class="row">
    <button data-seek="prev:checkpoint">Prev checkpoint</button>
    <button data-seek="prev:choice">Prev choice</button>
    <button data-seek="prev:event">Prev event</button>
    <input id="timeSlider" type="range" value="0" min="0" max="1" step="0.1">
    <button data-seek="next:event">Next event</button>
    <button data-seek="next:choice">Next choice</button>
    <button data-seek="next:checkpoint">Next checkpoint</button>
  </div>
  <div class="row">
    <label>t <input id="timeInput" type="number" step="0.1"></label>
    <label>window <input id="windowInput" type="number" value="10" min="1" step="1"></label>
    <label>stats <input id="statsInput" type="number" value="12" min="0" step="1"></label>
    <span id="status"></span>
  </div>
</header>
<main>
  <section>
    <h2>Event Window</h2>
    <div id="events"></div>
  </section>
  <section class="state">
    <h2>State</h2>
    <div id="state"></div>
  </section>
</main>
<script>
const source = document.getElementById("source");
const statusEl = document.getElementById("status");
const slider = document.getElementById("timeSlider");
const timeInput = document.getElementById("timeInput");
const windowInput = document.getElementById("windowInput");
const statsInput = document.getElementById("statsInput");
const eventsRoot = document.getElementById("events");
const stateRoot = document.getElementById("state");
let meta = null;
let currentTime = 0;
let pending = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

function fmt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  if (Math.abs(n) < 0.5) return "0";
  return n.toFixed(0);
}

function fmtTime(value) {
  const n = Number(value ?? 0);
  return Math.abs(n - Math.round(n)) < 0.01 ? String(Math.round(n)) : n.toFixed(2);
}

function actorSort(a, b) {
  return `${a.location}\u0000${a.title}\u0000${a.displayName}`
    .localeCompare(`${b.location}\u0000${b.title}\u0000${b.displayName}`);
}

function actorsById(frame) {
  return Object.fromEntries(frame.actors.map((actor) => [actor.id, actor]));
}

function roots(frame) {
  return frame.actors.filter((actor) => actor.active && actor.commander === null).sort(actorSort);
}

function children(frame, actorId) {
  return frame.actors.filter((actor) => actor.active && actor.commander === actorId).sort(actorSort);
}

function chainLabel(chain, actorMap) {
  return (chain || []).map((id) => actorMap[id] ? actorMap[id].displayName : id).join(" -> ");
}

function beliefCell(belief) {
  if (!belief) return '<span class="muted">-</span>';
  const conf = belief.confidence === null || belief.confidence === undefined
    ? ""
    : ` <span class="conf">c${Number(belief.confidence).toFixed(2)}</span>`;
  const age = belief.updatedAt === null || belief.updatedAt === undefined
    ? ""
    : ` <span class="conf">t${fmtTime(belief.updatedAt)}</span>`;
  return `${fmt(belief.value)}${conf}${age}`;
}

function renderActor(frame, actor, apex, actorMap) {
  const lineage = actor.lineage || [];
  const office = [];
  if (lineage.length > 1) office.push(`<div class="lineage">Office: ${esc(lineage.join(" -> "))}</div>`);
  if (actor.vacant) office.push(`<div class="lineage">Vacant - governed by ${esc(actor.regentName || actor.regent || "superior")}</div>`);
  const rows = frame.statsSchema.map((stat) => {
    const subject = `${actor.id}.${stat}`;
    const selfBelief = actor.known[subject];
    const apexBelief = apex ? apex.known[subject] : null;
    const chain = apexBelief && apexBelief.sourceChain && apexBelief.sourceChain.length
      ? `<div class="chain">via ${esc(chainLabel(apexBelief.sourceChain, actorMap))}</div>`
      : "";
    return `<tr><th>${esc(stat)}</th><td>${fmt(actor.stats[stat])}</td><td>${beliefCell(selfBelief)}</td><td>${beliefCell(apexBelief)}${chain}</td></tr>`;
  }).join("");
  const kids = children(frame, actor.id).map((child) => renderActor(frame, child, apex, actorMap)).join("");
  return `<section class="actor">
    <div class="actor-head"><div><strong>${esc(actor.vacant ? "Vacant" : actor.displayName)}</strong> <span>${esc(actor.title)}</span></div><div class="meta">${esc(actor.id)} @ ${esc(actor.location)}</div></div>
    ${office.join("")}
    <table><thead><tr><th>Stat</th><th>Real</th><th>Self known</th><th>Apex known</th></tr></thead><tbody>${rows}</tbody></table>
    ${kids ? `<div class="children">${kids}</div>` : ""}
  </section>`;
}

async function loadMeta() {
  meta = await (await fetch("/api/meta")).json();
  source.textContent = `${meta.path} | ${meta.scenario} seed=${meta.seed ?? "unknown"} | ${meta.eventCount} events`;
  slider.min = String(meta.startTime);
  slider.max = String(meta.endTime);
  slider.step = String(Math.max(0.1, (meta.endTime - meta.startTime) / 4000));
  currentTime = meta.startTime;
  await loadFrame(currentTime);
}

async function loadFrame(timeValue) {
  currentTime = Math.max(meta.startTime, Math.min(meta.endTime, Number(timeValue)));
  if (pending) pending.abort();
  pending = new AbortController();
  statusEl.textContent = "loading...";
  const params = new URLSearchParams({
    time: String(currentTime),
    window: windowInput.value,
    max_stats: statsInput.value,
  });
  try {
    const data = await (await fetch(`/api/frame?${params}`, { signal: pending.signal })).json();
    currentTime = data.time;
    slider.value = String(currentTime);
    timeInput.value = fmtTime(currentTime);
    statusEl.textContent = `t=${fmtTime(currentTime)} | ${data.position}/${data.eventCount}`;
    renderEvents(data.events);
    renderState(data.state);
  } catch (error) {
    if (error.name !== "AbortError") statusEl.textContent = String(error);
  }
}

function renderEvents(events) {
  eventsRoot.innerHTML = events.map((event) => `
    <div class="event">
      <div class="event-kind">t=${fmtTime(event.time)} ${esc(event.kind)}</div>
      <div>${esc(event.summary)}</div>
    </div>
  `).join("") || '<div class="muted">No non-observation events in this window.</div>';
}

function renderState(frame) {
  const actorMap = actorsById(frame);
  const apex = actorMap.king || actorMap.ceo || roots(frame)[0] || null;
  stateRoot.innerHTML = roots(frame).map((root) => renderActor(frame, root, apex, actorMap)).join("");
}

async function seek(direction, mode) {
  const params = new URLSearchParams({ time: String(currentTime), direction, mode });
  const data = await (await fetch(`/api/seek?${params}`)).json();
  await loadFrame(data.time);
}

let debounce = null;
slider.addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => loadFrame(Number(slider.value)), 120);
});
timeInput.addEventListener("change", () => loadFrame(Number(timeInput.value)));
windowInput.addEventListener("change", () => loadFrame(currentTime));
statsInput.addEventListener("change", () => loadFrame(currentTime));
for (const button of document.querySelectorAll("button[data-seek]")) {
  button.addEventListener("click", () => {
    const [direction, mode] = button.dataset.seek.split(":");
    seek(direction, mode);
  });
}
loadMeta();
</script>
</body>
</html>"""


class VisualizerHandler(BaseHTTPRequestHandler):
    store: ReplayStore
    index: EventIndex
    scenario: str
    seed: int | None
    source_path: Path

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_text(_html(), "text/html; charset=utf-8")
            elif parsed.path == "/api/meta":
                self._send_json(self._meta())
            elif parsed.path == "/api/frame":
                self._send_json(self._frame(parse_qs(parsed.query)))
            elif parsed.path == "/api/seek":
                self._send_json(self._seek(parse_qs(parsed.query)))
            else:
                self.send_error(404)
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary.
            self.send_error(500, explain=str(exc))

    def _meta(self) -> dict[str, Any]:
        return {
            "path": str(self.source_path),
            "scenario": self.scenario,
            "seed": self.seed,
            "eventCount": len(self.index.records),
            "startTime": self.index.start_time,
            "endTime": self.index.end_time,
            "choiceTimeCount": len(self.index.choice_times),
            "eventTimeCount": len(self.index.event_times),
            "kindCounts": self.index.kind_counts,
        }

    def _frame(self, query: dict[str, list[str]]) -> dict[str, Any]:
        time_value = float(query.get("time", [self.index.start_time])[0])
        window = float(query.get("window", [DEFAULT_WINDOW])[0])
        max_stats = int(query.get("max_stats", [DEFAULT_MAX_STATS])[0])
        return self.store.frame_at(time_value, window=max(1.0, window), max_stats=max_stats)

    def _seek(self, query: dict[str, list[str]]) -> dict[str, Any]:
        time_value = float(query.get("time", [self.index.start_time])[0])
        direction = query.get("direction", ["next"])[0]
        mode = query.get("mode", ["event"])[0]
        return {"time": self.index.seek_time(time_value, mode=mode, direction=direction)}

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, payload: str, content_type: str) -> None:
        data = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(path: Path, scenario: str | None, host: str, port: int) -> None:
    progress = Progress(enabled=True)
    resolved_scenario = scenario or _infer_scenario(path)
    seed = _infer_seed(path)
    progress.message(f"Scenario: {resolved_scenario} seed={seed if seed is not None else 'unknown'}")
    index = EventIndex(path, progress=progress)
    store = ReplayStore(index, resolved_scenario, seed)

    handler = type(
        "BoundVisualizerHandler",
        (VisualizerHandler,),
        {
            "store": store,
            "index": index,
            "scenario": resolved_scenario,
            "seed": seed,
            "source_path": path,
        },
    )
    server = HTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_port}/"
    print(f"Visualizer: {url}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    finally:
        index.close()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="run JSONL file")
    parser.add_argument("--scenario")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not args.path.exists():
        raise SystemExit(f"no such file: {args.path}")
    serve(args.path, args.scenario, args.host, args.port)


if __name__ == "__main__":
    main()

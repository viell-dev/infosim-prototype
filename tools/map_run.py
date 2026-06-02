#!/usr/bin/env python3
"""Generate a simple HTML hierarchy map from a run JSONL file.

The map samples the run at start, 25%, 50%, 75%, and end. Each checkpoint
shows the active command tree, each actor's real stats, that actor's own
belief about those stats, and the King's current belief about the same stats.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from infosim.actors import Actor  # noqa: E402
from infosim.world import STATS  # noqa: E402


CHECKPOINTS = (
    ("Start", 0.0),
    ("25%", 0.25),
    ("50%", 0.50),
    ("75%", 0.75),
    ("End", 1.0),
)


@dataclass
class Belief:
    value: float
    confidence: float | None = None
    updated_at: float | None = None
    source_chain: list[str] = field(default_factory=list)


@dataclass
class ActorState:
    id: str
    display_name: str
    title: str
    location: str
    commander: str | None
    stats: dict[str, float]
    known: dict[str, Belief] = field(default_factory=dict)
    active: bool = True


@dataclass
class OfficeExit:
    actor_id: str
    commander: str | None
    title: str
    stats: dict[str, float]
    children: list[str]


@dataclass
class ReplayState:
    actors: dict[str, ActorState]
    office_lineages: dict[str, list[str]]
    last_exit_by_location: dict[str, OfficeExit] = field(default_factory=dict)


@dataclass
class Checkpoint:
    label: str
    time: float
    state: ReplayState


def _scenario_build(name: str) -> tuple[Any, dict[str, Actor]]:
    if name == "frontier":
        from infosim.scenarios import frontier

        return frontier.build()
    if name in {"deep_chain", "deepchain"}:
        from infosim.scenarios import deep_chain

        return deep_chain.build()
    if name in {"space_miner", "spaceminer"}:
        from infosim.scenarios import space_miner

        return space_miner.build()
    raise ValueError(f"unknown scenario: {name}")


def _infer_scenario(path: Path) -> str:
    stem = path.stem.lower()
    if stem.startswith("frontier-"):
        return "frontier"
    if stem.startswith("deepchain-") or stem.startswith("deep-chain-"):
        return "deep_chain"
    if stem.startswith("space_miner-") or stem.startswith("spaceminer-"):
        return "space_miner"
    raise ValueError("could not infer scenario from filename; pass --scenario")


def _initial_state(scenario: str) -> ReplayState:
    _world, actors = _scenario_build(scenario)
    state = ReplayState(
        actors={
            actor.id: ActorState(
                id=actor.id,
                display_name=actor.display_name,
                title=actor.title,
                location=actor.location,
                commander=actor.commander,
                stats=dict(actor.stats),
            )
            for actor in actors.values()
        },
        office_lineages={
            actor.location: [actor.display_name]
            for actor in actors.values()
        },
    )
    return state


def _copy_state(state: ReplayState) -> ReplayState:
    return ReplayState(
        actors={
            actor_id: ActorState(
                id=actor.id,
                display_name=actor.display_name,
                title=actor.title,
                location=actor.location,
                commander=actor.commander,
                stats=dict(actor.stats),
                known={
                    subject: Belief(
                        value=belief.value,
                        confidence=belief.confidence,
                        updated_at=belief.updated_at,
                        source_chain=list(belief.source_chain),
                    )
                    for subject, belief in actor.known.items()
                },
                active=actor.active,
            )
            for actor_id, actor in state.actors.items()
        },
        office_lineages={
            location: list(lineage)
            for location, lineage in state.office_lineages.items()
        },
        last_exit_by_location={
            location: OfficeExit(
                actor_id=exit.actor_id,
                commander=exit.commander,
                title=exit.title,
                stats=dict(exit.stats),
                children=list(exit.children),
            )
            for location, exit in state.last_exit_by_location.items()
        },
    )


def _read_events(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def _subject_stat(subject: str) -> str:
    return subject.split(".", 1)[1]


def _format_value(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) < 0.5:
        return "0"
    return f"{value:.0f}"


def _active_children(state: ReplayState, actor_id: str) -> list[str]:
    return [
        actor.id
        for actor in state.actors.values()
        if actor.active and actor.commander == actor_id
    ]


def _event_display_name(ev: dict[str, Any]) -> str:
    if ev.get("display_name"):
        return str(ev["display_name"])
    human = ev.get("human", "")
    title = ev.get("title")
    if title:
        match = re.search(rf"{re.escape(str(title))} (.+?) takes office", human)
        if match:
            return match.group(1)
    return str(ev.get("actor", "(unknown)"))


def _apply_event(state: ReplayState, ev: dict[str, Any]) -> None:
    kind = ev.get("kind")
    actor_id = ev.get("actor")
    t = float(ev.get("time", 0.0))

    if kind == "observation" and actor_id in state.actors:
        subject = str(ev["subject"])
        stat = _subject_stat(subject)
        actor = state.actors[actor_id]
        actor.stats[stat] = float(ev["true_value"])
        actor.known[subject] = Belief(
            value=float(ev["estimated_value"]),
            confidence=float(ev["confidence"]),
            updated_at=t,
            source_chain=[actor_id],
        )
        return

    if kind == "receive" and ev.get("recipient") in state.actors:
        recipient = state.actors[str(ev["recipient"])]
        recipient.known[str(ev["subject"])] = Belief(
            value=float(ev["value"]),
            confidence=float(ev["confidence"]),
            updated_at=t,
            source_chain=list(ev.get("source_chain", [])),
        )
        return

    if kind == "response_integrated" and actor_id in state.actors:
        recipient = state.actors[actor_id]
        sender = str(ev.get("sender", ""))
        source_chain = [sender, actor_id] if sender else [actor_id]
        for subject, answer in dict(ev.get("answers") or {}).items():
            recipient.known[str(subject)] = Belief(
                value=float(answer["value"]),
                confidence=float(answer["confidence"]),
                updated_at=t,
                source_chain=source_chain,
            )
        return

    if kind == "true_state_change" and actor_id in state.actors:
        state.actors[actor_id].stats[str(ev["stat"])] = float(ev["after"])
        return

    if kind == "alien_contact" and actor_id in state.actors:
        state.actors[actor_id].stats["alien_presence"] = float(ev["after"])
        return

    if kind == "mining" and actor_id in state.actors:
        stats = state.actors[actor_id].stats
        stats["ore"] = stats.get("ore", 0.0) + float(ev["amount"])
        return

    if kind == "consumption" and actor_id in state.actors:
        stats = state.actors[actor_id].stats
        stats["ore"] = max(0.0, stats.get("ore", 0.0) - float(ev["amount"]))
        return

    if kind == "defense" and ev.get("target_actor") in state.actors:
        state.actors[str(ev["target_actor"])].stats["alien_presence"] = float(ev["after"])
        return

    if kind == "skim" and actor_id in state.actors:
        stats = state.actors[actor_id].stats
        stat = str(ev.get("stat") or ("ore" if "ore" in stats else "food_stores"))
        stats[stat] = max(0.0, stats.get(stat, 0.0) - float(ev["amount"]))
        return

    if kind == "action_started":
        detail = ev.get("kind_detail")
        if (
            detail in {"transfer_garrison", "send_supplies", "ore_tax", "manager_tax"}
            and ev.get("src_actor") in state.actors
        ):
            stats = state.actors[str(ev["src_actor"])].stats
            stat = str(ev.get("stat") or (
                "garrison_strength" if detail == "transfer_garrison" else "food_stores"
            ))
            stats[stat] = max(
                0.0,
                stats.get(stat, 0.0) - float(ev["magnitude"]),
            )
        return

    if kind == "action_completed":
        detail = ev.get("kind_detail")
        if (
            detail in {
                "transfer_garrison_arrive",
                "send_supplies_arrive",
                "ore_tax_arrive",
                "manager_tax_arrive",
            }
            and ev.get("dst_actor") in state.actors
        ):
            stats = state.actors[str(ev["dst_actor"])].stats
            stat = str(ev.get("stat") or (
                "garrison_strength" if detail == "transfer_garrison_arrive" else "food_stores"
            ))
            stats[stat] = stats.get(stat, 0.0) + float(ev["magnitude"])
        elif detail == "move_actor_arrive" and actor_id in state.actors:
            actor = state.actors[actor_id]
            actor.location = str(ev["target_location"])
            if ev.get("assigned_commander") is not None:
                actor.commander = str(ev["assigned_commander"])
        elif detail == "suppress_unrest_resolve" and ev.get("target_actor") in state.actors:
            state.actors[str(ev["target_actor"])].stats["unrest"] = float(ev["after"])
        return

    if kind == "dismissed" and actor_id in state.actors:
        actor = state.actors[actor_id]
        actor.active = False
        state.last_exit_by_location[actor.location] = OfficeExit(
            actor_id=actor.id,
            commander=actor.commander,
            title=actor.title,
            stats=dict(actor.stats),
            children=_active_children(state, actor.id),
        )
        return

    if kind == "appointed":
        location = str(ev["location"])
        prior = state.last_exit_by_location.get(location)
        new_id = str(ev["actor"])
        for actor in state.actors.values():
            if actor.active and actor.location == location and actor.id.startswith("vacant:"):
                actor.active = False
        new_actor = ActorState(
            id=new_id,
            display_name=_event_display_name(ev),
            title=str(ev.get("title") or (prior.title if prior else "Actor")),
            location=location,
            commander=ev.get("commander") if ev.get("commander") is not None else (
                prior.commander if prior else None
            ),
            stats={
                key: float(value)
                for key, value in dict(ev.get("stats") or (prior.stats if prior else {})).items()
            },
        )
        state.actors[new_id] = new_actor
        state.office_lineages.setdefault(location, []).append(new_actor.display_name)
        if prior:
            for child_id in prior.children:
                if child_id in state.actors and state.actors[child_id].active:
                    state.actors[child_id].commander = new_id
        return

    if kind == "appointment_failed":
        location = str(ev["location"])
        prior = state.last_exit_by_location.get(location)
        if prior is None:
            return
        vacant_id = f"vacant:{location}"
        vacant_actor = ActorState(
            id=vacant_id,
            display_name="Vacant",
            title=prior.title,
            location=location,
            commander=prior.commander,
            stats=dict(prior.stats),
        )
        state.actors[vacant_id] = vacant_actor
        state.office_lineages.setdefault(location, []).append("Vacant")
        for child_id in prior.children:
            if child_id in state.actors and state.actors[child_id].active:
                state.actors[child_id].commander = vacant_id
        return


def build_checkpoints(events: list[dict[str, Any]], scenario: str) -> list[Checkpoint]:
    end_time = max(float(ev.get("time", 0.0)) for ev in events) if events else 0.0
    targets = [(label, end_time * fraction) for label, fraction in CHECKPOINTS]
    state = _initial_state(scenario)
    checkpoints: list[Checkpoint] = []
    event_index = 0

    for label, target in targets:
        while event_index < len(events) and float(events[event_index].get("time", 0.0)) <= target:
            _apply_event(state, events[event_index])
            event_index += 1
        checkpoints.append(Checkpoint(label=label, time=target, state=_copy_state(state)))
    return checkpoints


def _actor_sort_key(actor: ActorState) -> tuple[str, str, str]:
    return (actor.location, actor.title, actor.display_name)


def _roots(state: ReplayState) -> list[ActorState]:
    return sorted(
        [actor for actor in state.actors.values() if actor.active and actor.commander is None],
        key=_actor_sort_key,
    )


def _children(state: ReplayState, actor_id: str) -> list[ActorState]:
    return sorted(
        [
            actor
            for actor in state.actors.values()
            if actor.active and actor.commander == actor_id
        ],
        key=_actor_sort_key,
    )


def _cell(belief: Belief | None) -> str:
    if belief is None:
        return '<span class="muted">-</span>'
    conf = (
        ""
        if belief.confidence is None
        else f' <span class="conf">c{belief.confidence:.2f}</span>'
    )
    age = (
        ""
        if belief.updated_at is None
        else f' <span class="conf">t{belief.updated_at:.0f}</span>'
    )
    return f"{_format_value(belief.value)}{conf}{age}"


def _chain_label(state: ReplayState, chain: list[str]) -> str:
    if not chain:
        return ""
    names = [
        state.actors[actor_id].display_name if actor_id in state.actors else actor_id
        for actor_id in chain
    ]
    return " -> ".join(names)


def _render_actor(state: ReplayState, actor: ActorState, king: ActorState | None) -> str:
    lineage = state.office_lineages.get(actor.location, [])
    office = ""
    if len(lineage) > 1:
        office = f'<div class="lineage">Office: {html.escape(" -> ".join(lineage))}</div>'

    rows = []
    for stat in sorted(STATS):
        subject = f"{actor.id}.{stat}"
        self_belief = actor.known.get(subject)
        king_belief = king.known.get(subject) if king else None
        chain = ""
        if king_belief and king_belief.source_chain:
            chain = (
                '<div class="chain">'
                f"via {html.escape(_chain_label(state, king_belief.source_chain))}"
                "</div>"
            )
        rows.append(
            "<tr>"
            f"<th>{html.escape(stat)}</th>"
            f"<td>{_format_value(actor.stats.get(stat))}</td>"
            f"<td>{_cell(self_belief)}</td>"
            f"<td>{_cell(king_belief)}{chain}</td>"
            "</tr>",
        )

    rendered_children = "".join(
        _render_actor(state, child, king)
        for child in _children(state, actor.id)
    )
    children_html = f'<div class="children">{rendered_children}</div>' if rendered_children else ""
    return (
        '<section class="actor">'
        '<div class="actor-head">'
        f'<div><strong>{html.escape(actor.display_name)}</strong> '
        f'<span>{html.escape(actor.title)}</span></div>'
        f'<div class="meta">{html.escape(actor.id)} @ {html.escape(actor.location)}</div>'
        "</div>"
        f"{office}"
        '<table><thead><tr><th>Stat</th><th>Real</th><th>Self known</th>'
        "<th>King known</th></tr></thead><tbody>"
        f"{''.join(rows)}"
        "</tbody></table>"
        f"{children_html}"
        "</section>"
    )


def render_html(checkpoints: list[Checkpoint], source_path: Path) -> str:
    blocks = []
    for checkpoint in checkpoints:
        state = checkpoint.state
        apex = state.actors.get("king") or state.actors.get("ceo")
        tree = "".join(_render_actor(state, root, apex) for root in _roots(state))
        blocks.append(
            '<article class="checkpoint">'
            f"<h2>{html.escape(checkpoint.label)} <span>t={checkpoint.time:.0f}</span></h2>"
            f"{tree}"
            "</article>",
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InfoSim Run Map - {html.escape(source_path.name)}</title>
<style>
body {{
  margin: 16px;
  font-family: system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.35;
}}
h1 {{ margin: 0 0 4px; }}
.source, .meta, .muted, .conf, .chain, h2 span {{
  color: #666;
  font-size: 12px;
}}
.checkpoint {{
  border: 1px solid #bbb;
  margin: 14px 0;
  padding: 10px;
  overflow-x: auto;
}}
h2 {{ margin: 0 0 10px; font-size: 18px; }}
.actor {{
  min-width: 680px;
  border-left: 2px solid #999;
  margin: 8px 0 0;
  padding-left: 10px;
}}
.actor-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}}
.lineage {{
  color: #7a4a00;
  font-size: 12px;
  margin-bottom: 4px;
}}
.help {{
  border: 1px solid #bbb;
  margin: 12px 0 14px;
  padding: 8px 10px;
  max-width: 980px;
}}
.help h2 {{
  margin: 0 0 6px;
  font-size: 16px;
}}
.help ul {{
  margin: 0;
  padding-left: 20px;
}}
.children {{
  margin-left: 24px;
  padding-left: 10px;
  border-left: 1px dotted #bbb;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  margin-bottom: 6px;
}}
th, td {{
  border-top: 1px solid #ddd;
  padding: 4px 6px;
  text-align: left;
  vertical-align: top;
}}
th {{ width: 22%; }}
td {{ width: 26%; }}
.chain {{ overflow-wrap: anywhere; }}
</style>
</head>
<body>
<header>
  <h1>InfoSim Run Map</h1>
  <div class="source">{html.escape(str(source_path))}</div>
  <section class="help">
    <h2>How to read this</h2>
    <ul>
      <li>Each block is a checkpoint sampled from the run: start, 25%, 50%, 75%, and end.</li>
      <li>Actors are nested by the active commander tree at that checkpoint.</li>
      <li><strong>Real</strong> is the replayed authoritative resource/stat value on that actor.</li>
      <li><strong>Self known</strong> is that actor's latest belief about their own stat.</li>
      <li><strong>King known</strong> is the King's latest belief about that actor's stat.</li>
      <li><strong>c</strong> is confidence, from 0 to 1. Higher means more trusted/clear.</li>
      <li><strong>t</strong> is the simulation time when that belief was last updated.</li>
      <li><strong>via</strong> is the source chain the King's belief traveled through.</li>
      <li><strong>Office</strong> shows replacements at the same position, for example A -&gt; B.</li>
    </ul>
  </section>
</header>
<main class="wrap">
{''.join(blocks)}
</main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="run JSONL file")
    parser.add_argument(
        "--scenario",
        choices=("frontier", "deep_chain", "deepchain", "space_miner", "spaceminer"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if not args.path.exists():
        raise SystemExit(f"no such file: {args.path}")
    scenario = args.scenario or _infer_scenario(args.path)
    events = _read_events(args.path)
    checkpoints = build_checkpoints(events, scenario)
    output_path = args.out or args.path.with_name(f"{args.path.stem}-map.html")
    output_path.write_text(render_html(checkpoints, args.path), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

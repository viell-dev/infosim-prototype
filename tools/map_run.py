#!/usr/bin/env python3
"""Generate a simple HTML replay browser from a run JSONL file.

The replay reconstructs simulation state from the JSONL stream, then emits a
plain HTML tool for stepping through notable event times, coarser decision /
action times, and the old start / 25% / 50% / 75% / end checkpoints.
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
    vacant: bool = False
    regent: str | None = None
    regent_name: str | None = None


@dataclass
class ReplayState:
    actors: dict[str, ActorState]
    # Occupant history per office id (display names over time) for the lineage.
    office_lineages: dict[str, list[str]]


@dataclass
class Checkpoint:
    label: str
    time: float
    state: ReplayState


@dataclass
class ReplayFrame:
    label: str
    time: float
    state: ReplayState
    events: list[dict[str, str]]
    is_checkpoint: bool = False
    is_choice: bool = False


CHOICE_EVENT_KINDS = {
    "action_completed",
    "action_started",
    "autonomous_action",
    "defense",
    "occupant_installed",
    "order_dispatched",
    "order_received",
    "order_unroutable",
    "regency_started",
    "report_forged",
    "request_dispatched",
    "response_dispatched",
    "response_integrated",
    "response_refused",
    "response_relayed",
    "review_cleared",
    "review_strike",
    "skim",
    "tax_forgiven",
}


def _scenario_build(name: str, seed: int | None = None) -> tuple[Any, dict[str, Actor]]:
    if name == "frontier":
        from infosim.scenarios import frontier

        return frontier.build()
    if name in {"deep_chain", "deepchain"}:
        from infosim.scenarios import deep_chain

        return deep_chain.build()
    if name in {"space_miner", "spaceminer"}:
        from infosim.scenarios import space_miner

        return space_miner.build()
    if name in {"isekai_kingdom", "isekaikingdom", "isekai-kingdom"}:
        from infosim.scenarios import isekai_kingdom

        return isekai_kingdom.build(seed=seed or 1)
    raise ValueError(f"unknown scenario: {name}")


def _infer_scenario(path: Path) -> str:
    stem = path.stem.lower()
    if stem.startswith("frontier-"):
        return "frontier"
    if stem.startswith("deepchain-") or stem.startswith("deep-chain-"):
        return "deep_chain"
    if stem.startswith("space_miner-") or stem.startswith("spaceminer-"):
        return "space_miner"
    if stem.startswith("isekai_kingdom-") or stem.startswith("isekaikingdom-"):
        return "isekai_kingdom"
    raise ValueError("could not infer scenario from filename; pass --scenario")


def _infer_seed(path: Path) -> int | None:
    match = re.search(r"-seed(\d+)-", path.stem)
    return int(match.group(1)) if match else None


def _initial_state(scenario: str, seed: int | None = None) -> ReplayState:
    _world, actors = _scenario_build(scenario, seed=seed)
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
            actor.id: [actor.display_name]
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
                vacant=actor.vacant,
                regent=actor.regent,
                regent_name=actor.regent_name,
            )
            for actor_id, actor in state.actors.items()
        },
        office_lineages={
            office_id: list(lineage)
            for office_id, lineage in state.office_lineages.items()
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


def _format_time(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value - round(value)) < 0.01:
        return f"{value:.0f}"
    return f"{value:.2f}"


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


def _actor_label(state: ReplayState, actor_id: object) -> str:
    actor_key = str(actor_id)
    actor = state.actors.get(actor_key)
    if actor is None:
        return actor_key
    if actor.vacant:
        return f"{actor.title} vacant office ({actor.id})"
    return f"{actor.title} {actor.display_name} ({actor.id})"


def _subject_label(state: ReplayState, subject: object) -> str:
    text = str(subject)
    if "." not in text:
        return text
    actor_id, stat = text.split(".", 1)
    return f"{_actor_label(state, actor_id)} {stat}"


def _event_summary(ev: dict[str, Any], state: ReplayState) -> str:
    kind = str(ev.get("kind", "event"))
    actor = ev.get("actor")
    sender = ev.get("sender")
    recipient = ev.get("recipient")

    if kind == "observation":
        return "local observation refreshed belief"
    if kind == "dispatch":
        forged = " forged" if ev.get("forged") else ""
        return (
            f"{_actor_label(state, sender)} sent{forged} report on "
            f"{_subject_label(state, ev.get('subject'))} "
            f"value {_format_value(_float_or_none(ev.get('value')))} "
            f"to {_actor_label(state, recipient)}"
        )
    if kind == "receive":
        return (
            f"{_actor_label(state, recipient)} updated belief in "
            f"{_subject_label(state, ev.get('subject'))} "
            f"to {_format_value(_float_or_none(ev.get('value')))}"
        )
    if kind == "report_forged":
        return (
            f"{_actor_label(state, actor)} forged "
            f"{_subject_label(state, ev.get('subject'))}: "
            f"{_format_value(_float_or_none(ev.get('true_belief')))} -> "
            f"{_format_value(_float_or_none(ev.get('forged_value')))}"
        )
    if kind == "order_dispatched":
        return (
            f"{_actor_label(state, ev.get('issuer'))} ordered "
            f"{_actor_label(state, recipient)} to {ev.get('order_kind')} "
            f"{_actor_label(state, ev.get('target_actor'))} "
            f"(magnitude {_format_value(_float_or_none(ev.get('magnitude')))}, "
            f"eta t={_format_time(_float_or_none(ev.get('eta_time')))})"
        )
    if kind == "order_delivered":
        return (
            f"{_actor_label(state, recipient)} received order "
            f"{ev.get('order_kind')} for {_actor_label(state, ev.get('target_actor'))}"
        )
    if kind == "order_received":
        return (
            f"{_actor_label(state, recipient)} acted on order "
            f"{ev.get('order_kind')} for {_actor_label(state, ev.get('target_actor'))}"
        )
    if kind == "order_unroutable":
        return (
            f"{_actor_label(state, actor)} could not route order to "
            f"{_actor_label(state, ev.get('target_actor'))}"
        )
    if kind == "request_dispatched":
        subjects = ", ".join(_subject_label(state, s) for s in ev.get("subjects", []))
        return (
            f"{_actor_label(state, actor)} requested fresh information from "
            f"{_actor_label(state, recipient)} about {subjects}"
        )
    if kind == "request_delivered":
        subjects = ", ".join(_subject_label(state, s) for s in ev.get("subjects", []))
        return (
            f"{_actor_label(state, recipient)} received information request from "
            f"{_actor_label(state, sender)} about {subjects}"
        )
    if kind == "response_dispatched":
        status = "refusal" if ev.get("refused") else f"{ev.get('n_answers', 0)} answers"
        return (
            f"{_actor_label(state, actor)} sent information response to "
            f"{_actor_label(state, recipient)} ({status})"
        )
    if kind == "response_integrated":
        return (
            f"{_actor_label(state, actor)} integrated information response from "
            f"{_actor_label(state, ev.get('sender'))} "
            f"({ev.get('n_answers', 0)} subjects)"
        )
    if kind == "response_relayed":
        return (
            f"{_actor_label(state, actor)} relayed information response "
            f"to {_actor_label(state, ev.get('parent_from_actor'))}"
        )
    if kind == "response_refused":
        return f"{_actor_label(state, actor)} received refused information response"
    if kind == "request_timeout":
        return f"{_actor_label(state, actor)} request timed out"
    if kind == "true_state_change":
        return (
            f"{_actor_label(state, actor)} {ev.get('stat')} changed "
            f"{_format_value(_float_or_none(ev.get('before')))} -> "
            f"{_format_value(_float_or_none(ev.get('after')))}"
        )
    if kind in {"mining", "consumption", "skim"}:
        verb = {
            "mining": "produced",
            "consumption": "consumed",
            "skim": "skimmed",
        }[kind]
        return (
            f"{_actor_label(state, actor)} {verb} "
            f"{_format_value(_float_or_none(ev.get('amount')))} {ev.get('stat')}"
        )
    if kind == "defense":
        return (
            f"{_actor_label(state, actor)} defended "
            f"{_actor_label(state, ev.get('target_actor'))}: {ev.get('stat')} "
            f"{_format_value(_float_or_none(ev.get('before')))} -> "
            f"{_format_value(_float_or_none(ev.get('after')))}"
        )
    if kind in {"action_started", "action_completed"}:
        target = ev.get("target_actor") or ev.get("dst_actor") or ev.get("src_actor") or actor
        detail = str(ev.get("kind_detail", kind)).replace("_", " ")
        if ev.get("before") is not None or ev.get("after") is not None:
            return (
                f"{detail}: {_actor_label(state, target)} {ev.get('stat')} "
                f"{_format_value(_float_or_none(ev.get('before')))} -> "
                f"{_format_value(_float_or_none(ev.get('after')))}"
            )
        return f"{detail}: {_actor_label(state, target)}"
    if kind == "autonomous_action":
        return f"{_actor_label(state, actor)} acted on local initiative"
    if kind == "review_strike":
        return (
            f"{_actor_label(state, actor)} marked "
            f"{_actor_label(state, ev.get('subordinate'))} "
            f"strike {ev.get('strike')}: {ev.get('reason')}"
        )
    if kind == "review_cleared":
        return (
            f"{_actor_label(state, actor)} cleared review strikes for "
            f"{_actor_label(state, ev.get('subordinate'))}"
        )
    if kind in {"occupant_installed", "occupant_dismissed", "regency_started"}:
        return f"{kind.replace('_', ' ')} at {_actor_label(state, actor)}"
    if kind in {"courier_lost", "courier_undeliverable"}:
        return f"{kind.replace('_', ' ')} #{ev.get('message_id')}"
    return _generic_event_summary(ev, state)


def _generic_event_summary(ev: dict[str, Any], state: ReplayState) -> str:
    kind = str(ev.get("kind", "event")).replace("_", " ")
    actor = ev.get("actor")
    if actor is not None:
        head = f"{kind}: {_actor_label(state, actor)}"
    else:
        head = kind
    details = []
    for key in ("location", "region", "stat", "subject", "target_actor", "amount", "before", "after"):
        if key not in ev:
            continue
        value = ev[key]
        if key == "subject":
            value = _subject_label(state, value)
        elif key == "target_actor":
            value = _actor_label(state, value)
        elif isinstance(value, float):
            value = _format_value(value)
        details.append(f"{key}={value}")
    if not details:
        return head
    return f"{head} ({', '.join(details)})"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    # --- generic economy application ------------------------------------------
    # Every economy event now carries a `stat` field, so the replay is
    # genre-agnostic: no garrison/ore/alien_presence names appear here.

    # Set a stat to an absolute value (own actor).
    if kind == "true_state_change" and actor_id in state.actors:
        state.actors[actor_id].stats[str(ev["stat"])] = float(ev["after"])
        return

    # Set a stat to an absolute value on whichever actor the event names.
    if kind in {"alien_contact", "defense"}:
        target = str(ev.get("target_actor") or actor_id or "")
        if target in state.actors and ev.get("stat") is not None and "after" in ev:
            state.actors[target].stats[str(ev["stat"])] = float(ev["after"])
        return

    # Add to a stat (production).
    if kind == "mining" and actor_id in state.actors and ev.get("stat") is not None:
        stats = state.actors[actor_id].stats
        stat = str(ev["stat"])
        stats[stat] = stats.get(stat, 0.0) + float(ev["amount"])
        return

    # Subtract from a stat (usage / skim).
    if kind in {"consumption", "skim"} and actor_id in state.actors and ev.get("stat") is not None:
        stats = state.actors[actor_id].stats
        stat = str(ev["stat"])
        stats[stat] = max(0.0, stats.get(stat, 0.0) - float(ev["amount"]))
        return

    # Transfers depart: any action carrying a stat + source actor + magnitude.
    if kind == "action_started":
        if ev.get("stat") is not None and ev.get("src_actor") in state.actors:
            stats = state.actors[str(ev["src_actor"])].stats
            stat = str(ev["stat"])
            stats[stat] = max(0.0, stats.get(stat, 0.0) - float(ev["magnitude"]))
        return

    if kind == "action_completed":
        detail = ev.get("kind_detail")
        if detail == "move_actor_arrive" and actor_id in state.actors:
            actor = state.actors[actor_id]
            actor.location = str(ev["target_location"])
            if ev.get("assigned_commander") is not None:
                actor.commander = str(ev["assigned_commander"])
        elif ev.get("stat") is not None and ev.get("dst_actor") in state.actors and "magnitude" in ev:
            # Transfer arrives.
            stats = state.actors[str(ev["dst_actor"])].stats
            stat = str(ev["stat"])
            stats[stat] = stats.get(stat, 0.0) + float(ev["magnitude"])
        elif ev.get("stat") is not None and ev.get("target_actor") in state.actors and "after" in ev:
            # Suppression resolves to an absolute value.
            state.actors[str(ev["target_actor"])].stats[str(ev["stat"])] = float(ev["after"])
        return

    # Office id is stable across occupants; the node persists. occupant_dismissed
    # is informational (the install/regency that follows updates the node).
    if kind == "occupant_installed" and actor_id in state.actors:
        office = state.actors[actor_id]
        office.display_name = _event_display_name(ev)
        office.title = str(ev.get("title") or office.title)
        office.vacant = False
        office.regent = None
        office.regent_name = None
        state.office_lineages.setdefault(actor_id, []).append(office.display_name)
        return

    if kind == "regency_started" and actor_id in state.actors:
        office = state.actors[actor_id]
        office.vacant = True
        office.regent = str(ev.get("regent")) if ev.get("regent") is not None else None
        office.regent_name = ev.get("regent_name")
        office.display_name = "Vacant"
        state.office_lineages.setdefault(actor_id, []).append("Vacant")
        return


def build_checkpoints(
    events: list[dict[str, Any]],
    scenario: str,
    seed: int | None = None,
) -> list[Checkpoint]:
    end_time = max(float(ev.get("time", 0.0)) for ev in events) if events else 0.0
    targets = [(label, end_time * fraction) for label, fraction in CHECKPOINTS]
    state = _initial_state(scenario, seed=seed)
    checkpoints: list[Checkpoint] = []
    event_index = 0

    for label, target in targets:
        while event_index < len(events) and float(events[event_index].get("time", 0.0)) <= target:
            _apply_event(state, events[event_index])
            event_index += 1
        checkpoints.append(Checkpoint(label=label, time=target, state=_copy_state(state)))
    return checkpoints


def _event_time(ev: dict[str, Any]) -> float:
    return float(ev.get("time", 0.0))


def _checkpoint_label_for(time: float, checkpoint_targets: dict[float, str]) -> str | None:
    for target, label in checkpoint_targets.items():
        if abs(time - target) < 0.0001:
            return label
    return None


def _has_visible_event(events: list[dict[str, Any]]) -> bool:
    return any(str(ev.get("kind")) != "observation" for ev in events)


def _has_choice_event(events: list[dict[str, Any]]) -> bool:
    return any(str(ev.get("kind")) in CHOICE_EVENT_KINDS for ev in events)


def _event_summaries(events: list[dict[str, Any]], state: ReplayState) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    observation_count = sum(1 for ev in events if ev.get("kind") == "observation")
    if observation_count:
        summaries.append({
            "kind": "observation",
            "summary": f"{observation_count} local observations refreshed beliefs",
        })
    for ev in events:
        kind = str(ev.get("kind", "event"))
        if kind == "observation":
            continue
        # Unknown scenario-owned events are still worth surfacing when they are
        # not pure observation cadence noise.
        summaries.append({
            "kind": kind,
            "summary": _event_summary(ev, state),
        })
    if not summaries:
        summaries.append({
            "kind": "checkpoint",
            "summary": "No notable event at this checkpoint; state includes all prior events.",
        })
    return summaries


def build_frames(
    events: list[dict[str, Any]],
    scenario: str,
    seed: int | None = None,
) -> list[ReplayFrame]:
    end_time = max((_event_time(ev) for ev in events), default=0.0)
    checkpoint_targets = {
        end_time * fraction: label
        for label, fraction in CHECKPOINTS
    }
    visible_times = {
        _event_time(ev)
        for ev in events
        if str(ev.get("kind")) != "observation"
    }
    target_times = sorted(set(visible_times) | set(checkpoint_targets.keys()))
    if not target_times:
        target_times = [0.0]

    state = _initial_state(scenario, seed=seed)
    frames: list[ReplayFrame] = []
    event_index = 0
    n_events = len(events)

    for target in target_times:
        events_at_time: list[dict[str, Any]] = []
        while event_index < n_events and _event_time(events[event_index]) <= target:
            ev = events[event_index]
            _apply_event(state, ev)
            if abs(_event_time(ev) - target) < 0.0001:
                events_at_time.append(ev)
            event_index += 1

        checkpoint_label = _checkpoint_label_for(target, checkpoint_targets)
        is_checkpoint = checkpoint_label is not None
        if not is_checkpoint and not _has_visible_event(events_at_time):
            continue
        label = checkpoint_label or f"t={_format_time(target)}"
        frames.append(ReplayFrame(
            label=label,
            time=target,
            state=_copy_state(state),
            events=_event_summaries(events_at_time, state),
            is_checkpoint=is_checkpoint,
            is_choice=_has_choice_event(events_at_time),
        ))

    if not any(frame.is_checkpoint for frame in frames):
        frames.insert(0, ReplayFrame(
            label="Start",
            time=0.0,
            state=_initial_state(scenario, seed=seed),
            events=[{
                "kind": "checkpoint",
                "summary": "Initial state before replayed events.",
            }],
            is_checkpoint=True,
            is_choice=False,
        ))
    return frames


def _actor_sort_key(actor: ActorState) -> tuple[str, str, str]:
    return (actor.location, actor.title, actor.display_name)


def _stats_in_state(state: ReplayState) -> list[str]:
    """Union of stat keys present on any actor — the run's effective stat schema.

    Genre-agnostic: a frontier run shows garrison/food/unrest, a space run shows
    ore/ships/population/alien_presence, with no cross-genre empty rows.
    """
    stats: set[str] = set()
    for actor in state.actors.values():
        stats.update(actor.stats.keys())
    return sorted(stats)


def _frame_payload(frame: ReplayFrame) -> dict[str, Any]:
    state = frame.state
    return {
        "label": frame.label,
        "time": frame.time,
        "isCheckpoint": frame.is_checkpoint,
        "isChoice": frame.is_choice,
        "events": frame.events,
        "statsSchema": _stats_in_state(state),
        "actors": [
            {
                "id": actor.id,
                "displayName": actor.display_name,
                "title": actor.title,
                "location": actor.location,
                "commander": actor.commander,
                "stats": actor.stats,
                "known": {
                    subject: {
                        "value": belief.value,
                        "confidence": belief.confidence,
                        "updatedAt": belief.updated_at,
                        "sourceChain": belief.source_chain,
                    }
                    for subject, belief in actor.known.items()
                },
                "active": actor.active,
                "vacant": actor.vacant,
                "regent": actor.regent,
                "regentName": actor.regent_name,
                "lineage": state.office_lineages.get(actor.id, []),
            }
            for actor in sorted(state.actors.values(), key=_actor_sort_key)
        ],
    }


def _frames_from_checkpoints(checkpoints: list[Checkpoint]) -> list[ReplayFrame]:
    return [
        ReplayFrame(
            label=checkpoint.label,
            time=checkpoint.time,
            state=checkpoint.state,
            events=[{
                "kind": "checkpoint",
                "summary": "Checkpoint snapshot.",
            }],
            is_checkpoint=True,
            is_choice=False,
        )
        for checkpoint in checkpoints
    ]


def render_html(replay: list[Checkpoint] | list[ReplayFrame], source_path: Path) -> str:
    if replay and isinstance(replay[0], ReplayFrame):
        frames = replay
    else:
        frames = _frames_from_checkpoints(replay)  # type: ignore[arg-type]
    payload = {
        "source": str(source_path),
        "frames": [_frame_payload(frame) for frame in frames],
    }
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InfoSim Replay - {html.escape(source_path.name)}</title>
<style>
body {{
  margin: 0;
  font-family: system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.35;
  color: #171717;
  background: #f6f6f4;
}}
h1 {{
  margin: 0;
  font-size: 22px;
}}
button {{
  border: 1px solid #aaa;
  border-radius: 4px;
  background: #fff;
  padding: 5px 8px;
  cursor: pointer;
}}
button:hover {{ background: #f0f0ed; }}
button:disabled {{
  color: #999;
  cursor: default;
}}
.topbar {{
  position: sticky;
  top: 0;
  z-index: 2;
  border-bottom: 1px solid #c9c6bd;
  background: #fffffb;
  padding: 12px 16px;
}}
.source, .meta, .muted, .conf, .chain, .frame-mark {{
  color: #66615a;
  font-size: 12px;
}}
.frame-row {{
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}}
#frameRange {{
  min-width: 240px;
  flex: 1 1 360px;
}}
.wrap {{
  display: grid;
  grid-template-columns: minmax(280px, 34%) minmax(620px, 1fr);
  gap: 16px;
  padding: 16px;
}}
.timeline {{
  min-width: 0;
}}
.event-list {{
  border-top: 1px solid #d7d3c9;
  margin-top: 8px;
  padding-top: 8px;
}}
.event {{
  border-bottom: 1px solid #e3e0d8;
  padding: 7px 0;
}}
.event-kind {{
  color: #65513b;
  font-size: 11px;
  text-transform: uppercase;
}}
.state {{
  min-width: 0;
  overflow-x: auto;
}}
.actor {{
  min-width: 680px;
  border-left: 2px solid #8c8678;
  margin: 8px 0 0;
  padding-left: 10px;
  background: #fffffb;
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
@media (max-width: 900px) {{
  .wrap {{
    grid-template-columns: 1fr;
  }}
  .state {{
    overflow-x: auto;
  }}
}}
</style>
</head>
<body>
<header class="topbar">
  <h1>InfoSim Replay</h1>
  <div class="source">{html.escape(str(source_path))}</div>
  <div class="frame-row">
    <button type="button" data-nav="prevCheckpoint">Prev checkpoint</button>
    <button type="button" data-nav="prevChoice">Prev choice</button>
    <button type="button" data-nav="prevEvent">Prev event</button>
    <input id="frameRange" type="range" min="0" max="0" value="0">
    <button type="button" data-nav="nextEvent">Next event</button>
    <button type="button" data-nav="nextChoice">Next choice</button>
    <button type="button" data-nav="nextCheckpoint">Next checkpoint</button>
  </div>
  <div class="frame-row">
    <strong id="frameTitle"></strong>
    <span id="frameMeta" class="frame-mark"></span>
  </div>
</header>
<main class="wrap">
  <section class="timeline">
    <h2>What Happened</h2>
    <div id="events" class="event-list"></div>
  </section>
  <section class="state">
    <h2>State</h2>
    <div id="state"></div>
  </section>
</main>
<script>
const DATA = {data_json};
let index = 0;
const frameRange = document.getElementById("frameRange");
const frameTitle = document.getElementById("frameTitle");
const frameMeta = document.getElementById("frameMeta");
const eventsRoot = document.getElementById("events");
const stateRoot = document.getElementById("state");

function esc(value) {{
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({{
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\\"": "&quot;",
    "'": "&#39;",
  }}[ch]));
}}

function fmt(value) {{
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  const n = Number(value);
  if (Math.abs(n) < 0.5) return "0";
  return n.toFixed(0);
}}

function fmtTime(value) {{
  const n = Number(value ?? 0);
  return Math.abs(n - Math.round(n)) < 0.01 ? String(Math.round(n)) : n.toFixed(2);
}}

function actorsById(frame) {{
  return Object.fromEntries(frame.actors.map((actor) => [actor.id, actor]));
}}

function actorSort(a, b) {{
  return `${{a.location}}\\u0000${{a.title}}\\u0000${{a.displayName}}`
    .localeCompare(`${{b.location}}\\u0000${{b.title}}\\u0000${{b.displayName}}`);
}}

function roots(frame) {{
  return frame.actors
    .filter((actor) => actor.active && actor.commander === null)
    .sort(actorSort);
}}

function children(frame, actorId) {{
  return frame.actors
    .filter((actor) => actor.active && actor.commander === actorId)
    .sort(actorSort);
}}

function actorLabel(actor) {{
  if (!actor) return "";
  const name = actor.vacant ? "Vacant" : actor.displayName;
  return `${{name}} ${{actor.title}}`;
}}

function chainLabel(chain, actorMap) {{
  return (chain || []).map((id) => {{
    const actor = actorMap[id];
    return actor ? actor.displayName : id;
  }}).join(" -> ");
}}

function beliefCell(belief) {{
  if (!belief) return '<span class="muted">-</span>';
  const conf = belief.confidence === null || belief.confidence === undefined
    ? ""
    : ` <span class="conf">c${{Number(belief.confidence).toFixed(2)}}</span>`;
  const age = belief.updatedAt === null || belief.updatedAt === undefined
    ? ""
    : ` <span class="conf">t${{fmtTime(belief.updatedAt)}}</span>`;
  return `${{fmt(belief.value)}}${{conf}}${{age}}`;
}}

function renderActor(frame, actor, apex, actorMap) {{
  const lineage = actor.lineage || [];
  const office = [];
  if (lineage.length > 1) {{
    office.push(`<div class="lineage">Office: ${{esc(lineage.join(" -> "))}}</div>`);
  }}
  if (actor.vacant) {{
    const regent = actor.regentName || actor.regent || "superior";
    office.push(`<div class="lineage">Vacant — governed by ${{esc(regent)}}</div>`);
  }}
  const rows = frame.statsSchema.map((stat) => {{
    const subject = `${{actor.id}}.${{stat}}`;
    const selfBelief = actor.known[subject];
    const apexBelief = apex ? apex.known[subject] : null;
    const chain = apexBelief && apexBelief.sourceChain && apexBelief.sourceChain.length
      ? `<div class="chain">via ${{esc(chainLabel(apexBelief.sourceChain, actorMap))}}</div>`
      : "";
    return `<tr>
      <th>${{esc(stat)}}</th>
      <td>${{fmt(actor.stats[stat])}}</td>
      <td>${{beliefCell(selfBelief)}}</td>
      <td>${{beliefCell(apexBelief)}}${{chain}}</td>
    </tr>`;
  }}).join("");
  const kids = children(frame, actor.id)
    .map((child) => renderActor(frame, child, apex, actorMap))
    .join("");
  return `<section class="actor">
    <div class="actor-head">
      <div><strong>${{esc(actor.vacant ? "Vacant" : actor.displayName)}}</strong>
        <span>${{esc(actor.title)}}</span></div>
      <div class="meta">${{esc(actor.id)}} @ ${{esc(actor.location)}}</div>
    </div>
    ${{office.join("")}}
    <table>
      <thead><tr><th>Stat</th><th>Real</th><th>Self known</th><th>Apex known</th></tr></thead>
      <tbody>${{rows}}</tbody>
    </table>
    ${{kids ? `<div class="children">${{kids}}</div>` : ""}}
  </section>`;
}}

function render() {{
  const frame = DATA.frames[index];
  const actorMap = actorsById(frame);
  const apex = actorMap.king || actorMap.ceo || roots(frame)[0] || null;
  frameTitle.textContent = `${{frame.label}}  t=${{fmtTime(frame.time)}}`;
  const marks = [];
  if (frame.isCheckpoint) marks.push("checkpoint");
  if (frame.isChoice) marks.push("choice/change");
  frameMeta.textContent = `${{index + 1}} / ${{DATA.frames.length}}${{marks.length ? "  " + marks.join(", ") : ""}}`;
  frameRange.value = String(index);
  eventsRoot.innerHTML = frame.events.map((event) => `
    <div class="event">
      <div class="event-kind">${{esc(event.kind)}}</div>
      <div>${{esc(event.summary)}}</div>
    </div>
  `).join("");
  stateRoot.innerHTML = roots(frame)
    .map((root) => renderActor(frame, root, apex, actorMap))
    .join("");
  for (const button of document.querySelectorAll("button[data-nav]")) {{
    const nav = button.getAttribute("data-nav");
    button.disabled = targetIndex(nav) === index;
  }}
}}

function nearestIndex(predicate, direction) {{
  for (let i = index + direction; i >= 0 && i < DATA.frames.length; i += direction) {{
    if (predicate(DATA.frames[i])) return i;
  }}
  return index;
}}

function targetIndex(nav) {{
  if (nav === "prevEvent") return Math.max(0, index - 1);
  if (nav === "nextEvent") return Math.min(DATA.frames.length - 1, index + 1);
  if (nav === "prevChoice") return nearestIndex((frame) => frame.isChoice, -1);
  if (nav === "nextChoice") return nearestIndex((frame) => frame.isChoice, 1);
  if (nav === "prevCheckpoint") return nearestIndex((frame) => frame.isCheckpoint, -1);
  if (nav === "nextCheckpoint") return nearestIndex((frame) => frame.isCheckpoint, 1);
  return index;
}}

for (const button of document.querySelectorAll("button[data-nav]")) {{
  button.addEventListener("click", () => {{
    index = targetIndex(button.getAttribute("data-nav"));
    render();
  }});
}}

frameRange.max = String(Math.max(0, DATA.frames.length - 1));
frameRange.addEventListener("input", () => {{
  index = Number(frameRange.value);
  render();
}});
render();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="run JSONL file")
    parser.add_argument(
        "--scenario",
        choices=(
            "frontier",
            "deep_chain",
            "deepchain",
            "space_miner",
            "spaceminer",
            "isekai_kingdom",
            "isekaikingdom",
            "isekai-kingdom",
        ),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if not args.path.exists():
        raise SystemExit(f"no such file: {args.path}")
    scenario = args.scenario or _infer_scenario(args.path)
    seed = _infer_seed(args.path)
    events = _read_events(args.path)
    frames = build_frames(events, scenario, seed=seed)
    output_path = args.out or args.path.with_name(f"{args.path.stem}-map.html")
    output_path.write_text(render_html(frames, args.path), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

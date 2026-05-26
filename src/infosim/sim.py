from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .actions import ActionInFlight
from .actors import Actor
from .logging_setup import EventLog
from .messages import MessageBus, MessageKind
from .policy import run_policy
from .reports import Report, observe, relay
from .world import World


# A scripted event mutates the world at a given tick. Logged via the event_log.
ScriptedEvent = Callable[["Simulation"], None]


@dataclass
class Simulation:
    world: World
    actors: dict[str, Actor]
    bus: MessageBus
    rng: random.Random
    event_log: EventLog
    schedule: dict[int, list[ScriptedEvent]] = field(default_factory=dict)
    actions_in_flight: list[ActionInFlight] = field(default_factory=list)
    _order_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))
    tick: int = 0

    # Subject naming convention
    @staticmethod
    def subject_for(region: str, var: str) -> str:
        return f"{region}.{var}"

    def schedule_event(self, tick: int, fn: ScriptedEvent) -> None:
        self.schedule.setdefault(tick, []).append(fn)

    def actors_in(self, region: str) -> list[Actor]:
        return [a for a in self.actors.values() if a.region == region]

    def run(self, total_ticks: int) -> None:
        for _ in range(total_ticks):
            self._step()
            self.tick += 1

    def _step(self) -> None:
        t = self.tick

        # 1. scripted true-state changes
        for fn in self.schedule.get(t, []):
            fn(self)

        # 2. local observations — one observer per region (most-senior by id),
        # firing only on the actor's observe cadence to keep logs scannable.
        seen_regions: set[str] = set()
        for actor in sorted(self.actors.values(), key=lambda a: a.id):
            if actor.region in seen_regions:
                continue
            seen_regions.add(actor.region)
            if t - actor.last_observe_tick < actor.observe_every:
                continue
            region = self.world.regions[actor.region]
            for var, true_value in sorted(region.state.items()):
                subject = self.subject_for(region.name, var)
                report = observe(actor, subject, float(true_value), self.rng)
                report.origin_tick = t
                actor.update_belief(
                    subject,
                    report.estimated_value,
                    report.confidence,
                    t,
                    report.source_chain,
                )
                self.event_log.emit(
                    t,
                    "observation",
                    f"[{region.name}] {actor.title} {actor.display_name} observes "
                    f"{var} ≈ {report.estimated_value:.0f} (true {true_value:.0f}, "
                    f"conf {report.confidence:.2f})",
                    actor=actor.id,
                    region=region.name,
                    subject=subject,
                    estimated_value=report.estimated_value,
                    true_value=true_value,
                    confidence=report.confidence,
                )
            actor.last_observe_tick = t

        # 3 & 4. cadence-driven reports get sent upward — one courier carries
        # everything this actor currently believes (own region + relayed beliefs).
        for actor in sorted(self.actors.values(), key=lambda a: a.id):
            if actor.reports_to is None:
                continue
            if t - actor.last_report_tick < actor.report_every:
                continue
            if not actor.known:
                continue
            recipient = self.actors[actor.reports_to]
            travel = self.world.travel_ticks(actor.region, recipient.region)
            for subject in sorted(actor.known.keys()):
                belief = actor.known[subject]
                report = Report(
                    source_actor=actor.id,
                    subject=subject,
                    estimated_value=belief.value,
                    confidence=belief.confidence,
                    origin_tick=t,
                    source_chain=list(belief.source_chain) or [actor.id],
                )
                msg = self.bus.dispatch(
                    sender_actor=actor.id,
                    recipient_actor=recipient.id,
                    origin_region=actor.region,
                    destination_region=recipient.region,
                    base_travel_ticks=travel,
                    dispatch_tick=t,
                    payload=report,
                )
                self.event_log.emit(
                    t,
                    "dispatch",
                    f"[{actor.region}] {actor.title} {actor.display_name} dispatches "
                    f"courier #{msg.id} → {recipient.region} "
                    f"(eta t={msg.eta_tick}, subject={subject}, value≈{report.estimated_value:.0f})",
                    message_id=msg.id,
                    sender=actor.id,
                    recipient=recipient.id,
                    eta_tick=msg.eta_tick,
                    subject=subject,
                    value=report.estimated_value,
                    confidence=report.confidence,
                )
            actor.last_report_tick = t

        # 5. deliver due messages — branch on kind
        for msg in self.bus.deliver_due(t):
            if msg.lost:
                self.event_log.emit(
                    t,
                    "courier_lost",
                    f"courier #{msg.id} ({msg.origin_region} → {msg.destination_region}) "
                    f"never arrived",
                    message_id=msg.id,
                    message_kind=msg.kind.value,
                    sender=msg.sender_actor,
                    recipient=msg.recipient_actor,
                )
                continue

            recipient = self.actors[msg.recipient_actor]

            if msg.kind == MessageKind.REPORT:
                transformed = relay(recipient, msg.payload, self.rng)
                recipient.update_belief(
                    transformed.subject,
                    transformed.estimated_value,
                    transformed.confidence,
                    t,
                    transformed.source_chain,
                )
                self.event_log.emit(
                    t,
                    "receive",
                    f"[{recipient.region}] {recipient.title} {recipient.display_name} receives "
                    f"courier #{msg.id} from {msg.sender_actor}: "
                    f"{transformed.subject} ≈ {transformed.estimated_value:.0f} "
                    f"(conf {transformed.confidence:.2f}, chain: {' → '.join(transformed.source_chain)})",
                    message_id=msg.id,
                    recipient=recipient.id,
                    subject=transformed.subject,
                    value=transformed.estimated_value,
                    confidence=transformed.confidence,
                    source_chain=transformed.source_chain,
                )
            else:  # ORDER
                recipient.inbox.append(msg.payload)
                self.event_log.emit(
                    t,
                    "order_delivered",
                    f"[{recipient.region}] {recipient.title} {recipient.display_name} receives "
                    f"order #{msg.payload.id} from {msg.sender_actor}: "
                    f"{msg.payload.kind.value} {msg.payload.target_region} "
                    f"(magnitude {msg.payload.magnitude:.0f})",
                    message_id=msg.id,
                    order_id=msg.payload.id,
                    recipient=recipient.id,
                    order_kind=msg.payload.kind.value,
                    target_region=msg.payload.target_region,
                    magnitude=msg.payload.magnitude,
                )

        # 7. decide — actors run their policies on cadence
        for actor in sorted(self.actors.values(), key=lambda a: a.id):
            if t - actor.last_decide_tick < actor.decide_every:
                continue
            run_policy(self, actor)
            actor.last_decide_tick = t

        # 8. resolve any actions whose completion tick is now
        remaining: list[ActionInFlight] = []
        for action in self.actions_in_flight:
            if action.complete_tick <= t:
                action.effect_fn(self)
            else:
                remaining.append(action)
        self.actions_in_flight = remaining

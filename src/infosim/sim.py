from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .actors import Actor
from .logging_setup import EventLog
from .messages import Message, MessageBus, MessageKind
from .personnel import Candidate
from .policies import run_policy
from .reports import Report, forge_value, observe, relay
from .scheduler import Event, EventKind, Scheduler
from .world import VARIABLES, World


FORGERY_THRESHOLD = 0.85  # loyalty above this -> no forgery (only saints are exempt).
                          # Below it, probability scales smoothly with (1-loyalty)^2.

ScriptedFn = Callable[["Simulation"], None]


@dataclass
class Simulation:
    """Discrete-event simulation engine.

    There is no global tick. Time advances to the next scheduled event. Each
    actor's cadences (observe_every / report_every / decide_every) are honoured
    by handlers that re-schedule the next event of the same kind after firing.

    Public API:
      - sim.schedule_scripted(time, fn) — fire fn(sim) at the given logical time
      - sim.run_until(stop_time)        — drain events up to (and including) stop_time
      - sim.now                         — current logical time (float)
    """
    world: World
    actors: dict[str, Actor]
    rng: random.Random
    event_log: EventLog
    scheduler: Scheduler = field(default_factory=Scheduler)
    bus: MessageBus = field(init=False)
    candidate_pool: list[Candidate] = field(default_factory=list)
    used_candidates: set[str] = field(default_factory=set)
    _order_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))
    _request_ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))
    _bootstrapped: bool = field(default=False, init=False)
    # Bus tuning is captured at construction time so dataclass init stays
    # ergonomic.
    bus_loss_prob: float = 0.05
    bus_jitter_frac: float = 0.2

    def __post_init__(self) -> None:
        self.bus = MessageBus(
            scheduler=self.scheduler,
            rng=self.rng,
            loss_prob=self.bus_loss_prob,
            jitter_frac=self.bus_jitter_frac,
        )

    @property
    def now(self) -> float:
        return self.scheduler.now

    @staticmethod
    def subject_for(actor_id: str, stat: str) -> str:
        """Belief subject key. ``"cmd_aldric.garrison_strength"`` means
        "estimate of cmd_aldric's garrison_strength stat." The dot-separator
        keeps the flat-dict scheme from M1 but reinterprets the LHS as an
        actor id rather than a region name.
        """
        return f"{actor_id}.{stat}"

    # ---- public scheduling -----------------------------------------------

    def schedule_scripted(self, when: float, fn: ScriptedFn) -> None:
        self.scheduler.schedule(when, Event(kind=EventKind.SCRIPTED, payload=fn))

    # ---- bootstrap -------------------------------------------------------

    def _bootstrap_actor_cadences(self) -> None:
        """Schedule each actor's first OBSERVE / REPORT / DECIDE at time 0.

        The 'first event fires immediately' behaviour is preserved from the
        previous tick-based model.
        """
        for actor in sorted(self.actors.values(), key=lambda a: a.id):
            self.scheduler.schedule(
                self.now,
                Event(kind=EventKind.OBSERVE, actor_id=actor.id),
            )
            self.scheduler.schedule(
                self.now,
                Event(kind=EventKind.REPORT, actor_id=actor.id),
            )
            self.scheduler.schedule(
                self.now,
                Event(kind=EventKind.DECIDE, actor_id=actor.id),
            )

    def schedule_actor_cadences(self, actor: Actor) -> None:
        """Schedule a freshly-appointed actor's first events one cadence ahead.

        Called from personnel.appoint() so a new appointee enters the rotation
        without firing instantly at their tenure start.
        """
        self.scheduler.schedule(
            self.now + actor.observe_every,
            Event(kind=EventKind.OBSERVE, actor_id=actor.id),
        )
        self.scheduler.schedule(
            self.now + actor.report_every,
            Event(kind=EventKind.REPORT, actor_id=actor.id),
        )
        self.scheduler.schedule(
            self.now + actor.decide_every,
            Event(kind=EventKind.DECIDE, actor_id=actor.id),
        )

    # ---- main loop -------------------------------------------------------

    def run_until(self, stop_time: float) -> None:
        if not self._bootstrapped:
            self._bootstrap_actor_cadences()
            self._bootstrapped = True

        while True:
            peek = self.scheduler.peek_next_time()
            if peek is None or peek > stop_time:
                # advance now to stop_time so end-of-run logging reflects the
                # caller's stop point even if no event fires there.
                self.scheduler.now = stop_time
                return
            popped = self.scheduler.pop_next()
            assert popped is not None
            _when, event = popped
            self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        if event.kind is EventKind.SCRIPTED:
            event.payload(self)
            return
        if event.kind is EventKind.MESSAGE_ARRIVED:
            self._handle_message(event.payload)
            return
        if event.kind is EventKind.ACTION_COMPLETE:
            event.payload.effect_fn(self)
            return
        if event.kind is EventKind.REQUEST_TIMEOUT:
            self._handle_request_timeout(event.actor_id, event.payload)
            return

        # Actor-keyed events (OBSERVE / REPORT / DECIDE). The actor may have
        # been dismissed since this event was scheduled — silently drop.
        actor = self.actors.get(event.actor_id) if event.actor_id else None
        if actor is None:
            return
        if event.kind is EventKind.OBSERVE:
            self._handle_observe(actor)
            self.scheduler.schedule(
                self.now + actor.observe_every,
                Event(kind=EventKind.OBSERVE, actor_id=actor.id),
            )
        elif event.kind is EventKind.REPORT:
            self._handle_report(actor)
            self.scheduler.schedule(
                self.now + actor.report_every,
                Event(kind=EventKind.REPORT, actor_id=actor.id),
            )
        elif event.kind is EventKind.DECIDE:
            run_policy(self, actor)
            self.scheduler.schedule(
                self.now + actor.decide_every,
                Event(kind=EventKind.DECIDE, actor_id=actor.id),
            )

    # ---- handlers --------------------------------------------------------

    def _handle_observe(self, actor: Actor) -> None:
        """Observe own stats with competence noise -> own belief.

        The actor's authoritative numbers (``actor.stats``) get filtered
        through their perception. Even an actor with perfect knowledge of
        their own resources may not perfectly perceive them — a
        low-competence commander undercounts garrison.
        """
        for stat, true_value in sorted(actor.stats.items()):
            subject = self.subject_for(actor.id, stat)
            report = observe(actor, subject, float(true_value), self.rng)
            report.origin_time = self.now
            actor.update_belief(
                subject,
                report.estimated_value,
                report.confidence,
                self.now,
                report.source_chain,
            )
            self.event_log.emit(
                self.now,
                "observation",
                f"[{actor.location}] {actor.title} {actor.display_name} observes "
                f"own {stat} ≈ {report.estimated_value:.0f} (true {true_value:.0f}, "
                f"conf {report.confidence:.2f})",
                actor=actor.id,
                location=actor.location,
                subject=subject,
                estimated_value=report.estimated_value,
                true_value=true_value,
                confidence=report.confidence,
            )

    def _handle_report(self, actor: Actor) -> None:
        if actor.commander is None:
            return
        if not actor.known:
            return
        recipient = self.actors.get(actor.commander)
        if recipient is None:
            return
        travel = self.world.travel_ticks(actor.location, recipient.location)
        for subject in sorted(actor.known.keys()):
            belief = actor.known[subject]
            outgoing_value = belief.value
            forged = False
            if actor.traits.loyalty < FORGERY_THRESHOLD:
                stat = subject.split(".", 1)[1]
                polarity = VARIABLES[stat].polarity
                is_bad_news = (
                    (polarity == +1 and belief.value < 1000.0) or
                    (polarity == -1 and belief.value > 20.0)
                )
                # Smooth probability — (1 - loyalty)^2 means mildly disloyal
                # actors lie occasionally rather than never; deeply disloyal
                # ones lie almost always. Ambition modulates appetite for
                # career-protective lies.
                disloyalty = 1.0 - actor.traits.loyalty
                forge_prob = actor.traits.ambition * disloyalty * disloyalty
                if is_bad_news and self.rng.random() < forge_prob:
                    severity = max(
                        0.0,
                        min(1.0, disloyalty * self.rng.uniform(0.5, 1.5)),
                    )
                    outgoing_value = forge_value(belief.value, stat, severity)
                    forged = True
                    self.event_log.emit(
                        self.now,
                        "report_forged",
                        f"[{actor.region}] {actor.title} {actor.display_name} forges "
                        f"{subject}: true belief {belief.value:.0f} → "
                        f"reported {outgoing_value:.0f} (loyalty {actor.traits.loyalty:.2f})",
                        actor=actor.id,
                        subject=subject,
                        true_belief=belief.value,
                        forged_value=outgoing_value,
                    )
            report = Report(
                source_actor=actor.id,
                subject=subject,
                estimated_value=outgoing_value,
                confidence=belief.confidence,
                origin_time=self.now,
                source_chain=list(belief.source_chain) or [actor.id],
            )
            msg = self.bus.dispatch(
                sender_actor=actor.id,
                recipient_actor=recipient.id,
                origin_region=actor.region,
                destination_region=recipient.region,
                base_travel_ticks=travel,
                dispatch_time=self.now,
                payload=report,
            )
            self.event_log.emit(
                self.now,
                "dispatch",
                f"[{actor.region}] {actor.title} {actor.display_name} dispatches "
                f"courier #{msg.id} → {recipient.region} "
                f"(eta t={msg.eta_time:.0f}, subject={subject}, "
                f"value≈{report.estimated_value:.0f})",
                message_id=msg.id,
                sender=actor.id,
                recipient=recipient.id,
                eta_time=msg.eta_time,
                subject=subject,
                value=report.estimated_value,
                confidence=report.confidence,
                forged=forged,
            )

    def _handle_message(self, msg: Message) -> None:
        if msg.lost:
            self.event_log.emit(
                self.now,
                "courier_lost",
                f"courier #{msg.id} ({msg.origin_region} → {msg.destination_region}) "
                f"never arrived",
                message_id=msg.id,
                message_kind=msg.kind.value,
                sender=msg.sender_actor,
                recipient=msg.recipient_actor,
            )
            return
        recipient = self.actors.get(msg.recipient_actor)
        if recipient is None:
            self.event_log.emit(
                self.now,
                "courier_undeliverable",
                f"courier #{msg.id} arrived at {msg.destination_region} but "
                f"recipient {msg.recipient_actor} no longer in office",
                message_id=msg.id,
                message_kind=msg.kind.value,
                intended_recipient=msg.recipient_actor,
            )
            return

        if msg.kind is MessageKind.REPORT:
            transformed = relay(recipient, msg.payload, self.rng)
            recipient.update_belief(
                transformed.subject,
                transformed.estimated_value,
                transformed.confidence,
                self.now,
                transformed.source_chain,
            )
            self.event_log.emit(
                self.now,
                "receive",
                f"[{recipient.region}] {recipient.title} {recipient.display_name} receives "
                f"courier #{msg.id} from {msg.sender_actor}: "
                f"{transformed.subject} ≈ {transformed.estimated_value:.0f} "
                f"(conf {transformed.confidence:.2f}, "
                f"chain: {' → '.join(transformed.source_chain)})",
                message_id=msg.id,
                recipient=recipient.id,
                subject=transformed.subject,
                value=transformed.estimated_value,
                confidence=transformed.confidence,
                source_chain=transformed.source_chain,
            )
        elif msg.kind is MessageKind.ORDER:
            recipient.inbox.append(msg.payload)
            self.event_log.emit(
                self.now,
                "order_delivered",
                f"[{recipient.location}] {recipient.title} {recipient.display_name} receives "
                f"order #{msg.payload.id} from {msg.sender_actor}: "
                f"{msg.payload.kind.value} {msg.payload.target_actor} "
                f"(magnitude {msg.payload.magnitude:.0f})",
                message_id=msg.id,
                order_id=msg.payload.id,
                recipient=recipient.id,
                order_kind=msg.payload.kind.value,
                target_actor=msg.payload.target_actor,
                magnitude=msg.payload.magnitude,
            )
        elif msg.kind is MessageKind.INFO_REQUEST:
            recipient.request_inbox.append((msg.sender_actor, msg.payload))
            self.event_log.emit(
                self.now,
                "request_delivered",
                f"[{recipient.location}] {recipient.title} {recipient.display_name} receives "
                f"INFO_REQUEST #{msg.payload.correlation_id} from {msg.sender_actor} "
                f"(originator {msg.payload.originator}, subjects {msg.payload.subjects})",
                message_id=msg.id,
                correlation_id=msg.payload.correlation_id,
                recipient=recipient.id,
                sender=msg.sender_actor,
                originator=msg.payload.originator,
                subjects=msg.payload.subjects,
                note=msg.payload.note,
            )
        elif msg.kind is MessageKind.INFO_RESPONSE:
            # Routed via the policy modules - they know how to relay vs consume.
            from .policies.info_requests import handle_info_response
            handle_info_response(self, recipient, msg.sender_actor, msg.payload)

    def _handle_request_timeout(self, actor_id: str | None, correlation_id: int) -> None:
        if actor_id is None:
            return
        actor = self.actors.get(actor_id)
        if actor is None:
            return
        pending = actor.pending_requests.pop(correlation_id, None)
        if pending is None:
            return  # already answered
        self.event_log.emit(
            self.now,
            "request_timeout",
            f"[{actor.location}] {actor.title} {actor.display_name} request "
            f"#{correlation_id} timed out (was waiting on {pending.waiting_for} "
            f"for {pending.subjects})",
            actor=actor.id,
            correlation_id=correlation_id,
            waiting_for=pending.waiting_for,
            subjects=pending.subjects,
        )
        # If this was a relay, send a refused response upstream so the
        # original asker can also clear their pending entry.
        if pending.parent_correlation_id is not None and pending.parent_from_actor is not None:
            from .policies.info_requests import dispatch_refusal_to_parent
            dispatch_refusal_to_parent(self, actor, pending, reason="downstream timeout")

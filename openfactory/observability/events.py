"""Job journal — a structured, queryable event stream (ADR-0001 D-13 telemetry).

Every meaningful step (state change, agent action, validation, review, PR) is a
JobEvent appended to a sink. This is the backbone that makes "ask the framework how
development is going — including what the agent is doing" answerable: a future
conversational surface (and the evals layer) reads this journal instead of scraping
logs. Sinks are pluggable — file now, Postgres later — behind one Protocol.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

log = logging.getLogger("openfactory.journal")

EventKind = Literal[
    "state", "agent_action", "validation", "review", "pr", "note", "warning", "error"
]


class JobEvent(BaseModel):
    ts: str  # ISO-8601 UTC
    job_id: str
    ticket_id: str
    kind: EventKind
    message: str
    data: dict = Field(default_factory=dict)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@runtime_checkable
class EventSink(Protocol):
    def emit(self, event: JobEvent) -> None:
        """Record an event. **NEVER RAISES** — see `_never_raises` below.

        The obligation is part of the contract, not of any one implementation, because a
        future sink written by someone else is reached from the same call sites."""
        ...


def _report(sink: object, exc: BaseException) -> None:
    """Say that an event was dropped — loudly the first time, quietly after that.

    Never a silent swallow: a journal that stopped writing and said nothing is
    indistinguishable from a factory that stopped working. But a full disk fails on EVERY
    event of a long job, and a warning each would drown the real ones — the same lesson
    `FileEventSink`'s dedup reader already learned one line at a time.
    """
    first = not getattr(sink, "_degraded", False)
    try:
        sink._degraded = True  # type: ignore[attr-defined]
    except AttributeError:  # a slotted or frozen third-party sink: stay loud rather than crash
        first = True
    (log.warning if first else log.debug)(
        "event sink %s dropped an event: %s", type(sink).__name__, exc
    )


def _never_raises(emit):
    """Decorator carrying the contract above onto one implementation.

    The journal is telemetry. A ticket abandoned mid-flight with partial work because a disk
    filled up has confused what the platform is FOR with what it REPORTS — and `machine.py::_emit`
    has no guard of its own, so whatever escapes a sink reaches the job. This is the obligation
    ADR-0022 §3 wrote into `say` ("returns whether it landed and never raises"), which the event
    sinks never inherited.

    `BaseException` is deliberately NOT caught. `KeyboardInterrupt` and `SystemExit` are not
    telemetry failures, and swallowing them here would make the process unkillable during a
    journal write — trading a dropped event for a box that will not stop.
    """

    @wraps(emit)
    def guarded(self, event: JobEvent) -> None:
        try:
            emit(self, event)
        except Exception as exc:
            _report(self, exc)

    return guarded


def _emit_isolated(sink: EventSink, event: JobEvent) -> None:
    """Emit through a sink the caller does not own, isolating its failure from the others.

    Distinct from `_never_raises`: that one holds a sink to the contract, this one protects a
    FAN-OUT from a sink that does not honour it (a third-party subscriber, or one of ours before
    its own guard runs). Without it, the first sink to fail costs every sink after it — and the
    file journal is registered before the live stdout feed, so a full disk would silently take
    away the one channel still capable of telling a human what happened.
    """
    try:
        sink.emit(event)
    except Exception as exc:
        _report(sink, exc)


class NullEventSink(EventSink):
    """Default: drops events (used when no journal is configured)."""

    def emit(self, event: JobEvent) -> None:
        return None


class InMemoryEventSink(EventSink):
    def __init__(self) -> None:
        self.events: list[JobEvent] = []

    def emit(self, event: JobEvent) -> None:
        self.events.append(event)


class FileEventSink(EventSink):
    """Append events as JSON-lines — greppable now, importable into a DB later.

    With dedup=True, an event whose identity (ts, job_id, kind, message) already exists
    in the file is skipped — so a retry that re-reads a remote task's log from the head
    can't duplicate the journal/panel feed (engineering.md #3)."""

    def __init__(self, path: Path, *, dedup: bool = False) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set[tuple] | None = None
        if dedup:
            self._seen = set()
            if path.exists():
                import json

                for line in path.read_text().splitlines():
                    try:
                        e = json.loads(line)
                        self._seen.add(self._key(e))
                    except (ValueError, TypeError):
                        # One malformed line in a journal is skipped rather than announced: this
                        # runs per line, and a warning each would drown the real ones.
                        log.debug("skipping an unreadable journal line")

    @staticmethod
    def _key(e: dict) -> tuple:
        return (e.get("ts"), e.get("job_id"), e.get("kind"), e.get("message"))

    @_never_raises
    def emit(self, event: JobEvent) -> None:
        if self._seen is not None:
            key = self._key(event.model_dump())
            if key in self._seen:
                return
            self._seen.add(key)
        with self.path.open("a") as f:
            f.write(event.model_dump_json() + "\n")


class StdoutEventSink(EventSink):
    """Stream events to stdout (→ CloudWatch in a Fargate task), so a remote job is
    never silent: every state change / action shows up live in the logs."""

    def __init__(self, prefix: str = "OPENFACTORY_EVENT:") -> None:
        self.prefix = prefix

    @_never_raises
    def emit(self, event: JobEvent) -> None:
        print(self.prefix + event.model_dump_json(), flush=True)


class TeeEventSink(EventSink):
    """Fan an event out to several sinks (e.g. file journal + live stdout).

    Each sink is isolated: one that fails costs its own event and nothing else. That matters
    because of the ORDER the box registers them — file journal first, live stdout second — so
    without isolation a full disk would take away the live feed too, which is the only channel
    that would still have reached a human.
    """

    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    def emit(self, event: JobEvent) -> None:
        for s in self.sinks:
            _emit_isolated(s, event)

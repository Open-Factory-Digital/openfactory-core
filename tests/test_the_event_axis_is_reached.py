"""The event-sink registry has callers (C-47, #90).

`EventSink` and `MetricSink` are ADR-0022's pattern one step earlier: two protocols that already
existed with no registry in front of them, so closing each was one registry and no port change.
The metrics registry was closed AND wired. The events registry was written, tested, and called by
nothing: every production site named the class —
`FileEventSink(...)` in five places, `TeeEventSink(FileEventSink(...), StdoutEventSink())` in two.

WHY IT HAD NO CALLERS IS THE INTERESTING PART, and it is not laziness. The shape the real code
needed — a file journal AND a live stdout feed — was not a row in the registry, so the common case
had to compose by hand, and once you are composing by hand the registry buys nothing. A registry
that cannot express the common case is a registry the common case routes around.

So `tee` is a row now, and `journal_for(path, live=…)` is the one call every site makes. A
deployment that wants OpenTelemetry, Loki or Postgres adds a row; before this it needed a patch in
seven places, in the module that exists to make defects visible.
"""

from __future__ import annotations

import pathlib

import pytest

from openfactory.observability.registry import (
    EVENT_SINKS,
    build_event_sink,
    event_sink_kind,
    journal_for,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Everywhere a journal is opened for real work.
CALL_SITES = [
    "openfactory/factory.py",
    "openfactory/runtime/temporal/activities.py",
    "openfactory/runtime/boxed_job.py",
    "openfactory/actions/catalog.py",
]


def test_no_call_site_names_a_sink_class():
    """The regression guard for the actual defect — the same shape as the harness axis's own
    `test_no_call_site_instantiates_a_concrete_harness`."""
    offenders = []
    for rel in CALL_SITES:
        src = (ROOT / rel).read_text()
        for name in ("FileEventSink(", "StdoutEventSink(", "TeeEventSink("):
            if name in src:
                offenders.append(f"{rel} constructs {name[:-1]}")
    assert offenders == [], offenders


def test_every_call_site_asks_the_registry():
    for rel in CALL_SITES:
        assert "journal_for" in (ROOT / rel).read_text(), rel


# ── the registry can express what the code needs ─────────────────────────────────────────────────

def test_the_common_case_is_a_ROW_not_a_hand_composition():
    """`tee` is why this registry had no callers: the boxed job wants both, and that was not
    expressible, so two call sites composed it themselves."""
    assert "tee" in EVENT_SINKS


def test_a_boxed_job_gets_file_and_stdout(tmp_path):
    from openfactory.observability.events import TeeEventSink

    assert isinstance(journal_for(tmp_path / "e.jsonl", live=True), TeeEventSink)


def test_a_plain_job_gets_the_file_alone(tmp_path):
    from openfactory.observability.events import FileEventSink

    assert isinstance(journal_for(tmp_path / "e.jsonl"), FileEventSink)


def test_a_live_feed_with_nowhere_to_write_is_stdout_only():
    """The sizing and split steps stream to the panel and have no Fargate task, so there is no
    per-job file to open. Building a `FileEventSink(None)` would crash the step."""
    from openfactory.observability.events import StdoutEventSink

    assert isinstance(journal_for(None, live=True), StdoutEventSink)


def test_a_deployment_can_override_every_journal(monkeypatch, tmp_path):
    """The whole point of an axis, and unreachable while seven places named a class."""
    from openfactory.observability.events import NullEventSink

    monkeypatch.setenv("OPENFACTORY_EVENT_SINK", "null")
    assert isinstance(journal_for(tmp_path / "e.jsonl", live=True), NullEventSink)
    assert event_sink_kind(live=True) == "null"


def test_an_unknown_kind_RAISES(monkeypatch):
    """Falling back would run a deployment with no journal, which looks exactly like a job that
    never started — the silent-stall failure this platform exists to make impossible."""
    with pytest.raises(ValueError, match="unknown event sink"):
        build_event_sink("loki", path=None)

"""The last two axes get a registry (C-11b).

ADR-0022 gave eight provider axes a `kind → builder` table resolved from configuration, with an
unknown kind raising rather than defaulting. Its audit never covered observability, so `EventSink`
and `MetricsSink` are honest Protocols with **no dispatch**: the composition root picks a concrete
class by hand in nine places.

That is the same pattern the ADR fixed everywhere else, one step earlier — and it is what stands
between a deployment and adding an OpenTelemetry sink without a code change. It is also what the
OSS distribution needs, because "SQLite instead of DynamoDB" has to be a configuration value, not
a different build.

Held to exactly the rules ADR-0022 wrote for the other eight:

    a table, not a conditional      one row per provider, resolved from config
    an unknown kind RAISES          naming what IS supported, at startup
    the contract is runtime-checked so a future sink cannot ship half-implemented
"""

from __future__ import annotations

import pytest

from openfactory.observability.events import EventSink
from openfactory.observability.metrics import MetricsSink
from openfactory.observability.registry import (
    EVENT_SINKS,
    METRICS_SINKS,
    build_event_sink,
    build_metrics_sink,
)

# ── the tables exist and dispatch ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,name", [(EVENT_SINKS, "event"), (METRICS_SINKS, "metrics")])
def test_every_axis_dispatches_through_a_table(table, name):
    assert isinstance(table, dict) and table, f"the {name}-sink axis has no dispatch table"


def test_the_event_sinks_that_exist_are_all_registered():
    assert {"null", "file", "stdout", "memory"} <= set(EVENT_SINKS)


def test_the_metrics_sinks_that_exist_are_all_registered():
    """The built-in rows. `dynamodb` is an add-on row now (`metrics.dynamodb` in the
    `openfactory.adapters` group) and is covered where the add-on is tested."""
    assert {"null", "sqlite", "memory"} <= set(METRICS_SINKS)
    assert "dynamodb" not in METRICS_SINKS, "the vendor row came back into the core table"


# ── an unknown kind raises, naming what is supported ────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["postgres", "otel", "typo", ""])
def test_an_unknown_event_sink_raises_rather_than_dropping_events(kind, tmp_path):
    """Falling back to Null would be the worst possible default: the factory would run with no
    journal at all, the panel would show an empty feed, and it would look exactly like a job that
    has not started."""
    with pytest.raises(ValueError, match="unknown event sink"):
        build_event_sink(kind, path=tmp_path / "j.jsonl")


@pytest.mark.parametrize("kind", ["postgres", "otel", "typo", ""])
def test_an_unknown_metrics_sink_raises_rather_than_dropping_telemetry(kind, tmp_path):
    with pytest.raises(ValueError, match="unknown metrics sink"):
        build_metrics_sink(kind, path=tmp_path / "m.db")


@pytest.mark.parametrize("build,kind", [(build_event_sink, "nope"), (build_metrics_sink, "nope")])
def test_the_error_names_what_IS_supported(build, kind, tmp_path):
    """ADR-0022's rule: actionable at startup, not merely a refusal."""
    with pytest.raises(ValueError) as e:
        build(kind, path=tmp_path / "x")
    assert "null" in str(e.value)


# ── what comes back satisfies the contract ──────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["null", "file", "stdout", "memory"])
def test_every_event_sink_satisfies_the_protocol(kind, tmp_path):
    assert isinstance(build_event_sink(kind, path=tmp_path / "j.jsonl"), EventSink)


@pytest.mark.parametrize("kind", ["null", "sqlite", "memory"])
def test_every_metrics_sink_satisfies_the_protocol(kind, tmp_path):
    assert isinstance(build_metrics_sink(kind, path=tmp_path / "m.db"), MetricsSink)


def test_the_sqlite_sink_is_wired_to_the_path_it_was_given(tmp_path):
    """A registry that built the right class against the wrong file would look correct and record
    nothing anybody reads."""
    from openfactory.observability.metrics import MetricRecord

    db = tmp_path / "sub" / "m.db"
    sink = build_metrics_sink("sqlite", path=db)
    sink.record(MetricRecord(project="demo", ticket="#1", ts="2026-08-02T10:00:00+00:00"))
    assert db.exists()


def test_the_file_sink_is_wired_to_the_path_it_was_given(tmp_path):
    from openfactory.observability.events import JobEvent, now_iso

    path = tmp_path / "sub" / "j.jsonl"
    build_event_sink("file", path=path).emit(
        JobEvent(ts=now_iso(), job_id="1", ticket_id="1", kind="state", message="x"))
    assert path.exists()


# ── resolution from the environment ─────────────────────────────────────────────────────────────

def test_the_default_metrics_sink_is_dynamodb_when_a_table_is_configured(monkeypatch, tmp_path):
    """The deployed behaviour must not change. A worker that silently started writing telemetry to
    a local file would lose the cost dashboard with nothing reporting it."""
    from openfactory.observability.registry import metrics_sink_kind

    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")
    monkeypatch.delenv("OPENFACTORY_METRICS_SINK", raising=False)
    assert metrics_sink_kind() == "dynamodb"


def test_the_default_metrics_sink_is_null_when_nothing_is_configured(monkeypatch):
    """Local dev with no AWS and no explicit choice: dropping telemetry is right, and it is what
    happens today."""
    from openfactory.observability.registry import metrics_sink_kind

    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    monkeypatch.delenv("OPENFACTORY_METRICS_SINK", raising=False)
    assert metrics_sink_kind() == "null"


def test_an_explicit_choice_beats_the_inferred_one(monkeypatch):
    """The OSS distribution says `sqlite` out loud. An inferred default that overrode it would
    make the compose file a lie."""
    from openfactory.observability.registry import metrics_sink_kind

    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    assert metrics_sink_kind() == "sqlite"


def test_an_unknown_configured_kind_fails_at_the_resolver_too(monkeypatch, tmp_path):
    """Resolving and building are two steps, and a typo must not survive the first one just to
    raise deep inside a job."""
    from openfactory.observability.registry import metrics_sink_kind

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "postgres")
    with pytest.raises(ValueError, match="unknown metrics sink"):
        build_metrics_sink(metrics_sink_kind(), path=tmp_path / "m.db")


# ── the reachability guard ──────────────────────────────────────────────────────────────────────

def test_the_worker_builds_its_metrics_sink_through_the_registry():
    """A registry nothing calls is the defect this repository has recorded nine times. The
    production path must go through it."""
    import inspect

    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities._metrics_sink)
    assert "build_metrics_sink" in src, (
        "_metrics_sink still picks a concrete class by hand — the registry is unreachable from "
        "the one place that matters"
    )

"""Which sink carries a deployment's telemetry — resolved from config, never from an import.

The last two axes to get what ADR-0022 gave the other eight. Its audit covered tracker, board,
forge, CI, channel, notifier, harness and sandbox; `EventSink` and `MetricsSink` were honest
Protocols with **no dispatch**, so the composition root picked a concrete class by hand in nine
places. Same pattern, one step earlier.

Two things depend on closing it. A deployment that wants OpenTelemetry, Loki or Postgres should add
a row rather than a patch — `TeeEventSink` already makes the fan-out free, and this is the other
half. And the OSS distribution needs "SQLite instead of DynamoDB" to be a configuration value, not
a different build.

The rules are copied from `agent/registry.py` rather than invented, so there is one to learn:

    a table, not a conditional      one row per provider
    an unknown kind RAISES          naming what IS supported, at startup

The raise matters more here than it looks. Falling back to Null would be the worst available
default: the factory would run with no journal, the panel would show an empty feed, and it would
look exactly like a job that has not started — which is the silent-stall failure this platform is
built to make impossible.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

#: Where a local journal or database lands when the caller does not say.
DEFAULT_EVENT_SINK = "file"


def _null_event(**_kw):
    from openfactory.observability.events import NullEventSink

    return NullEventSink()


def _file_event(**kw):
    from openfactory.observability.events import FileEventSink

    return FileEventSink(Path(kw["path"]), dedup=bool(kw.get("dedup")))


def _stdout_event(**kw):
    from openfactory.observability.events import StdoutEventSink

    return StdoutEventSink(**({"prefix": kw["prefix"]} if kw.get("prefix") else {}))


def _memory_event(**_kw):
    from openfactory.observability.events import InMemoryEventSink

    return InMemoryEventSink()


def _stdout_only_if_pathless(kw: dict) -> bool:
    """A live feed with nowhere to write is legitimate: the sizing and split steps stream to the
    panel and have no Fargate task, so there is no per-job journal file to open."""
    return not kw.get("path")


def _tee_event(**kw):
    """A file journal AND a live stdout feed — what every boxed job actually wants.

    The Fargate entrypoint composed this by hand (`TeeEventSink(FileEventSink(...),
    StdoutEventSink())`), and that hand-composition is why the registry had no callers: the shape
    the real code needed was not a row in it. A registry that cannot express the common case is a
    registry the common case routes around."""
    from openfactory.observability.events import TeeEventSink

    if _stdout_only_if_pathless(kw):
        return _stdout_event(**kw)
    return TeeEventSink(_file_event(**kw), _stdout_event(**kw))


#: kind → builder. A new sink joins as one row plus its module; nothing else changes.
EVENT_SINKS: dict[str, Callable[..., object]] = {
    "null": _null_event,
    "file": _file_event,
    "stdout": _stdout_event,
    "tee": _tee_event,
    "memory": _memory_event,
}


def _null_metrics(**_kw):
    from openfactory.observability.metrics import NullMetricsSink

    return NullMetricsSink()


def _sqlite_metrics(**kw):
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    return SqliteMetricsSink(kw["path"])


def _memory_metrics(**_kw):
    from openfactory.observability.metrics import InMemoryMetricsSink

    return InMemoryMetricsSink()


#: The built-in rows. THE VENDOR ROW IS NOT HERE ANY MORE: `dynamodb` registers through the
#: `openfactory.adapters` entry-point group (`metrics.dynamodb`, declared by the
#: `openfactory-aws` package — `addons/openfactory-aws/pyproject.toml` in the private tree),
#: exactly as a stranger's Postgres sink would — so the core imports nothing from
#: `observability/dynamo.py`, and deleting that file leaves this registry whole. The kind is still
#: what `metrics_sink_kind` infers from a configured table, and a deployment that names it without
#: the add-on installed is refused by name, listing what IS installed.
METRICS_SINKS: dict[str, Callable[..., object]] = {
    "null": _null_metrics,
    "sqlite": _sqlite_metrics,
    "memory": _memory_metrics,
}

#: What each SHIPPED metrics sink is addressed by — and none of them is a table. A reader's or a
#: deleter's `table=` override is a keyword only a table-shaped add-on (the vendor row) honours,
#: so a shipped kind handed one is refused BY NAME in `configured_metrics_sink`, never by its
#: builder dying on a keyword it does not take: `_sqlite_metrics` reads `kw["path"]`, so the
#: override alone was a `KeyError: 'path'`, and `memory` built a fresh empty store and handed it
#: to the deleter as though it held the named table (measured by the review, 2026-08-26). A row
#: added to `METRICS_SINKS` without an entry here is caught by the guard, not by a KeyError.
TABLELESS_METRICS_SINKS: dict[str, str] = {
    "null": "nothing — it declares no store at all",
    "sqlite": "a file, OPENFACTORY_METRICS_DB",
    "memory": "this process's memory",
}

#: The entry-point axis names: `event.<kind>` and `metrics.<kind>`.
EVENT_AXIS = "event"
METRICS_AXIS = "metrics"


def _built(builder, axis: str, kind: str, table: dict, /, **kw):
    """`/` because `table` is ALSO a legitimate sink kwarg (a DynamoDB table name), and without
    the positional-only marker `build_metrics_sink(kind, table=…)` collided with this function's
    own parameter — so EVERY message write through the worker's configured sink died with
    "got multiple values for argument 'table'", swallowed by `messages.write`'s never-raise rule.
    The panel's whole proactive voice was delivered to that exception for as long as this registry
    has existed; found the first minute a PanelNotifier actually tried to speak.

    The refusal lists what is installed as well as what is shipped (`plugins.known`), so a
    stranger who installed an add-on and typo'd its kind sees their own row in the list."""
    if builder is None:
        from openfactory import plugins

        known = ", ".join(plugins.known(axis, table))
        raise ValueError(f"unknown {axis} sink {kind!r} — known: {known}"
                         f"{plugins.install_hint(axis, _key(kind))}")
    return builder(**kw)


def _key(kind: str) -> str:
    return (kind or "").strip().lower()


def build_event_sink(kind: str, **kw):
    """The journal for this deployment. Raises on an unknown kind — see the module docstring.
    A built-in row wins; an add-on's row (`event.<kind>` entry point) fills the rest."""
    from openfactory import plugins

    key = _key(kind)
    builder = EVENT_SINKS.get(key) or plugins.builder(EVENT_AXIS, key, builtin=EVENT_SINKS)
    return _built(builder, EVENT_AXIS, kind, EVENT_SINKS, **kw)


def event_sink_kind(*, live: bool = False) -> str:
    """Which event sink this process wants.

    `live` is the one thing the call sites actually varied: a boxed job wants its journal on disk
    AND streamed to the panel, everything else wants the file alone. Naming that here is what lets
    every call site ask instead of construct — `OPENFACTORY_EVENT_SINK` then overrides the lot,
    which is
    the whole point of the axis and was unreachable while nine places named a class."""
    explicit = (os.environ.get("OPENFACTORY_EVENT_SINK") or "").strip().lower()
    return explicit or ("tee" if live else DEFAULT_EVENT_SINK)


def journal_for(path, *, live: bool = False, dedup: bool = False):
    """The journal for one job, resolved. The one call every site should make."""
    return build_event_sink(event_sink_kind(live=live), path=path, dedup=dedup)


def build_metrics_sink(kind: str, **kw):
    """The telemetry store for this deployment. Raises on an unknown kind. A built-in row wins;
    an add-on's row (`metrics.<kind>` entry point) fills the rest — which is where `dynamodb`
    lives now."""
    from openfactory import plugins

    key = _key(kind)
    builder = METRICS_SINKS.get(key) or plugins.builder(METRICS_AXIS, key, builtin=METRICS_SINKS)
    return _built(builder, METRICS_AXIS, kind, METRICS_SINKS, **kw)


def metrics_sink_kind() -> str:
    """Which metrics sink this deployment wants.

    An explicit `OPENFACTORY_METRICS_SINK` wins, because the OSS compose file says `sqlite` out loud
    and
    an inferred default that overrode it would make that file a lie.

    Otherwise the answer is inferred exactly as it was before this registry existed: DynamoDB when
    `OPENFACTORY_METRICS_TABLE` names a table (the deployed worker, set by terraform), else Null.
    Changing
    that inference would have silently moved a live deployment's cost dashboard, which is the one
    instrument every other decision here is measured on.
    """
    explicit = (os.environ.get("OPENFACTORY_METRICS_SINK") or "").strip().lower()
    if explicit:
        return explicit
    return "dynamodb" if os.environ.get("OPENFACTORY_METRICS_TABLE") else "null"


def configured_metrics_sink(**kw):
    """The sink this deployment DECLARES, built with the caller's overrides — the one door for a
    reader or a deleter that names a table (`table=`, `region=`).

    THE KIND IS NEVER THE CALLER'S TO SAY. Three core readers spelled the vendor's kind by heart
    here — `build_metrics_sink("dynamodb", table=…)` — so `table_name=` MEANT one vendor while the
    import-graph guard, which cannot see a string, stayed green. Now the override points the
    CONFIGURED sink at another table, whatever kind the registry or the environment says it is: a
    third-party sink with a table receives it, and a deployment whose sink holds no table —
    `null`, or a shipped sink addressed by something else (`TABLELESS_METRICS_SINKS`) — is
    refused by name, with the configured kind in the sentence, rather than handed a null store
    that drops the override in silence or a builder that dies on a keyword it never took."""
    kind = metrics_sink_kind()
    key = _key(kind)
    if kw.get("table") and key in TABLELESS_METRICS_SINKS:
        raise ValueError(
            f"a metrics table {kw['table']!r} was named, but this deployment's metrics sink is "
            f"{key!r}, which holds no table (it is addressed by {TABLELESS_METRICS_SINKS[key]}) "
            f"— set OPENFACTORY_METRICS_SINK to the sink that holds it")
    return build_metrics_sink(kind, **kw)

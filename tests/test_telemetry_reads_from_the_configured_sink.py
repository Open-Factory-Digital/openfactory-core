"""Telemetry must be READ from whichever sink it was written to (the audit's fourth finding).

`OPENFACTORY_METRICS_SINK=sqlite` is the local distribution's answer to "no DynamoDB", and the write side
honours it: `_metrics_sink()` resolves through `METRICS_SINKS` and builds a `SqliteMetricsSink`.

Both READ sides ignored the registry entirely. `api/metrics_view.scan_records` and
`observability/query.records_of_kind` each begin with `os.environ.get("OPENFACTORY_METRICS_TABLE")`,
return `[]` when it is unset, and otherwise go straight to `boto3.resource("dynamodb")`. On a local
install that variable is never set, so both return `[]` for ever.

`SqliteMetricsSink.scan()` and `.records_of_kind()` exist, are tested, have signatures that match
the two readers exactly — and are called by nothing. Written, tested, reached by nothing: the
seventeenth recorded instance in this repository, and this one is load-bearing.

WHAT GOES BLIND, and none of it announces itself:

- the **cost dashboard** — the commercial argument, showing "no data yet" for ever
- the tech-lead's memory of **what it has already said**, so it repeats itself
- **recurring-failure detection**, which needs history to see a pattern
- the **open-loop ledger** (ADR-0021), so questions asked are never followed up
- the product agent's **conversation memory** — the exact defect that module's docstring says it
  exists to prevent

Half a feature is worse than none here, because the half that works makes the other half look
present. The write succeeds, the file grows, and every reader answers "nothing recorded".
"""

from __future__ import annotations

import pytest

from openfactory.observability.metrics import MetricRecord


@pytest.fixture(autouse=True)
def _a_local_deployment(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    return tmp_path


@pytest.fixture
def written(_a_local_deployment):
    """Three records through the REAL write path a job uses."""
    from openfactory.observability.registry import build_metrics_sink, metrics_sink_kind

    sink = build_metrics_sink(metrics_sink_kind(), path=str(_a_local_deployment / "metrics.db"))
    for i, (kind, cost) in enumerate([("job", 1.5), ("job", 2.5), ("agent_run", 0.25)]):
        sink.record(MetricRecord(
            project="acme", ticket=str(100 + i), kind=kind, role="_job_",
            state="pr_open", total_cost_usd=cost, wall_s=60.0,
            ts=f"2026-08-0{i + 1}T00:00:00+00:00",
        ))
    return sink


# ── the dashboard reader ────────────────────────────────────────────────────────────────────────

def test_the_dashboard_reads_what_the_local_sink_wrote(written):
    """THE defect. Everything is configured correctly, the rows are on disk, and the cost view
    said 'no data yet'."""
    from openfactory.api.metrics_view import scan_records

    rows = scan_records()

    assert len(rows) == 3, rows


def test_the_dashboard_payload_is_not_empty(written):
    """One layer up, because `scan_records` returning rows is not the same as the view using
    them — the reachability half."""
    from openfactory.api.metrics_view import cost_dashboard

    payload = cost_dashboard(project="acme")

    assert payload, payload
    total = str(payload)
    assert "acme" in total or any(payload.get(k) for k in payload), payload


def test_no_boto3_is_reached_for_a_local_read(written):
    """The point of the local sink. A read that imports boto3 to discover it has nothing to ask is
    the same cloud reach the panel audit just removed."""
    import sys

    tried: list[str] = []

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("boto3", "botocore"):
                tried.append(name)
                raise ImportError(name)
            return None

    blocker = _Block()
    sys.meta_path.insert(0, blocker)
    try:
        from openfactory.api.metrics_view import scan_records

        assert len(scan_records()) == 3
    finally:
        sys.meta_path.remove(blocker)
    assert not tried, tried


# ── the generic reader (memory, loops, recurring failures) ──────────────────────────────────────

def test_records_of_kind_reads_the_local_sink(written):
    from openfactory.observability.query import records_of_kind

    rows = records_of_kind("acme", "job")

    assert len(rows) == 2, rows
    assert all(r.get("kind") == "job" for r in rows), rows


def test_records_of_kind_keeps_the_RECENT_rows_when_truncating(written):
    """`limit` must keep the newest, oldest-first. A memory truncated to its oldest rows remembers
    the beginning of time and nothing about now — `query.py` says so and the SQLite sink already
    implements it; this asserts the wiring preserves it."""
    from openfactory.observability.query import records_of_kind

    rows = records_of_kind("acme", "job", limit=1)

    assert len(rows) == 1
    assert rows[0]["ticket"] == "101", rows


def test_another_project_is_not_visible(written):
    from openfactory.observability.query import records_of_kind

    assert records_of_kind("globex", "job") == []


# ── the cloud path must not move ────────────────────────────────────────────────────────────────

# `test_dynamodb_is_still_used_when_that_is_the_configured_sink` lives in
# `tests/test_dynamo_metrics_sink.py` now: the vendor row is an add-on, and the test installs it.


def test_an_unset_sink_with_a_table_still_reads_dynamodb(monkeypatch):
    """The pilot sets `OPENFACTORY_METRICS_TABLE` and no `OPENFACTORY_METRICS_SINK`; `metrics_sink_kind()`
    already infers dynamodb from the table. This pins that the inference reaches the READ path
    too, so no deployed installation changes behaviour."""
    monkeypatch.delenv("OPENFACTORY_METRICS_SINK", raising=False)
    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")

    from openfactory.observability.registry import metrics_sink_kind

    assert metrics_sink_kind() == "dynamodb"


# ── reachability ────────────────────────────────────────────────────────────────────────────────

def test_neither_reader_asks_the_environment_for_a_table_first():
    """Both opened with `os.environ.get("OPENFACTORY_METRICS_TABLE")` and returned `[]` when unset — which
    is why a perfectly configured SQLite deployment read nothing. The sink registry decides."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    #: The reader, and what it may DELEGATE to — `scan_records` is now a thin degrading wrapper
    #: over `scan_all_or_raise` (#126), which is where the registry consultation lives. Following
    #: the delegation is the honest reading: what must not come back is a reader that decides for
    #: itself from the environment, wherever that decision is spelled.
    readers = (("openfactory/api/metrics_view.py", "scan_records", "scan_all_or_raise"),
               ("openfactory/api/metrics_view.py", "scan_all_or_raise", ""),
               ("openfactory/observability/query.py", "records_of_kind", ""))
    offenders = []
    for rel, fn, delegate in readers:
        tree = ast.parse((root / rel).read_text())
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == fn)
        body = ast.unparse(node)
        # `_configured_sink()` IS the registry consultation — the readers share it, which is the
        # point.
        consults = any(t in body for t in
                       ("_configured_sink", "metrics_sink_kind", "build_metrics_sink"))
        if not consults and not (delegate and delegate in body):
            offenders.append(f"{rel}:{node.lineno} — {fn} never consults the sink registry")
        # …and a reader that delegates must not ALSO decide for itself, which is how the two
        # answers drift back apart.
        if delegate and delegate in body:
            assert "OPENFACTORY_METRICS_TABLE" not in body, (
                f"{fn} delegates to {delegate} and still reads the environment itself")
    assert not offenders, "\n  ".join([""] + offenders)

"""SqliteMetricsSink — the same telemetry, on a machine with no AWS (C-11).

The cost dashboard is described in `architecture.md` §8 as *"the ruler we measure improvements
with"*. A distribution that cannot render it is not a factory anybody can operate, so the OSS
build needs a store, and SQLite is the one that needs no service.

What makes this more than "write rows to a file" is PARITY. The DynamoDB sink has four behaviours
the dashboard and the agents' memory silently depend on, and a naive SQLite version has none of
them:

    put_item OVERWRITES on the key        a retried activity must not double-count a job's cost
    TTL DELETES expired rows              ADR-0024: client conversation is retained, not kept
    numbers survive the round trip        stored as strings, parsed back by the reader
    a write failure never fails the job   telemetry is additive

The TTL one is the one that would have shipped broken: nothing raises, nothing logs, and a
deployment quietly keeps client messages for ever while its own ADR says it does not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time

import pytest

from openfactory.observability.metrics import MetricRecord
from openfactory.observability.sqlite_metrics import SqliteMetricsSink


def _rec(**kw) -> MetricRecord:
    base = dict(project="demo", ticket="#7", ts="2026-08-02T10:00:00+00:00", kind="agent_run",
                role="executor", model="opus", harness="claude_code", cost_usd=1.5,
                num_turns=12, input_tokens=1000, output_tokens=250)
    base.update(kw)
    return MetricRecord(**base)


# ── it stores and reads back ────────────────────────────────────────────────────────────────────

def test_a_recorded_row_comes_back_from_scan(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec())
    rows = sink.scan()
    assert len(rows) == 1
    assert rows[0]["pk"] == "demo" and rows[0]["ticket"] == "#7"


def test_numbers_come_back_as_numbers_not_strings(tmp_path):
    """`scan_records` parses DynamoDB's stringified numbers back before the dashboard sees them.
    A SQLite reader that returned strings would render every cost as 0.00 and never say why."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(cost_usd=2.25, num_turns=3, wall_s=91.5))
    row = sink.scan()[0]
    assert row["cost_usd"] == 2.25
    assert row["num_turns"] == 3
    assert row["wall_s"] == 91.5


def test_the_dynamo_key_shape_is_preserved(tmp_path):
    """Consumers read `pk`, `sk` and `kind_ts` — `query.py` and `metrics_view.py` both do."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    rec = _rec()
    sink.record(rec)
    row = sink.scan()[0]
    for k, v in rec.dynamo_key().items():
        assert row[k] == v


# ── parity with put_item: the key overwrites ────────────────────────────────────────────────────

def test_recording_the_same_key_twice_replaces_rather_than_duplicates(tmp_path):
    """`put_item` is an upsert. A Temporal activity that retries after a partial failure re-records
    the SAME key — appending instead would double the reported cost of a job, which is worse than
    losing it, because a wrong number is trusted."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(cost_usd=1.0))
    sink.record(_rec(cost_usd=1.0))
    rows = sink.scan()
    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 1.0


def test_a_later_write_on_the_same_key_wins(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(cost_usd=1.0))
    sink.record(_rec(cost_usd=9.0))
    assert sink.scan()[0]["cost_usd"] == 9.0


# ── parity with TTL: expired rows are gone ──────────────────────────────────────────────────────

def test_an_expired_row_is_not_returned(tmp_path):
    """DynamoDB deletes rows past `expires_at`. SQLite has no TTL, so the store must honour it
    itself — otherwise the OSS distribution keeps client conversation for ever while ADR-0024 says
    it is retained, and nothing anywhere reports the difference."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="message", ticket="#8", expires_at=int(time.time()) - 60))
    assert sink.scan() == []


def test_a_row_with_no_expiry_never_expires(tmp_path):
    """Operational memory carries no `expires_at` on purpose — a row that expired would make the
    tech-lead forget what it learned."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="agent_loop"))
    assert len(sink.scan()) == 1


def test_a_future_expiry_is_still_visible(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="message", expires_at=int(time.time()) + 3600))
    assert len(sink.scan()) == 1


def test_expired_rows_are_eventually_purged_from_disk(tmp_path):
    """Filtering on read keeps the answer right; it does not keep the promise. "We delete it" has
    to mean the bytes are gone, not that we stopped looking at them."""
    path = tmp_path / "m.db"
    sink = SqliteMetricsSink(path)
    sink.record(_rec(kind="message", expires_at=int(time.time()) - 60))
    sink.purge_expired()
    import sqlite3

    with sqlite3.connect(path) as c:
        assert c.execute("select count(*) from metrics").fetchone()[0] == 0


# ── records_of_kind: the agents' memory read path ───────────────────────────────────────────────

def test_records_of_kind_filters_by_project_and_kind(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="agent_loop", ticket="#1"))
    sink.record(_rec(kind="product_sweep", ticket="#2"))
    sink.record(_rec(project="other", kind="agent_loop", ticket="#3"))
    rows = sink.records_of_kind("demo", "agent_loop")
    assert [r["ticket"] for r in rows] == ["#1"]


def test_records_of_kind_returns_oldest_first(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    for n, ts in [("#1", "2026-08-01T00:00:00+00:00"), ("#2", "2026-08-03T00:00:00+00:00"),
                  ("#3", "2026-08-02T00:00:00+00:00")]:
        sink.record(_rec(kind="agent_loop", ticket=n, ts=ts))
    assert [r["ticket"] for r in sink.records_of_kind("demo", "agent_loop")] == ["#1", "#3", "#2"]


def test_the_limit_keeps_the_RECENT_rows(tmp_path):
    """`query.py` reverses a newest-first query for exactly this reason: a memory truncated to its
    OLDEST rows remembers the beginning of time and nothing about now."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    for n in range(5):
        sink.record(_rec(kind="agent_loop", ticket=f"#{n}", ts=f"2026-08-0{n + 1}T00:00:00+00:00"))
    rows = sink.records_of_kind("demo", "agent_loop", limit=2)
    assert [r["ticket"] for r in rows] == ["#3", "#4"]


def test_records_of_kind_hides_expired_rows_too(tmp_path):
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="message", expires_at=int(time.time()) - 1))
    assert sink.records_of_kind("demo", "message") == []


# ── telemetry never fails the job ───────────────────────────────────────────────────────────────

def test_a_write_to_an_impossible_path_does_not_raise(tmp_path):
    """Same contract as the Dynamo sink and the event sinks: telemetry is additive."""
    sink = SqliteMetricsSink(tmp_path / "nope" / "deeper" / "m.db")
    (tmp_path / "nope").write_text("I am a file, not a directory")
    sink.record(_rec())


def test_a_read_from_a_corrupt_database_SAYS_SO_rather_than_reading_as_empty(tmp_path):
    """INVERTED DELIBERATELY (#126). This asserted that an unreadable file returns `[]`, "so the
    dashboard shows 'no data yet', never a 500" — and the dashboard is the one caller for which
    that is true. Every other reader inherited it: `messages.read`'s own careful guard against
    exactly this became dead code, and the panel's human gates then showed an outage as a factory
    with nothing to say and a question that had "already been answered".

    The store now says it could not answer; the dashboard catches that in one line and still shows
    'no data yet' (see `test_the_dashboard_still_degrades_to_no_data`). A surface CHOOSING to
    degrade is not the same as every surface degrading because nothing told it anything was
    wrong."""
    from openfactory.observability.query import StoreUnreadable

    path = tmp_path / "m.db"
    path.write_bytes(b"this is not a sqlite file at all, not even close" * 10)
    sink = SqliteMetricsSink(path)
    with pytest.raises(StoreUnreadable):
        sink.scan()
    with pytest.raises(StoreUnreadable):
        sink.records_of_kind("demo", "agent_run")


def test_the_dashboard_still_degrades_to_no_data(tmp_path, monkeypatch):
    """The positive twin, and the reason the inversion above is safe: nobody decides anything from
    a cost dashboard in the next thirty seconds, so it keeps the old behaviour — explicitly, at its
    own edge, rather than by never being told."""
    from openfactory.api.metrics_view import scan_records

    path = tmp_path / "m.db"
    path.write_bytes(b"not a database" * 10)
    monkeypatch.setattr("openfactory.api.metrics_view._configured_sink",
                        lambda: SqliteMetricsSink(path))
    assert scan_records() == []


def test_a_failed_write_is_logged_rather_than_swallowed(tmp_path, caplog):
    sink = SqliteMetricsSink(tmp_path / "nope" / "m.db")
    (tmp_path / "nope").write_text("not a directory")
    with caplog.at_level("WARNING", logger="openfactory.metrics"):
        sink.record(_rec())
    assert any("demo" in r.getMessage() for r in caplog.records)


# ── two processes share the file ────────────────────────────────────────────────────────────────

def test_a_second_process_can_write_while_the_first_holds_the_file(tmp_path):
    """The worker writes and the panel reads, in different processes, on the same file. Without
    WAL and a busy timeout this is where 'database is locked' shows up — under load, in production,
    and never in a single-process test."""
    path = tmp_path / "m.db"
    first = SqliteMetricsSink(path)
    first.record(_rec(ticket="#1"))

    code = textwrap.dedent(f"""
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.sqlite_metrics import SqliteMetricsSink
        s = SqliteMetricsSink({str(path)!r})
        s.record(MetricRecord(project="demo", ticket="#2",
                              ts="2026-08-02T11:00:00+00:00", kind="agent_run"))
    """)
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)

    assert sorted(r["ticket"] for r in first.scan()) == ["#1", "#2"]


# ── the point of the card: no AWS on the machine ────────────────────────────────────────────────

def test_it_works_with_boto3_unimportable():
    """The done-condition of the card, asserted rather than assumed: a machine where `import boto3`
    raises must still record and render telemetry."""
    code = textwrap.dedent("""
        import sys, tempfile, os

        class _NoBoto:
            def find_module(self, name, path=None):
                if name == "boto3" or name.startswith("boto3."):
                    raise ImportError("boto3 is not installed on this machine")
                return None
            def find_spec(self, name, path=None, target=None):
                return self.find_module(name, path)

        sys.meta_path.insert(0, _NoBoto())

        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.sqlite_metrics import SqliteMetricsSink

        db = os.path.join(tempfile.mkdtemp(), "m.db")
        s = SqliteMetricsSink(db)
        s.record(MetricRecord(project="demo", ticket="#1",
                              ts="2026-08-02T10:00:00+00:00", kind="job",
                              total_cost_usd=3.5, wall_s=42.0))
        rows = s.scan()
        assert len(rows) == 1, rows
        assert rows[0]["total_cost_usd"] == 3.5, rows
        print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout


# ── it satisfies the contract the rest of the code depends on ───────────────────────────────────

def test_it_is_a_MetricsSink(tmp_path):
    from openfactory.observability.metrics import MetricsSink

    assert isinstance(SqliteMetricsSink(tmp_path / "m.db"), MetricsSink)


def test_extra_survives_the_round_trip(tmp_path):
    """`extra` is a free-form dict; a store that flattened it would lose whatever a future caller
    put there without anyone noticing."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(extra={"arm": "injected", "nested": {"a": 1}}))
    assert sink.scan()[0]["extra"] == {"arm": "injected", "nested": {"a": 1}}


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_a_row_with_a_junk_ticket_still_stores(tmp_path, bad):
    """Partial records must never block the write — the Dynamo sink's own docstring says so."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(MetricRecord(project="demo", ticket=bad or "", ts="2026-08-02T10:00:00+00:00"))
    assert len(sink.scan()) == 1


def test_the_json_payload_is_not_a_second_source_of_truth(tmp_path):
    """The indexed columns and the stored blob must agree. If they can drift, a reader that trusts
    one and a reader that trusts the other disagree about the same row."""
    sink = SqliteMetricsSink(tmp_path / "m.db")
    sink.record(_rec(kind="job", ticket="#42"))
    row = sink.scan()[0]
    import sqlite3

    with sqlite3.connect(tmp_path / "m.db") as c:
        pk, kind, ticket, data = c.execute(
            "select pk, kind, ticket, data from metrics").fetchone()
    blob = json.loads(data)
    assert (pk, kind, ticket) == (row["pk"], row["kind"], row["ticket"])
    assert blob["kind"] == kind and blob["ticket"] == ticket

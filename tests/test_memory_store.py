"""Persistence for the open-loop ledger (ADR-0021 §3) — and the read path it must not use.

The infra question the product owner asked, answered concretely: the memory needed an INDEX, not a
database.
Every read was `scan_records()` — a full table scan across every project, every agent run and every
job since the beginning, filtered in Python, on the one path all of the agents' memory depends on.
"""

from __future__ import annotations

import ast
from pathlib import Path

from openfactory.memory import store
from openfactory.memory.ledger import CLOSED, QUESTION, REMEDY, close_by_observation, open_loop
from openfactory.observability.metrics import InMemoryMetricsSink, MetricRecord


def _rows(sink) -> list[dict]:
    return [{"kind": r.kind, "pk": r.project, "ts": r.ts, "extra": r.extra} for r in sink.records]


def test_the_row_timestamp_is_when_it_was_RECORDED_not_when_the_loop_opened():
    """An earlier version reused the loop's own `ts` and appended the state for uniqueness, so
    `T1#closed` sorted before `T1#open` — the closing row arrived, in the record, before the thing
    it closed. A ledger whose chronology is wrong is worse than no ledger: everything read from it
    is confidently out of order."""
    sink = InMemoryMetricsSink()
    opened = open_loop(REMEDY, "478", owner="techlead", ts="OPENED-AT")
    store.write("books", [opened], sink=sink, now="2026-07-27T10:00:00")
    rec = sink.records[0]
    assert rec.ts == "2026-07-27T10:00:00"
    assert rec.extra["opened_ts"] == "OPENED-AT", "the loop's identity was lost"


def test_a_loop_survives_a_write_and_a_read():
    sink = InMemoryMetricsSink()
    loop = open_loop(QUESTION, "t-1", owner="product", ts="T1",
                     context={"person": "alice", "asked": "qual formato?"})
    assert store.write("books", [loop], sink=sink) == 1
    back = store.read("books", scan=lambda: _rows(sink))
    assert back == [loop], "a loop did not survive the round trip"


def test_closing_APPENDS_so_both_rows_survive():
    """Append-only is the property that makes the record trustworthy — an agent must not be able to
    quietly improve its own history."""
    sink = InMemoryMetricsSink()
    opened = open_loop(REMEDY, "478", owner="techlead", about="throttled", ts="T1")
    store.write("books", [opened], sink=sink, now="2026-07-27T10:00:00")
    # the observation key carries the loop's `about` — closing "478" with a blank signature must
    # NOT touch a loop opened about "throttled" (that mismatch staying open is the whole point)
    store.write("books",
                close_by_observation([opened], {(REMEDY, "478", "throttled"): "worked"}),
                sink=sink, now="2026-07-27T11:00:00")
    assert len(sink.records) == 2, "closing overwrote the opening row"
    folded = store.read("books", scan=lambda: _rows(sink))
    assert [x.state for x in folded] == ["open", CLOSED]


def test_two_rows_for_one_loop_never_collide_in_the_store():
    """The row key carries the state, so an append can never silently overwrite its own opening."""
    opened = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    closed = close_by_observation([opened], {(REMEDY, "478", ""): "worked"})[0]
    sink = InMemoryMetricsSink()
    store.write("books", [opened, closed], sink=sink, now="2026-07-27T10:00:00")
    keys = {MetricRecord.dynamo_key(r)["sk"] for r in sink.records}
    assert len(keys) == 2, "the two rows share a key and one would overwrite the other"


def test_an_unreadable_row_costs_that_row_and_nothing_else():
    sink = InMemoryMetricsSink()
    good = open_loop(QUESTION, "t", owner="product", ts="T1")
    store.write("books", [good], sink=sink)
    rows = _rows(sink) + [{"kind": store.LEDGER_KIND, "pk": "books", "ts": "T2", "extra": {}}]
    assert store.read("books", scan=lambda: rows) == [good]


def test_a_write_failure_never_raises_but_returns_zero():
    """An agent that cannot remember must still be able to act — but the caller can tell."""
    class _Broken:
        def record(self, rec):
            raise RuntimeError("dynamo is down")

    assert store.write("books", [open_loop(QUESTION, "t", owner="p", ts="T1")],
                       sink=_Broken()) == 0


def test_another_projects_loops_are_never_read():
    sink = InMemoryMetricsSink()
    store.write("books", [open_loop(QUESTION, "t", owner="product", ts="T1")], sink=sink)
    assert store.read("outra-empresa", scan=lambda: _rows(sink)) == []


# ── the read path ───────────────────────────────────────────────────────────────────────────────

def test_the_memory_is_read_by_INDEX_not_by_scanning_the_table():
    """The regression this guards: every memory read was a full table scan. Correct, and quietly
    more expensive every week, on the path all of the agents' memory depends on."""
    src = Path("openfactory/memory/store.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "read")
    body = ast.unparse(fn)
    assert "records_of_kind" in body, "the ledger no longer reads through the index"
    # scan_records may only appear behind the caller-injected test hook, never as the real path
    assert "scan_records" not in body, "the ledger went back to scanning the whole table"


def test_every_written_record_carries_the_index_key():
    """A row without `kind_ts` is invisible to the index — written, and then never found."""
    sink = InMemoryMetricsSink()
    store.write("books", [open_loop(REMEDY, "478", owner="techlead", ts="T1")], sink=sink)
    for rec in sink.records:
        assert rec.dynamo_key().get("kind_ts", "").startswith(f"{store.LEDGER_KIND}#")


# `test_the_index_fallback_is_LOUD` moved to `tests/test_dynamo_metrics_sink.py`: the scan fallback is
# a method of the DynamoDB sink now, an add-on this generic file must not name by path.

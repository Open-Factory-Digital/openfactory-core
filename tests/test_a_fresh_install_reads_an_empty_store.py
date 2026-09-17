"""#137: on a fresh install the metrics store is EMPTY, not unreadable.

`SqliteMetricsSink` applied its schema only when writing, and nothing writes a metric until a job
runs. So on a deployment that had run nothing yet, every read failed with `no such table: metrics`.
The panel reads the people store on every request, to decide whether it is open at all, so it logged

    metrics read failed on <path>/metrics.db: no such table: metrics
    OPENFACTORY_PEOPLE_UNREADABLE the people store could not be read ...

on essentially every request — measured on the e2e bed: 442 lines for 240 board reads — and nobody
registered by invitation could be identified until a job happened to write a metric.

What must still hold is the other half of #126: a store that CANNOT be read says so. A file that is
not a database is `StoreUnreadable`, never `[]`.
"""

from __future__ import annotations

import logging

import pytest

from openfactory.observability.query import StoreUnreadable
from openfactory.observability.sqlite_metrics import SqliteMetricsSink


def test_the_first_read_of_a_fresh_store_is_empty_and_says_nothing(tmp_path, caplog):
    sink = SqliteMetricsSink(tmp_path / "metrics.db")

    with caplog.at_level(logging.WARNING):
        assert sink.records_of_kind("_people", "person") == []
        assert sink.scan() == []

    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_a_store_whose_directory_does_not_exist_yet_reads_as_empty(tmp_path):
    """The panel can be up before the worker has made the state directory."""
    assert SqliteMetricsSink(tmp_path / "state" / "metrics.db").scan() == []


def test_a_fresh_store_is_readable_by_the_people_store_the_panel_asks_on_every_request(
        tmp_path, monkeypatch, caplog):
    from openfactory.identity.people import PeopleStore

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))

    with caplog.at_level(logging.WARNING):
        assert PeopleStore().has_people() is False

    unreadable = [r.getMessage() for r in caplog.records
                  if "UNREADABLE" in r.getMessage() or "no such table" in r.getMessage()]
    assert not unreadable, unreadable


def test_what_was_written_is_still_read_back(tmp_path):
    from openfactory.observability.metrics import MetricRecord

    sink = SqliteMetricsSink(tmp_path / "metrics.db")
    assert sink.scan() == []   # the read that made the table first
    assert sink.record(MetricRecord(project="p", kind="person", role="r", ticket="t1",
                                    ts="2026-09-17T00:00:00+00:00"))

    assert [row["ticket"] for row in sink.records_of_kind("p", "person")] == ["t1"]


def test_a_file_that_is_not_a_database_is_still_UNREADABLE_not_empty(tmp_path):
    """#126's half, which this must not undo: materialising a table is for a store nobody has
    written to, never a way to read a broken one as an empty one."""
    path = tmp_path / "metrics.db"
    path.write_bytes(b"definitely not a database" * 20)

    with pytest.raises(StoreUnreadable):
        SqliteMetricsSink(path).scan()


def test_a_store_deleted_while_the_process_runs_is_made_again_on_the_next_read(tmp_path):
    """The schema is made sure of once per file per process, so a panel reading on every request
    pays for it once. A file removed under a running process must not then fail every read for the
    rest of its life."""
    path = tmp_path / "metrics.db"
    sink = SqliteMetricsSink(path)
    assert sink.scan() == []
    for leftover in tmp_path.glob("metrics.db*"):
        leftover.unlink()

    # the connection that finds no table fails once, honestly, and the next read makes it again
    try:
        sink.scan()
    except StoreUnreadable:
        pass
    assert sink.scan() == []

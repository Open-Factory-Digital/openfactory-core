""""Returns whether it landed" has to be measured, not assumed (sweep B4, 2026-08-16).

The probe that opened this finding: one hundred rapid `messages.told()` calls against the real
sqlite sink, **ninety-nine rows on disk, one hundred `True`s returned.** Two defects stacked:

  * every sink's `record()` returned `None` — swallowing its own failures by design, telemetry
    must never fail a job — so `messages.write`, which promises "returns how many landed",
    incremented unconditionally and counted ATTEMPTS. Every caller gating on that bool —
    `PanelChannel.say`, `_product_post`'s dropped-post ledger rule, the panel notifier — was
    gating on nothing. `[[can-the-answer-shape-say-it]]`: `-> None` cannot say "it failed".
  * the same-microsecond disambiguator was the BATCH index, which restarts at 0 per call — so two
    single-message writes in one microsecond minted the same storage key and `INSERT OR REPLACE`
    quietly kept one. That is the row the probe lost.

This is the operator's literal complaint — *"memória que não persiste"* — measured.
"""

from __future__ import annotations

from openfactory.memory import messages
from openfactory.observability.metrics import (
    InMemoryMetricsSink,
    MetricRecord,
    NullMetricsSink,
)
from openfactory.observability.sqlite_metrics import SqliteMetricsSink


def _rows(sink) -> list[dict]:
    return [{"kind": r.kind, "pk": r.project, "ts": r.ts, "extra": r.extra} for r in sink.records]


# ── 1. the sinks answer honestly ────────────────────────────────────────────────────────────────

def test_every_sink_says_whether_the_record_landed(tmp_path):
    rec = MetricRecord(project="p", ticket="1", ts="2026-08-16T00:00:00")
    assert InMemoryMetricsSink().record(rec) is True
    assert SqliteMetricsSink(str(tmp_path / "m.db")).record(rec) is True
    assert NullMetricsSink().record(rec) is False, (
        "the sink that stores nothing claims the record landed — every caller that promises "
        "'returns whether it landed' becomes a liar on a metrics-off deployment")


def test_a_sink_that_cannot_write_answers_False_not_None(tmp_path):
    """The sqlite sink logs-and-swallows by design; the answer is how a caller finds out."""
    sink = SqliteMetricsSink(str(tmp_path / "m.db"))
    sink.path = str(tmp_path)  # a directory is not a database — every write now fails
    landed = sink.record(MetricRecord(project="p", ticket="1", ts="T"))
    assert landed is False, "a failed write answered something other than False"


# ── 2. the message layer counts what landed, not what it tried ──────────────────────────────────

def test_write_counts_only_what_the_sink_confirmed():
    class _Flaky:
        def __init__(self) -> None:
            self.n = 0

        def record(self, rec) -> bool:
            self.n += 1
            return self.n != 2  # the second write fails

    sink = _Flaky()
    wrote = messages.write("p", [messages.Message(kind=messages.SAID, text=t, ts="T")
                                 for t in ("a", "b", "c")], sink=sink)
    assert wrote == 2, (
        f"three attempts, one refused, and the layer reported {wrote} — callers gate the "
        f"operator's own conversation on this number")
    assert not messages.say("p", "x", sink=type("S", (), {"record": lambda self, r: False})()), (
        "say() promised 'returns whether it landed' over a sink that said it did not")


def test_a_hundred_writes_in_one_instant_are_a_hundred_rows(tmp_path):
    """THE PROBE THAT OPENED THE FINDING, kept as the guard. The batch-index disambiguator
    restarted at 0 per call, so same-microsecond single-message writes collided on the storage
    key and `INSERT OR REPLACE` kept one — 99 rows, 100 Trues."""
    sink = SqliteMetricsSink(str(tmp_path / "m.db"))
    stamp = "2026-08-16T12:00:00.000001"  # one microsecond, one hundred writes, forced
    for i in range(100):
        assert messages.told("p", f"turn {i}", by="operator-1", sink=sink, now=stamp)
    back = messages.read("p", scan=lambda: sink.records_of_kind("p", messages.MESSAGE_KIND))
    assert len(back) == 100, (
        f"{100 - len(back)} of 100 confirmed writes are missing from the store — "
        f"'memória que não persiste', measured")


def test_the_two_processes_cannot_collide_either():
    """The panel and the worker share one store. The sequence alone is per-process; the key must
    differ across processes too, which is what the pid contributes."""
    import inspect

    src = inspect.getsource(messages.write)
    assert "os.getpid()" in src, (
        "the storage key no longer carries the pid — the panel's and the worker's writes can "
        "mint the same key in the same microsecond and silently overwrite each other")

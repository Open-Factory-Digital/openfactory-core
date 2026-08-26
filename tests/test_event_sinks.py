"""StdoutEventSink + TeeEventSink — live progress streaming (so a remote job is never
silent) and fan-out to the file journal + stdout at once."""

from __future__ import annotations

from openfactory.observability import (
    InMemoryEventSink,
    JobEvent,
    StdoutEventSink,
    TeeEventSink,
    now_iso,
)


def _event(msg="implementing") -> JobEvent:
    return JobEvent(ts=now_iso(), job_id="#5", ticket_id="#5", kind="state", message=msg, data={})


def test_stdout_sink_prints_prefixed_json(capsys):
    StdoutEventSink().emit(_event("reviewing"))
    out = capsys.readouterr().out
    assert out.startswith("OPENFACTORY_EVENT:")
    assert '"reviewing"' in out


def test_tee_fans_out_to_all_sinks(capsys):
    mem = InMemoryEventSink()
    TeeEventSink(mem, StdoutEventSink()).emit(_event("implementing"))
    assert len(mem.events) == 1 and mem.events[0].message == "implementing"
    assert "OPENFACTORY_EVENT:" in capsys.readouterr().out  # also streamed


# ── a sink must never raise into the job (C-09b) ────────────────────────────────────────────────
#
# The journal is telemetry. A job that dies because telemetry failed has confused what it is FOR
# with what it REPORTS — and the failure mode is the expensive one: the ticket is abandoned mid
# flight with partial work, for a full disk. This is the same obligation ADR-0022 §3 wrote into
# `say` ("returns whether it landed and never raises"), which the event sinks never inherited.
#
# Swallowing silently would be its own defect, so the rule has two halves: never raise, and always
# say so in the log.


class _Exploding:
    """A sink that fails the way a real one does — at emit, not at construction."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc or OSError(28, "No space left on device")
        self.calls = 0

    def emit(self, event: JobEvent) -> None:
        self.calls += 1
        raise self.exc


def test_tee_keeps_going_when_a_sink_explodes():
    """The disk filling up must not cost the live stdout feed — the one thing that would still
    have told a human what happened."""
    boom, mem = _Exploding(), InMemoryEventSink()
    TeeEventSink(boom, mem).emit(_event("implementing"))
    assert boom.calls == 1  # it was tried
    assert len(mem.events) == 1  # and the sink AFTER it still received the event


def test_tee_does_not_raise_into_its_caller():
    """`machine.py::_emit` has no try/except of its own: whatever escapes here reaches the job."""
    TeeEventSink(_Exploding()).emit(_event("implementing"))


def test_a_failing_sink_is_logged_rather_than_swallowed(caplog):
    """Never a silent swallow. A journal that stopped writing and said nothing is indistinguishable
    from a job that stopped doing anything."""
    with caplog.at_level("WARNING", logger="openfactory.journal"):
        TeeEventSink(_Exploding()).emit(_event("implementing"))
    assert any("No space left" in r.getMessage() for r in caplog.records)


def test_file_sink_does_not_raise_when_the_journal_cannot_be_written(tmp_path):
    """The COMMON case: `factory.py` and `activities.py` hand the runner a bare FileEventSink, not
    a Tee. Guarding only the Tee would leave the main path exposed."""
    from openfactory.observability import FileEventSink

    path = tmp_path / "j.jsonl"
    sink = FileEventSink(path)
    path.write_text("")
    path.chmod(0o400)  # read-only: the write will fail
    try:
        sink.emit(_event("implementing"))
    finally:
        path.chmod(0o600)


def test_stdout_sink_does_not_raise_when_the_stream_is_gone(monkeypatch):
    """A closed stdout is what a container teardown looks like from inside the process."""
    import sys

    class _Closed:
        def write(self, *_a, **_kw):
            raise ValueError("I/O operation on closed file")

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _Closed())
    StdoutEventSink().emit(_event("implementing"))


def test_a_sink_that_raises_BaseException_still_propagates():
    """KeyboardInterrupt and SystemExit are not telemetry failures — swallowing them would make the
    process unkillable during a journal write."""
    import pytest

    with pytest.raises(KeyboardInterrupt):
        TeeEventSink(_Exploding(KeyboardInterrupt())).emit(_event("implementing"))


def test_file_sink_dedup_skips_already_journaled_events(tmp_path):
    # a retry that re-reads a remote log from the head must not duplicate the journal (R7)
    from openfactory.observability import FileEventSink

    path = tmp_path / "j.jsonl"
    ev = _event("implementing")
    FileEventSink(path).emit(ev)  # first attempt journaled it
    sink = FileEventSink(path, dedup=True)  # retry re-opens the journal
    sink.emit(ev)  # same event again — skipped
    sink.emit(_event("validating"))  # new event — appended
    lines = path.read_text().splitlines()
    assert len(lines) == 2

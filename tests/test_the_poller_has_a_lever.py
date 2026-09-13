"""#114: the state the ladder has always been able to REPORT is now one a person can reach.

`floor/ladder.py` has answered `poller_paused` since it was written, with the remedy *"there is no
button for this yet — resume the schedule on the engine"* — a state the product can see, name and
explain, reachable only by somebody holding the engine's credentials with the Temporal UI open.

WHY IT MATTERS BEYOND TIDINESS. Updating a compose deployment recreates the worker, and the poller
is a schedule inside it. Rolling while a job is in flight interrupts that job; rolling while a card
sits in TO-DO races a pickup against the restart. The safe sequence is pause → drain → pull → up →
resume, and the product could do the middle three.

THE HALF THAT IS NOT THE LEVER. A pause holds PICKUP. It does nothing to a job already running, and
an operator who reads "paused" as "drained" interrupts exactly the work they paused to protect — so
every command here answers both questions at once, and the pause says the sentence out loud.
"""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.floor.ladder import FloorInputs


class _State:
    def __init__(self, paused: bool, note: str = "") -> None:
        self.paused, self.note = paused, note


class _Handle:
    """Enough of Temporal's ScheduleHandle to hold the two facts this feature turns on."""

    def __init__(self, paused: bool, note: str = "") -> None:
        self.state = _State(paused, note)
        self.calls: list[tuple[str, str]] = []

    async def describe(self):
        return type("Desc", (), {"schedule": type("S", (), {"state": self.state})()})()

    async def pause(self, *, note: str) -> None:
        self.calls.append(("pause", note))
        self.state = _State(True, note)

    async def unpause(self, *, note: str) -> None:
        self.calls.append(("unpause", note))
        self.state = _State(False, note)


def _engine(handle: _Handle, monkeypatch):
    from openfactory.runtime.temporal import schedule as sched

    monkeypatch.setattr(sched, "connect", lambda: _coro(
        type("C", (), {"get_schedule_handle": lambda self, _id: handle})()))
    return handle


async def _coro_value(value):
    return value


def _coro(value):
    return _coro_value(value)


def _reading(monkeypatch, *, on: bool, note: str = "", jobs: list[dict] | None = None,
             known: bool = True):
    from openfactory.floor import reading as floor

    intake = {"known": known, "on": on, "note": note, "every_s": 180, "next_in_s": 42}

    async def fake_gather(client=None, *, want=(), **kw):
        return FloorInputs(intake=intake, jobs=list(jobs or []))

    monkeypatch.setattr(floor, "gather", fake_gather)


# ── the lever itself ────────────────────────────────────────────────────────────────────────────

def test_pausing_a_running_poller_pauses_it_and_carries_the_note(monkeypatch):
    """The note is the only record of WHY the queue is held — `view.intake` reads it back and the
    ladder prints it, so an unexplained pause is indistinguishable from an outage."""
    from openfactory.runtime.temporal.schedule import hold_poller

    handle = _engine(_Handle(paused=False), monkeypatch)
    result = asyncio.run(hold_poller(on=False, note="rolling to v0.2.1 — rob"))

    assert result == {"changed": True, "was_on": True, "note": "rolling to v0.2.1 — rob"}
    assert handle.calls == [("pause", "rolling to v0.2.1 — rob")]


def test_pausing_what_is_already_paused_is_a_sentence_not_an_action(monkeypatch):
    """A no-op that reports success teaches the reader the command did something. It also must
    not overwrite the note the FIRST pause left — that note is the one that explains the hold."""
    from openfactory.runtime.temporal.schedule import hold_poller

    handle = _engine(_Handle(paused=True, note="incident 402"), monkeypatch)
    result = asyncio.run(hold_poller(on=False, note="something else"))

    assert result == {"changed": False, "was_on": False, "note": "incident 402"}
    assert handle.calls == [], "a no-op must not touch the schedule"


def test_resuming_unpauses(monkeypatch):
    from openfactory.runtime.temporal.schedule import hold_poller

    handle = _engine(_Handle(paused=True, note="held"), monkeypatch)
    result = asyncio.run(hold_poller(on=True, note="rolled"))

    assert result["changed"] and result["was_on"] is False
    assert handle.calls == [("unpause", "rolled")]


# ── pause is not drain, and the command says so ─────────────────────────────────────────────────

def test_a_pause_says_the_running_job_is_still_running(monkeypatch):
    """The sentence this command exists to print. An operator pauses in order to ROLL, and a
    pause that reads as 'drained' interrupts exactly the work they paused to protect."""
    _engine(_Handle(paused=False), monkeypatch)
    _reading(monkeypatch, on=False,
             jobs=[{"project": "routing", "issue": "210", "status": "running", "state": "coding"},
                   {"project": "routing", "issue": "209", "status": "closed"}])

    out = CliRunner().invoke(app, ["poller", "pause", "--note", "rolling"]).output

    assert "PAUSED" in out
    assert "routing #210" in out
    assert "routing #209" not in out, "a closed job is not in flight"
    assert "holds NEW pickups only" in out
    assert "Wait for them before rolling" in out


def test_a_pause_with_nothing_running_says_nothing_is_running(monkeypatch):
    """And then it must NOT print the warning: an operator who is clear to roll should be told
    so, not handed a caveat about jobs that do not exist."""
    _engine(_Handle(paused=False), monkeypatch)
    _reading(monkeypatch, on=False, jobs=[{"project": "a", "issue": "1", "status": "closed"}])

    out = CliRunner().invoke(app, ["poller", "pause"]).output

    assert "in flight: nothing" in out
    assert "holds NEW pickups only" not in out


def test_status_answers_both_questions_at_once(monkeypatch):
    """Either answer alone misleads: 'paused' reads as safe-to-roll, and 'nothing in flight'
    reads as nothing-will-start while the schedule ticks."""
    _reading(monkeypatch, on=True,
             jobs=[{"project": "routing", "issue": "7", "status": "running", "state": "coding"}])

    out = CliRunner().invoke(app, ["poller", "status"]).output

    assert "poller: ON" in out
    assert "routing #7" in out


# ── what the state says about itself ────────────────────────────────────────────────────────────

def test_a_paused_poller_reports_the_note_that_explains_it(monkeypatch):
    _reading(monkeypatch, on=False, note="incident 402 — rob", jobs=[])

    out = CliRunner().invoke(app, ["poller", "status"]).output

    assert "PAUSED" in out and "incident 402 — rob" in out


def test_a_paused_poller_with_no_note_says_it_cannot_be_told_from_an_outage(monkeypatch):
    """The note is optional to Temporal and not to a reader. Silence here is the failure mode the
    whole feature is about: a held queue nobody can explain."""
    _reading(monkeypatch, on=False, note="", jobs=[])

    out = CliRunner().invoke(app, ["poller", "status"]).output

    assert "PAUSED" in out
    assert "outage" in out, "an unexplained hold must say what it cannot be distinguished from"


def test_an_unreadable_schedule_is_never_reported_as_on(monkeypatch):
    """`intake` answers `known: False` rather than guessing, and this must not flatten that into
    'ON' — a command claiming the factory is taking work when it could not ask is the same lie
    one layer down."""
    _reading(monkeypatch, on=None, known=False, jobs=[])

    out = CliRunner().invoke(app, ["poller", "status"]).output

    assert "UNKNOWN" in out
    assert "poller: ON" not in out


def test_an_unreachable_engine_refuses_by_name_rather_than_a_traceback(monkeypatch):
    """`openfactory doctor` is the bar: one sentence, the cause, and where to look."""
    from openfactory.runtime.temporal import schedule as sched

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(sched, "connect", lambda: boom())
    result = CliRunner().invoke(app, ["poller", "pause", "--note", "x"])

    assert result.exit_code == 2
    assert "could not pause the poller" in result.output
    assert "poller status" in result.output, "the refusal names where to look"
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["pause", "resume"])
def test_the_note_defaults_to_naming_who_pulled_the_lever(monkeypatch, command):
    """An unattributed hold is the thing the note exists to prevent, so omitting `--note` must
    not produce silence."""
    handle = _engine(_Handle(paused=(command == "resume")), monkeypatch)
    _reading(monkeypatch, on=(command == "resume"), jobs=[])

    CliRunner().invoke(app, ["poller", command])

    assert handle.calls, f"{command} did not reach the schedule"
    assert handle.calls[0][1], "the note was empty"
    assert "openfactory poller" in handle.calls[0][1]

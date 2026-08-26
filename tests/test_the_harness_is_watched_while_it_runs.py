"""The stall is seen DURING the pass, not at the wall (C-39, #82).

The arithmetic landed last round and was reached only from the end of a failed pass: the 4h wall
and the no-result branch. So the platform's answer to "is the agent stuck?" was correct and four
hours late by construction. The missing half was somebody holding the other end of the pipe while
the pass ran.

`SandboxAdapter.tail()` is that end. `activities.HarnessWatch` is what pulls on it, driven by the
one thing that is awake during a four-hour pass — `_heartbeat_while`'s 30-second loop, which until
now used its turn to say the WORKER was alive, which is not the same claim as the AGENT working.

WHAT IS PROVEN HERE:

  * the chain is REACHED — `run_job` builds the watcher, `_do_run_job` hands it the runner, and the
    heartbeat loop calls it. This repository has shipped "built, tested, reached by nothing" about
    twenty times, so the wiring is asserted through the real activity rather than by calling
    `HarnessWatch` directly and hoping;
  * a silent harness is reported in ONE tick rather than in four hours, and the silence signal
    exists at all — three of the four harnesses stamp no clock in their stream, so post-mortem this
    question is unanswerable for them; reading live is what answers it;
  * a healthy pass does NOT trip the alarm — the other half of every threshold, and the half a
    watcher that fires on everything would fail;
  * a box that cannot be read gets NO watcher, and the reason is said. A watcher attached to a box
    that answers nothing sees no events, and no events is indistinguishable from a working agent.
    That is the collapse the whole card is about;
  * a watcher that raises cannot end a pass that was otherwise fine.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from openfactory.runtime.temporal.activities import HarnessWatch, _heartbeat_while, _watch_for
from openfactory.runtime.temporal.io import RunJobInput

T0 = 1_800_000_000.0  # a real epoch second, so the stream's own clock reads as a clock


class _Box:
    """A box that answers `tail()` the way the port says: a list of new lines, or None for "I
    cannot read myself". Built from the real contract — it has exactly the one method the watcher
    calls, and no invented field."""

    def __init__(self, chunks: list[list[str]] | None):
        self._chunks = chunks
        self.reads = 0

    def tail(self):
        self.reads += 1
        if self._chunks is None:
            return None
        return self._chunks.pop(0) if self._chunks else []


class _Journal:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class _Runner:
    def __init__(self, box, journal):
        self.sandbox = box
        self.events = journal


def _assistant(text: str = "thinking") -> str:
    return json.dumps({"type": "assistant",
                       "message": {"content": [{"type": "text", "text": text}]}}) + "\n"


def _tool(name: str, target: str) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": {"command": target}}]}}) + "\n"


def _watch(box, journal=None) -> HarnessWatch:
    w = HarnessWatch(harness="claude_code", project="acme", issue="12")
    w.attach(_Runner(box, journal or _Journal()))
    return w


# ── the silence signal only exists because the reading is live ───────────────────────────────────

def test_a_harness_that_went_quiet_is_seen_within_one_tick():
    """CLAUDE STAMPS NOTHING. `read_harness` says so honestly at the wall — "this stream cannot
    answer silence" — and that gap is exactly what a live reader closes: a pulse that arrives now
    happened now, so the watcher stamps arrival itself."""
    watch = _watch(_Box([[_assistant(), _tool("Bash", "pytest -q")]]))

    assert watch.read(now=T0).stalls == (), "two events just arrived — nothing is wrong yet"

    later = watch.read(now=T0 + 40 * 60)
    assert [s.kind for s in later.stalls] == ["harness-silent"]
    assert "no stream event for the last 40 min" in later.note
    assert "silence" not in later.blind_to, (
        "a live watcher answers the silence question; only a post-mortem reader cannot")


def test_a_working_pass_never_trips_the_alarm():
    """The other half of every threshold. A watcher that fires on a healthy run costs more than no
    watcher: somebody turns it off, and then the real one is off too."""
    watch = _watch(_Box([[_tool("Bash", f"pytest tests/test_{n}.py")] for n in range(6)]))

    for n in range(6):
        reading = watch.read(now=T0 + n * 120)
        assert reading.stalls == (), f"tick {n} reported {reading.note}"


def test_a_long_test_suite_after_the_agent_is_not_a_silent_harness():
    """ONE BOX RUNS THREE THINGS: `setup:`, the harness, then `validate:`. `tail()` says what was
    written, not which of them wrote it — so the agent's last pulse keeps ageing through a
    twenty-minute test suite and the silence arithmetic, taken literally, reports a stall.

    True about the harness, useless as an alarm, and a false alarm is how a watcher gets switched
    off before the real one fires."""
    box = _Box([[_tool("Bash", "pytest -q")], ["collected 812 items\n"], ["....\n"]])
    watch = _watch(box)

    watch.read(now=T0)                       # the agent's last event
    watch.read(now=T0 + 10 * 60)             # pytest, ten minutes in — lines, no events
    reading = watch.read(now=T0 + 20 * 60)   # still pytest, twenty minutes in

    assert reading.stalls == (), f"reported a stall while the box was writing: {reading.note}"


def test_but_a_box_writing_nothing_at_all_still_reports_the_stall():
    """THE POSITIVE TWIN of the test above, and it is the one that matters: a suppression rule with
    no counterexample would quietly turn the whole signal off, and absence would read as compliance
    exactly as this repository keeps recording. A harness stuck at a prompt, looping in its own
    thinking, or waiting on an approval nobody will give writes NO lines — so nothing suppresses
    it."""
    watch = _watch(_Box([[_tool("Bash", "pytest -q")]]))

    watch.read(now=T0)
    reading = watch.read(now=T0 + 20 * 60)  # tail() → [] : not one line in twenty minutes

    assert [s.kind for s in reading.stalls] == ["harness-silent"]


def test_the_same_call_over_and_over_is_seen_as_a_loop():
    watch = _watch(_Box([[_tool("Bash", "pytest -q")] for _ in range(10)]))

    for n in range(10):
        reading = watch.read(now=T0 + n * 10)
    assert any(s.kind == "harness-spinning" for s in reading.stalls)


# ── could not read ≠ nothing to read ─────────────────────────────────────────────────────────────

def test_a_box_that_cannot_read_itself_is_not_a_calm_agent():
    """`tail()` → None is *I could not read*. If that were treated as an empty stream, a watcher
    would spend four hours confirming that a box it cannot see is doing fine."""
    assert _watch(_Box(None)).read(now=T0) is None


def test_before_the_runner_exists_there_is_nothing_to_conclude():
    """`attach` happens inside the worker thread once `build_runner` returns; the heartbeat loop
    starts ticking before that. Those early ticks must say *could not look*, not *silent agent*."""
    assert HarnessWatch(harness="claude_code", project="acme", issue="12").read(now=T0) is None


def test_a_harness_with_no_reader_concludes_nothing_ever():
    """`pulses_of` returns None for a harness it has no reader for — a different answer from an
    empty list, and the one that must never harden into "the agent said nothing"."""
    watch = HarnessWatch(harness="some_new_cli", project="acme", issue="12")
    watch.attach(_Runner(_Box([["whatever it printed\n"]]), _Journal()))
    assert watch.read(now=T0) is None


def test_an_empty_stream_reads_as_blind_not_as_healthy():
    """A box that is readable and has produced nothing yet. `read_harness` refuses to call that a
    clean bill of health, and the watcher must not either — it reports no stall AND says why."""
    reading = _watch(_Box([[]])).read(now=T0)
    assert reading is not None and reading.stalls == ()
    assert "not a clean bill of health" in reading.note


# ── it appears where impediments appear ──────────────────────────────────────────────────────────

def _quiet_since(minutes: int, journal) -> HarnessWatch:
    """A watcher whose one event arrived `minutes` ago ON THE REAL CLOCK.

    `tick()` deliberately takes no `now` — it is called by the heartbeat loop, which has no reason
    to carry a clock, so the wall time is read inside. A fixed epoch constant here would therefore
    measure against whatever today happens to be, and (being in 2027) once produced a NEGATIVE
    silence that quietly reported nothing wrong."""
    import time

    watch = _watch(_Box([[_assistant()]]), journal)
    watch.read(now=time.time() - minutes * 60)
    return watch


def test_a_stall_lands_in_the_job_s_own_journal():
    """ADR-0038: the panel is the reference surface, and it reads the job's journal. A watcher that
    only logs is the same silence with more CPU."""
    journal = _Journal()
    watch = _quiet_since(40, journal)

    said = watch.tick()

    assert "harness-silent" in said
    assert len(journal.events) == 1
    event = journal.events[0]
    assert event.kind == "warning"
    assert event.job_id == "12" and event.ticket_id == "12", (
        "keyed like every other event of this job, or the one line that says 'stuck' sits in a "
        "stream of its own")
    assert "travado" in event.message
    assert event.data["stalls"] == ["harness-silent"]
    assert event.data["cause"] and event.data["remedy"], (
        "the same classifier that reads a park note — one brain, not two")


def test_the_same_stall_is_not_repeated_every_thirty_seconds():
    """Four hours of ticks is 480 identical panel lines, which is how a feed stops being read on
    the tick that matters (`techlead.watch.worth_saying` argues the same for the hourly rounds)."""
    journal = _Journal()
    watch = _quiet_since(40, journal)

    first, second = watch.tick(), watch.tick()

    assert first and not second
    assert len(journal.events) == 1


def test_a_healthy_tick_says_nothing_at_all():
    journal = _Journal()
    watch = _watch(_Box([[_tool("Bash", "pytest -q")]]), journal)
    assert watch.tick() == ""
    assert journal.events == []


# ── a box that cannot be watched gets no watcher, and says so ────────────────────────────────────

def test_the_remote_box_is_not_given_a_watcher_that_would_see_nothing(caplog):
    """`fargate` answers `streams=False`: the harness's output never leaves the task, and only the
    orchestrator's own `OPENFACTORY_EVENT:` lines reach CloudWatch. Attaching a watcher there would
    produce four hours of "no events", which is indistinguishable from a healthy agent — the exact
    collapse this card exists to stop. The gap is LOGGED, because an unwatched pass has to be a
    known gap rather than an assumption."""
    with caplog.at_level(logging.INFO):
        assert _watch_for(RunJobInput(project="acme", issue="12", sandbox="fargate")) is None
    assert any("cannot be read while it runs" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("kind", ["worktree", "container"])
def test_a_readable_box_does_get_one(kind, monkeypatch):
    monkeypatch.setattr("openfactory.runtime.temporal.activities._project_or_none", lambda _n: None)
    watch = _watch_for(RunJobInput(project="acme", issue="12", sandbox=kind))
    assert isinstance(watch, HarnessWatch)


def test_an_unknown_box_costs_the_watcher_and_never_the_job(caplog):
    """`box_traits` raises for a kind nobody registered. A watcher is advisory: failing to build
    one must degrade to an unwatched pass, never fail the activity that was about to do the work."""
    with caplog.at_level(logging.WARNING):
        assert _watch_for(RunJobInput(project="acme", issue="12", sandbox="typo")) is None


# ── the wiring, asserted through the real activity ───────────────────────────────────────────────

def test_the_heartbeat_loop_calls_the_watcher_and_carries_what_it_says(monkeypatch):
    """THE REACHABILITY GUARD on the loop. Everything above can pass while nothing ever ticks."""
    beats: list[str] = []
    ticks = {"n": 0}

    def tick() -> str:
        ticks["n"] += 1
        return "harness-silent"

    async def scenario():
        import openfactory.runtime.temporal.activities as mod

        class _Act:
            logger = logging.getLogger("test")

            @staticmethod
            def heartbeat(detail):
                beats.append(detail)

        monkeypatch.setattr(mod, "activity", _Act)
        return await _heartbeat_while(lambda: "done", "acme#12 via container", tick=tick)

    assert asyncio.run(scenario()) == "done"
    assert ticks["n"] >= 1, "the loop never asked the watcher anything"
    assert any("harness-silent" in b for b in beats), (
        "what the watcher found never reached the heartbeat detail")


def test_a_watcher_that_raises_does_not_end_the_pass(monkeypatch):
    beats: list[str] = []

    async def scenario():
        import openfactory.runtime.temporal.activities as mod

        class _Act:
            logger = logging.getLogger("test")

            @staticmethod
            def heartbeat(detail):
                beats.append(detail)

        def explode():
            raise RuntimeError("the watcher is broken")

        monkeypatch.setattr(mod, "activity", _Act)
        return await _heartbeat_while(lambda: "done", "acme#12 via container", tick=explode)

    assert asyncio.run(scenario()) == "done"
    assert beats, "the heartbeat must still be issued — it is what keeps the activity alive"


def test_run_job_builds_a_watcher_and_hands_it_the_runner(monkeypatch):
    """THE OTHER HALF OF THE CHAIN, and the half that is easy to leave unwired: the watcher must
    reach the BOX, which is built three layers down inside `build_runner`. Asserted through
    `_do_run_job` itself rather than by calling `attach` in the test."""
    import openfactory.runtime.temporal.activities as mod

    box, journal = _Box([[_assistant()]]), _Journal()

    class _FakeRunner:
        sandbox = box
        events = journal

        def run(self, *_a, **_k):
            from openfactory.contracts import RunResult

            return RunResult(ticket_id="12", state="pr_open")

        def knowledge_arm(self):
            return None

    watch = HarnessWatch(harness="claude_code", project="acme", issue="12")
    monkeypatch.setattr(mod, "build_runner", lambda *a, **k: _FakeRunner())
    monkeypatch.setattr(mod, "ProjectRegistry",
                        lambda: type("R", (), {"get": staticmethod(lambda _n: object())})())
    monkeypatch.setattr(mod, "_runner_view", lambda *a, **k: (object(), "acme"))

    mod._do_run_job(RunJobInput(project="acme", issue="12", sandbox="container"), watch=watch)

    assert watch.read(now=T0) is not None, "the watcher never received the box"


# ── the whole chain, against a real process ──────────────────────────────────────────────────────

def test_a_real_box_running_a_real_harness_is_read_while_it_runs(tmp_path):
    """NO DOUBLES ANYWHERE BELOW THE WATCHER. A real `WorktreeSandbox` runs a real subprocess that
    narrates itself in claude's own `--output-format stream-json` shape, and the watcher reads it
    through the real `tail()`, the real `pulses_of` and the real `read_harness`.

    Every unit above can pass with a fake box while the actual chain — pipe, reader thread, cursor,
    parser — is broken at any one of its five joints. It also proves the timing claim end to end:
    the second poll sees MORE events than the first, from a process that has not exited.

    The stall itself is asserted by advancing `now`, not by sleeping twelve minutes: the threshold
    is `read_harness`'s parameter and the reading is pure, so waiting would test the clock."""
    import threading
    import time

    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.worktree import WorktreeSandbox

    script = tmp_path / "fake-harness.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"echo '{_assistant('planning').strip()}'\n"
        "sleep 0.5\n"
        f"echo '{_tool('Bash', 'pytest -q').strip()}'\n"
        "sleep 9\n"  # still running: the wall below stops it, which is the point
    )
    script.chmod(0o755)

    box = WorktreeSandbox(root=tmp_path)
    ws = Workspace(path=tmp_path, host_path=tmp_path, branch="sdlc/1", base_branch="main")
    watch = HarnessWatch(harness="claude_code", project="acme", issue="12")
    watch.attach(_Runner(box, _Journal()))

    pass_done = threading.Event()

    def agent_pass() -> None:
        try:
            box.run(workspace=ws, command=str(script), timeout=6)
        finally:
            pass_done.set()

    def read_until(at_least: int, deadline: float):
        """Poll the way the heartbeat loop does. A FIXED SLEEP WAS WRONG AND THE FIRST VERSION USED
        ONE: spawning a shell takes a couple of hundred milliseconds on a loaded machine, so a
        200 ms sleep read an empty stream and called it "nothing was read from a live process".
        Polling to a deadline measures the property (the reading advances during the run) instead of
        the interpreter's start-up time.

        AND THE DEADLINE ITSELF WAS STILL A MACHINE-SPEED ASSUMPTION. Two seconds, inside a script
        that only lived three: shell spawn, first read, second read and `not pass_done` all had to
        fit in that. It held here and failed twice on 2026-08-21 under three concurrent suites —
        which is not an exotic condition, it is what a contributor's laptop looks like. The whole
        envelope is now roughly doubled; on a machine that is not struggling this costs nothing,
        because every wait below returns the moment its condition is true."""
        last = None
        while time.monotonic() < deadline:
            last = watch.read(now=time.time())
            if last is not None and last.events >= at_least:
                return last
            time.sleep(0.05)
        return last

    thread = threading.Thread(target=agent_pass, daemon=True)
    thread.start()
    try:
        first = read_until(1, time.monotonic() + 5.0)
        assert first is not None and first.events >= 1, "nothing was read from a live process"
        # One stream event is several pulses (an assistant message is a TURN and its content), so
        # the second wait is expressed against what the first actually saw rather than a literal.
        second = read_until(first.events + 1, time.monotonic() + 5.0)

        assert not pass_done.is_set(), "the harness had already exited — this proved nothing live"
        assert second.events > first.events, "the reading did not advance while the agent worked"
        assert second.stalls == (), "a working pass must not trip the alarm"

        # …and the same reading, twelve minutes on, is the stall the card is about.
        assert [s.kind for s in watch.read(now=time.time() + 13 * 60).stalls] == ["harness-silent"]
    finally:
        thread.join(timeout=15)

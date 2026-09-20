"""The floor's budget read does not run on the loop that serves the panel (found 2026-09-19).

`floor/reading.py::gather` is awaited by `/api/floor` and by the engine stream's frames, on the
panel's ONE event loop, and `_budget_cached` was synchronous: `_budget()` spawns `gh api
rate_limit` on the one vendor that reports a budget, right there on the loop's thread. Measured
against the real registry, with a 10 ms heartbeat ticking on the same loop — its longest gap is
what every other request, both SSE streams and the socket really waited:

    a real `gh`, one floor read          0.49 s  →  the loop served nothing else for 0.50 s
    a `gh` that hangs 5 s and fails      5.02 s  →                                   5.02 s
    the same, the NEXT floor read        5.01 s  →                                   5.02 s
    ten floor reads arriving together   50.20 s  →  50.21 s, and TEN `gh` processes

The third row is why the second is the bad case: an unread budget is never cached, deliberately,
so a `gh` that fails slowly turns the memo off and every floor read pays the stall. `gh` is given
60 s by `github_project._run_gh`, and up to a second 60 s on its `@me` retry.

WHAT IS DOUBLED: `reading._budget`, the one function that spawns the subprocess — by a blocking
call that says which thread it ran on. The clock is real and the declared deadline is short.
Everything else is the real thing: the real `gather`, the real memo, the real single flight, and
for the CLI's path the real `asyncio.run`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime

import pytest

from openfactory.floor import reading

#: A blocking read long enough that a stall would be unmistakable, and what "the loop kept
#: serving" allows on eight shared cores.
_READ_S = 0.3
_A_TICK_IS_LATE_BY = 0.15
_DEADLINE = 1.5
_HANGS_AFTER = 6.0

T0 = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

OK = {"state": "ok", "kind": "github", "remaining": 4000, "limit": 5000}


def _forget_the_budget() -> None:
    """Empty memo, empty slot — asked with `getattr` so every case below says what it says about
    BEHAVIOUR against a tree that has no single flight and no `forget_budget` at all (the same
    reason `test_the_intake_memo_is_read_once_and_handed_out_as_a_copy.py::_in_flight` does)."""
    reading._budget_memo = None
    shared = getattr(reading, "_budget_read", None)
    if shared is not None:
        shared.forget()


@pytest.fixture(autouse=True)
def _a_short_deadline_and_an_empty_memo(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_BUDGET_DEADLINE", str(_DEADLINE))
    _forget_the_budget()
    yield
    _forget_the_budget()


class _Read:
    """`reading._budget`, doubled: it blocks a real thread, records which one, and counts."""

    def __init__(self, takes: float = _READ_S, answer: dict | None = None,
                 raises: Exception | None = None) -> None:
        self.takes, self.answer, self.raises = takes, answer or OK, raises
        self.calls = 0
        self.threads: list[int] = []
        self.started = threading.Event()
        self.release = threading.Event()   # only for the case that hangs
        self.hangs = False

    def __call__(self) -> dict:
        self.calls += 1
        self.threads.append(threading.get_ident())
        self.started.set()
        if self.hangs:
            self.release.wait(_HANGS_AFTER * 2)
        else:
            time.sleep(self.takes)
        if self.raises is not None:
            raise self.raises
        return dict(self.answer)


@pytest.fixture
def read(monkeypatch):
    made = _Read()
    monkeypatch.setattr(reading, "_budget", made)
    yield made
    made.release.set()      # never leave a blocked worker thread behind


async def _watched(coro):
    """Run `coro` with a 10 ms heartbeat already ticking on this loop; answer the longest gap it
    suffered, which is what everything else the panel serves would have waited."""
    gaps: list[float] = []
    stop = asyncio.Event()

    async def beat():
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beating = asyncio.ensure_future(beat())
    await asyncio.sleep(0.05)
    try:
        got = await asyncio.wait_for(coro, _HANGS_AFTER)
    finally:
        stop.set()
        await beating
    return got, max(gaps)


# ── 1. off the loop ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_blocking_read_does_not_run_on_the_loops_own_thread(read):
    got = await reading.gather(want=("budget",), now=T0)

    assert got.budget == OK
    assert read.threads and read.threads[0] != threading.get_ident(), (
        "the subprocess that reads the API budget ran on the thread that serves the panel")


@pytest.mark.asyncio
async def test_and_the_loop_keeps_SERVING_while_it_runs(read):
    _got, worst = await _watched(reading.gather(want=("budget",), now=T0))

    assert worst < _A_TICK_IS_LATE_BY, (
        f"a task on the panel's loop waited {worst * 1000:.0f} ms for a {_READ_S * 1000:.0f} ms "
        f"budget read — every other request, both SSE streams and the socket waited with it")


@pytest.mark.asyncio
async def test_a_floor_read_still_ANSWERS_with_the_budget_on_it(read):
    """The whole `gather`, as `/api/floor` asks for it — the read moving off the loop must not
    turn the budget into an unread one."""
    got = await reading.gather(want=("budget", "build"), now=T0)

    assert got.budget == OK and read.calls == 1


# ── 2. once for everybody waiting ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ten_floor_reads_arriving_together_cost_ONE_subprocess(read):
    got = await asyncio.gather(*(reading.gather(want=("budget",), now=T0) for _ in range(10)))

    assert read.calls == 1, f"ten floor reads at the window's expiry spawned {read.calls} reads"
    assert all(g.budget == OK for g in got), "a joiner was handed something else"


@pytest.mark.asyncio
async def test_each_reader_is_handed_its_OWN_copy(read):
    first, second = await asyncio.gather(reading.gather(want=("budget",), now=T0),
                                         reading.gather(want=("budget",), now=T0))
    first.budget["state"] = "MUTATED BY A CALLER"

    assert second.budget["state"] == "ok"
    later = await reading.gather(want=("budget",), now=T0)
    assert later.budget["state"] == "ok", "one reader's write became every floor's budget"


@pytest.mark.asyncio
async def test_a_reader_that_goes_away_does_not_cancel_the_read_under_the_others(read):
    leaving = asyncio.ensure_future(reading.gather(want=("budget",), now=T0))
    staying = asyncio.ensure_future(reading.gather(want=("budget",), now=T0))
    await asyncio.to_thread(read.started.wait, 2.0)
    leaving.cancel()

    got = await staying
    assert got.budget == OK, "the browser that went away took everybody's budget read with it"
    assert read.calls == 1


@pytest.mark.asyncio
async def test_a_read_that_FAILED_is_shared_and_never_stored(monkeypatch):
    """A lock would be single flight on success only: each reader behind a failing read would take
    it, find nothing stored — an unread budget is never cached — and read again."""
    made = _Read(takes=0.05, answer={"state": "unread"})
    monkeypatch.setattr(reading, "_budget", made)

    got = await asyncio.gather(*(reading.gather(want=("budget",), now=T0) for _ in range(6)))

    assert made.calls == 1, f"six readers behind one failing read spawned {made.calls}"
    assert all(g.budget == {"state": "unread"} for g in got)
    later = await reading.gather(want=("budget",), now=T0)
    assert made.calls == 2, "the failure was cached, so a recovery is invisible for a minute"
    assert later.budget == {"state": "unread"}


@pytest.mark.asyncio
async def test_the_window_still_holds_a_GOOD_answer(read):
    await reading.gather(want=("budget",), now=T0)
    await reading.gather(want=("budget",), now=T0)

    assert read.calls == 1, "the memo stopped holding the answer it did read"


# ── 3. a `gh` that hangs ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_read_that_HANGS_degrades_to_unread_inside_the_declared_deadline(read):
    read.hangs = True

    started = time.monotonic()
    got, worst = await _watched(reading.gather(want=("budget",), now=T0))
    took = time.monotonic() - started

    assert got.budget == {"state": "unread"}, (
        "a forge that never answers is reported as something other than unread")
    assert took < _HANGS_AFTER / 2, (
        f"the floor waited {took:.1f}s on a read that never answers — `gh` is given 60s by "
        f"`_run_gh`, and up to a second 60s on its retry")
    assert worst < _A_TICK_IS_LATE_BY, f"the loop stalled {worst * 1000:.0f} ms anyway"


@pytest.mark.asyncio
async def test_the_deadline_is_the_DEPLOYMENTS_to_set(monkeypatch, read):
    read.hangs = True
    monkeypatch.setenv("OPENFACTORY_BUDGET_DEADLINE", "0.05")

    started = time.monotonic()
    got = await reading.gather(want=("budget",), now=T0)

    assert got.budget == {"state": "unread"}
    assert time.monotonic() - started < _DEADLINE / 2, (
        "OPENFACTORY_BUDGET_DEADLINE was not read, so the number is not the operator's")


@pytest.mark.asyncio
async def test_a_read_that_ran_out_of_time_STILL_FILLS_the_window_when_it_lands(read):
    """It is shielded from the deadline for the reason every waiter is shielded: the read is
    nobody's, and throwing it away would make the next floor read spawn a second subprocess while
    the first is still running."""
    read.hangs = True
    first = await reading.gather(want=("budget",), now=T0)
    assert first.budget == {"state": "unread"}

    read.release.set()
    for _ in range(40):                      # the read lands on its own thread, a beat later
        await asyncio.sleep(0.05)
        if reading._budget_memo is not None:
            break

    later = await reading.gather(want=("budget",), now=T0)
    assert later.budget == OK, "the read that landed was thrown away"
    assert read.calls == 1, f"{read.calls} subprocesses for one window"


# ── 4. the callers that are not the panel ───────────────────────────────────────────────────────

def test_the_CLIs_floor_path_still_works(read):
    """`openfactory floor` and `poller status` have no loop of their own — they run
    `asyncio.run(floor.gather(...))`, which is a loop, and the read must still leave it."""
    got = asyncio.run(reading.gather(want=("budget", "build"), now=T0))

    assert got.budget == OK
    assert read.threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_a_budget_HANDED_IN_is_still_never_read_for(read):
    """The poller reads the budget every tick and hands it down; asking for it again would be a
    second subprocess for a number the caller already has."""
    got = await reading.gather(want=("budget",), budget={"state": "low"}, now=T0)

    assert got.budget == {"state": "low"} and read.calls == 0


# ── 5. one mechanism, two memos ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_BOTH_memos_share_one_single_flight(read):
    """#185 built the shared read for the schedule memo and the budget memo did not get it. A
    second copy beside the first is two mechanisms to keep true."""
    assert isinstance(reading._budget_read, type(reading._intake_read))
    assert reading._budget_read is not reading._intake_read, "one slot for two different reads"

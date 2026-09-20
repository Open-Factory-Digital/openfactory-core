"""The intake memo is read ONCE per window however many arrive, and what it hands out is the
caller's own (GitHub issues #165 and #166).

BOTH WERE FOUND REVIEWING #152, which made the schedule read process-wide, and both are properties
that changed silently when it did:

  #165  `intake_cached` returned the dict it had stored. Before the memo every caller got a freshly
        built answer, so writing to it reached nobody; after it, a write reached every surface for
        the next `INTAKE_TTL_S` seconds. Nothing in the tree writes to it today (`ladder.py` and
        `cli.py` only read, `api/app.py` serialises it) — it was latent, and the next reader that
        annotated the answer before rendering it would have had no way to know.
  #166  nothing serialised the readers that arrive WHILE a read is in flight. Each found an empty
        or expired memo and started its own: six concurrent readers, six reads, each of them
        `1 + N + P` sequential schedule describes. Six sequential readers cost one — the memo
        works, and the gap is the interval between the first read starting and it landing.

EVERY CASE DRIVES THE REAL `intake_cached` with a real `asyncio.gather` over a slow double of
`tv.intake`. Nothing here mocks the lock, a future or the clock's sleep: what is counted is calls
at `tv.intake`, which is the number #146 and #166 are both about.

THE TWO THINGS #145'S POOL LEARNED ON THIS SAME PATH ARE CASES HERE, not remarks (§3 and §4): a
lock is single flight on SUCCESS only unless it is written otherwise, and whatever the waiters
share has to belong to the loop that awaits it.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from openfactory.floor import reading

T0 = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _in_flight():
    """The read this module has registered as in flight, if any. Asked with `getattr` so these
    cases say what they say about BEHAVIOUR against a tree that has no single flight at all."""
    return getattr(reading, "_intake_flight", None)


def _answer() -> dict:
    """The shape `tv.intake` really returns: scalars on top, and one dict per watcher below."""
    return {"known": True, "on": True, "note": "", "every_s": 180.0,
            "watchers": {"openfactory-watch-p0": {"known": True, "on": True, "note": ""}}}


class _Slow:
    """`tv.intake`, counted, and slow enough that readers arriving together overlap."""

    def __init__(self, *, takes: float = 0.05, answer=None, raises: Exception | None = None):
        self.calls, self.takes, self.raises = 0, takes, raises
        self.answer = answer
        self.started = asyncio.Event()

    async def __call__(self, _client=None):
        self.calls += 1
        self.started.set()
        await asyncio.sleep(self.takes)
        if self.raises is not None:
            raise self.raises
        return self.answer() if callable(self.answer) else (self.answer or _answer())


@pytest.fixture
def slow(monkeypatch):
    from openfactory.runtime.temporal import view as tv

    double = _Slow()
    monkeypatch.setattr(tv, "intake", double)
    return double


# ── 1. #165 — what a caller is handed is its own ────────────────────────────────────────────────

async def test_a_caller_that_WRITES_to_its_answer_does_not_rewrite_the_window(slow):
    """The issue's own reproduction: read, write, read again inside the same window."""
    first = await reading.intake_cached(object(), now=T0)
    first["on"] = "MUTATED BY A CALLER"
    second = await reading.intake_cached(object(), now=T0)

    assert slow.calls == 1, "the second read was not served from the window at all"
    assert second is not first
    assert second["on"] is True, (
        f"a caller's write reached the next reader: on={second['on']!r}. Every surface would "
        f"read it for the next {reading.INTAKE_TTL_S:.0f}s (#165)")

    # AND THE SAME FOR AN ANSWER SERVED FROM THE WINDOW. `first` came back from the read and
    # `second` from the memo — two return paths, and a copy on one of them is not a copy on both.
    second["on"] = "MUTATED BY A READER INSIDE THE WINDOW"
    third = await reading.intake_cached(object(), now=T0)
    assert third is not second and third["on"] is True, (
        f"a write to an answer served from the window reached the next reader: {third['on']!r}")


async def test_and_not_through_a_NESTED_value_either(slow):
    """`watchers` is a dict of dicts, so a shallow copy still shares every watcher row — the one
    place a reader is most likely to annotate (rung 10 of `ladder.py` walks it row by row)."""
    for _path in ("the read", "the window"):    # the first answer is the read's, the next the memo's
        got = await reading.intake_cached(object(), now=T0)
        got["watchers"]["openfactory-watch-p0"]["on"] = "MUTATED"
        got["watchers"]["a-watcher-nobody-scheduled"] = {"known": True}
    last = await reading.intake_cached(object(), now=T0)

    assert slow.calls == 1
    assert last["watchers"] == _answer()["watchers"], (
        f"a write through `watchers` reached the next reader: {last['watchers']} (#165)")


async def test_the_FIRST_reader_of_a_window_cannot_rewrite_it_either(slow):
    """The reader that PAID for the read is handed a copy too. Returning the fresh object to it
    and copies to everybody else would leave the memo holding something a caller can write to."""
    first = await reading.intake_cached(object(), now=T0)
    first["note"] = "written by the reader that paid"
    assert (await reading.intake_cached(object(), now=T0))["note"] == ""


async def test_readers_that_SHARED_one_read_do_not_share_one_object(slow):
    got = await asyncio.gather(*(reading.intake_cached(object(), now=T0) for _ in range(3)))
    got[0]["watchers"].clear()
    assert slow.calls == 1
    assert got[1]["watchers"] and got[2]["watchers"], "two waiters were handed the same dict"


async def test_the_copy_is_still_what_the_routes_SERIALISE(slow):
    """Why a copy and not a read-only view: `/api/temporal/jobs` returns it and the stream
    `json.dumps` it. A `MappingProxyType` is refused by `json.dumps` outright."""
    got = await reading.intake_cached(object(), now=T0)
    assert type(got) is dict and type(got["watchers"]) is dict
    assert json.loads(json.dumps(got)) == _answer()


# ── 2. #166 — readers arriving together share one read ──────────────────────────────────────────

async def test_SIX_readers_arriving_together_cost_ONE_read(slow):
    """The issue's measurement: six concurrent → 6, six sequential → 1."""
    got = await asyncio.gather(*(reading.intake_cached(object(), now=T0) for _ in range(6)))

    assert slow.calls == 1, (
        f"six browsers arriving as the window expired cost {slow.calls} schedule reads, not 1 — "
        f"each is 1+N+P sequential describes (#166)")
    assert all(g == _answer() for g in got), "a waiter was not handed the answer it waited for"


async def test_and_the_read_they_shared_FILLS_the_window(slow):
    await asyncio.gather(*(reading.intake_cached(object(), now=T0) for _ in range(6)))
    await reading.intake_cached(object(), now=T0 + timedelta(seconds=reading.INTAKE_TTL_S / 2))
    assert slow.calls == 1

    await reading.intake_cached(object(), now=T0 + timedelta(seconds=reading.INTAKE_TTL_S + 1))
    assert slow.calls == 2, "the window stopped expiring"


async def test_a_read_that_has_LANDED_is_no_longer_in_flight(slow):
    """Single flight is about the read IN FLIGHT. It is not a second memo with no window: once the
    read has landed there is nothing to join, only the window to consult — so a reader past the
    window pays for a fresh read instead of being handed the finished one."""
    await reading.intake_cached(object(), now=T0)
    assert _in_flight() is None, "a finished read is still registered as in flight"

    await reading.intake_cached(object(), now=T0 + timedelta(seconds=reading.INTAKE_TTL_S + 1))
    assert slow.calls == 2


# ── 3. …on FAILURE too, which a lock alone does not give ────────────────────────────────────────

async def test_readers_queued_behind_a_FAILING_read_share_THAT_failure(monkeypatch):
    """What `view.connect()` learned in #145: behind a lock, six callers queued on a 0.5 s refusal
    failed at 0.5 / 1.0 / … / 3.0 s, six attempts one after another — an outage turned into a
    queue. Here: one attempt, and every waiter fails when IT fails."""
    from openfactory.runtime.temporal import view as tv

    refusal = _Slow(takes=0.2, raises=ConnectionError("the engine did not answer"))
    monkeypatch.setattr(tv, "intake", refusal)

    async def _timed():
        began = time.monotonic()
        try:
            await reading.intake_cached(object(), now=T0)
        except ConnectionError as exc:
            return time.monotonic() - began, str(exc)
        return time.monotonic() - began, None

    got = await asyncio.gather(*(_timed() for _ in range(6)))

    assert all(msg == "the engine did not answer" for _, msg in got), (
        f"a waiter did not see the failure it waited behind: {got}")
    assert refusal.calls == 1, (
        f"{refusal.calls} attempts against an engine that is refusing — the waiters each retried "
        f"instead of taking the failure they queued behind")
    slowest = max(t for t, _ in got)
    assert slowest < 0.8, (
        f"the last waiter failed after {slowest:.2f}s; one shared 0.2 s refusal is ~0.2 s, six in "
        f"series is 1.2 s")


async def test_and_a_failure_is_SHARED_NOT_STORED_so_the_next_reader_tries_again(monkeypatch):
    """`intake_cached` never stores a read that failed (#146). Sharing the failure with the
    waiters queued behind it must not become caching it for whoever arrives afterwards — that
    would freeze a panel in "did not answer" for a window after the engine recovered."""
    from openfactory.runtime.temporal import view as tv

    refusal = _Slow(takes=0.01, raises=ConnectionError("down"))
    monkeypatch.setattr(tv, "intake", refusal)
    with pytest.raises(ConnectionError):
        await reading.intake_cached(object(), now=T0)
    assert _in_flight() is None, "a failed read is still registered as in flight"

    recovered = _Slow(takes=0.0)
    monkeypatch.setattr(tv, "intake", recovered)
    assert (await reading.intake_cached(object(), now=T0))["known"] is True
    assert recovered.calls == 1


async def test_an_UNREAD_answer_is_shared_with_its_waiters_and_still_not_stored(monkeypatch):
    """`known: False` is `tv.intake`'s own "could not describe it". The waiters asked the same
    question at the same moment, so they get the same answer; the window does not keep it."""
    from openfactory.runtime.temporal import view as tv

    unread = _Slow(answer={"known": False, "on": None, "note": "", "watchers": {}})
    monkeypatch.setattr(tv, "intake", unread)
    got = await asyncio.gather(*(reading.intake_cached(object(), now=T0) for _ in range(4)))
    assert unread.calls == 1 and all(g["known"] is False for g in got)

    await reading.intake_cached(object(), now=T0)
    assert unread.calls == 2, "an unread answer was kept for the window (#146's rule)"


# ── 4. what the waiters share belongs to the loop that awaits it ────────────────────────────────

def test_a_read_in_flight_on_ANOTHER_loop_is_not_joined(monkeypatch):
    """`techlead/conversation.py` opens an `asyncio.run` per question, and the CLI's
    `poller status` opens one too, so this module is reached from more than one loop in a process's
    life. A future belongs to the loop that made it: awaiting one from another loop raises
    `RuntimeError: … attached to a different loop`, and one whose loop has stopped never resolves.
    So a reader joins a flight only on ITS OWN loop, and otherwise reads for itself."""
    from openfactory.runtime.temporal import view as tv

    double = _Slow(takes=0.05)
    monkeypatch.setattr(tv, "intake", double)

    other = asyncio.new_event_loop()
    try:
        async def _start_and_leave():
            task = asyncio.ensure_future(reading.intake_cached(object(), now=T0))
            await double.started.wait()
            return task

        # A read is now in flight on `other`, and `other` is not running: it cannot land.
        pending = other.run_until_complete(_start_and_leave())
        assert _in_flight() is not None and not pending.done()

        double.started = asyncio.Event()
        got = asyncio.run(asyncio.wait_for(reading.intake_cached(object(), now=T0), timeout=5))
        assert got == _answer()
        assert double.calls == 2, "the second loop should have paid for its own read"

        other.run_until_complete(pending)       # the first loop's read still lands, on its loop
    finally:
        other.close()


# ── 5. one reader going away does not take the read from the others ─────────────────────────────

async def test_a_WAITER_that_is_cancelled_does_not_cancel_the_read_for_the_rest(slow):
    """A browser that disconnects cancels its request. The read it was waiting on is not ITS
    read."""
    readers = [asyncio.ensure_future(reading.intake_cached(object(), now=T0)) for _ in range(4)]
    await slow.started.wait()
    readers[2].cancel()

    got = await asyncio.gather(*readers, return_exceptions=True)
    assert isinstance(got[2], asyncio.CancelledError)
    assert [g for i, g in enumerate(got) if i != 2] == [_answer()] * 3, got
    assert slow.calls == 1


async def test_the_reader_that_STARTED_the_read_being_cancelled_leaves_nobody_hanging(slow):
    """The sharper half. If the read ran inside the first caller's own coroutine, cancelling that
    caller would cancel the read, and the waiters behind it would either inherit a cancellation
    nobody sent them or wait on something that will never land."""
    readers = [asyncio.ensure_future(reading.intake_cached(object(), now=T0)) for _ in range(4)]
    await slow.started.wait()
    readers[0].cancel()

    got = await asyncio.wait_for(asyncio.gather(*readers, return_exceptions=True), timeout=5)
    assert isinstance(got[0], asyncio.CancelledError)
    assert got[1:] == [_answer()] * 3, got
    assert slow.calls == 1
    # …and the read it started still fills the window, because it was read.
    await reading.intake_cached(object(), now=T0)
    assert slow.calls == 1


async def test_a_read_cancelled_BEFORE_IT_BEGAN_does_not_wedge_every_reader_after_it(slow):
    """A task cancelled before its first step never enters its coroutine, so a `finally` in the
    read would not run and the finished task would sit in the slot — and every later reader on
    this loop would join it and be handed its `CancelledError`, for as long as the process lived.
    `asyncio.run` cancels what is left at teardown, which is when this happens for real; driven
    here by cancelling the registered task in the one loop turn between its creation and its
    first step."""
    first = asyncio.ensure_future(reading.intake_cached(object(), now=T0))
    await asyncio.sleep(0)                      # `first` has registered the read; it has not begun
    assert slow.calls == 0 and _in_flight() is not None
    _in_flight().task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    assert _in_flight() is None, "a read that never began is still registered as in flight"
    assert await asyncio.wait_for(reading.intake_cached(object(), now=T0), timeout=5) == _answer()
    assert slow.calls == 1


# ── 6. the blip still drops everything from before it (#139) ────────────────────────────────────

async def test_forget_intake_DETACHES_a_read_in_flight_so_its_answer_does_not_fill_the_window(slow):
    """`forget_intake` is the stream's "never carry an intake read from before the blip". A read
    that was already in flight when the blip was seen STARTED before it: its waiters still get
    their answer — they asked before the blip too — but it must not land in the window and be
    served as fresh for ten seconds afterwards."""
    before = asyncio.ensure_future(reading.intake_cached(object(), now=T0))
    await slow.started.wait()
    reading.forget_intake()
    assert _in_flight() is None

    assert await before == _answer()
    assert reading._intake_memo is None, "the read from before the blip filled the window"

    await reading.intake_cached(object(), now=T0)
    assert slow.calls == 2


async def test_forget_intake_still_drops_a_STORED_answer(slow):
    await reading.intake_cached(object(), now=T0)
    reading.forget_intake()
    await reading.intake_cached(object(), now=T0)
    assert slow.calls == 2


# ── 7. the sibling memo had the first half of the same shape ────────────────────────────────────

def test_the_BUDGET_memo_hands_out_a_copy_too(monkeypatch):
    """`_budget_cached` is the memo whose rule the intake one inherits, and it returned its stored
    dict the same way. It is synchronous, so it has no concurrent readers to serialise — only the
    aliasing half applies."""
    calls = []

    def _budget():
        calls.append(1)
        return {"state": "ok", "trackers": [{"kind": "github", "remaining": 4000}]}

    monkeypatch.setattr(reading, "_budget", _budget)
    for _path in ("the read", "the window"):    # as above: two return paths, each its own copy
        got = reading._budget_cached(now=T0)
        got["state"] = "MUTATED"
        got["trackers"][0]["remaining"] = 0
    last = reading._budget_cached(now=T0)

    assert len(calls) == 1
    assert last == {"state": "ok", "trackers": [{"kind": "github", "remaining": 4000}]}

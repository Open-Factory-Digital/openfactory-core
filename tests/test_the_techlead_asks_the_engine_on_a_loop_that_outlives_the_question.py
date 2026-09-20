"""A worker that answers N questions does not hold N engine clients (GitHub issue #147).

THE SAME SHAPE AS #134, ONE LAYER DOWN. `techlead/conversation.py::gather_jobs` is synchronous —
`techlead_ask` runs it on a worker thread, because `answer` clones a repository and runs an agent —
so to read the engine it opened an event loop of its own: `asyncio.run(_run())`, once per question.
`view.connect()` pools the read side's client BY THE LOOP THAT MADE IT, which is right (a client
handed to a loop that did not make it is a broken read), and the consequence is that every question
got a fresh loop, so a fresh client. The installed `temporalio` exposes nothing to close one with,
so dropping it releases nothing. Measured on a throwaway dev server, 2026-09-18, counting this
process's established connections to the engine's port after each `gather_jobs`:

    before:  1, 2, 3, 4, 5, 6
    after:   1, 1, 1, 1, 1, 1

THE FIX IS TO STOP MAKING LOOPS, not to change the pool's key. A caller with no loop of its own
runs its engine reads on ONE standing loop the process keeps (`standing.from_a_thread`), so the key
is the same from question to question and the pool does what it already did for the panel.

EVERY CASE GOES THROUGH THE REAL POOL AND THE REAL STANDING LOOP. What is doubled is
`connection.connect` — the one call that would open a socket, and the one
`tests/conftest.py::_no_live_durable_engine` forbids — by a counter, so what is measured is how
many clients were OPENED, which is the number the issue is about.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from openfactory.runtime.temporal import connection, standing
from openfactory.runtime.temporal import view as tv
from openfactory.techlead import conversation

THREAD_NAME = "openfactory-engine-reads"


class _Sentinel:
    def __init__(self, n: int) -> None:
        self.n = n


class _Counter:
    """`connection.connect`, counted. It suspends before it answers, as opening a client does —
    see `test_the_panel_holds_one_engine_client.py::_Counter` for what a fake that never yields
    fails to model."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> _Sentinel:
        await asyncio.sleep(0)
        self.calls += 1
        return _Sentinel(self.calls)


@pytest.fixture
def engine(monkeypatch) -> _Counter:
    """A declared engine, a counting `connection.connect`, an empty pool — and a job list that
    records WHICH client each question read with."""
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    counter = _Counter()
    counter.read_with = []

    async def _list_jobs(client, _ns, *, limit=50):
        counter.read_with.append(client)
        return []

    monkeypatch.setattr(connection, "connect", counter)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    tv.reset_clients()
    return counter


@pytest.fixture(autouse=True)
def _each_case_makes_its_own_standing_loop():
    """Forgotten before, so every case IS the first caller; stopped after, so a cut that makes the
    thread something other than a daemon fails its case instead of holding the run open at exit —
    `tools/mutate.py` waits for the process, with no deadline."""
    standing._forget_the_standing_loop()
    yield
    standing._forget_the_standing_loop()


def _project():
    return SimpleNamespace(name="acme")


def _standing_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == THREAD_NAME and t.is_alive()]


# ── 1. the property from the issue ──────────────────────────────────────────────────────────────

def test_SIX_questions_open_ONE_engine_client(engine):
    for _ in range(6):
        assert conversation.gather_jobs(_project()) == []

    assert engine.calls == 1, (
        f"six questions opened {engine.calls} engine clients. Nothing can close one, so a worker "
        f"answering questions all day holds one per question it was ever asked (#147)")
    assert len(engine.read_with) == 6 and len({id(c) for c in engine.read_with}) == 1, (
        "the questions did not all read with the one client")


async def test_and_the_same_from_the_THREADS_the_worker_really_asks_from(engine):
    """`techlead_ask` is `await asyncio.to_thread(conversation.answer, …)`: a running loop on the
    main thread, the question on a pool thread, a different one each time it likes. Some of them
    at once, because two people may ask at once — and a cold worker then races itself for the
    first client exactly as a cold panel does."""
    await asyncio.gather(*(asyncio.to_thread(conversation.gather_jobs, _project())
                           for _ in range(4)))
    for _ in range(3):
        await asyncio.to_thread(conversation.gather_jobs, _project())

    assert engine.calls == 1, f"seven questions from worker threads opened {engine.calls} clients"
    assert len(engine.read_with) == 7


def test_the_reads_run_on_ONE_standing_thread_however_many_ask(engine):
    for _ in range(5):
        conversation.gather_jobs(_project())
    assert len(_standing_threads()) == 1, (
        f"{len(_standing_threads())} standing loops — a loop per question is the defect, moved")
    assert _standing_threads()[0].daemon, "a standing loop that is not a daemon holds the process open"


def test_TWO_first_callers_at_once_start_ONE_loop(engine, monkeypatch):
    """The standing loop is made lazily, so the first question makes it — and the first TWO may
    arrive together. Made slow here so both are inside the making of it at the same moment."""
    made = []
    real = asyncio.new_event_loop

    def _slow_new_loop():
        made.append(1)
        time.sleep(0.05)
        return real()

    monkeypatch.setattr(standing.asyncio, "new_event_loop", _slow_new_loop)
    start = threading.Barrier(2)

    def _ask():
        start.wait(timeout=5)
        conversation.gather_jobs(_project())

    askers = [threading.Thread(target=_ask) for _ in range(2)]
    for t in askers:
        t.start()
    for t in askers:
        t.join(timeout=10)

    assert len(made) == 1, f"two first callers made {len(made)} standing loops"
    assert engine.calls == 1


# ── 2. what it must not become ──────────────────────────────────────────────────────────────────

async def test_a_caller_that_IS_running_a_loop_is_refused_by_name_and_nothing_is_started(engine):
    """Blocking a running loop on another loop's answer stalls everything that loop serves — in the
    worker, every activity. `asyncio.run` refused this case too (it raises inside a running loop);
    the refusal stays, and says what to do instead."""
    started = []

    async def _read():
        started.append(1)

    with pytest.raises(RuntimeError, match="await"):
        standing.from_a_thread(_read)
    assert not started, "the read was started for a caller that was refused"

    # …and the gatherer keeps its promise through it: no job state, never a traceback.
    assert conversation.gather_jobs(_project()) == []
    assert engine.calls == 0


def test_a_read_that_RAISES_raises_in_the_caller_and_the_gatherer_degrades(engine, monkeypatch):
    async def _refuses():
        raise ConnectionError("the engine refused")

    with pytest.raises(ConnectionError, match="the engine refused"):
        standing.from_a_thread(_refuses)

    monkeypatch.setattr(connection, "connect", _refuses)
    tv.reset_clients()
    assert conversation.gather_jobs(_project()) == []


def test_the_DEADLINE_every_read_has_still_holds_on_the_standing_loop(engine, monkeypatch):
    """#159/#161 bounded every engine read somebody waits for. Moving the reads to another loop
    must not move them out from under that bound."""
    async def _never_answers():
        await asyncio.sleep(30)

    monkeypatch.setattr(connection, "connect", _never_answers)
    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", "0.2")
    tv.reset_clients()

    began = time.monotonic()
    with pytest.raises(tv.EngineUnreachable):
        standing.from_a_thread(tv.connect)
    assert time.monotonic() - began < 5, "the read waited past its deadline"


def test_a_standing_loop_that_DIED_is_replaced_rather_than_asked_for_ever(engine):
    """Nothing in this tree stops it. But a loop that ended — a `SystemExit` raised inside a read
    ends `run_forever` — would otherwise refuse every question for the rest of the worker's life,
    and the only remedy would be a restart nobody knows to do."""
    conversation.gather_jobs(_project())
    first = _standing_threads()[0]
    standing._STANDING.loop.call_soon_threadsafe(standing._STANDING.loop.stop)
    first.join(timeout=5)
    assert not first.is_alive()

    assert conversation.gather_jobs(_project()) == []
    assert len(engine.read_with) == 2, "the question after the loop died was not answered"
    assert len(_standing_threads()) == 1 and _standing_threads()[0] is not first


# ── 3. the pool's own line is not moved ─────────────────────────────────────────────────────────

def test_a_client_is_STILL_never_handed_to_a_loop_that_did_not_make_it(engine):
    """The key stays the running loop — `test_the_panel_holds_one_engine_client.py` cases 5-6 hold
    that for two `asyncio.run` calls. Here for the pair this change creates: the standing loop and
    a loop of the caller's own, in one process, are two clients and never one shared across."""
    on_the_standing_loop = standing.from_a_thread(tv.connect)
    on_my_own = asyncio.run(tv.connect())
    assert on_the_standing_loop is not on_my_own
    assert engine.calls == 2

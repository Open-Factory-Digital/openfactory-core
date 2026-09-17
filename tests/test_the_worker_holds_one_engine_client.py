"""A worker that answers N questions holds ONE engine client, not N — issue #147.

`techlead/conversation.py::gather_jobs` ran `asyncio.run(_run())` once per question, and `_run`
awaits `view.connect()`. The pool behind `connect()` is keyed by `(engine target, RUNNING LOOP)`
and holds one entry in total (#134/#145), so a new loop per question is a new key per question: one
gRPC client opened per question and dropped unreleased. Dropping is not releasing — checked against
the INSTALLED temporalio 1.33.0 (re-checked 2026-09-17, unchanged since #134): neither `Client` nor
`ServiceClient` nor the bridge client under it exposes `close`, `shutdown`, `__aexit__` or
`__del__`. That is #134's leak in the worker process, on a human's clock instead of a poll tick.

The fix is `view.read_sync()`: ONE lazily-started daemon loop per process, submitted to with
`run_coroutine_threadsafe`, blocking the calling thread for the result — so `entry.loop is loop`
holds across questions and the pool answers the second question with the first one's client.
`test_the_panel_holds_one_engine_client.py` (case 5) still holds the pool's loop term, which has
not changed: twelve `asyncio.run(` call sites in the package still open a loop of their own.

THIS FILE DRIVES THE THING, it never reads text about it. There is no live engine in this container
and the suite forbids reaching one, so the number measured here is the CONNECT COUNT: it counts
calls to `connection.connect` — the one function `view.connect` resolves at call time — and asserts
that five questions produce one. No latency is claimed; #147 was filed from the source and never
timed on a deployment.

`view.connect` imports `connection.connect` INSIDE the function, so patching the module attribute
is what takes effect; the guard must NOT patch `view.connect`, which would bypass the pool the
property lives in. `TEMPORAL_ADDRESS` is declared in every case because the pool key is
`connection.fingerprint()`, which raises `EngineNotDeclared` when nobody said (#163).
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from openfactory.contracts.project import Project, ProviderRef
from openfactory.runtime.temporal import connection
from openfactory.runtime.temporal import view as tv
from openfactory.techlead import conversation

ROOT = Path(__file__).resolve().parents[1]


class _Sentinel:
    """A client that is not a client. Distinguishable by identity, and nothing in these cases ever
    performs an engine read on it: `list_jobs` is faked and the rows are `running`, which
    `_worth_a_verdict` scores 0, so no verdict query is asked of it."""

    def __init__(self, n: int) -> None:
        self.n = n

    def __repr__(self) -> str:
        return f"<sentinel client {self.n}>"


class _Counter:
    """A stand-in for `connection.connect` that says how many times it was actually called.

    IT SUSPENDS BEFORE IT ANSWERS, and that line is what makes the concurrency case a guard.
    Opening a gRPC client is I/O; a fake that returns without ever yielding to the loop does not
    model it, and PR #145 measured what that costs: with no `sleep(0)`, `asyncio.gather` ran each
    task to completion in its first step and the mutation row deleting the single-flight lock
    survived a full green run (2026-09-15) — the guard could not see its own cut.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> _Sentinel:
        await asyncio.sleep(0)
        self.calls += 1
        return _Sentinel(self.calls)


@pytest.fixture(autouse=True)
def read_loop_starts_and_ends_here():
    """A read loop that belongs to this test, on both ends.

    BEFORE, for the reason `tests/conftest.py` gives about the client pool: what a test leaves
    behind is its own business, and clearing before is what makes this one start from nothing
    whatever ran earlier — the loop identity cases below are assertions about a loop that must
    have been created here.

    AFTER, because this file is also what the mutation plan runs: the row that drops `daemon=True`
    leaves a thread running `run_forever`, which never returns on its own, and a non-daemon one
    would hold the interpreter open after the last test — the runner would read that as a hang
    rather than as the red row it is. `reset_read_loop()` stops and joins it either way.
    """
    tv.reset_read_loop()
    yield
    tv.reset_read_loop()


@pytest.fixture
def engine(monkeypatch) -> _Counter:
    """A declared engine, a counting `connection.connect`, and a pool that starts empty."""
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    counter = _Counter()
    monkeypatch.setattr(connection, "connect", counter)
    tv.reset_clients()
    return counter


@pytest.fixture
def floor(monkeypatch, engine) -> _Counter:
    """The tech-lead's read path with everything but the CONNECT faked.

    `view.connect` is deliberately left alone — it is the pool this property lives in. What is
    replaced is the engine listing (`view.list_jobs`, which would speak gRPC to the sentinel) and
    the three tracker/board reads `gather_jobs` enriches with, each of which is a provider call
    guarded by its own test file (`test_the_techlead_reads_through_the_ports.py`).
    """
    async def _list_jobs(client, ns, *, limit=50):
        await asyncio.sleep(0)
        return [{"project": "books", "issue": "69", "state": "running"},
                {"project": "outra", "issue": "99", "state": "running"}]

    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(conversation, "ticket_index",
                        lambda project, refs, tracker=None: {
                            "69": {"state": "closed", "title": "Plan 88.1 — Spreadsheet import"}})
    monkeypatch.setattr(conversation, "board_index", lambda project: {"69": "Done"})
    monkeypatch.setattr(conversation, "comments_for", lambda project, jobs, tracker=None: {})
    monkeypatch.setattr(conversation, "tracker_for", lambda project: object())
    return engine


def _project() -> Project:
    return Project(name="books", repo_path="/tmp/books",
                   tracker=ProviderRef(kind="github", repo="o/r"))


async def _which_loop() -> tuple[asyncio.AbstractEventLoop, int]:
    """What loop and what thread the read actually ran on."""
    await asyncio.sleep(0)
    return asyncio.get_running_loop(), threading.get_ident()


# ── 1. the property from the issue, at the surface that has it ─────────────────────────────────

def test_FIVE_questions_open_ONE_engine_client(floor):
    """Five questions were five clients, none of them releasable. Five questions are one client.

    Driven through the real `gather_jobs` — the function the issue names — with the counter at the
    `connection.connect` seam, so the number here is the one `lsof -nP -p <worker pid> -iTCP` would
    have counted on the worker.

    IT ALSO ASSERTS THE ANSWER, so this guard cannot pass on a read that came back broken: a
    `gather_jobs` that raised on every question would hold one client too, and answer every person
    with an empty floor.
    """
    project = _project()

    answers = [conversation.gather_jobs(project) for _ in range(5)]

    assert floor.calls == 1, (
        f"five questions to the tech-lead opened {floor.calls} engine clients — temporalio 1.33.0 "
        f"exposes no `close`, so every one past the first is held for the life of the worker")
    assert len(tv._CLIENTS) == 1, (
        f"five questions left {len(tv._CLIENTS)} entries in the pool: {tv._CLIENTS!r}")
    for jobs in answers:
        assert [j["issue"] for j in jobs] == ["69"], (
            f"the jobs came back wrong ({jobs!r}) — another project's job leaked in, or the read "
            f"never happened and this guard would be counting an engine nobody asked")
        assert jobs[0]["ticket_state"] == "closed"
        assert jobs[0]["title"] == "Plan 88.1 — Spreadsheet import"
        assert jobs[0]["board"] == "Done"


# ── 2. one loop, and it is not the caller's ────────────────────────────────────────────────────

def test_the_read_loop_is_ONE_loop_across_calls_and_is_NOT_the_callers(engine):
    """The mechanism under case 1: the pool reuses an entry only while the running loop IS the one
    that made it, so "one client across questions" is exactly "one loop across questions".

    And it is a loop of this module's own, on another thread — which is what keeps a connect that
    hangs (still hanging after 40 s when #145's probe gave up) inside the gatherer's own thread,
    where it already blocked, instead of on the worker's activity loop."""
    first, first_thread = tv.read_sync(_which_loop())
    second, second_thread = tv.read_sync(_which_loop())

    assert first is second, (
        f"two reads ran on two loops ({first!r}, {second!r}) — a loop per read is a key per read "
        f"in the pool, which is a client per read")
    assert first is tv._READ_LOOP, "the read did not run on the loop this module holds"
    assert first_thread == second_thread != threading.get_ident(), (
        f"the read ran on the CALLER's thread ({first_thread}/{second_thread} vs "
        f"{threading.get_ident()}) — a blocking read on the caller's own loop stalls whatever "
        f"that loop is serving")

    mine, _ = asyncio.run(_which_loop())

    assert mine is not first, (
        "the read loop is the loop an `asyncio.run` on this thread creates — then it dies with "
        "the call, and the next question re-keys the pool")


# ── 3. a thread that already has a loop is refused, by name ────────────────────────────────────

async def test_a_caller_that_already_has_a_RUNNING_LOOP_is_refused_BY_NAME(floor):
    """`read_sync` blocks its thread until the engine answers, so it must never be called on a live
    loop — `actions/catalog.py::_ask` documents that contract and both production callers honour it
    with `asyncio.to_thread` (`activities.py::techlead_ask`, `_ask` itself).

    `asyncio.run` refused this by raising `RuntimeError: asyncio.run() cannot be called from a
    running event loop`, which is a raw traceback naming no remedy. The refusal is KEPT and given a
    sentence — the house rule is that anything a caller can hit says the cause and the way out.

    This case is `async def`, so the test's own thread is the one with the running loop.
    """
    with pytest.raises(tv.ReadNeedsItsOwnThread) as refused:
        tv.read_sync(_which_loop())

    said = str(refused.value)
    assert "running event loop" in said and "asyncio.to_thread" in said, (
        f"the refusal does not say what happened and what to do instead: {said!r}")

    assert conversation.gather_jobs(_project()) == [], (
        "`gather_jobs` called from a thread with a running loop must degrade to [] as it did when "
        "`asyncio.run` raised here — the contract `_ask` is built around")
    assert floor.calls == 0, "a refused read opened an engine client anyway"


# ── 4. an exception inside the read reaches the caller, unchanged ──────────────────────────────

def test_an_exception_raised_INSIDE_the_read_reaches_the_SYNC_caller(engine):
    """`gather_jobs`' `except Exception` net is what turns an unreachable engine into `[]` instead
    of a traceback in a person's answer. A helper that swallowed what the coroutine raised would
    leave that net catching nothing and the caller unpacking a `None`."""
    async def boom():
        await asyncio.sleep(0)
        raise RuntimeError("the engine did not answer")

    with pytest.raises(RuntimeError, match="the engine did not answer") as seen:
        tv.read_sync(boom())

    assert type(seen.value) is RuntimeError, (
        f"the read's exception reached the caller as {type(seen.value).__name__} — a wrapped or "
        f"replaced exception is a caller that can no longer tell what happened")


# ── 5. …and the documented degradation is intact ───────────────────────────────────────────────

def test_gather_jobs_still_answers_EMPTY_when_the_engine_is_unreachable(floor, monkeypatch):
    """Existing, documented behaviour (`gather_jobs`: *"Returns `[]` when Temporal is
    unreachable"*), asserted here because this change moves the loop the failure travels through:
    the exception is now raised on the read loop and re-raised on the caller's thread."""
    async def refuse():
        await asyncio.sleep(0)
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)

    assert conversation.gather_jobs(_project()) == [], (
        "an unreachable engine reached the person as something other than an empty floor — the "
        "caller says so; it must never answer with a traceback")


# ── 6. the thread is a daemon ──────────────────────────────────────────────────────────────────

def test_the_read_loop_thread_is_a_DAEMON(engine):
    """`run_forever` never returns on its own and nothing stops this loop in production, so a
    non-daemon thread would hold a finished `openfactory act ask` — or a worker shutting down —
    open for ever. Asserted on the live thread object, not on the argument in the source."""
    tv.read_sync(_which_loop())

    assert tv._READ_THREAD is not None and tv._READ_THREAD.is_alive(), (
        f"the read loop's thread is {tv._READ_THREAD!r} after a read ran on it")
    assert tv._READ_THREAD.daemon is True, (
        "the read loop runs on a NON-daemon thread — `run_forever` never returns, so the process "
        "cannot exit once anybody has asked the tech-lead a question")


# ── 7. two threads, one loop, one client ───────────────────────────────────────────────────────

def test_EIGHT_THREADS_arriving_at_once_share_ONE_loop_and_ONE_client(engine):
    """The worker answers questions on `asyncio.to_thread`, so two questions at once arrive here on
    two threads at once — `Thread.start()` waits for the new thread to come up, which releases the
    GIL squarely inside the window between "is there a loop?" and "here it is". Two loops there are
    two pool keys, which is two clients: the defect this file is about, arriving by another door.

    The barrier is what makes this a race rather than a sequence."""
    ready = threading.Barrier(8)
    got: list[tuple] = []
    trouble: list[BaseException] = []

    def ask() -> None:
        try:
            ready.wait(timeout=10)
            loop, _ident = tv.read_sync(_which_loop())
            got.append((loop, tv.read_sync(tv.connect())))
        except BaseException as exc:  # noqa: BLE001 — a thread's failure must reach the assertions
            trouble.append(exc)

    threads = [threading.Thread(target=ask, name=f"asker-{i}") for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not trouble, f"a calling thread raised: {trouble!r}"
    assert len(got) == 8, f"only {len(got)} of eight threads came back"
    assert len({id(loop) for loop, _client in got}) == 1, (
        f"eight threads arriving together got {len({id(x) for x, _ in got})} read loops — the "
        f"create is not behind a lock, so a worker answering two questions at once opens two")
    assert engine.calls == 1, (
        f"eight threads opened {engine.calls} engine clients")
    assert len({id(client) for _loop, client in got}) == 1, (
        f"the eight threads were handed different clients: {got!r}")


# ── 8. nothing starts until somebody asks ──────────────────────────────────────────────────────

def test_IMPORTING_the_module_does_not_start_the_loop(tmp_path):
    """Lazy, so a process that never asks the tech-lead anything never starts a thread — `openfactory
    doctor`, the CLI's fast paths and a worker that only executes jobs all import this module.

    RUN IN A FRESH INTERPRETER, because by the time this test runs another case in this file (or
    another file in the suite) may already have started the loop in THIS one. The child imports the
    module and nothing else, and reports what it sees.
    """
    probe = ("import threading;"
             "from openfactory.runtime.temporal import view;"
             "print(view._READ_LOOP, view._READ_THREAD,"
             " [t.name for t in threading.enumerate() if 'openfactory' in t.name])")
    out = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True,
                         timeout=120)

    assert out.returncode == 0, f"the probe did not run: {out.stderr[-800:]}"
    assert out.stdout.strip() == "None None []", (
        f"importing `view` started the read loop: {out.stdout.strip()!r} — an import must not "
        f"cost a thread")


# ── 9. the reset seam the tests are entitled to ────────────────────────────────────────────────

def test_reset_read_loop_STOPS_the_loop_and_the_next_read_starts_a_new_one(engine):
    """The seam beside `reset_clients()`. It takes the pool with it, because a client keyed to a
    loop that has been stopped can never be reused: `connect()` would refuse it on loop identity
    and re-key, which is the one thing that must not be left to chance in a test file that counts
    connects.

    IT CONNECTS BEFORE IT RESETS, and that line is the difference between a guard and a decoration.
    Written without it, this case asserted an empty pool that `tests/conftest.py` had already
    emptied before the test began — and the mutation row that DELETES the `reset_clients()` call
    from `reset_read_loop()` survived a full green run (2026-09-17)."""
    first, _ = tv.read_sync(_which_loop())
    tv.read_sync(tv.connect())          # the pool must HOLD something, or the clear below is unseen
    stopped = tv._READ_THREAD

    assert len(tv._CLIENTS) == 1, "nothing was pooled, so this case would prove nothing"

    tv.reset_read_loop()

    assert tv._READ_LOOP is None and tv._READ_THREAD is None, (
        f"reset_read_loop() left {tv._READ_LOOP!r}/{tv._READ_THREAD!r} behind")
    assert stopped is not None and not stopped.is_alive(), (
        "the read loop's thread is still running after its loop was stopped and joined")
    assert not tv._CLIENTS, f"the pool kept {tv._CLIENTS!r}, keyed to a loop that no longer runs"

    second, _ = tv.read_sync(_which_loop())

    assert second is not first, "the next read ran on the loop that was supposed to be stopped"

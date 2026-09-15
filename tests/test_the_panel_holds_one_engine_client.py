"""The panel holds ONE engine client, instead of opening a fresh one per request — issue #134.

`openfactory/runtime/temporal/view.py::connect()` was three lines with no memory, and every
read-side caller resolves through it: `/api/floor` and `/api/floor/{project}` (the page asks for one
of the two on every engine frame — `panel.html::applyEngine`), `/api/inbox`,
`/api/coordinator/messages`, `/api/temporal/jobs`, `/api/decisions`, the action catalog's
`_connected()`. So a panel process opened one gRPC client per request and
released none.

MEASURED BY THE REPORTER, 2026-09-15, on a freshly restarted panel with NO browser attached: six
sequential `/api/floor` requests took it from 20 to 32 open gRPC connections to the engine.
Overnight: 41 connections, 7-13 % idle CPU, 20-27 s per request — against 0.18 s for the same
`gather(EVERYTHING)` called in-process. A restart put it back to ~2 s.

THIS FILE DRIVES THE THING, it never reads text about it. There is no live engine in this container
and the suite forbids reaching one, so the number this guard measures is the CONNECT COUNT: it
counts calls to `connection.connect` — the one function `view.connect` resolves at call time — and
asserts N requests produce one. Latency is the reporter's measurement and is quoted as theirs.

`view.connect` imports `connection.connect` INSIDE the function, so patching the module attribute
is what takes effect; binding a fake onto `view.connect` itself would bypass the pool entirely and
prove nothing. And `TEMPORAL_ADDRESS` is declared in every case because the pool key is
`connection.fingerprint()`, which raises `EngineNotDeclared` when nobody said (#163).
"""

from __future__ import annotations

import asyncio

import pytest

from openfactory.runtime.temporal import connection
from openfactory.runtime.temporal import view as tv


class _Sentinel:
    """A client that is not a client. Distinguishable by identity, and every engine read performed
    on it raises — which is what makes case 1 assert a 200 rather than a 500: the floor is supposed
    to DEGRADE to an unread engine, not take the route down."""

    def __init__(self, n: int) -> None:
        self.n = n

    def __repr__(self) -> str:  # what a pool `repr` would print
        return f"<sentinel client {self.n}>"


class _Counter:
    """A stand-in for `connection.connect` that says how many times it was actually called.

    IT SUSPENDS BEFORE IT ANSWERS, and that one line is what makes the concurrency case a guard.
    Opening a gRPC client is I/O; a fake that returns without ever yielding to the loop does not
    model it, because `asyncio.gather` then runs each task to completion in its first step and the
    second caller finds the pool already filled. Measured: with no `sleep(0)` here, the mutation
    row that DELETES the single-flight lock survived a full green run (2026-09-15) — the guard
    could not see its own cut.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> _Sentinel:
        await asyncio.sleep(0)
        self.calls += 1
        return _Sentinel(self.calls)


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


# ── 1. the property from the issue, at the surface that has it ──────────────────────────────────

def test_two_floor_requests_open_ONE_client(engine, monkeypatch, tmp_path):
    """Six requests were 12 more connections. Two requests are one client.

    `TestClient` IS USED AS A CONTEXT MANAGER, and that is the whole difference between a guard
    and a decoration. Starlette holds ONE blocking portal — one event loop — for the `with` block,
    which is what a uvicorn process is. `TestClient(app).get(...)` twice starts a portal per
    request, so the second request runs on a second loop, the pool correctly refuses the first
    loop's entry, and the counter reads 2 no matter how the pool behaves. Verified empirically
    while writing this: if this ever reads 2, look at the portal before you look at the pool.

    The route setup is `test_the_floor_is_a_platform_capability.py::test_the_route_ANSWERS`'s.
    """
    from starlette.testclient import TestClient

    from openfactory.api import app as api

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)

    with TestClient(api.app) as client:
        first = client.get("/api/floor")
        second = client.get("/api/floor")

    assert first.status_code == 200 and second.status_code == 200, (
        f"the floor stopped answering: {first.status_code}/{second.status_code} — this guard must "
        f"not be able to pass on a 500")
    assert engine.calls == 1, (
        f"two /api/floor requests opened {engine.calls} engine clients — the panel re-reads this "
        f"route on every engine frame, which is how 20 connections became 41 overnight")


# ── 2-3. the pool itself ────────────────────────────────────────────────────────────────────────

async def test_repeated_connects_on_one_loop_return_the_SAME_client(engine):
    a = await tv.connect()
    b = await tv.connect()
    c = await tv.connect()

    assert a is b is c, f"three connects handed back {a!r}, {b!r}, {c!r}"
    assert engine.calls == 1, f"three connects opened {engine.calls} clients"


async def test_CONCURRENT_first_calls_open_one_client(engine):
    """The single-flight half, and it is the normal case rather than an edge: the panel page issues
    several requests on load and then re-reads the floor on every engine frame, so a cold process
    races itself immediately. Without a lock every one of these sees an empty pool and connects."""
    got = await asyncio.gather(*(tv.connect() for _ in range(8)))

    assert engine.calls == 1, (
        f"eight concurrent first calls opened {engine.calls} clients — the create is not behind a "
        f"lock, so a cold panel still opens one per concurrent request")
    assert all(x is got[0] for x in got), f"the eight callers did not get one client: {got!r}"


# ── 4. a failure is never cached ────────────────────────────────────────────────────────────────

async def test_a_FAILED_connect_is_not_cached(engine, monkeypatch):
    """Caching a failure would freeze a panel in "the engine did not answer" until somebody
    restarted it — the same class of defect as the one being fixed. So it raises what it raised,
    every time, and leaves nothing behind that a later success has to get past."""
    async def refuse():
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)

    with pytest.raises(RuntimeError, match="the engine did not answer"):
        await tv.connect()
    with pytest.raises(RuntimeError, match="the engine did not answer"):
        await tv.connect()

    monkeypatch.setattr(connection, "connect", engine)
    got = await tv.connect()

    assert isinstance(got, _Sentinel), (
        f"the engine came back and the pool still answered {got!r} — a cached failure outlives the "
        f"outage that caused it")
    assert engine.calls == 1


# ── 5-6. the regression guard: `gather_jobs`' shape ─────────────────────────────────────────────

def test_a_SECOND_asyncio_run_does_not_get_the_first_runs_client(engine):
    """`techlead/conversation.py::gather_jobs` runs `asyncio.run(_run())` inside the worker, once
    per question, and `_run` awaits `view.connect()`. A client made on a loop that has since closed
    and handed to the next `asyncio.run` is a broken read in a path that works today — a regression
    traded for a panel fix.

    Driven as two real `asyncio.run` calls, which is why this case is `def` and not `async def`."""
    first = asyncio.run(tv.connect())
    second = asyncio.run(tv.connect())

    assert engine.calls == 2, (
        f"two separate `asyncio.run` calls opened {engine.calls} clients — the second run was "
        f"handed a client belonging to a loop that is now closed")
    assert first is not second, f"both runs got {first!r}"


def test_and_the_dead_loop_leaves_NO_entry_behind(engine):
    """A pool that keeps one entry per dead loop is the same leak wearing a cache's name. Asserted
    against the pool object the module holds, not against a string."""
    asyncio.run(tv.connect())
    asyncio.run(tv.connect())
    asyncio.run(tv.connect())

    assert len(tv._CLIENTS) == 1, (
        f"three closed loops left {len(tv._CLIENTS)} entries in the pool: {tv._CLIENTS!r} — at "
        f"most one live entry per engine target")


# ── 7. the target is part of the key ────────────────────────────────────────────────────────────

async def test_a_MOVED_engine_gets_a_new_client(engine, monkeypatch):
    first = await tv.connect()
    monkeypatch.setenv("TEMPORAL_ADDRESS", "somewhere.else:7233")
    second = await tv.connect()

    assert engine.calls == 2, (
        f"the engine moved and the pool opened {engine.calls} clients — a client held for the old "
        f"address is a panel reading an engine this deployment no longer points at")
    assert first is not second


async def test_a_CHANGED_CREDENTIAL_gets_a_new_client_at_the_same_address(engine, monkeypatch):
    """The half that makes the auth digest in the key a guard rather than a decoration: a
    redeployment that rotates the API key while keeping the address must not be served by a client
    still holding the old credential."""
    monkeypatch.setenv("TEMPORAL_API_KEY", "key-before-the-rotation")
    first = await tv.connect()
    monkeypatch.setenv("TEMPORAL_API_KEY", "key-after-the-rotation")
    second = await tv.connect()

    assert engine.calls == 2, (
        f"the credential rotated and the pool opened {engine.calls} clients — the address never "
        f"changed, so only the auth material in the key can tell these apart")
    assert first is not second


# ── 8. and the secret does not travel in it ─────────────────────────────────────────────────────

async def test_the_SECRET_is_not_in_the_key(engine, monkeypatch):
    """A pool key reaches a log line, a `repr` and a test failure message — including the ones in
    this very file, which print `tv._CLIENTS`. The digest answers "did this change?" and nothing
    else."""
    secret = "sk-a-real-looking-temporal-api-key-0123456789"
    monkeypatch.setenv("TEMPORAL_API_KEY", secret)

    await tv.connect()

    assert secret not in repr(tv._CLIENTS), (
        "the raw TEMPORAL_API_KEY is in the pool's repr — a failure message or a log line now "
        "carries the deployment's credential")
    assert secret not in repr(connection.fingerprint()), (
        "the raw TEMPORAL_API_KEY is in the fingerprint — digest it, do not carry it")


# ── 9. the reset seam the suite depends on ──────────────────────────────────────────────────────

async def test_reset_clients_EMPTIES_the_pool(engine):
    """`tests/conftest.py` calls this before every test. Without it a fake client one test left in
    the pool becomes the next test's engine, and the failure that follows depends on which tests
    ran first."""
    await tv.connect()
    tv.reset_clients()

    assert not tv._CLIENTS, f"reset_clients() left {tv._CLIENTS!r} behind"

    await tv.connect()

    assert engine.calls == 2, f"the pool survived its own reset ({engine.calls} connects)"

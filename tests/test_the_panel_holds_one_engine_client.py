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
import traceback

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
    """A synchronous caller reaches an engine read through a loop of its own, and twelve
    `asyncio.run(` call sites in this package still do exactly that (counted 2026-09-17: eight in
    `cli.py`, one in `product/release.py`, three worker entry points). A client made on a loop that
    has since closed and handed to the next `asyncio.run` is a broken read in a path that works
    today — a regression traded for a panel fix.

    THE EXAMPLE THIS CASE WAS WRITTEN FOR HAS MOVED, and the property has not. `techlead/
    conversation.py::gather_jobs` was the named `asyncio.run` per question until #147, which is
    also what made it hold one engine client per question; it now submits to `view.read_sync`'s one
    read loop (`tests/test_the_worker_holds_one_engine_client.py`). The rule this case holds is the
    pool's, not that caller's: `cli.py` still opens a loop per command.

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


# ── 10-11. a failure is SHARED with the callers queued behind it ────────────────────────────────

async def test_callers_QUEUED_behind_a_failing_connect_SHARE_its_failure(engine, monkeypatch):
    """The lock gave single flight on success and NOT on failure, and that made an outage a queue.

    A caller that queued behind a failing attempt took the lock, found `entry.client is None` and
    connected again — so N concurrent callers made N attempts, one after another. Measured by the
    reviewer of #145 on 2026-09-15, six concurrent `view.connect()` calls against a
    `connection.connect` that takes 0.5 s to refuse:

        da669de (no pool): 0.5, 0.5, 0.5, 0.5, 0.5, 0.5 s
        the lock alone:    0.5, 1.0, 1.5, 2.0, 2.5, 3.0 s

    A connect to an unreachable address was still hanging after 40 s when the probe measuring it
    gave up — that 40 s was the probe's own `asyncio.wait_for`, not a bound the SDK declares — and
    no read-side caller puts a timeout around `connect()`, so during an outage the floor re-read on
    every engine frame, `/api/inbox`, `/api/decisions` and the stream all queue on one lock and
    arrive faster than it drains.

    THIS CASE MEASURES BOTH NUMBERS, because either alone can pass over the defect: the attempt
    COUNT alone is satisfied by a pool that caches the failure for ever (case 12's property), and
    the ELAPSED time alone is satisfied by a fake that refuses instantly. The refusal here is
    0.2 s, the reviewer's probe value — six stacked would be 1.2 s.
    """
    refusal, calls = 0.2, []

    async def refuse():
        calls.append(1)
        await asyncio.sleep(refusal)
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)

    async def one():
        with pytest.raises(RuntimeError, match="the engine did not answer"):
            await tv.connect()

    started = asyncio.get_running_loop().time()
    await asyncio.gather(*(one() for _ in range(6)))
    elapsed = asyncio.get_running_loop().time() - started

    assert (len(calls), round(elapsed, 1)) == (1, refusal), (
        f"six concurrent callers made {len(calls)} attempts in {elapsed:.1f}s — one refusal is "
        f"{refusal}s, six stacked is {6 * refusal}s; a failure that is not shared turns an engine "
        f"outage into a queue every read-side request joins")


async def test_a_caller_arriving_AFTER_a_failed_attempt_tries_again(engine, monkeypatch):
    """The other half, and without it the fix above would be a cached failure wearing a new name: a
    caller that was not present for the failed attempt has no reason to inherit it, which is what
    lets a recovered engine be picked up without restarting the panel."""
    calls = []

    async def refuse():
        calls.append(1)
        await asyncio.sleep(0)
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)

    with pytest.raises(RuntimeError, match="the engine did not answer"):
        await tv.connect()
    with pytest.raises(RuntimeError, match="the engine did not answer"):
        await tv.connect()

    assert len(calls) == 2, (
        f"a caller arriving after the outage inherited an earlier failure ({len(calls)} attempts "
        f"for two sequential calls) — the engine is asked again, or a blip outlives itself")

    monkeypatch.setattr(connection, "connect", engine)
    got = await tv.connect()

    assert isinstance(got, _Sentinel), (
        f"the engine came back and the pool still answered {got!r} — a shared failure must not "
        f"outlive the attempt that produced it")


# ── 11b. …and the failure it retained is let go once the engine answers ─────────────────────────

async def test_the_retained_failure_is_RELEASED_once_the_engine_ANSWERS(engine, monkeypatch):
    """The pool keeps the last failure so it can be shared; once a client exists nothing can read
    it again, because the sharing branch is reachable only while `client is None`.

    MEASURED BY #145's REVIEWER, 2026-09-15: one failed connect followed by a successful one left
    the entry holding the exception and its 3 traceback frames for the life of the process. One
    object, so never a leak — which is why this rides here rather than in
    `test_no_unbounded_growth.py`: it is an exception nothing will read, held with its frames,
    and the line that drops it costs nothing.
    """
    async def refuse():
        await asyncio.sleep(0)
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)
    with pytest.raises(RuntimeError):
        await tv.connect()

    entry = next(iter(tv._CLIENTS.values()))
    assert entry.error is not None, "the failure was not retained, so it cannot have been shared"

    monkeypatch.setattr(connection, "connect", engine)
    got = await tv.connect()

    assert isinstance(got, _Sentinel), f"the engine came back and the pool answered {got!r}"
    entry = next(iter(tv._CLIENTS.values()))
    assert entry.error is None, (
        f"the engine answered and the entry still holds {entry.error!r} with its traceback — "
        f"nothing can read it once a client exists, so it is held for the life of the process")


# ── 12. …and the one retained exception object does not grow a traceback ───────────────────────

async def test_the_SHARED_failure_does_not_grow_a_traceback(engine, monkeypatch):
    """The pool retains ONE exception object for the length of an outage, and every waiter it is
    re-raised to appends a frame to that object's traceback unless the traceback is cleared.

    Measured through this pool on 2026-09-15, counting `traceback.extract_tb` on the retained
    object after 1 / 10 / 1000 re-raises: a bare `raise entry.error` gives 5 / 23 / 2003 frames and
    keeps going; `raise entry.error.with_traceback(None)` gives 2 / 2 / 2, message unchanged. This
    repository has a `tests/test_no_unbounded_growth.py` for exactly this shape — a module-level
    object that grows with traffic — and an outage is when the growth is fastest.

    IT RAISES THROUGH THE POOL rather than asserting about the source, which is the house rule: a
    guard that grepped `view.py` for `with_traceback` would be satisfied by this docstring.
    """
    async def refuse():
        await asyncio.sleep(0.02)   # slow enough that everyone queues behind this ONE attempt
        raise RuntimeError("the engine did not answer")

    monkeypatch.setattr(connection, "connect", refuse)

    async def one():
        with pytest.raises(RuntimeError):
            await tv.connect()

    frames = []
    for waiters in (2, 40):
        tv.reset_clients()
        await asyncio.gather(*(one() for _ in range(waiters)))
        entry = next(iter(tv._CLIENTS.values()))
        assert entry.error is not None, "the pool kept no failure to share"
        frames.append(len(traceback.extract_tb(entry.error.__traceback__)))
        assert str(entry.error) == "the engine did not answer", (
            f"clearing the traceback changed the message: {str(entry.error)!r}")

    assert frames[0] == frames[1], (
        f"the retained failure's traceback grew from {frames[0]} to {frames[1]} frames between 2 "
        f"and 40 waiters — one object, re-raised once per queued caller, growing for as long as "
        f"the engine is down")


# ── 13. a cert rewritten IN PLACE is picked up ─────────────────────────────────────────────────

async def test_a_cert_REWRITTEN_IN_PLACE_is_picked_up(monkeypatch, tmp_path):
    """`fingerprint()` digests the TLS files' CONTENTS, not their paths, and this is why.

    Before the pool the panel connected on every request, so `_auth()` re-read both files every
    time; reuse silently dropped that re-read, and a deployment whose cert is rewritten at an
    unchanged path kept the old cert until the process restarted. The reviewer of #145 measured it
    on 2026-09-15 by rewriting the file at `TEMPORAL_TLS_CERT` between two `view.connect()` calls,
    with `Client.connect` faked to record the bytes it was handed:

        da669de:      first b'CERT-BEFORE' | second b'CERT-ROTATED-IN-PLACE'
        on paths:     first b'CERT-BEFORE' | second b'CERT-BEFORE'

    DRIVEN THROUGH THE REAL `connection.connect`, not the counting fake, because the bytes this
    asserts on are ones `_auth()` reads — the fake would never touch the files. `Client.connect` is
    the seam `tests/conftest.py::_no_live_durable_engine` already holds, so faking it here is
    replacing a refusal with a recorder, not opening a door.
    """
    from temporalio.client import Client

    cert, key = tmp_path / "client.pem", tmp_path / "client.key"
    cert.write_bytes(b"CERT-BEFORE")
    key.write_bytes(b"KEY")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    monkeypatch.setenv("TEMPORAL_TLS_CERT", str(cert))
    monkeypatch.setenv("TEMPORAL_TLS_KEY", str(key))
    tv.reset_clients()

    handed = []

    async def record(*_args, **kwargs):
        await asyncio.sleep(0)
        handed.append(getattr(kwargs.get("tls"), "client_cert", None))
        return _Sentinel(len(handed))

    monkeypatch.setattr(Client, "connect", record)

    await tv.connect()
    cert.write_bytes(b"CERT-ROTATED-IN-PLACE")     # same path, new bytes
    await tv.connect()

    assert handed == [b"CERT-BEFORE", b"CERT-ROTATED-IN-PLACE"], (
        f"the cert was rotated in place and the pool handed the engine {handed!r} — a client "
        f"holding a superseded client certificate until somebody restarts the panel")


async def test_an_UNREADABLE_tls_file_does_not_raise_out_of_the_key(engine, monkeypatch, tmp_path):
    """The honest sentence about a missing cert belongs to `_auth()`, inside the connect attempt
    where a caller is already degrading — not to a key computation that has nothing to say."""
    monkeypatch.setenv("TEMPORAL_TLS_CERT", str(tmp_path / "there-is-no-such-file.pem"))
    monkeypatch.setenv("TEMPORAL_TLS_KEY", str(tmp_path / "nor-this-one.key"))

    address, namespace, digest = connection.fingerprint()   # must not raise

    assert (address, namespace) == ("engine.example:7233", "default")
    assert digest, "an unreadable TLS file left the key without an auth digest"


# ── 14. the pool holds ONE entry, whichever way the target changes ─────────────────────────────

async def test_the_pool_holds_ONE_entry_when_the_target_MOVES(engine, monkeypatch, tmp_path):
    """`fingerprint()` reads process-wide environment, so a process has exactly one engine target
    at a time — and a target that CHANGES yields a different key. Keeping the old entry beside the
    new one retains its client for the life of the process, which is #134's leak again on a
    deployment's clock. Case 6 above only covers a re-keyed entry under the SAME key (a closed
    loop); these are the three ways the KEY itself changes, and the cert one is the path the
    contents digest opens.
    """
    cert, key = tmp_path / "client.pem", tmp_path / "client.key"
    cert.write_bytes(b"CERT-BEFORE")
    key.write_bytes(b"KEY")

    await tv.connect()
    monkeypatch.setenv("TEMPORAL_ADDRESS", "moved.example:7233")          # the address moved
    await tv.connect()
    monkeypatch.setenv("TEMPORAL_API_KEY", "key-after-the-rotation")      # the credential rotated
    await tv.connect()
    monkeypatch.delenv("TEMPORAL_API_KEY")
    monkeypatch.setenv("TEMPORAL_TLS_CERT", str(cert))
    monkeypatch.setenv("TEMPORAL_TLS_KEY", str(key))
    await tv.connect()
    cert.write_bytes(b"CERT-ROTATED-IN-PLACE")                            # rewritten in place
    await tv.connect()

    assert engine.calls == 5, (
        f"five distinct engine targets opened {engine.calls} clients — each of these is a "
        f"deployment the panel must not keep reading through the previous client")
    assert len(tv._CLIENTS) == 1, (
        f"the target changed four times and the pool holds {len(tv._CLIENTS)} entries: "
        f"{tv._CLIENTS!r} — every stale entry is a retained gRPC client, which is issue #134 "
        f"arriving through the key instead of through the request")

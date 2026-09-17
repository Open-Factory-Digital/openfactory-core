"""#159: a read the panel is waiting on is bounded, and an engine that went silent is remembered.

MEASURED ON THE REAL STACK — `main` at `98dc177`, so with the pooled client of #145 — by killing
the engine under a running panel with a tab's stream attached:

    route                     engine up      engine gone
    /api/board/{project}      4-17 ms        8 ms
    /api/floor                9-15 ms        38.8 s
    /api/inbox                1-2 ms         8.9 s, then 500
    /api/temporal/jobs        7 ms           6.3 s

The client retries an unreachable engine before anything gives up (`gRPC call describe_schedule
retried 7 times`). The board's own route stays fast and the BOARD still crawls: a tab gets six
connections to a host, the page asks for the floor on every engine frame and holds the stream open,
so those six fill with requests waiting on retries and the board's reads queue behind them.

So every read this module serves is bounded, an engine that ran out of time is not asked again for
a moment, and the writes are left alone — a cancelled write is a request whose outcome nobody knows.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from openfactory.runtime.temporal import view as tv


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    """A deadline a test can wait for, and the memory it leaves behind."""
    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", "0.3")
    monkeypatch.setenv("OPENFACTORY_ENGINE_UNREACHABLE_FOR", "0.5")
    tv.reset_clients()
    yield
    tv.reset_clients()


class _Never:
    """A page of workflows that never arrives — `list_jobs` reads this with `async for`."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(self.seconds)
        raise StopAsyncIteration


class _Silent:
    """An engine that accepts the call and never answers — an unreachable address, not a refusal."""

    def __init__(self, *, seconds: float = 30.0) -> None:
        self.calls = 0
        self.seconds = seconds

    def list_workflows(self, *_a, **_kw):
        self.calls += 1
        return _Never(self.seconds)

    def __getattr__(self, _name):
        async def silent(*_a, **_kw):
            self.calls += 1
            await asyncio.sleep(self.seconds)
        return silent


async def _elapsed(coro) -> tuple[float, Exception | None]:
    started = time.monotonic()
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 — the test asserts on the type
        return time.monotonic() - started, exc
    return time.monotonic() - started, None


@pytest.mark.asyncio
async def test_a_read_the_panel_waits_for_is_bounded():
    took, error = await _elapsed(tv.list_jobs(_Silent(), "default"))

    assert isinstance(error, tv.EngineUnreachable), error
    assert "did not answer" in str(error)
    assert took < 2.0, f"the read waited {took:.1f}s on an engine that never answered"


@pytest.mark.asyncio
async def test_the_next_read_does_not_wait_for_a_silent_engine_again():
    engine = _Silent()
    await _elapsed(tv.list_jobs(engine, "default"))

    took, error = await _elapsed(tv.list_jobs(engine, "default"))

    assert isinstance(error, tv.EngineUnreachable), error
    assert took < 0.1, f"it waited {took:.2f}s again"
    assert engine.calls == 1, "the engine was asked again inside the window"
    assert tv.unreachable_for() > 0


@pytest.mark.asyncio
async def test_an_engine_that_comes_back_is_picked_up_without_a_restart():
    engine = _Silent()
    await _elapsed(tv.list_jobs(engine, "default"))
    await asyncio.sleep(0.6)   # the window this test configured

    took, error = await _elapsed(tv.list_jobs(engine, "default"))

    assert isinstance(error, tv.EngineUnreachable), error
    assert engine.calls == 2, "it never asked the engine again"
    assert took >= 0.25, "it did not actually wait for the engine's answer"


@pytest.mark.asyncio
async def test_the_memory_is_a_WINDOW_and_nothing_else_reopens_it(monkeypatch):
    """The window is the whole mechanism: while it is open no read runs, so by the time one
    answers the window has already passed. Clearing it on a successful read would be dead code —
    the mutation that removed such a line survived, which is how this was found."""

    async def jobs(_client, _namespace, **_kw):
        return [{"project": "p"}]

    engine = _Silent()
    await _elapsed(tv.list_jobs(engine, "default"))
    assert tv.unreachable_for() > 0

    monkeypatch.setattr(tv, "list_jobs", tv._bounded_read("the job list")(jobs))
    took, error = await _elapsed(tv.list_jobs(object(), "default"))
    assert isinstance(error, tv.EngineUnreachable), "a read ran while the window was open"

    await asyncio.sleep(0.6)
    assert tv.unreachable_for() == 0
    assert await tv.list_jobs(object(), "default") == [{"project": "p"}]
    assert took < 0.1


@pytest.mark.asyncio
async def test_an_engine_that_REFUSES_at_once_is_not_remembered_as_silent():
    """A refusal is an answer. Only a read that ran out of time is remembered, or a panel would go
    quiet for a window every time the engine said no."""

    class Refusing:
        def list_workflows(self, *_a, **_kw):
            raise RuntimeError("tcp connect error")

    took, error = await _elapsed(tv.list_jobs(Refusing(), "default"))

    assert isinstance(error, RuntimeError) and not isinstance(error, tv.EngineUnreachable)
    assert took < 0.2
    assert tv.unreachable_for() == 0


@pytest.mark.asyncio
async def test_a_connect_that_hangs_is_bounded_too(monkeypatch):
    """The pool's own docstring records a connect to an unreachable address "STILL HANGING AFTER
    40 s", with no caller bounding it."""

    async def never(*_a, **_kw):
        await asyncio.sleep(30)

    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "default")
    monkeypatch.setattr("openfactory.runtime.temporal.connection.connect", never)

    took, error = await _elapsed(tv.connect())

    assert isinstance(error, tv.EngineUnreachable), error
    assert took < 2.0, f"the connect waited {took:.1f}s"


@pytest.mark.asyncio
async def test_a_WRITE_is_never_cancelled_by_the_deadline():
    """"It did not answer in three seconds" must not be the reason a job is started twice."""

    class Slow:
        def __init__(self):
            self.started = 0

        async def start_workflow(self, *_a, **_kw):
            self.started += 1
            await asyncio.sleep(0.6)   # twice this test's deadline

            class _Handle:
                id = "job-1"
            return _Handle()

    from openfactory.runtime.temporal.io import JobParams

    engine = Slow()
    took, error = await _elapsed(tv.start_job(engine, JobParams(project="p", issue="1")))

    assert error is None, error
    assert engine.started == 1 and took >= 0.5, "the write was cut short by the read deadline"


@pytest.mark.asyncio
async def test_the_deadline_and_the_window_are_the_deployments_to_set(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", "7.5")
    monkeypatch.setenv("OPENFACTORY_ENGINE_UNREACHABLE_FOR", "9")
    assert (tv.read_deadline(), tv.unreachable_window()) == (7.5, 9.0)

    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", "not a number")
    monkeypatch.setenv("OPENFACTORY_ENGINE_UNREACHABLE_FOR", "0")
    assert (tv.read_deadline(), tv.unreachable_window()) == (3.0, 3.0)

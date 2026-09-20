"""The worker waits, at its birth, for the engine to be LISTENING — bounded, and said (#135).

WHAT HAPPENED. `openfactory up` starts the engine, the worker and the panel together. On some
restarts — likelier after a SIGKILL, when the engine's local database recovers before it binds —
the worker dialled before anything was listening, `Client.connect` raised, the worker exited, and
because one dying process ends the set the panel went down with it. Same command, nothing changed
between runs: a race.

WHERE THE WAIT BELONGS. The worker is the process with the dependency, and the engine's client
already rides out an engine that goes away WHILE the worker runs; the one outage it did not
survive was the one at its own first connect. Every starter has that race — `up`, a worker
started by hand beside `temporal server start-dev`, and compose whenever the engine container
restarts (`depends_on` orders the first start only) — so a wait in `up` would have fixed one of
three.

NOTHING LISTENING vs SOMETHING SAID NO. The client raises an untyped `RuntimeError` for a refused
connection, so telling the two apart by its message would be parsing a string another project
owns. The SOCKET is asked instead: wait, bounded, until the declared address accepts a
connection; then connect exactly ONCE and let whatever that raises — a bad key, a namespace that
does not exist — raise as it always did. A refusal that is an answer is never retried, by
construction: connect is never retried at all.

THE SOCKETS AND THE CLOCK HERE ARE REAL. A listener that starts after N seconds is a socket bound
after N seconds; only the engine's client is stood in for, because no engine runs in a test.
"""

from __future__ import annotations

import ast
import asyncio
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("temporalio")

from openfactory.runtime.temporal import connection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _ListensAfter:
    """A real listener on `port` that starts `delay` seconds from now."""

    def __init__(self, port: int, delay: float):
        self.port, self.delay, self.at = port, delay, 0.0
        self._sock: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        time.sleep(self.delay)
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", self.port))
        sock.listen(8)
        self.at = time.monotonic()
        self._sock = sock

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._thread.join(timeout=self.delay + 2)
        if self._sock is not None:
            self._sock.close()


@pytest.fixture
def dialled(monkeypatch):
    """Every call to the engine client's `connect`, with when it happened."""
    calls: list[float] = []

    async def connect(*_args, **_kwargs):
        calls.append(time.monotonic())
        return "the client"

    monkeypatch.setattr(connection.Client, "connect", connect)
    for var in ("TEMPORAL_ADDRESS", "TEMPORAL_ENDPOINT", "TEMPORAL_API_KEY",
                "TEMPORAL_TLS_CERT", "TEMPORAL_TLS_KEY"):
        monkeypatch.delenv(var, raising=False)
    return calls


def test_a_listener_that_starts_LATE_is_waited_for_and_dialled_once(dialled, monkeypatch):
    port = _a_free_port()
    monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{port}")

    with _ListensAfter(port, delay=1.2) as engine:
        client = asyncio.run(connection.connect_at_birth(within=10.0))

    assert client == "the client"
    assert len(dialled) == 1, f"the engine was dialled {len(dialled)} times"
    assert dialled[0] >= engine.at, (
        "the client dialled before anything was listening — the race #135 reported")


def test_an_engine_already_listening_costs_no_wait(dialled, monkeypatch):
    port = _a_free_port()
    monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{port}")

    with _ListensAfter(port, delay=0.0) as engine:
        while not engine.at:
            time.sleep(0.01)
        began = time.monotonic()
        asyncio.run(connection.connect_at_birth(within=10.0))

    assert time.monotonic() - began < 0.5 and len(dialled) == 1


def test_an_engine_that_NEVER_listens_is_a_bounded_wait_and_a_sentence(dialled, monkeypatch):
    port = _a_free_port()
    monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{port}")

    async def born():
        # A CASE ABOUT A BOUND MUST HAVE ONE OF ITS OWN. With the bound cut out of the code this
        # case waited for ever — it held the mutation runner for ten minutes on 2026-09-19 —
        # and a guard that hangs on the defect it names has not reported it.
        return await asyncio.wait_for(connection.connect_at_birth(within=1.0), timeout=8.0)

    began = time.monotonic()
    with pytest.raises(connection.EngineNotListening) as refused:
        asyncio.run(born())
    took = time.monotonic() - began

    assert 1.0 <= took < 3.0, f"a 1 s bound took {took:.1f}s"
    assert not dialled, "nothing was listening, so the client had nothing to dial"
    said = str(refused.value)
    for owed in (f"127.0.0.1:{port}", "1s", "TEMPORAL_ADDRESS", "OPENFACTORY_ENGINE_STARTS_IN",
                 "openfactory up"):
        assert owed in said, f"the refusal does not say {owed!r}: {said}"


def test_a_listener_that_says_NO_is_not_retried(monkeypatch, dialled):
    """A bad key or a missing namespace is an ANSWER. Waiting it out would turn a misconfiguration
    into thirty seconds of silence followed by the same error."""
    port = _a_free_port()
    monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{port}")
    attempts: list[float] = []

    async def refuses(*_args, **_kwargs):
        attempts.append(time.monotonic())
        raise RuntimeError("Request unauthorized")

    monkeypatch.setattr(connection.Client, "connect", refuses)

    with _ListensAfter(port, delay=0.0) as engine:
        while not engine.at:
            time.sleep(0.01)
        began = time.monotonic()
        with pytest.raises(RuntimeError, match="Request unauthorized"):
            asyncio.run(connection.connect_at_birth(within=10.0))

    assert len(attempts) == 1, f"a refusal that is an answer was retried {len(attempts)} times"
    assert time.monotonic() - began < 1.0


def test_an_engine_nobody_declared_is_refused_AT_ONCE_not_waited_for(dialled):
    """#163's rule stands: there is no address to wait on, and no local one is assumed."""
    began = time.monotonic()
    with pytest.raises(connection.EngineNotDeclared):
        asyncio.run(connection.connect_at_birth(within=10.0))

    assert time.monotonic() - began < 0.5 and not dialled


def test_the_bound_is_the_deployments_to_move(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_ENGINE_STARTS_IN", raising=False)
    assert connection.engine_starts_in() == 30.0
    monkeypatch.setenv("OPENFACTORY_ENGINE_STARTS_IN", "90")
    assert connection.engine_starts_in() == 90.0
    monkeypatch.setenv("OPENFACTORY_ENGINE_STARTS_IN", "soon")
    assert connection.engine_starts_in() == 30.0, "a bound that is not a number is not a bound"


def test_the_wait_ends_when_it_is_cancelled(dialled, monkeypatch):
    """`up` stops the set by signalling its children; a wait nothing can interrupt would hold the
    worker for the whole bound after the person pressed Ctrl-C (#160: the set ends together)."""
    port = _a_free_port()
    monkeypatch.setenv("TEMPORAL_ADDRESS", f"127.0.0.1:{port}")

    async def cancelled_after(seconds: float) -> float:
        began = time.monotonic()
        task = asyncio.ensure_future(connection.connect_at_birth(within=60.0))
        await asyncio.sleep(seconds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return time.monotonic() - began

    # FROM THE START, NOT FROM THE CANCEL: a wait that blocks the loop also blocks the coroutine
    # asking it to stop, so "how long did the cancel take" reads fast exactly when it is broken.
    assert asyncio.run(cancelled_after(0.6)) < 1.5


def test_the_worker_is_BORN_through_the_wait():
    """Read off the worker's own syntax tree: `main` awaits `connect_at_birth`, and nothing in it
    awaits the bare `connect` that dies on the first refusal."""
    tree = ast.parse((ROOT / "openfactory/runtime/temporal/worker.py").read_text())
    main = next(node for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "main")
    awaited = {node.value.func.id for node in ast.walk(main)
               if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
               and isinstance(node.value.func, ast.Name)}

    assert "connect_at_birth" in awaited, f"the worker's main awaits {sorted(awaited)}"
    assert "connect" not in awaited


def test_openfactory_worker_comes_through_the_same_door():
    """`openfactory worker` is the second entry point. It imported `main` and ran it bare, so the
    sentence existed for `-m` and the traceback survived for the command a person types."""
    tree = ast.parse((ROOT / "openfactory/cli.py").read_text())
    command = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "worker_cmd")
    imported = {alias.name for node in ast.walk(command) if isinstance(node, ast.ImportFrom)
                and node.module == "openfactory.runtime.temporal.worker" for alias in node.names}

    assert imported == {"born"}, f"`openfactory worker` runs {sorted(imported)}"


def test_a_worker_with_no_engine_to_reach_ends_in_a_SENTENCE_not_a_traceback(tmp_path):
    """What `up` sees: the real process, the real exit code, the real stderr."""
    port = _a_free_port()
    drive = ("import asyncio\n"
             "from openfactory.runtime.temporal.worker import born\n"
             "asyncio.run(born())\n")

    done = subprocess.run(
        [sys.executable, "-c", drive], cwd=ROOT, capture_output=True, text=True, timeout=25,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(ROOT),
             "TEMPORAL_ADDRESS": f"127.0.0.1:{port}", "OPENFACTORY_ENGINE_STARTS_IN": "1"})

    assert done.returncode == 1, done.stderr[-400:]
    assert "Traceback" not in done.stderr, done.stderr[-600:]
    assert f"127.0.0.1:{port}" in done.stderr and "OPENFACTORY_ENGINE_STARTS_IN" in done.stderr

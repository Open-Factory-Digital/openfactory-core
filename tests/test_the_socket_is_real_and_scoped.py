"""The live socket: dead everywhere, open to the wrong credential, and one loop per tab (#145).

Three defects on one transport, found while opening this API up so a customer can build their own
dashboard against it (#144). Each survived for a different reason, and the reasons are the
interesting part.

**IT WAS DEAD ON EVERY CONTAINERISED DEPLOYMENT.** No WebSocket protocol implementation was
declared anywhere — `websockets`, `wsproto` and `uvicorn[standard]` appear zero times in
`pyproject.toml`, the Dockerfile, compose or terraform. uvicorn resolves `ws="auto"` to
`unsupported` and answers the Upgrade with a 404. It worked in exactly one place: a developer's
venv, where `websockets` had arrived as somebody else's transitive dependency.

    AND NO TEST COULD HAVE CAUGHT IT. Starlette's `TestClient` speaks WebSocket in-process, over
    an ASGI call, importing no protocol library at all — so the entire suite was green while the
    deployed socket 404'd for everybody. A guard that connects via TestClient proves the handler;
    it cannot prove the server can carry it.

**IT CHECKED IDENTITY AND NOT SCOPE.** `_panel_gate` is `@app.middleware("http")`, and Starlette's
first line is `if scope["type"] != "http"` — a WebSocket bypasses it entirely, which the handler's
own docstring says. So the check was written by hand, and the hand-written one copied half: a
PRODUCT-scoped credential, refused with 403 on every HTTP read of the floor, was accepted here and
handed the project list and any project's conversation.

**IT RAN ONE READ LOOP PER TAB.** The docstring claimed "one backend poll feeds every connected
client"; `gen()` was defined inside the handler, so N tabs meant N registry and store reads every
two seconds. Invisible with one operator, untenable the moment a customer connects a dashboard —
which is precisely what this API is being opened for.
"""

from __future__ import annotations

import asyncio
import inspect
import tomllib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from openfactory.api import app as api

ROOT = Path(__file__).resolve().parent.parent


# ── 1. the server can actually carry a WebSocket ────────────────────────────────────────────────

def test_a_websocket_implementation_is_DECLARED():
    """Declared, so a fresh `pip install` of this package gets one. The panel image installs
    `.[runtime,slack]` and nothing in that closure pulled a protocol library."""
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    joined = " ".join(deps).lower()
    assert "websockets" in joined or "wsproto" in joined or "uvicorn[standard]" in joined, (
        f"no WebSocket implementation is declared, so uvicorn answers the Upgrade with a 404 on "
        f"every deployment that is not a developer's laptop: {deps}")


def test_uvicorn_can_RESOLVE_one_in_this_environment():
    """THE GUARD THAT WAS MISSING, and the only shape that could have caught this.

    Asserting the string is in `pyproject.toml` proves an intention. This asks uvicorn the same
    question it asks itself at startup — whether `ws="auto"` resolves to a real implementation or
    to `unsupported`, which is the code path that returns the 404."""
    import importlib

    from uvicorn.config import WS_PROTOCOLS

    # uvicorn resolves this string at startup and falls back to `unsupported` — the code path
    # that answers the Upgrade with a 404 — when the import fails. Asked the same way it asks.
    target = WS_PROTOCOLS["auto"]
    module, _, attr = target.partition(":")
    try:
        resolved = getattr(importlib.import_module(module), attr)
    except Exception as exc:  # noqa: BLE001 — this IS the failure being asserted against
        pytest.fail(f"uvicorn cannot load a WebSocket protocol here ({exc}) — `/api/stream` "
                    f"answers the Upgrade with a 404. It resolves from {sorted(WS_PROTOCOLS)}")
    assert resolved is not None
    assert "unsupported" not in resolved.__name__.lower(), (
        f"uvicorn resolved {resolved.__name__} — the no-implementation fallback, which 404s")


def test_the_PANEL_IMAGE_installs_it():
    """The dependency closure the container installs must reach the socket library.
    `docker/worker.Dockerfile` installs this tree's own package, and the panel service is built
    from that same Dockerfile — so what decides it is that `websockets` is a BASE dependency
    rather than an extra the image may or may not happen to name.

    ASKED OF THE IMAGE'S REAL INSTALL STEP, not of the words in the file. This line used to read
    `assert "pip install" in docker`, and on 2026-08-26 the install step became
    `sh docker/install-addons.sh '.[runtime]'`: the words went from present to absent while
    nothing about the closure moved, which is what a text match is worth here."""
    from test_the_public_cut_is_written_down import _install_step

    step = _install_step("docker/worker.Dockerfile")
    assert any(word.startswith(".") for word in step), (
        f"docker/worker.Dockerfile's install step does not install this tree's own package, so "
        f"the closure below is not what the panel image gets: {step}")
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert any("websockets" in d for d in deps), (
        "the socket library is in an EXTRA rather than the base dependencies — the panel image "
        "would only get it if that extra happens to be one of the two it installs")


# ── 2. the socket is scoped, not merely identified ──────────────────────────────────────────────

@pytest.fixture
def scoped(monkeypatch, tmp_path):
    """A deployment with one floor credential and one product credential."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "floor-secret")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKEN", "product-secret")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.delenv("OPENFACTORY_PRODUCT_TOKENS", raising=False)
    return TestClient(api.app)


def test_a_PRODUCT_credential_is_refused_the_floors_socket(scoped):
    """THE HOLE. It is 403'd on every HTTP read of the floor by the middleware in the same file,
    and was accepted here — then handed the project list and any project's conversation."""
    with pytest.raises(Exception):  # noqa: B017 — Starlette raises on a refused handshake
        with scoped.websocket_connect("/api/stream?token=product-secret"):
            pass


def test_the_SAME_credential_is_refused_over_HTTP_too(scoped):
    """The comparison that makes the point: the two transports must agree about one credential."""
    assert scoped.get("/api/projects", headers={"authorization": "Bearer product-secret"}
                      ).status_code == 403


def test_a_FLOOR_credential_still_opens_it(scoped):
    """The positive twin. A scope check that refused everybody would 'fix' this by removing the
    feature — and the panel would look exactly as broken as it did before."""
    with scoped.websocket_connect("/api/stream?token=floor-secret") as ws:
        assert ws.receive_json()["kind"] == "hello"


def test_the_scope_it_asks_for_is_the_one_the_HTTP_side_asks_for():
    """Asserted against `_scope_of_path`, so the two cannot drift: a route added under `/api/`
    defaults to FLOOR, and this socket serves the floor."""
    src = inspect.getsource(api.stream)
    assert "actions.FLOOR" in src and "_scopes_of" in src
    assert api._scope_of_path("/api/stream") == api.actions.FLOOR


# ── 3. one read, many subscribers ───────────────────────────────────────────────────────────────

def test_the_HANDLER_consumes_the_shared_reader_rather_than_reading_for_itself():
    """The half a test of `_Broadcast` cannot see. The fan-out can be perfect and still cost N
    reads if the socket handler keeps its own loop beside it — which is exactly what it had."""
    src = inspect.getsource(api.stream)
    assert "_broadcast.subscribe()" in src and "await queue.get()" in src, (
        "the socket reads for itself again — the shared reader is running beside it, unused")
    assert "_broadcast.unsubscribe(" in src, "a closed socket stays subscribed for ever"
    # EXACTLY ONCE — the opening frame, so a client that connects mid-conversation renders
    # immediately. A second occurrence is the per-tab loop returning.
    #
    # (Counted rather than sliced from `while True:`: the first one in this function belongs to
    # the inner `_resubscribe`, so the slice started in the wrong place and read the opening frame
    # as if it were the loop. A guard tripped by an inner function's loop.)
    assert src.count("_stream_snapshot") == 1, (
        f"the handler reads the snapshot {src.count('_stream_snapshot')} times — once is the "
        f"opening frame; more is the per-tab loop returning")


def test_the_shared_reader_is_started_ONCE_and_stopped_after_the_last_subscriber():
    """The lifecycle, because a fan-out that never stops is a process that never idles."""
    src = inspect.getsource(api._Broadcast)
    assert "asyncio.create_task" in src and "self._task.cancel()" in src


@pytest.mark.asyncio
async def test_TWO_SUBSCRIBERS_ON_ONE_PROJECT_cost_ONE_read(monkeypatch):
    """THE WHOLE POINT. Each open tab used to run its own loop: N tabs, N registry reads and N
    store reads every two seconds, for ever. This is what makes it safe for a customer to connect
    a dashboard of their own — the thing the API is being opened for."""
    reads: list[str] = []
    monkeypatch.setattr(api, "_stream_snapshot",
                        lambda project: (reads.append(project), {"projects": [project]})[1])
    monkeypatch.setattr(api, "_STREAM_TICK", 0.01)

    bus = api._Broadcast()
    a, b = bus.subscribe(), bus.subscribe()
    bus.wants("acme")
    try:
        assert (await asyncio.wait_for(a.get(), 2))[0] == "acme"
        assert (await asyncio.wait_for(b.get(), 2))[0] == "acme"
        # Two subscribers were served, and the snapshot was read once per TICK — not once per
        # subscriber per tick, which is what N loops meant.
        assert reads.count("acme") <= 2, (
            f"two subscribers cost {reads.count('acme')} reads of the same project")
    finally:
        bus.unsubscribe(a)
        bus.unsubscribe(b)


@pytest.mark.asyncio
async def test_a_STALLED_SUBSCRIBER_loses_frames_rather_than_memory(monkeypatch):
    """A queue that grows without bound is a process that dies for one slow socket. Frames are
    dropped instead, and the next full snapshot repairs the client — which is why every frame
    carries the whole section rather than a delta against something it may have missed."""
    monkeypatch.setattr(api, "_stream_snapshot", lambda project: {"projects": [project]})
    bus = api._Broadcast()
    q = bus.subscribe()
    try:
        for _ in range(500):
            bus._publish("acme", {"projects": ["x"]})
        assert q.qsize() <= 8, f"the queue grew to {q.qsize()} — it is unbounded"
    finally:
        bus.unsubscribe(q)


@pytest.mark.asyncio
async def test_ONE_BAD_TICK_does_not_end_the_fan_out_for_everybody(monkeypatch):
    """A reader that dies silently looks exactly like a factory with nothing to report."""
    calls = {"n": 0}

    def _flaky(project):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the registry blinked")
        return {"projects": [project]}

    monkeypatch.setattr(api, "_stream_snapshot", _flaky)
    monkeypatch.setattr(api, "_STREAM_TICK", 0.01)
    bus = api._Broadcast()
    q = bus.subscribe()
    bus.wants("acme")
    try:
        assert (await asyncio.wait_for(q.get(), 3))[0] == "acme", (
            "one failed tick ended the shared reader, and every subscriber went silent")
    finally:
        bus.unsubscribe(q)


def test_the_SNAPSHOT_is_read_off_the_event_loop():
    """`list_projects` and `channel_messages` are synchronous disk reads. On the loop they block
    every other connection on this process — which is worse now that there is one shared reader,
    because the one that blocks is the one everybody is waiting on."""
    # ON `_run` SPECIFICALLY. The first cut concatenated it with `stream`, whose opening-frame
    # read also uses `to_thread` — so the guard passed on that second occurrence while the SHARED
    # reader, the one everybody waits on, blocked the loop. Fifth time this repository has been
    # bitten by a substring that matched somewhere else.
    run = inspect.getsource(api._Broadcast._run)
    assert "to_thread(_stream_snapshot" in run, (
        "the shared reader does its disk reads on the event loop — and it is the one every "
        "subscriber is waiting on")
    first = inspect.getsource(api.stream)
    assert "to_thread(_stream_snapshot" in first, "the opening snapshot blocks the loop too"


# ── 4. somebody else's dashboard can reach it at all ────────────────────────────────────────────

def test_CORS_is_CLOSED_by_default():
    """A browser on another origin cannot read a single route unless a deployment says so — and
    "allow everything" would mean any page a logged-in operator visits can read their factory with
    the cookie already in their browser."""
    src = inspect.getsource(api)
    assert "OPENFACTORY_PANEL_ORIGINS" in src
    head = src[:src.index("@app.middleware")]
    assert "if _ORIGINS:" in head, "CORS is mounted unconditionally"


def test_a_BARE_OPTIONS_is_still_gated(scoped):
    """Only a preflight skips the gate, and a preflight is identified by the header a browser
    always sends with one. `OPTIONS` alone is an ordinary request and must be refused like any
    other — otherwise the exemption is a hole shaped like a method name."""
    # 401 SPECIFICALLY — the GATE's own answer. The first cut accepted 405 too, which is the
    # ROUTER saying "no OPTIONS handler here" AFTER the gate let the request through: the exact
    # state the mutation creates, read as a pass.
    assert scoped.options("/api/projects").status_code == 401, (
        "any OPTIONS request bypasses the credential check — the exemption is a hole shaped like "
        "a method name")


def test_CORS_opens_only_the_named_origins(monkeypatch):
    """Driven: a configured deployment answers the preflight for its own origin and not for
    another."""
    import importlib

    monkeypatch.setenv("OPENFACTORY_PANEL_ORIGINS", "https://ops.acme.com")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "s")
    mod = importlib.reload(api)
    try:
        client = TestClient(mod.app)
        allowed = client.options("/api/floor", headers={
            "origin": "https://ops.acme.com", "access-control-request-method": "GET"})
        assert allowed.headers.get("access-control-allow-origin") == "https://ops.acme.com"

        other = client.options("/api/floor", headers={
            "origin": "https://evil.example", "access-control-request-method": "GET"})
        assert other.headers.get("access-control-allow-origin") != "https://evil.example", (
            "an origin nobody named was allowed in")
    finally:
        monkeypatch.delenv("OPENFACTORY_PANEL_ORIGINS")
        importlib.reload(api)

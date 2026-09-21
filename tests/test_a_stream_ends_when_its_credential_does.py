"""A stream ends when the credential that opened it stops being good (#208).

WHAT HAPPENED. The panel gate (`_panel_gate`) runs when a request arrives, and an event stream's
request lasts as long as the tab. `/api/temporal/stream`, the per-job stream and the socket were
each authorized once, at the open, and then looped on "is the client still there" and nothing
else. So `/auth/logout` revoked a session in the store and the stream that session had opened
went on delivering every running job to a browser that was signed out; an expired session never
expired; a credential whose scope had narrowed kept receiving the floor.

DRIVEN, NOT READ. The server cases run the REAL app over ASGI — the real middleware admits the
stream, a real registered person signs in through the real `/auth/login`, the real `/auth/logout`
revokes — with a driver that reads the response a chunk at a time, because `TestClient` hands a
streaming body back only once it is complete and these never are. Nothing sleeps: the streams'
tick is a yield to the loop, the driver's one-chunk buffer holds the generator in step with the
reader, and the re-check's clock is moved by the case. EVERY WAIT IS BOUNDED, so a mutant that
never ends a stream fails a case instead of hanging the run.

The page cases execute `panel.html`'s own functions under node, on the base guard's harness
(`test_a_refusal_is_not_an_answer.py`); the event name they are fed is the one the server owns.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import json
import logging
import textwrap
import threading
import time as _time
import types
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.test_a_refusal_is_not_an_answer import ANA, REFUSED, _const, run

ROOT = Path(__file__).resolve().parent.parent
GOOD = "correct horse battery staple"

ENGINE = "/api/temporal/stream"
FEED = "/api/jobs/acme/7/stream"
#: Every route the dynamic cases drive. `test_every_stream_route_is_DRIVEN_here` holds this equal
#: to what `app.routes` says, so a third stream cannot arrive without a case of its own.
STREAMS = [ENGINE, FEED]

#: What a frame carries once the case has revoked the credential. The point of every case below:
#: this must never reach the reader.
LEAK = "AFTER-THE-CREDENTIAL-ENDED"

#: How many chunks a case reads while waiting for a stream to end. The driver holds the generator
#: at most three frames ahead of the reader, and the clock is moved ONCE, so the first frame made
#: after that is the one that asks; twelve is room, not a tuning.
REACH = 12


# ── the bench ───────────────────────────────────────────────────────────────────────────────────

class Stream:
    """One GET over ASGI, read a chunk at a time. The whole stack runs: CORS, the gate, the route.

    `send` blocks on a ONE-SLOT queue, so the generator is never more than a frame or two ahead
    of the reader — what makes "the clock moved, then a frame was made" a statement about order
    and not about timing."""

    END = object()

    def __init__(self, app, path: str, *, cookie: str = "", query: str = "") -> None:
        headers = [(b"host", b"panel.test")]
        if cookie:
            headers.append((b"cookie", f"openfactory_token={cookie}".encode()))
        self.scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                      "method": "GET", "scheme": "http", "path": path,
                      "raw_path": path.encode(), "query_string": query.encode(),
                      "root_path": "", "headers": headers, "client": ("127.0.0.1", 50208),
                      "server": ("panel.test", 80)}
        self._app = app
        self._chunks: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._hung_up = asyncio.Event()
        self._asked = False
        self.status = 0
        self.content_type = ""
        self._task: asyncio.Task | None = None

    async def _receive(self):
        if not self._asked:
            self._asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._hung_up.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.content_type = dict(message["headers"]).get(b"content-type", b"").decode()
            return
        if message.get("body"):
            await self._chunks.put(message["body"].decode())
        if not message.get("more_body"):
            await self._chunks.put(self.END)

    async def __aenter__(self) -> Stream:
        self._task = asyncio.create_task(self._app(self.scope, self._receive, self._send))
        return self

    async def __aexit__(self, *_exc) -> None:
        self._hung_up.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(self._task, 5)

    async def chunk(self):
        """The next chunk, or `END`. Five seconds is for ever here: nothing in a case sleeps."""
        return await asyncio.wait_for(self._chunks.get(), 5)

    async def read(self, n: int) -> list[str]:
        """Up to `n` chunks, stopping at the end of the response (`END` is kept as the last)."""
        got: list = []
        for _ in range(n):
            got.append(await self.chunk())
            if got[-1] is self.END:
                break
        return got


def ended_event(chunks) -> dict | None:
    """The typed goodbye among `chunks`, parsed the way EventSource would: by its `event:` line."""
    from openfactory.api import app as api

    name = getattr(api, "STREAM_ENDED_EVENT", "ended")
    for chunk in chunks:
        if isinstance(chunk, str) and chunk.startswith(f"event: {name}\n"):
            return json.loads(chunk.split("\ndata: ", 1)[1])
    return None


def said_after_the_end(chunks) -> list[str]:
    return [c for c in chunks if isinstance(c, str) and LEAK in c]


@pytest.fixture
def bench(monkeypatch, tmp_path):
    """A deployment with a REAL people store (the sqlite sink, in a file), one project, an engine
    that answers from a list the case controls, a tick that does not wait, and the re-check's
    clock in the case's hands."""
    from openfactory.api import app as api
    from openfactory.floor import reading
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "people.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    for name in ("OPENFACTORY_IDENTITY", "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS",
                 "OPENFACTORY_PRODUCT_TOKEN", "OPENFACTORY_PRODUCT_TOKENS",
                 "OPENFACTORY_PANEL_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({"projects": {"acme": {
        "name": "acme", "repo_path": "/work/acme", "enabled": True,
        "tracker": {"kind": "github", "repo": "acme/acme", "options": {"board_number": "1"}}}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))

    state = types.SimpleNamespace(jobs=[{"project": "acme", "issue": "7", "status": "running"}],
                                  clock=1000.0, asks=[], api=api, tmp=tmp_path)

    async def _connect(*_a, **_k):
        return object()

    async def _jobs(*_a, **_k):
        return list(state.jobs)

    async def _intake(_client=None):
        return {"known": True, "on": True, "note": "", "watchers": {}}

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "list_jobs", _jobs)
    monkeypatch.setattr(tv, "intake", _intake)
    monkeypatch.setattr(tv, "ui_base", lambda: "")
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    reading.forget_intake()

    real_sleep = asyncio.sleep

    async def _tick(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(api.asyncio, "sleep", _tick)

    async def _until(happened, what: str) -> None:
        """Wait — really, but for five seconds at most — for something another thread finishes."""
        for _ in range(500):
            if happened():
                return
            await real_sleep(0.01)
        raise AssertionError(f"five seconds passed and {what}")

    state.until = _until
    # `raising=False`: against a panel that predates the fix there is no clock to move, and the
    # case must then fail on what the stream DOES, not on a lookup.
    monkeypatch.setattr(api, "_stream_clock", lambda: state.clock, raising=False)

    real_verdict = getattr(api, "_gate_verdict", None)
    if real_verdict is not None:
        def _counted(path, credential):
            state.asks.append(path)
            return real_verdict(path, credential)
        monkeypatch.setattr(api, "_gate_verdict", _counted)

    def _journal(line: str) -> None:
        from openfactory.paths import events_file
        from openfactory.registry import ProjectRegistry

        path = events_file(ProjectRegistry().get("acme"), "7")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as out:
            out.write(json.dumps({"kind": "note", "message": line}) + "\n")

    state.journal = _journal
    _journal("the run began")

    def _leak_from_now_on() -> None:
        """Whatever either stream makes next carries `LEAK`."""
        state.jobs = [{"project": "acme", "issue": LEAK, "status": "running"}]
        _journal(LEAK)

    state.leak_from_now_on = _leak_from_now_on
    state.interval = getattr(api, "_STREAM_RECHECK_S", 10.0)
    return state


def register(ident: str = "ana@acme.example", *, groups=()) -> None:
    from openfactory.identity.people import PeopleStore

    store = PeopleStore()
    token, _ = store.invite(ident, display="Ana Lima", groups=tuple(groups), by="roberto")
    person = store.register(token=token, display="Ana Lima", password=GOOD)
    assert not isinstance(person, str), person


def sign_in(api, ident: str = "ana@acme.example") -> TestClient:
    """Through the real form: the session is whatever `/auth/login` minted and set as a cookie."""
    client = TestClient(api.app)
    client.post("/auth/login", data={"id": ident, "password": GOOD, "next": "/"},
                follow_redirects=False)
    assert client.cookies.get("openfactory_token"), "the form did not sign anybody in"
    return client


# ── 1. revoked: the defect ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", STREAMS)
async def test_a_stream_ENDS_after_the_session_that_opened_it_signs_out(bench, path):
    """THE DEFECT. Opened with a live session, which `/auth/logout` then revokes. Before: the
    stream went on for as long as the tab did, and the frame made after the sign-out — the floor,
    or the run's journal — was delivered to a browser nobody was signed in on."""
    register()
    browser = sign_in(bench.api)
    async with Stream(bench.api.app, path, cookie=browser.cookies["openfactory_token"]) as stream:
        first = await stream.read(2)
        assert stream.status == 200 and stream.content_type.startswith("text/event-stream")
        assert any("data: " in c for c in first), f"the stream said nothing at all: {first}"

        assert browser.get("/auth/logout").status_code == 200      # the REAL revocation
        bench.clock += bench.interval + 1
        bench.leak_from_now_on()
        rest = await stream.read(REACH)

    said = ended_event(rest)
    assert said is not None, (
        f"{path} was opened by a session that has since signed out, the re-check's interval has "
        f"passed, and it is still streaming — {len(rest)} more chunks, no goodbye: {rest[-2:]}")
    assert said["why"] == "signed_out" and said["status"] == 401
    assert rest[-1] is Stream.END, "it said goodbye and left the response open"
    assert not said_after_the_end(rest), (
        f"a frame made AFTER the sign-out reached the reader: {said_after_the_end(rest)}")
    assert said["login"] == "/auth/login", "the goodbye does not carry the gate's own 401 body"


@pytest.mark.parametrize("path", STREAMS)
async def test_a_session_that_is_STILL_GOOD_is_never_cut(bench, path):
    """THE TWIN, and the half a fix gets wrong by being eager. Five intervals pass; the gate is
    asked each time (counted — a twin that passes because nothing was ever asked proves
    nothing) and the stream is still delivering."""
    register()
    browser = sign_in(bench.api)
    async with Stream(bench.api.app, path, cookie=browser.cookies["openfactory_token"]) as stream:
        await stream.read(2)
        opened_with = len(bench.asks)
        for n in range(5):
            bench.clock += bench.interval + 1
            bench.jobs = [{"project": "acme", "issue": f"still-{n}", "status": "running"}]
            bench.journal(f"still-{n}")
            got = await stream.read(6)
            assert Stream.END not in got and ended_event(got) is None, (
                f"a good session was cut on re-check {n + 1}: {got}")
        assert any("still-4" in c for c in got), f"it stayed open and stopped delivering: {got}"
    assert len(bench.asks) - opened_with >= 5, (
        f"the gate was asked {len(bench.asks) - opened_with} time(s) in five intervals — this "
        f"case cannot tell a stream that is re-checked from one that never is")


async def test_it_is_NOT_asked_on_every_frame(bench):
    """The clock, and not the frame, is what asks: thirty frames inside one interval cost the
    store nothing beyond the open."""
    register()
    browser = sign_in(bench.api)
    async with Stream(bench.api.app, ENGINE, cookie=browser.cookies["openfactory_token"]) as s:
        await s.read(2)
        opened_with = len(bench.asks)
        bench.clock += bench.interval - 1
        await s.read(30)
    assert len(bench.asks) == opened_with, (
        f"{len(bench.asks) - opened_with} asks in thirty frames INSIDE the interval")


def test_the_interval_is_a_STATED_bound():
    """Tens of seconds at most. An hour here is the defect, configured."""
    from openfactory.api import app as api

    assert 2 < api._STREAM_RECHECK_S <= 30


# ── 2. expired, and no longer scoped ────────────────────────────────────────────────────────────

async def test_a_session_that_EXPIRES_ends_its_stream(bench, monkeypatch):
    """Nobody signs out: the session's own expiry passes. The people store's clock is moved — its
    own, not the process's — and the next re-check answers what the gate would."""
    from openfactory.identity import people

    register()
    browser = sign_in(bench.api)
    async with Stream(bench.api.app, ENGINE, cookie=browser.cookies["openfactory_token"]) as s:
        await s.read(2)
        late = types.SimpleNamespace(time=lambda: _time.time() + people.SESSION_TTL_SECONDS + 60)
        monkeypatch.setattr(people, "time", late)
        bench.clock += bench.interval + 1
        bench.leak_from_now_on()
        rest = await s.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "signed_out", f"an expired session still streams: {rest[-2:]}"
    assert rest[-1] is Stream.END and not said_after_the_end(rest)


class Directory:
    """An identity ADD-ON's row: a provider this file knows nothing about except the port. Who a
    credential is, and what they are scoped to, is looked up live — so it can CHANGE under an open
    stream, which no in-tree row's answer does without a restart."""

    def __init__(self) -> None:
        self.groups: dict[str, tuple[str, ...]] = {"ana-key": ()}
        self.broken = ""
        self.asked_on: list[str] = []

    def open_to_everyone(self) -> bool:
        return False

    def identify(self, *, credential: str, via: str = ""):
        from openfactory.identity.base import Subject

        self.asked_on.append(threading.current_thread().name)
        if self.broken:
            raise RuntimeError(self.broken.format(credential=credential))
        if credential not in self.groups:
            return None
        return Subject(id="ana", display="Ana", via="directory", groups=self.groups[credential])


@pytest.fixture
def directory(bench, monkeypatch):
    from openfactory.identity import registry

    row = Directory()
    monkeypatch.setitem(registry.IDENTITIES, "directory", lambda **_kw: row)
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "directory")
    return row


@pytest.mark.parametrize("path", STREAMS)
async def test_a_credential_that_became_PRODUCT_ONLY_loses_the_floors_stream(bench, directory,
                                                                             path):
    """Still somebody, no longer somebody who may read this path: the gate's 403, in the gate's
    own sentence — asked of a provider that is not the local one."""
    async with Stream(bench.api.app, path, cookie="ana-key") as stream:
        await stream.read(2)
        directory.groups["ana-key"] = ("product",)
        bench.clock += bench.interval + 1
        bench.leak_from_now_on()
        rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "not_allowed" and said["status"] == 403, rest[-2:]
    assert said["detail"] == REFUSED["body"]["detail"], (
        "the goodbye and the gate's 403 are two sentences — the page reads one of them")
    assert rest[-1] is Stream.END and not said_after_the_end(rest)


async def test_a_credential_the_provider_FORGETS_ends_its_stream(bench, directory):
    async with Stream(bench.api.app, ENGINE, cookie="ana-key") as stream:
        await stream.read(2)
        del directory.groups["ana-key"]
        bench.clock += bench.interval + 1
        rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "signed_out" and rest[-1] is Stream.END
    assert "login" not in said, "a provider with no login page is not given a door"


async def test_a_ROTATED_shared_token_ends_the_streams_it_opened(bench, monkeypatch):
    """The oldest credential this panel has: one shared token, presented as `?token=` because
    EventSource cannot set a header."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "the-old-token")
    async with Stream(bench.api.app, ENGINE, query="token=the-old-token") as stream:
        await stream.read(2)
        monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "the-new-token")
        bench.clock += bench.interval + 1
        rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "signed_out" and rest[-1] is Stream.END


async def test_a_person_DROPPED_from_the_token_map_loses_their_stream_and_nobody_else(
        bench, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "a-secret:ana:Ana,b-secret:bob:Bob")
    async with Stream(bench.api.app, ENGINE, cookie="a-secret") as ana, \
            Stream(bench.api.app, ENGINE, cookie="b-secret") as bob:
        await ana.read(2)
        await bob.read(2)
        monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "b-secret:bob:Bob")
        bench.clock += bench.interval + 1
        anas, bobs = await ana.read(REACH), await bob.read(6)
    assert ended_event(anas) and anas[-1] is Stream.END
    assert ended_event(bobs) is None and Stream.END not in bobs, f"Bob was cut with Ana: {bobs}"


async def test_an_OPEN_panel_is_never_cut(bench):
    """Nothing configured, nobody registered: the local-development posture. There is no
    credential to stop being good."""
    async with Stream(bench.api.app, ENGINE) as stream:
        await stream.read(2)
        for _ in range(3):
            bench.clock += bench.interval + 1
            got = await stream.read(6)
            assert ended_event(got) is None and Stream.END not in got, got


async def test_the_first_person_REGISTERED_closes_a_stream_that_was_opened_by_nobody(bench):
    """…and the door closing is seen too: the panel stops being open to everyone the moment
    somebody is registered, and a stream opened before that holds no credential at all."""
    async with Stream(bench.api.app, ENGINE) as stream:
        await stream.read(2)
        register()
        bench.clock += bench.interval + 1
        rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "signed_out" and said["login"] == "/auth/login"


async def test_the_store_is_NOT_read_on_the_event_loop(bench, directory):
    """`identify` is synchronous and, for a session, folds a store. On the loop it would stall
    every other stream and request for as long as the read takes, once per stream per interval."""
    async with Stream(bench.api.app, ENGINE, cookie="ana-key") as stream:
        await stream.read(2)
        directory.asked_on.clear()
        bench.clock += bench.interval + 1
        await stream.read(6)
    assert directory.asked_on, "the provider was never asked again"
    assert threading.current_thread().name not in directory.asked_on, (
        f"the re-check ran on the event loop's own thread: {directory.asked_on}")


# ── 3. a check that could not be made ───────────────────────────────────────────────────────────

async def test_a_check_that_RAISES_ends_the_stream_by_name_and_accuses_nobody(bench, directory,
                                                                              caplog):
    """Fail CLOSED, as the gate does for a request (a provider that raises is a 500, not a pass) —
    but `unavailable`, never `signed_out`: nobody was judged. And the provider's own sentence,
    which here quotes the credential, reaches the log without it."""
    async with Stream(bench.api.app, ENGINE, cookie="ana-key") as stream:
        await stream.read(2)
        directory.broken = "the directory refused token {credential}"
        bench.clock += bench.interval + 1
        bench.leak_from_now_on()
        with caplog.at_level(logging.INFO, logger="openfactory.panel"):
            rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "unavailable" and said["status"] == 503, rest[-2:]
    assert rest[-1] is Stream.END and not said_after_the_end(rest)
    assert "OPENFACTORY_STREAM_UNCHECKED" in caplog.text, "it ended in silence"
    assert "the directory refused token" in caplog.text, "the log does not say what went wrong"
    assert "ana-key" not in caplog.text + json.dumps(said), "the credential was written down"


async def test_a_provider_that_can_no_longer_be_BUILT_ends_the_stream_as_the_gate_would(
        bench, directory, monkeypatch):
    async with Stream(bench.api.app, ENGINE, cookie="ana-key") as stream:
        await stream.read(2)
        monkeypatch.setenv("OPENFACTORY_IDENTITY", "a-row-nobody-installed")
        bench.clock += bench.interval + 1
        rest = await stream.read(REACH)
    said = ended_event(rest)
    assert said and said["why"] == "unavailable" and said["status"] == 503
    assert said["detail"] == "identity provider unavailable", "not the gate's own 503"


async def test_neither_the_goodbye_nor_the_log_names_the_SESSION(bench, caplog):
    register()
    browser = sign_in(bench.api)
    session = browser.cookies["openfactory_token"]
    from openfactory.identity.people import digest

    with caplog.at_level(logging.DEBUG):
        async with Stream(bench.api.app, ENGINE, cookie=session) as stream:
            await stream.read(2)
            browser.get("/auth/logout")
            bench.clock += bench.interval + 1
            rest = await stream.read(REACH)
    assert ended_event(rest), rest[-2:]
    assert "OPENFACTORY_STREAM_ENDED" in caplog.text, "a stream ended and no log line says so"
    written = caplog.text + "".join(c for c in rest if isinstance(c, str))
    assert session not in written and digest(session) not in written


# ── 4. the gate is ONE function, and the middleware answers what it always did ──────────────────

def test_the_gate_and_the_stream_ask_the_SAME_function(bench, monkeypatch):
    """Two copies of an authorization rule is how they drift. The middleware's answer IS the
    verdict's, for each of the gate's three refusals and for a pass."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "op-secret:ana:Ana")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", "ba-secret:bia:Bia")
    api = bench.api
    client = TestClient(api.app)
    for path, credential in [("/api/floor", "op-secret"), ("/api/floor", "ba-secret"),
                             ("/api/floor", "nobody"), ("/api/whoami", "ba-secret"),
                             ("/api/product/acme", "ba-secret")]:
        verdict = api._gate_verdict(path, credential)
        answer = client.get(path, headers={"authorization": f"Bearer {credential}"})
        if verdict is None:
            assert answer.status_code not in (401, 403), (path, credential, answer.status_code)
        else:
            assert (answer.status_code, answer.json()) == (verdict.status, verdict.body)
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "a-row-nobody-installed")
    verdict = api._gate_verdict("/api/floor", "op-secret")
    answer = client.get("/api/floor", headers={"authorization": "Bearer op-secret"})
    assert (answer.status_code, answer.json()) == (verdict.status, verdict.body) == (
        503, {"detail": "identity provider unavailable"})
    assert api._gate_verdict("/p/acme", "") is None, "the HTML shell is gated now"


def test_a_request_presents_its_credential_in_the_order_it_always_did(bench, monkeypatch):
    """Header, then cookie, then `?token=` — and a header that is wrong is not rescued by a
    cookie that is right."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "h:hdr:H,c:cki:C,q:qry:Q")
    client = TestClient(bench.api.app)
    client.cookies.set("openfactory_token", "c")
    assert bench.api._credential_of(
        types.SimpleNamespace(headers={"authorization": "Bearer h"}, cookies={"openfactory_token": "c"},
                              query_params={"token": "q"})) == "h"
    assert bench.api._credential_of(
        types.SimpleNamespace(headers={}, cookies={"openfactory_token": "c"},
                              query_params={"token": "q"})) == "c"
    assert bench.api._credential_of(
        types.SimpleNamespace(headers={}, cookies={}, query_params={"token": "q"})) == "q"
    assert client.get("/api/whoami").status_code == 200, "the cookie is not read"
    assert client.get("/api/whoami", headers={"authorization": "Bearer nobody"}) \
        .status_code == 401, "a bad header fell through to the good cookie behind it"
    bare = TestClient(bench.api.app)
    assert bare.get("/api/whoami?token=q").status_code == 200, "`?token=` is not read"
    assert bare.get("/api/whoami").status_code == 401


# ── 5. a third stream cannot forget ─────────────────────────────────────────────────────────────

SEAM = "_event_stream"
_STREAMING = {"StreamingResponse", "EventSourceResponse"}


def _calls(tree: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            out.add(getattr(node.func, "id", None) or getattr(node.func, "attr", ""))
    return out


def _code_strings(tree: ast.AST) -> set[str]:
    """String constants that are CODE — docstrings are prose about a stream, not a stream."""
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)}
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}


def stream_routes(app) -> dict[str, ast.AST]:
    """Every HTTP route on `app` whose handler answers a stream, by ITS OWN CODE: it is annotated
    as returning one, builds one, goes through the seam, or names the media type. Parsed from the
    handler `app.routes` actually holds — a comment cannot satisfy it and cannot trip it."""
    found = {}
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or not getattr(route, "methods", None):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
        returns = ast.unparse(tree.body[0].returns) if tree.body[0].returns else ""
        if (_calls(tree) & (_STREAMING | {SEAM}) or "text/event-stream" in _code_strings(tree)
                or any(name in returns for name in _STREAMING)):
            found[route.path] = tree
    return found


def test_EVERY_route_that_answers_an_event_stream_goes_through_the_seam():
    from openfactory.api import app as api

    routes = stream_routes(api.app)
    assert {"/api/temporal/stream", "/api/jobs/{project}/{issue}/stream"} <= set(routes), (
        f"the enumeration lost the two streams this panel is known to have — it found {set(routes)}")
    for path, tree in routes.items():
        calls = _calls(tree)
        assert SEAM in calls and not calls & _STREAMING, (
            f"{path} answers a stream without `{SEAM}(request, frames)` — it is authorized once, "
            f"at the open, and never again (#208). Return `{SEAM}(request, gen())`.")
        seam_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                      and getattr(n.func, "id", "") == SEAM]
        assert all(getattr(c.args[0], "id", "") == "request" for c in seam_calls), (
            f"{path} hands the seam something other than its own request")


def test_NOTHING_in_the_panel_builds_a_streaming_response_but_the_seam():
    """The other door: a helper that builds the response for a route, which the route's own code
    would not show."""
    built = {}
    for module in sorted((ROOT / "openfactory/api").glob("*.py")):
        tree = ast.parse(module.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls(fn) & _STREAMING:
                inner = {n.name for n in ast.walk(fn) if n is not fn
                         and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and _calls(n) & _STREAMING}
                if not inner:
                    built[f"{module.name}::{fn.name}"] = True
    assert list(built) == [f"app.py::{SEAM}"], (
        f"a streaming response is built outside the seam: {sorted(built)}")


def test_every_stream_route_is_DRIVEN_here():
    """The enumeration above proves a stream goes through the seam; the cases at the top prove the
    seam ends it. A third stream gets both or the suite says which it lacks."""
    from openfactory.api import app as api

    templated = {"/api/jobs/{project}/{issue}/stream": FEED, "/api/temporal/stream": ENGINE}
    routes = set(stream_routes(api.app))
    assert routes == set(templated), (
        f"{sorted(routes - set(templated))} stream(s) have no case in this file — add each to "
        f"STREAMS and to this table")
    assert sorted(templated.values()) == sorted(STREAMS)


# ── 6. the socket ───────────────────────────────────────────────────────────────────────────────

class Socket:
    """The WebSocket the handler is handed, as far as it uses one. `TestClient`'s own would block
    a mutant for ever on `receive_json`; this one is awaited under a bound."""

    def __init__(self, token: str) -> None:
        self.query_params = {"token": token}
        self.cookies: dict = {}
        #: 2026-09-19: the handshake reads what `_credential_of` reads — header, cookie,
        #: `?token=` — so the stand-in has the header a real WebSocket has.
        self.headers: dict = {}
        self.url = types.SimpleNamespace(path="/api/stream")
        self.sent: list[dict] = []
        self.closed: tuple | None = None

    async def accept(self) -> None:
        return None

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        await asyncio.Event().wait()
        return ""

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


async def test_the_SOCKET_says_bye_and_closes_when_its_session_signs_out(bench, monkeypatch):
    register()
    browser = sign_in(bench.api)
    socket = Socket(browser.cookies["openfactory_token"])
    handler = asyncio.create_task(bench.api.stream(socket))
    await bench.until(lambda: len(socket.sent) >= 2, "the socket never sent its opening frames")
    assert [m["kind"] for m in socket.sent] == ["hello", "update"] and not handler.done()

    browser.get("/auth/logout")
    bench.clock += bench.interval + 1
    await asyncio.wait_for(handler, 5)

    bye = socket.sent[-1]
    assert bye["kind"] == "bye" and bye["ended"]["why"] == "signed_out", socket.sent
    assert socket.closed == (1008, "signed_out")


async def test_the_socket_of_a_GOOD_session_stays(bench):
    register()
    browser = sign_in(bench.api)
    socket = Socket(browser.cookies["openfactory_token"])
    handler = asyncio.create_task(bench.api.stream(socket))
    try:
        await bench.until(lambda: len(socket.sent) >= 2, "the socket never opened")
        for n in range(1, 4):
            before = len(bench.asks)
            bench.clock += bench.interval + 1
            await bench.until(lambda: len(bench.asks) > before,  # noqa: B023
                              f"the socket's credential was not asked about (interval {n})")
        assert not handler.done() and socket.closed is None, socket.sent
    finally:
        handler.cancel()


# ── 7. the page ─────────────────────────────────────────────────────────────────────────────────

def _event_name() -> str:
    from openfactory.api import app as api

    return api._panel_vocabulary().get("stream_ended")


#: An EventSource that records what the page does with it, and lets the case be the server.
PAGE_STUBS = """
const VOCAB={stream_ended:@event};
const sources=[];
class EventSource{constructor(u){this.url=u;this.closed=0;this.listeners={};this.onmessage=null;
    sources.push(this)}
  addEventListener(n,f){this.listeners[n]=f}
  close(){this.closed++}
  emit(n,d){const f=this.listeners[n];if(f)f({type:n,data:JSON.stringify(d||{})})}}
let es=null,engineES=null,focus=null,_ws=null;
const applied=[];function applyEngineFrame(f){applied.push(f)}function applyEngine(){}
const fed=[];function onEvent(e){fed.push(e)}
"""

PAGE = ("loadFloor", "streamEnded", "engineStream", "openFeed")
FLOOR_OK = {"status": 200, "body": {"word": "Armed", "line": "Armed — nothing is running"}}


def _filled(script: str, **named) -> str:
    """`@name` in a script becomes that value as JSON — the scripts are full of braces."""
    for name, value in named.items():
        script = script.replace(f"@{name}", json.dumps(value))
    return script


def page(scenario: str, **named) -> dict:
    """On the base guard's harness (which holds `_streamsEnded` and `reopenEndedStreams`, because
    an answered `loadFloor` reaches for them), plus the page's own constant — absent, like the
    functions, from a page that predates the fix."""
    stubs = "\n".join([_filled(PAGE_STUBS, event=_event_name()), _const("STREAM_ENDED")])
    return run(_filled(scenario, **named), *PAGE, stubs=stubs)


def test_the_page_LISTENS_for_the_name_the_server_sends():
    """The two ends joined: the name is the server's (`_panel_vocabulary`), and the page hears it
    as a NAMED event — `onmessage` never sees it, so it cannot be painted as a frame."""
    from openfactory.api import app as api

    assert _event_name() == api.STREAM_ENDED_EVENT
    out = page("""
      engineStream();openFeed("acme","7");
      return {heard:sources.map(s=>Object.keys(s.listeners))}""")
    assert out["heard"] == [[api.STREAM_ENDED_EVENT], [api.STREAM_ENDED_EVENT]]


def test_a_SIGNED_OUT_stream_is_closed_by_the_page_and_the_gate_is_asked_ONCE():
    """EventSource reconnects by itself on a close and cannot see a status. So the page closes it,
    and asks with a read that can: the 401 names the login, and `mfetch` goes there."""
    out = page("""
      routes={"/api/floor/acme":[{status:401,body:{detail:"unauthorized",login:"/auth/login"}}]};
      engineStream();const s=sources[0];
      s.emit(VOCAB.stream_ended,{why:"signed_out",status:401});await settle();
      return {closed:s.closed,opened:sources.length,went,calls,engineES,applied}""")
    assert out["closed"] == 1, "the source was left open: the browser reconnects it into a 401"
    assert out["opened"] == 1, "the page reopened a stream the server had just ended"
    assert out["calls"] == ["GET /api/floor/acme"]
    assert out["went"] == ["assign /auth/login?next=%2Fp%2Facme"]
    assert out["engineES"] is None and out["applied"] == [], "the goodbye was painted as a frame"


def test_a_REFUSED_stream_lands_on_the_headers_refused_state_and_asks_WHO():
    out = page("""
      routes={"/api/floor/acme":[@refused],"/api/whoami":[{status:200,body:@ana}]};
      engineStream();const s=sources[0];
      s.emit(VOCAB.stream_ended,{why:"not_allowed",status:403});await settle();
      return {closed:s.closed,opened:sources.length,calls,_floorRefused,who:me&&me.id}""",
               refused=REFUSED, ana=ANA)
    assert out["closed"] == 1 and out["opened"] == 1
    assert out["_floorRefused"] == REFUSED["body"]["detail"]
    assert "GET /api/whoami" in out["calls"] and out["who"] == "ana"


def test_a_stream_ended_over_a_BLIP_comes_back_once_the_floor_is_answered():
    """A good credential's stream is never lost for good: the floor read is ANSWERED, so the page
    opens it again — once, a new source, the old one closed."""
    out = page("""
      routes={"/api/floor/acme":[@floor]};
      engineStream();const s=sources[0];
      s.emit(VOCAB.stream_ended,{why:"unavailable",status:503});await settle();
      await loadFloor();await settle();   // …and an answer after that reopens nothing more
      return {closed:s.closed,urls:sources.map(x=>x.url),live:engineES===sources[1]}""",
               floor=FLOOR_OK)
    assert out["closed"] == 1
    assert out["urls"] == ["/api/temporal/stream", "/api/temporal/stream"] and out["live"]


def test_it_does_NOT_come_back_while_the_floor_is_refused_and_DOES_when_it_is_answered():
    out = page("""
      routes={"/api/floor/acme":[@refused,@floor],"/api/whoami":[{status:200,body:@ana}]};
      engineStream();
      sources[0].emit(VOCAB.stream_ended,{why:"not_allowed",status:403});await settle();
      const during=sources.length;
      await loadFloor();await settle();
      return {during,after:sources.length}""", refused=REFUSED, floor=FLOOR_OK, ana=ANA)
    assert out == {"during": 1, "after": 2}


def test_the_JOB_FEED_ends_the_same_way_and_returns_to_an_EMPTY_feed():
    """A new EventSource carries no Last-Event-ID: the journal replays from its first line, so the
    feed it returns to is emptied first — and only if that card is still the one on screen."""
    out = page("""
      routes={"/api/floor/acme":[@floor]};
      nodes["#feed"]=node();nodes["#feed"].innerHTML="<old lines>";
      openFeed("acme","7");
      sources[0].emit(VOCAB.stream_ended,{why:"unavailable",status:503});await settle();
      return {closed:sources[0].closed,urls:sources.map(x=>x.url),feed:nodes["#feed"].innerHTML}""",
               floor=FLOOR_OK)
    assert out["closed"] == 1 and out["urls"] == ["/api/jobs/acme/7/stream"] * 2
    assert out["feed"] == ""


def test_a_feed_nobody_is_looking_at_any_more_is_NOT_reopened():
    out = page("""
      routes={"/api/floor/acme":[@floor]};
      openFeed("acme","7");const s=sources[0];focus=null;
      s.emit(VOCAB.stream_ended,{why:"unavailable",status:503});await settle();
      return {opened:sources.length}""", floor=FLOOR_OK)
    assert out["opened"] == 1


def test_a_stream_that_errors_WITHOUT_the_event_is_still_the_browsers_to_reconnect():
    """A network drop is not a verdict. The page installs no `onerror` that closes the source, so
    the browser's own reconnect — today's behaviour — is untouched."""
    out = page("""
      engineStream();const s=sources[0];
      if(typeof s.onerror==="function")s.onerror({type:"error"});
      s.emit("error",{});await settle();
      return {closed:s.closed,calls,opened:sources.length}""")
    assert out == {"closed": 0, "calls": [], "opened": 1}


def test_a_FRAME_is_still_a_frame():
    out = page("""
      engineStream();
      sources[0].onmessage({data:JSON.stringify({connected:true,jobs:[]})});
      return {applied,closed:sources[0].closed}""")
    assert out == {"applied": [{"connected": True, "jobs": []}], "closed": 0}


# ── 8. the page's socket ────────────────────────────────────────────────────────────────────────

SOCKET_STUBS = """
const window={WebSocket:true};const sockets=[];
class WebSocket{constructor(u){this.url=u;this.closed=0;this.readyState=1;sockets.push(this)}
  close(){this.closed++}}
let _wsState="",_wsTries=0,_wsTimer=null,_chatProject="";
const timers=[];function setTimeout(f,ms){timers.push(ms);return timers.length}
function clearTimeout(){}
function streamStatus(state,detail){_wsState=state}
function viewOwner(){return "project"}function render(){}function paintChat(){}
"""


def socket_page(scenario: str, **named) -> dict:
    stubs = "\n".join([_filled(PAGE_STUBS, event=_event_name()), SOCKET_STUBS,
                       _const("STREAM_ENDED")])
    return run(_filled(scenario, **named), *PAGE, "streamConnect", stubs=stubs)


def test_a_socket_ENDED_over_its_credential_is_not_backed_off_into_a_refused_handshake():
    """`onclose` reconnects with a backoff, for ever. After a goodbye that carries `ended` the
    handshake would be refused every time, so the page lets go of the socket, asks the gate, and
    reconnects when the floor is answered."""
    out = socket_page("""
      routes={"/api/floor/acme":[@refused,@floor],"/api/whoami":[{status:200,body:@ana}]};
      streamConnect();const sock=sockets[0];
      sock.onmessage({data:JSON.stringify({kind:"bye",reason:"x",ended:{why:"not_allowed",status:403}})});
      sock.onclose();await settle();
      const during={timers:timers.length,sockets:sockets.length,closed:sock.closed,refused:_floorRefused};
      await loadFloor();await settle();
      return {during,after:sockets.length}""", refused=REFUSED, floor=FLOOR_OK, ana=ANA)
    assert out["during"] == {"timers": 0, "sockets": 1, "closed": 1,
                             "refused": REFUSED["body"]["detail"]}
    assert out["after"] == 2, "the socket never came back once the floor was answered"


def test_a_socket_that_merely_DROPPED_still_backs_off_and_reconnects():
    out = socket_page("""
      streamConnect();const sock=sockets[0];
      sock.onmessage({data:JSON.stringify({kind:"bye",reason:"the server is restarting"})});
      sock.onclose();await settle();
      return {timers,calls}""")
    assert out == {"timers": [2000], "calls": []}

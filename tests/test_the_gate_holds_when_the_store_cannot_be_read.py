"""The gate holds when the people store cannot be read.

THE RULE. "I cannot read who is registered" is never read as "nobody is registered". The second
is an ANSWER, and it is the one that keeps a new install open to its first operator
(`LocalIdentity.open_to_everyone`); the first is the absence of an answer, and a door that
gates on it stays CLOSED and says it cannot check — 503, by name, the posture the panel already
takes for an identity provider that cannot be built — until the store answers again, with nothing
restarted.

THE SEAM. `PeopleStore.snapshot` used to catch any failure to read and hand back an empty
snapshot, so every reader of the store met an outage as an empty store: the door's "is anybody
registered?", the session lookup, the login and registration forms, the shell's `people list`.
The store now raises `StoreUnreadable` and each reader decides for itself, which is what these
cases pin — one per reader, against the REAL app, a REAL sqlite sink on disk and a person who
REALLY registered through the form.

THE TWINS, because a guard that only ever sees a closed door cannot tell "holds" from "locked
everybody out": a store that answers and is empty is OPEN, a deployment that declared no store
(`null`) is OPEN, and a credential from the environment — which needs no store — still gets in
while the store is down.

MEASURED RED on `origin/main` @ 1512d0a: see the pull request.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient
from typer.testing import CliRunner

from openfactory.identity.people import PeopleStore
from openfactory.observability.query import StoreUnreadable
from openfactory.observability.sqlite_metrics import SqliteMetricsSink

GOOD = "correct horse battery staple"
ANA = "ana@acme.example"
UNAVAILABLE = "identity provider unavailable"

_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False


# ── a real deployment: local identity, people by invitation, a sqlite sink on disk ──────────────

@pytest.fixture
def deployment(tmp_path, monkeypatch) -> Path:
    """No token variable anywhere — the ONLY credentials this deployment has are the people it
    registered — and the store is a real file."""
    for name in ("OPENFACTORY_IDENTITY", "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS",
                 "OPENFACTORY_PRODUCT_TOKEN", "OPENFACTORY_PRODUCT_TOKENS",
                 "OPENFACTORY_METRICS_TABLE"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(home / "registry.yaml"))
    db = tmp_path / "store" / "metrics.db"
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(db))
    return db


def _client() -> TestClient:
    from openfactory.api.app import app

    return TestClient(app, follow_redirects=False)


def _register(client: TestClient, ident: str = ANA) -> str:
    """Invite and register through the real form. The session token the form handed back."""
    got = PeopleStore().invite(ident, display="Ana Lima", by="roberto")
    assert not isinstance(got, str), got
    token, _ = got
    landed = client.post("/auth/register", data={"invite": token, "display": "Ana Lima",
                                                 "password": GOOD, "again": GOOD})
    assert landed.status_code == 303, landed.text
    session = landed.cookies.get("openfactory_token") or client.cookies.get("openfactory_token")
    assert session, "the form registered nobody"
    client.cookies.clear()   # every case below states its credential; none rides on the jar
    return session


def _bearer(session: str) -> dict[str, str]:
    return {"authorization": f"Bearer {session}"}


# ── four ways a store stops answering, each one real, each one undone ───────────────────────────

class _Broken:
    """One way of making the store unreadable, and the way back."""

    def __init__(self, db: Path, monkeypatch) -> None:
        self.db, self.mp = db, monkeypatch
        self._undo = lambda: None

    def header(self) -> None:
        """The file's first bytes are no longer SQLite's."""
        for side in (self.db.with_name(self.db.name + "-wal"),
                     self.db.with_name(self.db.name + "-shm")):
            side.unlink(missing_ok=True)
        good = self.db.read_bytes()
        self.db.write_bytes(b"\x00not a database\x00" * 8 + good[128:])
        self._undo = lambda: self.db.write_bytes(good)

    def chmod(self) -> None:
        """The file is there and this process may not open it."""
        if _ROOT:
            pytest.skip("root reads a 000 file")
        self.db.chmod(0o000)
        self._undo = lambda: self.db.chmod(0o644)

    def sink(self) -> None:
        """The sink itself raises — a lock, a disk error, a remote store's outage — and NOT the
        typed exception: whatever a sink throws is one fact to the people store."""
        real = SqliteMetricsSink.records_of_kind

        def down(self, *a, **kw):
            raise RuntimeError("database is locked")

        self.mp.setattr(SqliteMetricsSink, "records_of_kind", down)
        self._undo = lambda: self.mp.setattr(SqliteMetricsSink, "records_of_kind", real)

    def unbuilt(self) -> None:
        """The deployment NAMES a sink this process cannot build: a typo, a row an image rebuild
        dropped. The people are still in the file; nothing can ask it."""
        self.mp.setenv("OPENFACTORY_METRICS_SINK", "sqlite-but-misspelled")
        self._undo = lambda: self.mp.setenv("OPENFACTORY_METRICS_SINK", "sqlite")

    def restore(self) -> None:
        self._undo()


WAYS = ("header", "chmod", "sink", "unbuilt")


@pytest.fixture(params=WAYS)
def broken(request, deployment, monkeypatch):
    """A deployment with one registered person, its store made unreadable one way. Yields
    `(client, session, breaker)`; the store is put back afterwards whatever the case did."""
    client = _client()
    session = _register(client)
    assert client.get("/api/projects").status_code == 401, "a registered person closes the door"
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 200
    breaker = _Broken(deployment, monkeypatch)
    getattr(breaker, request.param)()
    try:
        yield client, session, breaker
    finally:
        breaker.restore()


# ── the store says "unreadable", and does not remember it ───────────────────────────────────────

def test_the_store_raises_instead_of_answering_nobody(broken):
    _, _, breaker = broken
    for ask in (lambda s: s.has_people(), lambda s: s.people(), lambda s: s.pending(),
                lambda s: s.session_of("x"), lambda s: s.invitation_for("x"),
                lambda s: s.login(ANA, GOOD), lambda s: s.revoke("x"),
                lambda s: s.invite("bruno@acme.example", by="roberto")):
        with pytest.raises(StoreUnreadable):
            ask(PeopleStore())


def test_a_failed_read_is_not_remembered_so_the_next_read_is_the_recovery(broken):
    _, _, breaker = broken
    store = PeopleStore()
    with pytest.raises(StoreUnreadable):
        store.has_people()
    breaker.restore()
    assert store.has_people() is True, "the SAME store object must recover, with nothing rebuilt"


# ── the door: the middleware ────────────────────────────────────────────────────────────────────

def test_nobody_anonymous_is_let_in_and_the_answer_is_cannot_check(broken, caplog):
    client, _, _ = broken
    with caplog.at_level(logging.WARNING):
        got = client.get("/api/projects")
    assert got.status_code != 200, "an unreadable store opened the panel to everybody"
    assert got.status_code == 503 and got.json()["detail"].startswith(UNAVAILABLE), got.text
    assert "OPENFACTORY_PEOPLE_UNREADABLE" in caplog.text
    assert "OPENFACTORY_IDENTITY_UNAVAILABLE" in caplog.text


def test_the_refusal_does_not_carry_the_cause_to_a_caller_nobody_identified(broken, deployment):
    client, _, _ = broken
    body = client.get("/api/projects").text
    assert str(deployment) not in body and str(deployment.parent) not in body, body


def test_a_signed_in_person_is_told_cannot_check_and_not_unauthorized(broken):
    """401 would send them to sign in again against a store that cannot record it, and the page
    clears the session that works again the moment the store does."""
    client, session, _ = broken
    got = client.get("/api/projects", headers=_bearer(session))
    assert got.status_code == 503 and got.json()["detail"].startswith(UNAVAILABLE), got.text
    assert "login" not in got.json()


def test_every_read_under_the_gate_answers_the_same_way(broken):
    client, session, _ = broken
    for path in ("/api/whoami", "/api/projects", "/api/inbox", "/api/jobs/ghost/1/stream",
                 "/api/product/projects"):
        for headers in ({}, _bearer(session)):
            got = client.get(path, headers=headers)
            assert got.status_code == 503, (path, headers, got.status_code, got.text[:200])


def _through_the_gate(path: str, *, query: str = "", cookie: str = "") -> tuple[int, list[str]]:
    """One request through the REAL `_panel_gate`, with the route behind it replaced by a marker.

    For the routes that stream for ever once admitted (`/api/temporal/stream`): the test client
    waits for a generator that waits for a disconnect it never delivers, so an admitted request
    — which is exactly what a broken gate produces — would hang the case instead of failing it."""
    from openfactory.api import app as api

    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", f"openfactory_token={cookie}".encode()))
    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "headers": headers, "scheme": "http",
             "server": ("testserver", 80), "client": ("testclient", 50000), "root_path": "",
             "http_version": "1.1"}
    admitted: list[str] = []

    async def call_next(request):
        admitted.append(request.url.path)
        return PlainTextResponse("admitted")

    response = asyncio.run(api._panel_gate(Request(scope), call_next))
    return response.status_code, admitted


@pytest.mark.parametrize("path", ["/api/temporal/stream", "/api/jobs/acme/1/stream"])
def test_the_two_event_streams_are_behind_the_same_answer(broken, path):
    """EventSource cannot set a header, so these arrive with `?token=` or the cookie."""
    _, session, _ = broken
    for kw in ({}, {"query": f"token={session}"}, {"cookie": session}):
        status, admitted = _through_the_gate(path, **kw)
        assert (status, admitted) == (503, []), (path, kw, status, admitted)


# ── the door: `require_auth`, asked directly (the middleware answers first over HTTP) ───────────

def test_a_mutating_route_is_refused_the_same_way(broken):
    from fastapi import HTTPException

    from openfactory.api.app import require_auth

    client, session, _ = broken
    for authorization in ("", f"Bearer {session}"):
        with pytest.raises(HTTPException) as refused:
            require_auth(authorization=authorization)
        assert refused.value.status_code == 503, refused.value.detail
        assert str(refused.value.detail).startswith(UNAVAILABLE)
    got = client.post("/api/act/people_invite", json={"params": {"person": "x"}},
                      headers=_bearer(session))
    assert got.status_code == 503, got.text


# ── the door: the socket, which no HTTP middleware ever sees ────────────────────────────────────

def _socket_close_code(client: TestClient, url: str) -> int | None:
    """The close code the handshake was refused with; None when the socket was ACCEPTED."""
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect(url) as ws:
            ws.receive_text()   # `hello` — sent at once on an accepted socket, so this is bounded
            return None
    except WebSocketDisconnect as refused:
        return refused.code


def test_the_socket_is_refused_as_unavailable_not_as_a_bad_credential(broken):
    """1011, not 1008: the page stops retrying on a policy violation, and this credential works
    again the moment the store does."""
    client, session, _ = broken
    assert _socket_close_code(client, "/api/stream") == 1011
    assert _socket_close_code(client, f"/api/stream?token={session}") == 1011


# ── recovery, with nothing restarted ────────────────────────────────────────────────────────────

def test_the_panel_recovers_by_itself_when_the_store_answers_again(broken):
    client, session, breaker = broken
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 503
    breaker.restore()
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 200
    anonymous = client.get("/api/projects")
    assert anonymous.status_code == 401 and anonymous.json()["login"] == "/auth/login"
    assert _socket_close_code(client, "/api/stream") == 1008
    assert _socket_close_code(client, f"/api/stream?token={session}") is None


# ── the forms: refuse by name, change nothing ───────────────────────────────────────────────────

def test_the_login_form_says_unavailable_and_not_that_nobody_is_registered(broken):
    client, _, _ = broken
    page = client.get("/auth/login")
    assert page.status_code == 503 and "unavailable" in page.text, page.text
    assert "nobody is registered" not in page.text
    posted = client.post("/auth/login", data={"id": ANA, "password": GOOD, "next": "/"})
    assert posted.status_code == 503 and "unavailable" in posted.text, posted.text
    assert "not a registered person" not in posted.text
    assert "openfactory_token" not in posted.cookies


def test_a_redemption_is_refused_by_name_and_the_link_is_still_good_afterwards(
        deployment, monkeypatch):
    """Not parametrised over every way: the invitation has to be written while the store still
    answers, and the way back has to leave the link as it was."""
    client = _client()
    _register(client)
    token, _ = PeopleStore().invite("bruno@acme.example", display="Bruno", by="roberto")
    fields = {"invite": token, "display": "Bruno", "password": GOOD, "again": GOOD}
    breaker = _Broken(deployment, monkeypatch)
    breaker.sink()

    landing = client.get(f"/auth/register?invite={token}")
    assert landing.status_code == 503 and "unavailable" in landing.text, landing.text
    assert "not one this deployment issued" not in landing.text, "a good link was called a bad one"
    for form in (fields, {**fields, "again": "something else entirely"}):
        posted = client.post("/auth/register", data=form)
        assert posted.status_code == 503 and "unavailable" in posted.text, posted.text
        assert "openfactory_token" not in posted.cookies, "a session was minted it cannot record"

    breaker.restore()
    assert [p.id for p in PeopleStore().people()] == [ANA], "nothing was registered meanwhile"
    assert client.post("/auth/register", data=fields).status_code == 303
    assert sorted(p.id for p in PeopleStore().people()) == [ANA, "bruno@acme.example"]


def test_logout_still_signs_the_browser_out_and_says_what_it_could_not_do(broken, caplog):
    client, session, breaker = broken
    with caplog.at_level(logging.WARNING):
        out = client.get("/auth/logout", headers=_bearer(session))
    assert out.status_code == 200
    assert "OPENFACTORY_LOGOUT_NOT_REVOKED" in caplog.text
    breaker.restore()
    assert PeopleStore().session_of(session) is not None, "nothing was written blind"


# ── the shell and the action row ────────────────────────────────────────────────────────────────

def test_the_shell_says_unreadable_and_not_nobody_yet(broken):
    from openfactory.cli import app as cli

    listed = CliRunner().invoke(cli, ["people", "list"])
    assert listed.exit_code == 1, listed.output
    assert "cannot be read" in listed.output and "nobody is registered" not in listed.output

    invited = CliRunner().invoke(cli, ["people", "invite", ANA, "--by", "roberto"])
    assert invited.exit_code == 1, invited.output
    assert "cannot be read" in invited.output and "/auth/register" not in invited.output


def test_the_invite_row_is_unavailable_not_invalid(broken):
    from openfactory import actions

    outcome = asyncio.run(actions.perform(
        "people_invite", by=actions.Actor(id="roberto", display="roberto", via="cli", admin=True),
        person=ANA))
    assert not outcome.ok and outcome.code == actions.UNAVAILABLE, outcome
    assert "cannot be read" in outcome.message and not outcome.data.get("link")


# ── the provider's own answers ──────────────────────────────────────────────────────────────────

def test_the_local_row_closes_the_door_and_declares_why(broken):
    from openfactory.identity import build_identity

    _, session, _ = broken
    provider = build_identity()
    assert provider.unavailable() == "", "nothing was asked of the store yet"
    assert provider.open_to_everyone() is False
    assert provider.identify(credential=session, via="panel") is None
    assert provider.login_path == ""
    assert provider.unavailable(), "it answered without the store and did not say so"


def test_one_request_reads_a_store_that_is_down_once(deployment, monkeypatch):
    """A provider is one request. Its answers agree with each other, and a store that times out
    costs the request one timeout rather than one per question."""
    from openfactory.identity import build_identity

    _register(_client())
    reads: list[int] = []

    def down(self, *a, **kw):
        reads.append(1)
        raise RuntimeError("database is locked")

    monkeypatch.setattr(SqliteMetricsSink, "records_of_kind", down)
    provider = build_identity()
    provider.open_to_everyone()
    provider.identify(credential="some-session", via="panel")
    _ = provider.login_path
    assert len(reads) == 1, reads


def test_a_credential_that_needs_no_store_still_gets_in(broken, monkeypatch):
    """The operator's way in to see what is wrong. The environment map is read before the store,
    and an anonymous caller is still asked for a token rather than told the panel is down — a 503
    draws no prompt, and the prompt is how a token holder on a new browser gets in."""
    client, session, _ = broken
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "s3cret-r:roberto:Roberto")
    assert client.get("/api/projects", headers=_bearer("s3cret-r")).status_code == 200
    anonymous = client.get("/api/projects")
    assert anonymous.status_code == 401 and "login" not in anonymous.json(), anonymous.text
    # …and a session, which DOES need the store, is "cannot check" — not "unauthorized"
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 503

    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS")
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "the-shared-one")
    assert client.get("/api/projects", headers=_bearer("the-shared-one")).status_code == 200


def test_a_row_that_declares_nothing_keeps_the_answers_it_had(monkeypatch):
    """`unavailable` is asked by `getattr` and only a non-empty `str` is a declaration: a row
    that never heard of it, and a double that answers everything, are told 401 as before."""
    from unittest.mock import MagicMock

    from openfactory.api import app as api

    class Row:
        def identify(self, *, credential: str, via: str = ""):
            return None

    double = MagicMock()
    double.open_to_everyone.return_value = False
    double.identify.return_value = None
    for provider in (Row(), double):
        monkeypatch.setattr("openfactory.identity.build_identity", lambda p=provider: p)
        door = api._admission("anything")
        assert (door.open, door.subject, door.unavailable) == (False, None, ""), door

    class Declares(Row):
        def unavailable(self) -> str:
            return "the directory this row reads did not answer"

    monkeypatch.setattr("openfactory.identity.build_identity", lambda: Declares())
    assert api._admission("anything").unavailable.startswith(UNAVAILABLE)


# ── the other way of not seeing everybody: a window full of newer rows ──────────────────────────

def _fill_the_window(monkeypatch, *, beyond: int) -> tuple[TestClient, str]:
    """One registered person, then live sessions until the read's window holds `beyond` rows
    more than it keeps. `READ_LAST` is shrunk so the arithmetic is legible; measured at the real
    5000 on a sqlite sink the answer is the same (`has_people() is False` on main)."""
    from openfactory.identity import people

    monkeypatch.setattr(people, "READ_LAST", 40)
    client = _client()
    session = _register(client)          # three rows: invited, registered, session
    ana = PeopleStore().people()[0]
    for _ in range(people.READ_LAST - 3 + beyond):
        assert PeopleStore().open_session(ana)
    return client, session


def test_accounts_older_than_the_window_are_not_nobody(deployment, monkeypatch, caplog):
    """The read keeps the most recent rows and the accounts are the oldest. A fold that never saw
    them has not learned that nobody is registered."""
    client, session = _fill_the_window(monkeypatch, beyond=5)
    with caplog.at_level(logging.WARNING), pytest.raises(StoreUnreadable):
        PeopleStore().has_people()
    assert "OPENFACTORY_PEOPLE_WINDOW_FULL" in caplog.text
    assert client.get("/api/projects").status_code == 503
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 503
    assert _socket_close_code(client, "/api/stream") == 1011


def test_a_full_window_that_still_holds_an_account_is_an_ordinary_closed_door(
        deployment, monkeypatch):
    client, session = _fill_the_window(monkeypatch, beyond=0)
    assert PeopleStore().has_people() is True
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects", headers=_bearer(session)).status_code == 200


# ── the twins: what must STAY open ──────────────────────────────────────────────────────────────

def test_a_new_install_whose_store_answers_and_is_empty_is_open(deployment):
    client = _client()
    assert not deployment.exists(), "nothing has been written: this is the first read ever"
    assert client.get("/api/projects").status_code == 200
    assert client.get("/auth/login").status_code == 404, "no form before anybody is registered"
    assert _socket_close_code(client, "/api/stream") is None
    assert _through_the_gate("/api/temporal/stream") == (200, ["/api/temporal/stream"])


def test_an_open_invitation_does_not_close_a_new_install(deployment):
    assert not isinstance(PeopleStore().invite(ANA, by="roberto"), str)
    assert _client().get("/api/projects").status_code == 200


def test_a_deployment_that_declared_no_store_is_open(deployment, monkeypatch):
    """`null` keeps nothing, so nobody can be registered in it and nothing is unread: the
    local-development default, as designed."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")
    assert PeopleStore().has_people() is False
    assert _client().get("/api/projects").status_code == 200

    monkeypatch.delenv("OPENFACTORY_METRICS_SINK")
    assert PeopleStore().has_people() is False
    assert _client().get("/api/projects").status_code == 200


def test_a_sqlite_store_with_no_file_named_reads_the_file_it_writes(deployment, monkeypatch,
                                                                     tmp_path):
    """The writer defaulted the file's name and the reader did not, so this deployment could
    never be built for a read. Once an unbuildable sink closes the door that would have locked
    a new install out; the two now share one definition."""
    monkeypatch.delenv("OPENFACTORY_METRICS_DB")
    monkeypatch.chdir(tmp_path)
    client = _client()
    assert client.get("/api/projects").status_code == 200, "a new install, locked out"
    _register(client)
    assert client.get("/api/projects").status_code == 401

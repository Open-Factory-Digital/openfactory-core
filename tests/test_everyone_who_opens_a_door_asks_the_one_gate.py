"""The gate is one function; everyone who opens a door asks it, and nobody asks it on the loop.

#208 moved the panel's authorization decision into `_gate_verdict` — "who is this, and may they
read that" — and had two callers ask it: the HTTP middleware, and the watch that re-asks for
whatever stays open. It left two things, by name, and this file is about both.

**THE SOCKET'S HANDSHAKE WAS STILL A COPY.** An `@app.middleware("http")` never sees a websocket
scope, so `/api/stream` authorizes its own open. It did that with the rule written out again by
hand, and the hand-written one did not read the same credential: `?token=`, else the cookie, never
the `Authorization` header — where the gate reads header, cookie, `?token=`. Measured on
2026-09-19 over thirteen presentations of two real credentials, the two transports answered SEVEN
differently: a Bearer header every route accepts was refused the socket, and a connection the gate
refuses (a wrong header in front of a good cookie; a product cookie beside a floor `?token=`) was
accepted by it. It also logged no `DENIED_SCOPE_READ`, forgot what a connection presented when the
panel happened to be open, and let a provider's exception escape raw.

**THE MIDDLEWARE ASKED ON THE EVENT LOOP.** The verdict is synchronous and may read a store or
the network. Sub-millisecond for the local row on sqlite — and up to `HTTP_TIMEOUT_SECONDS` (5 s)
for the in-tree `oidc` row, whose `identify` fetches the issuer's discovery document inline.
Measured under uvicorn with an issuer that takes a second: somebody else's `GET /` — the HTML
shell, which is not gated — waited 1024 ms behind one stranger's ask.

Everything here drives the REAL app: `TestClient.websocket_connect` for the handshake, real
local-identity sessions minted by `/auth/login`, an add-on-shaped provider for what no in-tree row
does. The bench (a real sqlite people store, the re-check's clock in the case's hands) is #208's.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_a_stream_ends_when_its_credential_does import (  # noqa: F401 — fixtures
    Directory,
    Socket,
    bench,
    directory,
    register,
    sign_in,
)

ROOT = Path(__file__).resolve().parent.parent
SOCKET = "/api/stream"
FLOOR_READ = "/api/projects"

OPERATOR = "op-secret"
ANALYST = "ba-secret"


@pytest.fixture
def scoped(bench, monkeypatch):  # noqa: F811 — the fixture, not the import
    """One floor credential and one product credential, each naming a person."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", f"{OPERATOR}:ana:Ana")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", f"{ANALYST}:bia:Bia")
    return bench


# ── the two transports, driven ──────────────────────────────────────────────────────────────────

def _client(api, cookie: str = "") -> TestClient:
    client = TestClient(api.app)
    if cookie:
        client.cookies.set("openfactory_token", cookie)
    return client


def _headers(header: str) -> dict:
    return {"authorization": f"Bearer {header}"} if header else {}


def handshake(api, *, query: str = "", header: str = "", cookie: str = "", client=None):
    """What the socket answers this presentation: `("open", <first frame's kind>)`,
    `("refused", code, reason)` for a close BEFORE `accept()`, or `("accepted then closed", code,
    reason)`. Run on a thread of its own under a bound — `TestClient`'s socket blocks for ever on a
    handler that accepts and then says nothing, and a mutant may be exactly that."""
    out: list = []
    client = client or _client(api, cookie)

    def _drive() -> None:
        try:
            with client.websocket_connect(SOCKET + (f"?token={query}" if query else ""),
                                          headers=_headers(header)) as ws:
                try:
                    out.append(("open", ws.receive_json()["kind"]))
                except WebSocketDisconnect as gone:
                    out.append(("accepted then closed", gone.code, gone.reason))
        except WebSocketDisconnect as refused:
            out.append(("refused", refused.code, refused.reason))
        except Exception as exc:  # noqa: BLE001 — reported to the case, which decides
            out.append(("raised", type(exc).__name__, str(exc)))

    thread = threading.Thread(target=_drive, daemon=True)
    thread.start()
    thread.join(10)
    assert out, "ten seconds passed and the handshake neither opened nor closed"
    return out[0]


def get(api, path: str = FLOOR_READ, *, query: str = "", header: str = "", cookie: str = ""):
    answer = _client(api, cookie).get(path + (f"?token={query}" if query else ""),
                                      headers=_headers(header))
    return answer.status_code


#: What a socket does for each of the gate's answers — the watch's vocabulary (#208), so a socket
#: refused at the open and one ended ten seconds later are closed the same way.
AS_A_SOCKET = {200: ("open", "hello"), 401: ("refused", 1008, "signed_out"),
               403: ("refused", 1008, "not_allowed"), 503: ("refused", 1011, "unavailable")}

#: (what is presented, the gate's answer to it). The answer is written down, not computed from
#: the middleware, so the two transports cannot drift TOGETHER: this column is also a pin on the
#: middleware's own behaviour, which this change must not move.
PRESENTATIONS = [
    ("nothing", {}, 401),
    ("?token= floor", {"query": OPERATOR}, 200),
    ("?token= product", {"query": ANALYST}, 403),
    ("cookie floor", {"cookie": OPERATOR}, 200),
    ("cookie product", {"cookie": ANALYST}, 403),
    ("Bearer floor", {"header": OPERATOR}, 200),
    ("Bearer product", {"header": ANALYST}, 403),
    ("cookie product beside ?token= floor", {"cookie": ANALYST, "query": OPERATOR}, 403),
    ("cookie floor beside ?token= product", {"cookie": OPERATOR, "query": ANALYST}, 200),
    ("cookie floor beside a stale ?token=", {"cookie": OPERATOR, "query": "stale"}, 200),
    ("a wrong Bearer in front of a good cookie", {"header": "nobody", "cookie": OPERATOR}, 401),
    ("Bearer product in front of cookie floor", {"header": ANALYST, "cookie": OPERATOR}, 403),
]


# ── 1. one presentation, one answer ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("presented", "answer"), [(p, a) for _n, p, a in PRESENTATIONS],
                         ids=[n for n, _p, _a in PRESENTATIONS])
def test_the_socket_answers_a_presentation_AS_THE_GATE_DOES(scoped, presented, answer):
    """THE DEFECT. Whether a connection gets in is compared here, not the words it is refused
    with (those are the next case's): open where the gate answers 200, closed before `accept()`
    where it refuses."""
    assert get(scoped.api, **presented) == answer, "the middleware's own answer moved"
    said = handshake(scoped.api, **presented)
    assert said[:1] == AS_A_SOCKET[answer][:1] and (answer == 200 or said[1] == 1008), (
        f"GET {FLOOR_READ} answers {answer} and the socket's handshake answered {said}: two "
        f"answers to one presentation")


@pytest.mark.parametrize(("presented", "answer"), [(p, a) for _n, p, a in PRESENTATIONS if a != 200],
                         ids=[n for n, _p, a in PRESENTATIONS if a != 200])
def test_a_refused_handshake_says_WHY_in_the_words_the_watch_uses(scoped, presented, answer):
    """1008 `signed_out` for the gate's 401, 1008 `not_allowed` for its 403 — what a socket that
    is ended LATER is closed with. A header's product credential is somebody who may not, never
    nobody: the copy could not tell, because it never read the header."""
    assert handshake(scoped.api, **presented) == AS_A_SOCKET[answer]


def test_a_provider_that_cannot_be_BUILT_refuses_both_the_same_way(scoped, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "a-row-nobody-installed")
    assert get(scoped.api, header=OPERATOR) == 503
    assert handshake(scoped.api, header=OPERATOR) == AS_A_SOCKET[503]


def test_an_OPEN_panel_opens_the_socket_to_whoever_asks(bench):  # noqa: F811
    """The positive twin of everything above: nothing configured, nobody registered."""
    assert get(bench.api) == 200
    assert handshake(bench.api) == AS_A_SOCKET[200]


# ── 2. real sessions ────────────────────────────────────────────────────────────────────────────

def test_a_SESSION_opens_the_socket_and_stops_opening_it_once_signed_out(bench):  # noqa: F811
    register()
    browser = sign_in(bench.api)
    assert handshake(bench.api, client=browser) == AS_A_SOCKET[200]
    session = browser.cookies["openfactory_token"]
    assert handshake(bench.api, header=session) == AS_A_SOCKET[200], (
        "the session every route accepts as a Bearer header does not open the socket")
    browser.get("/auth/logout")
    assert handshake(bench.api, cookie=session) == AS_A_SOCKET[401]
    assert handshake(bench.api, header=session) == AS_A_SOCKET[401]


def test_a_person_invited_to_the_PRODUCT_is_refused_the_floors_socket(bench):  # noqa: F811
    """#145's hole, asked of a registered person's session rather than of a token row."""
    register("bia@acme.example", groups=("product",))
    browser = sign_in(bench.api, "bia@acme.example")
    session = browser.cookies["openfactory_token"]
    assert browser.get(FLOOR_READ).status_code == 403
    assert handshake(bench.api, client=browser) == AS_A_SOCKET[403]
    assert handshake(bench.api, header=session) == AS_A_SOCKET[403]


# ── 3. it IS the gate's function, and there is nothing beside it ────────────────────────────────

def test_the_handshake_asks_the_GATE_about_its_own_path_with_what_was_presented(scoped,
                                                                                monkeypatch):
    asked = []
    real = scoped.api._gate_verdict

    def _seen(path, credential):
        asked.append((path, credential))
        return real(path, credential)

    monkeypatch.setattr(scoped.api, "_gate_verdict", _seen)
    assert handshake(scoped.api, header=OPERATOR, cookie=ANALYST, query="stale")[0] == "open"
    assert asked and set(asked) == {(SOCKET, OPERATOR)}, (
        f"the handshake did not ask `_gate_verdict` about {SOCKET} with the credential "
        f"`_credential_of` reads: {asked}")


def test_the_gates_NO_is_the_handshakes_no(scoped, monkeypatch):
    """With the verdict swapped for one that refuses everybody, a good credential is refused: the
    decision is the function's. A handshake that decides for itself opens here."""
    api = scoped.api
    monkeypatch.setattr(api, "_gate_verdict", lambda _p, _c: api._Refusal(403, {"detail": "no"}))
    assert handshake(api, query=OPERATOR) == AS_A_SOCKET[403]


def test_the_gates_YES_is_the_handshakes_yes(scoped, monkeypatch):
    """…and the other way, which is what proves no copy is left BESIDE the ask: with the verdict
    answering yes to everybody, nothing else in the handshake still has an opinion."""
    monkeypatch.setattr(scoped.api, "_gate_verdict", lambda _p, _c: None)
    assert handshake(scoped.api, query="nobody-at-all") == AS_A_SOCKET[200]


# ── 4. what the copy did not do ─────────────────────────────────────────────────────────────────

def test_a_scope_refusal_at_the_socket_is_LOGGED_as_it_is_anywhere_else(scoped, caplog):
    with caplog.at_level(logging.DEBUG):
        assert handshake(scoped.api, query=ANALYST) == AS_A_SOCKET[403]
    assert f"DENIED_SCOPE_READ {SOCKET} (floor) for a credential scoped to product" in caplog.text, (
        "a product credential reached for the floor's socket and no audit line says so")
    assert ANALYST not in caplog.text, "the credential was written down"


async def test_a_socket_opened_on_an_OPEN_panel_REMEMBERS_what_it_presented(bench,  # noqa: F811
                                                                           monkeypatch):
    """The copy read the credential only when the panel was not open to everyone, so the watch
    was handed "" — and the day the deployment configured exactly the token this browser holds,
    its event streams stayed and its socket was ended as signed out."""
    socket = Socket("the-token-to-be")
    handler = asyncio.create_task(bench.api.stream(socket))
    try:
        await bench.until(lambda: len(socket.sent) >= 2, "the socket never opened")
        monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "the-token-to-be")
        before = len(bench.asks)
        bench.clock += bench.interval + 1
        await bench.until(lambda: len(bench.asks) > before, "the socket was not asked about again")
        await asyncio.sleep(0)
        assert not handler.done() and socket.closed is None, (
            f"the socket forgot the credential it was opened with: {socket.sent[-1]}")
    finally:
        handler.cancel()


def test_a_provider_that_RAISES_at_the_open_is_said_by_name_without_the_credential(
        bench, directory, caplog):  # noqa: F811
    """`identify` never raises by contract; an add-on's may. The watch already fails closed and
    by name (#208); the open is the watch's first ask, so it does too — 1011, because nobody was
    judged — instead of handing the server a traceback whose text quotes the credential."""
    directory.broken = "the directory refused token {credential}"
    with caplog.at_level(logging.DEBUG):
        said = handshake(bench.api, query="ana-key")
    assert said == AS_A_SOCKET[503], said
    assert "OPENFACTORY_STREAM_UNCHECKED" in caplog.text, "it was refused in silence"
    assert "the directory refused token" in caplog.text
    assert "ana-key" not in caplog.text + str(said), "the credential was written down"


def test_nothing_a_handshake_logs_or_says_names_the_SESSION(bench, caplog):  # noqa: F811
    from openfactory.identity.people import digest

    register()
    register("bia@acme.example", groups=("product",))
    ana, bia = sign_in(bench.api), sign_in(bench.api, "bia@acme.example")
    sessions = [ana.cookies["openfactory_token"], bia.cookies["openfactory_token"]]
    ana.get("/auth/logout")
    with caplog.at_level(logging.DEBUG):
        said = [handshake(bench.api, header=s) for s in sessions]
    assert said == [AS_A_SOCKET[401], AS_A_SOCKET[403]]
    written = caplog.text + str(said)
    for session in sessions:
        assert session not in written and digest(session) not in written


# ── 5. nobody asks on the event loop ────────────────────────────────────────────────────────────

def _panel(api) -> httpx.AsyncClient:
    """The real app on THIS test's event loop, so "the loop's thread" is the case's own."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                             base_url="http://panel.test")


async def test_the_MIDDLEWARE_asks_off_the_event_loop(bench, directory):  # noqa: F811
    """A path no route answers, so the gate is the only thing that asks the provider."""
    async with _panel(bench.api) as panel:
        answer = await panel.get("/api/no-such-route", headers=_headers("ana-key"))
    assert answer.status_code == 404, "the gate did not let a good credential through"
    assert directory.asked_on, "the provider was never asked"
    assert threading.current_thread().name not in directory.asked_on, (
        "the gate asked the identity provider on the event loop's own thread — every stream and "
        "every other request waits for as long as that read takes")


async def test_the_HANDSHAKE_asks_off_the_event_loop(bench, directory):  # noqa: F811
    socket = Socket("ana-key")
    handler = asyncio.create_task(bench.api.stream(socket))
    try:
        await bench.until(lambda: len(socket.sent) >= 2, "the socket never opened")
    finally:
        handler.cancel()
    assert directory.asked_on and threading.current_thread().name not in directory.asked_on


class SlowDirectory(Directory):
    """A provider whose lookup WAITS — an issuer that is slow to answer, a store across a
    network. Bounded: on a loop it holds, nothing else can release it."""

    def __init__(self) -> None:
        super().__init__()
        self.asking = threading.Event()
        self.answered = threading.Event()

    def identify(self, *, credential: str, via: str = ""):
        self.asking.set()
        self.answered.wait(2)
        return super().identify(credential=credential, via=via)


async def test_ONE_slow_ask_holds_nobody_else(bench, monkeypatch):  # noqa: F811
    """Measured on 2026-09-19 under uvicorn, the `oidc` row, an issuer that takes a second:
    somebody else's `GET /` waited 1024 ms behind one stranger's ask. Here the ask waits until the
    case lets it go, and meanwhile the shell, the login page and a second person are answered."""
    from openfactory.identity import registry

    row = SlowDirectory()
    monkeypatch.setitem(registry.IDENTITIES, "directory", lambda **_kw: row)
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "directory")
    async with _panel(bench.api) as panel:
        slow = asyncio.create_task(panel.get("/api/no-such-route", headers=_headers("ana-key")))
        await bench.until(row.asking.is_set, "the provider was never asked")
        shell = await asyncio.wait_for(panel.get("/"), 5)
        still_asking = not slow.done()
        row.answered.set()
        assert (await asyncio.wait_for(slow, 5)).status_code == 404
    assert shell.status_code == 200
    assert still_asking, (
        "the shell was answered only AFTER the slow ask gave up: one ask of the identity "
        "provider held the panel's event loop, and everybody on it")


async def test_a_path_the_gate_does_not_guard_never_WAITS_FOR_A_THREAD(bench, directory,  # noqa: F811
                                                                     monkeypatch):
    """The shell and the login page answer without a credential — so they must not queue behind
    the identity provider either, which is what a thread-pool slot per request would do to them
    the day every slot is held by an ask that waits."""
    hopped = []
    real = asyncio.to_thread

    async def _seen(fn, *args, **kwargs):
        hopped.append(args[:1])
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(bench.api.asyncio, "to_thread", _seen)
    async with _panel(bench.api) as panel:
        assert (await panel.get("/")).status_code == 200
        assert not hopped and not directory.asked_on, f"the HTML shell took a thread: {hopped}"
        assert (await panel.get("/api/no-such-route", headers=_headers("ana-key"))).status_code == 404
    assert hopped == [("/api/no-such-route",)], hopped


# ── 6. a fourth door cannot be written by hand ──────────────────────────────────────────────────

#: Who in `openfactory/api/` may ask the identity provider WHO SOMEBODY IS (`identify`) or whether
#: the door is open (`open_to_everyone`), and why. Anybody else doing it is deciding admission
#: beside the gate — which is how the socket came to read a different credential.
MAY_ASK_WHO = {
    "_gate_verdict": "the gate: the one place a read is admitted or refused",
    "require_auth": "the write gate, header-only, BEHIND the middleware — it cannot admit what "
                    "the gate refused; folding it into the verdict is its own change",
    "_subject": "names the actor for the audit line and hands the action layer its scopes; it "
                "refuses nobody (`perform` does), and it answers `whoami`",
}

#: Who may BUILD the provider without asking it who anybody is: the login doors, which need the
#: provider's login flow and are reachable without a credential by design.
MAY_BUILD = {
    "_login_provider": "the SSO redirect and callback run the provider's own flow",
    "_form_login": "the local row's login form, once anybody is registered",
    "_no_login_page": "says WHY there is no login page, 404 or 503",
    "_local_provider": "the registration link, which makes the first person",
}

_ASKS_WHO = {"identify", "open_to_everyone"}


def _functions(tree: ast.AST):
    """Each function with the nodes that are ITS OWN — a nested function's belong to the nested
    one, so a helper inside a handshake is named, not hidden behind its parent."""
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            own, stack = [], list(ast.iter_child_nodes(fn))
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                own.append(node)
                stack.extend(ast.iter_child_nodes(node))
            yield fn, own


def who_asks(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(functions that ask the provider who somebody is, functions that build one). By CODE: an
    attribute or a call named `identify`/`open_to_everyone`, or the name handed to `getattr` —
    which is how the gate itself asks an add-on's row. A comment or a docstring is not code."""
    asks, builds = set(), set()
    for fn, own in _functions(tree):
        for node in own:
            if isinstance(node, ast.Attribute) and node.attr in _ASKS_WHO:
                asks.add(fn.name)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "getattr" \
                    and any(isinstance(a, ast.Constant) and a.value in _ASKS_WHO for a in node.args):
                asks.add(fn.name)
            if isinstance(node, ast.Call) and "build_identity" in (
                    getattr(node.func, "id", ""), getattr(node.func, "attr", "")):
                builds.add(fn.name)
    return asks, builds


def _api_modules() -> dict[str, ast.AST]:
    return {m.name: ast.parse(m.read_text()) for m in sorted((ROOT / "openfactory/api").glob("*.py"))}


def test_NOBODY_in_the_panel_asks_who_somebody_is_but_the_gate_and_the_named_few():
    asks, builds = set(), set()
    for tree in _api_modules().values():
        found = who_asks(tree)
        asks |= found[0]
        builds |= found[1]
    assert asks == set(MAY_ASK_WHO), (
        f"{sorted(asks - set(MAY_ASK_WHO))} ask(s) the identity provider who somebody is, outside "
        f"`_gate_verdict`. A door that decides for itself is a second copy of the rule: ask "
        f"`_ask_the_gate(path, _credential_of(connection))` instead. (No longer asking: "
        f"{sorted(set(MAY_ASK_WHO) - asks)}.)")
    assert builds - asks == set(MAY_BUILD), (
        f"the functions that build an identity provider without being the gate are "
        f"{sorted(builds - asks)}, and the ones named here with a reason are {sorted(MAY_BUILD)}")


def test_the_enumeration_SEES_a_copy_written_by_hand():
    """Proven able to fail, on the shapes a copy has been written in: the handshake's own (a
    `getattr` for the row that may not declare it), a plain call, and one tucked into a helper
    inside the route."""
    copy = ast.parse(
        "async def stream(ws):\n"
        "    provider = build_identity()\n"
        "    if not getattr(provider, 'open_to_everyone', lambda: False)():\n"
        "        who = provider.identify(credential=ws.query_params.get('token'), via='panel')\n"
        "async def feed(ws):\n"
        "    def _known():\n"
        "        return build_identity().identify(credential='', via='panel')\n"
        "    '''provider.identify is only mentioned here'''\n"
        "def prose():\n"
        "    '''build_identity().identify(...) in a docstring is not code'''\n")
    assert who_asks(copy) == ({"stream", "_known"}, {"stream", "_known"})


def _socket_routes(app) -> dict[str, ast.AST]:
    import inspect
    import textwrap

    from starlette.routing import WebSocketRoute

    return {route.path: ast.parse(textwrap.dedent(inspect.getsource(route.endpoint)))
            for route in app.routes if isinstance(route, WebSocketRoute)}


def _line_of(tree: ast.AST, called: str) -> int:
    lines = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
             and called in (getattr(n.func, "id", ""), getattr(n.func, "attr", ""))]
    return min(lines) if lines else 0


def test_EVERY_websocket_route_asks_before_it_accepts():
    """The middleware cannot see one, so each asks for itself — through the watch, with what
    `_credential_of` reads, BEFORE `accept()`. A second socket gets this or the suite says so."""
    from openfactory.api import app as api

    routes = _socket_routes(api.app)
    assert set(routes) == {SOCKET}, (
        f"{sorted(set(routes) - {SOCKET})} is a websocket route with no case in this file: drive "
        f"it through `handshake` above, then name it here")
    for path, tree in routes.items():
        watch, reads, asked = (_line_of(tree, "_CredentialWatch"), _line_of(tree, "_credential_of"),
                               _line_of(tree, "asked"))
        accept = _line_of(tree, "accept")
        assert watch and reads and asked, (
            f"{path} does not ask the gate for itself — no HTTP middleware runs for a websocket. "
            f"`watch = _CredentialWatch(ws.url.path, _credential_of(ws))`, then "
            f"`await watch.asked()` and close on anything but None.")
        assert accept and max(watch, reads, asked) < accept, (
            f"{path} accepts the socket (line {accept}) before it has asked (line {asked})")

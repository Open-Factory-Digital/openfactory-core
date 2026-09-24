"""The panel is a chat with the product role — #266 slice 5, ADR-0051 D13 and D15.

WHAT IS PINNED HERE. The product page was a form that polled: the row held the request open while
the door polled the conversation for the answer, the page re-read the thread every five seconds for
five minutes, and the room every thirty. Now the conversation and the role's presence reach the
page over a socket of its own (`/api/product/stream`), read once per open conversation from the
conversation's workflow (`ConversationWorkflow.watch`), and FILTERED PER SUBSCRIBER: a private
conversation reaches its own person and nobody else, a room reaches whoever may read the room. A
message carries the page it was written on, and the card on a card's page reaches the role as its
current state — a card of this project, on a board this person may read, and no other.

HOW. The socket is driven through the REAL app with Starlette's `TestClient` — the real gate at
the handshake, real per-person credentials — against a durable engine stood in for in process
(`Conversations`): each message is numbered the way the workflow numbers it and answered by the
worker's OWN turn function (`activities._conversation_turn`), with only the product module behind
the engine replaced. The workflow's own `watch` query, and the page context crossing it into the
turn, are driven on Temporal's test server. The page's rule — no clock on the product chat — is
held over `panel.html`, and its frame handling is executed under node.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.memory.transcript import Turn
from openfactory.runtime.temporal.io import TurnInput

ROOT = Path(__file__).resolve().parent.parent
PANEL = (ROOT / "openfactory/api/panel.html").read_text()
SOCKET = "/api/product/stream"

ANA, BRUNO, CARLA, BIA = "tok-ana", "tok-bruno", "tok-carla", "tok-bia"


# ── the bench ───────────────────────────────────────────────────────────────────────────────────

def _project(name: str, docs: str, repo: str) -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language="pt-BR",
                   tracker=ProviderRef(kind="github", repo=repo),
                   product=ProductConfig(docs_repo=docs, admins=["ana"], agent_name="Nina"))


class Memory:
    """The transcript in memory, keyed by thread, the way the store keys a conversation."""

    def __init__(self) -> None:
        self.turns: dict[str, list[Turn]] = {}
        self.n = 0

    def record(self, project, *, thread, role, text, actor="", channel="", message_id="",
               in_reply_to="", addressed=True):
        # the transcript keeps which message a turn is and what it answers (#266 slice 4), and
        # whether it was addressed to the role (#266 slice 6)
        self.n += 1
        self.turns.setdefault(thread, []).append(Turn(role=role, text=text, ts=f"t{self.n}",
                                                      actor=actor, addressed=addressed))
        return f"t{self.n}"

    def recent(self, project, *, thread, channel="", budget=0, overheard=False):
        # what the room said to somebody else is read only by a caller that shows the room
        return [t for t in self.turns.get(thread, []) if overheard or t.addressed]


class Role:
    """The product module behind the engine: it answers with what it was handed as the current
    state, so a test can read on the page what reached the role."""

    handed: list[str] = []

    def __init__(self, project, via=""):
        pass

    def settle_acceptance(self, text):
        return None

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def close_decisions_answered(self, *, channel=""):
        return 0

    def answer(self, question, *, context="", conversation="", pending=""):
        Role.handed.append(context)
        said = f"resposta a: {question}" + (f" || {context}" if context else "")
        return SimpleNamespace(ok=True, text=said, is_request=False)


class Tracker:
    """Card #42 of the books board, as its tracker has it — and nothing else."""

    read: list[str] = []

    def get_ticket(self, ref):
        Tracker.read.append(ref)
        if ref != "42":
            raise KeyError(ref)
        return SimpleNamespace(title="Relatório mensal", state="open", labels=["parked"])

    def comments(self, ref):
        return [SimpleNamespace(author="openfactory",
                                body="parked: the tests failed on the date parser")]


class Conversations:
    """The durable engine behind the door and the socket, stood in for IN PROCESS.

    One conversation per workflow id, numbered the way `ConversationWorkflow` numbers it: each
    message heard, then — one turn at a time — the worker's own turn function run in a thread and
    its replies published. `watch` and `where` answer from that. `hold` is set while turns may
    run; cleared, a turn stops after it has started, so the role is seen busy."""

    def __init__(self) -> None:
        self.convs: dict[str, dict] = {}
        self.arrivals: list = []
        self.hold = threading.Event()
        self.hold.set()

    async def start_workflow(self, workflow, arg, *, id, task_queue, start_signal=None,
                             start_signal_args=(), **_kw):
        arrival = start_signal_args[0]
        c = self.convs.get(id)
        if c is None:
            c = self.convs[id] = {"seq": 0, "heard": [], "outbox": [], "running": False,
                                  "waiting": [], "seen": set(), "lock": asyncio.Lock()}
        if arrival.id in c["seen"]:
            return
        c["seen"].add(arrival.id)
        self.arrivals.append(arrival)
        c["seq"] += 1
        c["heard"].append({"type": "said", "seq": c["seq"], "id": arrival.id,
                           "speaker": arrival.speaker, "text": arrival.text})
        c["waiting"].append(arrival.speaker)
        asyncio.get_running_loop().create_task(self._turn(c, arg, arrival))

    async def _turn(self, c, arg, arrival) -> None:
        from openfactory.registry import ProjectRegistry
        from openfactory.runtime.temporal.activities import _conversation_fast, _conversation_turn

        async with c["lock"]:
            c["waiting"].remove(arrival.speaker)
            c["running"] = True
            await asyncio.to_thread(self.hold.wait)
            project = ProjectRegistry().get(arrival.project)
            work = TurnInput(product=arg.product, project=arrival.project,
                             conversation=arg.conversation, speaker=arrival.speaker,
                             text=arrival.text, id=arrival.id, ids=[arrival.id], via=arrival.via,
                             language=arrival.language, context=dict(arrival.context))
            run = _conversation_fast if arrival.fast else _conversation_turn
            replies = await asyncio.to_thread(run, project, work)
            c["running"] = False
            c["seq"] += 1
            c["outbox"].append({"seq": c["seq"], "covers": [arrival.id], "final": True,
                                "replies": [r.model_dump(mode="json") for r in replies
                                            if r.kind != "receipt"]})

    def get_workflow_handle(self, wid):
        engine = self

        class _Handle:
            async def query(self, name, arg, **_kw):
                c = engine.convs.get(wid)
                if c is None:
                    raise RuntimeError(f"workflow not found: {wid}")
                if name == "where":
                    return {"state": "queued", "ahead": 0, "coalesced": False,
                            "duplicate": False, "replies": []}
                assert name == "watch", name
                fresh = [{"type": "replies", **e} for e in c["outbox"] if e["seq"] > int(arg)]
                fresh += [h for h in c["heard"] if h["seq"] > int(arg)]
                return {"seq": c["seq"], "entries": sorted(fresh, key=lambda e: e["seq"]),
                        "presence": {"running": c["running"], "fast": 0,
                                     "waiting": list(c["waiting"])}}

        return _Handle()


@pytest.fixture
def chat(monkeypatch, tmp_path):
    """Three people with a panel credential, one with a product-only credential, two products —
    and the engine, the memory, the role and the tracker stood in for."""
    from openfactory.actions import catalog
    from openfactory.adapters.tracker import registry as trackers
    from openfactory.api import product_chat
    from openfactory.memory import transcript
    from openfactory.product import door
    from openfactory.product import module as product_module
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    for p in (_project("books", "acme/books-docs", "acme/books"),
              _project("shop", "acme/shop-docs", "acme/shop")):
        ProjectRegistry(path).add(p)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS",
                       f"{ANA}:ana:Ana,{BRUNO}:bruno:Bruno,{CARLA}:carla:Carla")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKENS", f"{BIA}:bia:Bia")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)

    engine = Conversations()

    async def _engine():
        return engine

    async def _connected():
        return engine, None

    monkeypatch.setattr(door, "_engine", _engine)
    monkeypatch.setattr(catalog, "_connected", _connected)
    memory = Memory()
    monkeypatch.setattr(transcript, "record", memory.record)
    monkeypatch.setattr(transcript, "recent", memory.recent)
    monkeypatch.setattr(product_module, "ProductModule", Role)
    monkeypatch.setattr(trackers, "build_tracker", lambda *_a, **_k: Tracker())
    # the reader's clock, shortened: a test waits a fraction of a second, never a tick
    monkeypatch.setattr(product_chat, "BUSY_TICK", 0.02)
    monkeypatch.setattr(product_chat, "IDLE_TICK", 0.05)
    Role.handed, Tracker.read = [], []
    yield SimpleNamespace(engine=engine, memory=memory)
    engine.hold.set()   # a case that failed while a turn was held must not hold the next one


def _open(client: TestClient, token: str):
    return client.websocket_connect(SOCKET, headers={"authorization": f"Bearer {token}"})


def _next(ws, within: float) -> dict:
    """The socket's next frame, or a TimeoutError — `receive_json` would wait for ever."""
    async def _get():
        with anyio.fail_after(within):
            return await ws._send_rx.receive()

    message = ws.portal.call(_get)
    ws._raise_on_close(message)
    return json.loads(message["text"])


def until(ws, wanted, *, within: float = 8.0) -> list[dict]:
    """Every frame up to and including the first `wanted` accepts."""
    seen: list[dict] = []
    deadline = time.monotonic() + within
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"waited {within}s and it never came; saw {seen}")
        try:
            frame = _next(ws, left)
        except TimeoutError:
            raise AssertionError(f"waited {within}s and it never came; saw {seen}") from None
        seen.append(frame)
        if wanted(frame):
            return seen


def subscribe(ws, project: str = "books", **asked) -> list[dict]:
    assert _next(ws, 5)["kind"] == "hello"
    ws.send_json({"kind": "subscribe", "project": project, **asked})
    return until(ws, lambda f: f["kind"] in ("history", "refused"))


def say(ws, text: str, *, context=None, sid: str | None = None) -> str:
    sid = sid or f"m{abs(hash((text, time.monotonic_ns()))):020d}"
    ws.send_json({"kind": "say", "id": sid, "text": text,
                  **({"context": context} if context is not None else {})})
    return sid


def answered(text: str):
    return lambda f: f["kind"] == "reply" and f"resposta a: {text}" in f["text"]


def said_anywhere(frames: list[dict], words: str) -> bool:
    return any(words in json.dumps(f, ensure_ascii=False) for f in frames)


# ── a private conversation reaches its own person, and nobody else ─────────────────────────────

def test_two_private_conversations_never_reach_each_other(chat):
    """Ana and Bruno each talk to the role in their own conversation, on the same project, at the
    same time. Each is handed what they said and what the role answered them — and nothing of the
    other's, in either direction."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, ANA) as ana, _open(client, BRUNO) as bruno:
        assert subscribe(ana, room=False)[0]["private"] is True
        assert subscribe(bruno, room=False)[0]["private"] is True

        say(ana, "segredo da ana")
        mine = until(ana, answered("segredo da ana"))
        assert said_anywhere(mine, "segredo da ana")

        say(bruno, "segredo do bruno")
        bruno_saw = until(bruno, answered("segredo do bruno"))
        assert not said_anywhere(bruno_saw, "segredo da ana"), bruno_saw

        say(ana, "de novo a ana")
        ana_saw = until(ana, answered("de novo a ana"))
        assert not said_anywhere(ana_saw, "segredo do bruno"), ana_saw


def test_a_private_key_that_is_not_ones_own_is_REFUSED_at_the_subscription(chat):
    """The page never names a private conversation; a socket that names somebody else's anyway is
    refused before anything is read — the rule every product row keys by (`key_for`)."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, BRUNO) as bruno:
        frames = subscribe(bruno, room=False, thread="person:ana")
        assert frames[-1]["kind"] == "refused", frames
        assert "one person's alone" in frames[-1]["why"]
        assert not any(f["kind"] in ("subscribed", "history") for f in frames), frames


def test_the_filter_is_asked_for_every_frame_not_trusted_from_the_subscription():
    """`may_receive` is the routing: a subscriber whose subscription somehow named another
    person's private conversation is still handed none of it, because its OWN key is not that
    conversation's."""
    from openfactory.api.product_chat import Subscriber, may_receive

    def sub(**kw):
        base = dict(person="bruno", own="person:bruno", product="p", project="books",
                    conversation="person:bruno", may_read_room=True, frames=None)
        return Subscriber(**{**base, **kw})

    assert may_receive(sub(), product="p", conversation="person:bruno")
    assert not may_receive(sub(conversation="person:ana"), product="p",
                           conversation="person:ana"), "a stolen key was handed the frames"
    assert not may_receive(sub(own="", conversation="person:ana"), product="p",
                           conversation="person:ana")
    assert not may_receive(sub(), product="q", conversation="person:bruno"), "another product"
    assert may_receive(sub(conversation="books"), product="p", conversation="books")
    assert not may_receive(sub(conversation="books", may_read_room=False), product="p",
                           conversation="books"), "the room reached somebody who may not read it"


# ── a room reaches its members, and only them ───────────────────────────────────────────────────

def test_a_room_is_delivered_to_its_members_only(chat):
    """Ana and Bruno are in the books room: each sees what the other said and what the role
    answered. Carla is in her own conversation on books, and Bia in the shop's room: neither is
    handed a word of the books room."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, ANA) as ana, \
            _open(client, BRUNO) as bruno, _open(client, CARLA) as carla, \
            _open(client, BIA) as bia:
        assert subscribe(ana, room=True)[0]["room"] is True
        subscribe(bruno, room=True)
        subscribe(carla, room=False)
        subscribe(bia, "shop", room=True)

        say(ana, "na sala, a ana")
        seen = until(bruno, answered("na sala, a ana"))
        heard = [f for f in seen if f["kind"] == "said"]
        assert heard and heard[0]["text"] == "na sala, a ana" and heard[0]["speaker"] == "ana"
        assert heard[0]["mine"] is False
        until(ana, answered("na sala, a ana"))

        say(carla, "a carla, sozinha")
        carla_saw = until(carla, answered("a carla, sozinha"))
        assert not said_anywhere(carla_saw, "na sala, a ana"), carla_saw

        say(bia, "na sala da loja")
        bia_saw = until(bia, answered("na sala da loja"))
        assert not said_anywhere(bia_saw, "na sala, a ana"), bia_saw
        assert not said_anywhere(bia_saw, "a carla, sozinha"), bia_saw


def test_joining_a_room_hands_over_what_was_said_there_before(chat):
    """The catch-up is the transcript: a page that subscribes — for the first time, or again after
    its socket dropped — is handed the room's recent turns before anything live."""
    from openfactory.api import app as api

    with TestClient(api.app) as client:
        with _open(client, ANA) as ana:
            subscribe(ana, room=True)
            say(ana, "antes de o bruno chegar")
            until(ana, answered("antes de o bruno chegar"))
        with _open(client, BRUNO) as bruno:
            history = subscribe(bruno, room=True)[-1]
        texts = [t["text"] for t in history["turns"]]
        assert "antes de o bruno chegar" in texts
        assert any(t.startswith("resposta a: antes de o bruno chegar") for t in texts)


# ── busy is a presence, and each person is told their own place ─────────────────────────────────

def test_the_roles_presence_is_published_and_names_nobody(chat):
    """While Ana's turn runs, the room is told the role is thinking; Bruno, who wrote behind her,
    is told his turn is next — and no presence anybody is handed names who the role is answering.
    When the answer goes out the room is told so, and the role is idle again."""
    from openfactory.api import app as api

    chat.engine.hold.clear()
    with TestClient(api.app) as client, _open(client, ANA) as ana, _open(client, BRUNO) as bruno:
        try:
            subscribe(ana, room=True)
            subscribe(bruno, room=True)

            say(ana, "a primeira")
            until(ana, lambda f: f["kind"] == "presence" and f["state"] == "thinking")
            say(bruno, "e a segunda")
            bruno_saw = until(bruno, lambda f: f["kind"] == "presence" and f["ahead"] == 1)
            assert bruno_saw[-1]["state"] == "thinking"
            presences = [f for f in bruno_saw if f["kind"] == "presence"]
            assert all(set(p) == {"kind", "state", "ahead"} for p in presences), presences
            assert not any("ana" in json.dumps(p) for p in presences), "a presence named a person"
        finally:
            chat.engine.hold.set()
        after = until(ana, answered("e a segunda"))
        states = [f["state"] for f in after if f["kind"] == "presence"]
        assert "answering" in states, states
        assert until(ana, lambda f: f["kind"] == "presence" and f["state"] == "idle")


def test_presence_is_computed_per_person_from_the_conversations_own_account():
    from openfactory.api.product_chat import presence_for

    raw = {"running": True, "fast": 0, "waiting": ["bruno", "carla"]}
    assert presence_for(raw, "bruno") == {"kind": "presence", "state": "thinking", "ahead": 1}
    assert presence_for(raw, "carla")["ahead"] == 2
    assert presence_for(raw, "ana") == {"kind": "presence", "state": "thinking", "ahead": 0}
    assert presence_for({"running": False, "fast": 0, "waiting": []}, "ana")["state"] == "idle"
    assert presence_for(None, "ana")["state"] == "offline"


# ── the page context reaches the engine — as far as the person may see ──────────────────────────

def test_the_page_context_reaches_the_engine_as_the_card_the_person_is_looking_at(chat):
    """"Why did this stop?" asked on card #42's page: the role is handed card #42 — its title and
    the factory's latest word on it — as the current state, and answers about it."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, ANA) as ana:
        subscribe(ana, room=False)
        say(ana, "why did this stop?",
            context={"page": "card", "project": "books", "card": "42"})
        reply = until(ana, answered("why did this stop?"))[-1]
    assert chat.engine.arrivals[-1].context == {"page": "card", "card": "42"}
    assert "card #42" in reply["text"] and "Relatório mensal" in reply["text"], reply
    assert "the tests failed on the date parser" in Role.handed[-1]
    assert Tracker.read == ["42"]


@pytest.mark.parametrize("context, why", [
    ({"page": "card", "project": "shop", "card": "42"}, "belongs to shop"),
    ({"page": "card", "project": "books", "card": "acme/shop#42"}, "lives in acme/shop"),
    ({"page": "card", "project": "books", "card": "../42"}, "not a card of this board"),
    ({"page": "card", "project": "books", "card": "42", "thread": "person:ana"},
     "not thread"),
])
def test_a_context_naming_a_card_of_another_project_is_REFUSED(chat, context, why):
    """A card of another project — by the page's project, by a repository in the ref, or by a
    shape no board has — is refused with the message: nothing reaches the door, and no tracker
    is read."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, ANA) as ana:
        subscribe(ana, room=False)
        sid = say(ana, "why did this stop?", context=context)
        ack = until(ana, lambda f: f["kind"] == "ack" and f["id"] == sid)[-1]
    assert ack["ok"] is False and why in ack["text"], ack
    assert chat.engine.arrivals == [] and Tracker.read == []


def test_a_credential_that_cannot_read_the_board_cannot_ask_about_a_card(chat):
    """Bia holds a product credential: the board is refused her, so a card cannot become the
    subject of her question either — the context must never widen what a person may read. The
    product page's own context is hers to send."""
    from openfactory.api import app as api

    with TestClient(api.app) as client, _open(client, BIA) as bia:
        subscribe(bia, room=False)
        sid = say(bia, "why did this stop?",
                  context={"page": "card", "project": "books", "card": "42"})
        ack = until(bia, lambda f: f["kind"] == "ack" and f["id"] == sid)[-1]
        assert ack["ok"] is False and "cannot read the board" in ack["text"], ack
        assert Tracker.read == []

        say(bia, "o que falta?", context={"page": "product", "project": "books"})
        reply = until(bia, answered("o que falta?"))[-1]
    assert "product page" in reply["text"]


def test_admit_keeps_the_page_and_the_card_and_nothing_else():
    from openfactory.product.page import admit

    books = _project("books", "acme/books-docs", "acme/books")
    assert admit(books, None, may_read_board=True) == ({}, "")
    assert admit(books, {"page": "board", "project": "books"}, may_read_board=False) == (
        {"page": "board"}, "")
    assert admit(books, {"page": "card", "project": "books", "card": "#42"},
                 may_read_board=True) == ({"page": "card", "card": "42"}, "")
    assert admit(books, {"page": "card", "card": "acme/books#42"},
                 may_read_board=True) == ({"page": "card", "card": "42"}, "")
    assert admit(books, {"page": "nowhere"}, may_read_board=True)[1]
    assert admit(books, {"page": "card", "card": 42}, may_read_board=True)[1]
    assert admit(books, "card 42", may_read_board=True)[1]


def test_the_door_refuses_a_context_nobody_admitted():
    """The row admits a context and hands on the page and the card; anything else at the door
    came round that rule, and is refused rather than carried into a workflow's history."""
    from openfactory.product import door
    from openfactory.product.engine import Message

    books = _project("books", "acme/books-docs", "acme/books")
    ok = Message(id="m-00000001", project="books", conversation="books", text="oi",
                 context={"page": "card", "card": "42"})
    assert door.refusal(ok, books) == ""
    stray = ok.model_copy(update={"context": {"page": "card", "project": "shop"}})
    assert "page context" in door.refusal(stray, books)


def test_the_row_hands_the_message_over_and_returns_without_waiting(chat):
    """`wait=false` is the chat: the row returns the door's acknowledgement at once, never the
    answer — the answer reaches the page over the socket."""
    from openfactory import actions
    from openfactory.actions.base import Actor

    async def _say():
        # BOUNDED: a row that waited would read `where` until the conversation answered, and the
        # stand-in's `where` never says it has
        return await asyncio.wait_for(actions.perform(
            "product_say", by=Actor(id="ana", via="panel", conversation="person:ana"),
            project="books", message="sem esperar", message_id="m-sem-esperar-1",
            wait="false"), 5)

    out = asyncio.run(_say())
    assert out.ok and out.data["pending"] is True and out.data["id"] == "m-sem-esperar-1", out
    assert out.data["replies"] == []
    assert [a.id for a in chat.engine.arrivals] == ["m-sem-esperar-1"]


def test_the_row_refuses_a_message_id_it_could_not_carry(chat):
    from openfactory import actions
    from openfactory.actions.base import Actor

    out = asyncio.run(actions.perform(
        "product_say", by=Actor(id="ana", via="panel"), project="books", message="oi",
        message_id="../../etc", wait="false"))
    assert not out.ok and "message id" in out.message
    assert chat.engine.arrivals == []


# ── the socket is a door like every other ───────────────────────────────────────────────────────

def test_the_socket_refuses_a_caller_with_no_credential_before_it_accepts(chat):
    from openfactory.api import app as api

    with pytest.raises(WebSocketDisconnect) as refused:  # noqa: PT012
        with TestClient(api.app).websocket_connect(SOCKET):
            pass
    assert refused.value.code == 1008


def test_the_socket_speaks_as_the_person_the_COOKIE_names(chat):
    """A browser cannot put a header on a socket, and the page puts no credential in the socket's
    address: the cookie the page already holds is what the handshake reads, and the person it
    names is the person the socket speaks as."""
    from openfactory.api import app as api

    client = TestClient(api.app)
    client.cookies.set("openfactory_token", ANA)
    with client, client.websocket_connect(SOCKET) as ana:
        subscribe(ana, room=False)
        say(ana, "pelo cookie")
        until(ana, answered("pelo cookie"))
    assert chat.engine.arrivals[-1].speaker == "ana"
    assert chat.engine.arrivals[-1].conversation == "person:ana"


# ── the workflow's own account, on the engine ───────────────────────────────────────────────────

@pytest.mark.owns_its_engine
async def test_the_conversation_numbers_what_it_heard_and_published_and_carries_the_page(
        monkeypatch, tmp_path):
    """On Temporal's test server, with the conversation workflow as it ships: `watch` hands back
    each message heard and each reply published, numbered, after a cursor — and the page a message
    was written on reaches the worker's turn."""
    from temporalio import activity
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from openfactory.product import door
    from openfactory.product.engine import Message, Reply
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import TASK_QUEUE
    from openfactory.runtime.temporal.activities import conversation_report
    from openfactory.runtime.temporal.conversation import ConversationWorkflow

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    books = _project("books", "acme/books-docs", "acme/books")
    ProjectRegistry(tmp_path / "registry.yaml").add(books)
    turns: list[TurnInput] = []
    released = asyncio.Event()

    @activity.defn(name="conversation_turn")
    async def turn(inp: TurnInput) -> dict:
        turns.append(inp)
        while not released.is_set():
            activity.heartbeat("held")
            await asyncio.sleep(0.02)
        return {"replies": [Reply(text=f"resposta a: {inp.text}", in_reply_to=inp.id,
                                  conversation=inp.conversation).model_dump(mode="json")]}

    @activity.defn(name="conversation_fast")
    async def fast(inp: TurnInput) -> dict:
        return {"replies": []}

    quick = door.Settings(debounce_seconds=0.1, bound_seconds=30.0)
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                          activities=[turn, fast, conversation_report]):
            # BOTH NAME THE ROLE, as the panel's room detects it (#266 slice 6, ADR-0051 D14): a
            # room message is a turn only when it is addressed to the role
            first = await door.receive(
                Message(id="m-primeira-0001", project="books", conversation="books",
                        speaker="ana", text="por que parou?", via="panel",
                        context={"page": "card", "card": "42"}, mentions_role=True),
                project=books, client=env.client, settings=quick)
            deadline = time.monotonic() + 10
            while not turns and time.monotonic() < deadline:
                await asyncio.sleep(0.02)
            assert turns and turns[0].context == {"page": "card", "card": "42"}

            await door.receive(Message(id="m-segunda-0001", project="books",
                                       conversation="books", speaker="bruno", text="e eu?",
                                       via="panel", mentions_role=True),
                               project=books, client=env.client, settings=quick)
            busy = await door.watch(env.client, first.workflow_id, 0)
            assert busy["presence"] == {"running": True, "fast": 0, "waiting": ["bruno"]}
            said = [(e["type"], e["seq"], e["text"]) for e in busy["entries"]]
            assert said == [("said", 1, "por que parou?"), ("said", 2, "e eu?")], said

            released.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                later = await door.watch(env.client, first.workflow_id, busy["seq"])
                if len(later["entries"]) == 2:
                    break
                await asyncio.sleep(0.05)
            replies = [(e["type"], e["seq"], e["replies"][0]["text"]) for e in later["entries"]]
            assert replies == [("replies", 3, "resposta a: por que parou?"),
                               ("replies", 4, "resposta a: e eu?")], replies
            assert (await door.watch(env.client, first.workflow_id, 4))["entries"] == []
            with pytest.raises(door.NotStarted):
                await door.watch(env.client, door.workflow_id("repo:acme/none", "x"), 0)
    finally:
        await env.shutdown()


# ── the page: no clock on the product chat ──────────────────────────────────────────────────────

def _code() -> str:
    page = re.sub(r"/\*.*?\*/", "", PANEL, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in page.splitlines())


CODE = _code()


def _function(name: str) -> str:
    at = CODE.find(f"function {name}(")
    assert at >= 0, f"the panel has no function {name}"
    start = at - 6 if CODE[max(0, at - 6):at] == "async " else at
    depth = 0
    for pos in range(CODE.index("{", at), len(CODE)):
        if CODE[pos] == "{":
            depth += 1
        elif CODE[pos] == "}":
            depth -= 1
            if depth == 0:
                return CODE[start:pos + 1]
    raise AssertionError(f"could not find the end of panel function {name}")


def _product_chat_functions() -> list[str]:
    """Every function the product chat runs: the product page's own, and every `pchat…` one."""
    own = ["bootProduct", "renderProduct", "askProduct", "answerStaged", "setScope",
           "paintScope", "paintThread", "prodLook", "pageContext"]
    return own + sorted(set(re.findall(r"function (pchat[A-Za-z]*)\(", CODE)))


def test_the_product_chat_reads_on_NO_clock():
    """No polling on the product page (#266 slice 5's first criterion). The thirty-second room
    read, the five-second follow-up and the thread read they both made are gone; the one timer
    the chat keeps is the reconnect's backoff, and it re-opens the socket — it reads nothing."""
    for name in _product_chat_functions():
        body = _function(name)
        assert "setInterval" not in body, f"{name} reads the product chat on a clock"
        assert "_CHAT_TICK" not in body, f"{name} runs on the chat's polling tick"
        assert "product_thread" not in body, f"{name} re-reads the thread"
        if "setTimeout" in body:
            assert name == "pchatReopen" and "setTimeout(pchatConnect," in body, (
                f"{name} schedules something other than the socket's reconnect")
    for gone in ("loadThread", "watchRoom", "followUp"):
        assert f"function {gone}(" not in CODE, f"{gone} came back"


def test_the_product_page_boots_as_the_product_page_for_an_operator_too():
    """An operator's credential may read the floor, and the floor's boot starts five timers — so
    on the product page it would poll on the product chat's behalf. The page boots as what it is."""
    boot = _function("boot")
    route = "if(curProduct()!==null){ bootProduct(); return; }"
    assert route in boot, "an operator's product page runs the floor's clocks"
    assert boot.index(route) < boot.index("setInterval"), "the clocks start before the route"


def test_the_backoff_is_capped_and_a_reconnect_catches_up_by_subscribing():
    reopen, opened = _function("pchatReopen"), _function("pchatConnect")
    assert "Math.min(PCHAT_BACKOFF_MS" in reopen and "Math.pow(2" in reopen
    assert "pchatSubscribe()" in opened, "a socket that comes back never asks for the catch-up"


def test_no_credential_is_put_in_the_product_sockets_address():
    opened = _function("pchatConnect")
    assert "/api/product/stream`" in opened
    assert "token" not in opened, "the socket's URL carries the credential"


def test_every_message_carries_the_page_it_was_written_on():
    assert "context:pageContext()" in _function("pchatSay")


def test_the_chat_is_on_every_page():
    """The floor's boot mounts the chat, and every render follows the page to its project."""
    assert "pchatBoot()" in _function("boot")
    assert "pchatFollowPage()" in _function("render")
    assert "pchatUse(" in _function("renderProduct")


# ── the page's own functions, executed ──────────────────────────────────────────────────────────

_PRELUDE = r"""
const nodes={};function node(){const n={innerHTML:"",textContent:"",value:"",style:{display:""},
  scrollTop:0,scrollHeight:0,classList:{on:new Set(),toggle(c,v){v?this.on.add(c):this.on.delete(c)},
  contains(c){return this.on.has(c)},add(c){this.on.add(c)},remove(c){this.on.delete(c)}},
  focus(){}};return n}
function $(s){return nodes[s]||null}
const document={cookie:"",querySelectorAll(){return[]},body:{insertAdjacentHTML(){}}};
const localStorage={getItem(){return null},setItem(){}};
const crypto={getRandomValues(b){for(let i=0;i<b.length;i++)b[i]=i;return b}};
let location={pathname:"/",protocol:"http:",host:"panel.test"};
let _streamsEnded={};const sent=[];
function api(){return Promise.resolve([])}
function loadRequirements(){}
"""


def _run(script: str, *, pathname: str, board: str = "") -> object:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH — the page's JavaScript cannot be executed here")
    esc = next(line for line in CODE.splitlines() if line.startswith("const esc="))
    backoff = next(line for line in CODE.splitlines() if line.startswith("const PCHAT_BACKOFF_MS="))
    state = CODE[CODE.index("let _pc="):]
    state = state[:state.index(";") + 1]
    names = ["curProject", "curProduct", "curLogs", "curBoard", *_product_chat_functions()]
    program = "\n".join([_PRELUDE, esc, backoff, state, board,
                         *(_function(n) for n in names if n not in ("bootProduct",
                                                                    "renderProduct",
                                                                    "prodLook")),
                         f"location.pathname={json.dumps(pathname)};",
                         "console.log(JSON.stringify((()=>{" + script + "})()))"])
    done = subprocess.run([node, "-e", program], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-1500:]
    return json.loads(done.stdout)


def test_on_card_42s_page_the_context_names_card_42():
    got = _run("_pc.project='books';return pageContext()", pathname="/p/books/card/42")
    assert got == {"page": "card", "project": "books", "card": "42"}


def test_the_card_open_in_the_boards_drawer_is_the_one_the_person_is_looking_at():
    got = _run("_pc.project='books';return pageContext()", pathname="/p/books/board",
               board="let _bd={project:'books',card:'7'};")
    assert got == {"page": "card", "project": "books", "card": "7"}


def test_a_page_of_another_project_names_no_card_to_this_chat():
    got = _run("_pc.project='shop';return pageContext()", pathname="/p/books/card/42")
    assert got == {"page": "board"}


def test_the_catch_up_keeps_the_proposal_waiting_and_the_reading_rows_reports():
    """A history frame repaints from the store; what the store cannot repaint stays — the report of
    a reading row, and the buttons of a proposal waiting for this person's answer."""
    got = _run("""nodes['#prodThread']=node();
      pchatFrame({kind:'reply',text:'Registro isto?',type:'answer',
                  options:{token:'tok-1',approve:'Registrar',reject:'Não'}});
      _pc.items.push({who:'agent',label:'Triage',text:'three cards wait',local:true});
      pchatFrame({kind:'history',turns:[{role:'agent',actor:'Nina',text:'Registro isto?'}]});
      return {html:nodes['#prodThread'].innerHTML,staged:_pc.staged}""",
               pathname="/product/books")
    assert got["staged"]["token"] == "tok-1"
    assert "Registrar" in got["html"], "the repaint took the sign-off buttons away"
    assert "three cards wait" in got["html"], "the reading row's report vanished"


def test_the_page_asks_for_the_room_or_its_own_and_never_names_a_key():
    got = _run("""const s={readyState:1,send(x){sent.push(JSON.parse(x))}};
      _pc.sock=s;_pc.project='books';_pc.room=true;pchatSubscribe();
      _pc.room=false;pchatSubscribe();return sent""", pathname="/product/books")
    assert got == [{"kind": "subscribe", "project": "books", "room": True},
                   {"kind": "subscribe", "project": "books", "room": False}]


def test_a_message_is_shown_at_once_and_marked_by_its_own_acknowledgement():
    got = _run("""nodes['#prodThread']=node();
      _pc.sock={readyState:1,send(x){sent.push(JSON.parse(x))}};_pc.live=true;_pc.project='books';
      pchatSay('olá');const id=sent[0].id;
      const before=nodes['#prodThread'].innerHTML;
      pchatFrame({kind:'said',id,text:'olá',speaker:'ana',mine:true});
      pchatFrame({kind:'ack',id,ok:true,text:'recebi sua mensagem'});
      return {sent,before,after:nodes['#prodThread'].innerHTML,items:_pc.items.length}""",
               pathname="/product/books")
    assert got["sent"][0]["kind"] == "say" and got["sent"][0]["context"] == {
        "page": "product", "project": "books"}
    assert "sending…" in got["before"] and "recebi sua mensagem" in got["after"]
    assert got["items"] == 1, "the page's own message was drawn twice"

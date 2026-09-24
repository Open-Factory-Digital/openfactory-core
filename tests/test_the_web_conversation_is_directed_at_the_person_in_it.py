"""On the web, everybody shared one conversation with the product role (#33, slice 3).

The `say` activity keyed the transcript on `inp.thread or name`, and the panel sent no thread —
so the key was the PROJECT'S NAME: A and B wrote into one conversation and the role read them as
one person. Slack hid this (a thread comes free). Worse, the panel's free-text box reaches
`product_ask`, whose worker turn handed the role the question ALONE — no transcript read, none
written — so on the web every message was turn one, for everybody.

Now the actor carries the conversation it is in: `person:<id>` for a subject either identity row
named, `visitor:<cookie>` for a browser nobody has identified yet, and a product row uses it when
the caller passed no thread. The ask turn records the person's message on arrival, hands the role
the earlier turns of THAT conversation, and records the reply — the three moves the say turn
already made. Reads stay ungated; agreeing to anything still needs a known person.

SINCE #266 SLICE 2 the ask turn and the say turn are ONE turn — the engine, behind the one row
`product_say` — so what is pinned below is pinned on that turn. SINCE SLICE 3 the row sends the
message through the door onto its conversation, and the worker's turn is
`activities._conversation_turn`; the row is where an empty thread becomes the project's room.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import actions
from openfactory.actions.base import Actor
from openfactory.memory.transcript import Turn

ROOT = Path(__file__).resolve().parent.parent


def _project():
    return SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO",
                                                                 docs_repo="acme/docs"))


@pytest.fixture
def dispatched(monkeypatch):
    """What a catalog row hands the engine, captured where it lands — for the conversation's row,
    the message the door enqueues on its conversation (#266 slice 3), answered at once."""
    from openfactory.actions import catalog

    seen: dict = {}

    class _Engine:
        async def start_workflow(self, name, inp, *, start_signal_args=(), **_kw):
            seen["workflow"], seen["input"] = name, start_signal_args[0]

        def get_workflow_handle(self, _wid):
            class _Handle:
                async def query(self, _name, message_id, **_kw):
                    return {"state": "answered", "replies": [
                        {"text": "resposta", "kind": "answer", "in_reply_to": message_id}]}
            return _Handle()

    async def _connected():
        return _Engine(), None

    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_k: (object(), _project(), None))
    return seen


class Memory:
    """The transcript in memory, keyed the way the store keys it: by thread."""

    def __init__(self) -> None:
        self.turns: dict[str, list[Turn]] = {}
        self.n = 0

    def record(self, project, *, thread, role, text, actor="", channel=""):
        self.n += 1
        ts = f"t{self.n}"
        self.turns.setdefault(thread, []).append(Turn(role=role, text=text, ts=ts, actor=actor))
        return ts

    def recent(self, project, *, thread, channel="", budget=0):
        return list(self.turns.get(thread, []))


class Role:
    """A product module that remembers what conversation it was handed — with the few verbs the
    turn reaches before the answer (nothing awaits a yes or a "did it work?", the base reads)."""

    handed: list[str] = []
    reply = SimpleNamespace(ok=True, text="resposta", is_request=False)

    def __init__(self, project, via=""):
        pass

    def settle_acceptance(self, text):
        return None

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def close_decisions_answered(self, *, channel=""):
        return 0

    def answer(self, question, *, context="", conversation="", pending=""):
        Role.handed.append(conversation)
        return Role.reply


@pytest.fixture
def worker(monkeypatch):
    from openfactory.memory import transcript
    from openfactory.product import module as product_module

    memory = Memory()
    monkeypatch.setattr(transcript, "record", memory.record)
    monkeypatch.setattr(transcript, "recent", memory.recent)
    monkeypatch.setattr(product_module, "ProductModule", Role)
    Role.handed = []
    Role.reply = SimpleNamespace(ok=True, text="resposta", is_request=False)
    return memory


# ── the rows carry the actor's conversation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_row_carries_the_actor_s_conversation_when_no_thread_is_named(dispatched):
    """The one row (`product_say`, which `product_ask` became in #266 slice 2) — the panel's box
    reaches it now, so this is the door the actor's conversation has to travel through."""
    who = Actor(id="ana", via="panel", conversation="person:ana")

    out = await actions.perform("product_say", by=who, project="acme", message="e o segundo?")
    assert out.ok, out.message
    assert dispatched["workflow"] == "ConversationWorkflow"
    assert dispatched["input"].conversation == "person:ana"
    assert dispatched["input"].speaker == "ana"

    await actions.perform("product_say", by=who, project="acme", message="e o segundo?",
                          thread="T1")
    assert dispatched["input"].conversation == "T1", "a thread the caller names wins"

    await actions.perform("product_say", by=Actor(id="cli", via="cli"), project="acme",
                          message="e o segundo?")
    assert dispatched["input"].conversation == "acme", (
        "a transport that keys nothing lands in the project's room")


def test_the_row_declares_the_thread_and_the_input_carries_it():
    from openfactory.runtime.temporal.io import Arrival

    assert "thread" in actions.CATALOG["product_say"].optional
    assert Arrival(id="m1", project="acme", conversation="person:ana").conversation == \
        "person:ana"
    assert Actor(id="x").conversation == "", "every actor that predates this keys nothing"


# ── the panel resolves the conversation from the subject ────────────────────────────────────────

def _request(*, cookie: str = "", bearer: str = ""):
    from starlette.requests import Request

    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/act/product_say",
                    "query_string": b"", "headers": headers})


def test_the_panel_keys_a_known_person_by_id_and_a_stranger_by_the_visitor_cookie(monkeypatch):
    from openfactory.api import app as panel

    for name in ("OPENFACTORY_IDENTITY", "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PRODUCT_TOKEN",
                 "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "s3cret-a:ana@acme.example:Ana")
    visitor = "a1b2c3d4e5f60718"

    known = panel._actor(_request(cookie=f"openfactory_visitor={visitor}", bearer="s3cret-a"))
    assert known.conversation == "person:ana@acme.example", "a known person is their own key"

    stranger = panel._actor(_request(cookie=f"openfactory_visitor={visitor}"))
    assert stranger.id == "panel" and stranger.conversation == f"visitor:{visitor}"

    assert panel._actor(_request()).conversation == "", "no cookie: the project-wide one"
    assert panel._actor(_request(cookie="openfactory_visitor=../x")).conversation == ""
    assert panel._actor(_request(cookie="openfactory_visitor=short")).conversation == ""


def test_the_page_mints_the_visitor_cookie_at_boot():
    html = (ROOT / "openfactory/api/panel.html").read_text()

    assert "ensureVisitor();" in html
    assert 'document.cookie="openfactory_visitor="+id+"; path=/; SameSite=Lax' in html
    assert "crypto.getRandomValues" in html, "random, not a counter"


# ── the worker remembers the conversation it is handed ──────────────────────────────────────────

def _turn(message: str, asked_by: str, thread: str):
    """The worker's side of the one row: the message, through the turn engine — in the
    conversation the row resolves, which for no thread is the project's room."""
    from openfactory.runtime.temporal.activities import _conversation_turn
    from openfactory.runtime.temporal.io import TurnInput

    return _conversation_turn(_project(), TurnInput(
        product="repo:acme/docs", project="acme", conversation=thread or "acme",
        speaker=asked_by, text=message, id=f"{asked_by}:{message}", via="panel"))


def test_the_turn_records_the_person_hands_the_role_the_thread_and_records_the_reply(worker):
    _turn("quero um relatório mensal", "ana", "person:ana")
    assert Role.handed == [""], "turn one: nothing came before"
    assert [(t.role, t.actor) for t in worker.turns["person:ana"]] == [("person", "ana"),
                                                                       ("agent", "")]

    _turn("e o segundo?", "ana", "person:ana")
    assert "quero um relatório mensal" in Role.handed[1] and "resposta" in Role.handed[1]
    assert "e o segundo?" not in Role.handed[1], "the question being asked is not history"


def test_two_people_on_the_web_are_two_conversations(worker):
    _turn("quero um relatório mensal", "ana", "person:ana")
    _turn("e o segundo?", "bruno", "person:bruno")

    assert Role.handed[1] == "", "Bruno's turn one sees nothing of Ana's"
    assert set(worker.turns) == {"person:ana", "person:bruno"}


def test_no_thread_is_the_project_wide_conversation_and_what_she_could_not_answer_is_SAID(worker):
    """No thread is the project's room, as it always was. And a turn the role could not answer is
    answered with the client's sentence for that, recorded as what she said — the conversation's
    rule, pinned in `test_the_conversation_is_pinned.py`. The panel's old ask turn recorded nothing
    and handed the row a refusal instead; that path is gone on purpose (#266 slice 2): one turn,
    one answer to the same message on every surface."""
    from openfactory.product.voice import unavailable

    _turn("olá", "cli", "")
    assert list(worker.turns) == ["acme"], "keyed by the project, as the say turn keys it"

    Role.reply = SimpleNamespace(ok=False, text="", error="no corpus", is_request=False)
    replies = _turn("olá de novo", "cli", "person:ana")
    assert [t.role for t in worker.turns["person:ana"]] == ["person", "agent"]
    assert replies[-1].text == unavailable(language=None), replies


def test_the_client_s_document_says_so():
    text = (ROOT / "docs/reference/product-role.md").read_text()
    assert "own conversation" in text and "cookie" in text

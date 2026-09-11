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
    return SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO"))


@pytest.fixture
def dispatched(monkeypatch):
    """The workflow input a catalog row hands the engine, captured where it lands."""
    from openfactory.actions import catalog

    seen: dict = {}

    class _Engine:
        async def execute_workflow(self, name, inp, **_kw):
            seen["workflow"], seen["input"] = name, inp
            return {"ok": True, "outcome": "done", "message": "feito",
                    "answer": {"ok": True, "text": "resposta"}}

    async def _connected():
        return _Engine(), None

    async def _no_intent(*_a, **_k):
        return None

    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_k: (object(), _project(), None))
    monkeypatch.setattr(catalog, "_say_as_an_intent", _no_intent)
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
    """A product module that remembers what conversation it was handed."""

    handed: list[str] = []
    reply = SimpleNamespace(ok=True, text="resposta", is_request=False)

    def __init__(self, project, via=""):
        pass

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
async def test_the_ask_row_carries_the_actor_s_conversation_when_no_thread_is_named(dispatched):
    who = Actor(id="ana", via="panel", conversation="person:ana")

    out = await actions.perform("product_ask", by=who, project="acme", question="e o segundo?")
    assert out.ok, out.message
    assert dispatched["workflow"] == "ProductAskWorkflow"
    assert dispatched["input"].thread == "person:ana"
    assert dispatched["input"].asked_by == "ana"

    await actions.perform("product_ask", by=who, project="acme", question="e o segundo?",
                          thread="T1")
    assert dispatched["input"].thread == "T1", "a thread the caller names wins"

    await actions.perform("product_ask", by=Actor(id="cli", via="cli"), project="acme",
                          question="e o segundo?")
    assert dispatched["input"].thread == "", "a transport that keys nothing sends nothing"


@pytest.mark.asyncio
async def test_the_say_row_carries_it_too(dispatched):
    who = Actor(id="ana", via="panel", conversation="person:ana")

    out = await actions.perform("product_say", by=who, project="acme", message="e o segundo?")
    assert out.ok, out.message
    assert dispatched["workflow"] == "ProductSayWorkflow"
    assert dispatched["input"].thread == "person:ana"

    await actions.perform("product_say", by=who, project="acme", message="x", thread="T1")
    assert dispatched["input"].thread == "T1"


def test_the_ask_row_declares_the_thread_and_the_input_carries_it():
    from openfactory.runtime.temporal.io import ProductAskInput

    assert "thread" in actions.CATALOG["product_ask"].optional
    assert ProductAskInput(project="acme", question="q").thread == ""
    assert Actor(id="x").conversation == "", "every actor that predates this keys nothing"


# ── the panel resolves the conversation from the subject ────────────────────────────────────────

def _request(*, cookie: str = "", bearer: str = ""):
    from starlette.requests import Request

    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/act/product_ask",
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

def test_the_ask_turn_records_the_person_hands_the_role_the_thread_and_records_the_reply(worker):
    from openfactory.runtime.temporal.activities import _product_draft

    _product_draft(_project(), "quero um relatório mensal", "ana", "person:ana")
    assert Role.handed == [""], "turn one: nothing came before"
    assert [(t.role, t.actor) for t in worker.turns["person:ana"]] == [("person", "ana"),
                                                                       ("agent", "")]

    _product_draft(_project(), "e o segundo?", "ana", "person:ana")
    assert "quero um relatório mensal" in Role.handed[1] and "resposta" in Role.handed[1]
    assert "e o segundo?" not in Role.handed[1], "the question being asked is not history"


def test_two_people_on_the_web_are_two_conversations(worker):
    from openfactory.runtime.temporal.activities import _product_draft

    _product_draft(_project(), "quero um relatório mensal", "ana", "person:ana")
    _product_draft(_project(), "e o segundo?", "bruno", "person:bruno")

    assert Role.handed[1] == "", "Bruno's turn one sees nothing of Ana's"
    assert set(worker.turns) == {"person:ana", "person:bruno"}


def test_no_thread_is_the_project_wide_conversation_and_a_refusal_is_not_recorded(worker):
    from openfactory.runtime.temporal.activities import _product_draft

    _product_draft(_project(), "olá", "cli", "")
    assert list(worker.turns) == ["acme"], "keyed by the project, as the say turn keys it"

    Role.reply = SimpleNamespace(ok=False, text="", error="no corpus", is_request=False)
    _product_draft(_project(), "olá de novo", "cli", "person:ana")
    assert [t.role for t in worker.turns["person:ana"]] == ["person"], \
        "a refusal is not the role's reply, and is not recorded as one"


def test_the_client_s_document_says_so():
    text = (ROOT / "docs/reference/product-role.md").read_text()
    assert "own conversation" in text and "cookie" in text

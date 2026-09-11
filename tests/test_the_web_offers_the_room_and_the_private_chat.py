"""On the web, the private conversation's key was a free parameter (#33, slice 4).

Slice 3 keyed the web conversation by person — `person:<id>`, `visitor:<cookie>` — and promised
that nobody else could reach a private draft, *"not by a new rule, by the key"*. The key travelled
as `thread`, an ordinary optional parameter of `product_say` and `product_ask`, and a caller who
named it entered that conversation: measured on `bf9752d`, both rows handed the engine
`thread='person:ana'` for an actor whose own conversation was `person:bruno`. `staging.consume`
checks the DRAFT's identity, never who answers — the room's rule, kept on purpose — so Bruno's
"sim" would have consumed what Ana had staged, in her name.

Now one rule resolves the key for `ask`, `say` and the new read `product_thread`
(`product/conversation.py::key_for`): a named thread wins — a room, or one's own private key —
none means one's own, and somebody else's private key is refused before the engine is asked. The
surface mints its keys with the prefixes the rule refuses to take. And the panel OFFERS the two
conversations the keying made possible — the project's room and "just me" — reading each from the
store the worker records into, so the room shows what the others said and a reload shows what the
role still remembers.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory import actions
from openfactory.actions import catalog
from openfactory.actions.base import DENIED, PRODUCT, Actor
from openfactory.memory.transcript import Turn
from openfactory.product.conversation import PERSON, VISITOR, is_private, key_for

ROOT = Path(__file__).resolve().parent.parent
PANEL = (ROOT / "openfactory/api/panel.html").read_text()
APP = (ROOT / "openfactory/api/app.py").read_text()


def _project():
    return SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO"))


def _bruno() -> Actor:
    return Actor(id="bruno", via="panel", conversation="person:bruno")


@pytest.fixture
def dispatched(monkeypatch):
    """The workflow input a catalog row hands the engine — or nothing, when it never got there."""
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


# --- the rule ------------------------------------------------------------------------------

def test_no_name_is_the_callers_own_conversation():
    assert key_for(named="", own="person:ana") == "person:ana"
    assert key_for(named="  ", own="visitor:abcdefgh") == "visitor:abcdefgh"
    assert key_for(named="", own="") == "", "a CLI actor keys nothing — the worker resolves the room"


def test_the_projects_room_is_a_name_anybody_may_say():
    assert key_for(named="acme", own="person:bruno") == "acme"
    assert key_for(named="acme", own="") == "acme"


@pytest.mark.parametrize("own", ["person:ana", "visitor:abcdefgh"])
def test_ones_own_private_key_may_be_spelled_out(own):
    assert key_for(named=own, own=own) == own


@pytest.mark.parametrize("named", ["person:ana", "visitor:abcdefgh"])
@pytest.mark.parametrize("own", ["person:bruno", "visitor:zzzzzzzz", ""])
def test_somebody_elses_private_key_is_refused(named, own):
    assert key_for(named=named, own=own) is None, (
        f"{own or 'the CLI'} named {named} and was let in — the slice-3 promise was a parameter")


def test_the_surface_mints_with_the_prefixes_the_rule_refuses():
    from openfactory.api.app import VISITOR_COOKIE, _conversation_of
    known = _conversation_of(SimpleNamespace(cookies={}), SimpleNamespace(known=True, id="ana"))
    assert known == f"{PERSON}ana" and is_private(known)
    visitor = _conversation_of(SimpleNamespace(cookies={VISITOR_COOKIE: "abcdefgh12"}),
                               SimpleNamespace(known=False, id=""))
    assert visitor == f"{VISITOR}abcdefgh12" and is_private(visitor)
    assert not is_private("acme")


def test_the_prefixes_have_one_definition():
    """A surface that spelled its key differently would mint rooms by accident."""
    assert 'f"person:' not in APP and 'f"visitor:' not in APP, (
        "app.py mints a private key with a literal instead of product/conversation.py's prefixes")


# --- the rows ------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("row,words", [("product_say", {"message": "sim"}),
                                       ("product_ask", {"question": "sim"})])
async def test_a_turn_refuses_to_enter_another_persons_conversation(dispatched, row, words):
    out = await actions.perform(row, by=_bruno(), project="acme", thread="person:ana", **words)
    assert not out.ok and out.code == DENIED, (out.ok, out.code, out.message)
    assert "input" not in dispatched, "refused AFTER the engine recorded the turn under her key"
    assert "one person's alone" in out.message


@pytest.mark.asyncio
@pytest.mark.parametrize("thread,lands", [("acme", "acme"), ("person:bruno", "person:bruno"),
                                          ("", "person:bruno")])
async def test_the_room_and_ones_own_still_go_through(dispatched, thread, lands):
    out = await actions.perform("product_say", by=_bruno(), project="acme", message="oi",
                                thread=thread)
    assert out.ok, out.message
    assert dispatched["input"].thread == lands


@pytest.mark.asyncio
async def test_ask_and_say_resolve_the_key_the_same_way(dispatched):
    """One helper, both rows. A rule that lived in each would drift, and a drifted key is the
    slice-3 defect again on whichever row drifted."""
    for row, words in (("product_say", {"message": "oi"}), ("product_ask", {"question": "oi"})):
        dispatched.clear()
        out = await actions.perform(row, by=_bruno(), project="acme", thread="person:bruno",
                                    **words)
        assert out.ok and dispatched["input"].thread == "person:bruno", row
    src = (ROOT / "openfactory/actions/catalog.py").read_text()
    assert src.count("_conversation_key(thread, by)") >= 3, "a row resolves the key on its own"


@pytest.fixture
def remembered(monkeypatch):
    """A transcript with a room and two private conversations, behind `transcript.recent`."""
    from openfactory.memory import transcript
    store = {
        "acme": [Turn(role="person", text="precisamos do fechamento", ts="t1", actor="ana"),
                 Turn(role="agent", text="anotado", ts="t2"),
                 Turn(role="person", text="e o segundo?", ts="t3", actor="bruno")],
        "person:bruno": [Turn(role="person", text="só eu", ts="t4", actor="bruno")],
        "person:ana": [Turn(role="person", text="segredo", ts="t5", actor="ana")],
    }
    asked: list = []

    def recent(project, *, thread, channel="", budget=0):
        asked.append(thread)
        return list(store.get(thread, []))

    monkeypatch.setattr(transcript, "recent", recent)
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_k: (object(), _project(), None))
    return asked


@pytest.mark.asyncio
async def test_product_thread_reads_the_room(remembered):
    out = await actions.perform("product_thread", by=_bruno(), project="acme", thread="acme")
    assert out.ok, out.message
    assert remembered == ["acme"]
    assert out.data["thread"] == "acme" and out.data["private"] is False
    assert [t["actor"] for t in out.data["turns"]] == ["ana", "Ana PO", "bruno"]
    assert [t["role"] for t in out.data["turns"]] == ["person", "agent", "person"]
    assert "ana: precisamos do fechamento" in out.message and "Ana PO: anotado" in out.message


@pytest.mark.asyncio
async def test_product_thread_defaults_to_ones_own(remembered):
    out = await actions.perform("product_thread", by=_bruno(), project="acme")
    assert out.ok and remembered == ["person:bruno"]
    assert out.data["private"] is True
    assert [t["text"] for t in out.data["turns"]] == ["só eu"]


@pytest.mark.asyncio
async def test_product_thread_never_hands_over_another_persons_conversation(remembered):
    out = await actions.perform("product_thread", by=_bruno(), project="acme",
                                thread="person:ana")
    assert not out.ok and out.code == DENIED, (out.ok, out.code)
    assert remembered == [], "the store was asked before the name was judged"


@pytest.mark.asyncio
async def test_a_cli_actor_reads_the_room_it_writes_into(remembered):
    """The CLI keys nothing and the worker resolves that to the project's name. The read must
    resolve it the same way, or the CLI reads an empty conversation it has been writing into."""
    out = await actions.perform("product_thread", by=Actor(id="cli", via="cli"), project="acme")
    assert out.ok and remembered == ["acme"] and out.data["thread"] == "acme"


@pytest.mark.asyncio
async def test_an_empty_conversation_still_answers(remembered):
    out = await actions.perform("product_thread", by=Actor(id="cli", via="cli"), project="acme",
                                thread="a-room-nobody-used")
    assert out.ok and out.data["turns"] == [] and "nothing was said here yet" in out.message


def test_the_read_is_registered_as_one():
    spec = actions.spec("product_thread")
    assert spec.scope == PRODUCT and spec.needs_admin is False
    assert tuple(spec.required) == ("project",) and tuple(spec.optional) == ("thread",)


# --- the page ------------------------------------------------------------------------------

def _js(fn: str) -> str:
    """The body of one function of the panel's script, up to its closing brace at column 0."""
    start = PANEL.index(f"function {fn}(")
    return PANEL[start:PANEL.index("\n}", start) + 2]


def test_the_panel_offers_both_conversations():
    for needle in ('id="scopeRoom"', 'id="scopeMine"', "setScope(true)", "setScope(false)"):
        assert needle in PANEL, needle


def test_the_room_is_the_projects_name_and_just_me_names_nothing():
    """The worker resolves an empty thread to the project's name, so the room IS that name; a
    private turn names nothing and the server keys it by who the browser is — a key the page never
    sees and cannot forge for somebody else."""
    line = PANEL[PANEL.index("function _scopeParam("):]
    line = line[:line.index("\n")]
    assert "_prod.room?{thread:_prod.project}:{}" in line, line
    assert "_scopeParam()" in _js("askProduct"), "the turn is keyed on its own"
    assert "_scopeParam()" in _js("loadThread"), "the read is keyed on its own"


def test_the_page_reads_the_conversation_from_the_store():
    assert 'act("product_thread"' in _js("loadThread")
    assert "loadThread()" in _js("bootProduct"), "a reload forgets what the role remembers"
    assert "loadThread()" in _js("setScope"), "switching conversations keeps the other's lines"
    assert "watchRoom()" in _js("bootProduct") and "if(_prod.room)loadThread()" in _js("watchRoom"), (
        "the room is a mailbox: what the others said never arrives")


def test_a_draft_awaiting_signoff_is_not_repainted_away():
    assert "_prod.draft)return" in _js("loadThread"), (
        "a repaint from the store drops the sign-off buttons while the person is reading the draft")


def test_the_reading_rows_reports_survive_a_repaint():
    assert _js("prodLook").count("local:true") == 2, "a triage report vanishes at the next tick"
    assert "filter(m=>m.local)" in _js("loadThread")


def test_the_choice_is_remembered_per_browser():
    assert "of.prod.room" in _js("setScope") and "of.prod.room" in _js("bootProduct")

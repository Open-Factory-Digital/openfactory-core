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
    return SimpleNamespace(name="acme", product=SimpleNamespace(agent_name="Ana PO",
                                                                 docs_repo="acme/docs"))


def _bruno() -> Actor:
    return Actor(id="bruno", via="panel", conversation="person:bruno")


@pytest.fixture
def dispatched(monkeypatch):
    """What a catalog row hands the engine — or nothing, when it never got there. For the
    conversation's row that is the message the door enqueues on its conversation (#266 slice 3),
    answered at once."""
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


# --- the rule ------------------------------------------------------------------------------

def test_no_name_is_the_callers_own_conversation():
    assert key_for(named="", own="person:ana") == "person:ana"
    assert key_for(named="  ", own="visitor:abcdefgh") == "visitor:abcdefgh"
    assert key_for(named="", own="") == "", "a CLI actor keys nothing — the row resolves the room"


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
@pytest.mark.parametrize("row,words", [("product_say", {"message": "sim"})])
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
    assert dispatched["input"].conversation == lands


@pytest.mark.asyncio
async def test_every_row_that_names_a_conversation_resolves_the_key_the_same_way(dispatched):
    """One helper, every row. A rule that lived in each would drift, and a drifted key is the
    slice-3 defect again on whichever row drifted. `ask` and `say` were two of those rows until
    #266 slice 2 made them one; the turn, the read and the cases still share the helper."""
    out = await actions.perform("product_say", by=_bruno(), project="acme",
                                thread="person:bruno", message="oi")
    assert out.ok and dispatched["input"].conversation == "person:bruno"
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
    """The room IS the project's name; a private conversation is named by nobody on the page — the
    server keys it by who the browser is, a key the page never sees and cannot forge for somebody
    else. SINCE #266 SLICE 5 the page says which over the product chat's socket (`room`), and the
    turn and the read cannot land in different conversations because they are one subscription."""
    sub = _js("pchatSubscribe")
    assert 'kind:"subscribe",project:_pc.project,room:_pc.room' in sub, sub
    assert "thread" not in sub and "person:" not in sub, "the page names a conversation key"
    assert "pchatSay(" in _js("askProduct"), "the turn goes somewhere the subscription is not"


def test_the_page_reads_the_conversation_from_the_store():
    """The store is the conversation and the page a view of it — handed on every subscription
    (the socket's `history` frame, read from the transcript), and live after that: what the others
    said in the room arrives as it is said, without a clock (#266 slice 5)."""
    frame = _js("pchatFrame")
    assert 'm.kind==="history"' in frame and 'm.kind==="said"' in frame, (
        "the room is a mailbox: what the others said never arrives")
    assert "pchatUse(" in _js("renderProduct"), "a reload forgets what the role remembers"
    assert "pchatSubscribe()" in _js("setScope"), "switching conversations keeps the other's lines"


def test_a_draft_awaiting_signoff_is_not_repainted_away():
    # `_prod.staged` since #266 slice 2: what waits is a proposal the conversation STAGED, answered
    # by its buttons or by a typed yes — no longer a draft held in the page for a propose button.
    # `_pc.staged` since slice 5: the repaint from the store is the socket's catch-up, and it
    # leaves the waiting proposal and its buttons alone
    history = _js("pchatFrame").split('m.kind==="history"')[1].split("else if")[0]
    assert "_pc.staged=" not in history.replace(" ", ""), (
        "a repaint from the store drops the sign-off buttons while the person is reading the draft")
    assert "pchatStagedAlone()" in _js("paintThread")


def test_the_reading_rows_reports_survive_a_repaint():
    assert _js("prodLook").count("local:true") == 2, "a triage report vanishes at the next tick"
    assert "filter(i=>i.local||i.pending)" in _js("pchatFrame")


def test_the_choice_is_remembered_per_browser():
    assert "of.prod.room" in _js("setScope") and "of.prod.room" in _js("bootProduct")

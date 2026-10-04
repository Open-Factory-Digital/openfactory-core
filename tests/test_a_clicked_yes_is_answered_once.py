"""A clicked yes is answered once, however many times the page catches up (#402).

WHAT WAS MEASURED. A person approved a staged proposal on the panel and the private conversation
showed the role's answer twice — two identical bubbles. The transcript held ONE agent row for it,
and that row was the only agent row with no `in_reply_to`: the click recorded its "sim" with no id
and its answer as the reply to nothing (`confirm.answer_staged`). The page had drawn that answer
itself the moment the click returned (`answerStaged`, `local`), and its catch-up keeps every
`local` item — so after a reconnect the answer came back from the transcript AND stayed from the
page. Nothing on either side said the two were the same turn: the history the page is handed
dropped every turn's id.

THE RULE THIS FILE HOLDS: turns are reconciled by IDENTITY — which message a line is, which message
an answer answers — end to end, and never by the words. A person may get the same sentence twice
on purpose ("Registrado." to two proposals), and a text match would delete the second.

  1. the page — the click mints an id, the bubble remembers it, the catch-up drops what the store
     now holds by that id and keeps everything else;
  2. the gate — the click's two rows are recorded as a pair, with the page's id or a minted one;
  3. the hops — the row validates and carries the id, the activity hands it to the gate;
  4. the other places the class lived — `door.tell` records what its reply answers, the history
     read hands the ids to the page, and the socket's echo matches by identity first.
"""

from __future__ import annotations

import pytest

from openfactory.product import confirm as executor
from tests.test_the_confirmation_executor import (
    _actor,
    _Engine,
    _Module,
    _project,
    _returns,
    _stage,
)
from tests.test_the_panel_is_a_chat import _run


@pytest.fixture(autouse=True)
def _clean():
    import openfactory.product.channel as pc

    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ── 1. the page ─────────────────────────────────────────────────────────────────────────────────

_CLICKED = """nodes['#prodThread']=node();
  globalThis.act=async(n,p)=>{sent.push({n,p});return {ok:true,message:'Registrado.'}};
  _pc.project='books';
  pchatFrame({kind:'reply',text:'Registro este defeito?',type:'answer',
              options:{token:'k|fp',approve:'Sim',reject:'Não'}});
  await answerStaged('approve');
  const id=sent[0].p.message_id;
"""


def test_the_answer_to_a_click_is_drawn_ONCE_after_the_page_catches_up():
    """THE MEASURED DEFECT. The click returns, the page draws the answer; the socket reconnects and
    the page is handed the transcript, which holds that answer as the reply to the click. One
    bubble — it was two."""
    got = _run(_CLICKED + """
      pchatFrame({kind:'history',turns:[
        {role:'agent',actor:'Nina',text:'Registro este defeito?'},
        {role:'person',actor:'ana',text:'sim',mine:true,id},
        {role:'agent',actor:'Nina',text:'Registrado.',in_reply_to:id}]});
      return {n:_pc.items.filter(i=>i.text==='Registrado.').length,
              html:nodes['#prodThread'].innerHTML}""", pathname="/product/books")

    assert got["n"] == 1, f"the click's answer was drawn {got['n']} times after the catch-up"
    assert got["html"].count("Registrado.") == 1, got["html"]


def test_the_click_sends_an_id_the_row_accepts():
    """The id is the page's, and it has to survive the row's check — an id the row refuses would
    turn every click into a refusal."""
    from openfactory.actions.catalog import _MESSAGE_ID

    got = _run(_CLICKED + "return {id, answers:_pc.items[_pc.items.length-1].answers}",
               pathname="/product/books")

    assert got["id"] and _MESSAGE_ID.match(got["id"]), got
    assert got["answers"] == got["id"], "the bubble does not remember the click it answers"


def test_the_click_s_answer_STAYS_while_the_transcript_does_not_hold_it_yet():
    """The control. A catch-up read before the answer was recorded — or one that could not record
    it — must not take the only copy the person has."""
    got = _run(_CLICKED + """
      pchatFrame({kind:'history',turns:[{role:'agent',actor:'Nina',
                                         text:'Registro este defeito?'}]});
      return _pc.items.filter(i=>i.text==='Registrado.').length""", pathname="/product/books")

    assert got == 1, "the catch-up dropped a click answer the transcript does not hold"


def test_two_answers_that_SAY_the_same_thing_are_both_kept():
    """NOT BY THE WORDS. The same "Registrado." to two proposals is two answers; the one drawn by
    the page for a third click, which the history has not answered yet, is a third."""
    got = _run(_CLICKED + """
      pchatFrame({kind:'history',turns:[
        {role:'person',actor:'ana',text:'sim',mine:true,id:'click-one-000'},
        {role:'agent',actor:'Nina',text:'Registrado.',in_reply_to:'click-one-000'},
        {role:'person',actor:'ana',text:'sim',mine:true,id:'click-two-000'},
        {role:'agent',actor:'Nina',text:'Registrado.',in_reply_to:'click-two-000'}]});
      return _pc.items.filter(i=>i.text==='Registrado.').length""", pathname="/product/books")

    assert got == 3, f"answers were merged by their words: {got} of 3 left"


def test_a_message_still_on_its_way_up_is_drawn_once_when_the_history_holds_it():
    """THE SAME CLASS, ON THE PERSON'S SIDE. A message the page drew as `pending` whose row lands
    in the catch-up was kept beside that row — the person's own words, twice."""
    got = _run("""nodes['#prodThread']=node();
      _pc.sock={readyState:1,send(x){sent.push(JSON.parse(x))}};_pc.live=true;_pc.project='books';
      pchatSay('olá');const id=sent[0].id;
      crypto.getRandomValues=b=>{for(let i=0;i<b.length;i++)b[i]=200-i;return b};
      pchatSay('tudo bem?');
      pchatFrame({kind:'history',turns:[{role:'person',actor:'ana',text:'olá',mine:true,id}]});
      return {hello:_pc.items.filter(i=>i.text==='olá').length,
              other:_pc.items.filter(i=>i.text==='tudo bem?').length}""",
               pathname="/product/books")

    assert got["hello"] == 1, "a message the transcript holds was kept as pending beside it"
    assert got["other"] == 1, "a message the transcript does not hold yet was dropped"


# ── 2. the gate ─────────────────────────────────────────────────────────────────────────────────

def _recorded(monkeypatch) -> list[dict]:
    from openfactory.memory import transcript

    rows: list[dict] = []
    monkeypatch.setattr(transcript, "record", lambda _p, **kw: rows.append(kw) or "ts")
    return rows


def test_the_click_s_two_rows_are_recorded_as_a_pair_under_the_page_s_id(monkeypatch):
    rows = _recorded(monkeypatch)
    token, _ = _stage()

    code, sentence = executor.answer_staged(_project(), token=token, approved=True, user="U1",
                                            module=_Module(), message_id="click-0123456789")

    assert code == "done" and sentence
    person = [r for r in rows if r["role"] == "person"]
    agent = [r for r in rows if r["role"] == "agent"]
    assert [r.get("message_id") for r in person] == ["click-0123456789"], person
    assert [r.get("in_reply_to") for r in agent] == ["click-0123456789"], (
        "the click's answer is recorded as the reply to nothing — the page cannot find it")


def test_a_click_with_no_id_still_records_a_pair(monkeypatch):
    """A chat add-on's button and the CLI send none: the gate mints one, so the record still says
    which answer answers which message."""
    rows = _recorded(monkeypatch)
    token, _ = _stage()

    executor.answer_staged(_project(), token=token, approved=True, user="U1", module=_Module())

    (person,) = [r for r in rows if r["role"] == "person"]
    (agent,) = [r for r in rows if r["role"] == "agent"]
    assert person.get("message_id"), "the click's line was recorded with no id"
    assert agent.get("in_reply_to") == person["message_id"], (person, agent)


# ── 3. the hops ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _resolvable(monkeypatch):
    from openfactory.actions import catalog

    project = _project()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_kw: (object(), project, None))
    return project


@pytest.mark.asyncio
async def test_the_row_carries_the_click_s_id_to_the_worker(_resolvable, monkeypatch):
    from openfactory.actions import catalog

    engine = _Engine({"outcome": "done", "message": "Registrado."})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token="C0PROD|abc", answer="approve",
                                           by=_actor(), yes=True, message_id="click-0123456789")

    assert result.ok, result.message
    (_, inp, _), = engine.seen
    assert inp.message_id == "click-0123456789"


@pytest.mark.asyncio
async def test_the_row_refuses_an_id_it_could_not_carry(_resolvable, monkeypatch):
    from openfactory.actions import catalog

    engine = _Engine({"outcome": "done", "message": "ok"})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token="C0PROD|abc", answer="approve",
                                           by=_actor(), yes=True, message_id="a b\n")

    assert not result.ok and result.code == catalog.INVALID, result.message
    assert engine.seen == [], "a malformed id travelled into a workflow"


def test_the_row_declares_the_id():
    """A parameter the row does not declare is refused by the action layer before `run` — the
    page's id would never arrive, and every click would fail."""
    from openfactory.actions.catalog import CATALOG

    spec = CATALOG["product_answer"]
    assert "message_id" in spec.optional, spec.optional


@pytest.mark.asyncio
async def test_the_worker_hands_the_id_to_the_gate(monkeypatch):
    from openfactory.product import confirm
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import ProductAnswerInput

    seen: dict = {}
    monkeypatch.setattr(ProjectRegistry, "get", lambda self, name: _project())
    monkeypatch.setattr(confirm, "answer_staged",
                        lambda project, **kw: seen.update(kw) or ("done", "ok"))

    await activities.product_role_answer(ProductAnswerInput(
        project="books", token="C0PROD|abc", approved=True, actor="ana", via="panel",
        message_id="click-0123456789"))

    assert seen.get("message_id") == "click-0123456789", seen


# ── 4. the other places the class lived ─────────────────────────────────────────────────────────

def test_what_the_role_tells_is_recorded_with_what_it_answers(monkeypatch):
    """`door.tell` published its reply naming `in_reply_to` and recorded it naming nothing: the same
    answer, told two ways."""
    from openfactory.product import door

    rows = _recorded(monkeypatch)

    async def _took(event, **_kw):
        return door.Ack(accepted=True, id=event.id)

    monkeypatch.setattr(door, "_admit", _took)

    assert door.tell(_project(), conversation="person:ana", text="A proposta abriu.",
                     in_reply_to="asked-0123456789")
    assert [r.get("in_reply_to") for r in rows] == ["asked-0123456789"], rows
    # AN ANNOUNCEMENT IS THE PLATFORM SPEAKING, NOT THE ROLE'S ANSWER (#457): recorded with a kind
    # that is not an answer, so the distillation never reads it as something the role said.
    from openfactory.memory import transcript

    assert [r.get("kind") for r in rows] == ["announcement"], rows
    assert transcript.ANSWER != "announcement"


def test_the_history_hands_the_page_which_message_each_turn_is(monkeypatch):
    from openfactory.api import product_chat
    from openfactory.memory import transcript
    from openfactory.memory.transcript import Turn

    monkeypatch.setattr(transcript, "recent", lambda *_a, **_kw: [
        Turn(role="person", text="sim", actor="ana", id="click-0123456789"),
        Turn(role="agent", text="Registrado.", in_reply_to="click-0123456789")])

    turns = product_chat._history(_project(), "person:ana", "ana")

    assert [(t["id"], t["in_reply_to"]) for t in turns] == [
        ("click-0123456789", ""), ("", "click-0123456789")], turns


def _subscriber(history: list[dict]):
    import asyncio
    import time

    from openfactory.api import product_chat as pc

    sub = pc.Subscriber(person="ana", own="person:ana", product="books", project="books",
                        conversation="person:ana", may_read_room=True, frames=asyncio.Queue())
    sub.echoes = [pc._echo_key(t["role"], t.get("id") if t["role"] != "agent"
                               else t.get("in_reply_to"), t["text"]) for t in history]
    sub.echo_until = time.monotonic() + 60
    return sub


def test_the_socket_drops_the_echo_of_a_turn_BY_ITS_IDENTITY():
    from openfactory.api.product_chat import ProductChat

    sub = _subscriber([{"role": "person", "text": "sim", "id": "click-0123456789"},
                       {"role": "agent", "text": "Registrado.", "in_reply_to": "click-0123456789"}])

    assert ProductChat._an_echo(sub, {"kind": "said", "id": "click-0123456789", "text": "sim"})
    assert ProductChat._an_echo(sub, {"kind": "reply", "text": "Registrado.",
                                      "in_reply_to": "click-0123456789"})


def test_the_socket_DELIVERS_an_answer_that_only_says_the_same_thing():
    """The words matched two different answers; the identity does not."""
    from openfactory.api.product_chat import ProductChat

    sub = _subscriber([{"role": "agent", "text": "Registrado.", "in_reply_to": "click-one-000"}])

    assert not ProductChat._an_echo(sub, {"kind": "reply", "text": "Registrado.",
                                          "in_reply_to": "click-two-000"}), (
        "an answer to another message was dropped as the echo of one that said the same words")


def test_a_row_recorded_with_no_identity_is_still_recognised_by_its_words():
    """The rows written before #266 slice 4, and the proactive posts, have neither id; for them the
    words are all there is, and dropping the echo still beats drawing it twice."""
    from openfactory.api.product_chat import ProductChat

    sub = _subscriber([{"role": "agent", "text": "Bom dia."}])

    assert ProductChat._an_echo(sub, {"kind": "reply", "text": "Bom dia.", "in_reply_to": ""})

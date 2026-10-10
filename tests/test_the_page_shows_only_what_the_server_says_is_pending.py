"""The product page shows buttons only for the proposal the server says is waiting (#443).

WHAT WAS MEASURED (2026-09-30, live). The role staged a defect card for its yes; the person typed
"sim" instead of clicking. The store recorded it — `answered`, `approve`, by the person — the card
was filed and the role said "Registered…". Two hours later, after the panel restarted, the page drew
an agent bubble holding nothing but "WAITING FOR YOUR ANSWER — Confirm and record / Do not record".

The page kept the last token a reply carried (`_pc.staged`) until a CLICK cleared it, and a history
read drew it alone (`pchatStagedAlone`) once the reply's own line no longer carried its buttons.
Now the server says what waits — in the history frame, and in a `staged` frame whenever it changes
— read from the durable store every process writes, and the page replaces its own with it."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from openfactory.memory import messages
from openfactory.product import staging
from tests.the_sink_door import SINK_DOOR

PROJECT = SimpleNamespace(name="books", language="en")
ROOM = "books"


@pytest.fixture(autouse=True)
def durable_store(monkeypatch):
    """The store `remember` mirrors into and `waiting_in` reads — in memory, at the two seams
    `messages` resolves (the fixture `test_the_product_conversation_is_core` uses)."""
    from tests.test_the_panel_is_a_channel import _Sink

    store = _Sink()
    monkeypatch.setattr(SINK_DOOR, lambda: store)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind",
                        lambda project, kind, limit=500, **kw: store.of_kind(project, kind,
                                                                             limit))
    staging._reset_for_tests()
    yield store
    staging._reset_for_tests()


def _stage(person: str = "ana", conversation: str = ROOM) -> str:
    key = staging.key_for(conversation, person)
    entry = {"kind": "defect", "title": "Toolbar cut off", "restated": "Toolbar cut off",
             "requester": person, "conversation": conversation}
    staging.remember(key, entry, lang="en", project=PROJECT, person=person)
    return staging.proposal_token(key, staging.pending_for(key))


# ── the server: what waits is the store's to say ────────────────────────────────────────────────

def test_a_staged_proposal_is_named_with_the_labels_it_was_asked_with():
    token = _stage()
    got = staging.waiting_in(PROJECT, ROOM, "ana")
    assert got == {"token": token, "approve": "Confirm and record", "reject": "Do not record"}


def test_a_proposal_answered_BY_A_TYPED_YES_elsewhere_is_named_no_more():
    """The typed "sim" answered the row in the worker; this process still holds its own thawed
    copy in `_PENDING` — which is exactly what the page must not be told."""
    token = _stage()
    assert staging.pending_for(staging.key_for(ROOM, "ana")) is not None, "setup: a local copy"
    messages.answer("books", token=token, answer="approve", by="ana")
    assert staging.waiting_in(PROJECT, ROOM, "ana") is None, (
        "a proposal the store says is answered was still named — the page draws its buttons")


def test_an_expired_proposal_is_named_no_more():
    _stage()
    later = __import__("time").time() + staging.PROPOSAL_TTL_SECONDS + 60
    assert staging.waiting_in(PROJECT, ROOM, "ana", now=later) is None


def test_another_persons_proposal_is_not_this_persons_but_one_staged_for_nobody_is():
    _stage(person="bob")
    assert staging.waiting_in(PROJECT, ROOM, "ana") is None, "Bob's draft offered to Ana"
    assert staging.waiting_in(PROJECT, ROOM, "bob") is not None
    staging.remember(ROOM, {"kind": "defect", "title": "Anyone's", "restated": "Anyone's"},
                     lang="en", project=PROJECT)
    assert staging.waiting_in(PROJECT, ROOM, "ana") is not None, (
        "a proposal staged under the conversation alone is found by anyone in it, as before")


def test_an_unreadable_store_names_nothing(monkeypatch):
    monkeypatch.setattr(messages, "pending", lambda *a, **k: 1 / 0)
    assert staging.waiting_in(PROJECT, ROOM, "ana") is None


# ── the socket: told on the history, and again whenever it changes ─────────────────────────────

def _subscriber(staged=None):
    from openfactory.api.product_chat import Subscriber

    return Subscriber(person="ana", own="person:ana", product="books", project="books",
                      conversation=ROOM, may_read_room=True, frames=asyncio.Queue(), held=None,
                      staged=staged)


def _frames(sub) -> list[dict]:
    out = []
    while not sub.frames.empty():
        out.append(sub.frames.get_nowait()[1])
    return out


@pytest.fixture
def registry(monkeypatch):
    class _Registry:
        def get(self, name):
            if name != "books":
                raise KeyError(name)
            return PROJECT
    monkeypatch.setattr("openfactory.registry.ProjectRegistry", _Registry)


async def test_the_hub_tells_a_subscriber_when_what_waits_changes_and_only_then(registry):
    from openfactory.api.product_chat import ProductChat

    token = _stage()
    hub = ProductChat()
    sub = _subscriber(staged={"token": token, "approve": "Confirm and record",
                              "reject": "Do not record"})
    hub._subs.add(sub)
    await hub.restage("books", ROOM)
    assert _frames(sub) == [], "nothing changed, and a frame was said anyway"
    messages.answer("books", token=token, answer="approve", by="ana")
    await hub.restage("books", ROOM)
    assert _frames(sub) == [{"kind": "staged", "staged": None}]
    await hub.restage("books", ROOM)
    assert _frames(sub) == [], "the same answer was said twice"


async def test_a_subscriber_still_reading_its_history_is_not_told_before_it(registry):
    from openfactory.api.product_chat import _UNTOLD, ProductChat

    _stage()
    hub = ProductChat()
    sub = _subscriber(staged=_UNTOLD)
    hub._subs.add(sub)
    await hub.restage("books", ROOM)
    assert _frames(sub) == [], "the history frame is the first thing a subscriber is handed"


async def test_the_watch_asks_again_after_every_batch_it_delivers(monkeypatch):
    """The typed yes arrives as entries — the person's line, then the role's thanks — and the
    reply carries no buttons to clear any: the watch is what asks the store again."""
    from openfactory.api import product_chat
    from openfactory.product import door

    asked = []

    class _Hub(product_chat.ProductChat):
        async def restage(self, product, conversation):
            asked.append((product, conversation))

    hub = _Hub(engine=lambda: asyncio.sleep(0))
    watch = product_chat._Watch(hub, "books", ROOM)
    watch.primed.set()

    async def _watch(client, wid, cursor):
        return {"seq": cursor + 1, "presence": {},
                "entries": [{"seq": cursor + 1, "type": "replies",
                             "replies": [{"text": "Registered.", "kind": "answer"}]}]}

    monkeypatch.setattr(door, "watch", _watch)
    await watch._once()
    assert asked == [("books", ROOM)]

    async def _quiet(client, wid, cursor):
        return {"seq": cursor, "presence": {}, "entries": []}

    monkeypatch.setattr(door, "watch", _quiet)
    await watch._once()
    assert asked == [("books", ROOM)], "a read that delivered nothing asked the store anyway"


def test_the_history_frame_carries_what_waits():
    import inspect

    from openfactory.api import product_chat

    code = inspect.getsource(product_chat.serve)
    assert "staged_for, project, key, actor.id" in code
    assert '{"kind": "history", "turns": turns, "staged": sub.staged,' in code


# ── the page: it replaces its own with what the server names ───────────────────────────────────

def _page(script: str) -> dict:
    from tests.test_the_panel_is_a_chat import _run

    return _run("nodes['#prodThread']=node();" + script, pathname="/product/books")


ASK = """pchatFrame({kind:'reply',text:'Register this?',type:'answer',
          options:{token:'tok-1',approve:'Confirm and record',reject:'Do not record'}});"""


def test_a_TYPED_yes_takes_the_buttons_away():
    got = _page(ASK + """
      pchatFrame({kind:'said',id:'m2',text:'sim',speaker:'ana',mine:true});
      pchatFrame({kind:'reply',text:'Registered.',type:'answer'});
      pchatFrame({kind:'staged',staged:null});
      return {staged:_pc.staged,html:nodes['#prodThread'].innerHTML}""")
    assert got["staged"] is None
    assert "Confirm and record" not in got["html"], "a typed yes left the buttons on the page"


def test_a_history_that_names_nothing_removes_a_stale_proposal():
    """The measured page: a token kept from a proposal answered hours ago, and the history read
    after a restart — which used to draw it alone, under no question."""
    got = _page("""_pc.staged={token:'tok-old',approve:'Confirm and record',reject:'Do not record'};
      pchatFrame({kind:'history',staged:null,turns:[{role:'agent',text:'Registered.'}]});
      return {staged:_pc.staged,alone:pchatStagedAlone(),html:nodes['#prodThread'].innerHTML}""")
    assert got["staged"] is None and got["alone"] == ""
    assert "Waiting for your answer" not in got["html"]


def test_a_history_that_names_one_keeps_it_alone_when_its_line_is_out_of_view():
    got = _page("""pchatFrame({kind:'history',turns:[{role:'agent',text:'Registered.'}],
                   staged:{token:'tok-2',approve:'Confirm and record',reject:'Do not record'}});
      return {staged:_pc.staged,alone:pchatStagedAlone()}""")
    assert got["staged"]["token"] == "tok-2"
    assert "Confirm and record" in got["alone"]


def test_a_staged_frame_replaces_never_merges():
    got = _page(ASK + """
      pchatFrame({kind:'staged',staged:{token:'tok-3',approve:'Yes',reject:'No'}});
      return _pc.staged""")
    assert got == {"token": "tok-3", "approve": "Yes", "reject": "No"}

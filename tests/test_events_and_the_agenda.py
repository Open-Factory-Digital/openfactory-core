"""Events and the agenda — #267 slice 3, ADR-0052: the product role hears what happens WHEN it
happens, says it in the conversation it concerns, and what it owes to whom is visible.

WHAT IS PINNED HERE, in the order of the slice's acceptance:

  - a delivered card is announced to its REQUESTER'S conversation when the job that delivered it
    ends — through the job's one exit (`activities.record_outcome`) and the one door — not at the
    next sweep, and not in the project's room; with nobody's conversation known, the room hears
    it, naming nobody;
  - a proactive message waits its turn in the conversation's line: never published while a turn
    is being answered, never ahead of a message sent before it, and never counted as somebody's
    place in the queue;
  - the agenda is on the panel and each person sees their own items and the room's — never
    another person's private ones — and the role reads the same agenda, as its conversation may;
  - the weekly sweep catches what an event missed, and nothing is ever said twice;
  - nobody is named across conversations;
  - and an event cannot be forged from outside: the door every transport reaches refuses one,
    and only the factory's own producers tell it one.

HOW. The conversation is Temporal's own ephemeral test server running `ConversationWorkflow` as it
ships, with the turn stood in for (a turn whose text carries a held word waits for the test); the
producers are the real activity bodies, the real `events` module and the real door. The ledger is a
list, the transcript a recorder, and the board is what the test says it is.
"""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import (
    ACCEPTANCE,
    CLOSED,
    DECISION,
    DELIVERY,
    QUESTION,
    open_loop,
    waiting,
)
from openfactory.product import agenda, door, events, followup, voice
from openfactory.product.engine import Message, Reply
from openfactory.product.key import product_key
from openfactory.product.speaker import sealed
from openfactory.product.triage import Ticket, TriageReport
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.activities import conversation_report
from openfactory.runtime.temporal.conversation import ConversationWorkflow
from openfactory.runtime.temporal.io import HoldSyncInput, OverheardInput, TurnInput

ROOT = Path(__file__).resolve().parent.parent
LANG, AGENT = "pt-BR", "Nina"
#: The person who asked — an id that no sentence of the role's could contain by accident, so a
#: test that looks for it in what the role said is looking for a leak, not for a coincidence.
ANA, BRUNO = "ana-requester-77", "bruno-other-42"
ANAS, BRUNOS = f"person:{ANA}", f"person:{BRUNO}"
ROOM = "books"
QUICK = door.Settings(debounce_seconds=0.1, bound_seconds=10.0)
T0 = "2026-09-20T10:00:00+00:00"


def _project(tmp_path) -> Project:
    return Project(name=ROOM, repo_path=str(tmp_path / "work" / ROOM), language=LANG,
                   product=ProductConfig(docs_repo="acme/books-docs", admins=[ANA],
                                         agent_name=AGENT))


def _delivery(subject: str = "7", issues: str = "500", *, where: str = "",
              who: str = "", ts: str = T0, **extra):
    return open_loop(DELIVERY, subject, owner="product", ts=ts,
                     context={"issues": issues, **followup.delivered_to(where, who), **extra})


def _announcement(subject: str = "7") -> str:
    loop = _delivery(subject)
    return (followup.delivered_text(loop, agent_name=AGENT, language=LANG)
            + followup.acceptance_question(loop, agent_name=AGENT, language=LANG))


@pytest.fixture
def registry(monkeypatch, tmp_path) -> Project:
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    project = _project(tmp_path)
    ProjectRegistry(path).add(project)
    return project


@pytest.fixture
def ledger(monkeypatch) -> SimpleNamespace:
    """The loop ledger as a list — append-only, like the store."""
    book = SimpleNamespace(rows=[])
    monkeypatch.setattr(loop_store, "read", lambda project, **_k: list(book.rows))
    monkeypatch.setattr(loop_store, "write",
                        lambda project, loops, **_k: book.rows.extend(loops) or len(loops))
    return book


@pytest.fixture
def memory(monkeypatch) -> list[dict]:
    """What the product's memory was asked to record."""
    from openfactory.memory import transcript

    said: list[dict] = []
    monkeypatch.setattr(transcript, "record",
                        lambda project, **kw: said.append(kw) or "ts")
    return said


# ── the engine: Temporal's own test server ──────────────────────────────────────────────────────

@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture
def the_door_reaches(env, monkeypatch):
    """What a producer with no client of its own reaches — every one of them tells the door from a
    thread (`door.announce_now`): a fresh client of THIS test's engine, made in that thread's own
    event loop."""
    target = env.client.service_client.config.target_host

    async def _connect():
        return await Client.connect(target, namespace=env.client.namespace,
                                    data_converter=pydantic_data_converter)

    monkeypatch.setattr(door, "_engine", _connect)


class _Worker:
    """The worker's side of a conversation, stood in for: a turn answers "resposta a: <text>", and
    a turn whose text carries a HELD word waits until the test lets it go."""

    def __init__(self) -> None:
        self.turns: list[dict] = []
        self.held: dict[str, asyncio.Event] = {}

    def hold(self, word: str) -> asyncio.Event:
        self.held[word] = asyncio.Event()
        return self.held[word]

    def started(self, text: str) -> bool:
        return any(t["text"] == text for t in self.turns)

    def activities(self) -> list:
        me = self

        @activity.defn(name="conversation_turn")
        async def turn(inp: TurnInput) -> dict:
            row = {"text": inp.text, "end": None}
            me.turns.append(row)
            for word, released in me.held.items():
                while word in inp.text and not released.is_set():
                    activity.heartbeat("held")
                    await asyncio.sleep(0.02)
            row["end"] = time.monotonic()
            return {"replies": [Reply(text=f"resposta a: {inp.text}", addressed_to=inp.speaker,
                                      in_reply_to=inp.id,
                                      conversation=inp.conversation).model_dump(mode="json")]}

        @activity.defn(name="conversation_fast")
        async def fast(inp: TurnInput) -> dict:
            return {"replies": []}

        @activity.defn(name="conversation_overheard")
        async def overheard(inp: OverheardInput) -> dict:
            return {"kept": True}

        return [turn, fast, overheard, conversation_report]


def _worker(env, w: _Worker) -> Worker:
    return Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                  activities=w.activities())


async def _until(ready, *, within: float = 15.0) -> None:
    deadline = time.monotonic() + within
    while not ready():
        if time.monotonic() > deadline:
            raise AssertionError("waited and it never happened")
        await asyncio.sleep(0.05)


#: A test that STARTS its own durable engine (`WorkflowEnvironment`) — the one legitimate reason
#: to open a real connection; every other test here is kept off any engine by `conftest.py`.
engine_of_its_own = pytest.mark.owns_its_engine


async def _published(env, project, conversation: str) -> list[str]:
    """Everything the conversation PUBLISHED, in order — [] when nothing was ever written in it."""
    try:
        seen = await door.watch(env.client, door.workflow_id(product_key(project), conversation),
                                0)
    except door.NotStarted:
        return []
    return [r["text"] for e in seen["entries"] if e.get("type") == "replies"
            for r in e.get("replies") or []]


def _said_by(who: str, text: str) -> Message:
    return Message(project=ROOM, conversation=ROOM, speaker=who, text=text, via="panel",
                   mentions_role=True)


def _job_ended(issue: str = "500", state: str = "done"):
    """THE JOB'S ONE EXIT, as `JobWorkflow.run` calls it for every job."""
    return ActivityEnvironment().run(acts.record_outcome,
                                     HoldSyncInput(project=ROOM, issue=issue, state=state))


# ── 1. a delivered card is announced to its requester's conversation, when it is delivered ─────

@engine_of_its_own
async def test_a_delivered_card_is_announced_in_its_REQUESTERS_conversation_WHEN_the_job_ends(
        env, registry, ledger, memory, the_door_reaches, monkeypatch):
    """The job that finished the work ends; the board says the card was delivered; the requester
    hears it in the conversation they asked in — now, from the job's own exit, with no sweep run
    at all. The room hears nothing, and the ledger moves: the delivery closes, and the "did it
    work?" it asked opens, where it was asked."""
    ledger.rows = [_delivery(where=ANAS, who=ANA)]
    monkeypatch.setattr(events, "_delivered_now", lambda project: {"500"})
    swept: list = []
    monkeypatch.setattr(acts, "_product_followup", lambda *a, **k: swept.append(a) or "")
    async with _worker(env, _Worker()):
        await _job_ended()
        await _until(lambda: bool(ledger.rows[1:]))
        texts: list[str] = []
        for _ in range(100):
            texts = await _published(env, registry, ANAS)
            if texts:
                break
            await asyncio.sleep(0.05)
        room = await _published(env, registry, ROOM)

    assert texts == [_announcement()], texts
    assert room == [], "a delivery asked for in a private conversation was said in the room"
    assert swept == [], "it waited for the sweep"
    closed = [x for x in ledger.rows if x.kind == DELIVERY and x.state == CLOSED]
    asked = [x for x in ledger.rows if x.kind == ACCEPTANCE]
    assert [x.outcome for x in closed] == ["delivered"]
    assert [(x.about, x.context.get("conversation"), x.context.get("requester"))
            for x in asked] == [(ANAS, ANAS, sealed(ANA))]
    assert [(m["thread"], m["role"], m["text"]) for m in memory] == [
        (ANAS, "agent", _announcement())], "the announcement is not in the product's memory"


@engine_of_its_own
async def test_a_card_that_is_done_but_NOT_delivered_announces_nothing(
        env, registry, ledger, memory, the_door_reaches, monkeypatch):
    """The board decides, not the job's word: a split card closes and ships nothing itself, and a
    requirement whose other card is still open is not ready."""
    ledger.rows = [_delivery(issues="500,501", where=ANAS, who=ANA)]
    monkeypatch.setattr(events, "_delivered_now", lambda project: {"500"})
    async with _worker(env, _Worker()):
        await _job_ended("500")
        await asyncio.sleep(0.3)
        assert await _published(env, registry, ANAS) == []
    assert all(x.state != CLOSED for x in ledger.rows)


def test_a_job_that_ended_ANY_other_way_asks_nothing(registry, ledger, monkeypatch):
    """Parked, failed, skipped: no card was finished, so the ledger is not even read."""
    asked: list = []
    monkeypatch.setattr(events, "card_finished", lambda project, **kw: asked.append(kw) or [])
    for state in ("on_hold", "failed", "skipped", "pr_open"):
        asyncio.run(_job_ended(state=state))
    assert asked == []
    for state in ("done", "merged"):
        asyncio.run(_job_ended(state=state))
    assert [kw["card"] for kw in asked] == ["500", "500"]


def test_with_NOBODYS_conversation_known_the_room_hears_it_and_nobody_is_named(
        registry, ledger, monkeypatch):
    told: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: told.append(kw) or True)
    ledger.rows = [_delivery(who=ANA)]

    events.deliver(registry, delivered={"500"})

    assert [t["conversation"] for t in told] == [ROOM]
    assert ANA not in told[0]["text"] and "ana" not in told[0]["text"].lower()


def test_the_newest_request_on_a_card_decides_where_its_events_go(registry):
    rows = [_delivery("7", where=ANAS, ts="2026-09-01T00:00:00+00:00"),
            _delivery("9", where=BRUNOS, ts="2026-09-02T00:00:00+00:00")]
    assert events.conversation_for(registry, "500", rows=rows) == BRUNOS
    assert events.conversation_for(registry, "999", rows=rows) == ROOM
    assert events.conversation_for(registry, "", rows=rows) == ROOM


# ── 2. a proactive message never interleaves with a turn in progress ────────────────────────────

@engine_of_its_own
async def test_a_proactive_message_NEVER_interleaves_with_a_turn_in_progress(
        env, registry, memory, the_door_reaches):
    """Ana's turn is being answered; Bruno writes; then a delivery is announced in the room. The
    announcement waits: nothing is published while Ana's turn runs, Bruno — who wrote first — is
    answered before it, and Bruno is never told the announcement is a turn ahead of him."""
    w = _Worker()
    released = w.hold("devagar")
    wid = door.workflow_id(product_key(registry), ROOM)
    async with _worker(env, w):
        first = await door.receive(_said_by(ANA, "devagar, o relatório"), project=registry,
                                   client=env.client, settings=QUICK)
        await _until(lambda: w.started("devagar, o relatório"))
        then = await door.receive(_said_by(BRUNO, "e o prazo?"), project=registry,
                                  client=env.client, settings=QUICK)
        told = await asyncio.to_thread(door.announce_now, registry, id="evt-delivered-7",
                                       conversation=ROOM, text="está pronto")
        assert told

        await asyncio.sleep(0.5)
        assert await _published(env, registry, ROOM) == [], (
            "the announcement was published in the middle of a turn being answered")
        stands = await env.client.get_workflow_handle(wid).query("where", then.id)
        assert stands["state"] == "queued" and stands["ahead"] == 1, stands
        presence = (await door.watch(env.client, wid, 0))["presence"]
        assert presence["waiting"] == [BRUNO], "an event was shown as somebody in the queue"

        released.set()
        published: list[str] = []
        for _ in range(200):
            published = await _published(env, registry, ROOM)
            if len(published) >= 3:
                break
            await asyncio.sleep(0.05)
    assert published == ["resposta a: devagar, o relatório", "resposta a: e o prazo?",
                         "está pronto"], published
    assert first.accepted and then.accepted


@engine_of_its_own
async def test_with_NOTHING_being_answered_an_event_is_published_at_once(
        env, registry, memory, the_door_reaches):
    async with _worker(env, _Worker()):
        started = time.monotonic()
        assert await asyncio.to_thread(door.announce_now, registry, id="evt-now",
                                       conversation=ANAS, text="está pronto")
        published: list[str] = []
        for _ in range(100):
            published = await _published(env, registry, ANAS)
            if published:
                break
            await asyncio.sleep(0.05)
    assert published == ["está pronto"]
    assert time.monotonic() - started < 10, "an idle conversation held the event back"


@engine_of_its_own
async def test_an_event_is_never_COALESCED_into_a_persons_turn(env, registry, memory,
                                                              the_door_reaches):
    """Two messages from Ana with an event between them are still one turn of Ana's — her words,
    and nothing that happened — and the event is its own item."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        await door.receive(_said_by(BRUNO, "devagar"), project=registry, client=env.client,
                           settings=QUICK)
        await _until(lambda: w.started("devagar"))
        await door.receive(_said_by(ANA, "um"), project=registry, client=env.client,
                           settings=QUICK)
        await asyncio.to_thread(door.announce_now, registry, id="evt-between",
                                conversation=ROOM, text="aconteceu algo")
        await door.receive(_said_by(ANA, "dois"), project=registry, client=env.client,
                           settings=QUICK)
        released.set()
        published: list[str] = []
        for _ in range(200):
            published = await _published(env, registry, ROOM)
            if len(published) >= 3:
                break
            await asyncio.sleep(0.05)
    assert [t["text"] for t in w.turns] == ["devagar", "um\n\ndois"]
    assert published[-1] == "aconteceu algo" and "aconteceu" not in published[1]


@engine_of_its_own
async def test_a_reply_to_an_announcement_in_the_room_IS_a_message_to_the_role(
        env, registry, memory, the_door_reaches, monkeypatch):
    """The role spoke in the room by announcing something, so it takes part there (ADR-0051 D14):
    "funcionou!" written as a reply to the announcement is for the role, and is a turn — not a
    line the room said to itself."""
    from openfactory.memory import transcript

    monkeypatch.setattr(transcript, "took_part", lambda project, **_k: False)
    w = _Worker()
    async with _worker(env, w):
        assert await asyncio.to_thread(door.announce_now, registry, id="evt-room",
                                       conversation=ROOM, text="está pronto")
        await asyncio.sleep(0.3)
        reply = Message(project=ROOM, conversation=ROOM, speaker=ANA, text="funcionou!",
                        in_reply_to="evt-room", via="panel", mentions_role=False)
        ack = await door.receive(reply, project=registry, client=env.client, settings=QUICK)
        await _until(lambda: w.started("funcionou!"))
    assert ack.state != door.OVERHEARD, ack


# ── 3. the sweep is the catch-all, and nothing is said twice ────────────────────────────────────

class _BoardModule:
    """What the sweep's follow-through reads of the module: the board it already fetched."""

    def __init__(self, *delivered: str) -> None:
        self._board_tickets = [Ticket(number=n, title="t", state="closed", column="Done")
                               for n in delivered]
        self.token = None


@engine_of_its_own
async def test_the_sweep_catches_a_delivery_the_event_MISSED_and_never_announces_it_twice(
        env, registry, ledger, memory, the_door_reaches, monkeypatch):
    """The job ended while the board could not be read, so the event said nothing; the weekly
    sweep, as the catch-all, announces it — to the requester's conversation, once. Then the
    event is told again and the sweep runs again, and nothing more is said."""
    ledger.rows = [_delivery(where=ANAS, who=ANA)]
    monkeypatch.setattr(acts, "_land_product_proposals", lambda project, **kw: [])
    monkeypatch.setattr(events, "_delivered_now", lambda project: None)   # the board was down
    async with _worker(env, _Worker()):
        await _job_ended()
        await asyncio.sleep(0.3)
        assert await _published(env, registry, ANAS) == [], "an unreadable board announced"

        swept = await asyncio.to_thread(acts._product_followup, registry, _BoardModule("500"),
                                        TriageReport(), registry.product)
        texts: list[str] = []
        for _ in range(100):
            texts = await _published(env, registry, ANAS)
            if texts:
                break
            await asyncio.sleep(0.05)
        assert texts == [_announcement()]
        assert "closed:1" in swept and "accepting:1" in swept, swept

        monkeypatch.setattr(events, "_delivered_now", lambda project: {"500"})
        await _job_ended()
        again = await asyncio.to_thread(acts._product_followup, registry, _BoardModule("500"),
                                        TriageReport(), registry.product)
        await asyncio.sleep(0.5)
        texts = await _published(env, registry, ANAS)
    assert texts == [_announcement()], "the delivery was announced twice"
    assert "closed:0" in again and "accepting:0" in again, again
    assert len([x for x in ledger.rows if x.kind == ACCEPTANCE]) == 1


@engine_of_its_own
async def test_the_same_happening_told_twice_is_ONE_item_in_the_conversation(
        env, registry, memory, the_door_reaches):
    async with _worker(env, _Worker()):
        for _ in range(2):
            assert await asyncio.to_thread(door.announce_now, registry, id="evt-twice",
                                           conversation=ANAS, text="está pronto")
        await asyncio.sleep(0.5)
        assert await _published(env, registry, ANAS) == ["está pronto"]


def test_a_delivery_the_door_did_NOT_take_stays_open_for_the_next_telling(registry, ledger,
                                                                           monkeypatch):
    monkeypatch.setattr(events, "_tell", lambda project, **kw: False)
    ledger.rows = [_delivery(where=ANAS, who=ANA)]

    assert events.deliver(registry, delivered={"500"}) == []
    assert [x.state for x in waiting(ledger.rows)] == ["open"]


def test_a_delivery_is_told_under_a_DETERMINISTIC_id_so_a_retold_one_is_dropped(
        registry, ledger, monkeypatch):
    told: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: told.append(kw) or False)
    ledger.rows = [_delivery(where=ANAS, who=ANA)]
    events.deliver(registry, delivered={"500"})
    events.deliver(registry, delivered={"500"})
    assert len(told) == 2 and told[0]["id"] == told[1]["id"]
    assert told[0]["id"].startswith(f"{events.DELIVERED}-")


def test_a_door_that_refused_leaves_NOTHING_in_the_products_memory(registry, memory,
                                                                    monkeypatch):
    """Recorded the moment the door takes it, and only then: a message nobody will read is not a
    memory of having said it (`tests/test_sweep_records_only_what_posted.py`, one layer down)."""
    async def _refused(message, **_kw):
        return door.Ack(accepted=False, id=message.id, reason="the engine is down")

    monkeypatch.setattr(door, "_admit", _refused)
    assert door.announce_now(registry, id="evt-x", conversation=ANAS, text="está pronto") is False
    assert memory == []


# ── 4. the agenda: on the panel, per person, and in the role's own reading ──────────────────────

def _rows_of_everyone() -> list:
    """Ana's private delivery, Bruno's private one, a room delivery, a room question, a decision
    asked of Ana in her own conversation — and a tech-lead remedy, which is the floor's."""
    return [open_loop("remedy", "300", owner="techlead", about="sig",
                      ts="2026-08-31T00:00:00+00:00"),
            _delivery("7", where=ANAS, who=ANA, ts="2026-09-01T00:00:00+00:00"),
            _delivery("9", "600", where=BRUNOS, who=BRUNO, ts="2026-09-02T00:00:00+00:00"),
            _delivery("11", "700", who=ANA, ts="2026-09-03T00:00:00+00:00"),
            open_loop(QUESTION, "42", owner="product", about="no-criteria",
                      ts="2026-09-04T00:00:00+00:00",
                      context={"person": "joao-login", "asked": "o que precisa ser verdade?"}),
            open_loop(DECISION, "pdf-ou-csv", owner="product", ts="2026-09-05T00:00:00+00:00",
                      context={"asked": "PDF ou CSV?", "asked_of": sealed(ANA),
                               "asked_in": sealed(ANAS)})]


def test_each_person_sees_their_OWN_items_and_the_rooms_never_another_persons_private_ones():
    rows = _rows_of_everyone()
    ana = agenda.items(rows, agenda.Viewer(own=ANAS, person=ANA), room=ROOM)
    bruno = agenda.items(rows, agenda.Viewer(own=BRUNOS, person=BRUNO), room=ROOM)
    nobody = agenda.items(rows, agenda.Viewer(), room=ROOM)

    assert [(i.subject, i.to) for i in ana] == [("7", "you"), ("11", "you"), ("42", "the room"),
                                                ("pdf-ou-csv", "you")]
    assert [(i.subject, i.to) for i in bruno] == [("9", "you"), ("11", "the room"),
                                                  ("42", "the room")]
    assert [i.subject for i in nobody] == ["11", "42"]
    outsider = agenda.Viewer(own=BRUNOS, person=BRUNO, may_read_room=False)
    assert [i.subject for i in agenda.items(rows, outsider, room=ROOM)] == ["9"]


def test_an_item_says_what_is_owed_or_awaited_and_to_whom_and_NAMES_NOBODY():
    ana = agenda.items(_rows_of_everyone(), agenda.Viewer(own=ANAS, person=ANA), room=ROOM)
    said = {i.subject: (i.direction, i.said) for i in ana}
    assert said["7"] == (agenda.OWED, "tell you when requirement 7 is ready")
    assert said["42"] == (agenda.AWAITED, "an answer about #42")
    assert said["pdf-ou-csv"] == (agenda.AWAITED, "a decision from you")
    every_word = repr([i.as_dict() for i in ana])
    for name in (ANA, BRUNO, "joao-login", sealed(ANA)):
        assert name not in every_word, f"{name!r} reached an agenda item"


@pytest.fixture
def panel(monkeypatch, registry, ledger):
    """Two people with a panel credential each; the ledger holds everyone's items."""
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", f"tok-ana:{ANA}:Ana,tok-bruno:{BRUNO}:Bruno")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_PRODUCT_TOKENS", raising=False)
    ledger.rows = _rows_of_everyone()
    from fastapi.testclient import TestClient

    from openfactory.api import app as api

    return TestClient(api.app)


def _agenda_of(client, token: str) -> dict:
    r = client.post("/api/act/product_agenda", json={"params": {"project": ROOM}},
                    headers={"authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_agenda_is_ON_THE_PANEL_and_filtered_by_who_the_credential_names(panel):
    ana, bruno = _agenda_of(panel, "tok-ana"), _agenda_of(panel, "tok-bruno")

    assert [i["subject"] for i in ana["data"]["items"]] == ["7", "11", "42", "pdf-ou-csv"]
    assert [i["subject"] for i in bruno["data"]["items"]] == ["9", "11", "42"]
    assert "7" not in [i["subject"] for i in bruno["data"]["items"]], "Ana's item reached Bruno"
    assert ANA not in str(bruno) and "PDF ou CSV" not in str(bruno)


def test_a_caller_cannot_ask_for_SOMEBODY_ELSES_agenda(panel):
    """The row takes no conversation and no person: whose agenda it is comes from the credential."""
    r = panel.post("/api/act/product_agenda",
                   json={"params": {"project": ROOM, "thread": ANAS, "person": ANA}},
                   headers={"authorization": "Bearer tok-bruno"})
    assert r.status_code != 200 or "7" not in [i["subject"] for i in r.json()["data"]["items"]]


def test_the_operators_list_of_loops_carries_nobody_elses_private_items(panel):
    r = panel.get(f"/api/loops/{ROOM}", headers={"authorization": "Bearer tok-bruno"})
    assert r.status_code == 200, r.text
    subjects = [x["subject"] for x in r.json()["waiting"]]
    assert "9" in subjects and "11" in subjects and "42" in subjects and "300" in subjects
    assert "7" not in subjects and "pdf-ou-csv" not in subjects, subjects


def test_the_role_reads_the_agenda_ITS_CONVERSATION_may_see(registry, ledger):
    """The facts pack's loops (`loops.md`, `decisions.md`) are read through the same rule: a room's
    turn is read by the room, and never carries anybody's private item."""
    from openfactory.product.facts import render_loops
    from openfactory.product.module import _loops_seen_in

    ledger.rows = _rows_of_everyone()
    in_the_room = render_loops(_loops_seen_in(registry, ROOM, ROOM))
    in_anas = render_loops(_loops_seen_in(registry, ANAS, ROOM))

    assert "`7`" not in in_the_room and "pdf-ou-csv" not in in_the_room
    assert "`9`" not in in_the_room and "`11`" in in_the_room
    assert "`7`" in in_anas and "pdf-ou-csv" in in_anas and "`9`" not in in_anas


@pytest.mark.parametrize("answering_in,sees,never", [
    (ROOM, ["`11`", "`42`"], ["`7`", "`9`", "pdf-ou-csv"]),
    (ANAS, ["`7`", "`11`", "pdf-ou-csv"], ["`9`"]),
])
def test_the_module_WRITES_the_agenda_of_the_conversation_it_answers_into_its_facts(
        tmp_path, registry, ledger, answering_in, sees, never):
    """The pack the role opens (`loops.md`), written by the module's own `_write_facts` for the
    conversation the engine said it answers in (`answering_in`)."""
    from openfactory.product.module import ProductModule

    ledger.rows = _rows_of_everyone()
    root = tmp_path / "ws"
    root.mkdir()
    fake = SimpleNamespace(project=registry, _combined=str(root), _workspace=lambda: None,
                           _board_cards=lambda: [])
    ProductModule.answering_in(fake, answering_in)
    into = ProductModule._write_facts(fake)
    loops = (into / "loops.md").read_text() + (into / "decisions.md").read_text()

    assert all(s in loops for s in sees), loops
    assert not [n for n in never if n in loops], loops


def test_the_engine_tells_the_module_which_conversation_it_answers_in():
    engine = (ROOT / "openfactory/product/engine.py").read_text()
    stage = engine[engine.index("    answering_in = getattr(module, \"answering_in\", None)"):]
    assert stage.index("answering_in(thread)") < stage.index("answer = module.answer(")


def test_the_panel_page_draws_the_agenda_and_reads_it_on_NO_clock():
    import re

    page = (ROOT / "openfactory/api/panel.html").read_text()
    code = page[page.index("<script>"):]

    def _function(name: str) -> str:
        start = code.index(f"function {name}(")
        nxt = re.search(r"\n(async )?function ", code[start + 10:])
        return code[start:start + 10 + (nxt.start() if nxt else len(code))]

    assert 'id="prodAgenda"' in _function("renderProduct")
    assert "loadAgenda()" in _function("bootProduct")
    assert 'act("product_agenda"' in _function("loadAgenda")
    assert "loadAgenda()" in _function("pchatAgendaMoved")
    assert "pchatAgendaMoved()" in _function("pchatFrame")
    for name in ("loadAgenda", "paintAgenda", "pchatAgendaMoved"):
        assert "setInterval" not in _function(name) and "setTimeout" not in _function(name)


# ── 5. nobody is named across conversations ─────────────────────────────────────────────────────

def test_a_reply_in_the_ROOM_neither_closes_nor_learns_of_a_delivery_asked_in_private(
        registry, ledger):
    """Ana's "did it work?" was asked in her own conversation; Bruno's "funcionou" in the room is
    not an answer to it — and hears nothing about it. Ana's, in hers, is."""
    from openfactory.product.module import ProductModule

    asked = followup.acceptance_of(_delivery(where=ANAS, who=ANA,
                                             channel=ANAS), ts=T0)
    ledger.rows = [asked.__class__(**{**asked.__dict__, "context": {
        **asked.context, "conversation": ANAS}})]
    module = ProductModule(registry)

    assert module.settle_acceptance("funcionou", conversation=ROOM) is None
    assert waiting(ledger.rows)
    verdict, loop, _ = module.settle_acceptance("funcionou", conversation=ANAS)
    assert verdict == "worked" and loop.subject == "7"


def test_the_status_line_counts_the_ROOMS_deliveries_never_somebodys_private_one(ledger):
    ledger.rows = [_delivery("7", where=ANAS, who=ANA), _delivery("11", "700", who=ANA)]
    line = followup.waiting_line(ROOM, language="en")
    assert "1 request" in line and "2 request" not in line, line


def test_the_turn_asks_the_acceptance_WHERE_the_reply_was_written(registry, ledger,
                                                                    monkeypatch):
    """The engine's settling stage, driven: Bruno's "funcionou" in the room is not an answer to
    Ana's private "did it work?" — the turn goes on as conversation — and Ana's, in hers, is."""
    from openfactory.product import engine
    from openfactory.product.module import ProductModule

    asked = followup.acceptance_of(_delivery(where=ANAS, who=ANA, channel=ANAS), ts=T0)
    ledger.rows = [asked.__class__(**{**asked.__dict__, "context": {
        **asked.context, "conversation": ANAS}})]
    monkeypatch.setattr(engine, "find_waiting", lambda *a, **k: (None, None))
    module = ProductModule(registry)

    in_the_room = engine.settle(registry, text="funcionou", user=BRUNO, thread=ROOM,
                                module=module)
    in_hers = engine.settle(registry, text="funcionou", user=ANA, thread=ANAS, module=module)

    assert in_the_room.reply is None, in_the_room
    assert in_hers.reply == followup.accepted_text(asked, agent_name=AGENT)


def test_the_sweep_chases_a_did_it_work_WHERE_it_was_asked_and_a_private_decision_NOWHERE(
        registry, ledger, monkeypatch):
    told: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: told.append(kw) or True)
    monkeypatch.setattr(acts, "_land_product_proposals", lambda project, **kw: [])
    old = "2026-01-01T00:00:00+00:00"
    asked = followup.acceptance_of(_delivery(where=ANAS, who=ANA, channel=ANAS), ts=old)
    ledger.rows = [
        asked.__class__(**{**asked.__dict__, "context": {**asked.context, "conversation": ANAS}}),
        open_loop(DECISION, "pdf-ou-csv", owner="product", ts=old,
                  context={"asked": "PDF ou CSV?", "asked_of": sealed(ANA),
                           "asked_in": sealed(ANAS)}),
        open_loop(DECISION, "prazo", owner="product", ts=old,
                  context={"asked": "qual o prazo?", "asked_of": sealed(BRUNO),
                           "asked_in": sealed(ROOM)})]

    acts._product_followup(registry, _BoardModule(), TriageReport(), registry.product)

    where = [(t["conversation"], t["text"]) for t in told]
    assert [w for w, _ in where] == [ANAS, ROOM], where
    assert "PDF ou CSV?" not in " ".join(t for _, t in where), (
        "a decision asked in private was read out to the room")
    assert "qual o prazo?" in where[1][1]


def test_no_event_sentence_has_a_place_for_a_name_nor_the_factorys_own_words():
    for text in (voice.ci_went_red(ref="42", title="Relatório", language=LANG),
                 voice.pull_request_waiting(ref="42", title="Relatório", days=3, language=LANG),
                 voice.preview_up(ref="42", url="https://preview.books.example", language=LANG),
                 voice.document_ingested(name="manual.pdf", language=LANG),
                 _announcement()):
        assert voice.jargon_in(text) == [], text
    for catalogue in (voice._CI_RED, voice._PR_WAITING, voice._PREVIEW_UP,
                      voice._DOCUMENT_INGESTED):
        for sentence in catalogue.values():
            fields = {part.split("}")[0] for part in sentence.split("{")[1:]}
            assert fields <= {"sig", "card", "days", "url", "name"}, sentence


def test_a_preview_sends_them_to_THEIR_product_and_nothing_else():
    """The one link an event may carry is the client's own product running the change (ADR-0050)
    — a placeholder the producer fills, never a literal, and never one of ours."""
    for sentence in voice._PREVIEW_UP.values():
        assert "{url}" in sentence and "http" not in sentence
    said = voice.preview_up(ref="42", url="https://preview.books.example/", language="en")
    assert "https://preview.books.example" in said and voice.jargon_in(said) == []


# ── the other events: said once, to the requester, else the room ────────────────────────────────

@pytest.fixture
def told(registry, ledger, monkeypatch) -> list[dict]:
    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    monkeypatch.setattr(events, "_title_of", lambda project, card: "Relatório mensal")
    return said


def test_a_red_check_is_said_ONCE_per_pull_request_to_the_cards_requester(registry, ledger,
                                                                          told):
    ledger.rows = [_delivery(where=ANAS, who=ANA)]
    assert events.ci_went_red(registry, card="500", pr_url="https://forge/pr/1")
    assert not events.ci_went_red(registry, card="500", pr_url="https://forge/pr/1")
    assert events.ci_went_red(registry, card="500", pr_url="https://forge/pr/2")
    assert [t["conversation"] for t in told] == [ANAS, ANAS]
    assert told[0]["text"] == voice.ci_went_red(ref="500", title="Relatório mensal",
                                                language=LANG, agent_name=AGENT)


def test_a_red_check_on_a_card_nobody_asked_for_is_said_to_the_room(registry, ledger, told):
    assert events.ci_went_red(registry, card="777", pr_url="https://forge/pr/9")
    assert [t["conversation"] for t in told] == [ROOM]


def test_the_repair_pass_tells_the_product_role_before_it_runs(registry, monkeypatch):
    heard: list = []
    monkeypatch.setattr(events, "ci_went_red",
                        lambda project, **kw: heard.append((project.name, kw)) or True)
    acts._the_checks_went_red(acts.CiRepairInput(project=ROOM, issue="500",
                                                 pr_url="https://forge/pr/1"))
    assert heard == [(ROOM, {"card": "500", "pr_url": "https://forge/pr/1"})]
    source = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    repair = source[source.index("async def repair_ci("):]
    assert repair.index("_the_checks_went_red") < repair.index("_heartbeat_while")


def test_a_pull_request_is_said_to_WAIT_only_after_48h_counted_from_the_first_round_that_saw_it(
        registry, ledger, told):
    gate = [("500", "https://forge/pr/1")]
    t0 = 1_000_000.0
    assert events.pull_requests_at_the_gate(registry, gate, now=t0) == []
    assert events.pull_requests_at_the_gate(registry, gate, now=t0 + 47 * 3600) == []
    assert events.pull_requests_at_the_gate(registry, gate, now=t0 + 48 * 3600) == ["500"]
    assert events.pull_requests_at_the_gate(registry, gate, now=t0 + 72 * 3600) == []
    assert told[0]["text"] == voice.pull_request_waiting(ref="500", title="Relatório mensal",
                                                         days=2, language=LANG,
                                                         agent_name=AGENT)


def test_the_techlead_round_hands_the_merge_gates_it_saw_to_the_product_role():
    source = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    watch = source[source.index("async def techlead_watch("):]
    watch = watch[:watch.index("\n@activity.defn")]
    assert 'if gate == "merge" and payload.get("pr_url"):' in watch
    assert 'at_the_merge_gate.append((ticket, str(payload.get("pr_url"))))' in watch
    assert "_pull_requests_waiting, project, at_the_merge_gate" in watch


def test_a_preview_and_a_document_have_their_ENTRY_POINTS_and_are_said_once(registry, ledger,
                                                                           told):
    ledger.rows = [_delivery(where=ANAS, who=ANA)]
    assert events.preview_up(registry, card="500", url="https://preview.books.example")
    assert not events.preview_up(registry, card="500", url="https://preview.books.example")
    assert events.document_ingested(registry, name="manual.pdf", key="doc-1")
    assert not events.document_ingested(registry, name="manual.pdf", key="doc-1")
    assert events.document_ingested(registry, name="contrato.pdf", key="doc-2",
                                    conversation=BRUNOS)
    assert [t["conversation"] for t in told] == [ANAS, ROOM, BRUNOS]


def test_a_project_with_NO_product_role_is_told_nothing(tmp_path, ledger, monkeypatch):
    said: list = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    bare = Project(name="floor-only", repo_path=str(tmp_path / "w" / "f"))
    assert not events.ci_went_red(bare, card="1", pr_url="x")
    assert events.card_finished(bare, card="1") == []
    assert events.deliver(bare, delivered={"1"}) == []
    assert said == []


def test_every_WIRED_producer_calls_its_event_and_the_unwired_ones_say_so():
    """`events.PRODUCERS` is what the report claims: each named producer reaches its entry point
    in the source, and the one whose producer lives on another branch (the preview's, #265) is
    named as not wired."""
    source = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()

    def _body(name: str) -> str:
        start = source.index(f"def {name}(")
        return source[start:source.index("\ndef ", start + 10)
                      if "\ndef " in source[start + 10:] else len(source)]

    reaches = {events.DELIVERED: ("record_outcome", "_a_card_was_finished", "card_finished"),
               events.CI_RED: ("repair_ci", "_the_checks_went_red", "ci_went_red"),
               events.PR_WAITING: ("techlead_watch", "_pull_requests_waiting",
                                   "pull_requests_at_the_gate")}
    for kind, (producer, helper, entry) in reaches.items():
        assert events.PRODUCERS[kind].endswith(f"::{producer}")
        assert helper in _body(producer), f"{producer} no longer tells {kind}"
        assert f"events.{entry}(" in _body(helper), f"{helper} no longer reaches {entry}"
    assert events.PRODUCERS[events.PREVIEW_UP] == ""
    # #269 wired the document's: its producer is the ingestion's own `announce`
    documents = (ROOT / "openfactory/product/documents/ingest.py").read_text()
    start = documents.index("def announce(")
    assert events.PRODUCERS[events.DOCUMENT_INGESTED] == (
        "openfactory/product/documents/ingest.py::announce")
    assert "events.document_ingested(" in documents[start:documents.index("\ndef ", start + 10)]
    assert set(events.PRODUCERS) == set(events.KINDS)


# ── where a delivery's conversation comes from: the staged record ──────────────────────────────

def test_filing_the_work_records_WHERE_it_was_asked_and_a_digest_of_WHO(ledger):
    from openfactory.product.authoring import WriteResult
    from openfactory.product.module import ProductModule

    fake = SimpleNamespace(project=SimpleNamespace(name=ROOM))
    ProductModule._open_delivery(fake, SimpleNamespace(number=7),
                                 [WriteResult(ok=True, ref="#500")], conversation=ANAS,
                                 requester=ANA)
    ProductModule._track_defect(fake, "88", conversation=ANAS, requester=ANA)

    assert [(x.subject, x.context.get("conversation"), x.context.get("requester"))
            for x in ledger.rows] == [("7", ANAS, sealed(ANA)), ("defeito-88", ANAS, sealed(ANA))]
    assert ANA not in repr([x.context for x in ledger.rows]).replace(ANAS, "")


def test_the_confirmation_hands_the_STAGED_conversation_and_requester_to_the_filing():
    """An admin's yes on somebody's behalf still owes the announcement to whoever asked, where
    they asked — read off the staged entry, never off who said yes."""
    from openfactory.product import confirm

    class _Module:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def open_cards_for(self, number, *, actor, conversation="", requester=""):
            self.calls.append({"actor": actor, "conversation": conversation,
                               "requester": requester})
            return []

    class _Older:
        def open_cards_for(self, number, *, actor):
            return []

    module = _Module()
    entry = {"requester": ANA, "conversation": ANAS}
    confirm._the_official_cards(module, 7, BRUNO, SimpleNamespace(name=ROOM), LANG, "ok",
                                entry=entry)
    assert module.calls == [{"actor": BRUNO, "conversation": ANAS, "requester": ANA}]
    assert confirm._whose(_Older().open_cards_for, entry) == {}
    assert confirm._whose(module.open_cards_for, {}) == {"conversation": "", "requester": ""}


def _filing(registry, **overrides) -> SimpleNamespace:
    """The module's own filing verbs over a module whose every seam is stood in for — what each
    verb hands the next is recorded in `handed`."""
    from openfactory.product.authoring import WriteResult

    handed: dict[str, dict] = {}
    requirement = SimpleNamespace(number=7, is_live=True, is_promise=True,
                                  came_from_the_code=False)
    fake = SimpleNamespace(
        project=registry, _via="api", _board_tickets=[], handed=handed,
        context=lambda: SimpleNamespace(
            available=True, link=SimpleNamespace(docs_repo="acme/books-docs"),
            corpus=SimpleNamespace(by_number=lambda n: requirement)),
        _read_board=lambda **_k: ([], ""), _workspace=lambda: (None, None), _sources=lambda: [],
        _role=lambda **_k: SimpleNamespace(issues_for=lambda **_k: SimpleNamespace(
            ok=True, issues=[SimpleNamespace(title="Exportar")])),
        _tracker=lambda: object(), _board_or_default=lambda board: None,
        _file_one=lambda *a, **k: WriteResult(ok=True, ref="#500"),
        _open_delivery=lambda req, results, **kw: handed.setdefault("_open_delivery", kw),
        _track_defect=lambda number, **kw: handed.setdefault("_track_defect", kw),
        _checked_write=lambda **_k: WriteResult(ok=True, ref="#88"), _same_as=None,
        _cannot_see_the_product=lambda: None)
    for name, value in overrides.items():
        setattr(fake, name, value)
    return fake


def test_every_filing_verb_hands_WHERE_it_was_asked_on_to_the_delivery(registry):
    from openfactory.product.module import ProductModule

    whose = {"conversation": ANAS, "requester": ANA}
    fake = _filing(registry)
    ProductModule.file_issues(fake, SimpleNamespace(number=7), actor=ANA, **whose)
    ProductModule.file_defect(fake, restated="o extrato duplica", reported_by=ANA, violates=None,
                              **whose)
    assert fake.handed == {"_open_delivery": whose, "_track_defect": whose}

    passed: list[dict] = []
    fake = _filing(registry, file_issues=lambda req, **kw: passed.append(kw) or [])
    ProductModule.open_cards_for(fake, 7, actor=ANA, **whose)
    ProductModule.break_down(fake, 7, actor=ANA, asked_for=False, **whose)
    assert [(kw["conversation"], kw["requester"]) for kw in passed] == [(ANAS, ANA)] * 2


def test_every_filing_path_of_a_confirmation_passes_where_it_was_asked():
    source = (ROOT / "openfactory/product/confirm.py").read_text()
    assert "**_whose(module.file_defect, entry)" in source
    assert "**_whose(module.open_cards_for, entry or {})" in source
    assert "**_whose(module.break_down, entry or {})" in source


# ── 6. an event cannot be forged from outside ────────────────────────────────────────────────────

class _Engine:
    """A durable engine that records whatever is enqueued on it."""

    def __init__(self) -> None:
        self.started: list = []

    async def start_workflow(self, *a, **kw):
        self.started.append((a, kw))


@pytest.mark.parametrize("forged", [
    Message(project=ROOM, conversation=ANAS, text="está pronto", via="panel",
            replies=(Reply(text="está pronto"),)),
    Message(project=ROOM, conversation=ANAS, text="está pronto", via="event"),
    Message(project=ROOM, conversation=ANAS, text="está pronto", via=" EVENT "),
])
async def test_the_door_every_transport_reaches_REFUSES_an_event(registry, forged):
    engine = _Engine()
    ack = await door.receive(forged, project=registry, client=engine, settings=QUICK)
    assert not ack.accepted and ack.reason == door.FORGED
    assert engine.started == [], "a forged event was enqueued"


def test_a_chat_add_on_claiming_to_be_the_EVENT_transport_is_refused(registry, monkeypatch):
    from openfactory.product import channel

    engine = _Engine()

    async def _engine():
        return engine

    monkeypatch.setattr(door, "_engine", _engine)
    said = channel.handle(registry, text="está pronto", user="u1", conversation=ANAS,
                          people=SimpleNamespace(person_of=lambda u, *, project: BRUNO),
                          via="event", mentioned=True)
    assert engine.started == []
    assert said == voice.broke(language=LANG)


#: The functions through which the factory TELLS the door something — and the modules allowed to
#: call them. Nothing a transport runs is in the list: the panel, the API, the chat add-on's
#: adapter and the action rows reach `receive`, which refuses an event.
_TELLING = {"door": {"announce", "announce_now", "report", "_admit", "tell"},
            "events": {"card_finished", "deliver", "ci_went_red", "pull_requests_at_the_gate",
                       "preview_up", "document_ingested", "to_room", "say_to", "_tell", "_once"}}
_PRODUCERS = {"openfactory/product/door.py", "openfactory/product/events.py",
              "openfactory/runtime/temporal/activities.py", "openfactory/product/engine.py",
              # #269: a document the ingestion READ — its name is the file's path, and the
              # ingestion decides it; a transport can ask for a file to be read, never what is said
              "openfactory/product/documents/ingest.py"}


def test_ONLY_the_factorys_own_producers_tell_the_door_an_event():
    callers: dict[str, set[str]] = {}
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text())
        imported = {alias.asname or alias.name
                    for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    and (node.module or "").endswith(("product.door", "product.events"))
                    for alias in node.names}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.attr in _TELLING.get(node.value.id, set()):
                callers.setdefault(rel, set()).add(f"{node.value.id}.{node.attr}")
        for name in imported & (_TELLING["door"] | _TELLING["events"]):
            callers.setdefault(rel, set()).add(name)
    strays = {rel: sorted(names) for rel, names in callers.items() if rel not in _PRODUCERS}
    assert not strays, f"something outside the factory's producers tells the door: {strays}"
    assert "openfactory/runtime/temporal/activities.py" in callers


def test_the_guard_above_is_LOOKING():
    """It would pass over an empty tree: the producers it allows are where it finds the calls."""
    source = (ROOT / "openfactory/runtime/temporal/activities.py").read_text()
    for call in ("events.card_finished(", "events.ci_went_red(",
                 "events.pull_requests_at_the_gate(", "events.deliver(", "events.to_room(",
                 "door.report("):
        assert call in source, call

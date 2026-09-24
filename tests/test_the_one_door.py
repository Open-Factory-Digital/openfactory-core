"""One door, parallel conversations — #266 slice 3, ADR-0051 D1 and D3–D6, run on an engine.

WHAT IS PINNED HERE. Every message to the product role enters through `door.receive`: validated,
deduplicated by its id, enqueued as a signal on its conversation's long-lived workflow
(`po-{product}-{conversation}`, started with signal-with-start) and acknowledged at once, with no
model called. Behind the door, `ConversationWorkflow` takes one turn at a time inside a
conversation and nothing orders two conversations; it hears a speaker out (debounce), answers what
one speaker sent in a burst as one turn (coalescing) without letting anyone jump the queue, bounds a
turn at about ninety seconds and hands what outlives it back through the door, answers the
read-only asks beside a busy turn, and continues as new without forgetting what it has seen. The
turns share a ceiling per product and per deployment, and two registry projects of one product are
one conversation key space.

HOW. On Temporal's own ephemeral test server (`WorkflowEnvironment`), like every other workflow
test here, with the conversation workflow as it ships and the worker's activities stood in for
where the test is about the QUEUE — each records what it was asked and when, and a turn whose text
carries a word the test holds waits until the test lets it go. Where the test is about the CEILING
the worker's real turn activity runs, with only the engine behind it replaced; and the late answer
always goes back through the real report activity and the real door.

THE ONE THING THE TEST SERVER CANNOT DO is notice a dead worker by its missing heartbeat, and it
cannot fail a sticky task over to a new worker either — so the restart test gives the dying worker
no sticky cache and lets the SDK's own shutdown report the turn it abandoned, which is the
production path a restart takes when the worker is stopped rather than killed. The turn is then
retried (`conversation.TURN_RETRY`) on a worker that replays the conversation from its history
alone.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import cap, door, engine, voice
from openfactory.product.engine import Message, Reply
from openfactory.product.key import product_key
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal import conversation as conversation_mod
from openfactory.runtime.temporal.activities import conversation_report
from openfactory.runtime.temporal.conversation import ConversationWorkflow
from openfactory.runtime.temporal.io import OverheardInput, TurnInput
from tests.the_sink_door import SINK_DOOR

#: THIS FILE STARTS ITS OWN ENGINE, like `test_temporal_workflow`. `WorkflowEnvironment` boots an
#: ephemeral Temporal on a port it picked and owns its whole life. Everything else in the suite is
#: blocked by `conftest._no_live_durable_engine` (#107).
pytestmark = pytest.mark.owns_its_engine

LANG, AGENT = "pt-BR", "Nina"
BOOKS_DOCS, SHOP_DOCS = "acme/books-docs", "acme/shop-docs"
ALICE, BOB, CAROL, DAVE = "U0ALICE", "U0BOB", "U0CAROL", "U0DAVE"
#: A conversation's numbers, shortened so a test waits a fraction of a second, never ninety.
QUICK = door.Settings(debounce_seconds=0.2, bound_seconds=10.0)


def _project(name: str = "books", docs: str = BOOKS_DOCS) -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language=LANG,
                   product=ProductConfig(docs_repo=docs, admins=["U0ADMIN"], agent_name=AGENT))


def _message(text: str, *, speaker: str, conversation: str = "sala", project: str = "books",
             id: str | None = None, mentions_role: bool = True) -> Message:
    """A message TO THE ROLE in a room. Since #266 slice 6 (ADR-0051 D14) a room message is a turn
    only when it is addressed to the role, and every message here is about the queue a turn waits
    in — so each one names the role, the way the panel's room says it does. What happens to one
    that does not is `tests/test_no_vendor_in_the_core.py`'s."""
    return Message(**({"id": id} if id else {}), project=project, conversation=conversation,
                   speaker=speaker, text=text, via="panel", mentions_role=mentions_role)


async def _until(ready, *, within: float = 10.0) -> None:
    deadline = time.monotonic() + within
    while not ready():
        if time.monotonic() > deadline:
            raise AssertionError("waited and it never happened")
        await asyncio.sleep(0.02)


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture
def registry(monkeypatch, tmp_path) -> dict[str, Project]:
    """Three registry projects: two of ONE product (one context repository), one of another."""
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    projects = {p.name: p for p in (_project("books"), _project("books-api"),
                                    _project("shop", SHOP_DOCS))}
    for p in projects.values():
        ProjectRegistry(path).add(p)
    return projects


class _Worker:
    """The worker's side, stood in for: every turn is recorded with when it started and ended,
    and a turn whose text carries a HELD word waits until the test lets it go."""

    def __init__(self) -> None:
        self.turns: list[dict] = []
        self.fast: list[dict] = []
        self.kept: list[dict] = []
        self.held: dict[str, asyncio.Event] = {}

    def hold(self, word: str) -> asyncio.Event:
        self.held[word] = asyncio.Event()
        return self.held[word]

    def started(self, text: str) -> bool:
        return any(t["text"] == text for t in self.turns)

    def activities(self, *, dies: bool = False) -> list:
        me = self

        @activity.defn(name="conversation_turn")
        async def turn(inp: TurnInput) -> dict:
            row = {"conversation": inp.conversation, "speaker": inp.speaker, "text": inp.text,
                   "project": inp.project, "ids": list(inp.ids), "attempt":
                   activity.info().attempt, "start": time.monotonic(), "end": None}
            me.turns.append(row)
            if dies:
                while True:                      # until the worker it runs on goes away
                    activity.heartbeat("working")
                    await asyncio.sleep(0.05)
            for word, released in me.held.items():
                while word in inp.text and not released.is_set():
                    activity.heartbeat("held")
                    await asyncio.sleep(0.02)
            row["end"] = time.monotonic()
            return {"replies": [_said(f"resposta a: {inp.text}", inp)]}

        @activity.defn(name="conversation_fast")
        async def fast(inp: TurnInput) -> dict:
            me.fast.append({"text": inp.text, "speaker": inp.speaker, "at": time.monotonic()})
            return {"replies": [_said("status: tudo em dia", inp)]}

        @activity.defn(name="conversation_overheard")
        async def overheard(inp: OverheardInput) -> dict:
            # what a room said to somebody else, KEPT (#266 slice 6) — recorded here, never a turn
            me.kept.append({"text": inp.text, "speaker": inp.speaker, "id": inp.id,
                            "conversation": inp.conversation})
            return {"kept": True}

        return [turn, fast, overheard, conversation_report]


def _said(text: str, inp: TurnInput) -> dict:
    return Reply(text=text, addressed_to=inp.speaker, in_reply_to=inp.id,
                 conversation=inp.conversation).model_dump(mode="json")


def _worker(env, w: _Worker, **kw) -> Worker:
    return Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                  activities=w.activities(dies=kw.pop("dies", False)), **kw)


async def _send(env, message: Message, project: Project, settings=QUICK) -> door.Ack:
    return await door.receive(message, project=project, client=env.client, settings=settings)


async def _answer(env, ack: door.Ack, *, within: float = 15.0) -> list[Reply]:
    replies = await door.wait(ack, client=env.client, bound=within)
    assert replies is not None, f"{ack.id} was never answered"
    return replies


# ── conversations run in parallel; inside one, one turn at a time ───────────────────────────────

async def test_two_messages_in_DIFFERENT_conversations_run_at_the_same_time(env, registry):
    """ADR-0051 D3: each conversation is its own queue, so a slow turn in one holds nobody in
    another — both turns are running before either has finished."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        one = await _send(env, _message("devagar, um", speaker=ALICE, conversation="sala-a"),
                          registry["books"])
        two = await _send(env, _message("devagar, dois", speaker=BOB, conversation="sala-b"),
                          registry["books"])
        await _until(lambda: w.started("devagar, um") and w.started("devagar, dois"))
        assert all(t["end"] is None for t in w.turns), "one conversation waited for the other"
        released.set()
        assert (await _answer(env, one))[-1].text == "resposta a: devagar, um"
        assert (await _answer(env, two))[-1].text == "resposta a: devagar, dois"
    assert one.workflow_id != two.workflow_id


async def test_two_messages_in_the_SAME_conversation_run_one_after_the_other(env, registry):
    """Inside a conversation, one turn at a time: the second person's turn starts only after the
    first person's has ended — never beside it, where each answer would be blind to the other."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        first = await _send(env, _message("devagar, primeiro", speaker=ALICE), registry["books"])
        await _until(lambda: w.started("devagar, primeiro"))
        second = await _send(env, _message("segundo", speaker=BOB), registry["books"])
        await asyncio.sleep(QUICK.debounce_seconds * 4)
        assert not w.started("segundo"), "the second turn ran beside the first"
        released.set()
        await _answer(env, first)
        await _answer(env, second)
    one, two = w.turns
    assert (one["text"], two["text"]) == ("devagar, primeiro", "segundo")
    assert two["start"] >= one["end"], "the turns overlapped"


async def test_the_second_sender_is_acknowledged_within_two_seconds_and_NOBODY_is_named(
        env, registry):
    """ADR-0051 D5: busy is a presence, never a refusal. The second person in a room hears within
    two seconds that the message is kept and they are next — and nothing in what they get back
    says who the role is answering."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        await _send(env, _message("devagar, a Alice primeiro", speaker=ALICE), registry["books"])
        await _until(lambda: w.started("devagar, a Alice primeiro"))

        began = time.monotonic()
        ack = await _send(env, _message("e eu?", speaker=BOB), registry["books"])
        took = time.monotonic() - began

        assert took < 2.0, f"the second sender waited {took:.2f}s for an acknowledgement"
        assert ack.accepted and ack.state == door.QUEUED and ack.ahead == 1, ack
        assert ack.text == voice.you_are_next(ahead=1, language=LANG, agent_name=AGENT)
        assert ALICE not in ack.model_dump_json(), "the acknowledgement names the other person"
        released.set()
        await _answer(env, ack)


def test_the_busy_acknowledgement_has_no_place_for_a_name_in_ANY_language():
    """The anonymity is structural: every catalogue the busy acknowledgement is composed from has
    no placeholder but the count, in every language it is written in — there is nowhere a name
    could go, whoever calls it."""
    import string

    for catalogue in (voice._YOU_ARE_NEXT, voice._IN_ORDER, voice._HEARD, voice._HANDED_OFF):
        for sentence in catalogue.values():
            fields = {f for _, f, _, _ in string.Formatter().parse(sentence) if f}
            assert fields <= {"ahead"}, (sentence, fields)


# ── nothing a person said is lost with the process ──────────────────────────────────────────────

async def test_no_message_is_lost_when_the_worker_restarts_mid_turn(env, registry):
    """A message is a signal, so it is in the conversation's history the moment the door returns.
    The worker dies with a turn half done; a message arrives while no worker runs at all; a new
    worker — with no cache, replaying the conversation from its history — answers both, the
    interrupted turn on its second attempt."""
    dying, fresh = _Worker(), _Worker()
    first = _worker(env, dying, dies=True, max_cached_workflows=0)
    running = asyncio.create_task(first.run())
    try:
        interrupted = await _send(env, _message("o saldo vem errado", speaker=ALICE),
                                  registry["books"])
        await _until(lambda: dying.started("o saldo vem errado"))
    finally:
        await first.shutdown()
        await running
    meanwhile = await _send(env, _message("alguém aí?", speaker=BOB), registry["books"])
    assert meanwhile.accepted, "the door refused a message while no worker was running"

    async with _worker(env, fresh, max_cached_workflows=0):
        assert (await _answer(env, interrupted))[-1].text == "resposta a: o saldo vem errado"
        assert (await _answer(env, meanwhile))[-1].text == "resposta a: alguém aí?"
    retried = next(t for t in fresh.turns if t["text"] == "o saldo vem errado")
    assert retried["attempt"] == 2, retried


# ── the ceiling ─────────────────────────────────────────────────────────────────────────────────

class _Measured:
    """The engine behind the worker's REAL turn activity, replaced by a turn that takes a moment
    and counts how many run at once — per product, and in all."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now: dict[str, int] = {}
        self.most: dict[str, int] = {}
        self.all_now = self.all_most = 0

    def turn(self, project, message, *, module=None):
        key = product_key(project)
        with self.lock:
            self.now[key] = self.now.get(key, 0) + 1
            self.most[key] = max(self.most.get(key, 0), self.now[key])
            self.all_now += 1
            self.all_most = max(self.all_most, self.all_now)
        time.sleep(0.4)
        with self.lock:
            self.now[key] -= 1
            self.all_now -= 1
        return [Reply(text=f"feito: {message.text}", in_reply_to=message.id,
                      conversation=message.conversation, addressed_to=message.speaker)]


@pytest.fixture
def measured(monkeypatch) -> _Measured:
    from openfactory.product import module as module_mod
    from openfactory.runtime.temporal.activities import conversation_turn

    m = _Measured()
    monkeypatch.setattr(engine, "turn", m.turn)
    monkeypatch.setattr(module_mod, "ProductModule", lambda project, *, via="": object())
    m.activity = conversation_turn
    cap.reset()
    yield m
    cap.reset()


async def _many(env, registry, m: _Measured) -> None:
    fake = _Worker()
    activities = [m.activity, *fake.activities()[1:]]
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                      activities=activities):
        sent = [await _send(env, _message(f"pedido {i}", speaker=ALICE, conversation=f"c{i}",
                                          project=name), registry[name])
                for i, name in enumerate(("books", "books-api", "books", "shop", "shop"))]
        for ack in sent:
            assert (await _answer(env, ack))[-1].text.startswith("feito:")


async def test_the_ceiling_PER_PRODUCT_holds_and_orders_nothing_across_products(
        env, registry, measured, monkeypatch):
    """ADR-0051 D4. One turn at a time per product here, across five conversations and both
    registry projects of one product — while the other product's turns run beside them: the
    ceiling limits, it does not queue products behind each other."""
    monkeypatch.setenv(cap.PER_PRODUCT_ENV, "1")
    monkeypatch.setenv(cap.PER_DEPLOYMENT_ENV, "2")

    await _many(env, registry, measured)

    books, shop = product_key(registry["books"]), product_key(registry["shop"])
    assert measured.most == {books: 1, shop: 1}, measured.most
    assert measured.all_most == 2, "two products' turns never ran side by side"


async def test_the_ceiling_PER_DEPLOYMENT_holds(env, registry, measured, monkeypatch):
    monkeypatch.setenv(cap.PER_PRODUCT_ENV, "3")
    monkeypatch.setenv(cap.PER_DEPLOYMENT_ENV, "1")

    await _many(env, registry, measured)

    assert measured.all_most == 1, measured.all_most


def test_the_ceiling_is_a_counting_semaphore_per_product_and_for_the_deployment():
    """The mechanism on its own: a product's slots, the deployment's, and a turn that stops
    waiting when whoever asked for it is gone."""
    def _gives_up_after(seconds: float) -> threading.Event:
        """A wait that cannot hang the suite: it is abandoned when the time is up."""
        gone = threading.Event()
        timer = threading.Timer(seconds, gone.set)
        timer.daemon = True
        timer.start()
        return gone

    ceiling = cap.Ceiling(per_product=1, per_deployment=2)
    with ceiling.hold("repo:a"):
        abandoned = threading.Event()
        abandoned.set()
        with pytest.raises(cap.Abandoned):
            with ceiling.hold("repo:a", abandoned=abandoned):
                pass
        with ceiling.hold("repo:b", abandoned=_gives_up_after(2.0)):
            with pytest.raises(cap.Abandoned):
                with ceiling.hold("repo:c", abandoned=abandoned):
                    pass


def test_the_ceiling_reads_its_numbers_from_the_environment_and_refuses_nonsense(monkeypatch):
    cap.reset()
    try:
        monkeypatch.setenv(cap.PER_PRODUCT_ENV, "0")
        monkeypatch.setenv(cap.PER_DEPLOYMENT_ENV, "7")
        got = cap.ceiling()
        assert (got.per_product, got.per_deployment) == (cap.DEFAULT_PER_PRODUCT, 7)
    finally:
        cap.reset()


# ── the product is the key ──────────────────────────────────────────────────────────────────────

async def test_two_registry_projects_of_ONE_product_share_one_conversation(env, registry):
    """ADR-0051 D2: the conversation is the product's. The same conversation reached from the
    two registry projects of one product is ONE workflow, so its turns are one queue — each turn
    still answered with the registry project its speaker was on."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        web = await _send(env, _message("devagar, do site", speaker=ALICE, project="books"),
                          registry["books"])
        await _until(lambda: w.started("devagar, do site"))
        api = await _send(env, _message("e da api?", speaker=BOB, project="books-api"),
                          registry["books-api"])
        assert web.workflow_id == api.workflow_id and web.product == api.product
        assert api.state == door.QUEUED and api.ahead == 1, "the other project's turn ran beside"
        released.set()
        await _answer(env, web)
        await _answer(env, api)
    assert [t["project"] for t in w.turns] == ["books", "books-api"]
    other = await _send(env, _message("oi", speaker=CAROL, project="shop"), registry["shop"])
    assert other.workflow_id != web.workflow_id, "two products share a conversation"


def test_a_workflow_id_names_the_product_and_the_conversation_and_hashes_NO_text():
    """`po-{product}-{conversation}`, deterministic across processes — the per-message ids ended
    in `hash(text)`, randomised per process. Two keys that read alike are two conversations."""
    web, api = _project("books"), _project("books-api")
    one = door.workflow_id(product_key(web), "person:ana")

    assert one == door.workflow_id(product_key(api), "person:ana")
    assert one.startswith("po-") and "person-ana" in one
    assert one != door.workflow_id(product_key(web), "person-ana")
    assert one != door.workflow_id(product_key(_project("shop", SHOP_DOCS)), "person:ana")
    for text in ("o saldo vem errado", "sim"):
        assert text.replace(" ", "-") not in one


# ── the door refuses what it cannot enqueue, and never calls a model ────────────────────────────

@pytest.mark.parametrize("message, project, why", [
    (Message(project="books", conversation="sala", text="   "), _project(), "empty"),
    (Message(project="books", conversation="sala", text="x" * (door.MAX_TEXT + 1)), _project(),
     "characters"),
    (Message(project="books", conversation="", text="oi"), _project(), "conversation"),
    (Message(project="books", conversation="sala", text="oi"), _project("shop", SHOP_DOCS),
     "handed the project"),
    (Message(project="books", conversation="sala", text="oi"),
     Project(name="books", repo_path="/t"), "no product role"),
], ids=["empty", "too-long", "no-conversation", "another-project", "no-product-role"])
async def test_the_door_REFUSES_what_it_will_not_enqueue(message, project, why):
    class _Untouchable:
        async def start_workflow(self, *a, **k):
            raise AssertionError("a refused message reached the engine")

    ack = await door.receive(message, project=project, client=_Untouchable(), settings=QUICK)

    assert not ack.accepted and why in ack.reason, ack


def test_only_what_READS_skips_the_turn():
    """The fast path is the engine's read-only intents that spend no model call — decided by the
    word list, so the door can decide it without calling anything."""
    for said in ("status", "Nina, faz a triagem do board", "quem é você?"):
        assert engine.reads_only(said), said
    for said in ("olha o que está parado", "quero um relatório mensal", "sim", "fecha o #12"):
        assert not engine.reads_only(said), said


# ── one speaker's burst is one turn, and nobody jumps the queue ─────────────────────────────────

async def test_a_burst_is_heard_out_and_answered_as_ONE_turn(env, registry):
    """ADR-0051 D5: people write in bursts, so a turn waits for its speaker to pause — and what
    they said meanwhile is one message, answered once."""
    w = _Worker()
    slow = door.Settings(debounce_seconds=0.8, bound_seconds=10.0)
    async with _worker(env, w):
        first = await _send(env, _message("preciso de um relatório", speaker=ALICE),
                            registry["books"], slow)
        second = await _send(env, _message("mensal, por favor", speaker=ALICE),
                             registry["books"], slow)
        assert second.text == "", "the second line of a burst was acknowledged twice"
        answered = await _answer(env, second)
        assert await _answer(env, first) == answered
    assert [t["text"] for t in w.turns] == ["preciso de um relatório\n\nmensal, por favor"]


async def test_what_one_speaker_sent_while_the_role_was_busy_is_one_turn_and_NOBODY_jumps(
        env, registry):
    """Alice writes, Bob writes, Alice writes again, Dave writes — all while the role answers
    Carol. Alice's two lines are one turn, in the place her FIRST line earned; Bob is next after
    her, exactly where he would have been without her second line; and Dave, who wrote last, is
    answered last."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        await _send(env, _message("devagar, Carol", speaker=CAROL), registry["books"])
        await _until(lambda: w.started("devagar, Carol"))
        a1 = await _send(env, _message("a1", speaker=ALICE), registry["books"])
        b1 = await _send(env, _message("b1", speaker=BOB), registry["books"])
        a2 = await _send(env, _message("a2", speaker=ALICE), registry["books"])
        d1 = await _send(env, _message("d1", speaker=DAVE), registry["books"])

        assert (a1.ahead, b1.ahead, d1.ahead) == (1, 2, 3), (a1, b1, d1)
        assert b1.text == voice.you_are_next(ahead=2, language=LANG, agent_name=AGENT)
        assert a2.text == "", "a line joining its speaker's waiting turn was acknowledged again"
        released.set()
        for ack in (a1, b1, a2, d1):
            await _answer(env, ack)
    assert [(t["speaker"], t["text"]) for t in w.turns] == [
        (CAROL, "devagar, Carol"), (ALICE, "a1\n\na2"), (BOB, "b1"), (DAVE, "d1")]


async def test_a_message_sent_TWICE_is_one_turn_and_the_retry_reads_the_first_answer(
        env, registry):
    """Deduplicated by the message's own id: a transport that retries a send is one turn, and the
    retry is handed the answer the first one got."""
    w = _Worker()
    same = uuid.uuid4().hex
    async with _worker(env, w):
        first = await _send(env, _message("oi", speaker=ALICE, id=same), registry["books"])
        answered = await _answer(env, first)
        again = await _send(env, _message("oi", speaker=ALICE, id=same), registry["books"])

        assert again.duplicate and again.text == "", again
        assert await _answer(env, again) == answered
    assert len(w.turns) == 1, w.turns


# ── the bound, and the way back through the door ────────────────────────────────────────────────

async def test_a_turn_past_its_BOUND_is_handed_off_and_its_answer_comes_back_through_the_door(
        env, registry, monkeypatch):
    """ADR-0051 D6. The person hears, at the bound, that the work goes on; the conversation moves
    on to the next turn; and the answer, when it comes, returns through `door.receive` as an
    internal event and is published to the message it answers."""
    events: list[Message] = []
    real = door.receive

    async def _spy(message, **kw):
        if message.replies:
            events.append(message)
        return await real(message, **kw)

    monkeypatch.setattr(door, "receive", _spy)
    w = _Worker()
    released = w.hold("devagar")
    bounded = door.Settings(debounce_seconds=0.1, bound_seconds=1.0)
    async with _worker(env, w):
        long = await _send(env, _message("devagar, um levantamento", speaker=ALICE),
                           registry["books"], bounded)
        promised = await _answer(env, long)
        assert [(r.kind, r.text) for r in promised] == [
            ("handoff", voice.handed_off(language=LANG, agent_name=AGENT))]

        after = await _send(env, _message("e o resto?", speaker=BOB), registry["books"], bounded)
        assert (await _answer(env, after))[-1].text == "resposta a: e o resto?", (
            "the conversation waited for the turn it had handed off")

        released.set()
        await _until(lambda: bool(events))
        handle = env.client.get_workflow_handle(long.workflow_id)
        for _ in range(100):
            stands = await handle.query("where", long.id)
            if stands["state"] == door.ANSWERED:
                break
            await asyncio.sleep(0.05)
    assert stands["state"] == door.ANSWERED, stands
    assert [r["text"] for r in stands["replies"]] == ["resposta a: devagar, um levantamento"]
    assert [e.in_reply_to for e in events] == [long.id], "the late answer did not use the door"


# ── what only reads is answered beside a busy turn ──────────────────────────────────────────────

async def test_what_only_asks_to_be_SHOWN_is_answered_beside_a_busy_turn(env, registry):
    """Decision 5: nobody jumps the queue inside a group — except a read. "status" while the role
    answers somebody else is shown at once, with no turn and no model call."""
    w = _Worker()
    released = w.hold("devagar")
    async with _worker(env, w):
        await _send(env, _message("devagar, um pedido", speaker=ALICE), registry["books"])
        await _until(lambda: w.started("devagar, um pedido"))
        asked = await _send(env, _message("status", speaker=BOB), registry["books"])

        assert asked.text == "", "a read was acknowledged as if it waited"
        assert (await _answer(env, asked))[-1].text == "status: tudo em dia"
        assert w.turns[0]["end"] is None, "the read waited for the turn"
        released.set()
    assert [t["text"] for t in w.turns] == ["devagar, um pedido"]


# ── history is bounded, and nothing seen is forgotten ───────────────────────────────────────────

async def test_a_conversation_CONTINUES_AS_NEW_and_remembers_what_it_has_seen(
        env, registry, monkeypatch):
    """After `TURNS_PER_RUN` turns an idle conversation continues as new, carrying the ids it has
    seen and what it published — so a retry that arrives after the move is still one message, and
    still reads its answer. Run without the sandbox so the number can be made small."""
    monkeypatch.setattr(conversation_mod, "TURNS_PER_RUN", 2)
    w = _Worker()
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                      activities=w.activities(), workflow_runner=UnsandboxedWorkflowRunner()):
        first = await _send(env, _message("um", speaker=ALICE), registry["books"])
        answered = await _answer(env, first)
        handle = env.client.get_workflow_handle(first.workflow_id)
        run = (await handle.describe()).run_id
        await _answer(env, await _send(env, _message("dois", speaker=ALICE), registry["books"]))
        for _ in range(100):
            if (await handle.describe()).run_id != run:
                break
            await asyncio.sleep(0.05)
        assert (await handle.describe()).run_id != run, "the conversation never continued as new"

        again = await _send(env, _message("um", speaker=ALICE, id=first.id), registry["books"])
        assert again.duplicate, "the new run forgot the ids the old one had seen"
        assert await _answer(env, again) == answered
        await _answer(env, await _send(env, _message("três", speaker=ALICE), registry["books"]))
    assert [t["text"] for t in w.turns] == ["um", "dois", "três"]


# ── every transport through the one door ────────────────────────────────────────────────────────

async def test_the_PANEL_row_sends_through_the_door_and_answers_in_one_call(
        env, registry, monkeypatch):
    """Until the panel is a chat (slice 5), its box keeps working: the row sends through the door
    and waits — bounded — for the replies to its own message."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    monkeypatch.setenv(door.DEBOUNCE_ENV, "0.1")
    monkeypatch.setattr(catalog, "_product_module",
                        lambda name, **_k: (object(), registry[name], None))

    async def _connected():
        return env.client, None

    monkeypatch.setattr(catalog, "_connected", _connected)
    w = _Worker()
    async with _worker(env, w):
        outcome = await actions.perform("product_say", by=Actor(id="U0CLIENT", via="panel"),
                                        project="books", message="o extrato pode mudar?")

    assert outcome.ok, outcome.message
    assert outcome.message == "resposta a: o extrato pode mudar?"
    assert outcome.data["pending"] is False and outcome.data["acknowledged"]
    assert [(t["conversation"], t["speaker"]) for t in w.turns] == [("books", "U0CLIENT")]


@pytest.fixture
def engine_for_other_threads(env, monkeypatch):
    """What a caller with no client of its own reaches: a fresh client of THIS test's engine, made
    in the caller's own event loop (the chat adapter and `door.tell` run theirs on a thread)."""
    target = env.client.service_client.config.target_host

    async def _connect():
        return await Client.connect(target, namespace=env.client.namespace,
                                    data_converter=pydantic_data_converter)

    monkeypatch.setattr(door, "_engine", _connect)


async def test_the_CHAT_adapter_hears_the_acknowledgement_BEFORE_the_answer(
        env, registry, engine_for_other_threads, monkeypatch):
    """`channel.handle` goes through the door like every transport, and the acknowledgement
    reaches its `notify` the moment the door has it — before the slow part, where #266 slice 2
    had moved it beside the answer. Since #266 slice 6 the add-on says who its user is (`people`),
    that the role was mentioned, and its own name (`via`)."""
    from openfactory.product import channel

    class _People:
        def person_of(self, user, *, project):
            return user

    monkeypatch.setenv(door.DEBOUNCE_ENV, "0.2")
    monkeypatch.setenv(door.BOUND_ENV, "10")
    w = _Worker()
    released = w.hold("devagar")
    heard: list[str] = []
    async with _worker(env, w):
        answering = asyncio.create_task(asyncio.to_thread(
            channel.handle, registry["books"], text="devagar, o extrato", user=ALICE,
            conversation="T1", people=_People(), via="chat", mentioned=True,
            notify=heard.append))
        await _until(lambda: bool(heard) and w.started("devagar, o extrato"))
        assert not answering.done(), "the answer came before the turn was let go"
        assert heard == [voice.on_it(language=LANG, agent_name=AGENT, seed="devagar, o extrato")]
        released.set()
        said = await answering
    assert said == "resposta a: devagar, o extrato"
    assert heard == [voice.on_it(language=LANG, agent_name=AGENT, seed="devagar, o extrato")], (
        "a receipt came again beside the answer")


async def test_an_INTERNAL_EVENT_is_recorded_first_and_published_through_the_door(
        env, registry, engine_for_other_threads, monkeypatch):
    """The baseline's outcome, and anything the role says outside a turn: `door.tell` records it
    in the product's memory, then sends it through the door onto the conversation it belongs to,
    where it is published to the message it answers."""
    rows: list[dict] = []

    class _Table:
        def record(self, rec):
            rows.append({"project": rec.project, "ticket": rec.ticket, "role": rec.role,
                         "text": rec.extra.get("text")})
            return True

    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: _Table())
    w = _Worker()
    async with _worker(env, w):
        asked = await _send(env, _message("documenta o que já existe", speaker="U0ADMIN"),
                            registry["books"])
        await _answer(env, asked)
        told = await asyncio.to_thread(door.tell, registry["books"], conversation="sala",
                                       text="pronto: escrevi o que o produto faz hoje",
                                       in_reply_to=asked.id, addressed_to="U0ADMIN")
        assert told
        stands = None
        for _ in range(100):
            stands = await env.client.get_workflow_handle(asked.workflow_id).query("where",
                                                                                   asked.id)
            if stands["replies"] and stands["replies"][-1]["text"].startswith("pronto"):
                break
            await asyncio.sleep(0.05)
    assert [r["text"] for r in stands["replies"]] == ["pronto: escrevi o que o produto faz hoje"]
    assert rows == [{"project": product_key(registry["books"]), "ticket": "sala",
                     "role": "agent", "text": "pronto: escrevi o que o produto faz hoje"}]


# ── the read-only fast path, in the engine ──────────────────────────────────────────────────────

class _NoTurn:
    """A module that can be READ and must never be asked to think: every verb of a turn raises."""

    def __init__(self) -> None:
        self.released = 0

    def context(self, **_kw):
        from types import SimpleNamespace

        from openfactory.product.corpus import Corpus

        return SimpleNamespace(available=True, reason="", corpus=Corpus())

    def _never(self, *a, **k):
        raise AssertionError("the read-only path took a turn")

    answer = confirmed = settle_acceptance = draft = close_decisions_answered = _never

    def release(self):
        self.released += 1


@pytest.fixture
def recorded(monkeypatch) -> list[tuple[str, str]]:
    from openfactory.memory import transcript

    said: list[tuple[str, str]] = []
    monkeypatch.setattr(transcript, "record",
                        lambda project, *, role, text, **_k: said.append((role, text)) or "ts")
    monkeypatch.setattr(engine, "_waiting_line", lambda project: "")
    return said


def test_the_fast_path_answers_a_read_WITHOUT_a_turn_and_touches_nothing_staged(recorded):
    """No settle, no model, no staging: "status" while a proposal waits in the conversation is
    shown the status, and the proposal is still there for the yes it is waiting for."""
    from openfactory.product import staging

    project = _project()
    staging.remember("sala", {"kind": "fact", "term": "erp", "body": "usa Primavera",
                              "said_by": ""}, project=project)
    module = _NoTurn()
    try:
        replies = engine.fast(project, _message("status", speaker=BOB), module=module)

        assert replies[-1].text == voice.corpus_state(available=True, requirements=0,
                                                      promises=0, language=LANG)
        assert replies[-1].addressed_to == BOB and replies[-1].conversation == "sala"
        assert staging.pending_for("sala") is not None, "the read touched the staged proposal"
        assert recorded == [("person", "status"), ("agent", replies[-1].text)]
        assert module.released == 1
    finally:
        staging._PENDING.clear()


def test_the_fast_path_handed_something_that_is_NOT_a_read_says_so_rather_than_take_a_turn(
        recorded):
    replies = engine.fast(_project(), _message("quero um relatório mensal", speaker=BOB),
                          module=_NoTurn())

    assert [r.text for r in replies] == [voice.broke(language=LANG)]


# ── the baseline's outcome is an internal event on the conversation it was asked in ─────────────

def test_the_first_pass_reports_back_THROUGH_THE_DOOR_to_the_conversation_that_asked(
        monkeypatch):
    """The outcome of the asynchronous task the role started goes back through `door.tell` —
    recorded, then published on the conversation the request came from, answering the message
    that asked — never a bare `say` on a channel from the pass's thread."""
    from pathlib import Path

    told: list[dict] = []
    done = threading.Event()

    def _tell(project, **kw):
        told.append(kw)
        done.set()
        return True

    monkeypatch.setattr(door, "tell", _tell)

    class _Surveying:
        def baseline(self):
            from openfactory.product.authoring import WriteResult

            return WriteResult(ok=True, url="https://forge.example/pull/9")

    engine._baseline_reply(_project(), _Surveying(), AGENT, "U0ADMIN", None,
                           conversation="person:ana", room="", asked="m-7")

    assert done.wait(5), "the pass finished and never reported back"
    assert told == [{"conversation": "person:ana", "text": voice.baseline_done(
        ok=True, url="https://forge.example/pull/9", detail="", existed=False, language=LANG,
        agent_name=AGENT), "room": "", "in_reply_to": "m-7", "addressed_to": "U0ADMIN"}]
    assert "build_channel" not in Path(engine.__file__).read_text(), (
        "the engine reaches a channel again")


# ── the documented numbers are the code's ───────────────────────────────────────────────────────

def test_the_configuration_reference_documents_the_numbers_the_CODE_has():
    """ADR-0051 left the debounce, the bound and the two ceilings to be set here; an operator
    reads them in `docs/configuration.md`, and a default written in two places drifts."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "configuration.md").read_text()
    for name, value in ((door.DEBOUNCE_ENV, door.DEFAULT_DEBOUNCE_SECONDS),
                        (door.BOUND_ENV, door.DEFAULT_BOUND_SECONDS),
                        (cap.PER_PRODUCT_ENV, cap.DEFAULT_PER_PRODUCT),
                        (cap.PER_DEPLOYMENT_ENV, cap.DEFAULT_PER_DEPLOYMENT)):
        row = re.search(rf"^\| `{name}` \| `([^`]+)` \|", text, re.M)
        assert row, f"{name} is not documented"
        assert float(row.group(1)) == float(value), (name, row.group(1), value)


def test_the_door_reads_its_numbers_from_the_environment_and_refuses_nonsense(monkeypatch):
    monkeypatch.setenv(door.DEBOUNCE_ENV, "0")
    monkeypatch.setenv(door.BOUND_ENV, "0")
    got = door.Settings.from_environment()
    assert (got.debounce_seconds, got.bound_seconds) == (0.0, door.DEFAULT_BOUND_SECONDS)

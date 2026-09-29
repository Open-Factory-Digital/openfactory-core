"""A turn says what it is doing while the person waits — #395.

WHY THIS FILE EXISTS. On a live deployment a person wrote to the product role, got the receipt,
then the hand-off at the bound, then NOTHING for two to ten minutes — and concluded the product was
broken. The metrics store said otherwise: a turn is a chain of model calls (answer 143 s → draft
40 s → judge 100 s → redraft 34 s → judge …) with ~0 s of platform time between them. The engine
had two moments it could tell anybody about, "I am on it" and "here is the answer", and the
conversation even reported the role IDLE once a turn passed its bound.

WHAT IS PINNED HERE:

  - the turn reports its stages, in order, through one hook (`product/progress.py`) that the
    engine's stages and anything deeper in the turn call — and with no sink it does nothing, and a
    sink that raises costs nothing;
  - every stage the hook may name has words in every language the voice speaks;
  - on Temporal's test server, with the REAL `conversation_turn` activity, the stages reach the
    conversation's presence in order, a turn past its bound is still at work and still says what
    it is doing, the hand-off names the stage it was at, and the stage is gone with the answer;
  - no stage reaches the transcript, the outbox a chat add-on reads, the replies or the model;
  - the panel is handed the stage in its presence frame, once per change, and draws it as ONE line
    it replaces — executed under node.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project
from openfactory.product import channel, door, engine, progress, voice
from openfactory.product.engine import Message, Reply
from openfactory.product.role import ProductAnswer
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.activities import conversation_report, conversation_turn
from openfactory.runtime.temporal.conversation import ConversationWorkflow

LANG, AGENT = "pt-BR", "Nina"


def _project(name: str = "books") -> Project:
    return Project(name=name, repo_path=f"/work/{name}", language=LANG,
                   product=ProductConfig(docs_repo="acme/books-docs", admins=["U0ADMIN"],
                                         agent_name=AGENT))


class _Module:
    """The product module with the model replaced: it answers, and — asked for a request — drafts
    nothing testable, so the turn reaches the draft's stage and stages nothing."""

    def __init__(self, *, is_request: bool = False) -> None:
        self.prompts: list[str] = []
        self.is_request = is_request

    def settle_acceptance(self, text):
        return None

    def close_decisions_answered(self, *, channel=""):
        return 0

    def context(self, **_kw):
        from openfactory.product.corpus import Corpus

        return SimpleNamespace(available=True, reason="", corpus=Corpus())

    def answer(self, question, *, context="", conversation="", pending=""):
        self.prompts.append("\n".join([question, context, conversation, pending]))
        return ProductAnswer(ok=True, text="uma resposta", is_request=self.is_request)

    def draft(self, request, *, asked_by=""):
        self.prompts.append(request)
        return ProductAnswer(ok=False, error="nada testável")


@pytest.fixture
def said(monkeypatch) -> list[str]:
    """The transcript kept in a list; the project memory reads nothing."""
    from openfactory.memory import transcript

    kept: list[str] = []
    monkeypatch.setattr(transcript, "record",
                        lambda project, *, thread, role, text, **_k: kept.append(text)
                        or f"ts{len(kept)}")
    monkeypatch.setattr(transcript, "recent", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_with_elsewhere", lambda project, conversation, *a, **k:
                        conversation)
    return kept


def _message(text: str) -> Message:
    return Message(project="books", conversation="C0PROD", room="C0PROD", speaker="U0CLIENT",
                   text=text)


def _all_words() -> list[str]:
    return [voice.stage_text(s, language=lang, step=1, of=2)
            for s in progress.STAGES for lang in ("pt-BR", "en")]


# ── the hook ────────────────────────────────────────────────────────────────────────────────────

def test_a_turn_tells_its_stages_IN_ORDER_through_the_hook(said):
    """A request: the conversation is read, the model answers, then the draft — three stages, in
    the order the person waits through them, told to the sink the turn was handed."""
    told: list[tuple[str, dict]] = []
    module = _Module(is_request=True)

    replies = engine.turn(_project(), _message("preciso exportar em PDF"), module=module,
                          progress=lambda stage, counts: told.append((stage, counts)))

    assert [stage for stage, _ in told] == ["reading", "answering", "drafting"], told
    assert replies[-1].text == "uma resposta"


def test_a_stage_deeper_in_the_turn_reaches_the_same_sink_and_none_outlives_it():
    """The card loop, the module — anything the turn calls — says `progress.stage(...)` with no
    parameter threaded to it; outside the block nothing is told."""
    told: list[tuple[str, dict]] = []
    with progress.reporting(lambda stage, counts: told.append((stage, counts))):
        progress.stage("card_draft", step=1, of=2)
        progress.stage("card_review", step=1, of=2)
    progress.stage("card_review", step=2, of=2)
    assert told == [("card_draft", {"step": 1, "of": 2}), ("card_review", {"step": 1, "of": 2})]


def test_with_no_sink_nothing_happens_and_a_sink_that_raises_costs_nothing(said):
    """A chat add-on calling the engine directly hands no sink and gets the turn it always got; a
    sink that breaks costs the status, never the answer."""
    progress.stage("reading")                       # no turn, no sink: nothing, and no raise

    def _broken(stage, counts):
        raise RuntimeError("the socket went away")

    plain = engine.turn(_project(), _message("como estamos no PDF?"), module=_Module())
    broken = engine.turn(_project(), _message("como estamos no PDF?"), module=_Module(),
                         progress=_broken)
    assert [(r.kind, r.text) for r in broken] == [(r.kind, r.text) for r in plain]
    assert broken[-1].text == "uma resposta"


def test_a_stage_no_language_has_words_for_is_NOT_told():
    told: list[str] = []
    with progress.reporting(lambda stage, counts: told.append(stage)):
        progress.stage("pondering the universe")
    assert told == []


def test_every_stage_has_words_in_every_language_the_voice_speaks():
    """A surface must never show a stage as its key, nor as English to a pt-BR client."""
    for stage in progress.STAGES:
        pt = voice.stage_text(stage, language="pt-BR", step=1, of=2)
        en = voice.stage_text(stage, language="en", step=1, of=2)
        assert pt and en and pt != en, stage
        assert "{" not in pt + en, (stage, pt, en)
    assert voice.stage_text("card_review", language="pt-BR", step=1, of=2) == \
        "revisando o cartão (1/2)"
    assert voice.stage_text("card_review", language="en") == "reviewing the card (? of ?)"


def test_the_hand_off_NAMES_the_stage_and_without_one_is_the_sentence_it_always_was():
    """The one message a chat add-on hears while it waits says what the role is doing — and a turn
    that reported nothing keeps the sentence every transport already knows."""
    words = voice.stage_text("card_review", language="pt-BR", step=1, of=2)
    named = voice.handed_off(language="pt-BR", agent_name=AGENT, stage=words)
    assert named.startswith("Nina: ") and "agora estou revisando o cartão (1/2)" in named
    assert voice.handed_off(language="pt-BR", agent_name=AGENT) == (
        "Nina: " + voice._HANDED_OFF["pt-BR"])
    assert "right now I am reading the board" in voice.handed_off(
        language="en", stage=voice.stage_text("board", language="en"))


# ── nothing a stage says is a reply, a record or a prompt ───────────────────────────────────────

def test_no_stage_reaches_the_transcript_the_replies_or_the_model(said):
    module = _Module(is_request=True)
    replies = engine.turn(_project(), _message("preciso exportar em PDF"), module=module,
                          progress=lambda stage, counts: None)
    everything = json.dumps([said, [r.text for r in replies], module.prompts], ensure_ascii=False)
    leaked = [w for w in _all_words() if w in everything]
    assert not leaked, leaked


def test_a_chat_add_on_WITHOUT_a_status_line_is_not_spammed(said):
    """The stages are not replies, so a surface that can only post messages gets exactly what it
    got before: the one receipt and the answer — never a message per stage."""
    notified: list[str] = []
    told: list[str] = []
    replies = engine.turn(_project(), _message("preciso exportar em PDF"),
                          module=_Module(is_request=True),
                          progress=lambda stage, counts: told.append(stage))
    out = channel.deliver(replies, notify=notified.append)
    assert len(told) == 3, told
    assert [r.kind for r in replies] == ["receipt", "answer"]
    assert len(notified) == 1 and out == "uma resposta"


# ── the worker tells it the moment it changes ───────────────────────────────────────────────────

async def test_the_activity_tells_each_stage_WHEN_it_changes_not_at_the_next_pulse(monkeypatch):
    """The turn's thread says a stage; the activity's loop is woken by it and tells the
    conversation at once — the heartbeat pulse is five seconds, and a stage that waited for it
    would be a stage late by five seconds. The same stage said twice is told once, and a `tell`
    that fails is tried no more and costs the turn nothing."""
    monkeypatch.setattr(acts.activity, "heartbeat", lambda *a: None)
    stages = acts._Stages(asyncio.get_running_loop(), "pt-BR")
    told: list[tuple[float, str, str]] = []
    start = time.monotonic()

    async def _tell(stage, words):
        told.append((time.monotonic() - start, stage, words))

    def _work(_abandoned):
        stages.say("reading", {})
        time.sleep(0.3)
        stages.say("reading", {})
        time.sleep(0.3)
        stages.say("card_review", {"step": 2, "of": 2})
        time.sleep(0.3)
        return "a resposta"

    assert await acts._turning(_work, "a turn", stages=stages, tell=_tell) == "a resposta"
    assert [(s, w) for _at, s, w in told] == [("reading", "lendo a conversa"),
                                              ("card_review", "revisando o cartão (2/2)")]
    assert all(at < 2.0 for at, _s, _w in told), f"a stage waited for the pulse: {told}"

    calls: list[str] = []

    async def _broken(stage, words):
        calls.append(stage)
        raise RuntimeError("the engine went away")

    stages = acts._Stages(asyncio.get_running_loop(), "pt-BR")

    def _again(_abandoned):
        stages.say("reading", {})
        time.sleep(0.2)
        stages.say("board", {})
        time.sleep(0.2)
        return "ainda a resposta"

    assert await acts._turning(_again, "a turn", stages=stages, tell=_broken) == \
        "ainda a resposta"
    assert calls == ["reading"], "a tell that failed was tried again"


async def test_a_SLOW_tell_never_holds_the_heartbeat_past_the_pulse(monkeypatch):
    """THE HEARTBEAT IS WHAT KEEPS THE TURN ALIVE (review of #398). A status signal awaited in the
    heartbeat's own loop made the gap between two beats as long as the signal took — measured at
    8.31 s for an 8 s tell, with no ceiling, and at `conversation.HEARTBEAT` the engine re-runs the
    turn on another worker. Here the pulse is shrunk to 0.2 s and every tell sleeps 1.5 s: the
    largest gap between two beats must stay within the pulse, and the stage is still told."""
    monkeypatch.setattr(acts, "_TURN_PULSE", 0.2)
    beats: list[float] = []
    monkeypatch.setattr(acts.activity, "heartbeat", lambda *a: beats.append(time.monotonic()))
    stages = acts._Stages(asyncio.get_running_loop(), "pt-BR")
    told: list[str] = []

    async def _slow(stage, words):
        await asyncio.sleep(1.5)
        told.append(stage)

    def _work(_abandoned):
        stages.say("reading", {})
        time.sleep(2.0)
        return "a resposta"

    assert await acts._turning(_work, "a turn", stages=stages, tell=_slow) == "a resposta"
    gap = max(b - a for a, b in zip(beats, beats[1:], strict=False))
    assert gap <= 0.2 + 0.15, f"a slow tell held the heartbeat for {gap:.2f} s: {beats}"
    assert told == ["reading"]


async def test_a_tell_that_NEVER_answers_is_given_up_and_the_turn_goes_on_untold(monkeypatch):
    """A tell that hangs is bounded by `_TELL_WITHIN` and then counts as one that failed: no more
    tells for this turn, and the turn's answer is untouched."""
    monkeypatch.setattr(acts, "_TURN_PULSE", 0.2)
    monkeypatch.setattr(acts, "_TELL_WITHIN", 0.3)
    monkeypatch.setattr(acts.activity, "heartbeat", lambda *a: None)
    stages = acts._Stages(asyncio.get_running_loop(), "pt-BR")
    calls: list[str] = []
    start = time.monotonic()
    given_up: list[float] = []

    async def _hung(stage, words):
        calls.append(stage)
        try:
            await asyncio.sleep(5)   # far past `_TELL_WITHIN`, and bounded so a mutant cannot hang
        except asyncio.CancelledError:
            given_up.append(time.monotonic() - start)
            raise

    def _work(_abandoned):
        stages.say("reading", {})
        time.sleep(0.6)
        stages.say("board", {})
        time.sleep(0.4)
        return "a resposta"

    assert await acts._turning(_work, "a turn", stages=stages, tell=_hung) == "a resposta"
    assert calls == ["reading"], "a tell that timed out was tried again"
    assert given_up and given_up[0] < 0.8, \
        f"the hung tell was held until the turn ended, not given up at its bound: {given_up}"


# ── the conversation keeps it, shows it, and forgets it with the answer ─────────────────────────


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture
def registry(monkeypatch, tmp_path) -> Project:
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    books = _project()
    ProjectRegistry(path).add(books)
    return books


class _Turn:
    """The engine's turn behind the REAL activity, stood in for: it tells a stage, waits for the
    test to let it go on, tells the next, and answers. Called on the activity's thread with the
    activity's own sink — so what is pinned is the activity's plumbing, not a double of it."""

    def __init__(self) -> None:
        self.go = [threading.Event(), threading.Event()]

    def __call__(self, project, inp, *, abandoned=None, progress=None, again=False):
        progress("reading", {})
        self.go[0].wait(20)
        progress("card_review", {"step": 1, "of": 2})
        self.go[1].wait(20)
        return [Reply(text=f"resposta a: {inp.text}", addressed_to=inp.speaker,
                      in_reply_to=inp.id, conversation=inp.conversation)]


async def _presence_until(handle, wanted, *, within: float = 15.0) -> dict:
    deadline = time.monotonic() + within
    while True:
        got = await handle.query("watch", 0)
        if wanted(got["presence"]):
            return got
        if time.monotonic() > deadline:
            raise AssertionError(f"waited {within}s; the presence stayed {got['presence']}")
        await asyncio.sleep(0.05)


@pytest.mark.owns_its_engine
async def test_the_stages_reach_the_presence_in_order_PAST_the_bound_and_go_with_the_answer(
        env, registry, monkeypatch):
    """The real `conversation_turn` signals its own conversation as the turn moves on. Before the
    bound the running turn says it is reading; at the bound the hand-off names where it is; past
    the bound the role is still at work and its stage keeps moving; the answer takes it away — and
    no stage was ever an entry a transport could publish."""
    turn = _Turn()
    monkeypatch.setattr(acts, "_conversation_turn", turn)
    # REAL SECONDS: the stage reaches the conversation in a fraction of one, well inside the bound
    bounded = door.Settings(debounce_seconds=0.1, bound_seconds=3.0)
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                      activities=[conversation_turn, conversation_report]):
        ack = await door.receive(Message(project="books", conversation="sala", speaker="U0ANA",
                                         text="abre um cartão", via="panel", mentions_role=True),
                                 project=registry, client=env.client, settings=bounded)
        handle = env.client.get_workflow_handle(ack.workflow_id)

        reading = voice.stage_text("reading", language=LANG)
        first = await _presence_until(handle, lambda p: p["stage"] == reading)
        # running, or already past the bound — the test server skips time — but at work either way
        assert first["presence"]["working"] == 1

        promised = await door.wait(ack, client=env.client, bound=15)
        assert [(r.kind, r.text) for r in promised] == [
            ("handoff", voice.handed_off(language=LANG, agent_name=AGENT, stage=reading))]

        turn.go[0].set()
        reviewing = voice.stage_text("card_review", language=LANG, step=1, of=2)
        late = await _presence_until(handle, lambda p: p["stage"] == reviewing)
        assert not late["presence"]["running"] and late["presence"]["working"] == 1, (
            "a turn past its bound read as a role with nothing to do")

        turn.go[1].set()
        done = await _presence_until(handle, lambda p: p["working"] == 0)
        assert done["presence"]["stage"] == ""
        stands = await handle.query("where", ack.id)
        assert [r["text"] for r in stands["replies"]] == ["resposta a: abre um cartão"]

        published = json.dumps([e for e in done["entries"] if e.get("type") == "replies"],
                               ensure_ascii=False)
        assert reviewing not in published, "a stage was published as something the role said"


@pytest.mark.owns_its_engine
async def test_a_turn_answered_INSIDE_its_bound_leaves_no_stage_behind(env, registry, monkeypatch):
    """The common case: the turn tells its stages and answers before the bound. The moment its
    answer is published the conversation says nothing is at work — a stage left up would tell the
    person the role is still busy on a question it has answered."""
    turn = _Turn()
    for go in turn.go:
        go.set()
    monkeypatch.setattr(acts, "_conversation_turn", turn)
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                      activities=[conversation_turn, conversation_report]):
        ack = await door.receive(Message(project="books", conversation="sala", speaker="U0ANA",
                                         text="e o PDF?", via="panel", mentions_role=True),
                                 project=registry, client=env.client,
                                 settings=door.Settings(debounce_seconds=0.1, bound_seconds=30.0))
        replies = await door.wait(ack, client=env.client, bound=15)
        assert [r.kind for r in replies] == ["answer"]
        got = await env.client.get_workflow_handle(ack.workflow_id).query("watch", 0)
    assert got["presence"]["working"] == 0 and got["presence"]["stage"] == "", got["presence"]


@pytest.mark.owns_its_engine
async def test_a_stage_for_a_turn_the_conversation_is_not_waiting_on_is_dropped(env, registry):
    """A stage that arrives after its turn's answer — or for a turn never started here — must not
    put a status back up that nothing will ever take down."""
    from openfactory.runtime.temporal.io import TurnProgress

    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ConversationWorkflow],
                      activities=[conversation_turn, conversation_report]):
        ack = await door.receive(Message(project="books", conversation="sala", speaker="U0ANA",
                                         text="status", via="panel", mentions_role=True),
                                 project=registry, client=env.client)
        handle = env.client.get_workflow_handle(ack.workflow_id)
        await handle.signal("progress", TurnProgress(turn="nobody", stage="board",
                                                     words="lendo o quadro"))
        got = await handle.query("watch", 0)
    assert got["presence"]["stage"] == "" and got["presence"]["working"] == 0


# ── the panel: one status line, replaced ────────────────────────────────────────────────────────

def test_the_presence_frame_carries_the_stage_while_the_role_thinks_and_only_then():
    from openfactory.api.product_chat import presence_for

    raw = {"running": True, "fast": 0, "waiting": [], "working": 1, "stage": "lendo o quadro"}
    assert presence_for(raw, "ana") == {"kind": "presence", "state": "thinking", "ahead": 0,
                                        "stage": "lendo o quadro"}
    past_the_bound = {"running": False, "fast": 0, "waiting": [], "working": 1,
                      "stage": "revisando o cartão (1/2)"}
    assert presence_for(past_the_bound, "ana")["state"] == "thinking"
    assert presence_for({"running": False, "fast": 0, "waiting": [], "working": 0,
                         "stage": "lendo o quadro"}, "ana") == {
        "kind": "presence", "state": "idle", "ahead": 0}


async def test_each_stage_is_handed_ONCE_and_the_next_replaces_it():
    """The hub hands a subscriber a presence only when it changed: the same stage read on every
    tick is one frame, and a new stage is the next frame — a line replaced, not a bubble a tick."""
    from openfactory.api.product_chat import ProductChat, Subscriber, presence_for

    hub = ProductChat()
    sub = Subscriber(person="ana", own="person:ana", product="books", project="books",
                     conversation="books", may_read_room=True, frames=asyncio.Queue(), held=None)
    reading = {"running": True, "fast": 0, "waiting": [], "working": 1, "stage": "lendo o quadro"}
    board = {**reading, "stage": "escrevendo a proposta"}
    for raw in (reading, reading, reading, board, board):
        hub._put(sub, presence_for(raw, "ana"), presence=True)
    frames = []
    while not sub.frames.empty():
        frames.append(sub.frames.get_nowait())
    assert [f.get("stage") for _generation, f in frames] == ["lendo o quadro",
                                                           "escrevendo a proposta"]


def test_the_page_draws_the_stage_as_ONE_line_and_a_later_presence_replaces_it():
    from tests.test_the_panel_is_a_chat import _run

    got = _run("""nodes['#prodThread']=node();_pc.live=true;_pc.agentName='Nina';
      _pc.items.push({who:'me',text:'abre um cartão',id:'m1'});
      pchatFrame({kind:'presence',state:'thinking',ahead:0,stage:'lendo o quadro'});
      const one=pchatPresenceText();
      pchatFrame({kind:'presence',state:'thinking',ahead:0,stage:'revisando o cartão (1/2)'});
      const two=pchatPresenceText(),html=nodes['#prodThread'].innerHTML;
      pchatFrame({kind:'presence',state:'thinking',ahead:0});
      const three=pchatPresenceText();
      pchatFrame({kind:'presence',state:'thinking',ahead:1,stage:'lendo o quadro'});
      return {one,two,three,queued:pchatPresenceText(),html}""", pathname="/product/books")
    assert got["one"] == "Nina — lendo o quadro…"
    assert got["two"] == "Nina — revisando o cartão (1/2)…"
    assert "revisando o cartão (1/2)" in got["html"] and "lendo o quadro" not in got["html"], (
        "the page kept the old stage beside the new one")
    assert got["three"] == "Nina is thinking…"
    assert got["queued"] == "Nina is busy — yours is next", "a stage hid the person's place"

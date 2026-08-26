"""Every question was turn one, and the transcript was already being written (#168).

THE OWNER'S QUESTION that produced this: *"I've built chat systems with memory before and I don't
remember having to worry about dialogue fluidity — I gave the agent TOOLS and it worked. Today we
hit misunderstandings that looked to me like a lack of tool-calling."*

A five-agent analysis of this codebase agreed with the symptom and located the cause one layer
down. Part of it is not about tools at all: `_remember` writes BOTH halves of every tech-lead
exchange into the message store (`catalog.py`), the panel paints them as a thread — and nothing
under `openfactory/techlead/` ever read them back. The role answered every question as a stranger.

That is #159 measured: it dictated `reply resume #103 in Slack` after having been told, in the
same thread, that this deployment has no Slack. A person does not do that. Neither does a role
with a memory.

RENDERED AT THE DOOR AND CARRIED AS DATA, exactly like `can`: the store lives where the question
arrived, and the worker must not acquire a second way to reach it. Bounded in CHARACTERS, because
token-efficiency is one of the three promises this product sells.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openfactory.util import scratch

# ── 1. the thread reaches the prompt ────────────────────────────────────────────────────────────

def _context_built(monkeypatch, *, thread: str) -> str:
    """Drive `_answer` and capture the context string the harness is actually handed.

    BEHAVIOURAL, because the source-reading version of this could not see its own cut: `thread`
    appears in `_answer`'s SIGNATURE, so a mutation deleting it from the prompt left the assertion
    green. Two of the ten mutations survived on exactly that, which is the recurring shape here —
    a guard that reads code instead of running it ([[built-tested-reached-by-nothing]]).

    `build_techlead` is imported INSIDE `_answer`, so the patch target is the source module, not
    this one ([[a-negative-guard-needs-a-positive-twin]], last corollary)."""
    import openfactory.adapters.agent as agent_registry
    from openfactory.techlead import conversation

    seen: dict[str, str] = {}

    class _Harness:
        def chat(self, *, sandbox, workspace, question, context):
            seen["context"] = context
            return {"text": "ok"}

    monkeypatch.setattr(conversation, "gather_jobs", lambda p: [])
    # A SCRATCH DIR, NEVER "/tmp". `_answer` owns what `clone_repo` hands back and deletes it
    # recursively in a `finally`; this line used to say "/tmp", so the suite ran
    # `rmtree("/tmp")`. Harmless-looking on macOS, where pytest keeps its files under
    # /private/var/folders — on Linux it deleted pytest's own temp root and failed 898 later
    # tests (2026-08-21). `util/scratch.discard` now refuses it; this keeps the stub honest.
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda p: (scratch.make("test-memory"), False))
    monkeypatch.setattr(conversation, "comment_digest", lambda jobs: "")
    monkeypatch.setattr(conversation, "answer_text", lambda res: "an answer")
    monkeypatch.setattr(agent_registry, "build_techlead", lambda p: _Harness())

    conversation._answer(_Project(), "why is #7 parked?", cap=None, can=("resume",),
                         thread=thread)
    return seen.get("context", "")


class _Project:
    name = "demo"
    repo_path = "/tmp/demo"


def test_the_thread_REACHES_the_prompt(monkeypatch):
    built = _context_built(monkeypatch, thread="## The conversation so far\nyou: I said this before")

    assert "I said this before" in built, (
        "the thread is carried all the way to the harness and then not put in the prompt")


def test_and_it_lands_ABOVE_the_snapshot(monkeypatch):
    """A correction issued two turns ago must outrank the stale fact it corrected. Where it sits
    relative to the platform's own GUIDANCE is not asserted: orders-then-history reads as well as
    history-then-orders, and a guard for a claim nobody can justify is decoration."""
    built = _context_built(monkeypatch, thread="MARKER-THREAD")

    assert built.index("MARKER-THREAD") < built.index("Current jobs"), (
        "the conversation is rendered below the snapshot, where a stale fact outranks a correction")


def test_no_thread_adds_NO_empty_scaffolding(monkeypatch):
    """A blank heading tells a model there was a conversation it cannot see."""
    built = _context_built(monkeypatch, thread="")

    assert built.startswith(_context_built(monkeypatch, thread="")[:40])
    assert "conversation so far" not in built.lower()


def test_the_answer_port_accepts_it_and_defaults_to_none():
    """A caller that knows nothing about threads must keep working — every existing one does."""
    from openfactory.techlead import conversation

    sig = inspect.signature(conversation.answer)
    assert "thread" in sig.parameters
    assert sig.parameters["thread"].default == ""


def test_the_worker_hop_carries_it():
    """`AskInput` is the only channel between the door and the worker. A field the activity does
    not forward is a field that does not exist."""
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import AskInput

    assert "thread" in AskInput.model_fields
    assert AskInput(project="p", question="q").thread == "", (
        "an AskWorkflow already in flight must deserialise into the behaviour it started with")
    src = inspect.getsource(activities.techlead_ask)
    assert "inp.thread" in src, "the activity drops the thread on the floor"


def test_the_DOOR_is_what_reads_the_store():
    """Authority and now history are both resolved where the request arrived. A worker that read
    the store itself would be a second way to reach it — the arrangement `can` exists to avoid."""
    from openfactory.actions import catalog

    ask = inspect.getsource(catalog._ask)
    assert "_thread_so_far" in ask
    tree = ast.parse(inspect.cleandoc("\n" + ask))
    call = next((n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "AskInput"), None)
    assert call is not None, "the door no longer builds an AskInput — this guard measures nothing"
    assert {k.arg for k in call.keywords} >= {"can", "thread"}, (
        "the door decides authority and history in one place, and passes both as data")


# ── 2. it is bounded, and it degrades ───────────────────────────────────────────────────────────

def test_the_thread_is_bounded_in_characters():
    """A turn can be one word or a whole diagnosis, so a turn count bounds nothing. Token
    efficiency is a promise this product sells, not a preference."""
    from openfactory.actions import catalog

    assert isinstance(catalog._THREAD_BUDGET, int) and 0 < catalog._THREAD_BUDGET <= 8000
    src = inspect.getsource(catalog._thread_so_far)
    assert "budget=_THREAD_BUDGET" in src, "the read is unbounded — every long thread is a bill"


def test_a_store_that_will_not_answer_costs_the_thread_and_not_the_ANSWER(monkeypatch):
    """The posture `_remember` takes one function down: losing the record of a conversation is a
    bad day; refusing to answer because of it is a worse one."""
    from openfactory.actions import catalog
    from openfactory.memory import transcript

    def _boom(*a, **k):
        raise RuntimeError("the store is gone")

    monkeypatch.setattr(transcript, "of_messages", _boom)
    assert catalog._thread_so_far("demo") == ""


def test_the_question_just_asked_is_not_read_back_as_history(monkeypatch):
    """`_remember` writes the question BEFORE the agent runs, so without this the model sees it
    twice — once as the question and once as something it apparently already answered."""
    from openfactory.actions import catalog
    from openfactory.memory import transcript

    class _T:
        def __init__(self, role, text):
            self.role, self.text, self.actor, self.ts = role, text, "", ""

    monkeypatch.setattr(transcript, "of_messages",
                        lambda *a, **k: [_T("person", "older question"),
                                         _T("agent", "older answer"),
                                         _T("person", "the one just asked")])
    rendered = catalog._thread_so_far("demo", without="the one just asked")
    assert "older question" in rendered and "older answer" in rendered
    assert "the one just asked" not in rendered


# ── 2b. IT READS THE STORE THE TECH-LEAD ACTUALLY WRITES TO ────────────────────────────────────
#
# THE DEFECT THIS SECTION EXISTS FOR, found by running the fix on the live pilot rather than by any
# test here: the first wiring called `transcript.recent`, which reads the OBSERVABILITY records the
# product channel writes. The tech-lead's turns go to `memory.messages` through `_remember` — the
# same rows the panel paints. Sixty-four rows sat in the store and the thread came back EMPTY, and
# every unit guard above stayed green because they stub the reader. Built, tested, reached by
# nothing — in the change written to fix a role that could not remember.

class _Store:
    """The message store in memory, in the shape `messages.read(scan=…)` takes — the same fake the
    staged-decision suite uses, so this guard exercises the real parser and the real kinds."""

    def __init__(self):
        self.rows: list[dict] = []

    def record(self, rec) -> bool:
        self.rows.append({"kind": rec.kind, "pk": rec.project, "ts": rec.ts,
                          "extra": dict(rec.extra)})
        return True

    def scan(self):
        return list(self.rows)


def test_the_reader_reads_the_STORE_THE_TECHLEAD_WRITES_TO():
    """Driven through the real writers and the real parser: `_remember`'s own rows must come back."""
    from openfactory.memory import messages, transcript

    store = _Store()
    messages.told("demo", "is #7 stuck?", by="somebody", channel="demo", sink=store)
    messages.say("demo", "it is waiting on CI", channel="demo", sink=store)

    turns = transcript.of_messages("demo", budget=4000, scan=store.scan)

    assert [t.text for t in turns] == ["is #7 stuck?", "it is waiting on CI"], turns
    assert [t.role for t in turns] == ["person", "agent"], (
        "who said what is lost — a thread that cannot tell the client from the factory is worse "
        "than none")


def test_the_machinery_rows_are_not_conversation():
    """The same store carries staged questions and recorded answers. They are plumbing; rendering
    them as turns would teach the model to answer its own bookkeeping."""
    from openfactory.memory import messages, transcript

    store = _Store()
    messages.told("demo", "a real turn", by="somebody", channel="demo", sink=store)
    messages.ask("demo", "approve this?", token="t1", approve="yes", reject="no",
                 channel="demo", sink=store)
    messages.answer("demo", token="t1", answer="approve", by="somebody", sink=store)

    kept = [t.text for t in transcript.of_messages("demo", budget=4000, scan=store.scan)]
    assert kept == ["a real turn"], kept


def test_the_budget_keeps_the_RECENT_end():
    """Trimming from the front would keep the opening of a long conversation and drop what was
    just said — the half that carries the thread."""
    from openfactory.memory import messages, transcript

    store = _Store()
    for i in range(12):
        messages.told("demo", f"turn-{i:02d} " + "x" * 80, by="somebody", channel="demo",
                      sink=store, now=f"2026-08-20T00:{i:02d}:00+00:00")

    kept = [t.text for t in transcript.of_messages("demo", budget=300, scan=store.scan)]

    assert kept, "the budget dropped everything"
    assert "turn-11" in kept[-1], f"the newest turn was trimmed away: {kept}"
    assert not any("turn-00" in k for k in kept), "the oldest survived a budget it should not fit"


# ── 3. the renderer stopped welding one language ────────────────────────────────────────────────

def test_the_transcript_block_speaks_the_CALLERS_language():
    """It was hard-coded Portuguese — right for the product role answering a pt-BR client, wrong
    for the tech-lead, whose whole surface is English by design (#160's class, one instance)."""
    from openfactory.memory import transcript

    class _T:
        role, text, actor, ts = "person", "oi", "", ""

    default = transcript.render([_T()])
    assert "Conversa até aqui" not in default, "the neutral default still speaks one client's tongue"

    theirs = transcript.render([_T()], heading="## Conversa até aqui", somebody="pessoa")
    assert "Conversa até aqui" in theirs and "pessoa" in theirs, (
        "the product channel can no longer say it in the client's language")


@pytest.mark.parametrize("turns", [[], None])
def test_an_empty_thread_renders_NOTHING_rather_than_a_heading(turns):
    """A heading with no turns under it tells a model there was a conversation it cannot see."""
    from openfactory.memory import transcript

    assert transcript.render(turns or []) == ""

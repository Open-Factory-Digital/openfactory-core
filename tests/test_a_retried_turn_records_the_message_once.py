"""A turn run again after its worker died records the person's message ONCE (#394).

WHAT HAPPENED. A person sent "sim, confirmo." in a panel conversation. The turn was calling the
model when the worker container was recreated six minutes later; Temporal handed the turn to the
new worker (`TURN_RETRY`), which answered. The conversation's transcript then held the person's
message twice — one row at the moment it was sent, a second, same text, five seconds after the new
worker took the turn — and every later turn read the person repeating themselves. The retry's own
prompt carried it twice as well: once as history (the first attempt's row) and once as the
question, because the history left out only the row the SECOND write had just returned.

THE CAUSE is a key made of the moment of the WRITE: a row is `<ts>#<ticket>#<role>`, `ts` was
`now()`, and a second run of the same write was a second row. The message now carries when it was
SAID (`Message.at`, stamped where it arrived) through the conversation to the worker, and the row
is written under that moment — so both sinks' put, which replaces on the key, makes the retry land
on the first attempt's row.

Everything here runs the real paths: the worker's activity under Temporal's own test environment
(so the attempt number is the one Temporal hands a retry), the engine, the transcript and a real
SQLite store. Only the model is replaced.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from openfactory.memory import transcript

#: When the person pressed send — the door's moment, not any worker's.
SAID = "2026-09-28T21:39:25.123456+00:00"


class _WorkerLost(BaseException):
    """The container going away mid-turn: nothing in the engine catches it, as nothing in a killed
    process catches anything."""


class _Model:
    """The product module with the model replaced. `die` makes the next answer take the worker
    down; `says` is what it answers; `heard` keeps the history each answer was handed."""

    def __init__(self, says: str = "resposta", *, die: bool = False):
        from openfactory.product.role import ProductAnswer

        self._answer = ProductAnswer
        self.says, self.die = says, die
        self.heard: list[str] = []

    def settle_acceptance(self, text, **_k):
        return None

    def close_decisions_answered(self, **_k):
        return 0

    def record_decisions(self, labels, **_k):
        return 0

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def answer(self, question, *, conversation="", pending="", **_k):
        self.heard.append(conversation)
        if self.die:
            raise _WorkerLost()
        return self._answer(ok=True, text=self.says)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real SQLite store — `INSERT OR REPLACE` on `(pk, sk)`, as the deployment's — and the
    project's memory and state under `tmp_path`."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product import cap, staging

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr("openfactory.paths.project_memory_dir", lambda _p: tmp_path / "memory")
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()
    cap.reset()
    project = Project(name="acme", repo_path=str(tmp_path / "repo"), language="pt-BR",
                      tracker=ProviderRef(kind="github", repo="a/b"),
                      forge=ProviderRef(kind="github", repo="a/b"),
                      product=ProductConfig(docs_repo="acme/docs", agent_name="Clara"))
    yield project
    staging._PENDING.clear()
    staging._EXPIRED_TOMBSTONES.clear()
    cap.reset()


def _lines(project, role: str) -> list[dict]:
    """What memory holds for `role`, as every reader sees it: a row with no text is nobody's."""
    found, _full = transcript.rows(project)
    return [r for r in found if r.get("role") == role
            and str((r.get("extra") or {}).get("text", "")).strip()]


def _input(project, *, id: str = "m1", text: str = "sim, confirmo.", at: str = SAID):
    from openfactory.product.key import product_key
    from openfactory.runtime.temporal.io import TurnInput

    return TurnInput(product=product_key(project), project=project.name, conversation="c1",
                     speaker="ana", text=text, id=id, ids=[id], via="panel", at=at)


async def _attempt(project, monkeypatch, inp, model: _Model, *, attempt: int):
    """ONE ATTEMPT of the worker's `conversation_turn`, as Temporal runs it — the attempt number is
    the one Temporal's own activity environment hands the activity."""
    from temporalio.testing import ActivityEnvironment

    from openfactory.product import module as module_mod
    from openfactory.runtime.temporal import activities

    monkeypatch.setattr(activities, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: project))
    monkeypatch.setattr(module_mod, "ProductModule", lambda _p, *, via="api": model)
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=attempt)
    return await env.run(activities.conversation_turn, inp)


# ── the defect as it happened ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_turn_whose_worker_died_mid_answer_leaves_one_line_for_the_person(
        store, monkeypatch):
    first = _Model(die=True)
    with pytest.raises(_WorkerLost):
        await _attempt(store, monkeypatch, _input(store), first, attempt=1)
    assert len(_lines(store, "person")) == 1, "the first attempt did not record on arrival"

    again = _Model("Registrado.")
    out = await _attempt(store, monkeypatch, _input(store), again, attempt=2)

    people = _lines(store, "person")
    assert [r["extra"]["text"] for r in people] == ["sim, confirmo."], (
        "the retried turn recorded the person's message a second time")
    assert people[0]["ts"] == SAID, "the line is not under the moment the person said it"
    assert [r["extra"]["text"] for r in _lines(store, "agent")] == ["Registrado."]
    assert [r["text"] for r in out["replies"]] == ["Registrado."]
    # AND THE RETRY'S OWN PROMPT: the message is the question, never also its own history
    assert "sim, confirmo." not in again.heard[-1], (
        "the retried turn handed the model the person's message as history AND as the question")


@pytest.mark.asyncio
async def test_a_retry_after_the_answer_was_recorded_keeps_the_answer_the_person_was_shown(
        store, monkeypatch):
    """The first attempt answered and recorded it, and its worker died before Temporal heard
    back. The conversation publishes the SECOND attempt's answer, so that is the one memory keeps
    — one answer to one message."""
    await _attempt(store, monkeypatch, _input(store), _Model("primeira resposta"), attempt=1)
    await _attempt(store, monkeypatch, _input(store), _Model("segunda resposta"), attempt=2)

    assert len(_lines(store, "person")) == 1
    answers = _lines(store, "agent")
    assert [r["extra"]["text"] for r in answers] == ["segunda resposta"], (
        "memory keeps an answer the person never saw, beside the one they did")
    assert answers[0]["extra"].get("in_reply_to") == "m1"


@pytest.mark.asyncio
async def test_a_retry_withdraws_only_the_answer_to_its_own_message(store, monkeypatch):
    """Two turns answering two messages keep both answers; a retry of the second replaces the
    second's answer and never touches the first's."""
    second = _input(store, id="m2", text="e o segundo?", at="2026-09-28T21:50:00+00:00")
    await _attempt(store, monkeypatch, _input(store, id="m1", at=SAID), _Model("um"), attempt=1)
    await _attempt(store, monkeypatch, second, _Model("dois"), attempt=1)
    assert [r["extra"]["text"] for r in _lines(store, "agent")] == ["um", "dois"]
    await _attempt(store, monkeypatch, second, _Model("dois, de novo"), attempt=2)
    assert [r["extra"]["text"] for r in _lines(store, "agent")] == ["um", "dois, de novo"]
    assert len(_lines(store, "person")) == 2


@pytest.mark.asyncio
async def test_a_person_who_really_says_it_again_is_heard_twice(store, monkeypatch):
    """Keyed by the MESSAGE, never by its words: the same text in a new message is a new line."""
    await _attempt(store, monkeypatch, _input(store, id="m1", at=SAID), _Model(), attempt=1)
    await _attempt(store, monkeypatch, _input(store, id="m2", at="2026-09-28T21:41:02+00:00"),
                   _Model(), attempt=1)
    assert [r["extra"]["text"] for r in _lines(store, "person")] == ["sim, confirmo."] * 2


# ── the other writes of the same class ──────────────────────────────────────────────────────────

def test_the_read_only_answer_run_twice_leaves_one_line_each(store, monkeypatch):
    from openfactory.product import engine

    monkeypatch.setattr(engine, "reads_only", lambda _t: True)
    answers = iter(["tudo certo", "tudo certo, de novo"])
    monkeypatch.setattr(engine, "intents", lambda _ex: next(answers))
    message = engine.Message(id="m9", project="acme", conversation="c1", speaker="ana",
                             text="status", at=SAID)
    engine.fast(store, message, module=_Model())
    engine.fast(store, message, module=_Model(), again=True)
    assert [(r["ts"], r["extra"]["text"]) for r in _lines(store, "person")] == [(SAID, "status")]
    assert [r["extra"]["text"] for r in _lines(store, "agent")] == ["tudo certo, de novo"]


@pytest.mark.asyncio
async def test_a_message_kept_for_the_room_and_retried_is_one_line(store, monkeypatch):
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import OverheardInput

    monkeypatch.setattr(activities, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: store))
    kept = OverheardInput(project="acme", conversation="room", speaker="bruno",
                          text="alguém viu o relatório?", id="m5", at=SAID)
    await activities.conversation_overheard(kept)
    await activities.conversation_overheard(kept)
    found, _full = transcript.rows(store)
    assert [(r["ts"], r["extra"]["text"]) for r in found] == [(SAID, "alguém viu o relatório?")]


def test_an_intake_notes_a_message_once_and_a_new_message_again(tmp_path, monkeypatch):
    from openfactory.contracts.project import Project
    from openfactory.product import case

    monkeypatch.setattr(case, "_path", lambda _p: tmp_path / "cases.json")
    project = Project(name="notes", repo_path=str(tmp_path))
    answer = SimpleNamespace(text="Qual tela?", reading=None)
    case.note_turn(project, "c1", "ana", "o relatório quebra", answer, now=100.0, message_id="m1")
    again = case.note_turn(project, "c1", "ana", "o relatório quebra", answer, now=160.0,
                           message_id="m1")
    assert again.facts == ["o relatório quebra"], "the retried turn noted the words twice"
    assert again.asked == ["Qual tela?"]
    later = case.note_turn(project, "c1", "ana", "o relatório quebra", answer, now=200.0,
                           message_id="m2")
    assert later.facts == ["o relatório quebra"] * 2


# ── the key, in both sinks' shape ───────────────────────────────────────────────────────────────

def test_the_same_turn_written_twice_has_one_key_in_every_sink(monkeypatch):
    """SQLite's `INSERT OR REPLACE` and DynamoDB's `put_item` both replace on `(pk, sk)`, and both
    take it from `MetricRecord.dynamo_key()`: two writes of one turn must produce one key there,
    and two turns said at different moments two keys."""
    from openfactory.observability.metrics import InMemoryMetricsSink
    from tests.the_sink_door import SINK_DOOR

    sink = InMemoryMetricsSink()
    monkeypatch.setattr(SINK_DOOR, lambda *a, **k: sink)
    for _ in range(2):
        assert transcript.record("acme", thread="c1", role="person", text="sim", at=SAID) == SAID
    transcript.record("acme", thread="c1", role="person", text="sim",
                      at="2026-09-28T21:41:02+00:00")
    keys = [(r.dynamo_key()["pk"], r.dynamo_key()["sk"]) for r in sink.records]
    assert keys[0] == keys[1] and keys[2] != keys[0]
    assert sink.records[0].expires_at == sink.records[1].expires_at, (
        "the retry's row differs from the first in its expiry — it is not the same row")


def test_a_moment_without_a_zone_is_utc_and_one_that_is_no_moment_is_the_write():
    from openfactory.memory.transcript import _said_at

    naive = _said_at("2026-09-28T21:39:25")
    assert naive is not None and naive.isoformat() == "2026-09-28T21:39:25+00:00"
    assert _said_at("ontem") is None
    assert _said_at("") is None


# ── the moment travels from the door to the worker ──────────────────────────────────────────────

def test_the_moment_it_was_said_travels_from_the_door_to_the_worker(store):
    from openfactory.product import door, engine
    from openfactory.runtime.temporal.activities import _said
    from openfactory.runtime.temporal.conversation import ConversationWorkflow
    from openfactory.runtime.temporal.io import ConversationInput

    message = engine.Message(project="acme", conversation="c1", speaker="ana", text="oi")
    assert message.at, "a message is not stamped with when it arrived"
    arrival = door._arrival(message, store, fast=False, agent_name="Clara")
    assert arrival.at == message.at
    flow = ConversationWorkflow(ConversationInput(product="acme", conversation="c1"))
    later = arrival.model_copy(update={"id": "m2", "at": "2026-09-28T22:00:00+00:00"})
    work = flow._input([arrival, later])
    assert work.at == later.at, "the turn is not keyed by the message its id names"
    assert _said(work) == {"at": later.at}
    assert _said(work.model_copy(update={"at": ""})) == {}, (
        "an input admitted before the stamp existed must let the message stamp the worker's clock")

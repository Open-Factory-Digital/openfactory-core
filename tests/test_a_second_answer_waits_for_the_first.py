"""A second answer to a staged proposal waits for the first one, and reads what it reads (#456).

WHAT WAS MEASURED. On the live bed (2026-10-01) a person answered a staged proposal while an
earlier answer to it was still running. `product_answer` starts `ProductAnswerWorkflow` under one
id per proposal token, so the two answers collided — as the row's own comment promised they would,
"the second gets the first one's result rather than performing it twice". The engine does not do
that: it refuses the second start with `WorkflowAlreadyStartedError`, the row's generic `except`
turned it into `FAILED` — "I could not answer that just now, and nothing was performed." — and
`/api/act` served that as HTTP 500, while the first answer was performing the proposal.

THE RULE THIS FILE HOLDS: a second answer to a proposal already being answered is never told that
nothing was performed, and never performs it again. It waits on the SAME execution and gets the
first answer's outcome; when that outcome cannot be read, it is a conflict with the answer already
given, and the sentence says where that answer's result can be found.

  1. the engine — two answers to one token against a workflow still running, on Temporal's own
     test server, with the real `ProductAnswerWorkflow` and the act it runs held open;
  2. the doubles — the attached outcome goes through the same mapping, and an outcome that cannot
     be read is a CONFLICT that says where to look.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.io import ProductAnswerInput
from openfactory.runtime.temporal.workflow import ProductAnswerWorkflow
from tests.test_the_confirmation_executor import _actor, _project, _returns

TOKEN = "C0PROD|abc"


@pytest.fixture
def _resolvable(monkeypatch):
    """A project the row can resolve, so whatever it answers is the row's and never `no such
    project`."""
    from openfactory.actions import catalog

    project = _project()
    monkeypatch.setattr(catalog, "_product_module",
                        lambda _name, **_kw: (object(), project, None))
    return project


# ── 1. the engine ───────────────────────────────────────────────────────────────────────────────

#: What the act on the worker was asked to perform, one row per run — `(workflow id, input)`.
PERFORMED: list[tuple[str, ProductAnswerInput]] = []
#: Released by the test once the second answer has reached the running execution.
HELD: dict[str, asyncio.Event] = {}


@activity.defn(name="product_role_answer")
async def _the_act(inp: ProductAnswerInput) -> dict:
    """The act behind the real workflow, held open: it is still running when the second answer
    arrives, which is the window the measured defect lived in."""
    PERFORMED.append((activity.info().workflow_id, inp))
    await HELD["go"].wait()
    return {"outcome": "done", "message": "Registrado. **erp** entrou no glossário."}


class _Watched:
    """The test engine's own client, with a note of which execution a caller waited on."""

    def __init__(self, client) -> None:
        self.client, self.attached = client, []

    async def execute_workflow(self, *args, **kwargs):
        return await self.client.execute_workflow(*args, **kwargs)

    def get_workflow_handle(self, workflow_id, **kwargs):
        self.attached.append(workflow_id)
        return self.client.get_workflow_handle(workflow_id, **kwargs)


@pytest.fixture
async def env():
    PERFORMED.clear()
    HELD["go"] = asyncio.Event()
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        HELD["go"].set()
        await e.shutdown()


async def _until(what, why: str, *, within: float = 20.0) -> None:
    deadline = time.monotonic() + within
    while not what():
        if time.monotonic() > deadline:
            raise AssertionError(f"waited {within}s: {why}")
        await asyncio.sleep(0.02)


@pytest.mark.owns_its_engine
async def test_a_second_answer_while_the_first_runs_gets_the_first_one_s_outcome(
        env, _resolvable, monkeypatch):
    """THE MEASURED DEFECT. Two answers to one token; the act of the first is still running when
    the second arrives. The second waits on that same execution and returns what the first
    returns — the act ran ONCE, and nobody was told that nothing was performed."""
    from openfactory.actions import catalog

    client = _Watched(env.client)
    monkeypatch.setattr(catalog, "_connected", _returns(client))

    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[ProductAnswerWorkflow],
                      activities=[_the_act]):
        first = asyncio.create_task(catalog._product_answer(
            project="books", token=TOKEN, answer="approve", by=_actor(), yes=True,
            message_id="click-first-0001"))
        await _until(lambda: PERFORMED, "the first answer never reached the worker")
        second = asyncio.create_task(catalog._product_answer(
            project="books", token=TOKEN, answer="approve", by=_actor(id="bia"), yes=True,
            message_id="click-second-001"))
        await _until(lambda: client.attached or second.done(),
                     "the second answer neither returned nor waited on the first")
        assert not second.done(), (
            f"the second answer returned while the first was still running: {second.result()}")
        HELD["go"].set()
        a, b = await asyncio.wait_for(asyncio.gather(first, second), timeout=60)

    assert len(PERFORMED) == 1, f"the proposal was performed {len(PERFORMED)} times"
    (started, _), = PERFORMED
    assert client.attached == [started], (
        f"the second answer waited on {client.attached}, not on the execution that ran, "
        f"{started}")
    assert a.ok, a.message
    assert b.ok and b.code == a.code, (b.code, b.message)
    assert b.message == a.message == "Registrado. erp entrou no glossário.", (a.message, b.message)
    assert b.data["outcome"] == a.data["outcome"] == "done", (a.data, b.data)
    assert "nothing was performed" not in b.message


# ── 2. the doubles ──────────────────────────────────────────────────────────────────────────────

class _Running:
    """An engine on which this proposal's answer is already running: a second start is refused,
    and the running execution answers `outcome` — or raises it, when it is an exception."""

    def __init__(self, outcome) -> None:
        self.outcome, self.started, self.attached = outcome, [], []

    async def execute_workflow(self, name, _inp, **kw):
        self.started.append(kw["id"])
        raise WorkflowAlreadyStartedError(kw["id"], name)

    def get_workflow_handle(self, workflow_id, **_kw):
        self.attached.append(workflow_id)
        outcome = self.outcome

        class _Handle:
            async def result(self):
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        return _Handle()


@pytest.mark.asyncio
async def test_the_first_answer_s_refusal_reaches_the_second_with_the_first_one_s_code(
        _resolvable, monkeypatch):
    """EXACTLY AS THE FIRST CALLER GETS IT. A first answer that found the proposal gone is a
    CONFLICT with its own sentence, and so is the second that waited on it."""
    from openfactory.actions import catalog

    engine = _Running({"outcome": "gone", "message": "Alguém já respondeu isso."})
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token=TOKEN, answer="approve",
                                           by=_actor(), yes=True)

    assert engine.attached == engine.started, (engine.started, engine.attached)
    assert not result.ok and result.code == catalog.CONFLICT, (result.code, result.message)
    assert result.message == "Alguém já respondeu isso.", result.message


@pytest.mark.asyncio
async def test_an_answer_that_cannot_read_the_first_one_s_outcome_is_a_conflict_not_a_failure(
        _resolvable, monkeypatch):
    """The earlier answer holds the proposal and may have performed it, so "nothing was
    performed" would be the measured falsehood again, and FAILED the 500 again. A conflict with
    the answer already given — and the sentence says where its result is found."""
    from openfactory.actions import catalog

    engine = _Running(RuntimeError("temporal: deadline exceeded reaching namespace acme.x9k2"))
    monkeypatch.setattr(catalog, "_connected", _returns(engine))

    result = await catalog._product_answer(project="books", token=TOKEN, answer="approve",
                                           by=_actor(), yes=True)

    assert engine.attached == engine.started, (engine.started, engine.attached)
    assert not result.ok and result.code == catalog.CONFLICT, (result.code, result.message)
    assert "nothing was performed" not in result.message, result.message
    assert "already being answered" in result.message, result.message
    assert "product_pending" in result.message, (
        "the refusal does not say where the earlier answer's result can be read")
    assert "deadline" not in result.message and "acme" not in result.message, (
        f"the engine's diagnosis went to the client: {result.message}")

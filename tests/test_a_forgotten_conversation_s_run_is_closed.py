"""A forgotten conversation's run is closed, against a real engine, and the next message starts a
new one that holds nothing of it (#533).

A conversation's run ends only in `continue_as_new`, after `TURNS_PER_RUN` turns, and a forgotten
conversation takes no more: measured on a deployment, eight runs were still `Running` six days
after `project forget`, one holding 76 entries — what was said, and what was answered — that the
engine's retention never reaches while the run is open. `forget.close_runs` terminates them; this
proves, on the engine's own test server, what that buys: the run is closed, and the next message
starts a new run through the door's signal-with-start, whose state holds only itself.

The listing `close_runs` does first is `tests/test_a_project_is_forgotten_in_one_command.py`'s:
this test server implements no visibility query (`ListWorkflowExecutions` is unimplemented here).
"""

from __future__ import annotations

import asyncio

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from openfactory.product import door, forget
from tests.test_the_one_door import (  # noqa: F401 — the fixture, imported to be requested here
    ALICE,
    _answer,
    _message,
    _send,
    _Worker,
    _worker,
    registry,
)

#: THIS FILE STARTS ITS OWN ENGINE, like `test_the_one_door`: `WorkflowEnvironment` boots an
#: ephemeral Temporal it owns its whole life (`conftest._no_live_durable_engine`, #107).
pytestmark = pytest.mark.owns_its_engine


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


def _said(seen: dict) -> str:
    return " ".join(str(e) for e in (seen or {}).get("entries") or [])


async def test_the_closed_run_is_ended_and_the_next_message_starts_one_that_holds_nothing(
        env, registry):  # noqa: F811 — `registry` is the one-door fixture, imported above
    w = _Worker()
    async with _worker(env, w):
        first = await _send(env, _message("o pedido esquecido", speaker=ALICE), registry["books"])
        await _answer(env, first)
        wid = first.workflow_id
        before = await env.client.get_workflow_handle(wid).describe()
        assert "o pedido esquecido" in _said(await door.watch(env.client, wid, 0))

        closed, at_work = await forget.close_idle(env.client, [wid])

        assert (closed, at_work) == ([wid], [])
        ended = await env.client.get_workflow_handle(wid, run_id=before.run_id).describe()
        assert ended.status == WorkflowExecutionStatus.TERMINATED, ended.status

        again = await _send(env, _message("um pedido novo", speaker=ALICE), registry["books"])
        await _answer(env, again)
        now = await env.client.get_workflow_handle(wid).describe()
        seen = _said(await door.watch(env.client, wid, 0))

    assert now.run_id != before.run_id, "the next message wrote into the closed run"
    assert now.status == WorkflowExecutionStatus.RUNNING
    assert "um pedido novo" in seen
    assert "o pedido esquecido" not in seen, "the new run carried the forgotten conversation"


async def test_a_run_with_a_turn_at_work_is_left_open(env, registry):  # noqa: F811
    """Never ended mid-turn: the message being answered would be lost, and its answer with it."""
    w = _Worker()
    held = w.hold("SEGURA")
    async with _worker(env, w):
        ack = await _send(env, _message("SEGURA isto", speaker=ALICE), registry["books"])
        while not w.started("SEGURA isto"):
            await asyncio.sleep(0.02)

        closed, at_work = await forget.close_idle(env.client, [ack.workflow_id])

        assert (closed, at_work) == ([], [ack.workflow_id])
        held.set()
        await _answer(env, ack)
        status = (await env.client.get_workflow_handle(ack.workflow_id).describe()).status
    assert status == WorkflowExecutionStatus.RUNNING

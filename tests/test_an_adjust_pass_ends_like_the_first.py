"""An adjust pass a person asked for ends the way the first pass did (#413 part 3, #448 slice 2).

MEASURED ON A LIVE RUN (#448, card #1000007): the operator's adjust pass rewrote the pull request,
and when it ended nothing rebuilt the preview and nobody told the requester. `ready_for_you` is keyed
on the card and the pull request, which a second pass does not change, so it was deduplicated away.

WHAT IS PROVEN HERE, on the real `JobWorkflow` in a time-skipping engine with the merge gate's own
harness (`test_the_merge_gate_is_heard_on_every_path`):

  · a pass that rewrote the pull request calls `card_adjusted`, numbered — and one that changed
    nothing calls nothing;
  · the new command is behind `workflow.patched`: a history recorded without it replays on this code,
    and the same history replayed WITH it diverges, so the replay proves something.
"""

from __future__ import annotations

import pytest
import test_the_merge_gate_is_heard_on_every_path as gate
from gate_answers import answer_merge_gate
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from openfactory.contracts import JobState, RunResult
from openfactory.runtime.temporal.io import AdjustedInput, AdjustInput
from openfactory.runtime.temporal.workflow import JobWorkflow

pytestmark = pytest.mark.owns_its_engine

MARKER = "an-adjust-pass-ends-like-the-first"


@pytest.fixture
async def env():
    """This file's own ephemeral engine, started and disposed of here: the barrier is lifted for a
    server the test owns (`test_the_suite_cannot_reach_a_live_engine`), not for one it borrows."""
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


_ADJUSTED: list[AdjustedInput] = []
_PASSES: list[AdjustInput] = []
_CHANGED = [True]


@activity.defn(name="adjust_pr")
async def mock_adjust(inp: AdjustInput) -> RunResult:
    _PASSES.append(inp)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url,
                     code_changed=_CHANGED[0])


@activity.defn(name="card_adjusted")
async def mock_adjusted(inp: AdjustedInput) -> str:
    _ADJUSTED.append(inp)
    return "told"


MOCKS = [*gate.MOCKS, mock_adjust, mock_adjusted]


@pytest.fixture(autouse=True)
def _fresh():
    gate._REPAIRS.clear(), gate._CLOSED.clear(), gate._MERGED.clear()
    gate._HOLD_REPAIR.clear(), gate._HOLD_READ.clear()
    gate._READS[0] = 0
    gate._CI[0], gate._MSTATE[0] = gate.RED, "blocked"
    gate._UPDATES.clear(), gate._AT.clear(), gate._FORCED.clear()
    gate._AUTO[0] = False
    _ADJUSTED.clear()
    _PASSES.clear()
    _CHANGED[0] = True


async def _adjust_then_discard(client, instruction: str = "the button on the right") -> object:
    h = await gate._start(client)
    await gate._napping_after_a_repair(h)
    await answer_merge_gate(h, "adjust", instruction, "ana")

    async def adjusted_and_resting():
        g = await h.query(JobWorkflow.awaiting_merge)
        # the pass ran and the gate is a question again — `card_adjusted`, when it runs, runs
        # before the watch re-opens the gate
        return g if (g and not g.get("working") and _PASSES) else None

    await gate._until("the adjust pass over and the gate back", adjusted_and_resting)
    await answer_merge_gate(h, "discard", "", "ana")
    await h.result()
    return h


async def test_a_pass_that_rewrote_the_pull_request_is_told_numbered(env):
    async with Worker(env.client, task_queue=gate.TQ, workflows=[JobWorkflow], activities=MOCKS):
        await _adjust_then_discard(env.client)

    [told] = _ADJUSTED
    assert (told.pass_number, told.by, told.pr_url) == (1, "ana", "https://x/pr/1"), told
    assert "the button on the right" in told.instruction


async def test_a_pass_that_changed_nothing_says_nothing(env):
    """#179: an adjust that could not act on the instruction pushes nothing — there is no new
    head to try, and telling the requester "pass 1 is ready" would be a lie."""
    _CHANGED[0] = False
    async with Worker(env.client, task_queue=gate.TQ, workflows=[JobWorkflow], activities=MOCKS):
        await _adjust_then_discard(env.client)

    assert _ADJUSTED == []


async def test_a_job_recorded_before_the_marker_replays_and_the_replay_proves_something(
        env, monkeypatch):
    """The history is recorded with `patched` answering False for this marker — the arm a job in
    flight before this change selects — and replayed through the real `patched()`. Then the same
    history through the marker's arm must DIVERGE, or the green replay verified nothing."""
    from temporalio import workflow as tw

    real = tw.patched
    with monkeypatch.context() as m:
        m.setattr(tw, "patched", lambda name: False if name == MARKER else real(name))
        async with Worker(env.client, task_queue=gate.TQ, workflows=[JobWorkflow],
                          activities=MOCKS):
            h = await _adjust_then_discard(env.client)
        history = await h.fetch_history()
    assert _ADJUSTED == [], "the recording ran the new command it claims to predate"

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    monkeypatch.setattr(tw, "patched", lambda name: True if name == MARKER else real(name))
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    said = str(caught.value)
    assert "determinis" in said.lower() or "TMPRL1100" in said or "Nondeterminism" in said, (
        f"the marker's arm failed the replay for another reason: {said[:400]}")

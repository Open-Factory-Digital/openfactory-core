"""A merged ticket has to be able to reach Done (pilot, 2026-08-16).

The operator asked the question this file exists to answer, the evening before merging his first
real ticket:

    "when the merge is done a deploy to staging happens — and I have not seen anywhere that picks
     up the staging domain so the tech-lead (or the PO) can ask for validation. This project HAS a
     staging environment, that is the flow, but other companies may have another one, and I have
     not seen anywhere this would work."

Reading the code for his configuration, the answer was worse than the missing address. Every
project this platform's own onboarding creates declares no `environments:`, so:

  * `should_promote` is False and the promotion tail — the ONLY writer of `JobState.DONE` in the
    ordinary flow — never runs;
  * `JobState.MERGED` maps to *In review* on purpose (merged is still overseen while it deploys);
  * the in-job orchestrator, which writes tracker states as it goes, returned long before the
    human answered the merge gate.

So the card stops at *In review* for ever, the last word on the ticket is "PR ready for review",
and nothing anywhere says that the post-merge half of the platform is switched off for this
project. A factory that quietly does nothing looks exactly like a factory whose next step has not
arrived yet — which is precisely why he could not tell.

THE TEST RUNS THE REAL WORKFLOW against an ephemeral engine, rather than reading the source: the
defect was not a wrong sentence, it was a call that was never reached.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.manifest import PostMergeDeploy
from openfactory.runtime.temporal.io import (
    HoldSyncInput,
    JobParams,
    MergeCheckInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow

TQ = "test-merge-end"

#: THIS FILE STARTS ITS OWN ENGINE and throws it away — the one declared exception to the suite's
#: no-live-engine rule (`conftest.OWNS_ITS_ENGINE`), same as `test_temporal_workflow`.
pytestmark = pytest.mark.owns_its_engine

#: What the run produced, per test — the manifest facts ride back on the RunResult.
_RESULT: dict = {}
#: Every `settle_ticket` call the workflow made.
_SETTLED: list[HoldSyncInput] = []


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1",
                     **_RESULT)


@activity.defn(name="check_pr_status")
async def mock_merged(inp: MergeCheckInput) -> str:
    return "merged"


@activity.defn(name="settle_ticket")
async def mock_settle(inp: HoldSyncInput) -> str:
    _SETTLED.append(inp)
    return inp.state


@activity.defn(name="fetch_ticket_title")
async def mock_title(inp) -> str:
    return "a ticket"


@activity.defn(name="refresh_knowledge")
async def mock_refresh(inp) -> str:
    return "published"


@activity.defn(name="notify_coordinator_say")
async def mock_say(inp) -> None:
    return None


@activity.defn(name="check_ci_status")
async def mock_ci(inp: MergeCheckInput) -> str:
    return "success"


MOCKS = [mock_run_job, mock_merged, mock_settle, mock_title, mock_refresh, mock_say, mock_ci]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _merge_one(client: Client) -> RunResult:
    async with Worker(client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await client.start_workflow(JobWorkflow.run,
                                        JobParams(project="p", issue="87", promote=False),
                                        id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        return await h.result()


async def test_a_merge_with_nothing_after_it_still_reaches_Done(env: WorkflowEnvironment):
    """THE CARD MUST BE ABLE TO LEAVE 'In review'. Without this the board's terminal column is
    unreachable for every project that declares no environments — which is every project the
    onboarding creates."""
    _RESULT.clear(), _SETTLED.clear()
    result = await _merge_one(env.client)

    assert result.state == JobState.MERGED
    assert [s.state for s in _SETTLED] == [JobState.DONE.value], (
        "the merged ticket was never settled on the tracker — its card stays in 'In review' "
        "for ever, because the promotion tail that writes Done never runs for this project")


async def test_the_ticket_SAYS_that_nothing_is_watching_and_names_what_would(
        env: WorkflowEnvironment):
    """The half the operator actually asked about. Silence and "the next step has not happened
    yet" are the same thing on a ticket, so the closing comment states which keys are missing and
    where they live — the remedy travels with the finding."""
    _RESULT.clear(), _SETTLED.clear()
    await _merge_one(env.client)

    note = _SETTLED[0].note
    for owed in ("post_merge_deploy", "environments", ".openfactory/project.yaml"):
        assert owed in note, f"the closing comment never mentions {owed}: {note!r}"
    assert "nobody will be asked to validate" in note


async def test_a_project_that_DID_declare_a_watch_is_told_what_is_being_watched(
        env: WorkflowEnvironment):
    """The same sentence must not be printed at a project that configured this properly — it would
    be telling a shop with a deploy watch that nothing is watching. Derived from the run's own
    manifest facts, not from a template."""
    _RESULT.clear(), _SETTLED.clear()
    _RESULT["post_merge_deploy"] = PostMergeDeploy(workflow="deploy.yml", env="staging",
                                                   timeout_minutes=45)
    await _merge_one(env.client)

    note = _SETTLED[0].note
    assert "deploy.yml" in note and "staging" in note and "45" in note
    assert "nobody will be asked to validate" not in note, (
        "a project WITH a deploy watch is being told nothing is watching")
    assert "no `environments:`" in note, (
        "it watches a deploy and promotes nothing, and only half of that is being said")


async def test_the_HUMAN_S_OWN_ANSWER_reaches_it_too(env: WorkflowEnvironment):
    """THE PATH THE OPERATOR ACTUALLY TAKES, and the reason this test exists separately.

    Every other test here merges through the CI watch (`check_pr_status` → "merged"). The pilot
    merges by answering the gate — the panel's button, or "pode fazer o merge" in the chat — which
    goes through `human_merge_gate` → `merge_pr_now` and returns from a DIFFERENT function. The
    two converge, but "they converge" is a claim about control flow read from a screen, and this
    codebase has paid for that reading before. So it is exercised."""
    _RESULT.clear(), _SETTLED.clear()

    @activity.defn(name="check_pr_status")
    async def never_merges(inp: MergeCheckInput) -> str:
        return "open"

    @activity.defn(name="merge_pr_now")
    async def merges_on_demand(inp: MergeCheckInput) -> bool:
        return True

    @activity.defn(name="pr_mergeable_state")
    async def blocked(inp: MergeCheckInput) -> str:
        # "checks pending" — the watch simply waits, so the gate stays open for a human. An
        # UNREGISTERED activity here fails the loop and parks the job as an impediment, which is
        # how the first run of this test reported "the gate never opened".
        return "blocked"

    mocks = ([m for m in MOCKS if m is not mock_merged]
             + [never_merges, merges_on_demand, blocked])
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=mocks):
        # THE DEADLINE IS PUSHED OUT OF REACH, the lesson `test_temporal_workflow::_parked`
        # already paid for: `start_time_skipping` leaps to the next timer whenever every workflow
        # is blocked on one, so a poll loop does not walk the clock — it teleports. With the
        # default 14 days the job arrived at its merge deadline and parked before this test could
        # answer the gate, and the failure read as "the gate never opened".
        h = await env.client.start_workflow(
            JobWorkflow.run,
            JobParams(project="p", issue="87", promote=False, merge_deadline_days=3650),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        for _ in range(60):
            gate = await h.query(JobWorkflow.awaiting_merge)
            if gate and gate.get("gate_live"):
                break
            await env.sleep(timedelta(seconds=1))
        else:
            raise AssertionError("the job never opened a merge gate for a human to answer")
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "operator-1"])
        result = await h.result()

    assert result.state == JobState.MERGED
    assert [s.state for s in _SETTLED] == [JobState.DONE.value], (
        "a merge a HUMAN answered for never settles the ticket — the card the operator just "
        "merged stays in 'In review'")


async def test_a_project_WITH_environments_is_left_to_the_promotion_tail(
        env: WorkflowEnvironment):
    """The boundary. When there IS a chain, the promotion tail owns the ending — this must not
    settle the ticket underneath it and call Done what is really 'staging verifying'."""
    _RESULT.clear(), _SETTLED.clear()
    _RESULT["environments"] = ["staging", "prod"]
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await env.client.start_workflow(
            JobWorkflow.run, JobParams(project="p", issue="87", promote=False),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        # `promote_staging` is deliberately NOT registered, so the run dies AT the promotion call
        # — which is also the proof that it got there. Without naming the activity this would pass
        # just as well for a workflow that fell over before the merge.
        with pytest.raises(Exception) as blew_up:
            await h.result()
    # The activity's name is in the CAUSE chain; Temporal's top-level message is generic.
    chain, exc = [], blew_up.value
    while exc is not None:
        chain.append(str(exc))
        exc = exc.__cause__
    assert any("promote_staging" in link for link in chain), (
        f"the run did not reach the promotion tail at all: {chain}")
    assert _SETTLED == [], (
        "a project with a promotion chain had its ticket settled as Done at the merge, before "
        "anything was promoted or verified")

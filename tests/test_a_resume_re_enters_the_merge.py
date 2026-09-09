"""ADR-0049 slice 3d — a resume on a refused merge goes back to the MERGE, not to the agent.

WHAT IT COST BEFORE. A person answers the merge gate, the forge refuses — on a local forge,
because their own working tree holds an edit to a file the branch touches; on GitHub, because a
rule this App cannot satisfy. The job parks and says what is in the way. They clear it and answer
`resume`, which is the verb the park itself offers. The lifecycle loop then runs the AGENT again:
a full paid pass re-doing work that is already committed on the branch and already in an open pull
request, holding the single-slot floor for the length of it, and only after all that does the
merge get tried a second time.

THE CAUSE IS STRUCTURAL, not a wrong branch. The merge watch runs INSIDE the `if result is None:`
arm that runs the agent, so "go back to the watch" had nowhere to enter. Slice 3c stopped short of
this deliberately and said so: the restructuring is a change every in-flight job replays, and it
deserved a review looking only at it.

THE MARK IS A FIELD. `RunResult.merge_refused` is what this path reads — never the note, which is
prose in the forge's own words and exactly what a translation card rewrites.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts import JobState, RunResult
from openfactory.runtime.temporal.io import HoldSyncInput, JobParams, MergeCheckInput, RunJobInput
from openfactory.runtime.temporal.workflow import JobWorkflow

TQ = "test-resume-into-merge"

#: THIS FILE STARTS ITS OWN ENGINE and throws it away — the declared exception to the suite's
#: no-live-engine rule (`conftest.OWNS_ITS_ENGINE`), as `test_the_merge_is_the_end_of_the_road`.
pytestmark = pytest.mark.owns_its_engine

#: every `run_job` the workflow asked for — the whole point of the slice is that this stays at 1.
_RUNS: list[RunJobInput] = []
#: how many times a person's merge answer reached the forge, and what it answered each time.
_MERGES: list[str] = []
#: what the forge says, in order. `""` is *it landed*; anything else is a refusal it can explain.
_SAYS: list[str] = []


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    """The first attempt opens a pull request; a SECOND one lands on its own.

    The second answer exists so a job that legitimately goes back to the agent — the pull request
    was closed, there is nothing left to merge — can reach an ending instead of hanging the test
    on a gate nobody will answer."""
    _RUNS.append(inp)
    if len(_RUNS) > 1:
        return RunResult(ticket_id=inp.issue, state=JobState.MERGED, pr_url="https://x/pr/2",
                         branch="openfactory/87")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1",
                     branch="openfactory/87")


#: what the forge says the pull request IS, so a test can close it under the watch.
_STATUS = ["open"]


@activity.defn(name="check_pr_status")
async def never_merges(inp: MergeCheckInput) -> str:
    return _STATUS[0]


@activity.defn(name="pr_mergeable_state")
async def blocked(inp: MergeCheckInput) -> str:
    """"checks pending" — the watch waits, so the gate stays open for a person to answer."""
    return "blocked"


@activity.defn(name="check_ci_status")
async def ci_pending(inp: MergeCheckInput) -> str:
    return "pending"


@activity.defn(name="merge_pr_saying_why")
async def merge_says_why(inp: MergeCheckInput) -> str:
    said = _SAYS.pop(0) if _SAYS else ""
    _MERGES.append(said)
    return said


@activity.defn(name="merge_pr_now")
async def merge_now(inp: MergeCheckInput) -> bool:
    """Registered for the pre-patch path only — a job parked at this gate before ADR-0049 D4
    replays against it, and an unregistered activity parks the job instead of failing loudly."""
    return True


@activity.defn(name="settle_ticket")
async def mock_settle(inp: HoldSyncInput) -> str:
    return inp.state


@activity.defn(name="mark_needs_action")
async def mock_mark(inp: HoldSyncInput) -> str:
    return "somebody"


@activity.defn(name="diagnose_impediment")
async def mock_diagnose(inp: HoldSyncInput) -> bool:
    """`bool`, and the type is the whole reason this mock is spelled out: the real activity
    answers whether it managed to diagnose, and a `str` here fails the workflow task on decode —
    which surfaces as the gate simply never opening."""
    return False


@activity.defn(name="fetch_ticket_title")
async def mock_title(inp) -> str:
    return "a ticket"


@activity.defn(name="refresh_knowledge")
async def mock_refresh(inp) -> str:
    return "published"


@activity.defn(name="notify_coordinator_say")
async def mock_say(inp) -> None:
    return None


MOCKS = [mock_run_job, never_merges, blocked, ci_pending, merge_says_why, merge_now,
         mock_settle, mock_mark, mock_diagnose, mock_title, mock_refresh, mock_say]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _wait_for_gate(h: WorkflowHandle, env: WorkflowEnvironment) -> None:
    """THE DEADLINE IS PUSHED OUT OF REACH by the caller, and this is why: time-skipping leaps to
    the next timer whenever every workflow is blocked on one, so a poll loop teleports rather than
    walks. With the default fourteen days the job reaches its merge deadline and parks before the
    test can answer anything, and the failure reads as "the gate never opened"."""
    for _ in range(60):
        gate = await h.query(JobWorkflow.awaiting_merge)
        if gate and gate.get("gate_live"):
            return
        await env.sleep(timedelta(seconds=1))
    raise AssertionError("the job never opened a merge gate for a person to answer")


async def _wait_for_park(h: WorkflowHandle, env: WorkflowEnvironment) -> dict:
    for _ in range(60):
        parked = await h.query(JobWorkflow.awaiting_action)
        if parked:
            return parked
        await env.sleep(timedelta(seconds=1))
    raise AssertionError("the refused merge never parked for a person")


async def _start(client: Client) -> WorkflowHandle:
    return await client.start_workflow(
        JobWorkflow.run,
        JobParams(project="p", issue="87", promote=False, merge_deadline_days=3650),
        id=f"wf-{uuid.uuid4()}", task_queue=TQ)


# ── the path itself ─────────────────────────────────────────────────────────────────────────────

async def test_a_resumed_merge_refusal_reaches_the_merge_without_running_the_agent_again(
        env: WorkflowEnvironment):
    """THE SLICE, END TO END. Refused once, resumed, landed — with exactly one agent pass in the
    whole job. The count is the assertion: `run_job` is the paid thing, and re-doing work that is
    already on the branch is what this path existed to charge for."""
    _RUNS.clear(), _MERGES.clear(), _SAYS.clear()
    _STATUS[0] = "open"
    _SAYS.append("error: Your local changes to 'app.py' would be overwritten by merge.")

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _wait_for_gate(h, env)
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        parked = await _wait_for_park(h, env)
        assert "app.py" in (parked.get("note") or ""), (
            "the park does not say what the forge said, so the person cannot clear it")
        assert await h.query(JobWorkflow.awaiting_merge) is None, (
            "the panel still says a merge is being watched on a job that is waiting for a "
            "person — the wait outlived the watch it belongs to")

        await h.signal(JobWorkflow.act_on_impediment, args=["resume", ""])
        await _wait_for_gate(h, env)          # back at the MERGE, not in an agent pass
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        result = await h.result()

    assert result.state == JobState.MERGED
    assert len(_MERGES) == 2, f"the merge was attempted {len(_MERGES)} times, not twice"
    assert len(_RUNS) == 1, (
        f"the agent ran {len(_RUNS)} times — a resume on a refused merge is re-doing work that "
        f"is already committed on the branch and already in an open pull request")


async def test_the_resumed_merge_keeps_what_the_post_merge_half_reads(env: WorkflowEnvironment):
    """RE-ENTERED WITH THE PULL REQUEST, NOT WITH THE PARK. The hold carries a note and a URL; the
    branch, the auto-merge flag and the manifest facts live on the result the watch was holding.
    Rebuilt from the park, the merge would land and the tail that watches, promotes and settles
    would have nothing to work from."""
    _RUNS.clear(), _MERGES.clear(), _SAYS.clear()
    _STATUS[0] = "open"
    _SAYS.append("refused")

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _wait_for_gate(h, env)
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        await _wait_for_park(h, env)
        await h.signal(JobWorkflow.act_on_impediment, args=["resume", ""])
        await _wait_for_gate(h, env)
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        result = await h.result()

    assert result.state == JobState.MERGED
    assert result.branch == "openfactory/87", (
        "the merged result lost the branch — it was rebuilt from the hold instead of carried")
    assert result.ticket_id == "87"


# ── the mark, and what must not stand in for it ─────────────────────────────────────────────────

def test_the_refusal_marks_the_hold_rather_than_only_describing_it():
    """The field exists and defaults to the old behaviour."""
    assert RunResult(ticket_id="1", state=JobState.ON_HOLD).merge_refused is False, (
        "an attempt from before this field must read as 'no merge was refused'")


def test_the_resume_path_reads_the_MARK_and_not_the_notes_wording():
    """THE `attempts_spent` LESSON (#124), applied before it costs anything. The note carries the
    forge's own sentence, in whatever language and wording the forge chose, and a card about
    wording is exactly what rewrites it. The branch that decides whether a person pays for an
    agent pass must not be reachable from prose."""
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    src = inspect.getsource(wf.JobWorkflow._lifecycle)
    marker = 'workflow.patched("hold-resumes-into-merge")'
    condition = src[src.rindex("if ", 0, src.index(marker)):src.index(marker) + len(marker)]
    assert "merge_refused" in condition, "the resume path does not read the mark"
    assert ".note" not in condition, (
        "the resume-into-merge decision reads the hold's prose — one translation card away from "
        "sending every refused merge back through a full agent pass")


def test_the_mark_is_set_where_the_refusal_HAPPENS_and_nowhere_else():
    """One writer. A mark set in a second place is a mark two paths can disagree about — and the
    one that matters is the durable watch, which is where the forge actually answers."""
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    assert inspect.getsource(wf).count("merge_refused=True") == 1, (
        "the merge-refusal mark is written in more than one place")


async def test_a_SECOND_park_that_is_not_a_merge_refusal_goes_back_to_the_agent(
        env: WorkflowEnvironment):
    """THE FLAG IS CONSUMED, and this is the case that can tell.

    Refused once and resumed, the job is back in the merge watch. What parks it the second time is
    not a refusal — the pull request was closed while nobody was looking, so there is nothing left
    to merge and the next resume is meant to be a fresh attempt. A re-entry flag left set sends
    that resume back into a watch on a closed pull request, which parks again, which resumes
    again: a person answering `resume` for ever on a job that can only move by running.

    It is the mutation `pr_again = resume_into_merge` — a cut every other test in this file
    survives, because none of them park twice."""
    _RUNS.clear(), _MERGES.clear(), _SAYS.clear()
    _STATUS[0] = "open"
    _SAYS.append("refused")

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _wait_for_gate(h, env)
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        await _wait_for_park(h, env)

        _STATUS[0] = "closed"                       # somebody closed it while it was parked
        await h.signal(JobWorkflow.act_on_impediment, args=["resume", ""])
        for _ in range(60):
            parked = await h.query(JobWorkflow.awaiting_action)
            if parked and "closed" in (parked.get("note") or ""):
                break
            await env.sleep(timedelta(seconds=1))
        else:
            raise AssertionError("the watch never noticed the pull request had been closed")

        await h.signal(JobWorkflow.act_on_impediment, args=["resume", ""])
        result = await h.result()

    assert len(_RUNS) == 2, (
        f"the agent ran {len(_RUNS)} time(s) — a resume after a park that was NOT a merge "
        f"refusal is still being sent back into the merge watch, and the only pull request it "
        f"has to watch is closed")
    assert result.state == JobState.MERGED

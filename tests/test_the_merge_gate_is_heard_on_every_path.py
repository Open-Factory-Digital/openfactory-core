"""#184 (the comment) — a person's answer at an open merge gate is heard on EVERY path of the watch.

WHAT IT COST. The panel offers Merge / Adjust / Discard as soon as the merge watch is set, and
`human_merge_gate` stores the answer. The only place the answer was CONSUMED sat inside the branch
the loop takes when CI is NOT failing. So while the checks read `failure` the loop went
repair → sleep → re-check → repair and never reached it, and after `_CI_REPAIR_MAX` it returned
`CI still failing … needs a human` without ever reading what the human had already said. A person
who clicked Discard did not get the pull request closed; a person who clicked Merge did not get it
merged; both buttons appeared to work. With #184's phantom failure that was every pull request on
a repository whose policies include one the factory can never satisfy.

THREE CLAIMS, each driven on the real `JobWorkflow` and a real (time-skipping) engine:

  1. an answer given while the checks are red is acted on — it PRE-EMPTS the next repair;
  2. while a repair pass is rewriting the pull request the gate says so and refuses, instead of
     storing an answer that would land on a diff nobody has read;
  3. a job already in the watch replays what it recorded — and, because it cannot hear an answer
     on the failing path, it stops publishing a gate there that looks answerable.

TIME STANDS STILL UNTIL `result()` IS AWAITED. The time-skipping server only leaps while a client
awaits a result (or calls `env.sleep`), so these tests poll in REAL time while they wait for the
job to reach the nap after a repair: the two-minute timer is then still pending when the answer
is signalled, which is the whole situation under test.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.runtime.temporal import view
from openfactory.runtime.temporal.io import (
    CiRepairInput,
    HoldSyncInput,
    JobParams,
    MergeCheckInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow

TQ = "test-the-gate-is-heard"

#: THIS FILE STARTS ITS OWN ENGINE and throws it away — the declared exception to the suite's
#: no-live-engine rule (`conftest.OWNS_ITS_ENGINE`).
pytestmark = pytest.mark.owns_its_engine

RED = CiDecision(verdict="failure", action="repair", checks=["build"],
                 evidence="FAILED tests/test_export.py::test_it")

_REPAIRS: list[CiRepairInput] = []
_CLOSED: list[str] = []
_MERGED: list[str] = []
#: set by a test to hold the repair (or the read) open until the test has looked at the gate
_HOLD_REPAIR: list[asyncio.Event] = []
_HOLD_READ: list[asyncio.Event] = []
_READS = [0]


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1",
                     branch="openfactory/12", auto_merge=_AUTO[0])


#: whether the job is on the machine-merge path, and how often its self-merge was tried
_AUTO = [False]
_FORCED: list[str] = []


@activity.defn(name="force_merge_pr")
async def mock_force_refused(inp: MergeCheckInput) -> bool:
    """The forge refuses the self-merge — the watch naps and re-polls.

    ONLY THREE TIMES, and that is for the day this guard is needed: a job whose answer is never
    read would otherwise go refused → nap → refused until a ten-year merge deadline, and the case
    would HANG against the very defect it names instead of failing (measured: the first run of
    the plan sat on its first row for ten minutes). On the fourth try the merge lands, the job
    ends, and the assertion about the close is what speaks."""
    _FORCED.append(inp.pr_url)
    _AT.setdefault("force", activity.info().scheduled_time)
    return len(_FORCED) > 3


@activity.defn(name="check_pr_status")
async def mock_open(inp: MergeCheckInput) -> str:
    """Open until a merge the forge accepted — a person's, or the self-merge that lands on its
    fourth try — and merged from then on: the watch claims it on this READ (#180)."""
    return "merged" if (_MERGED or len(_FORCED) > 3) else "open"


#: what the checks and the mergeable state answer; a test about another path changes them
_CI = [RED]
_MSTATE = ["blocked"]
_UPDATES: list[str] = []
#: WHEN, ON THE ENGINE'S OWN CLOCK, each act was scheduled. The time-skipping engine makes a
#: two-minute nap free in test time — `result()` lets the clock leap — so "the answer was acted
#: on" cannot tell a nap that WOKE from one that slept and was read afterwards (measured: the
#: two mutations that put the plain `sleep` back both survived the first run of the plan). The
#: engine's clock can: a woken nap acts within seconds of the pass, a slept one `_CI_POLL` later.
_AT: dict[str, datetime] = {}
#: well under the two-minute nap, well over any real scheduling delay on a loaded machine
_PROMPTLY = timedelta(seconds=60)


@activity.defn(name="read_ci_checks")
async def mock_red(inp: MergeCheckInput) -> CiDecision:
    _READS[0] += 1
    if _HOLD_READ and _READS[0] == 1:
        await _HOLD_READ[0].wait()
    return _CI[0]


@activity.defn(name="update_pr_branch")
async def mock_update(inp: MergeCheckInput) -> bool:
    _UPDATES.append(inp.pr_url)
    _AT["update"] = activity.info().scheduled_time
    return True


@activity.defn(name="check_ci_status")
async def mock_red_word(inp: MergeCheckInput) -> str:
    """What a job recorded BEFORE #184's first marker replays — registered for the replay case."""
    return "failure"


@activity.defn(name="repair_ci")
async def mock_repair(inp: CiRepairInput) -> RunResult:
    _REPAIRS.append(inp)
    _AT["repair"] = activity.info().scheduled_time
    if _HOLD_REPAIR:
        await _HOLD_REPAIR[0].wait()
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url)


@activity.defn(name="close_pr")
async def mock_close(inp: MergeCheckInput) -> None:
    _CLOSED.append(inp.pr_url)
    _AT["close"] = activity.info().scheduled_time


@activity.defn(name="merge_pr_saying_why")
async def mock_merge(inp: MergeCheckInput) -> str:
    _MERGED.append(inp.pr_url)
    return ""


@activity.defn(name="merge_pr_now")
async def mock_merge_now(inp: MergeCheckInput) -> bool:
    return True


@activity.defn(name="pr_mergeable_state")
async def mock_blocked(inp: MergeCheckInput) -> str:
    return _MSTATE[0]


@activity.defn(name="settle_ticket")
async def mock_settle(inp: HoldSyncInput) -> str:
    return inp.state


@activity.defn(name="mark_needs_action")
async def mock_mark(inp: HoldSyncInput) -> str:
    return "somebody"


@activity.defn(name="diagnose_impediment")
async def mock_diagnose(inp: HoldSyncInput) -> bool:
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


MOCKS = [mock_run_job, mock_force_refused, mock_open, mock_red, mock_red_word, mock_update,
         mock_repair, mock_close, mock_merge, mock_merge_now, mock_blocked, mock_settle, mock_mark, mock_diagnose,
         mock_title, mock_refresh, mock_say]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture(autouse=True)
def _fresh():
    _REPAIRS.clear(), _CLOSED.clear(), _MERGED.clear()
    _HOLD_REPAIR.clear(), _HOLD_READ.clear()
    _READS[0] = 0
    _CI[0], _MSTATE[0] = RED, "blocked"
    _UPDATES.clear(), _AT.clear(), _FORCED.clear()
    _AUTO[0] = False


async def _start(client: Client) -> WorkflowHandle:
    return await client.start_workflow(
        JobWorkflow.run,
        JobParams(project="p", issue="12", promote=False, merge_deadline_days=3650,
                  impediment_deadline_days=1),
        id=f"wf-{uuid.uuid4()}", task_queue=TQ)


async def _until(what: str, check, *, tries: int = 400):
    """Poll in REAL time — `env.sleep` would let the clock leap past the nap under test."""
    for _ in range(tries):
        got = await check()
        if got:
            return got
        await asyncio.sleep(0.05)
    raise AssertionError(f"never saw: {what}")


async def _napping_after_a_repair(h: WorkflowHandle) -> dict:
    async def look():
        gate = await h.query(JobWorkflow.awaiting_merge)
        return gate if (_REPAIRS and gate and not gate.get("working")) else None
    return await _until("the watch resting after its first repair", look)


# ── 1. an answer given while the checks are red is acted on ─────────────────────────────────────

async def test_a_discard_while_ci_is_red_closes_the_pull_request(env: WorkflowEnvironment):
    """THE DEFECT, END TO END. The answer used to sit unread behind repair → sleep → repair, and
    the job ended `CI still failing` with the pull request open. Now it pre-empts the next repair:
    ONE repair ran (the one already over when the person answered), and the forge was told to
    close the pull request."""
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _napping_after_a_repair(h)
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        result = await h.result()

    assert _CLOSED == ["https://x/pr/1"], "Discard was accepted and the pull request stayed open"
    assert "closed without merging by a-person" in (result.note or "")
    assert len(_REPAIRS) == 1, f"{len(_REPAIRS)} repairs ran — the answer waited behind one"
    waited = _AT["close"] - _AT["repair"]
    assert waited < _PROMPTLY, (
        f"the close was scheduled {waited} after the repair on the engine's clock — the nap did "
        f"not wake for the answer, it slept its two minutes and the click looked dead meanwhile")


async def test_a_merge_while_ci_is_red_reaches_the_forge(env: WorkflowEnvironment):
    """`merge_pr`, not the admin override: if the forge refuses on the red check, that is a
    sentence the person reads (the refused-merge hold) — not a button that did nothing."""
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        await _napping_after_a_repair(h)
        await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])
        result = await h.result()

    assert result.state == JobState.MERGED and _MERGED == ["https://x/pr/1"]
    assert len(_REPAIRS) == 1


async def test_an_answer_that_arrives_during_the_read_pre_empts_the_repair(
        env: WorkflowEnvironment):
    """Not "within a poll": BEFORE the pass is launched. The read is held open, the person
    answers, the read comes back red — and no agent runs on a pull request somebody just closed."""
    _HOLD_READ.append(asyncio.Event())
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)

        async def reading():
            return _READS[0] >= 1 and await h.query(JobWorkflow.awaiting_merge)
        await _until("the watch reading the checks", reading)
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        _HOLD_READ[0].set()
        await h.result()

    assert _REPAIRS == [] and _CLOSED == ["https://x/pr/1"]


# ── 2. while a pass rewrites the pull request, the gate says so ─────────────────────────────────

async def test_the_gate_refuses_while_a_ci_repair_is_rewriting_the_pull_request(
        env: WorkflowEnvironment):
    """The same refusal an `adjust` pass already gets (#151), at the seam every surface crosses:
    a Merge here would land whatever the agent has pushed so far."""
    _HOLD_REPAIR.append(asyncio.Event())
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)

        async def working():
            gate = await h.query(JobWorkflow.awaiting_merge)
            return gate if (gate and gate.get("working")) else None
        gate = await _until("the gate saying a pass is rewriting the pull request", working)
        assert "rewriting this pull request" in view.gate_cannot_hear(gate)

        _HOLD_REPAIR.pop().set()
        rested = await _napping_after_a_repair(h)
        assert view.gate_cannot_hear(rested) == "", (
            "the pass is over and the gate still refuses — it would never re-open")
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        await h.result()
    assert _CLOSED == ["https://x/pr/1"]


async def test_an_answer_wakes_the_nap_after_a_branch_update_too(env: WorkflowEnvironment):
    """EVERY path, not only the red one: a pull request that keeps falling behind naps after each
    update, and an answer given there used to wait out the rebase budget."""
    _CI[0], _MSTATE[0] = CiDecision(verdict="success"), "behind"
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)

        async def updated():
            return _UPDATES and await h.query(JobWorkflow.awaiting_merge)
        await _until("the watch resting after a branch update", updated)
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        await h.result()
    assert _CLOSED == ["https://x/pr/1"] and len(_UPDATES) == 1, (
        f"{len(_UPDATES)} branch updates ran before the answer was read")
    waited = _AT["close"] - _AT["update"]
    assert waited < _PROMPTLY, (
        f"the close was scheduled {waited} after the branch update — that nap did not wake")


async def test_an_answer_wakes_the_nap_after_a_refused_self_merge_too(env: WorkflowEnvironment):
    """The third nap: a green, mergeable pull request on the machine-merge path whose self-merge
    the forge refuses. A person who gives up on it there is heard at once, too."""
    _CI[0], _MSTATE[0], _AUTO[0] = CiDecision(verdict="success"), "clean", True
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)

        async def refused():
            return _FORCED and await h.query(JobWorkflow.awaiting_merge)
        await _until("the watch resting after a refused self-merge", refused)
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        await h.result()
    assert _CLOSED == ["https://x/pr/1"] and len(_FORCED) == 1
    waited = _AT["close"] - _AT["force"]
    assert waited < _PROMPTLY, (
        f"the close was scheduled {waited} after the refused self-merge — that nap did not wake")


# ── 3. a job already in the watch ───────────────────────────────────────────────────────────────

MARKER = "the-gate-is-heard-on-every-path"


def _patched_as(monkeypatch, answer: bool):
    """`workflow.patched`, answering `answer` for THIS marker and the truth for every other."""
    from temporalio import workflow as tw

    real = tw.patched
    monkeypatch.setattr(tw, "patched", lambda name: answer if name == MARKER else real(name))


async def test_a_job_that_cannot_hear_says_so_and_replays_what_it_recorded(
        env: WorkflowEnvironment, monkeypatch):
    """A job that was in the loop before the marker runs the sequence it recorded, in which
    nothing reads the gate while the checks are red. It must not LOOK answerable there: the
    merge wait carries the sentence and the one seam every surface answers through refuses.

    WHAT THE REPLAY PROVES AND WHAT IT DOES NOT. The history is recorded with `patched` answering
    False for this one marker — the arm a pre-marker history selects — and replayed through the
    real `patched()`. That proves the marker gates every command this slice added. It is not a
    history written by the old binary; the un-heard arm being the old sequence is a read of the
    diff (a `sleep` where there was a `sleep`, and no consumption).

    THE RECORDING CARRIES AN ANSWER, and it has to. Measured: with nobody answering, the two arms
    write the SAME history — a `wait_condition` with a timeout and a `sleep` are both one timer —
    so a replay of such a history through the heard arm passes and verifies nothing. The arms
    differ only where an answer exists: the heard arm closes the pull request, the recorded one
    runs its second repair. So a Discard is signalled straight at the workflow (past the seam
    that would refuse it, as a page left open would), and is — on this arm — never read."""
    with monkeypatch.context() as m:
        _patched_as(m, False)
        async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
            h = await _start(env.client)
            gate = await _napping_after_a_repair(h)
            assert "before an answer could be heard" in view.gate_cannot_hear(gate), (
                "a gate nothing reads on this path is still published as answerable")
            await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
            result = await h.result()  # red to the end: both repairs, then the hold
        history = await h.fetch_history()
    assert result.state == JobState.ON_HOLD and len(_REPAIRS) == 2 and _CLOSED == [], (
        "the recording is not the un-heard arm it claims to be")

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    # VERIFY THE VERIFIER: the same history through the heard arm must diverge — it consumes the
    # answer where the recording ran a repair — or the green replay above proves nothing.
    _patched_as(monkeypatch, True)
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    # THE DIVERGENCE HAS TWO SPELLINGS. Measured on temporalio 1.32: the heard arm wakes at the
    # recorded signal and cancels the nap's timer, and the engine's state machine refuses the
    # history's `TimerFired` for a timer it was just told to cancel — a fatal "transition is
    # invalid" rather than the word "nondeterminism". Both mean the same thing: this history was
    # not written by this sequence.
    said = str(caught.value)
    assert ("CancelTimerCommandSent" in said or "determinis" in said.lower()
            or "TMPRL1100" in said), f"the ungated replay failed for another reason: {said[:400]}"


async def test_a_job_that_CAN_hear_is_not_told_it_cannot(env: WorkflowEnvironment):
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS):
        h = await _start(env.client)
        gate = await _napping_after_a_repair(h)
        assert "cannot_hear" not in gate and view.gate_cannot_hear(gate) == ""
        await h.signal(JobWorkflow.human_merge_gate, args=["discard", "", "a-person"])
        await h.result()

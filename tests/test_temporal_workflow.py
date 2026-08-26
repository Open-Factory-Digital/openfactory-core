"""JobWorkflow orchestration, proven deterministically.

Runs the REAL workflow against Temporal's time-skipping test environment with
MOCKED activities (no GitHub, no sandbox), so it exercises the workflow's
branching and the durable human-in-the-loop — fast, repeatable, offline. The
mocks share the real activities' names, so the workflow is unmodified.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts import JobState, RunResult
from openfactory.runtime.temporal.io import (
    CiRepairInput,
    CoordinatorInput,
    CoordinatorItem,
    CoordinatorSayInput,
    HoldSyncInput,
    JobParams,
    KnowledgeRefreshInput,
    MergeCheckInput,
    PollInput,
    PreflightInput,
    PreflightVerdict,
    PromoteInput,
    RatePauseInput,
    ReleaseInput,
    RunJobInput,
    ScanInput,
    SplitInput,
    StartJobsInput,
)
from openfactory.runtime.temporal.workflow import JobWorkflow

#: THIS FILE STARTS ITS OWN ENGINE, and says so rather than being guessed at.
#: `WorkflowEnvironment.start_time_skipping` boots an ephemeral Temporal on a port it picked and
#: owns its whole life — the only legitimate reason in this suite to open a real connection.
#: Everything else is blocked by `conftest._no_live_durable_engine`, because a run on a machine
#: with the OSS compose stack up created real workflows on a developer's engine (#107).
pytestmark = pytest.mark.owns_its_engine

TQ = "test-openfactory-jobs"

# Real-time budget for the query-polling helpers below. These wait for the workflow to REACH a
# state; the environment skips the workflow's timers but our sleeps are wall-clock, so this is a
# bet on machine speed. Each loop breaks the moment the state appears, so a generous budget costs
# nothing when things are fast and only buys slack when they are not. It is deliberately large
# because a flake here BLOCKS THE DEPLOY: infra/deploy.sh runs this suite before rolling out.
_POLL_TRIES = 1500  # × 20ms ≈ 30s
_POLL_SLEEP = 0.02



def test_worker_registers_every_activity_the_workflows_call():
    """Guard: an activity imported but left out of the worker's registration list is invisible
    until it's INVOKED in prod, where it fails NotFoundError (how github_budget shipped once
    unregistered and broke the poll). Assert the poller's activities are all registered."""
    from openfactory.runtime.temporal.worker import WORKER_ACTIVITIES

    names = {getattr(a, "__name__", None) for a in WORKER_ACTIVITIES}
    for required in ("tracker_budgets", "scan_projects", "scan_todo", "start_jobs",
                     "available_slots", "preflight_check", "split_ticket", "run_job"):
        assert required in names, f"{required} is not registered on the worker"
    assert len(names) == len(WORKER_ACTIVITIES)  # no duplicate registrations


# -- mocked activities (same names as the real ones) --------------------------
@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1")


@activity.defn(name="promote_staging")
async def mock_promote_staging(inp: PromoteInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.AWAITING_PROD_APPROVAL)


@activity.defn(name="release_prod")
async def mock_release_prod(inp: ReleaseInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.DONE)


@activity.defn(name="check_pr_status")
async def mock_status_merged(inp: MergeCheckInput) -> str:
    return "merged"  # merged immediately — promotion may proceed


@activity.defn(name="check_pr_status")
async def mock_status_open(inp: MergeCheckInput) -> str:
    return "open"  # never merges → holds at the deadline


@activity.defn(name="check_pr_status")
async def mock_status_closed(inp: MergeCheckInput) -> str:
    return "closed"  # a human closed the PR WITHOUT merging → hold at once (ADR-0007)


@activity.defn(name="stop_job")
async def mock_stop_job(inp: RunJobInput) -> int:
    _STOPPED.append(inp.issue)
    return 1


@activity.defn(name="run_job")
async def failing_run_job(inp: RunJobInput) -> RunResult:
    raise RuntimeError("boom")


_RUN_CALLS: list[str] = []


@activity.defn(name="run_job")
async def paused_then_ok_run_job(inp: RunJobInput) -> RunResult:
    _RUN_CALLS.append(inp.issue)
    if len(_RUN_CALLS) == 1:
        return RunResult(ticket_id=inp.issue, state=JobState.PAUSED, note="rate limited")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN)


_RESUME_HANDLES: list[str | None] = []
_RESUME_ATTEMPTS: list[int] = []


@activity.defn(name="run_job")
async def paused_with_handle_then_ok(inp: RunJobInput) -> RunResult:
    # C2: the first pass pauses AND reports an opaque resume_handle; the workflow must feed that
    # exact handle back into the SECOND run_job so the attempt continues instead of restarting.
    _RESUME_HANDLES.append(inp.resume_handle)
    _RESUME_ATTEMPTS.append(inp.attempt)
    if len(_RESUME_HANDLES) == 1:
        return RunResult(ticket_id=inp.issue, state=JobState.PAUSED, note="rate limited",
                         resume_handle="opaque-session-token")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN)


_HOLD_HANDLES: list[str | None] = []


@activity.defn(name="run_job")
async def resumable_hold_then_ok(inp: RunJobInput) -> RunResult:
    # ADR-0013 D1: a hold that CARRIES a resume_handle preserved partial work — the operator's
    # Resume must CONTINUE it (thread the handle), not restart clean.
    _HOLD_HANDLES.append(inp.resume_handle)
    if len(_HOLD_HANDLES) == 1:
        return RunResult(ticket_id=inp.issue, state=JobState.ON_HOLD,
                         note="agent stopped: turn cap", resume_handle="preserved-handle")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN)


_FAILED_CALLS: list[str] = []


@activity.defn(name="run_job")
async def failed_then_ok(inp: RunJobInput) -> RunResult:
    # A box crash arrives as a RETURNED FAILED result (the entrypoint always emits a contract
    # result). It must PARK like any impediment — not complete-and-free the floor.
    _FAILED_CALLS.append(inp.issue)
    if len(_FAILED_CALLS) == 1:
        return RunResult(ticket_id=inp.issue, state=JobState.FAILED,
                         note="box failed: prepare crashed")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN)


_STOPPED: list[str] = []

@activity.defn(name="fetch_ticket_title")
async def mock_fetch_ticket_title(inp) -> str:
    return "a ticket"


@activity.defn(name="check_ci_status")
async def mock_ci_success(inp: MergeCheckInput) -> str:
    return "success"


# Every merge path now ends with the post-merge Knowledge Pipeline. Registering it keeps these
# tests on the INTENDED path: without it the activity is simply not found, and each merge test
# silently exercises the swallow-the-failure branch instead (plus pays its failure latency, which
# is exactly the kind of drag that turns a real-time polling assertion flaky).
_REFRESHED: list[str] = []


@activity.defn(name="refresh_knowledge")
async def mock_refresh_knowledge(inp: KnowledgeRefreshInput) -> str:
    _REFRESHED.append(inp.project)
    return "published"


@activity.defn(name="pr_mergeable_state")
async def mock_mergeable_blocked(inp: MergeCheckInput) -> str:
    return "blocked"  # checks pending — the watch waits (no rebase, no escalate)


@activity.defn(name="pr_mergeable_state")
async def mock_mergeable_behind(inp: MergeCheckInput) -> str:
    return "behind"  # base advanced — the watch auto-updates the branch


@activity.defn(name="update_pr_branch")
async def mock_update_branch(inp: MergeCheckInput) -> bool:
    return True


@activity.defn(name="notify_coordinator")
async def mock_notify_coordinator(item: CoordinatorItem) -> None:
    return None  # a decision-park hands off to the coordinator; tests no-op it


@activity.defn(name="notify_coordinator_say")
async def mock_notify_say(inp: CoordinatorSayInput) -> None:
    return None  # narration (pickup/merge/park) is a side-effect; tests no-op it


@activity.defn(name="diagnose_impediment")
async def mock_diagnose_impediment(inp: HoldSyncInput) -> bool:
    return False  # the tech-lead diagnosis fires on a park; no-op it in workflow tests


@activity.defn(name="preflight_check")
async def mock_preflight_fit(inp: PreflightInput) -> PreflightVerdict:
    return PreflightVerdict(verdict="fit")


@activity.defn(name="preflight_check")
async def mock_preflight_split(inp: PreflightInput) -> PreflightVerdict:
    return PreflightVerdict(verdict="split", reasons="two features",
                            children=[{"title": "a", "objective": "o", "criteria": ["c"]},
                                      {"title": "b", "objective": "o2", "criteria": ["c2"]}])


@activity.defn(name="preflight_check")
async def mock_preflight_unclear(inp: PreflightInput) -> PreflightVerdict:
    return PreflightVerdict(verdict="unclear", questions=["what exactly is the outcome?"])


_SPLIT_CALLS: list[SplitInput] = []


@activity.defn(name="split_ticket")
async def mock_split_ticket(inp: SplitInput) -> str:
    _SPLIT_CALLS.append(inp)
    return "split into #100, #101"


@activity.defn(name="mark_needs_action")
async def mock_mark_needs_action(inp) -> str:
    return "ok"


MOCKS = [mock_run_job, mock_status_merged, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
         mock_release_prod, mock_fetch_ticket_title, mock_ci_success]


async def _worker(env: WorkflowEnvironment) -> Worker:
    return Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=MOCKS)


async def _start(client: Client, params: JobParams):
    return await client.start_workflow(
        JobWorkflow.run, params, id=f"wf-{uuid.uuid4()}", task_queue=TQ
    )


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _parked(h, env, *, state: str = "", advance=timedelta(minutes=45),
                  step=timedelta(minutes=1)) -> dict:
    """Advance the clock ONCE past the auto-update cycles, then wait for the park in real time.

    TWO WRONG SHAPES CAME BEFORE THIS ONE, AND BOTH ARE INSTRUCTIVE.

    The original was `await env.sleep(30 minutes)` and then a bare query — a race that only lost
    under load, which is the worst kind of flake because it teaches everyone to re-run instead of
    to look. It failed in the full suite (~4200 tests on a contended CPU) and passed alone, and the
    same seed gave different answers across runs, so it was never an ordering leak.

    The obvious fix — advance a little, look, repeat — was WORSE, and the reason is the point.
    `WorkflowEnvironment.start_time_skipping` auto-skips to the next timer whenever every workflow
    is blocked on one, so repeated `env.sleep` calls do not add up to their arguments: the clock
    leaps. With `merge_deadline_days=30` in play it leapt straight past the escalation window to
    the DEADLINE, and the job parked `on_hold` — a real park, on the real code path, that simply is
    not the one under test. Only saying which state we were waiting for made that visible; waiting
    for any truthy park had quietly accepted the wrong one.

    Wall-clock polling is not the answer either, and that was the third wrong shape: the
    environment auto-skips whenever every workflow is blocked on a timer, so simply WAITING —
    in real time or simulated — lets the clock run. There is no way to hold it still.

    What actually works is to stop the DEADLINE from competing. These tests are about the rebase
    budget, so their `merge_deadline_days` is pushed far out of reach; then small advances walk the
    clock to the escalation without any chance of arriving at a park the test is not about. The
    caller says which state it wants, so an arrival at the wrong one is reported by name instead of
    being silently accepted.
    """
    seen: list[str] = []
    waited = timedelta()
    while waited <= advance:
        act = await h.query(JobWorkflow.awaiting_action)
        if act and (not state or act.get("state") == state):
            return act
        if act and (line := f"{act.get('state')}: {act.get('note') or '(no note)'}") not in seen:
            # THE NOTE, not just the state. "Parks seen: ['on_hold']" says the job stopped
            # somewhere else; the note says WHY, which is the difference between a diagnosis and a
            # rerun. The park carries it already (`workflow.py::_park` copies `result.note`).
            seen.append(line)
        await env.sleep(step)
        waited += step
    raise AssertionError(
        f"the job never parked on {state or 'a decision'} — it is either still working or it "
        f"stalled SILENTLY, which is the invariant this test guards. Parks seen: {seen or 'none'}"
    )


async def test_human_path_holds_floor_until_merge(env: WorkflowEnvironment):
    # ADR-0007: even the human-review path (no auto_merge) now waits for the PR to actually
    # MERGE — the floor stays held so the next ticket builds on a base that includes this one.
    _REFRESHED.clear()
    async with await _worker(env):
        h = await _start(env.client, JobParams(project="p", issue="10", promote=False))
        result = await h.result()
    assert result.state == JobState.MERGED  # waited for the merge (mock: merged), didn't stop at PR
    assert result.pr_url == "https://x/pr/1"
    # reality changed, so the Knowledge Pipeline runs — post-merge, and without holding the floor
    assert _REFRESHED == ["p"]


async def test_human_path_holds_until_deadline_when_never_merged(env: WorkflowEnvironment):
    # a human PR that never merges holds the floor only until the deadline, then releases (ON_HOLD)
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_open, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod, mock_fetch_ticket_title, mock_ci_success, mock_mergeable_blocked],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="10", promote=False,
                                               merge_deadline_days=1))
        result = await h.result()  # time-skips the merge-wait window
    assert result.state == JobState.ON_HOLD
    assert "not merged" in (result.note or "").lower()


async def test_closed_pr_holds_immediately_not_at_deadline(env: WorkflowEnvironment):
    # ADR-0007: a human who CLOSES the PR without merging must free the floor AT ONCE. The
    # merge_deadline is the DEFAULT 14 days here — if the watch polled it out the test would
    # hang; a prompt ON_HOLD proves the closed-PR early-exit, not a deadline timeout.
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_closed, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod, mock_fetch_ticket_title, mock_ci_success],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="10", promote=False))
        result = await h.result()
    assert result.state == JobState.ON_HOLD
    assert "closed without merging" in (result.note or "").lower()


async def test_promotes_to_prod_on_approval_signal(env: WorkflowEnvironment):
    import asyncio

    async with await _worker(env):
        h = await _start(env.client, JobParams(project="p", issue="10", promote=True))
        # a premature approval is dropped (M6) — wait until parked at the gate, then approve
        for _ in range(_POLL_TRIES):
            if await h.query(JobWorkflow.awaiting_approval):
                break
            await asyncio.sleep(_POLL_SLEEP)
        await h.signal(JobWorkflow.approve_prod, args=["1.2.0", "alice", "ship it"])
        result = await h.result()
    assert result.state == JobState.DONE


async def test_premature_approval_is_dropped(env: WorkflowEnvironment):
    async with await _worker(env):
        h = await _start(
            env.client,
            JobParams(project="p", issue="10", promote=True, approval_deadline_days=1),
        )
        # signal immediately, before the gate — must NOT bypass; job holds at the deadline
        await h.signal(JobWorkflow.approve_prod, args=["9.9.9", "ghost", "sneaky"])
        result = await h.result()
    assert result.state == JobState.ON_HOLD


async def test_paused_job_resumes_durably_inside_the_workflow(env: WorkflowEnvironment):
    _RUN_CALLS.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[paused_then_ok_run_job, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="9", sandbox="fargate"))
        result = await h.result()  # time-skips the resume backoff
    assert result.state == JobState.PR_OPEN  # resumed past the rate-limit pause
    assert len(_RUN_CALLS) == 2  # paused once, then succeeded — never silently stalled


async def test_pause_threads_resume_handle_into_the_next_run(env: WorkflowEnvironment):
    # C2 end-to-end through the durable workflow: the paused attempt's opaque handle must reach
    # the resumed run_job — the first call gets None (fresh), the second gets the exact handle.
    _RESUME_HANDLES.clear()
    _RESUME_ATTEMPTS.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[paused_with_handle_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="9", sandbox="fargate"))
        result = await h.result()  # time-skips the resume backoff
    assert result.state == JobState.PR_OPEN
    assert _RESUME_HANDLES == [None, "opaque-session-token"]  # fresh, then resumed with the handle
    # each lifecycle iteration is discriminated for launcher idempotency: a resume must launch
    # a FRESH task, never reconcile the previous iteration's stale stopped result (audit MED)
    assert _RESUME_ATTEMPTS == [0, 1]


async def test_preflight_fit_runs_the_job_normally(env: WorkflowEnvironment):
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_preflight_fit, *MOCKS],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="10", promote=False))
        result = await h.result()
    assert result.state == JobState.MERGED  # gate said fit → the normal lifecycle ran


async def test_preflight_split_creates_children_and_frees_the_floor(env: WorkflowEnvironment):
    # ADR-0013 D3: an oversized ticket is SPLIT — children created, workflow completes
    # deliberately (floor freed), and NO run_job / Fargate ever happens.
    _SPLIT_CALLS.clear()
    ran: list[str] = []

    @activity.defn(name="run_job")
    async def must_not_run(inp: RunJobInput) -> RunResult:
        ran.append(inp.issue)
        return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN)

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_preflight_split, mock_split_ticket, must_not_run, mock_status_merged,
                    mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title, mock_ci_success],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="37", promote=False))
        result = await h.result()
    assert result.state == JobState.DONE
    assert "split into" in (result.note or "")
    assert len(_SPLIT_CALLS) == 1 and len(_SPLIT_CALLS[0].children) == 2
    assert ran == []  # the expensive path never launched


async def test_preflight_unclear_parks_for_refinement(env: WorkflowEnvironment):
    # unclear → needs_refinement PARK (single-line: floor held until Resume/Skip), and a
    # Resume re-runs — preflight judges the improved ticket again.
    calls = {"n": 0}

    @activity.defn(name="preflight_check")
    async def unclear_then_fit(inp: PreflightInput) -> PreflightVerdict:
        calls["n"] += 1
        if calls["n"] == 1:
            return PreflightVerdict(verdict="unclear", questions=["scope?"])
        return PreflightVerdict(verdict="fit")

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[unclear_then_fit, *MOCKS],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="10", promote=False))
        await _wait_parked(h)
        act = await h.query(JobWorkflow.awaiting_action)
        assert act and "can't size" in act["note"]
        await h.signal(JobWorkflow.act_on_impediment, args=["resume"])
        result = await h.result()
    assert result.state == JobState.MERGED  # clarified → fit → normal run
    assert calls["n"] == 2  # preflight re-judged after the human clarified


async def test_resumable_hold_resume_continues_with_the_handle(env: WorkflowEnvironment):
    # ADR-0013 D1: hold with a handle → operator Resume threads the handle into the re-run
    # (continue), instead of clearing it (the old always-fresh semantics).
    _HOLD_HANDLES.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[resumable_hold_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="9", sandbox="fargate"))
        await _wait_parked(h)
        await h.signal(JobWorkflow.act_on_impediment, args=["resume"])
        result = await h.result()
    assert result.state == JobState.PR_OPEN
    assert _HOLD_HANDLES == [None, "preserved-handle"]  # fresh, then CONTINUED


async def test_failed_result_parks_instead_of_freeing_the_floor(env: WorkflowEnvironment):
    # Audit HIGH: a box crash returns FAILED — before this fix it fell through the park logic
    # and COMPLETED the workflow, silently freeing the floor with the ticket abandoned
    # (violating ADR-0010's "every non-progressing outcome parks").
    _FAILED_CALLS.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[failed_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="9", sandbox="fargate"))
        await _wait_parked(h)  # FAILED → parked as an impediment, floor held
        act = await h.query(JobWorkflow.awaiting_action)
        assert act and act["kind"] == "impediment"
        await h.signal(JobWorkflow.act_on_impediment, args=["resume"])
        result = await h.result()
    assert result.state == JobState.PR_OPEN  # operator resumed → the re-run succeeded
    assert len(_FAILED_CALLS) == 2


_MARK_CALLS: list[dict] = []


@activity.defn(name="mark_needs_action")
async def spy_mark_needs_action(inp: HoldSyncInput) -> str:
    _MARK_CALLS.append({"issue": inp.issue, "state": inp.state, "note": inp.note})
    return "creator-bob"  # the ticket's author, so the coordinator can route the escalation


@pytest.mark.asyncio
async def test_park_reconciles_board_to_needs_action(env: WorkflowEnvironment):
    # #394: the in-job orchestrator sets the board as it parks — but a crashed/timed-out job dies
    # first, leaving the ticket reading "In progress" while it actually needs a human. The
    # WORKFLOW must reconcile the tracker itself (→ Needs Action) when it parks an impediment.
    _FAILED_CALLS.clear()
    _MARK_CALLS.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[failed_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod, spy_mark_needs_action],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="9", sandbox="fargate"))
        await _wait_parked(h)
        assert _MARK_CALLS, "parking must reconcile the board (→ Needs Action)"
        assert _MARK_CALLS[0]["state"] == JobState.FAILED.value  # the parked state, mapped by tracker
        assert _MARK_CALLS[0]["issue"] == "9"
        await h.signal(JobWorkflow.act_on_impediment, args=["resume"])
        await h.result()


_IMP_CALLS: list[str] = []


@activity.defn(name="run_job")
async def hold_then_ok(inp: RunJobInput) -> RunResult:
    _IMP_CALLS.append(inp.issue)
    if len(_IMP_CALLS) == 1:  # first pass: an impediment (e.g. spec missing acceptance criteria)
        return RunResult(ticket_id=inp.issue, state=JobState.NEEDS_REFINEMENT,
                         note="ticket has no acceptance criteria")
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/9")


@activity.defn(name="run_job")
async def always_hold(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.NEEDS_REFINEMENT, note="no AC")


async def _wait_parked(h) -> None:
    import asyncio
    for _ in range(_POLL_TRIES):
        if await h.query(JobWorkflow.awaiting_action):
            return
        await asyncio.sleep(_POLL_SLEEP)


async def test_impediment_parks_holding_the_floor_then_resume_reruns(env: WorkflowEnvironment):
    # ADR-0010 single-line strict: an impediment PARKS (holds the floor) instead of completing;
    # the operator's Resume re-runs the (now-fixed) ticket from the top → it merges.
    _IMP_CALLS.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[hold_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod, mock_fetch_ticket_title, mock_ci_success],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="40", promote=False))
        await _wait_parked(h)
        act = await h.query(JobWorkflow.awaiting_action)
        assert act and act["kind"] == "impediment" and "acceptance" in act["note"]
        await h.signal(JobWorkflow.act_on_impediment, args=["resume"])
        result = await h.result()
    assert result.state == JobState.MERGED  # re-ran the fixed ticket → merged
    assert len(_IMP_CALLS) == 2  # parked once, resumed, then succeeded


@workflow.defn
class _AdviseSpy:
    """A stand-in for a parked JobWorkflow — records the advise_decision signal the coordinator
    relays, so we can assert the tech-lead's briefing reached the job."""

    def __init__(self) -> None:
        self._advice = None

    @workflow.signal
    async def advise_decision(self, advice: dict) -> None:
        self._advice = advice

    @workflow.run
    async def run(self) -> dict:
        await workflow.wait_condition(lambda: self._advice is not None)
        return self._advice


async def test_coordinator_advises_a_parked_decision(env: WorkflowEnvironment):
    # The always-alive coordinator: on a parked decision it reasons (mocked here) and RELAYS a
    # humanized briefing back to the job (advise_decision). v0 advisory — it never acts.
    from openfactory.runtime.temporal.workflow import CoordinatorWorkflow

    @activity.defn(name="coordinator_advise")
    async def mock_advise(item: CoordinatorItem) -> dict:
        return {"summary": "behind a busy main", "recommend": "merge",
                "rationale": "CI is green; force it in", "watch_outs": ""}

    worker = Worker(env.client, task_queue=TQ, workflows=[CoordinatorWorkflow, _AdviseSpy],
                    activities=[mock_advise])
    async with worker:
        spy = await env.client.start_workflow(_AdviseSpy.run, id=f"spy-{uuid.uuid4()}",
                                              task_queue=TQ)
        coord = await env.client.start_workflow(
            CoordinatorWorkflow.run, CoordinatorInput(project="p"),
            id=f"coord-{uuid.uuid4()}", task_queue=TQ)
        await coord.signal(CoordinatorWorkflow.on_decision, CoordinatorItem(
            project="p", issue="1", job_id=spy.id, kind="merge", question="how to land it?",
            options=[{"key": "merge", "label": "merge now"}]))
        advice = await spy.result()  # the coordinator relayed its take to the (parked) job
    assert advice["recommend"] == "merge" and "busy main" in advice["summary"]


async def test_blocked_parks_with_options_then_resume_injects_the_choice(env: WorkflowEnvironment):
    # DecisionRequest round-trip: a BLOCKED result parks with OPTIONS (awaiting_action.decision),
    # and answering with a choice key resumes the job with that option resolved and injected into
    # the next run (the agent proceeds with it, never re-asks). "No park without options" (owner).
    from openfactory.contracts import canned
    dr = canned("plan", "Which store for the durable rate limit?",
                [("A", "Postgres", "durable; already a dep"),
                 ("B", "SQLite", "simpler; new file store")], default="A")
    seen: list[str] = []

    @activity.defn(name="run_job")
    async def blocked_then_ok(inp: RunJobInput) -> RunResult:
        seen.append(inp.decision)
        if len(seen) == 1:
            return RunResult(ticket_id=inp.issue, state=JobState.BLOCKED, decision=dr)
        return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1")

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[blocked_then_ok, mock_status_merged, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod, mock_fetch_ticket_title, mock_ci_success, mock_notify_coordinator],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="60", promote=False))
        await _wait_parked(h)
        act = await h.query(JobWorkflow.awaiting_action)
        assert act["state"] == "blocked" and act["decision"]  # parked WITH options
        assert [o["key"] for o in act["decision"]["options"]] == ["A", "B"]
        await h.signal(JobWorkflow.act_on_impediment, args=["resume", "A"])  # answer: option A
        result = await h.result()
    assert result.state == JobState.MERGED  # resumed and completed
    assert seen[0] == ""  # first run had no decision
    assert seen[1].startswith("DECISION A") and "Postgres" in seen[1]  # the choice was injected


async def test_behind_pr_is_auto_updated_then_merges(env: WorkflowEnvironment):
    # Busy-main resilience: a BEHIND PR (other devs advanced the base) is brought up to date by
    # the watch so auto-merge can fire — instead of silently waiting on a merge that never comes.
    updates = {"n": 0}

    @activity.defn(name="update_pr_branch")
    async def counting_update(inp: MergeCheckInput) -> bool:
        updates["n"] += 1
        return True

    @activity.defn(name="check_pr_status")
    async def behind_then_merged(inp: MergeCheckInput) -> str:
        return "merged" if updates["n"] >= 1 else "open"  # merges once we've updated it

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, behind_then_merged, mock_ci_success, mock_mergeable_behind,
                    counting_update, mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="70", promote=False))
        result = await h.result()
    assert result.state == JobState.MERGED  # landed after the auto-update
    assert updates["n"] >= 1  # the watch updated the BEHIND branch (self-heal)


async def test_behind_pr_escalates_to_a_decision_after_the_rebase_budget(env: WorkflowEnvironment):
    # Never a silent forever-wait (owner): a PR that keeps falling behind is auto-updated only up
    # to the bound, then PARKS on a DecisionRequest with EXECUTABLE options (wait / merge / skip)
    # — the human decides, the factory acts. Here the operator skips → SKIPPED (2026-08-16: a
    # person's decision gets its own state; `on_hold` is what the job was BEFORE they answered).
    @activity.defn(name="update_pr_branch")
    async def always_update(inp: MergeCheckInput) -> bool:
        return True

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_open, mock_ci_success, mock_mergeable_behind,
                    always_update, mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title, mock_notify_coordinator, mock_notify_say,
                    # REGISTERED BECAUSE THE WORKFLOW CALLS THEM ON THIS PATH. Their absence is
                    # the whole story behind these two tests being "intermittent": the workflow
                    # raised NotFoundError for `preflight_check`, parked `on_hold`, and the
                    # assertion compared that park to the escalation it was waiting for. It looked
                    # like a timing race for as long as nobody asked WHICH park had happened.
                    mock_preflight_fit, mock_mark_needs_action,
                    mock_diagnose_impediment],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="71", promote=False,
                                               merge_deadline_days=3650))
        act = await _parked(h, env, state="blocked")
        assert act["decision"]  # parked WITH options, not silent
        keys = [o["key"] for o in act["decision"]["options"]]
        assert "wait" in keys and "merge" in keys and "skip" in keys  # executable choices
        await h.signal(JobWorkflow.act_on_impediment, args=["skip", ""])
        result = await h.result()
    # ANSWERED, so the state says a person answered. "Escalated and never stuck forever" is what
    # this test guards; `on_hold` said the escalation was still open after somebody closed it.
    assert result.state == JobState.SKIPPED
    assert "behind" in (result.note or "").lower()  # the problem is stated


async def test_behind_pr_merge_now_choice_force_merges(env: WorkflowEnvironment):
    # The 'merge now' option is EXECUTABLE — picking it force-merges the PR (factory acts).
    forced = {"n": 0}

    @activity.defn(name="update_pr_branch")
    async def always_update(inp: MergeCheckInput) -> bool:
        return True

    @activity.defn(name="force_merge_pr")
    async def force_merge(inp: MergeCheckInput) -> bool:
        forced["n"] += 1
        return True

    @activity.defn(name="check_pr_status")
    async def open_then_merged(inp: MergeCheckInput) -> str:
        return "merged" if forced["n"] >= 1 else "open"

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, open_then_merged, mock_ci_success, mock_mergeable_behind,
                    always_update, force_merge, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod, mock_fetch_ticket_title, mock_notify_coordinator,
                    mock_notify_say, mock_preflight_fit, mock_mark_needs_action,
                    mock_diagnose_impediment],
    )
    async with worker:
        # THE DEADLINE IS PUSHED OUT OF REACH ON PURPOSE. This test is about the REBASE BUDGET;
        # with the default deadline the time-skipping clock could reach it first and the job parked
        # `on_hold` — a real park, on real code, that is simply not the one under test.
        h = await _start(env.client, JobParams(project="p", issue="72", promote=False,
                                               merge_deadline_days=3650))
        assert await _parked(h, env, state="blocked")  # parked on the merge decision
        await h.signal(JobWorkflow.act_on_impediment, args=["resume", "merge"])  # merge now
        result = await h.result()
    assert result.state == JobState.MERGED and forced["n"] >= 1  # the factory force-merged


async def test_clean_mergeable_pr_self_merges_when_auto_merge_did_not_fire(env: WorkflowEnvironment):
    # ROOT FIX (never blocked): a PR that is CLEAN (all required checks passed, up-to-date) on the
    # machine-merge path but hasn't landed — `--auto` was never armed or got cleared — must be
    # merged by the factory itself, not left waiting out the 14-day deadline. A tech-lead lands it.
    forced = {"n": 0}

    @activity.defn(name="run_job")
    async def armed_run_job(inp: RunJobInput) -> RunResult:
        return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN,
                         pr_url="https://x/pr/1", auto_merge=True)

    @activity.defn(name="pr_mergeable_state")
    async def mergeable_clean(inp: MergeCheckInput) -> str:
        return "clean"  # mergeable NOW — but nothing is merging it

    @activity.defn(name="force_merge_pr")
    async def force_merge(inp: MergeCheckInput) -> bool:
        forced["n"] += 1
        return True

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[armed_run_job, mock_status_open, mock_ci_success, mergeable_clean,
                    force_merge, mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="73", promote=False))
        result = await h.result()
    assert result.state == JobState.MERGED and forced["n"] >= 1  # self-healed, never blocked


async def test_clean_pr_on_human_path_is_not_self_merged(env: WorkflowEnvironment):
    # GUARD: the self-heal is gated on auto_merge — a CLEAN PR on the HUMAN-review path (a human
    # must merge) is NEVER force-merged by the factory; it waits for the human (holds at deadline).
    forced = {"n": 0}

    @activity.defn(name="run_job")
    async def human_run_job(inp: RunJobInput) -> RunResult:
        return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN,
                         pr_url="https://x/pr/1", auto_merge=False)

    @activity.defn(name="pr_mergeable_state")
    async def mergeable_clean(inp: MergeCheckInput) -> str:
        return "clean"

    @activity.defn(name="force_merge_pr")
    async def force_merge(inp: MergeCheckInput) -> bool:
        forced["n"] += 1
        return True

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[human_run_job, mock_status_open, mock_ci_success, mergeable_clean,
                    force_merge, mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="74", promote=False,
                                               merge_deadline_days=1))
        await env.sleep(timedelta(days=2))  # past the deadline → holds for the human
        result = await h.result()
    assert forced["n"] == 0  # never force-merged a human-review PR
    assert result.state == JobState.ON_HOLD


async def test_impediment_skip_completes_and_frees_the_floor(env: WorkflowEnvironment):
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[always_hold, mock_status_merged, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="41", promote=False))
        await _wait_parked(h)
        await h.signal(JobWorkflow.act_on_impediment, args=["skip"])
        result = await h.result()  # skip → completes, floor frees, and the DECISION is recorded
    # SKIPPED, not the parked state. The job carried `needs_refinement` into the gate; reporting
    # that back after a person answered says the gate is still waiting for them (pilot,
    # 2026-08-16). The reason survives on the ticket comment, which is where he asked for it.
    assert result.state == JobState.SKIPPED


async def test_impediment_deadline_auto_frees_the_floor(env: WorkflowEnvironment):
    # a forgotten block must not jam the queue forever — after impediment_deadline_days it
    # auto-skips (completes), freeing the floor.
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[always_hold, mock_status_merged, mock_stop_job, mock_refresh_knowledge, mock_promote_staging,
                    mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="42", promote=False,
                                               impediment_deadline_days=1))
        result = await h.result()  # no signal → time-skips past the deadline → auto-skip
    assert result.state == JobState.NEEDS_REFINEMENT


@activity.defn(name="check_ci_status")
async def mock_ci_failure(inp: MergeCheckInput) -> str:
    return "failure"


@activity.defn(name="repair_ci")
async def mock_repair_paused(inp: CiRepairInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PAUSED, note="session limit")


@activity.defn(name="run_job")
async def always_paused(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PAUSED, note="session limit")


async def test_ci_repair_pause_is_visible_and_skippable(env: WorkflowEnvironment):
    # CONSISTENCY (ADR-0010): a rate-limit DURING the CI repair must be a VISIBLE park —
    # awaiting_action exposes it (kind=rate_limit) and a Skip completes SKIPPED "skipped by
    # operator" (once, no second park) — never a blind 30-min sleep the panel can't see.
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_open, mock_ci_failure, mock_repair_paused,
                    mock_stop_job, mock_refresh_knowledge, mock_promote_staging, mock_release_prod,
                    mock_fetch_ticket_title],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="50", promote=False))
        await _wait_parked(h)
        act = await h.query(JobWorkflow.awaiting_action)
        assert act and act["kind"] == "rate_limit"  # the merge-loop pause is visible
        await h.signal(JobWorkflow.act_on_impediment, args=["skip"])
        result = await h.result()  # completes directly — the skip is not re-parked outside
    assert result.state == JobState.SKIPPED
    assert "skipped by operator" in (result.note or "")


async def test_rate_limit_skip_is_reported_as_the_decision_it_was(env: WorkflowEnvironment):
    # A skipped rate-limited job must NOT complete "paused", which reads as "will resume
    # automatically" when it never will. It used to normalise to `on_hold`, which was closer and
    # still wrong: a person answered, and `on_hold` is the state they answered FROM. The note
    # keeps saying what it was skipped from.
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[always_paused, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="51", promote=False))
        await _wait_parked(h)
        act = await h.query(JobWorkflow.awaiting_action)
        assert act and act["kind"] == "rate_limit"
        await h.signal(JobWorkflow.act_on_impediment, args=["skip"])
        result = await h.result()
    assert result.state == JobState.SKIPPED
    assert result.state != JobState.PAUSED, "it would read as 'will resume automatically'"
    assert "skipped by operator" in (result.note or "")


_MERGE_FLAG = {"merged": False}


@activity.defn(name="check_pr_status")
async def mock_status_flag(inp: MergeCheckInput) -> str:
    return "merged" if _MERGE_FLAG["merged"] else "open"


@activity.defn(name="run_job")
async def human_path_run_job(inp: RunJobInput) -> RunResult:
    # human-review path: PR opened, auto-merge NOT armed (e.g. a suppression handed over)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN,
                     pr_url="https://x/pr/7", auto_merge=False)


async def test_awaiting_merge_is_visible_while_waiting_for_a_human(env: WorkflowEnvironment):
    # The #69 lesson: a PR waiting for the OPERATOR's merge must be queryable — the panel
    # shows "PR ready — waiting for YOUR merge" instead of a silent "starting…" for hours.
    _MERGE_FLAG["merged"] = False
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[human_path_run_job, mock_status_flag, mock_ci_success, mock_mergeable_blocked, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod, mock_fetch_ticket_title],
    )
    async with worker:
        # `merge_deadline_days` OUT OF REACH — the module docstring's own cure, applied to the
        # `_parked` siblings and left off exactly this test. Without it the time-skipping engine
        # can burn the 14-day deadline while this real-time poll starves on a contended CPU; the
        # deadline exit clears `awaiting_merge` in its finally, every remaining query answers
        # None, and precisely ONE test fails — the 1-in-~18 full-suite flake whose name cost
        # fifteen suite runs to recover (2026-08-14). With the deadline unreachable and the
        # activities pinned (CI green, mergeable blocked, merged only when this test says so),
        # NO exit of the merge loop is reachable until the flag flips: the window cannot close,
        # so the poll below is a wait, not a race.
        h = await _start(env.client, JobParams(project="p", issue="60", promote=False,
                                               merge_deadline_days=3650))
        import asyncio
        mw = None
        for _ in range(_POLL_TRIES):
            mw = await h.query(JobWorkflow.awaiting_merge)
            if mw:
                break
            await asyncio.sleep(_POLL_SLEEP)
        # visible + honest: the PR link, the human-merge flag, and WHAT it's waiting for
        assert mw is not None, (
            "never observed awaiting_merge — and with merge_deadline_days out of reach this is "
            "no longer the Round-6 timing race: the merge wait either never became visible or "
            "cleared through an exit no activity in this test can trigger. Look for a "
            "regression, not a flake."
        )
        assert mw["pr_url"] == "https://x/pr/7" and mw["auto"] is False
        assert "note" in mw  # the panel shows what the wait is on (transparency)
        # the gate declares it can HEAR — the fx-mono dead-letter lesson. The first observed
        # wait may predate the loop's first iteration ("PR open — checking CI"), so poll on.
        for _ in range(_POLL_TRIES):
            if mw.get("gate_live") is not None:
                break
            await asyncio.sleep(_POLL_SLEEP)
            mw = await h.query(JobWorkflow.awaiting_merge) or mw
        assert mw.get("gate_live") is True, (
            "the merge wait never published whether its gate can hear — without it, "
            "answer_merge_gate cannot tell a live gate from a dead letter")
        _MERGE_FLAG["merged"] = True  # the human merged → the watch resolves
        result = await h.result()
        assert await h.query(JobWorkflow.awaiting_merge) is None  # cleared after the wait
    assert result.state == JobState.MERGED


async def test_a_crash_stops_the_task_and_parks(env: WorkflowEnvironment):
    # ADR-0010: a job that crashes after its retries must NOT silently free the floor — it stops
    # any lingering task and PARKS (as an impediment) until the operator acts (here: skip).
    _STOPPED.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[failing_run_job, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="77", sandbox="fargate",
                                               impediment_deadline_days=1))
        # crash → stop the task → park; no operator signal → the deadline auto-skips (frees the
        # floor). result() time-skips the activity retries AND the 1-day park in one go.
        result = await h.result()
    assert result.state == JobState.ON_HOLD
    assert "errored" in (result.note or "")  # the crash was parked as an impediment, not swallowed
    assert _STOPPED == ["77"]  # the lingering task was stopped before parking


async def test_a_crash_on_an_add_on_box_stops_it_from_the_STAMPED_traits(env: WorkflowEnvironment):
    """The workflow's own lookup cannot see an add-on's box (it is pure, by design), so the traits
    travel on `JobParams.box`, stamped by `start_jobs`. Driven through the real workflow: a box the
    built-in table has never heard of, declared remote, gets its `stop_job` on a crash. Without
    the stamp the same params RAISE inside the body — which is the honest answer, not a guess."""
    from openfactory.adapters.sandbox.registry import BoxTraits

    nomad = BoxTraits("nomad", remote=True, honours_image=True, idempotent=False, streams=False,
                      isolates_resources=True, transfers_state=True)
    _STOPPED.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[failing_run_job, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="78", sandbox="nomad", box=nomad,
                                               impediment_deadline_days=1))
        result = await h.result()
    assert result.state == JobState.ON_HOLD
    assert _STOPPED == ["78"], "a remote add-on box crashed and nothing stopped it"


_PROMOTED_ON: list[tuple[str, str]] = []


@activity.defn(name="promote_staging")
async def promote_recording_the_box(inp: PromoteInput) -> RunResult:
    _PROMOTED_ON.append(("staging", inp.sandbox))
    return RunResult(ticket_id=inp.issue, state=JobState.AWAITING_PROD_APPROVAL)


@activity.defn(name="release_prod")
async def release_recording_the_box(inp: ReleaseInput) -> RunResult:
    _PROMOTED_ON.append(("release", inp.sandbox))
    return RunResult(ticket_id=inp.issue, state=JobState.DONE)


async def test_promotion_runs_on_the_JOBS_box_not_the_workers(env: WorkflowEnvironment):
    """The live arm of `patched("promotion-box-kind")`, through the real workflow: both promotion
    inputs name the job's box — an add-on box the built-in table has never heard of — rather than
    `""` (which the activity resolves to the WORKER'S default, and refused non-retryably for a
    job on a remote add-on box promoted on a `container` worker)."""
    import asyncio

    from openfactory.adapters.sandbox.registry import BoxTraits

    nomad = BoxTraits("nomad", remote=True, honours_image=True, idempotent=False, streams=False,
                      isolates_resources=True, transfers_state=True)
    _PROMOTED_ON.clear()
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    promote_recording_the_box, release_recording_the_box, mock_fetch_ticket_title,
                    mock_ci_success],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="81", sandbox="nomad", box=nomad,
                                               promote=True))
        for _ in range(_POLL_TRIES):
            if await h.query(JobWorkflow.awaiting_approval):
                break
            await asyncio.sleep(_POLL_SLEEP)
        await h.signal(JobWorkflow.approve_prod, args=["1.0.0", "alice", "ship it"])
        result = await h.result()
    assert result.state == JobState.DONE
    assert _PROMOTED_ON == [("staging", "nomad"), ("release", "nomad")]


async def test_holds_when_prod_approval_times_out(env: WorkflowEnvironment):
    async with await _worker(env):
        h = await _start(
            env.client,
            JobParams(project="p", issue="10", promote=True, approval_deadline_days=2),
        )
        result = await h.result()  # no signal → time-skip past the deadline
    assert result.state == JobState.ON_HOLD
    assert result.note == "prod approval window elapsed"


@activity.defn(name="run_job")
async def run_job_with_environments(inp: RunJobInput) -> RunResult:
    # the manifest declares environments → the CONFIG asks for promotion (A2)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN,
                     pr_url="https://x/pr/2", environments=["staging", "prod"])


async def test_manifest_environments_drive_promotion_without_flag(env: WorkflowEnvironment):
    import asyncio

    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[run_job_with_environments, mock_status_merged, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod],
    )
    async with worker:
        # promote flag NOT set — the result's environments alone must trigger promotion
        h = await _start(env.client, JobParams(project="p", issue="30", promote=False))
        for _ in range(_POLL_TRIES):
            if await h.query(JobWorkflow.awaiting_approval):
                break
            await asyncio.sleep(_POLL_SLEEP)
        await h.signal(JobWorkflow.approve_prod, args=["1.0.0", "alice", ""])
        result = await h.result()
    assert result.state == JobState.DONE  # config-driven, end to end


async def test_unmerged_pr_never_promotes_holds_at_deadline(env: WorkflowEnvironment):
    worker = Worker(
        env.client, task_queue=TQ, workflows=[JobWorkflow],
        activities=[mock_run_job, mock_status_open, mock_stop_job, mock_refresh_knowledge,
                    mock_promote_staging, mock_release_prod, mock_mergeable_blocked],
    )
    async with worker:
        h = await _start(env.client, JobParams(project="p", issue="31", promote=True,
                                               merge_deadline_days=1))
        result = await h.result()  # time-skips the merge polling window
    assert result.state == JobState.ON_HOLD
    assert "not merged" in (result.note or "")  # staging NEVER ran against unmerged code


async def test_poll_workflow_scans_and_starts_new_tickets(env: WorkflowEnvironment):
    from openfactory.runtime.temporal.poller import PollWorkflow

    started_calls: list[StartJobsInput] = []

    @activity.defn(name="scan_projects")
    async def mock_scan_projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="scan_todo")
    async def mock_scan_todo(inp: ScanInput) -> list[str]:
        return ["101", "102"]

    @activity.defn(name="start_jobs")
    async def mock_start_jobs(inp: StartJobsInput) -> list[str]:
        started_calls.append(inp)
        return inp.issues

    @activity.defn(name="available_slots")
    async def mock_slots() -> int:
        return 5  # floor idle → both fit

    @activity.defn(name="tracker_budgets")
    async def mock_budget() -> list[dict]:
        return [_budget_row("ok", "books")]

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[mock_scan_projects, mock_scan_todo, mock_start_jobs, mock_slots,
                                mock_budget])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-{uuid.uuid4()}", task_queue=TQ,
        )
        result = await h.result()
    assert result == {"books": ["101", "102"]}  # both tickets picked up
    assert started_calls[0].sandbox == "fargate"


def _budget_row(state: str, *projects: str, kind: str = "github") -> dict:
    """One row as `tracker_budgets` answers it — the port's answer for one credential, and the
    projects that share it. The numbers matter only when `state` is `low`."""
    return {"kind": kind, "projects": list(projects), "state": state, "vendor": "GitHub",
            "resource": "graphql", "remaining": 12 if state == "low" else 5000, "limit": 5000,
            "reset_epoch": 0, "floor": 200}


# ── a tick in flight at the deploy replays its PRE-SEAM history on this code ────────────────────
#
# `PollWorkflow`'s first command changed when budgets became per vendor (`scan_projects` now
# precedes the budget read, whose activity has a new type). A tick that was mid-flight when the
# worker was replaced replays its recorded history against the new code, and a first command that
# differs is TMPRL1100 — the exact failure `workflow-changes-need-patched` exists for, which no
# test that STARTS a workflow can see, because a fresh start always takes the live arm. So these
# RECORD a history with the pre-seam poller, then REPLAY it through the real `PollWorkflow`.

_PRE_SEAM_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))


@workflow.defn(name="PollWorkflow", sandboxed=False)
class _PreSeamPollWorkflow:
    """The poller as it was before `patched("tracker-budgets")`, command for command: one budget
    read of one vendor (`github_budget`), then the scan. Registered under the real name so the
    history it writes is one the real `PollWorkflow` is asked to replay."""

    @workflow.run
    async def run(self, inp: PollInput) -> dict:
        budget = await workflow.execute_activity(
            "github_budget", start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_PRE_SEAM_RETRY)
        if budget and budget.get("remaining", 200) < 200:
            await workflow.execute_activity(
                "announce_rate_pause",
                RatePauseInput(resource=str(budget.get("resource") or "API"),
                               remaining=int(budget.get("remaining") or 0),
                               reset_epoch=int(budget.get("reset") or 0)),
                start_to_close_timeout=timedelta(minutes=1), retry_policy=_PRE_SEAM_RETRY)
            return {"skipped": "github_rate_low", "budget": budget}
        projects = await workflow.execute_activity(
            "scan_projects", start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_PRE_SEAM_RETRY)
        slots = await workflow.execute_activity(
            "available_slots", start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_PRE_SEAM_RETRY)
        started: dict[str, list[str]] = {}
        for p in projects:
            if slots <= 0:
                break
            issues = await workflow.execute_activity(
                "scan_todo", ScanInput(**p), start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_PRE_SEAM_RETRY)
            if not issues:
                continue
            take = issues[:slots]
            started[p["project"]] = await workflow.execute_activity(
                "start_jobs", StartJobsInput(project=p["project"], issues=take,
                                             sandbox=inp.sandbox),
                start_to_close_timeout=timedelta(minutes=2), retry_policy=_PRE_SEAM_RETRY)
            slots -= len(take)
        return started


@workflow.defn(name="PollWorkflow", sandboxed=False)
class _UngatedPollWorkflow:
    """The live sequence with NO gate — what `PollWorkflow` would be without `patched()`. The
    verifier's twin: a pre-seam history replayed through this must FAIL, or the replay tests
    below would pass on a replayer that cannot see a divergence."""

    @workflow.run
    async def run(self, inp: PollInput) -> dict:
        await workflow.execute_activity(
            "scan_projects", start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_PRE_SEAM_RETRY)
        await workflow.execute_activity(
            "tracker_budgets", start_to_close_timeout=timedelta(minutes=1),
            retry_policy=_PRE_SEAM_RETRY)
        return {}


def _pre_seam_activities(remaining: int):
    """The activities a pre-seam tick called, answering as they did."""
    read: list[str] = []

    @activity.defn(name="github_budget")
    async def github_budget() -> dict:
        return {"resource": "graphql", "remaining": remaining, "limit": 5000, "reset": 0}

    @activity.defn(name="announce_rate_pause")
    async def announce(inp: RatePauseInput) -> bool:
        return True

    @activity.defn(name="scan_projects")
    async def projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="available_slots")
    async def slots() -> int:
        return 5

    @activity.defn(name="scan_todo")
    async def scan(inp: ScanInput) -> list[str]:
        read.append(inp.project)
        return ["101"]

    @activity.defn(name="start_jobs")
    async def start(inp: StartJobsInput) -> list[str]:
        return inp.issues

    return [github_budget, announce, projects, slots, scan, start], read


async def _recorded_pre_seam_tick(env: WorkflowEnvironment, *, remaining: int):
    """Run the pre-seam poller once and hand back `(its history, its result)`."""
    acts, _ = _pre_seam_activities(remaining)
    worker = Worker(env.client, task_queue=TQ, workflows=[_PreSeamPollWorkflow], activities=acts)
    async with worker:
        h = await env.client.start_workflow(
            _PreSeamPollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-pre-seam-{uuid.uuid4()}", task_queue=TQ,
        )
        result = await h.result()
    return await h.fetch_history(), result


@pytest.mark.parametrize("remaining,expected", [
    (5000, {"books": ["101"]}),                       # the scan arm: budget fine, one pickup
    (12, {"skipped": "github_rate_low", "budget": {  # the skip arm: announced, then skipped
        "resource": "graphql", "remaining": 12, "limit": 5000, "reset": 0}}),
])
async def test_a_pre_seam_tick_REPLAYS_on_this_code(env: WorkflowEnvironment, remaining,
                                                     expected):
    """Both arms of the sequence a history written before `tracker-budgets` can carry, replayed
    through the REAL `PollWorkflow` — `patched()` answers False on a history without its marker
    and the pre-seam sequence is what the engine is handed, command for command."""
    from temporalio.worker import Replayer

    from openfactory.runtime.temporal.poller import PollWorkflow

    history, result = await _recorded_pre_seam_tick(env, remaining=remaining)
    assert result == expected, "the recording is not the pre-seam tick it claims to be"
    await Replayer(workflows=[PollWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)


async def test_and_the_replayer_can_SEE_a_diverging_first_command(env: WorkflowEnvironment):
    """Verify the verifier: the same history through the live sequence WITHOUT the gate is a
    non-deterministic replay — so a green replay above is the gate working, not a replayer that
    cannot tell."""
    from temporalio.worker import Replayer

    history, _ = await _recorded_pre_seam_tick(env, remaining=5000)
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[_UngatedPollWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    assert "determinis" in str(caught.value).lower() or "TMPRL1100" in str(caught.value), (
        f"the ungated replay failed for another reason: {caught.value!r}")


async def test_a_tick_started_on_THIS_code_replays_on_this_code(env: WorkflowEnvironment):
    """The live arm's own history, replayed: the marker `patched()` recorded is read back and
    the per-vendor sequence is what the engine is handed."""
    from temporalio.worker import Replayer

    from openfactory.runtime.temporal.poller import PollWorkflow

    @activity.defn(name="scan_projects")
    async def projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="tracker_budgets")
    async def budgets() -> list[dict]:
        return [_budget_row("ok", "books")]

    @activity.defn(name="available_slots")
    async def slots() -> int:
        return 5

    @activity.defn(name="scan_todo")
    async def scan(inp: ScanInput) -> list[str]:
        return ["101"]

    @activity.defn(name="start_jobs")
    async def start(inp: StartJobsInput) -> list[str]:
        return inp.issues

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[projects, budgets, slots, scan, start])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-live-{uuid.uuid4()}", task_queue=TQ,
        )
        assert await h.result() == {"books": ["101"]}
    await Replayer(workflows=[PollWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(
        await h.fetch_history())


async def test_poll_workflow_skips_the_tick_when_every_projects_budget_is_low(
        env: WorkflowEnvironment):
    """Rate-limit resilience: when the budget of every project's tracker is below the ADAPTER's
    floor, the poller skips the tick (no board read, no start) and says so — protecting the
    quota + never crashing the poll on an exhausted limit (the silent TIMED_OUT we hit)."""
    from openfactory.runtime.temporal.poller import PollWorkflow

    read = []

    @activity.defn(name="tracker_budgets")
    async def low_budget() -> list[dict]:
        return [_budget_row("low", "books")]

    @activity.defn(name="scan_projects")
    async def projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="scan_todo")
    async def must_not_read(inp: ScanInput) -> list[str]:
        read.append(inp.project)
        return ["101"]

    # THE PAUSE IS ANNOUNCED NOW (2026-08-14): the skip used to be a log line nobody reads, so
    # the floor went quiet for an hour and the operator learned of it from an unrelated command.
    # Registered here because a workflow that calls an activity the worker does not know about
    # fails at exactly the moment it matters.
    said = []

    @activity.defn(name="announce_rate_pause")
    async def announce(inp: RatePauseInput) -> bool:
        said.append(inp)
        return True

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[low_budget, projects, must_not_read, announce])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-{uuid.uuid4()}", task_queue=TQ,
        )
        result = await h.result()
    assert result.get("skipped") == "budget_low"  # tick skipped, reason surfaced
    assert read == []  # the board was never read
    # …and the announcement names WHOSE budget and WHICH projects, as the adapter said them —
    # and the tracker KIND apart from the display name, which keys the once-per-window marker
    assert said and said[0].vendor == "GitHub" and said[0].projects == ["books"]
    assert said[0].kind == "github"


async def test_a_mixed_deployment_parks_only_the_projects_on_the_EXHAUSTED_vendor(
        env: WorkflowEnvironment):
    """The budget is the CREDENTIAL's, not the deployment's. The tick used to be skipped whole
    on one vendor's number — a Jira board sat unscanned for an hour because GitHub's hourly
    quota was spent (measured 2026-08-24). Each vendor's row parks its own projects; the rest
    are scanned and started as on any other tick."""
    from openfactory.runtime.temporal.poller import PollWorkflow

    read: list[str] = []

    @activity.defn(name="tracker_budgets")
    async def budgets() -> list[dict]:
        return [_budget_row("low", "books"), _budget_row("not_reported", "films", kind="jira")]

    @activity.defn(name="scan_projects")
    async def projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"},
                {"project": "films", "board_owner": "", "board_number": "",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="scan_todo")
    async def scan(inp: ScanInput) -> list[str]:
        read.append(inp.project)
        return ["7"]

    @activity.defn(name="start_jobs")
    async def start(inp: StartJobsInput) -> list[str]:
        return inp.issues

    @activity.defn(name="available_slots")
    async def slots() -> int:
        return 5

    @activity.defn(name="announce_rate_pause")
    async def announce(inp: RatePauseInput) -> bool:
        return True

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[budgets, projects, scan, start, slots, announce])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-{uuid.uuid4()}", task_queue=TQ,
        )
        result = await h.result()
    assert read == ["films"], f"the exhausted vendor's project was read, or the other was not: {read}"
    assert result == {"films": ["7"]}


@pytest.mark.parametrize("slots,expected", [(1, ["101"]), (0, None)])
async def test_poll_workflow_respects_the_floor(env: WorkflowEnvironment, slots, expected):
    """Floor-aware pickup: only `slots` tickets start per tick (in order), so a TO-DO batch is
    picked up one at a time — never all launched at once. slots=0 (a job in flight) → nothing."""
    from openfactory.runtime.temporal.poller import PollWorkflow

    started_calls: list[StartJobsInput] = []

    @activity.defn(name="scan_projects")
    async def mock_scan_projects() -> list[dict]:
        return [{"project": "books", "board_owner": "Org", "board_number": "6",
                 "pickup_status": "TO-DO"}]

    @activity.defn(name="scan_todo")
    async def mock_scan_todo(inp: ScanInput) -> list[str]:
        return ["101", "102", "103"]  # three waiting in TO-DO

    @activity.defn(name="start_jobs")
    async def mock_start_jobs(inp: StartJobsInput) -> list[str]:
        started_calls.append(inp)
        return inp.issues

    @activity.defn(name="available_slots")
    async def mock_slots() -> int:
        return slots

    @activity.defn(name="tracker_budgets")
    async def mock_budget() -> list[dict]:
        return [_budget_row("ok", "books")]

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[mock_scan_projects, mock_scan_todo, mock_start_jobs, mock_slots,
                                mock_budget])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="fargate"),
            id=f"poll-{uuid.uuid4()}", task_queue=TQ,
        )
        result = await h.result()
    if expected is None:
        assert result == {} and started_calls == []  # floor full → started nothing
    else:
        assert result == {"books": expected}  # only `slots` tickets, in board order
        assert started_calls[0].issues == expected  # never passed the whole batch


def test_pause_backoff_grows_and_caps():
    # B (partner-reported re-burn): the resume backoff must GROW with consecutive resumes so a
    # pool-wide usage cap isn't hammered every 30 min, re-launching the agent and re-burning the
    # tokens it's waiting on. 30 → 60 → 90 → 120 …, capped at _PAUSE_BACKOFF_MAX (2h).
    from datetime import timedelta

    from openfactory.runtime.temporal.workflow import _PAUSE_BACKOFF_MAX, JobWorkflow

    assert JobWorkflow._pause_backoff(0) == timedelta(minutes=30)
    assert JobWorkflow._pause_backoff(1) == timedelta(minutes=60)
    assert JobWorkflow._pause_backoff(2) == timedelta(minutes=90)
    assert JobWorkflow._pause_backoff(3) == timedelta(minutes=120)
    # never exceeds the cap, however many resumes pile up
    assert JobWorkflow._pause_backoff(10) == _PAUSE_BACKOFF_MAX
    assert JobWorkflow._pause_backoff(100) == _PAUSE_BACKOFF_MAX
    # retry_at is advisory telemetry only — it does NOT shorten/override the paced backoff
    assert JobWorkflow._pause_backoff(0, retry_at="10:30pm") == timedelta(minutes=30)


def test_the_agent_wall_fires_BEFORE_temporals_ceiling():
    """Two clocks race on a stuck job, and the wrong winner destroys the feature.

    The agent wall stops the run WITH a sentence — it parks, the tech-lead diagnoses it, a human
    decides. Temporal's ceiling stops it with nothing: a cancel, and on fargate a retry that
    restarts the ticket from scratch having explained nothing. They were equal (4h vs 4h) while the
    activity also clones, plans, validates, reviews and pushes, so Temporal won in practice; and
    `repair_ci` sat at 2h with a 4h agent inside it, where Temporal ALWAYS won.
    """
    import re
    from pathlib import Path

    from openfactory.adapters.sandbox.timeouts import (
        ACTIVITY_CEILING,
        AGENT_TIMEOUT,
        LAUNCHER_TIMEOUT,
    )

    # three nested clocks; only the innermost one explains itself, so it must fire first
    assert AGENT_TIMEOUT < LAUNCHER_TIMEOUT < ACTIVITY_CEILING

    # imported HERE, not at module level: the durable engine's workflow sandbox re-imports this
    # module's imports, and `add_ons` resolves a path at import time, which the sandbox forbids
    import add_ons

    launcher_src = add_ons.source("openfactory/runtime/fargate/launcher.py").read_text()
    assert "timeout: int = LAUNCHER_TIMEOUT," in launcher_src, (
        "the launcher restated its deadline instead of deriving it — it drifted to exactly the "
        "agent wall once, and abandoned jobs at the moment they were writing their diagnosis"
    )

    # and no agent-running activity may go back to a hand-written ceiling
    src = Path("openfactory/runtime/temporal/workflow.py").read_text()
    blocks = {}
    for chunk in src.split("execute_activity(")[1:]:
        name = chunk.strip().split(",", 1)[0].strip()
        blocks.setdefault(name, chunk[: chunk.find("retry_policy")])

    for name in ("run_job", "repair_ci"):
        window = blocks[name]
        assert "ACTIVITY_CEILING" in window, (
            f"{name} must derive its ceiling from the agent wall, not restate it"
        )
        assert not re.search(r"start_to_close_timeout=timedelta\(hours=", window), (
            f"{name} has a hand-written ceiling again — it will drift from the wall"
        )


def test_every_merge_wait_says_what_it_is_waiting_on():
    """`awaiting_merge` feeds the panel's "PR ready — waiting for YOUR merge". Its `note` is what
    turns that from a state into an explanation, and one of the four assignments omitted it.

    THE ONE THAT OMITTED IT WAS THE FIRST, which is the worst place for it: between that line and
    `_ci_merge_loop`'s first iteration, the panel showed a wait with nothing saying what the wait
    was on. Brief, and briefly is enough — a full-suite run caught it as an intermittent
    `assert "note" in mw`, which reads as a flake and was a real (if short) gap.

    Asserted structurally rather than by racing the engine again: every dict literal assigned to
    `_merge_wait` must carry all three keys."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "openfactory/runtime/temporal/workflow.py"
    missing: list[str] = []
    for node in ast.walk(ast.parse(src.read_text())):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        targets = {ast.unparse(t) for t in node.targets}
        if "self._merge_wait" not in targets:
            continue
        keys = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        if "note" not in keys:
            missing.append(f"workflow.py:{node.lineno} — keys {sorted(keys)}")
    assert not missing, (
        "a merge wait is surfaced to the panel without saying what it is waiting on:\n  "
        + "\n  ".join(missing)
    )


# ── the answer must not outrun the ear (fx-mono#1 dead letter, 2026-08-04) ──────────────────────

def test_gate_deafness_is_only_declared_never_presumed():
    """`gate_live: False` is the workflow's own confession (patched() memoized off for its
    history). True hears; ABSENT means a binary too old to say — assume the old behavior rather
    than refuse answers a live gate would consume."""
    from openfactory.runtime.temporal.view import gate_cannot_hear

    assert "no answer can reach it" in gate_cannot_hear({"gate_live": False})
    assert gate_cannot_hear({"gate_live": True}) == ""
    assert gate_cannot_hear({}) == ""


async def test_an_answer_to_a_deaf_gate_is_refused_before_the_signal():
    """THE fx-mono#1 failure, at the seam every surface goes through: a deploy replaced the
    gate-holder; the successor replayed pre-patch history and could never consume a gate answer —
    yet the API accepted the adjust, told the operator "sent back for one pass", and the signal
    sat unread until the 14-day deadline. The refusal must come BEFORE the signal: a delivered
    answer is a recorded promise, and this run can keep no promise."""
    from openfactory.runtime.temporal import view as tv

    class _Handle:
        signaled = False

        async def query(self, *a, **k):
            return {"pr_url": "https://x/pr/2", "auto": False,
                    "note": "waiting for CI / the merge", "gate_live": False}

        async def signal(self, *a, **k):
            self.signaled = True

    class _Client:
        def __init__(self, handle):
            self._handle = handle

        def get_workflow_handle(self, *a, **k):
            return self._handle

    h = _Handle()
    with pytest.raises(RuntimeError, match="before the merge gate existed"):
        await tv.answer_merge_gate(_Client(h), "p", "1", answer="adjust",
                                   instruction="fix the rounding", by="me")
    assert h.signaled is False, "the doomed answer was still delivered"


async def test_a_deaf_gate_is_named_deaf_not_already_merged():
    """The catalog's generic wrap says 'not waiting on a merge — it may have merged already',
    which for a deaf gate is the opposite of the truth: the job IS waiting. The distinct type
    must survive to the operator's sentence."""
    from openfactory.actions import catalog

    class _Handle:
        async def query(self, *a, **k):
            return {"pr_url": "https://x/pr/2", "auto": False, "note": "waiting",
                    "gate_live": False}

        async def signal(self, *a, **k):  # pragma: no cover — must never run
            raise AssertionError("signaled a deaf gate")

    class _Client:
        def get_workflow_handle(self, *a, **k):
            return _Handle()

    async def _fake_connected():
        return _Client(), None

    real_connected = catalog._connected
    catalog._connected = _fake_connected
    try:
        class _Proj:
            name = "fx-mono"

        real_project = catalog._project
        catalog._project = lambda p: (_Proj(), None)
        try:
            gate, bad = await catalog._answer_gate(project="fx-mono", issue="1",
                                                   by="me", answer="adjust", instruction="x")
        finally:
            catalog._project = real_project
    finally:
        catalog._connected = real_connected

    assert gate is None
    assert "waiting on a merge it cannot hear" in bad.message
    assert "may have merged already" not in bad.message


async def test_the_pause_names_the_ROW_s_kind_not_the_reference_vendor(env: WorkflowEnvironment):
    """The reviewer's surviving cut (2026-08-26): every `low` row in this file was the reference
    vendor's, so `kind="github"` written as a literal into the announcement — a vendor name in
    core, the exact class the budget seam removes — kept the whole suite green. Two vendors
    exhausted in one reset window would then share one `rate-pause-github-<epoch>.said` marker
    and the second would stay silent. One row of another kind is the whole guard."""
    from openfactory.runtime.temporal.poller import PollWorkflow

    @activity.defn(name="tracker_budgets")
    async def low_budget() -> list[dict]:
        return [{**_budget_row("low", "films", kind="jira"), "vendor": "Jira"}]

    @activity.defn(name="scan_projects")
    async def projects() -> list[dict]:
        return [{"project": "films", "pickup_status": "TO-DO"}]

    @activity.defn(name="scan_todo")
    async def must_not_read(inp: ScanInput) -> list[str]:
        raise AssertionError("the board was read on a paused vendor")

    said = []

    @activity.defn(name="announce_rate_pause")
    async def announce(inp: RatePauseInput) -> bool:
        said.append(inp)
        return True

    worker = Worker(env.client, task_queue=TQ, workflows=[PollWorkflow],
                    activities=[low_budget, projects, must_not_read, announce])
    async with worker:
        h = await env.client.start_workflow(
            PollWorkflow.run, PollInput(sandbox="container"),
            id=f"poll-{uuid.uuid4()}", task_queue=TQ,
        )
        await h.result()
    assert said and said[0].kind == "jira", (
        "the announcement carries a kind that is not the row's — a literal in core")
    assert said[0].vendor == "Jira"

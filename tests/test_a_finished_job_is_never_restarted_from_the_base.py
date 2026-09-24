"""#302 — a ticket whose pull request is open is never run again, and its branch is never rebuilt.

THE SEQUENCE, AS IT WAS FILED (`v0.3.0-8-g0f8314c`, `sandbox: worktree`, `merge_policy: human`):

    09:53:59  validating: every gate PASS → reviewing
    09:56:11  an activity times out; the workflow parks: kind=self_healing
    10:02:08  review: approved_with_findings (score 85)    ← the attempt CONTINUES and completes
    10:02:14  pr: opened · state: pr_open                   ← the work is done and delivered
    10:11:11  the self-heal timer elapses → default "resume"
              spec_validation → preparing → implementing   ← a second full agent pass

…after which `git reflog openfactory/<n>` held one line, `branch: Created from <base>`: the finished
attempt's commit was gone from the job branch, and nobody had pressed anything.

DRIVEN ON THE REAL THINGS. The real `JobWorkflow` on a time-skipping engine, and a `run_job` that
runs the real `JobRunner` the way the activity does — a fresh runner per call, the worktree box on
a real repository, the shipped local forge keeping the pull request in its own database. The one
thing staged is the timeout: the first attempt finishes and the engine is told it timed out, which
is what the engine was told on the deployment. The merge watch's reads are doubles; this file stops
at the gate they open.

TWO FIXES, EACH WITH ITS PROOF:

  the runner    whether the ticket is already delivered is READ from the forge — an open pull
                request from its branch — and never inferred from `resume_handle`, which the
                workflow cannot hold for an attempt whose result it lost;
  the workflow  the self-heal carries the parked attempt's handle, as the other two resuming
                parks already did, so a hold that pushed its partial work is continued rather than
                rebuilt from the base.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.client import WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory import namespace
from openfactory.adapters.forge.local import LocalForge
from openfactory.adapters.sandbox import WorktreeSandbox
from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    Finding,
    JobState,
    Manifest,
    ReviewResult,
    RunResult,
    Ticket,
)
from openfactory.contracts.checks import CiDecision
from openfactory.observability import InMemoryEventSink
from openfactory.orchestrator import JobRunner
from openfactory.runtime.temporal.io import HoldSyncInput, JobParams, MergeCheckInput, RunJobInput
from openfactory.runtime.temporal.workflow import JobWorkflow
from tests.test_walking_skeleton import FakeTracker

TQ = "test-a-finished-job-is-never-restarted"

#: THE FILE STARTS ITS OWN ENGINE for the tests marked with this, and throws it away — the
#: declared exception to the suite's no-live-engine rule (`conftest.OWNS_ITS_ENGINE`).
engine = pytest.mark.owns_its_engine

TICKET = Ticket(id="#7", title="add the export", objective="export the orders as CSV",
                repo="shop", acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
BRANCH = namespace.job_branch(TICKET.id)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True).returncode == 0


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A person's repository, and the forge: on the local row they are the same directory."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t.dev")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("# shop\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


class _Agent:
    """Writes the ticket's file, a different line on every pass, so two passes leave two commits.

    It also says what each pass FOUND in its checkout, which is how the resume proof tells work
    continued from work rebuilt. `stop_first` makes the first pass stop part-way, the way a harness
    whose connection dropped does, leaving what it had written."""

    def __init__(self, stop_first: str = "") -> None:
        self.stop_first = stop_first
        self.passes: list[dict] = []

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        path = workspace.path / "feature.py"
        found = path.read_text() if path.exists() else ""
        self.passes.append({"found": found, "handle": context.resume_handle})
        n = len(self.passes)
        if n == 1 and self.stop_first:
            path.write_text("PARTIAL = 1\n")
            return AgentRunResult(ok=False, summary=self.stop_first, cost_usd=0.01)
        path.write_text(f"{found}VALUE = {n}\n")
        return AgentRunResult(ok=True, summary=f"pass {n}", cost_usd=0.01,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


class _Reviewer:
    """85 and then 80, as on the deployment — two readings of two different commits."""

    def __init__(self) -> None:
        self.scores = [85, 80]

    def review(self, *, sandbox, workspace, review_input) -> ReviewResult:
        score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
        return ReviewResult(decision="approved_with_findings", score=score,
                            findings=[Finding(severity="low", description="a nit")],
                            summary="does what the card asks")


class _Job:
    """Everything one ticket's runs share: the repository, the forge's database, the journal, and
    the agent and reviewer whose passes are counted. A RUNNER is built per run, as the activity
    builds one per call — nothing an attempt remembers in memory reaches the next."""

    def __init__(self, repo: Path, tmp_path: Path, *, agent: _Agent | None = None,
                 manifest: Manifest | None = None, forge=None) -> None:
        self.repo, self.tmp = repo, tmp_path
        self.forge = forge or LocalForge("shop", str(repo), db_path=tmp_path / "board.db")
        self.tracker = FakeTracker(TICKET)
        self.agent = agent or _Agent()
        self.reviewer = _Reviewer()
        self.journal = InMemoryEventSink()
        self.manifest = manifest or Manifest(validate={"test": "true", "security": "true"})
        self.runs: list[RunJobInput] = []
        #: where the job branch pointed when the first attempt ended, however it ended
        self.first_head = ""

    def runner(self) -> JobRunner:
        return JobRunner(tracker=self.tracker, forge=self.forge, agent=self.agent,
                         sandbox=WorktreeSandbox(root=self.tmp / "wt"), manifest=self.manifest,
                         repo_path=self.repo, reviewer=self.reviewer, events=self.journal)

    def run(self, handle: str | None = None) -> RunResult:
        return self.runner().run(TICKET.id, resume_handle=handle)

    def head(self) -> str:
        return _git(self.repo, "rev-parse", BRANCH)


# ═══ the runner: what any way back in reads first ════════════════════════════════════════════════

def test_a_ticket_whose_pull_request_is_open_runs_no_agent_and_leaves_its_branch(repo, tmp_path):
    """THE ROOT, WITHOUT AN ENGINE. The second run is what every way back in does — a self-heal, an
    operator's resume, a card moved back to the queue — and it carries no handle, exactly as the
    self-heal's did. It must hand the open pull request back to the merge, not do the ticket again
    over a rebuilt branch."""
    job = _Job(repo, tmp_path)
    first = job.run()
    assert first.state is JobState.PR_OPEN and first.pr_url, first.note
    delivered = job.head()
    walked = len(job.tracker.states)

    again = job.run()

    assert len(job.agent.passes) == 1, (
        f"{len(job.agent.passes)} agent passes on a ticket whose pull request was already open — "
        f"the work was done again, at full price")
    assert job.head() == delivered, (
        "the job branch no longer points at the delivered commit: it was rebuilt from the base "
        "under an open pull request")
    assert again.state is JobState.PR_OPEN and again.pr_url == first.pr_url, again
    assert again.branch == BRANCH
    said = [e.message for e in job.journal.events if e.kind == "note"]
    assert any(first.pr_url in m and "already open" in m for m in said), (
        f"nothing in the journal says why this run did nothing: {said}")
    assert job.tracker.states[walked:] == [JobState.PR_OPEN], (
        f"the card was walked through the job again: {job.tracker.states[walked:]}")


@pytest.mark.parametrize("which", ["the lookup answers None", "the state read raises"])
def test_a_forge_that_cannot_be_read_holds_the_run_and_touches_nothing(repo, tmp_path, which):
    """COULD NOT LOOK IS NOT "THERE IS NONE". Going on would be this defect again, through the one
    door left: a rebuilt branch under a pull request that may well be open. Both of the port's
    ways of saying it: `pr_for_head` answers None, and `pr_status` raises rather than guess."""
    job = _Job(repo, tmp_path)
    job.run()
    delivered = job.head()

    class _CannotSay:
        """The shipped row, except that one of the two reads this fix makes fails."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def pr_for_head(self, head, *, repo=""):
            return None if which == "the lookup answers None" else self._inner.pr_for_head(head)

        def pr_status(self, *, pr, repo=""):
            raise RuntimeError("the forge answered 503")

    job.forge = _CannotSay(job.forge)
    held = job.run()

    assert held.state is JobState.ON_HOLD, held
    assert "could not read" in held.note and BRANCH in held.note, held.note
    assert len(job.agent.passes) == 1, "an agent ran on a read that failed"
    assert job.head() == delivered, "the branch was rebuilt on a read that failed"


@pytest.mark.parametrize("ended", ["closed", "merged"])
def test_a_pull_request_that_ended_is_not_gone_back_to(repo, tmp_path, ended):
    """OPEN IS DELIVERED, AND NOTHING ELSE IS. A closed pull request is a person's discard and a
    merged one's work is in the base; a card that comes back after either is somebody asking for
    work, and a run that answered with the old pull request would refuse it without a word."""
    job = _Job(repo, tmp_path)
    first = job.run()
    if ended == "closed":
        job.forge.close_pr(pr=first.pr_url, reason="not this way")
    else:
        job.forge.merge_pr(pr=first.pr_url)

    again = job.run()

    assert len(job.agent.passes) == 2, f"a {ended} pull request was taken for delivered work"
    assert again.state is JobState.PR_OPEN and again.pr_url != first.pr_url, again


# ═══ the workflow: the sequence as it was filed ═══════════════════════════════════════════════════

@activity.defn(name="check_pr_status")
async def _still_open(inp: MergeCheckInput) -> str:
    return "open"


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
    """Checks pending — the watch waits, so the gate stays open for the test to read."""
    return "blocked"


@activity.defn(name="read_ci_checks")
async def _pending(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="pending")


@activity.defn(name="notify_coordinator_say")
async def _say(inp) -> None:
    return None


@activity.defn(name="notify_coordinator")
async def _advise(inp) -> None:
    return None


@activity.defn(name="fetch_ticket_title")
async def _title(inp) -> str:
    return TICKET.title


@activity.defn(name="mark_needs_action")
async def _mark(inp: HoldSyncInput) -> str:
    return "somebody"


@activity.defn(name="diagnose_impediment")
async def _diagnose(inp: HoldSyncInput) -> bool:
    return False


_WATCH = [_still_open, _blocked, _pending, _say, _advise, _title, _mark, _diagnose]


def _run_job(job: _Job, *, lose_the_first: bool):
    """`run_job` as the activity runs it, with the first attempt's ending lost when asked.

    LOST AFTER IT LANDED, which is the whole of #302: the attempt finishes — review, pull request,
    `pr_open` — and what reaches the engine is a timeout, in the words the engine used."""

    @activity.defn(name="run_job")
    async def run_job(inp: RunJobInput) -> RunResult:
        job.runs.append(inp)
        runner = job.runner()
        result = await asyncio.to_thread(
            runner.run, inp.issue, resume_handle=inp.resume_handle, spent_turns=inp.spent_turns,
            decision=inp.decision)
        if len(job.runs) == 1:
            job.first_head = job.head()
            if lose_the_first:
                raise ApplicationError("Activity task timed out", non_retryable=True)
        return result

    return run_job


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _at_the_gate(h: WorkflowHandle, env: WorkflowEnvironment) -> tuple[dict, list[str]]:
    """Walk the job to its merge gate; return the gate and the parks it passed through.

    REAL TIME WHILE ANYTHING RUNS, SKIPPED TIME ONLY WHILE IT NAPS. The attempts are real git work
    that takes real seconds, under a two-minute heartbeat timeout; skipping minutes of engine time
    over one would time it out for real. So the clock is moved only across a self-heal's nap, and
    only as far as the moment it wakes."""
    parks: list[str] = []
    for _ in range(3000):
        gate = await h.query(JobWorkflow.awaiting_merge)
        if gate and gate.get("gate_live"):
            return gate, parks
        parked = await h.query(JobWorkflow.awaiting_action) or {}
        kind = parked.get("kind")
        if kind and (not parks or parks[-1] != kind):
            parks.append(kind)
        if kind == "impediment":
            raise AssertionError(f"the job parked for a person instead: {parked.get('note')}")
        if kind == "self_healing" and parked.get("wakes_at"):
            wakes = datetime.fromisoformat(parked["wakes_at"])
            now = await env.get_current_time()
            await env.sleep(max(wakes - now, timedelta(0)) + timedelta(seconds=2))
        else:
            await asyncio.sleep(0.05)
    raise AssertionError(f"the job never reached its merge gate — it went through {parks}")


async def _drive(env: WorkflowEnvironment, job: _Job, *, lose_the_first: bool):
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[_run_job(job, lose_the_first=lose_the_first), *_WATCH]):
        h = await env.client.start_workflow(
            JobWorkflow.run,
            JobParams(project="shop", issue=TICKET.id, sandbox="worktree", promote=False,
                      merge_deadline_days=3650),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        try:
            return await _at_the_gate(h, env)
        finally:
            await h.terminate()


@engine
async def test_the_self_heal_after_a_delivered_attempt_goes_back_to_the_merge(env, repo,
                                                                              tmp_path):
    """THE SEQUENCE AS FILED: one attempt, delivered, its ending lost to a timeout; the self-heal
    wakes and resumes by default. What must come of that is the merge of the pull request that is
    already open — not a second agent pass, and not a branch rebuilt from the base."""
    job = _Job(repo, tmp_path)

    gate, parks = await _drive(env, job, lose_the_first=True)

    assert parks[:1] == ["self_healing"], f"the timeout did not self-heal: {parks}"
    assert len(job.runs) == 2, f"the self-heal did not resume at all: {len(job.runs)} run(s)"
    assert len(job.agent.passes) == 1, (
        f"{len(job.agent.passes)} agent passes: the self-heal re-ran a ticket whose pull request "
        f"was already open")
    assert job.head() == job.first_head, (
        f"`{BRANCH}` was rebuilt: it points at {job.head()[:10]} and the delivered attempt's "
        f"commit is {job.first_head[:10]}")
    opened = job.forge.pr_for_head(BRANCH)
    assert gate.get("pr_url") == opened and gate.get("auto") is False, (
        f"the gate is not the delivered pull request's, waiting for a person: {gate}")


@engine
async def test_a_self_heal_continues_a_hold_that_kept_its_work(env, repo, tmp_path):
    """THE HANDLE TRAVELS. A pass that stopped part-way on a dropped connection pushes what it had
    written and parks WITH a handle; the classifier calls a reset connection transient, so the
    self-heal takes it. The resume must continue that work — the other two resuming parks always
    carried the handle, and this one dropped it, so the runner rebuilt the branch it was on."""
    job = _Job(repo, tmp_path, agent=_Agent(stop_first="connection reset by peer"),
               manifest=Manifest(validate={"test": "true", "security": "true"},
                                 recovery_max_attempts=0))

    gate, parks = await _drive(env, job, lose_the_first=False)

    assert parks[:1] == ["self_healing"], f"the stop did not self-heal: {parks}"
    assert len(job.runs) == 2
    assert job.runs[1].resume_handle, (
        "the self-heal resumed with no handle, so the second pass started over from the base")
    assert job.agent.passes[1]["found"] == "PARTIAL = 1\n", (
        f"the second pass did not find the first one's work: {job.agent.passes[1]}")
    assert job.first_head and _is_ancestor(repo, job.first_head, BRANCH), (
        "the commit the first pass pushed is not under the branch any more")
    assert gate.get("pr_url") == job.forge.pr_for_head(BRANCH)

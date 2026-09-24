"""#304 — the pull request says what the LAST attempt did, on every forge row.

A job ran a second attempt on the same head — after a self-heal resume, an operator's resume, any
re-entry into the attempt loop. The second attempt ran the gates again, took a new review and
"opened" the pull request again. The pull request kept the FIRST attempt's body:

    10:02:08  review  approved_with_findings (score 85)   findings: 5
    10:02:14  pr      opened .../pr/2
    10:18:29  review  approved_with_findings (score 80)   findings: 5
    10:18:30  pr      opened .../pr/2

    $ curl -s '/api/board/<project>?pr=2' | jq -r '.pr.body' | grep -o 'score [0-9]*'
    score 85

The commit merged was the second attempt's; the review a person read to approve that merge was the
first attempt's, about a commit that was no longer the head. Under `merge_policy: human` the body IS
the merge interface. `base_sha` was written once too, at the first open, and never again.

THE CAUSE IS ONE BRANCH IN EACH ROW. `open_pr` answers the pull request already open from `head`
— rightly, so a retried activity does not file a second one (D-16) — and every row returned it
without looking at what it had been handed. A retry hands the same text; a later attempt hands a
description of a different commit, and it was dropped the same way.

WHAT IS HELD HERE:

  the rows       GitHub, Azure Repos and the local forge each bring the open pull request up to
                 date with the title and body they were handed — the local row with the base it
                 was opened against and the change's identity too — and a refused update is said
                 by name, never raised and never silent;
  the sequence   on the real `JobWorkflow` over the real `JobRunner`, worktree box and local forge:
                 whichever attempt's commit is the head, the pull request's body is THAT attempt's
                 review, gates and cost, and its `base_sha` is the base that head was cut from.
"""

from __future__ import annotations

import asyncio
import logging
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
from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.local import LocalForge
from openfactory.adapters.sandbox import WorktreeSandbox
from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    Finding,
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
from tests.test_the_forge_opens_a_pr_in_another_repository import _Run, ado_forge, gh_forge
from tests.test_walking_skeleton import FakeTracker

TQ = "test-the-pull-request-says-what-the-last-attempt-did"

#: THE FILE STARTS ITS OWN ENGINE for the test marked with this, and throws it away — the declared
#: exception to the suite's no-live-engine rule (`conftest.OWNS_ITS_ENGINE`).
engine = pytest.mark.owns_its_engine

TICKET = Ticket(id="#7", title="add the export", objective="export the orders as CSV",
                repo="shop", acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
BRANCH = namespace.job_branch(TICKET.id)

#: What each attempt's review says, so a body can be read back for which attempt it describes.
#: The scores are the deployment's own; the findings differ, as they did there.
READINGS = {1: (85, "the export names its columns in English"),
            2: (80, "the export drops the header row")}
#: What each attempt's agent pass costs — the `Cost:` line is the third thing a body carries.
COSTS = {1: 0.01, 2: 0.03}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


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


def _somebody_lands(repo: Path, name: str) -> str:
    """A person's commit on `main`, the way a merge of somebody else's work arrives."""
    (repo / name).write_text("theirs\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"somebody else's {name}")
    return _git(repo, "rev-parse", "main")


def _attempt_on(repo: Path, text: str) -> None:
    """An attempt's commit on the job branch, cut from `main` as it stands — the way the box cuts
    one — leaving the person's checkout on `main`."""
    _git(repo, "checkout", "-q", "-B", BRANCH, "main")
    (repo / "feature.py").write_text(text)
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-q", "-m", "the attempt")
    _git(repo, "checkout", "-q", "main")


# ═══ the rows ═════════════════════════════════════════════════════════════════════════════════════

def test_the_local_row_brings_the_open_pull_request_up_to_date(repo, tmp_path):
    """The row the filed report was measured on. Title, body, `base_sha` and `patch_id` are all
    what the SECOND open was handed and found — one row per head, describing the head it has."""
    forge = LocalForge("shop", str(repo), db_path=tmp_path / "board.db")
    _attempt_on(repo, "VALUE = 1\n")
    first = forge.open_pr(head=BRANCH, base="main", title="add the export", body="score 85")

    moved = _somebody_lands(repo, "theirs.txt")
    _attempt_on(repo, "VALUE = 2\n")
    again = forge.open_pr(head=BRANCH, base="main", title="add the export (2)", body="score 80")

    assert again == first, "a second pull request was filed for one head"
    row = forge._row(first)  # noqa: SLF001 — the row is what the page and the API read
    assert (row["title"], row["body"]) == ("add the export (2)", "score 80"), (
        f"the pull request still says what the first attempt did: {row['body']!r}")
    assert row["base_sha"] == moved, "the row records the base the FIRST attempt was opened on"
    assert row["patch_id"] == forge._patch_id("main", BRANCH, str(repo))  # noqa: SLF001


def test_the_local_row_a_retry_changes_nothing(repo, tmp_path):
    """D-16 still holds: a retried activity hands the same text and gets the same pull request,
    with nothing in it moved."""
    forge = LocalForge("shop", str(repo), db_path=tmp_path / "board.db")
    _attempt_on(repo, "VALUE = 1\n")
    first = forge.open_pr(head=BRANCH, base="main", title="t", body="b")
    before = forge._row(first)  # noqa: SLF001

    assert forge.open_pr(head=BRANCH, base="main", title="t", body="b") == first
    after = forge._row(first)  # noqa: SLF001
    moved = {k for k in before if before[k] != after[k]}
    assert moved <= {"updated_at"}, f"a retry rewrote {sorted(moved)}"


def test_github_brings_the_open_pull_request_up_to_date():
    """One `gh pr edit`, in the repository the pull request was looked up in, with both fields."""
    docs = "AcmeCorp/acme-books-documentation"
    f = gh_forge({"pr list": _Run(stdout=f"https://github.com/{docs}/pull/2\n"),
                  "pr edit": _Run(stdout=f"https://github.com/{docs}/pull/2\n")})

    url = f.open_pr(head=BRANCH, base="main", title="add the export (2)", body="score 80",
                    repo=docs)

    assert url == f"https://github.com/{docs}/pull/2"
    edits = [a for a in f._gh.calls if a[:2] == ["pr", "edit"]]  # noqa: SLF001
    assert len(edits) == 1, (
        "the open pull request was answered and left as the first attempt had it")
    argv = edits[0]
    assert argv[2] == url and argv[argv.index("--repo") + 1] == docs
    assert argv[argv.index("--title") + 1] == "add the export (2)"
    assert argv[argv.index("--body") + 1] == "score 80"
    assert not any(a[:2] == ["pr", "create"] for a in f._gh.calls)  # noqa: SLF001


def test_github_a_refused_update_is_said_and_the_pull_request_still_answers(caplog):
    f = gh_forge({"pr list": _Run(stdout="https://github.com/o/r/pull/2\n"),
                  "pr edit": _Run(returncode=1, stderr="HTTP 403: Resource not accessible")})

    with caplog.at_level(logging.WARNING):
        url = f.open_pr(head=BRANCH, base="main", title="t", body="score 80")

    assert url == "https://github.com/o/r/pull/2", "a refused description edit cost the job its PR"
    assert "OPENFACTORY_PR_BODY_REFUSED" in caplog.text, "the pull request went stale in silence"


_ADO_ACTIVE = {"value": [{"pullRequestId": 5, "status": "active",
                          "repository": {"name": "fx-ado", "project": {"name": "factory"}}}]}


def test_azure_brings_the_open_pull_request_up_to_date():
    """One PATCH on the pull request the lookup found, carrying the title and the description —
    the description cut to the vendor's ceiling, as on the create, or the update is a 400."""
    f = ado_forge({"GET git/repositories/fx-ado/pullrequests": _ADO_ACTIVE,
                   "PATCH git/repositories/fx-ado/pullrequests/5": {"pullRequestId": 5}})
    long_body = "score 80\n" + "x" * 5000

    url = f.open_pr(head=BRANCH, base="main", title="add the export (2)", body=long_body)

    assert url == "https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/5"
    assert f._fake.paths("PATCH") == ["git/repositories/fx-ado/pullrequests/5"], (  # noqa: SLF001
        "the open pull request was answered and left as the first attempt had it")
    sent = f._fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/5")  # noqa: SLF001
    assert sent["title"] == "add the export (2)"
    assert sent["description"].startswith("score 80") and len(sent["description"]) <= 4000
    assert f._fake.paths("POST") == []  # noqa: SLF001


def test_azure_a_refused_update_is_said_and_the_pull_request_still_answers(caplog):
    def refuse(_params):
        raise AzureDevOpsError("PATCH … → 403 TF401027: You need the Git 'PullRequestContribute'")

    f = ado_forge({"GET git/repositories/fx-ado/pullrequests": _ADO_ACTIVE,
                   "PATCH git/repositories/fx-ado/pullrequests/5": refuse})

    with caplog.at_level(logging.WARNING):
        url = f.open_pr(head=BRANCH, base="main", title="t", body="score 80")

    assert url.endswith("/pullrequest/5"), "a refused description edit cost the job its PR"
    assert "OPENFACTORY_PR_BODY_REFUSED" in caplog.text, "the pull request went stale in silence"


# ═══ the sequence, on the real job ════════════════════════════════════════════════════════════════

class _Agent:
    """Writes the ticket's file, a different line on every pass, and costs what `COSTS` says."""

    def __init__(self) -> None:
        self.passes = 0

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.passes += 1
        (workspace.path / "feature.py").write_text(f"VALUE = {self.passes}\n")
        return AgentRunResult(ok=True, summary=f"pass {self.passes}",
                              cost_usd=COSTS[min(self.passes, 2)], actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True)


class _Reviewer:
    """Reads the attempt in hand: the verdict it gives names WHICH attempt's commit it read."""

    def review(self, *, sandbox, workspace, review_input) -> ReviewResult:
        n = int((workspace.path / "feature.py").read_text().split("=")[-1])
        score, finding = READINGS[n]
        return ReviewResult(decision="approved_with_findings", score=score,
                            findings=[Finding(severity="low", description=finding)],
                            summary="does what the card asks")


class _Job:
    def __init__(self, repo: Path, tmp_path: Path) -> None:
        self.repo, self.tmp = repo, tmp_path
        self.forge = LocalForge("shop", str(repo), db_path=tmp_path / "board.db")
        self.tracker = FakeTracker(TICKET)
        self.agent, self.reviewer = _Agent(), _Reviewer()
        self.journal = InMemoryEventSink()
        self.runs: list[RunJobInput] = []

    def runner(self) -> JobRunner:
        return JobRunner(tracker=self.tracker, forge=self.forge, agent=self.agent,
                         sandbox=WorktreeSandbox(root=self.tmp / "wt"),
                         manifest=Manifest(validate={"test": "true", "security": "true"}),
                         repo_path=self.repo, reviewer=self.reviewer, events=self.journal)


@activity.defn(name="check_pr_status")
async def _still_open(inp: MergeCheckInput) -> str:
    return "open"


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
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


def _run_job(job: _Job):
    """`run_job` as the activity runs it — a fresh runner per call — with the first attempt's
    ending lost to a timeout after it landed, and somebody's commit reaching `main` meanwhile."""

    @activity.defn(name="run_job")
    async def run_job(inp: RunJobInput) -> RunResult:
        job.runs.append(inp)
        result = await asyncio.to_thread(
            job.runner().run, inp.issue, resume_handle=inp.resume_handle,
            spent_turns=inp.spent_turns, decision=inp.decision)
        if len(job.runs) == 1:
            _somebody_lands(job.repo, "theirs.txt")
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


async def _at_the_gate(h: WorkflowHandle, env: WorkflowEnvironment) -> dict:
    """Walk the job to its merge gate. Real time while an attempt runs — it is real git work under
    a two-minute heartbeat timeout — and skipped time only across a self-heal's nap."""
    for _ in range(3000):
        gate = await h.query(JobWorkflow.awaiting_merge)
        if gate and gate.get("gate_live"):
            return gate
        parked = await h.query(JobWorkflow.awaiting_action) or {}
        if parked.get("kind") == "impediment":
            raise AssertionError(f"the job parked for a person instead: {parked.get('note')}")
        if parked.get("kind") == "self_healing" and parked.get("wakes_at"):
            wakes = datetime.fromisoformat(parked["wakes_at"])
            now = await env.get_current_time()
            await env.sleep(max(wakes - now, timedelta(0)) + timedelta(seconds=2))
        else:
            await asyncio.sleep(0.05)
    raise AssertionError("the job never reached its merge gate")


@engine
async def test_the_pull_request_describes_the_attempt_whose_commit_is_its_head(env, repo,
                                                                               tmp_path):
    """THE SEQUENCE AS FILED, AND THE INVARIANT IT BROKE. Whatever the job does after the lost
    ending — a second attempt, or going back to the pull request that is already open — the body a
    person approves the merge on is the reading of the commit that merges, and the row's base is
    the base that commit was cut from. Asked of the HEAD, so the proof does not depend on which of
    the two the job chose: on the defect the head was the second attempt's and the body the
    first's."""
    job = _Job(repo, tmp_path)
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[_run_job(job), *_WATCH]):
        h = await env.client.start_workflow(
            JobWorkflow.run,
            JobParams(project="shop", issue=TICKET.id, sandbox="worktree", promote=False,
                      merge_deadline_days=3650),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ)
        try:
            gate = await _at_the_gate(h, env)
        finally:
            await h.terminate()

    row = job.forge._row(gate["pr_url"])  # noqa: SLF001 — what the page and the API read
    assert row and row["head"] == BRANCH and row["state"] == "open", row
    n = int(_git(repo, "show", f"{BRANCH}:feature.py").split("=")[-1])
    score, finding = READINGS[n]
    other_score, other_finding = READINGS[3 - n]
    body = row["body"]
    assert f"## Review — approved_with_findings (score {score})" in body and finding in body, (
        f"the head is attempt {n}'s commit and the pull request does not carry its review:\n{body}")
    assert f"(score {other_score})" not in body and other_finding not in body, (
        f"the pull request still carries the review of attempt {3 - n}, about a commit that is "
        f"not its head:\n{body}")
    assert f"Cost: ${COSTS[n]:.4f}" in body, f"the cost is not attempt {n}'s:\n{body}"
    assert row["base_sha"] == _git(repo, "merge-base", "main", BRANCH), (
        "the row records a base the head was not cut from")

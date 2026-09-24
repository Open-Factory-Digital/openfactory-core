"""A card is closed when its pull request MERGES — never when a merge was only asked for (#180).

Since #195 the tracker row closes a delivered card at Done, wherever it lives: the GitHub row
closes the issue as completed, so a card routed from `acme/issues` and delivered through a pull
request in `acme/api` is no longer left open. That made Done a CLOSE, and it put a question on
every path that writes Done: did the pull request actually merge?

On one path it had not. At the human merge gate — `merge_policy: human`, the default — the person
answers *merge*, the workflow calls `merge_pr`, and a call that did not raise was taken as the
merge. But the port says in so many words that TRIGGERING IS NOT MERGING: GitHub's `merge_pr` arms
`--auto`, which merges once the required checks pass, and Azure DevOps's arms auto-complete, which
completes asynchronously. So the job ended MERGED, settled the card as Done, and the tracker
closed it — while the pull request was still open, waiting on checks that could still fail. A
card whose work never merged was closed as delivered. The machine's self-merge took the same word
for the deed after `force_merge`.

What is held here, on the real `JobWorkflow` over a time-skipping engine, with the REAL merge and
status activities driving each shipped forge row over a recorded transport:

  * a merge a person asked for is Done only once the forge reads the pull request merged;
  * one that never lands — the pull request is closed instead — is never Done;
  * the same for the machine's self-merge;

and, on the tracker row, that Done does not duplicate what the forge's closing word already did:
on the owned pairing `Closes #12` closed the issue at the merge, and the row writes nothing more.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.adapters.tracker.github import GitHubIssuesTracker
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.runtime.temporal import activities
from openfactory.runtime.temporal.io import HoldSyncInput, JobParams, MergeCheckInput, RunJobInput
from openfactory.runtime.temporal.workflow import JobWorkflow
from tests.test_a_delivered_card_is_closed_by_its_tracker import FakeGH

TQ = "test-closed-only-when-merged"

#: THIS FILE STARTS ITS OWN ENGINE and throws it away — the declared exception to the suite's
#: no-live-engine rule (`conftest.OWNS_ITS_ENGINE`).
pytestmark = pytest.mark.owns_its_engine


# ── the shipped forge rows, over a recorded transport ───────────────────────────────────────────

class _GitHubPR:
    """`gh` for one pull request. `pr merge` is accepted — with `--auto` that ARMS the merge, and
    GitHub merges it once the required checks pass — and `pr view` says what the pull request is
    until the test lands it or closes it."""

    url = "https://github.com/acme/api/pull/7"

    def __init__(self) -> None:
        self.state = "OPEN"
        self.merges: list[list[str]] = []

    def __call__(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        if args[:2] == ["pr", "merge"]:
            self.merges.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ["pr", "view"]:
            merged = "2026-09-24T10:00:00Z" if self.state == "MERGED" else None
            return subprocess.CompletedProcess(
                args, 0, stdout=json.dumps({"state": self.state, "mergedAt": merged}), stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr=f"not recorded: {args}")

    def row(self):
        from openfactory.adapters.forge.github import GitHubForge

        forge = GitHubForge("acme/api", token="t")
        forge._gh = self
        return forge

    def land(self) -> None:
        self.state = "MERGED"

    def abandon(self) -> None:
        self.state = "CLOSED"


class _AzurePR:
    """Azure DevOps for one pull request. Arming auto-complete (or completing directly) is
    answered at once, and the pull request completes later — the row's own `merge_pr` says it was
    measured completing six seconds after the arming — or is abandoned."""

    url = "https://dev.azure.com/acme/Shop/_git/shop-api/pullrequest/7"

    def __init__(self) -> None:
        self.status = "active"
        self.merges: list[dict] = []

    def call(self, method: str, path: str, body: dict | None = None, **_kw) -> dict:
        if method == "GET" and path == "connectionData":
            return {"authenticatedUser": {"id": "the-factory"}}
        if method == "GET" and path == "git/pullrequests/7":
            return {"pullRequestId": 7, "status": self.status,
                    "repository": {"name": "shop-api"},
                    "lastMergeSourceCommit": {"commitId": "c0ffee"}}
        if method == "PATCH" and path == "git/repositories/shop-api/pullrequests/7":
            self.merges.append(dict(body or {}))
            return {}
        raise AssertionError(f"not recorded: {method} {path}")

    def row(self):
        from openfactory.adapters.forge.azure_devops import AzureReposForge

        forge = AzureReposForge("shop-api", organization="acme", project="Shop", token="t")
        forge._client = lambda: self
        return forge

    def land(self) -> None:
        self.status = "completed"

    def abandon(self) -> None:
        self.status = "abandoned"


_ROWS = {"GitHub": _GitHubPR, "Azure DevOps": _AzurePR}


# ── the workflow's other activities ─────────────────────────────────────────────────────────────

#: what `run_job` hands the watch — the row's pull request, and which path merges it
_OPENED: dict = {}
#: every `settle_ticket` the workflow made — the call that writes Done, and so closes the card
_SETTLED: list[HoldSyncInput] = []
_MSTATE = ["blocked"]


@activity.defn(name="run_job")
async def mock_run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=_OPENED["url"],
                     branch="openfactory/87", auto_merge=_OPENED["auto"])


@activity.defn(name="read_ci_checks")
async def mock_ci(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="success")


@activity.defn(name="pr_mergeable_state")
async def mock_mstate(inp: MergeCheckInput) -> str:
    return _MSTATE[0]


@activity.defn(name="merge_pr_now")
async def mock_merge_now(inp: MergeCheckInput) -> bool:
    """Registered for the pre-patch path only, like its siblings in the other gate tests."""
    return True


@activity.defn(name="settle_ticket")
async def mock_settle(inp: HoldSyncInput) -> str:
    _SETTLED.append(inp)
    return inp.state


@activity.defn(name="record_outcome")
async def mock_journal(inp: HoldSyncInput) -> str:
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


#: THE REAL ONES: what the forge row is asked to do, and what it answers about the pull request.
REAL = [activities.merge_pr_saying_why, activities.check_pr_status, activities.force_merge_pr]
MOCKS = [mock_run_job, mock_ci, mock_mstate, mock_merge_now, mock_settle, mock_journal,
         mock_mark, mock_diagnose, mock_title, mock_refresh, mock_say]


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.fixture(params=list(_ROWS), ids=list(_ROWS))
def pr(request, monkeypatch):
    """One pull request on one shipped forge row, handed to the REAL activities."""
    recorded = _ROWS[request.param]()
    forge = recorded.row()

    class _Registry:
        def get(self, name):
            return name

    monkeypatch.setattr(activities, "ProjectRegistry", _Registry)
    monkeypatch.setattr(activities, "_forge_for", lambda project: forge)
    _OPENED.clear(), _SETTLED.clear()
    _OPENED.update(url=recorded.url, auto=False)
    _MSTATE[0] = "blocked"
    return recorded


async def _start(env: WorkflowEnvironment):
    return await env.client.start_workflow(
        JobWorkflow.run,
        JobParams(project="p", issue="87", promote=False, merge_deadline_days=3650,
                  impediment_deadline_days=1),
        id=f"wf-{uuid.uuid4()}", task_queue=TQ)


async def _real_time(what: str, check, *, tries: int = 400):
    """Poll in REAL time — the engine's clock stands still until a result is awaited."""
    for _ in range(tries):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"never saw: {what}")


async def _answer_merge(h, env: WorkflowEnvironment) -> None:
    for _ in range(60):
        gate = await h.query(JobWorkflow.awaiting_merge)
        if gate and gate.get("gate_live"):
            break
        await env.sleep(timedelta(seconds=1))
    else:
        raise AssertionError("the job never opened a merge gate for a person to answer")
    await h.signal(JobWorkflow.human_merge_gate, args=["merge", "", "a-person"])


async def _nothing_settled_while_it_is_open(h, pr) -> None:
    """Give a wrong ending every chance to happen: the merge was asked for, the pull request is
    still open, and nothing may say Done — which is what closes the card."""
    await _real_time("the forge asked to merge", lambda: pr.merges)
    for _ in range(40):
        if _SETTLED:
            break
        await asyncio.sleep(0.05)
    assert not [s for s in _SETTLED if s.state == JobState.DONE.value], (
        "the card was settled as Done — and so CLOSED — while its pull request was still open: "
        "the merge was only armed")
    assert (await h.describe()).status == WorkflowExecutionStatus.RUNNING, (
        "the job ended while the pull request it was watching had not merged")


# ── a merge a person asked for ──────────────────────────────────────────────────────────────────

async def test_a_merge_a_person_asked_for_is_Done_only_once_the_forge_reads_it_merged(
        env: WorkflowEnvironment, pr):
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[*REAL, *MOCKS]):
        h = await _start(env)
        await _answer_merge(h, env)
        await _nothing_settled_while_it_is_open(h, pr)

        pr.land()  # the checks passed; the forge merged it on its own
        result = await h.result()

    assert result.state == JobState.MERGED
    assert [s.state for s in _SETTLED] == [JobState.DONE.value], (
        "the merge landed and the card was not settled as Done exactly once")


async def test_an_armed_merge_that_never_lands_never_closes_the_card(
        env: WorkflowEnvironment, pr):
    """THE CASE THE RULE IS FOR. The checks failed, and the pull request was closed instead of
    merged. The card was never delivered, so nothing may write Done on it."""
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[*REAL, *MOCKS]):
        h = await _start(env)
        await _answer_merge(h, env)
        await _nothing_settled_while_it_is_open(h, pr)

        pr.abandon()
        result = await h.result()

    assert result.state != JobState.MERGED, result
    assert JobState.DONE.value not in [s.state for s in _SETTLED], (
        "a card whose pull request was closed WITHOUT merging was settled as Done — closed as "
        "delivered work")


async def test_the_waiting_merge_is_shown_as_the_forges_not_the_persons(
        env: WorkflowEnvironment, pr):
    """The person answered; what the job waits on now is the forge landing it. The watch must not
    go back to asking them for a merge they already gave."""
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[*REAL, *MOCKS]):
        h = await _start(env)
        await _answer_merge(h, env)
        await _nothing_settled_while_it_is_open(h, pr)

        gate = await h.query(JobWorkflow.awaiting_merge)
        assert gate and gate.get("auto") is True, (
            f"the watch is asking the person for the merge they already gave: {gate}")
        pr.land()
        await h.result()


# ── the machine's own self-merge ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pr", ["Azure DevOps"], indirect=True)
async def test_a_self_merge_the_forge_accepted_is_Done_only_once_it_reads_merged(
        env: WorkflowEnvironment, pr):
    """The machine's own merge of a clean pull request, `force_merge`. On Azure DevOps it is a
    completion request, the same one the row's `merge_pr` falls back to and calls asynchronous;
    GitHub's `gh pr merge --admin` merges before it answers. Either way, Done follows the READ."""
    _OPENED["auto"] = True
    _MSTATE[0] = "clean"
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[*REAL, *MOCKS]):
        h = await _start(env)
        await _nothing_settled_while_it_is_open(h, pr)

        pr.land()
        result = await h.result()

    assert result.state == JobState.MERGED
    assert [s.state for s in _SETTLED] == [JobState.DONE.value]


# ── the tracker row does not duplicate the forge's closing word ─────────────────────────────────

@pytest.fixture
def gh(monkeypatch) -> FakeGH:
    fake = FakeGH()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def test_an_issue_the_merge_already_closed_is_not_closed_a_second_time(gh):
    """The owned pairing: the pull request's `Closes #7` closed the issue at the merge, before
    Done is written. The row reads that, and writes nothing — one writer per close."""
    gh.first = [("--json state", "CLOSED\n")]

    GitHubIssuesTracker("o/r").set_state("#7", JobState.DONE)

    assert not gh.matching("issue", "close"), "the row closed an issue the merge had closed"


def test_an_issue_the_merge_did_not_close_is_closed_once_as_completed(gh):
    """Every other pairing — another repository, Azure Repos, a local forge — and the owned one
    whose merge went into a branch GitHub's keyword does not act on."""
    gh.first = [("--json state", "OPEN\n")]

    GitHubIssuesTracker("acme/api").set_state("acme/issues#12", JobState.DONE)

    [closed] = gh.matching("issue", "close")
    assert closed[closed.index("--repo") + 1] == "acme/issues"
    assert closed[closed.index("--reason") + 1] == "completed"


def test_an_issue_closed_between_the_read_and_a_refused_close_is_not_reported(gh, caplog):
    """The keyword can land after the row looked. A close refused then is not a card left open:
    the issue reads open until the close is tried, and closed from then on."""
    real = gh.__call__

    def answering(argv, **kw):
        if "--json" in argv and "state" in argv:
            gh.calls.append(list(argv))
            state = "CLOSED" if gh.matching("issue", "close") else "OPEN"
            return subprocess.CompletedProcess(argv, 0, stdout=f"{state}\n", stderr="")
        return real(argv, **kw)

    gh.fail = {"issue close"}
    tracker = GitHubIssuesTracker("o/r")
    with pytest.MonkeyPatch.context() as mp, caplog.at_level(logging.ERROR):
        mp.setattr(subprocess, "run", answering)
        tracker.set_state("#7", JobState.DONE)

    assert gh.matching("issue", "close"), "the row never tried to close an issue it read open"
    assert "OPENFACTORY_DELIVERED_CARD_NOT_CLOSED" not in caplog.text

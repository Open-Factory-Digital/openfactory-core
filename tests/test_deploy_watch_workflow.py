"""Post-merge deploy WATCH (ADR-0005), proven deterministically.

The watch must (a) notify the deploy's real outcome, (b) survive a stuck deploy by
notifying a timeout rather than hanging, and (c) NEVER gate the job — a merged job
completes and frees the floor whether or not the deploy is watchable. Run against
Temporal's time-skipping env with mocked activities (no GitHub), so the polling +
the abandoned-child spawn are exercised offline.
"""

from __future__ import annotations

import uuid

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.manifest import PostMergeDeploy
from openfactory.runtime.temporal.io import (
    DeployNotifyInput,
    DeployStatusInput,
    DeployWatchInput,
    JobParams,
    MergeCheckInput,
    RunJobInput,
)
from openfactory.runtime.temporal.workflow import DeployWatchWorkflow, JobWorkflow

#: THIS FILE STARTS ITS OWN ENGINE, like `test_temporal_workflow`. `WorkflowEnvironment` boots an
#: ephemeral Temporal on a port it picked and owns its whole life. Everything else in the suite is
#: blocked by `conftest._no_live_durable_engine` (#107).
pytestmark = pytest.mark.owns_its_engine

TQ = "test-deploy-watch"

# notify_deploy is a side channel; record what it emitted so the tests can assert the
# outcome the watch reported without a real notifier.
_NOTIFIED: list[dict] = []


@activity.defn(name="notify_deploy")
async def mock_notify(inp: DeployNotifyInput) -> None:
    _NOTIFIED.append({"status": inp.status, "env": inp.env, "run_url": inp.run_url,
                      "issue": inp.issue})


def _status_activity(script: list[dict]):
    """A check_deploy_status that returns each scripted probe in turn, holding the last."""
    calls = {"n": 0}

    @activity.defn(name="check_deploy_status")
    async def mock_status(inp: DeployStatusInput) -> dict:
        i = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        return script[i]

    return mock_status


@pytest.fixture
async def env():
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _run_watch(wenv: WorkflowEnvironment, script: list[dict], **kw) -> str:
    _NOTIFIED.clear()
    worker = Worker(
        wenv.client, task_queue=TQ, workflows=[DeployWatchWorkflow],
        activities=[_status_activity(script), mock_notify],
    )
    async with worker:
        return await wenv.client.execute_workflow(
            DeployWatchWorkflow.run,
            DeployWatchInput(project="p", issue="10", pr_url="https://x/pr/1",
                             workflow="deploy.yml", **kw),
            id=f"dw-{uuid.uuid4()}", task_queue=TQ,
        )


async def test_notifies_success(env: WorkflowEnvironment):
    out = await _run_watch(env, [{"status": "success", "run_url": "u/7"}])
    assert out == "success"
    assert _NOTIFIED == [{"status": "success", "env": "dev", "run_url": "u/7", "issue": "10"}]


async def test_notifies_failure(env: WorkflowEnvironment):
    out = await _run_watch(env, [{"status": "failure", "run_url": "u/9"}], env="dev")
    assert out == "failure"
    assert _NOTIFIED[0]["status"] == "failure"


async def test_waits_through_none_then_pending_then_reports(env: WorkflowEnvironment):
    # deploy not dispatched yet → still running → done; the watch keeps polling (durable
    # timers, time-skipped) and reports only the terminal outcome, once.
    out = await _run_watch(env, [
        {"status": "none", "run_url": None},
        {"status": "pending", "run_url": "u/7"},
        {"status": "success", "run_url": "u/7"},
    ])
    assert out == "success"
    assert len(_NOTIFIED) == 1  # exactly one notification, the terminal one
    assert _NOTIFIED[0]["run_url"] == "u/7"


async def test_stuck_deploy_times_out_and_notifies_never_hangs(env: WorkflowEnvironment):
    # perpetually pending → the watch must give up at the deadline with a timeout notice,
    # not hang forever (watching never blocks anything).
    out = await _run_watch(env, [{"status": "pending", "run_url": "u/7"}], timeout_minutes=5)
    assert out == "timeout"
    assert _NOTIFIED[0]["status"] == "timeout"


# -- integration: a MERGED job spawns the abandoned watch and frees the floor at once ------

@activity.defn(name="run_job")
async def merged_run_job(inp: RunJobInput) -> RunResult:
    # the machine armed auto-merge and set the deploy-watch config (ADR-0005)
    return RunResult(
        ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1",
        auto_merge=True,
        post_merge_deploy=PostMergeDeploy(workflow="deploy.yml", env="dev"),
    )


@activity.defn(name="check_pr_status")
async def merged_yes(inp: MergeCheckInput) -> str:
    return "merged"


@activity.defn(name="check_ci_status")
async def ci_success(inp: MergeCheckInput) -> str:
    return "success"


@activity.defn(name="stop_job")
async def noop_stop(inp: RunJobInput) -> int:
    return 0


async def test_merged_job_spawns_watch_and_returns_immediately(env: WorkflowEnvironment):
    _NOTIFIED.clear()
    worker = Worker(
        env.client, task_queue=TQ,
        workflows=[JobWorkflow, DeployWatchWorkflow],
        activities=[merged_run_job, merged_yes, ci_success, noop_stop,
                    _status_activity([{"status": "success", "run_url": "u/7"}]), mock_notify],
    )
    async with worker:
        client: Client = env.client
        h = await client.start_workflow(
            JobWorkflow.run, JobParams(project="p", issue="55", promote=False),
            id="wf-merged-55", task_queue=TQ,
        )
        result = await h.result()
        assert result.state == JobState.MERGED  # the job is DONE — floor is free

        # the abandoned child kept running past the parent's completion and reported the
        # deploy outcome via notify (id convention: openfactory-deploy-<project>-<issue>).
        child = client.get_workflow_handle("openfactory-deploy-p-55")
        assert await child.result() == "success"
    assert _NOTIFIED and _NOTIFIED[0]["status"] == "success" and _NOTIFIED[0]["issue"] == "55"

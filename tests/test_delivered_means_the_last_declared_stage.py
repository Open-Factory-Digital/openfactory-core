"""Delivered means delivered: the delivery is announced when the change reaches the LAST stage the
project declares, and a "did not work" after it is a defect linked to the card, for the requester's
yes (#448 slice 5, behaviour 6; ADR-0055 D1 — `delivered` follows `released`, never the merge, when
a project declares stages).

WHAT WAS WRONG, measured on this branch's parent (6bca65e) before a line of it changed:

  · A project that declares `post_merge_deploy:` and no `environments:` — a repository that deploys
    from its own workflow — was settled Done AT THE MERGE (`should_promote` is False, so
    `_finish_at_the_merge` ran), and Done is what a delivery is announced from: the job's one exit
    (`record_outcome` → `events.card_finished` → `deliver`) told the requester "what you asked for
    is ready — did it work?" while the deploy the factory was still watching had not happened and
    could still fail. The watch's outcome reached the operator and the room only, and a red deploy
    undid nothing. The requester's merge telling (#448 slice 3) said no stage followed.
  · On the pairing whose forge closes the card itself (`Closes #12`, GitHub issues over the same
    repository), EVERY staged shape — a watched deploy or a chain — had its card closed at the
    merge, and a closed card is what reads as delivered (`triage.Ticket.delivered`): the next look
    at the board, the job's end or the weekly sweep, announced it whatever stage was still ahead.
  · A "did not work" closed the acceptance as `did-not-work` and asked the person to say it all
    again — in Portuguese whatever the project spoke — so that it could be registered. Nothing was
    staged, nothing named the card, and the person the delivery was for could not have confirmed a
    defect without being on the approvers' list.

AND WHAT WAS ALREADY RIGHT, pinned here so it stays so: a project with no stage is delivered at the
merge; a chain with production is delivered once production is released.

HOW. The real `JobWorkflow` and `DeployWatchWorkflow` on this file's own time-skipping engine, with
the real job-ending activities (`settle_ticket`, `record_outcome`, `tell_the_requester_it_merged`)
over the real local board, the real ledger on the SQLite store and the real events module; the real
chat turn, staging, confirmation and pen (`ProductModule.file_defect`) for the "did not work".
Doubled: what leaves the machine (the forge's answers, the deploy's status, the notifier, the box's
promotion), the door (`events._tell`, recorded), and ONE reading of the board — `done_reads_
delivered` says which, and why.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from temporalio import activity

import openfactory.product.channel as pc
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.contracts.manifest import PostMergeDeploy
from openfactory.memory import store as loop_store
from openfactory.memory.ledger import ACCEPTANCE, DELIVERY, open_loop, waiting
from openfactory.product import events, followup, voice
from openfactory.product.speaker import sealed
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import (
    DeployNotifyInput,
    DeployStatusInput,
    DeployWatchInput,
    HoldSyncInput,
    JobParams,
    MergeCheckInput,
    PromoteInput,
    ReleaseInput,
    RunJobInput,
    TicketRef,
)
from openfactory.runtime.temporal.workflow import DeployWatchWorkflow, JobWorkflow
from tests.the_chat_turn import chat_turn

LANG, AGENT, ROOM = "en", "Nina", "acme"
ASKER, ADMIN, STRANGER = "ana-asked-77", "po-admin-12", "somebody-else-42"
#: The requester's own conversation — where the card was asked for, and where it is announced.
KEY = f"person:{ASKER}"
TITLE = "Export the list"
STILL_BROKEN = "It still does not export — the button does nothing."
STAGING = "https://staging.acme.example"


@pytest.fixture(autouse=True)
def _nothing_staged():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a product role, its board `project init` made, and its
    memory — the ledger and the store — on SQLite."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.board import forget_board
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language=LANG,
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN],
                                               agent_name=AGENT)))
    project = registry.get(ROOM)
    LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
    forget_board()
    yield project
    forget_board()


@pytest.fixture
def tracker(deployment):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(deployment)


@pytest.fixture
def board(deployment):
    from openfactory.adapters.board import build_board

    return build_board(deployment)


#: What happened, in the order it happened — the deploy's probes, the card's settles, the job's
#: records of an ending, and what reached the door.
_LOG: list[tuple] = []


@pytest.fixture
def door(monkeypatch):
    """The one door every telling goes through, recorded; `_once` and its record run as they are."""
    _LOG.clear()
    monkeypatch.setattr(events, "_tell", lambda project, **kw: _LOG.append(
        ("told", kw["conversation"], kw["text"])) or True)
    monkeypatch.setattr(events, "_preview_offered", lambda project, card: False)
    return _LOG


@pytest.fixture
def done_reads_delivered(board):
    """NOTHING IS STOOD IN ANY MORE. This slice once read the local board's Done column as
    delivered, because that row kept a Done card open and no delivery was ever announced on it
    (filed as #500). #500 is fixed (#506): the local row closes a card at Done as delivered, as
    every hosted row does, so the real reading (`events._delivered_now`) is the one these tests
    walk. The fixture stays as the name the tests ask for."""
    return board


def _pen(project, tmp_path, monkeypatch):
    """The product role's real pen, over the project's own tracker, board and ledger."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    pen = ProductModule(project, context=ctx, agent=_Harness("{}"))
    # THE MODEL'S READING OF A MESSAGE is the one thing a turn would spend on: every message here
    # is settled before the conversation, and one that reached it would be a test that went wrong
    monkeypatch.setattr(pen, "answer", lambda *a, **k: pytest.fail("the turn reached the model"))
    return pen


def _asked_for(project, tracker, board, tmp_path, monkeypatch, *, where: str = KEY,
               who: str = ASKER) -> str:
    """A card somebody asked for in `where`, at its merge — its delivery owed to them there."""
    ref = tracker.create_ticket(title=TITLE, body="an export button on the list",
                                requester=who).lstrip("#")
    board.set_column(issue=ref, issue_url="", name="In review")
    _pen(project, tmp_path, monkeypatch)._track_ticket(ref, title=TITLE, conversation=where,
                                                       requester=who)
    return ref


def _column(board, ref: str) -> str:
    """Where the card is: an open card in the column the board lists it in; a card closed as
    delivered in Done, where the local row closes it since #500 (#506), as the hosted rows do —
    the board lists open cards only."""
    for name in ("Backlog", "To Do", "In progress", "In review", "Needs Action", "Done"):
        if ref in [str(r).lstrip("#") for r in board.items_in_status(name)]:
            return name
    from openfactory.adapters.board_db import connect

    with connect() as conn:
        row = conn.execute("SELECT state, closed_reason, column_key FROM cards WHERE ref = ?",
                           (int(str(ref).lstrip("#")),)).fetchone()
    if row is not None and tuple(row) == ("closed", "completed", "done"):
        return "Done"
    return ""


def _told() -> list[tuple[str, str]]:
    return [(e[1], e[2]) for e in _LOG if e[0] == "told"]


def _went_in(ref: str, *, stages: bool) -> str:
    return voice.merged_for_you(ref=ref, title=TITLE, stages_follow=stages, language=LANG,
                                agent_name=AGENT)


def _announced(project, ref: str) -> str:
    """The delivery's own sentence and its "did it work?", as `deliver` composes them."""
    loop = open_loop(DELIVERY, f"cartao-{ref}", owner="product", ts="t",
                     context={"issues": ref, "ticket": "1", "title": TITLE})
    return (followup.delivered_text(loop, agent_name=AGENT, language=LANG)
            + followup.acceptance_question(loop, agent_name=AGENT, language=LANG))


# ── 1. the job and the watch, on the real workflows ─────────────────────────────────────────────

TQ = "test-delivered-at-the-last-stage"
JOB_PR = "https://forge.example/acme/pull/9"

#: What the run carried back from the box: the manifest's stages.
_RUN: dict = {}
#: The deploy's status, probe by probe — the last one held.
_PROBES: list[dict] = []


@activity.defn(name="run_job")
async def _run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=JOB_PR, auto_merge=True,
                     **_RUN)


@activity.defn(name="read_ci_checks")
async def _green(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="success")


@activity.defn(name="check_pr_status")
async def _merged(inp: MergeCheckInput) -> str:
    return "merged"


@activity.defn(name="stop_job")
async def _stop(inp: RunJobInput) -> int:
    return 0


@activity.defn(name="fetch_ticket_title")
async def _title(inp: TicketRef) -> str:
    return TITLE


@activity.defn(name="notify_coordinator_say")
async def _narrated(inp) -> None:
    return None


@activity.defn(name="refresh_knowledge")
async def _refreshed(inp) -> str:
    return "published"


@activity.defn(name="check_deploy_status")
async def _probe(inp: DeployStatusInput) -> dict:
    seen = len([e for e in _LOG if e[0] == "probe"])
    got = _PROBES[min(seen, len(_PROBES) - 1)]
    _LOG.append(("probe", got["status"]))
    return got


@activity.defn(name="notify_deploy")
async def _notified(inp: DeployNotifyInput) -> None:
    _LOG.append(("notified", inp.status))


#: THE TRACKER AT ITS SLOWEST, for the test that asks for it (`client`, `watch_settled`): a settle
#: In review that finds the card's watch ALREADY RUNNING is held until the watch has settled the
#: card. That interleaving is one the engine permits once a watch starts before the job's own
#: settle; here it is made certain, rather than left to which activity a worker picks up first.
_SLOW: dict = {}


@activity.defn(name="settle_ticket")
async def _settle(inp: HoldSyncInput) -> str:
    """The REAL settle, on the real local board — recorded on its way past."""
    _LOG.append(("settle", inp.state, inp.note))
    if _SLOW and inp.state == JobState.MERGED.value and await _watch_running(inp.issue):
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(_SLOW["watch_settled"].wait(), timeout=30)
    done = await acts.settle_ticket(inp)
    if _SLOW and inp.state != JobState.MERGED.value:
        _SLOW["watch_settled"].set()
    return done


async def _watch_running(ref: str) -> bool:
    from temporalio.client import WorkflowExecutionStatus

    try:
        desc = await _SLOW["client"].get_workflow_handle(f"openfactory-deploy-{ROOM}-{ref}"
                                                         ).describe()
    except Exception:  # noqa: BLE001 — not started: the order this file expects
        return False
    return desc.status == WorkflowExecutionStatus.RUNNING


@activity.defn(name="record_outcome")
async def _journal(inp: HoldSyncInput) -> str:
    """The REAL record of an ending — the journal, and the delivery check behind it."""
    _LOG.append(("journal", inp.state))
    return await acts.record_outcome(inp)


def _the_box_writes(issue: str, state: JobState) -> None:
    """What the box's `PromotionRunner` writes onto the card as it promotes (`_state`)."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.registry import ProjectRegistry

    build_tracker(ProjectRegistry().get(ROOM)).set_state(issue, state)


@activity.defn(name="promote_staging")
async def _promoted(inp: PromoteInput) -> RunResult:
    """What the box's `PromotionRunner.promote` answers for the chain the run carried: with stages,
    a park at the production gate; with NONE — `--promote` on a manifest that declares no chain —
    an empty walk that writes Done at once, which is what made it announce early (#501)."""
    _LOG.append(("promoted", inp.issue))
    if not _RUN.get("environments"):
        _the_box_writes(inp.issue, JobState.DONE)
        return RunResult(ticket_id=inp.issue, state=JobState.DONE)
    _the_box_writes(inp.issue, JobState.AWAITING_PROD_APPROVAL)
    return RunResult(ticket_id=inp.issue, state=JobState.AWAITING_PROD_APPROVAL,
                     look_stage="staging", look_at=STAGING)


@activity.defn(name="release_prod")
async def _released(inp: ReleaseInput) -> RunResult:
    _LOG.append(("released", inp.issue))
    _the_box_writes(inp.issue, JobState.DONE)
    return RunResult(ticket_id=inp.issue, state=JobState.DONE)


def _activities():
    from gate_answers import SEAL_CHECK

    return [SEAL_CHECK, _run_job, _green, _merged, _stop, _title, _narrated, _refreshed, _probe,
            _notified, _settle, _journal, _promoted, _released, acts.tell_the_requester_it_merged]


@pytest.fixture
async def env():
    """This file's own ephemeral engine, started and disposed of here — the declared exception to
    the suite's no-live-engine rule (`conftest.OWNS_ITS_ENGINE`)."""
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    _RUN.clear(), _PROBES.clear(), _SLOW.clear()
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


def _deploy(**kw) -> PostMergeDeploy:
    return PostMergeDeploy(workflow="deploy.yml", env="staging", url=STAGING, **kw)


async def _watched(env, ref: str) -> str:
    """The abandoned watch, to its end. Its handle is not one the engine skips time for — only
    `start_workflow`'s are — so the clock is let go here exactly as such a handle lets it go."""
    async with env.time_skipping_unlocked():
        return await env.client.get_workflow_handle(f"openfactory-deploy-{ROOM}-{ref}").result()


async def _job(env, ref: str, *, approve: bool = False, watch: bool = True,
               promote: bool = False):
    """The job run to its end — and, when the project watches a deploy, the watch to its end.
    `promote` is the start-time flag (`--promote`, `JobParams.promote`)."""
    from gate_answers import approve_prod
    from temporalio.worker import Worker

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow, DeployWatchWorkflow],
                      activities=_activities()):
        h = await env.client.start_workflow(
            JobWorkflow.run, JobParams(project=ROOM, issue=ref, merge_deadline_days=3650,
                                       promote=promote),
            id=f"wf-{uuid.uuid4()}", task_queue=TQ, result_type=RunResult)
        at_the_gate = None
        if approve:
            for _ in range(400):
                if await h.query(JobWorkflow.awaiting_approval):
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("the job never parked at the production gate")
            at_the_gate = list(_LOG)
            await approve_prod(h, "1.0.0", ADMIN)
        result = await h.result()
        watched = None
        if _RUN.get("post_merge_deploy") and watch:
            watched = await _watched(env, ref)
        history = await h.fetch_history()
    return result, watched, at_the_gate, history


def _settled() -> list[str]:
    return [e[1] for e in _LOG if e[0] == "settle"]


def _journalled() -> list[str]:
    return [e[1] for e in _LOG if e[0] == "journal"]


@pytest.mark.owns_its_engine
async def test_a_watched_deploy_is_the_last_stage_and_the_delivery_waits_for_it_green(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """BEHAVIOUR 6: nothing is delivered at the merge; the requester hears the change went in and
    that a stage follows; the delivery and its "did it work?" come when the watch sees it green."""
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy(timeout_minutes=45)
    _PROBES[:] = [{"status": "pending", "run_url": None}, {"status": "success", "run_url": "u/7"}]

    result, watched, _, _ = await _job(env, ref)

    assert result.state is JobState.MERGED and watched == "success"
    # IN REVIEW AT THE MERGE, said on the card, and before the watch's first look
    assert _settled() == [JobState.MERGED.value, JobState.DONE.value], _LOG
    [at_merge] = [e for e in _LOG if e[0] == "settle" and e[1] == JobState.MERGED.value]
    assert "deploy.yml" in at_merge[2] and "staging" in at_merge[2] and "45" in at_merge[2]
    assert "when it is green, not before" in at_merge[2]
    assert _LOG.index(at_merge) < _LOG.index(("probe", "pending"))
    # the job's own end found nothing delivered; the watch's end did
    assert _journalled() == [JobState.MERGED.value, JobState.DONE.value]
    assert _told() == [(KEY, _went_in(ref, stages=True)),
                       (KEY, _announced(deployment, ref))], _told()
    delivered_at = _LOG.index(("told", KEY, _announced(deployment, ref)))
    assert _LOG.index(("journal", JobState.MERGED.value)) < _LOG.index(("probe", "success")) \
        < delivered_at, _LOG
    assert _column(board, ref) == "Done"
    # …and the watch still spoke where it always spoke
    assert ("notified", "success") in _LOG


@pytest.mark.owns_its_engine
async def test_a_deploy_green_at_the_watchs_first_look_leaves_the_card_done(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """THE CARD IS SETTLED IN REVIEW BEFORE ITS WATCH STARTS (#448 slice 5, the review of #503).
    Two awaits in one workflow happen in the order they are written, and here the order is the
    claim: a deploy already green at the watch's first look settles the card Done, and a settle In
    review that came after the watch started would put the delivered card back. The tracker is
    as slow as it can be (`_SLOW`), so the wrong order loses every time, not when a worker happens
    to pick the activities that way."""
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy()
    _PROBES[:] = [{"status": "success", "run_url": "u/7"}]
    _SLOW.update(client=env.client, watch_settled=asyncio.Event())

    result, watched, _, _ = await _job(env, ref)

    assert result.state is JobState.MERGED and watched == "success"
    assert [e for e in _LOG if e[0] == "probe"] == [("probe", "success")], _LOG
    assert _settled() == [JobState.MERGED.value, JobState.DONE.value], _LOG
    assert _column(board, ref) == "Done", (
        "the card went back to In review after its deploy was green — settled after its watch")
    assert _told().count((KEY, _announced(deployment, ref))) == 1, _told()


@pytest.mark.parametrize("probes,status,said", [
    ([{"status": "failure", "run_url": "u/9"}], "failure", "The staging deploy failed"),
    ([{"status": "pending", "run_url": "u/7"}], "timeout",
     "The staging deploy was not seen to finish within 5 minutes"),
], ids=["failed", "never seen"])
@pytest.mark.owns_its_engine
async def test_a_deploy_that_fails_or_is_never_seen_delivers_nothing(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch,
        probes, status, said):
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy(timeout_minutes=5)
    _PROBES[:] = probes

    result, watched, _, _ = await _job(env, ref)

    assert result.state is JobState.MERGED and watched == status
    assert _settled() == [JobState.MERGED.value, JobState.ON_HOLD.value], _LOG
    [held] = [e for e in _LOG if e[0] == "settle" and e[1] == JobState.ON_HOLD.value]
    assert held[2].startswith(said) and "nothing is delivered" in held[2], held[2]
    assert _journalled() == [JobState.MERGED.value, JobState.ON_HOLD.value]
    assert _told() == [(KEY, _went_in(ref, stages=True))], "something was announced as delivered"
    assert _column(board, ref) == "Needs Action"
    assert ("notified", status) in _LOG, "the watch stopped saying it where it always did"


@pytest.mark.owns_its_engine
async def test_a_watch_that_could_not_start_leaves_the_card_settled_where_it_always_was(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """A watch already running for this card (a re-run of it) is not one this job started, and it
    will settle nothing: the card is not left In review for a watch that is not coming — the merge
    settles it, as it did before this slice."""
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy()
    _PROBES[:] = [{"status": "pending", "run_url": None}]
    await env.client.start_workflow(
        DeployWatchWorkflow.run,
        DeployWatchInput(project=ROOM, issue=ref, pr_url=JOB_PR, workflow="deploy.yml",
                         env="staging", timeout_minutes=720),
        id=f"openfactory-deploy-{ROOM}-{ref}", task_queue=TQ)

    result, _, _, _ = await _job(env, ref, watch=False)

    assert result.state is JobState.MERGED
    assert _settled() == [JobState.MERGED.value, JobState.DONE.value], _LOG
    assert _column(board, ref) == "Done"
    assert _told()[-1] == (KEY, _announced(deployment, ref))


@pytest.mark.owns_its_engine
async def test_a_project_with_no_stage_is_delivered_at_the_merge_as_before(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)

    result, watched, _, _ = await _job(env, ref)

    assert result.state is JobState.MERGED and watched is None
    assert _settled() == [JobState.DONE.value]
    assert _journalled() == [JobState.MERGED.value]
    # the delivery says it, and the merge telling says nothing beside it (#448 slice 3)
    assert _told() == [(KEY, _announced(deployment, ref))], _told()
    assert _column(board, ref) == "Done"


@pytest.mark.owns_its_engine
async def test_a_chain_with_production_is_delivered_once_production_is_released(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["environments"] = ["staging", "prod"]

    result, _, at_the_gate, _ = await _job(env, ref, approve=True)

    assert [(e[1], e[2]) for e in at_the_gate if e[0] == "told"] == [
        (KEY, _went_in(ref, stages=True))], "delivered before production was released"
    assert result.state is JobState.DONE
    assert _settled() == [], "the promotion owns this card's column, as it always did"
    assert _told() == [(KEY, _went_in(ref, stages=True)), (KEY, _announced(deployment, ref))]
    assert _LOG.index(("released", ref)) < _LOG.index(("told", KEY, _announced(deployment, ref)))


@pytest.mark.owns_its_engine
async def test_promote_on_a_deploy_only_manifest_WATCHES_THE_DEPLOY_not_an_empty_promotion(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """#501 (c). `--promote` asked for a promotion the manifest has no stage for: the box walked an
    empty chain, wrote Done, and the job's end announced the delivery before the watched deploy.
    The deploy is this card's last stage with the flag exactly as without it."""
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy(timeout_minutes=45)
    _PROBES[:] = [{"status": "pending", "run_url": None}, {"status": "success", "run_url": "u/7"}]

    result, watched, _, _ = await _job(env, ref, promote=True)

    assert ("promoted", ref) not in _LOG, "an empty promotion still ran and wrote Done"
    assert result.state is JobState.MERGED and watched == "success"
    assert _settled() == [JobState.MERGED.value, JobState.DONE.value], _LOG
    assert _journalled() == [JobState.MERGED.value, JobState.DONE.value]
    assert _told() == [(KEY, _went_in(ref, stages=True)),
                       (KEY, _announced(deployment, ref))], _told()
    assert _LOG.index(("probe", "success")) < _LOG.index(
        ("told", KEY, _announced(deployment, ref))), "delivered before the deploy was green"
    assert _column(board, ref) == "Done"


@pytest.mark.owns_its_engine
async def test_promote_on_a_manifest_WITH_a_chain_still_walks_it_whatever_it_watches(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """The other side of the same line: a chain is a stage the promotion owns, and the flag
    still sends the job down it when a deploy is watched beside it."""
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["environments"] = ["staging", "prod"]
    _RUN["post_merge_deploy"] = _deploy()
    _PROBES[:] = [{"status": "success", "run_url": "u/7"}]

    result, _, _, _ = await _job(env, ref, approve=True, promote=True)

    assert ("promoted", ref) in _LOG and ("released", ref) in _LOG, _LOG
    assert result.state is JobState.DONE
    assert _settled() == [], "the promotion owns this card's column, as it always did"


# ── 2. new commands, behind their markers ───────────────────────────────────────────────────────

async def _replays(history, *, workflows, marker: str, monkeypatch) -> None:
    """The recorded history replays through the real `patched()`, and DIVERGES through the
    marker's arm — or the green replay verified nothing."""
    from temporalio import workflow as tw
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer

    real = tw.patched
    await Replayer(workflows=workflows,
                   data_converter=pydantic_data_converter).replay_workflow(history)
    monkeypatch.setattr(tw, "patched", lambda name: True if name == marker else real(name))
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=workflows,
                       data_converter=pydantic_data_converter).replay_workflow(history)
    said = str(caught.value)
    assert "determinis" in said.lower() or "TMPRL1100" in said or "Nondeterminism" in said, (
        f"the marker's arm failed the replay for another reason: {said[:400]}")


@pytest.mark.owns_its_engine
async def test_a_job_that_merged_before_this_replays_its_done_at_the_merge(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    from temporalio import workflow as tw

    marker = "delivered-at-the-last-declared-stage"
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy()
    _PROBES[:] = [{"status": "success", "run_url": "u/7"}]
    real = tw.patched
    with monkeypatch.context() as m:
        m.setattr(tw, "patched", lambda name: False if name == marker else real(name))
        result, watched, _, history = await _job(env, ref)
    assert result.state is JobState.MERGED and watched == "success"
    assert _settled() == [JobState.DONE.value], "the recording ran the commands it predates"

    await _replays(history, workflows=[JobWorkflow], marker=marker, monkeypatch=monkeypatch)


@pytest.mark.owns_its_engine
async def test_a_promote_job_that_merged_before_this_replays_its_empty_promotion(
        env, deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """#501 (c): a `--promote` job on a deploy-only manifest recorded before the marker walked
    the empty promotion, and replays it; the marker's arm diverges from that history."""
    from temporalio import workflow as tw

    marker = "promote-on-a-deploy-only-manifest-watches-it"
    ref = _asked_for(deployment, tracker, board, tmp_path, monkeypatch)
    _RUN["post_merge_deploy"] = _deploy()
    _PROBES[:] = [{"status": "success", "run_url": "u/7"}]
    real = tw.patched
    with monkeypatch.context() as m:
        m.setattr(tw, "patched", lambda name: False if name == marker else real(name))
        result, _, _, history = await _job(env, ref, promote=True)
    assert ("promoted", ref) in _LOG and result.state is JobState.DONE, (
        "the recording did not run the commands it predates")

    await _replays(history, workflows=[JobWorkflow], marker=marker, monkeypatch=monkeypatch)


@pytest.mark.owns_its_engine
async def test_a_watch_started_before_this_replays_without_settling(env, monkeypatch):
    from temporalio import workflow as tw
    from temporalio.worker import Worker

    marker = "the-watch-settles-the-last-stage"
    _LOG.clear()
    _PROBES[:] = [{"status": "success", "run_url": "u/7"}]
    real = tw.patched
    with monkeypatch.context() as m:
        m.setattr(tw, "patched", lambda name: False if name == marker else real(name))
        async with Worker(env.client, task_queue=TQ, workflows=[DeployWatchWorkflow],
                          activities=_activities()):
            h = await env.client.start_workflow(
                DeployWatchWorkflow.run,
                DeployWatchInput(project=ROOM, issue="5", pr_url=JOB_PR, workflow="deploy.yml",
                                 env="staging", delivers=True),
                id=f"dw-{uuid.uuid4()}", task_queue=TQ)
            assert await h.result() == "success"
            history = await h.fetch_history()
    assert _settled() == [] and _journalled() == []

    await _replays(history, workflows=[DeployWatchWorkflow], marker=marker,
                   monkeypatch=monkeypatch)


def test_a_watch_that_only_informs_is_told_so_by_default():
    """A watch started before the field — and every watch of a project with a chain — settles
    nothing: the field's default is the old behaviour."""
    assert DeployWatchInput(project="p", issue="1", pr_url="u", workflow="d").delivers is False


# ── 3. the forge does not close the card a stage still waits on ─────────────────────────────────

@pytest.mark.parametrize("declared,closing", [
    ({}, "Closes #12"),
    ({"post_merge_deploy": {"workflow": "deploy.yml", "env": "staging"}}, ""),
    # `deploy_ref` beside the address: a chain stage with nothing to observe is refused when the
    # manifest loads (#501, on its own branch), and this row is about the closing word, not that
    ({"environments": {"staging": {"url": STAGING, "deploy_ref": "staging"}}}, ""),
], ids=["nothing follows", "a watched deploy", "a chain"])
def test_the_forge_closes_the_card_at_the_merge_only_when_nothing_follows(declared, closing):
    """`Closes #12` makes the forge close the card AT THE MERGE, and a closed card reads as
    delivered. The tracker row closes it at Done on every pairing (#180), so with a stage ahead
    the word is withheld — and the mention, which links the change to the card, stays."""
    from openfactory.adapters.forge.github import GitHubForge
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.contracts import AcceptanceCriterion, Manifest, Ticket
    from openfactory.orchestrator.machine import card_reference_for

    ticket = Ticket(id="#12", title="add the export", objective="export the orders", repo="acme/api",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    runner = SimpleNamespace(tracker=GitHubIssuesTracker("acme/api", token="t"),
                             forge=GitHubForge("acme/api", token="t"),
                             manifest=Manifest(**declared), project=None)

    card = card_reference_for(runner, ticket)

    assert card.owned and card.title == "#12: add the export"
    assert card.closing == closing


# ── 4. "it did not work": a defect linked to the card, for the requester's yes ──────────────────

def _delivered(project, tracker, board, tmp_path, monkeypatch, **kw) -> str:
    """A card asked for, delivered and announced — its "did it work?" asked where it was asked."""
    ref = _asked_for(project, tracker, board, tmp_path, monkeypatch, **kw)
    tracker.set_state(ref, JobState.DONE)
    written = events.card_finished(project, card=ref)
    assert [x.kind for x in written] == [DELIVERY, ACCEPTANCE], written
    return ref


def _say(project, pen, text: str, *, who: str = ASKER, where: str = KEY) -> str:
    return str(chat_turn(project, text=text, user=who, thread=where, module=pen))


def _staged(project, *, who: str = ASKER, where: str = KEY):
    return pc.find_waiting(where, where, project=project, person=who)[1]


def _cards(tracker) -> dict[str, str]:
    return {str(t.ref).lstrip("#"): t.title for t in tracker.list_tickets(state="all")}


def test_the_requester_says_it_did_not_work_and_their_yes_files_the_linked_defect(
        deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """BEHAVIOUR 6, its second half, end to end on real parts — and no approver is needed: the
    delivery was theirs."""
    ref = _delivered(deployment, tracker, board, tmp_path, monkeypatch)
    [asked] = [x for x in waiting(loop_store.read(ROOM)) if x.kind == ACCEPTANCE]
    assert asked.context["issues"] == ref and asked.context["requester"] == sealed(ASKER)
    pen = _pen(deployment, tmp_path, monkeypatch)

    said = _say(deployment, pen, STILL_BROKEN)

    assert said == voice.delivery_did_not_work(cards=[ref], title=TITLE, language=LANG,
                                               agent_name=AGENT), said
    assert f"I'll file a defect for #{ref} ({TITLE}) with what you said, linked to it." in said
    staged = _staged(deployment)
    assert staged["kind"] == "defect" and staged["linked"] == ref and staged["their_delivery"]
    assert staged["restated"] == STILL_BROKEN and staged["requester"] == ASKER
    assert staged["title"] == f"Did not work after delivery: {TITLE} (#{ref})"
    # the "did it work?" is answered — as not working — and nothing is filed before the yes
    assert not [x for x in waiting(loop_store.read(ROOM)) if x.kind == ACCEPTANCE]
    assert list(_cards(tracker)) == [ref]

    filed = _say(deployment, pen, "yes")

    assert filed.startswith(voice.defect_filed(ref="", violates=None, language=LANG)), filed
    [defect] = [r for r in _cards(tracker) if r != ref]
    assert _cards(tracker)[defect] == staged["title"]
    body = {str(t.ref).lstrip("#"): t.body for t in tracker.list_tickets(state="all")}[defect]
    assert f"**After the delivery of:** #{ref} — the person who asked said it did not work." \
        in body, body
    assert STILL_BROKEN in body
    assert _column(board, defect) == "Backlog", "a defect is filed where a person promotes it"
    notes = [c.body for c in tracker.comments(f"#{ref}")]
    assert any(f"#{defect}" in n and "after this card's delivery" in n for n in notes), notes
    # …and the fix is owed to them, where they said it did not work
    [owed] = [x for x in waiting(loop_store.read(ROOM)) if x.kind == DELIVERY]
    assert owed.subject == f"defeito-{defect}" and owed.context["conversation"] == KEY
    assert _staged(deployment) is None


def test_in_the_room_anybody_s_report_is_staged_like_any_other_and_their_yes_files_nothing(
        deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """A delivery nobody's conversation was known for is announced in the room, and answered from
    it. Whoever says it did not work there is not the person it was for: their report is staged as
    any other report is, and their own yes — on no approvers' list — files nothing."""
    ref = _delivered(deployment, tracker, board, tmp_path, monkeypatch, where="", who="")
    pen = _pen(deployment, tmp_path, monkeypatch)

    said = _say(deployment, pen, STILL_BROKEN, who=STRANGER, where=ROOM)

    staged = _staged(deployment, who=STRANGER, where=ROOM)
    assert staged["kind"] == "defect" and staged["linked"] == ref
    assert "their_delivery" not in staged
    assert said == voice.delivery_did_not_work(cards=[ref], title=TITLE, language=LANG,
                                               agent_name=AGENT), said

    refused = _say(deployment, pen, "yes", who=STRANGER, where=ROOM)

    assert refused == voice.cannot_write(has_approvers=True, language=LANG), refused
    assert list(_cards(tracker)) == [ref], "a defect was filed on a yes nobody may give"


def test_where_approvers_confirm_for_a_reporter_they_are_named_and_their_yes_files_it(
        deployment, tracker, board, door, done_reads_delivered, tmp_path, monkeypatch):
    """`accept_on_behalf`: the product lets an approver confirm what somebody else reported — so
    the proposal names them, as every other report's does, and an approver's yes files it."""
    on_behalf = deployment.model_copy(update={"product": deployment.product.model_copy(
        update={"accept_on_behalf": True})})
    ref = _delivered(on_behalf, tracker, board, tmp_path, monkeypatch, where="", who="")
    pen = _pen(on_behalf, tmp_path, monkeypatch)

    said = _say(on_behalf, pen, STILL_BROKEN, who=STRANGER, where=ROOM)

    assert said.endswith(f"({ADMIN}: registering this needs your confirmation.)"), said

    _say(on_behalf, pen, "yes", who=ADMIN, where=ROOM)

    [defect] = [r for r in _cards(tracker) if r != ref]
    body = {str(t.ref).lstrip("#"): t.body for t in tracker.list_tickets(state="all")}[defect]
    assert f"**After the delivery of:** #{ref}" in body and STRANGER in body, body


def test_a_requirement_s_delivery_that_did_not_work_cites_the_promise(
        deployment, tracker, board, door, tmp_path, monkeypatch):
    """A requirement's delivery owed its cards against requirement 7: the defect breaks REQ-0007."""
    ref = tracker.create_ticket(title=TITLE, body="b", requester=ASKER).lstrip("#")
    loop_store.write(ROOM, [followup.acceptance_of(
        open_loop(DELIVERY, "7", owner="product", ts="t", context={"issues": ref}),
        ts="2026-10-04T10:00:00+00:00")])
    pen = _pen(deployment, tmp_path, monkeypatch)

    _say(deployment, pen, STILL_BROKEN, who=STRANGER, where=ROOM)

    staged = _staged(deployment, who=STRANGER, where=ROOM)
    assert staged["violates"] == 7 and staged["linked"] == ref


def test_an_acceptance_asked_before_this_names_no_card_and_is_answered_as_it_was(
        deployment, tracker, board, door, tmp_path, monkeypatch):
    loop_store.write(ROOM, [open_loop(ACCEPTANCE, "cartao-12", owner="product", ts="t",
                                      context={"ticket": "1", "title": TITLE,
                                               "conversation": KEY})])
    pen = _pen(deployment, tmp_path, monkeypatch)

    said = _say(deployment, pen, STILL_BROKEN)

    assert said == followup.rejected_text(
        open_loop(ACCEPTANCE, "cartao-12", owner="product", ts="t"), agent_name=AGENT), said
    assert _staged(deployment) is None


def test_the_acceptance_names_the_cards_delivered_never_one_cancelled_out_of_it():
    from openfactory.memory.ledger import CANCELLED_CARDS

    loop = open_loop(DELIVERY, "7", owner="product", ts="t",
                     context={"issues": "500,501,502", CANCELLED_CARDS: "501"})

    asked = followup.acceptance_of(loop, ts="2026-10-04T10:00:00+00:00")

    assert asked.context["issues"] == "500,502"
    assert "issues" not in followup.acceptance_of(
        open_loop(DELIVERY, "8", owner="product", ts="t", context={}), ts="t").context


def test_two_cards_reports_in_the_same_words_are_two_proposals():
    """The button posted for one card's defect must not file the other's."""
    from openfactory.product.staging import proposal_token

    one = {"kind": "defect", "restated": "it did not work", "linked": "500"}
    other = {**one, "linked": "501"}

    assert proposal_token(KEY, one) != proposal_token(KEY, other)


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_what_the_requester_reads_is_in_their_language_and_free_of_jargon(language):
    said = [voice.delivery_did_not_work(cards=["7"], title="t", language=language),
            voice.delivery_did_not_work(cards=["7", "8"], language=language),
            voice.defect_after_delivery_title(ref="7", title="t", language=language)]

    assert not {s: voice.jargon_in(s) for s in said if voice.jargon_in(s)}
    if language == "pt-BR":
        assert said[0].startswith("Entendido — então NÃO está resolvido")
        assert "o #7 (t)" in said[0] and "o #7 e o #8" in said[1] and "ligado a eles" in said[1]
    else:
        assert "#7 and #8" in said[1] and "linked to them" in said[1]


def test_a_long_title_is_cut_and_its_card_kept_whole():
    title = voice.defect_after_delivery_title(ref="1234", title="x" * 200, language="en")

    assert len(title) == 80 and title.endswith("… (#1234)")

"""The requester's loop, walked through the card's door on real parts (#448 slice 6; ADR-0055 D9's
third kind of test, D12).

THE EPIC'S DONE-WHEN. "A scenario test walks a card through request → preview → adjust × 2 →
accepted → auto-merge → staging 'not yet' → adjust → staging approved → production → delivered,
on real parts (ADR-0055 D9), with the requester told at every step in their own conversation."
So one card walks it here, and at every step the test reads back what each consumer says: the
card's record (the transition, where it found the card and where it left it), its column on the
board, and what the person who asked for it was told — the sentence, and the conversation it went
to. At the end the requester's reading of the record (`lifecycle/reading.py::step`) has walked all
seven steps, every transition is recorded with every effect's outcome, and the hourly converge has
nothing left to do.

WHAT IS REAL. The real `JobWorkflow`, on this file's own time-skipping engine, with the real
activities that touch the card — `run_job`, `adjust_pr`, `card_adjusted`, `tell_the_requester`,
`tell_the_requester_it_merged`, `promote_staging`, `release_prod`, `verify_gate_seal` — each
handing its box's outcomes to the worker, which applies them through the card's door. The real
local tracker and board, the real ledger, the real card record and acceptance store (the SQLite a
local deployment runs), the real events module up to the conversation's enqueue, the real product
module (`send_back`, `accept_change`), the real settling stage of the conversation
(`engine.settle`) for the requester's "still broken" and "it worked", and the real hourly round
(`_offer_the_release_to_the_client`). The product side's answers reach the job through the real
seams (`view.answer_merge_gate`, `view.another_change`, `release.release` → `view.approve_job`),
sealed, on the process's standing loop, with the engine client the product side keeps
(`release._client`) pointed at this file's engine.

DOUBLED, ONLY WHAT LEAVES THE MACHINE OR SPENDS:
  · the box BELOW the activities (`_do_run_job`, `_run_adjust`, `_run_promotion`): each returns the
    result a box returns, its outcomes handed back (`RunResult.handed_back`);
  · the forge: the checks (`read_ci_checks`), its mergeability, the merge itself, the pull
    request's state, and where each pull request's branch points (`demand._forge_state`, the head
    the preview's judgement compares with);
  · the coordinator's narration, the knowledge refresh and the ticket title, which the job asks of
    services this file does not run;
  · the conversation's door (`events._tell`): what the product role tells is recorded, with where;
  · ONE CALL OF THE ENGINE: the time-skipping test server does not implement
    `ListWorkflowExecutions` — verified on this tree with temporalio's own server, which answers
    "Method temporal.api.workflowservice.v1.WorkflowService/ListWorkflowExecutions is
    unimplemented" — so the round's listing of the running jobs (`release.parked_for_release`)
    is handed the job this file started; everything it then asks of the job (`awaiting_approval`,
    `where_to_look`) is the real workflow's answer.

Pointing `release._client` and `standing.from_a_thread` at this engine is real, not doubled: a
client the test's loop made answers a query and a signal from the standing loop's thread (verified
on this tree before this file was written).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from temporalio import activity

import openfactory.product.channel as pc
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.contracts.review import ReviewResult
from openfactory.contracts.run import HandedBack
from openfactory.lifecycle import CardEvent, reading
from openfactory.lifecycle.table import (
    HELD,
    MERGED_FOR_YOU,
    RELEASE_ASK,
    RELEASE_ASK_THEIRS,
    RELEASE_DID_NOT_WORK,
    RELEASE_THEIRS_WORKED,
    RELEASE_WORKED,
    STAGED_FOR_YOU,
    TRIED,
    Column,
    Comment,
    Forget,
    Loops,
    State,
    Tell,
    after,
    allowed,
    consequences,
)
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import (
    JobParams,
    MergeCheckInput,
    TicketRef,
)

LANG, AGENT, ROOM = "en", "Nina", "acme"
ASKER, ADMIN = "ana-asked-77", "po-admin-12"
#: The conversation the requester asked in — where every step of their loop is told.
THEIRS = f"person:{ASKER}"
TITLE = "Export the list"
QA = "https://qa.acme.example"
PR9, PR10 = "https://forge.example/acme/pull/9", "https://forge.example/acme/pull/10"
#: Each pass pushes a new head, and the preview is rebuilt from it: what the requester tried.
HEADS = {"first": "a" * 40, "pass 1": "b" * 40, "pass 2": "c" * 40, "change 2": "d" * 40}
TQ = "test-the-requesters-loop"


# ── the deployment: a registered local project, its stores, and what was told ─────────────────

@pytest.fixture(autouse=True)
def _nothing_staged_nothing_cached():
    from openfactory.preview import demand

    pc._PENDING.clear()
    demand._CACHE.clear()
    yield
    pc._PENDING.clear()
    demand._CACHE.clear()


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a product role, its board `project init` made, the ledger,
    the card record and the acceptances on SQLite, and the operator's two answers for this loop:
    three passes, and the requester's own "it worked" releases (`release_by_requester`)."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import PreviewPolicy, Project, ProviderRef
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
                                               agent_name=AGENT),
                         preview=PreviewPolicy(required=True), adjust_passes=3,
                         release_by_requester=True))
    project = registry.get(ROOM)
    LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
    forget_board()
    yield project
    forget_board()


@pytest.fixture
def told(monkeypatch) -> list[dict]:
    """Every telling the conversation's door took — `{"id", "conversation", "text"}`, in order."""
    from openfactory.product import events

    said: list[dict] = []

    def _tell(project, *, id: str, conversation: str, text: str) -> bool:
        said.append({"id": id, "conversation": conversation, "text": text})
        return True

    monkeypatch.setattr(events, "_tell", _tell)
    return said


@pytest.fixture
def forge(monkeypatch) -> dict[str, str]:
    """Where each pull request's branch points NOW, as the forge answers the preview's judgement."""
    from openfactory.preview import demand

    heads: dict[str, str] = {}

    def _state(project, token, was, *, forge_of=None, heads_of=None):
        return demand.ForgeState(open=tuple(heads), heads=dict(heads), branches={})

    monkeypatch.setattr(demand, "_forge_state", _state)
    return heads


# ── the box below the activities, and the forge ────────────────────────────────────────────────

#: What the box was asked, in order — `("run", change)`, `("adjust", instruction)`, the promotion.
_BOX: list[tuple] = []
#: Pull requests merged on the forge.
_MERGED: list[str] = []


def _once_the_person_s_door_closed(issue: str, event: str, count: int) -> None:
    """A BOX TAKES MINUTES, A DOOR MILLISECONDS — and an instant double would turn that into a
    race nothing real runs: the person's transition (`resumed`, `released`) is recorded right after
    its act sends the job the answer, while the box the job then runs hands its outcome to the door
    only once its pass, its build or its production release is done. So the box's double returns
    once the card's record holds the person's `count`-th `event`, as the real one always would."""
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record

    for _ in range(400):
        rows = record.read(record.keyed_sink(), ROOM, canonical_ref(issue)).rows
        if sum(1 for r in rows if r.event == event) >= count:
            return
        time.sleep(0.025)
    raise AssertionError(f"the box ran before the person's {event} was recorded")


def _approved() -> ReviewResult:
    return ReviewResult(decision="approved", score=90)


def _the_box_opens_a_pull_request(inp, run_id=None, watch=None) -> RunResult:
    """The job's box: a pull request a person decides — the look is all that holds its merge
    (`merge_policy: auto`, `preview.required`) — on the change this run builds (`change`)."""
    _BOX.append(("run", inp.change))
    if inp.change:
        # the new change of the card, asked for at the last gate: after the "not yet"'s pass
        _once_the_person_s_door_closed(inp.issue, "resumed", 3)
    pr = PR10 if inp.change else PR9
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=pr,
                     branch=f"openfactory/{inp.issue}" + (f"-{inp.change}" if inp.change else ""),
                     auto_merge=False, preview_required=True, auto_but_for_the_look=True,
                     review=_approved(), environments=["staging", "production"],
                     handed_back=[HandedBack(state=JobState.PR_OPEN, needs_person=True)])


def _the_box_adjusts(inp, run_id=None) -> RunResult:
    """One pass on the same pull request, read again by the review: the gate re-opens on it."""
    _BOX.append(("adjust", inp.instruction))
    _once_the_person_s_door_closed(inp.issue, "resumed", inp.attempt)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url,
                     code_changed=True, review=_approved(),
                     handed_back=[HandedBack(state=JobState.PR_OPEN, needs_person=True)])


def _the_box_promotes(project_name, issue, phase, extra_env, run_id=None, *, sandbox) -> RunResult:
    """The promotion's box: staging verified and parked at the production gate; production
    released and verified — Done."""
    _BOX.append((phase,))
    if phase == "release":
        _once_the_person_s_door_closed(issue, "released", 1)
    if phase == "staging":
        return RunResult(ticket_id=issue, state=JobState.AWAITING_PROD_APPROVAL,
                         look_stage="staging", look_at=QA,
                         handed_back=[HandedBack(state=JobState.AWAITING_PROD_APPROVAL)])
    return RunResult(ticket_id=issue, state=JobState.DONE,
                     handed_back=[HandedBack(state=JobState.DONE)])


@activity.defn(name="read_ci_checks")
async def _green(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="success")


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
    return "blocked"


@activity.defn(name="check_pr_status")
async def _status(inp: MergeCheckInput) -> str:
    return "merged" if inp.pr_url in _MERGED else "open"


@activity.defn(name="merge_pr_saying_why")
async def _merge(inp: MergeCheckInput) -> str:
    _MERGED.append(inp.pr_url)
    return ""


@activity.defn(name="fetch_ticket_title")
async def _title(inp: TicketRef) -> str:
    return TITLE


@activity.defn(name="notify_coordinator_say")
async def _narrated(inp) -> None:
    return None


@activity.defn(name="refresh_knowledge")
async def _refreshed(inp) -> str:
    return "published"


def _activities() -> list:
    """The real activities that touch the card, and the forge's and the services' doubles."""
    return [acts.run_job, acts.adjust_pr, acts.card_adjusted, acts.tell_the_requester,
            acts.tell_the_requester_it_merged, acts.settle_ticket, acts.mark_needs_action,
            acts.record_outcome, acts.promote_staging, acts.release_prod, acts.verify_gate_seal,
            _green, _blocked, _status, _merge, _title, _narrated, _refreshed]


@pytest.fixture
async def env(monkeypatch):
    """This file's own ephemeral engine (`conftest.OWNS_ITS_ENGINE`), and the product side's client
    pointed at it, on the real standing loop."""
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    from openfactory.product import release
    from openfactory.runtime.temporal import standing

    _BOX.clear(), _MERGED.clear()
    monkeypatch.setattr(acts, "_do_run_job", _the_box_opens_a_pull_request)
    monkeypatch.setattr(acts, "_run_adjust", _the_box_adjusts)
    monkeypatch.setattr(acts, "_run_promotion", _the_box_promotes)
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)

    async def _client():
        return e.client

    monkeypatch.setattr(release, "_client", _client)
    standing._forget_the_standing_loop()
    try:
        yield e
    finally:
        standing._forget_the_standing_loop()
        await e.shutdown()


class _Listed:
    """The engine's client as the hourly round reaches it — every call the real client's, but the
    one the time-skipping server does not implement: listing the running jobs, handed the job this
    file started (see the module's docstring)."""

    def __init__(self, client, job_id: str) -> None:
        self._client, self._job = client, job_id

    async def list_workflows(self, _query):
        described = await self._client.get_workflow_handle(self._job).describe()
        yield SimpleNamespace(id=self._job, run_id=described.run_id)

    def get_workflow_handle(self, *args, **kwargs):
        return self._client.get_workflow_handle(*args, **kwargs)


# ── what each consumer says, read back as a second process would ───────────────────────────────

def _history(project, ref: str):
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record

    return record.read(record.keyed_sink(), project.name, canonical_ref(ref))


def _rows(project, ref: str) -> list[tuple[str, str, str]]:
    return [(r.event, r.before, r.after) for r in _history(project, ref).rows]


def _column(project, ref: str) -> str:
    """Where the card is on its board: the column of an open card, `done` for one closed there."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key
    from openfactory.adapters.board_db import connect
    from openfactory.contracts.refs import canonical_ref

    board = build_board(project)
    column = (board.columns() or {}).get(canonical_ref(ref), "")
    if column:
        return stage_key(board, column)
    with connect() as conn:
        row = conn.execute("SELECT state, closed_reason FROM cards WHERE ref = ?",
                           (int(canonical_ref(ref)),)).fetchone()
    return "done" if row is not None and tuple(row) == ("closed", "completed") else ""


def _said_on_the_card(project, ref: str) -> list[str]:
    from openfactory.adapters.tracker.registry import build_tracker

    return [c.body for c in build_tracker(project).comments(ref) or []]


def _releases(project, ref: str) -> dict[tuple[str, str], str]:
    """Every release question about the card, by `(where it was asked, run)`: open, or its outcome."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import ACCEPTANCE, fold
    from openfactory.product import followup

    return {(x.about, str((x.context or {}).get("run") or "")): (x.outcome or x.state)
            for x in fold(loop_store.read(project.name))
            if x.kind == ACCEPTANCE and followup.is_release(x) == ref}


def _new(told: list[dict], since: int) -> list[tuple[str, str]]:
    return [(t["conversation"], t["text"]) for t in told[since:]]


async def _until(check, *, what: str):
    for _ in range(600):
        got = await check()
        if got:
            return got
        await asyncio.sleep(0.05)
    raise AssertionError(f"never saw: {what}")


async def _at_the_merge_gate(h, *, pr: str, left: int):
    """The job at its merge gate on `pr`, asking a person, with `left` passes left — never a gate a
    pass is rewriting, nor the one it published before the last answer."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    async def look():
        gate = await h.query(JobWorkflow.awaiting_merge)
        return gate if (gate and not gate.get("working") and gate.get("pr_url") == pr
                        and "auto_but_for_the_look" in gate
                        and gate.get("adjusts_left") == left) else None

    return await _until(look, what=f"the merge gate on {pr} with {left} pass(es) left")


async def _at_the_production_gate(h):
    from openfactory.runtime.temporal.workflow import JobWorkflow

    async def look():
        return await h.query(JobWorkflow.awaiting_approval)

    return await _until(look, what="the job parked at its production gate")


def _tried(ref: str, pr: str, head: str) -> None:
    """The card's preview, up and built from `head` for `pr` — what the requester tries."""
    from openfactory import preview

    assert preview.record(preview.Preview(
        project=ROOM, unit=ref, cards=(ref,), state=preview.LIVE, services={"web": 3000},
        heads={pr: head}, pr_urls=(pr,), expires_at=int(time.time()) + 3600))


def _module(project):
    from openfactory.product.module import ProductModule

    return ProductModule(project, via="panel")


def _settled(project, text: str):
    """What the requester writes in their conversation, read by its real settling stage."""
    from openfactory.product import engine as turn

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(turn, "find_waiting", lambda *a, **k: (None, None))
        return turn.settle(project, text=text, user=ASKER, thread=THEIRS,
                           module=_module(project))


def _filed(project) -> str:
    """The card the product role filed for ASKER from what they asked in THEIRS — through its door,
    with the promise its filing makes (`_track_ticket`)."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.product.authoring import ticket_body

    tracker, board = build_tracker(project), build_board(project)
    ref = tracker.create_ticket(title=TITLE, requester=ASKER, body=ticket_body(
        described="an export button on the list", reported_by=ASKER, source="chat"))
    module = _module(project)
    placed, _ = module._filed_through_the_door(
        ref, by=ASKER, tracker=tracker, board=board,
        owed=module._track_ticket(ref, title=TITLE, conversation=THEIRS, requester=ASKER))
    assert placed, "the card was not placed where it is filed"
    return ref.lstrip("#")


# ── the scenario ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.owns_its_engine
async def test_a_card_walks_the_requesters_whole_loop_through_its_door(
        env, deployment, told, forge, monkeypatch):
    from temporalio.worker import Worker

    from openfactory.lifecycle import converge, transition
    from openfactory.product import events, followup, voice
    from openfactory.runtime.temporal import view as tv
    from openfactory.runtime.temporal.workflow import JobWorkflow

    project = deployment
    # ── request: filed for them, from their conversation ──
    ref = _filed(project)
    # read the moment after it was written: on no column yet, and the filing places it
    assert _rows(project, ref) == [("filed", "", "backlog")]
    assert _column(project, ref) == "backlog" and told == []
    # ── promoted: a person queues it, the one gesture that spends ──
    assert transition(project, ref, CardEvent.PROMOTED, by=ADMIN).ok
    assert _rows(project, ref)[-1] == ("promoted", "backlog", "todo")
    assert _column(project, ref) == "todo" and told == []

    title = events._title_of(project, ref)
    assert title == TITLE

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await env.client.start_workflow(
            JobWorkflow.run, JobParams(project=ROOM, issue=ref, merge_deadline_days=3650,
                                       approval_deadline_days=3650, adjust_passes=3),
            id=tv.job_id(ROOM, ref), task_queue=TQ, result_type=RunResult)

        # ── preview ready: PR 9, the look all that holds its merge ──
        gate = await _at_the_merge_gate(h, pr=PR9, left=3)
        assert gate["auto_but_for_the_look"] is True, gate
        assert _rows(project, ref)[-1][:1] == ("pr_opened",)
        assert _rows(project, ref)[-1][2] == "waiting_on_a_person"
        assert _column(project, ref) == "needs_action"
        assert _new(told, 0) == [(THEIRS, _ready(project, ref, title))]
        assert reading.step(_history(project, ref)).now == reading.PREVIEW_READY

        # ── adjust × 2: the requester sends it back from their own control, twice ──
        for number, (words, bar) in enumerate([
                ("Put the export button on the toolbar.", ["The export button is on the toolbar"]),
                ("Name the file after the list.", ["The export button is on the toolbar",
                                                   "The file is named after the list"])], 1):
            before, said = len(_history(project, ref).rows), len(told)
            sent = await asyncio.to_thread(_module(project).send_back, ref, actor=ASKER,
                                           instruction=words, criteria=bar)
            assert sent.ok, sent.detail
            resumed = _history(project, ref).rows[before]
            assert (resumed.event, resumed.after) == ("resumed", "running"), resumed
            assert resumed.by == ASKER and resumed.facts.get("gate") == "merge"
            await _at_the_merge_gate(h, pr=PR9, left=3 - number)
            assert [r.event for r in _history(project, ref).rows[before:]] == [
                "resumed", "pr_opened", "adjusted"]
            assert _rows(project, ref)[-1][2] == "waiting_on_a_person"
            assert _column(project, ref) == "needs_action"
            [(where, text)] = _new(told, said)
            assert where == THEIRS, where
            assert text == voice.card_moved("pass_ready", ref=ref, title=title, language=LANG,
                                            agent_name=AGENT, pass_number=number,
                                            link=events._where_to_try(project, ref)), text
            assert all(f"- {c}" in _body(project, ref) or c in _body(project, ref)
                       for c in bar), "the pass did not read the bar the person corrected"
            assert reading.step(_history(project, ref)).now == reading.PREVIEW_READY

        # ── accepted: "that's it", against the head they tried in the preview ──
        _tried(ref, PR9, HEADS["pass 2"])
        forge[PR9] = HEADS["pass 2"]
        before, said = len(_history(project, ref).rows), len(told)
        yes = await asyncio.to_thread(_module(project).accept_change, ref, actor=ASKER,
                                      where=THEIRS)
        assert yes.ok and yes.merging, yes.detail
        accepted = _history(project, ref).rows[before]
        assert (accepted.event, accepted.before, accepted.after) == (
            "accepted", "waiting_on_a_person", "waiting_on_a_person")
        assert accepted.facts.get("head") == HEADS["pass 2"]
        assert any("accepted it" in c for c in _said_on_the_card(project, ref))

        # ── auto-merge: the yes gave the gate its merge; the job lands it and parks at staging ──
        await _at_the_production_gate(h)
        assert _MERGED == [PR9]
        assert [r.event for r in _history(project, ref).rows[before:]] == [
            "accepted", "merged", "staged"]
        merged, staged = _history(project, ref).rows[-2:]
        assert (merged.after, staged.before, staged.after) == ("merged", "merged", "staged")
        assert staged.facts.get("where") == QA and staged.facts.get("stage") == "staging"
        assert _column(project, ref) == "needs_action"
        assert _new(told, said) == [(THEIRS, voice.merged_for_you(
            ref=ref, title=title, stages_follow=True, language=LANG, agent_name=AGENT))]
        assert reading.step(_history(project, ref)).now == reading.IN_STAGING

        # ── in staging: the round asks the room, then tells them where they asked ──
        run1 = (await h.describe()).run_id
        said = len(told)
        asked = await _the_round(project, env, ref)
        assert asked == "release-asked:1"
        assert _rows(project, ref)[-1] == ("staged", "staged", "staged")
        assert _new(told, said) == [
            (events.room_of(project), followup.release_question(
                requirement="", where=QA, agent_name=AGENT, language=LANG)),
            (THEIRS, voice.staged_for_you(ref=ref, title=title, where=QA, language=LANG,
                                          agent_name=AGENT))]
        assert _releases(project, ref) == {(events.room_of(project), run1): "open",
                                           (THEIRS, run1): "open"}
        assert _column(project, ref) == "needs_action"
        # …and asked once: the next round finds both copies open and asks nothing
        said = len(told)
        assert await _the_round(project, env, ref) == "release-asked:0"
        assert _new(told, said) == [] and _rows(project, ref)[-1] == ("staged", "staged", "staged")

        # ── staging "not yet": in their conversation, then the pass it becomes ──
        said = len(told)
        no = await asyncio.to_thread(_settled, project, "still broken: the date column is missing")
        assert no.not_yet == ref, no
        assert no.reply == f"{AGENT}: " + voice.engine_said("release_declined", language=LANG)
        assert _rows(project, ref)[-1] == ("stage_rejected", "staged", "staged")
        rejected = _history(project, ref).rows[-1]
        assert rejected.by == ASKER and "date column" in rejected.why, rejected
        assert _column(project, ref) == "needs_action" and _new(told, said) == []
        assert _releases(project, ref) == {(events.room_of(project), run1): "did-not-work",
                                           (THEIRS, run1): "did-not-work"}
        assert any("Not yet" in c for c in _said_on_the_card(project, ref))
        assert reading.step(_history(project, ref)).now == reading.ADJUSTING
        sent = await asyncio.to_thread(
            _module(project).send_back, ref, actor=ASKER,
            instruction="Add the date column to the export.",
            criteria=["The export button is on the toolbar", "The file is named after the list",
                      "The export has a date column"])
        assert sent.ok and sent.merged, sent.detail
        assert _rows(project, ref)[-1] == ("resumed", "staged", "running")

        # ── adjust: a new change of the card, PR 10, ready for them again ──
        await _until(lambda: _a(any(r.event == "pr_opened" and r.facts.get("pr_url") == PR10
                                    for r in _history(project, ref).rows)),
                     what="the new change's pull request")
        await _at_the_merge_gate(h, pr=PR10, left=0)
        assert _BOX[-1] == ("run", 1), _BOX
        assert _rows(project, ref)[-1] == ("pr_opened", "waiting_on_a_person",
                                           "waiting_on_a_person")
        assert _column(project, ref) == "needs_action"
        assert _new(told, said) == [(THEIRS, _ready(project, ref, title))]
        assert reading.step(_history(project, ref)).now == reading.PREVIEW_READY

        # ── staging approved: accepted, merged, staged again in a new run, told again ──
        _tried(ref, PR10, HEADS["change 2"])
        forge[PR10] = HEADS["change 2"]
        said = len(told)
        yes = await asyncio.to_thread(_module(project).accept_change, ref, actor=ASKER,
                                      where=THEIRS)
        assert yes.ok and yes.merging, yes.detail
        await _at_the_production_gate(h)
        assert _MERGED == [PR9, PR10]
        assert [r.event for r in _history(project, ref).rows[-3:]] == [
            "accepted", "merged", "staged"]
        assert _column(project, ref) == "needs_action"
        run2 = (await h.describe()).run_id
        assert run2 != run1, "the new change is not a new run of the card's job"
        assert await _the_round(project, env, ref) == "release-asked:1"
        assert _rows(project, ref)[-1] == ("staged", "staged", "staged")
        assert _releases(project, ref)[(THEIRS, run2)] == "open"
        assert _new(told, said) == [
            (THEIRS, voice.merged_for_you(ref=ref, title=title, stages_follow=True,
                                          language=LANG, agent_name=AGENT)),
            (events.room_of(project), followup.release_question(
                requirement="", where=QA, agent_name=AGENT, language=LANG)),
            (THEIRS, voice.staged_for_you(ref=ref, title=title, where=QA, language=LANG,
                                          agent_name=AGENT))]

        # ── production: their own "it worked" releases it (`release_by_requester`) ──
        said = len(told)
        worked = await asyncio.to_thread(_settled, project, "it worked")
        assert worked.reply == f"{AGENT}: " + voice.engine_said("releasing", language=LANG)
        result = await h.result()

    assert result.state is JobState.DONE
    assert _releases(project, ref)[(THEIRS, run2)] == "worked"
    assert _releases(project, ref)[(events.room_of(project), run2)] == "worked"
    released, delivered = _history(project, ref).rows[-2:]
    assert (released.event, released.before, released.after) == ("released", "staged", "running")
    assert released.by == ASKER
    assert (delivered.event, delivered.after) == ("delivered", "delivered")
    assert _column(project, ref) == "done"
    # ── delivered: announced in their conversation, with "did it work?", once ──
    loop = next(x for x in _owed(project) if x.subject == f"cartao-{ref}")
    announced = (followup.delivered_text(loop, agent_name=AGENT, language=LANG)
                 + followup.acceptance_question(loop, agent_name=AGENT, language=LANG))
    assert _new(told, said) == [(THEIRS, announced)]
    assert sum(1 for t in told if t["text"] == announced) == 1

    # ── the reading, the record, the converge ──
    history = _history(project, ref)
    walked = reading.step(history)
    assert walked.now == reading.DELIVERED
    assert set(walked.walked) == set(reading.STEPS), walked.walked
    assert [r.seq for r in history.rows] == list(range(1, len(history.rows) + 1))
    for row in history.rows:
        outcomes = [row.outcome(i) for i in range(len(row.effects))]
        assert all(outcomes), f"{row.event}: an effect with no outcome — {row.effects}"
        assert not [o for o in outcomes if o.startswith("failed")], (row.event, outcomes)
    assert converge(project) == [], "the hourly converge found something left to apply"


async def _a(value):
    return value


def _ready(project, ref: str, title: str) -> str:
    """What the requester hears when a pull request of the card is theirs to try (#401): the
    voice's sentence, with what the events module reads at that moment."""
    from openfactory.preview.live import link_for
    from openfactory.product import events, voice

    return voice.ready_for_you(ref=ref, title=title, card_url=events._card_url(project, ref),
                               review="approved", preview=False,
                               preview_url=link_for(project, ref), language=LANG,
                               agent_name=AGENT, preview_starts_itself=False)


def _body(project, ref: str) -> str:
    from openfactory.adapters.tracker.registry import build_tracker

    return str(getattr(build_tracker(project).get_ticket(ref), "raw", "") or "")


def _owed(project) -> list:
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, fold

    return [x for x in fold(loop_store.read(project.name)) if x.kind == DELIVERY]


async def _the_round(project, env, ref: str) -> str:
    """The tech-lead's hourly round asking about what is parked — the real activity, on the real
    job (its listing aside, `_Listed`)."""
    from temporalio.testing import ActivityEnvironment

    from openfactory.runtime.temporal import view as tv

    return await ActivityEnvironment().run(acts._offer_the_release_to_the_client, project,
                                           _Listed(env.client, tv.job_id(ROOM, ref)))


# ── the rows the loop walks, by name (ADR-0055 D1 as amended 2026-10-05) ───────────────────────

_LOOP = (CardEvent.RESUMED, CardEvent.ACCEPTED, CardEvent.STAGED, CardEvent.STAGE_REJECTED,
         CardEvent.RELEASED)


def test_the_loop_past_the_pull_request_happens_only_on_a_card_the_factory_holds():
    """Running, waiting on a person, merged, at a stage: the engine says which job waits on what,
    and the table refuses what no gate could be asked about — and `delivered` comes from a merged or
    staged card too, the last declared stage's (#448 slice 5)."""
    assert HELD == frozenset({State.RUNNING, State.WAITING_ON_A_PERSON, State.MERGED,
                              State.STAGED})
    for event in (*_LOOP, CardEvent.DELIVERED):
        for state in HELD:
            assert allowed(state, event) is None, (event, state)
        for state in (State.BACKLOG, State.TODO, State.DELIVERED, State.CLOSED, State.REMOVED):
            assert allowed(state, event, open_card=state not in (State.CLOSED, State.REMOVED)) \
                is not None, (event, state)
        assert allowed(None, event) is None, f"{event}: a card no board places is refused"


def test_each_step_of_the_loop_does_what_its_row_says():
    # a pass sent back: the act corrected the bar and sent it; the pass's marks are its column
    assert consequences(CardEvent.RESUMED, {"note": ""}) == (Forget(),)
    assert after(CardEvent.RESUMED, {}) is State.RUNNING
    # "that's it" at the merge gate: the note on the card
    assert consequences(CardEvent.ACCEPTED, {"gate": "merge", "note": "accepted"}) == (
        Comment(), Forget())
    # …at the last gate, where their word does not release: their copy closed, the room told
    assert consequences(CardEvent.ACCEPTED, {"gate": "last", "note": ""}) == (
        Loops(RELEASE_THEIRS_WORKED), Tell(TRIED), Forget())
    # …and a yes that may release, given when the job was gone (#273): every copy, nobody told
    assert consequences(CardEvent.ACCEPTED, {"gate": "last", "unreleased": "gone",
                                             "note": ""}) == (Loops(RELEASE_WORKED), Forget())
    assert after(CardEvent.ACCEPTED, {"before": "staged"}) is State.STAGED
    assert after(CardEvent.ACCEPTED, {"before": "waiting_on_a_person"}) is \
        State.WAITING_ON_A_PERSON
    # the merge, by the box or the settle, and by the job's telling — which writes no column
    assert consequences(CardEvent.MERGED, {"note": ""}) == (Column("merged"), Forget())
    assert consequences(CardEvent.MERGED, {"pr_url": PR9, "stages_follow": False,
                                           "note": ""}) == (Tell(MERGED_FOR_YOU), Forget())
    assert consequences(CardEvent.MERGED, {"stages_follow": True, "note": ""}) == (
        Column("merged"), Forget()), "a telling with no pull request tells nothing"
    # the production gate, handed back by the box; the round's asking, once the room was asked
    assert consequences(CardEvent.STAGED, {"note": ""}) == (Column("awaiting_prod_approval"),
                                                            Forget())
    assert consequences(CardEvent.STAGED, {"asked_at": "t", "note": ""}) == (
        Loops(RELEASE_ASK), Tell(STAGED_FOR_YOU), Loops(RELEASE_ASK_THEIRS))
    assert after(CardEvent.STAGED, {}) is State.STAGED
    # "not yet" at the stage; the release
    assert consequences(CardEvent.STAGE_REJECTED, {"note": "not yet"}) == (
        Comment(), Loops(RELEASE_DID_NOT_WORK), Forget())
    assert after(CardEvent.STAGE_REJECTED, {}) is State.STAGED
    assert consequences(CardEvent.RELEASED, {"note": ""}) == (Loops(RELEASE_WORKED), Forget())
    assert after(CardEvent.RELEASED, {}) is State.RUNNING
    # a production gate is a stage the box hands back, never a park
    from openfactory.lifecycle.handed_back import OUTCOMES

    assert OUTCOMES[JobState.AWAITING_PROD_APPROVAL] is CardEvent.STAGED


class _Ports:
    """A double of every port the door touches, keeping what each effect was handed."""

    name = "acme"

    def __init__(self, state: State, sink=None) -> None:
        from openfactory.lifecycle.ports import Seen

        self.seen_as = Seen(state=state, title=TITLE)
        self.sink_ = sink
        self.calls: list[tuple] = []

    def sink(self):
        from openfactory.lifecycle import record

        if self.sink_ is None:
            raise record.Unrecordable("this double keeps no record")
        return self.sink_

    def seen(self, card):
        return self.seen_as

    def asked_in(self, card):
        return THEIRS

    def column(self, card, key, **kw):
        self.calls.append(("column", key))
        return "moved"

    def comment(self, card, text):
        self.calls.append(("comment", text))
        return "said"

    def loops(self, card, action, **kw):
        self.calls.append(("loops", action, kw))
        return "done"

    def tell(self, card, *, notice, **kw):
        self.calls.append(("tell", notice, kw))
        return "told"

    def forget(self):
        self.calls.append(("forget",))
        return "forgotten"


def _through(event, ports, **facts):
    from openfactory.lifecycle import transition

    return transition(SimpleNamespace(name="acme", language="en"), "#12", event, by=ASKER,
                      facts={"note": "", **facts}, ports=ports)


def test_the_door_reads_a_merged_or_staged_card_from_its_record_for_the_loop_alone():
    """No column holds merged or staged: a production gate is Needs Action like any park. For the
    loop's events the door reads the record's latest move instead (ADR-0055 D2 amended 2026-10-05);
    with no record the column stands, and the other events are judged as they were."""
    from openfactory.observability.metrics import InMemoryMetricsSink

    sink = InMemoryMetricsSink()
    ports = _Ports(State.WAITING_ON_A_PERSON, sink)
    staged = _through(CardEvent.STAGED, ports)
    assert (staged.before, staged.after) == (State.WAITING_ON_A_PERSON, State.STAGED)
    for event in _LOOP:
        moved = _through(event, ports, gate="last")
        assert moved.before is State.STAGED, (event, moved.before)
        if moved.after is State.RUNNING:          # a pass, or a release: back at the stage
            _through(CardEvent.STAGED, ports)
    # a park is judged by its column: the record's word is the loop's alone
    parked = _through(CardEvent.PARKED, ports)
    assert parked.before is State.WAITING_ON_A_PERSON, parked
    # no record: the column stands
    unrecorded = _through(CardEvent.RELEASED, _Ports(State.WAITING_ON_A_PERSON))
    assert unrecorded.before is State.WAITING_ON_A_PERSON and not unrecorded.recorded
    # only merged or staged is the record's to say: a pass it holds running, the column judges
    sink = InMemoryMetricsSink()
    ports = _Ports(State.WAITING_ON_A_PERSON, sink)
    _through(CardEvent.RESUMED, ports, gate="merge")
    assert _through(CardEvent.ACCEPTED, ports, gate="merge").before is State.WAITING_ON_A_PERSON
    # and only a column that cannot tell is refined: a card a person put back in the backlog is
    # in the backlog, whatever stage the record last saw it at
    _through(CardEvent.STAGED, ports)
    ports.seen_as = replace(ports.seen_as, state=State.BACKLOG)
    refused = _through(CardEvent.RELEASED, ports)
    assert refused.refused and refused.before is State.BACKLOG, refused


def test_the_tellings_and_the_question_carry_what_the_round_and_the_job_know():
    """The executor hands each port what the transition knew: whether stages follow, where to look
    and which run — and, to the release question, when it was asked and in which room."""
    ports = _Ports(State.RUNNING)
    _through(CardEvent.MERGED, ports, pr_url=PR9, stages_follow=True)
    [(_, notice, said)] = [c for c in ports.calls if c[0] == "tell"]
    assert (notice, said["stages_follow"], said["pr_url"]) == (MERGED_FOR_YOU, True, PR9)

    ports = _Ports(State.STAGED)
    _through(CardEvent.STAGED, ports, asked_at="2026-10-05T10:00:00+00:00", run="run-1",
             where=QA, requirement="7", room=ROOM)
    asked = [c for c in ports.calls if c[0] in ("loops", "tell")]
    assert [c[1] for c in asked] == [RELEASE_ASK, STAGED_FOR_YOU, RELEASE_ASK_THEIRS]
    assert asked[0][2]["release"] == {"asked_at": "2026-10-05T10:00:00+00:00", "run": "run-1",
                                      "where": QA, "requirement": "7", "room": ROOM}
    assert (asked[1][2]["where"], asked[1][2]["run"]) == (QA, "run-1")

    ports = _Ports(State.STAGED)
    _through(CardEvent.ACCEPTED, ports, gate="last", run="run-1", where=QA, who="Ana")
    [(_, notice, said)] = [c for c in ports.calls if c[0] == "tell"]
    assert (notice, said["who"], said["run"]) == (TRIED, "Ana", "run-1")


def test_the_requesters_reading_is_read_from_the_record_alone():
    """Seven steps, and a card that left the loop is at none of them (ADR-0055 D12)."""
    from openfactory.lifecycle.record import History, Row

    def history(*events: tuple[str, dict]) -> History:
        return History(rows=tuple(Row(card="12", seq=n, event_id=f"e{n}", event=e, by="x",
                                      facts=f) for n, (e, f) in enumerate(events, 1)))

    walked = reading.step(history(
        ("filed", {}), ("promoted", {}), ("pr_opened", {"needs_person": True}),
        ("resumed", {}), ("pr_opened", {"needs_person": True}), ("adjusted", {}),
        ("accepted", {}), ("merged", {}), ("staged", {}), ("staged", {"asked_at": "t"}),
        ("stage_rejected", {}), ("resumed", {}), ("pr_opened", {"needs_person": True}),
        ("released", {}), ("delivered", {})))
    assert walked.now == reading.DELIVERED
    assert walked.walked == (reading.PREVIEW_READY, reading.ADJUSTING, reading.PREVIEW_READY,
                             reading.ACCEPTED, reading.MERGED, reading.IN_STAGING,
                             reading.ADJUSTING, reading.PREVIEW_READY, reading.RELEASED,
                             reading.DELIVERED)
    assert set(walked.walked) == set(reading.STEPS)
    # an armed merge waits on a build: nobody's preview is ready
    assert reading.step(history(("pr_opened", {"needs_person": False}))).now == ""
    # a card that left the loop is at no step; a promise or an edit leaves it where it was
    assert reading.step(history(("pr_opened", {"needs_person": True}),
                                ("discarded", {}))).now == ""
    assert reading.step(history(("merged", {}), ("promised", {}), ("edited", {}))).now == \
        reading.MERGED
    assert reading.step(history(("closed", {"delivered": True}))).now == reading.DELIVERED
    assert reading.STEPS == ("preview ready", "adjusting", "accepted", "merged", "in staging",
                             "released", "delivered")


# ── the release question through the card's door, on the real ledger (#448 slices 4 and 6) ─────

def _a_card_asked_for_in_their_conversation(project) -> str:
    ref = _filed(project)
    assert any(x.subject == f"cartao-{ref}" for x in _owed(project)), "nothing was owed to them"
    return ref


def test_the_release_question_is_asked_once_per_asking_and_theirs_once_per_run(deployment, told):
    """The round's asking opens the room's copy once — a sweep applying it again opens nothing —
    and the requester's only once they were told, and once per run: a later asking of the room in
    the same run never asks them again."""
    from openfactory.lifecycle import loops
    from openfactory.product import events

    ref = _a_card_asked_for_in_their_conversation(deployment)
    room = events.room_of(deployment)
    asked = {"asked_at": "2026-10-05T10:00:00+00:00", "run": "run-1", "where": QA, "room": room}
    assert loops.release_asked(deployment, ref, asked, theirs=False) == "asked the room"
    assert loops.release_asked(deployment, ref, asked, theirs=False) == \
        "the room was asked already"
    assert loops.release_asked(deployment, ref, asked, theirs=True) == \
        "not asked: they were not told it is theirs to try"
    assert events.to_try_at_the_stage(deployment, card=ref, where=QA, run="run-1") == "told"
    assert loops.release_asked(deployment, ref, asked, theirs=True) == "asked them"
    assert _releases(deployment, ref) == {(room, "run-1"): "open", (THEIRS, "run-1"): "open"}
    assert loops.release_answered(deployment, ref, "did-not-work") == "2 closed as did-not-work"
    again = {**asked, "asked_at": "2026-10-05T11:00:00+00:00"}
    assert loops.release_asked(deployment, ref, again, theirs=False) == "asked the room"
    assert loops.release_asked(deployment, ref, again, theirs=True) == \
        "they were asked already for this run"
    assert loops.release_asked(deployment, ref, {**again, "run": "run-2"}, theirs=True) == \
        "not asked: they were not told it is theirs to try"


def test_their_yes_closes_their_copy_and_leaves_the_room_s(deployment, told):
    from openfactory.lifecycle import loops
    from openfactory.product import events

    ref = _a_card_asked_for_in_their_conversation(deployment)
    room = events.room_of(deployment)
    asked = {"asked_at": "2026-10-05T10:00:00+00:00", "run": "run-1", "where": QA, "room": room}
    events.to_try_at_the_stage(deployment, card=ref, where=QA, run="run-1")
    loops.release_asked(deployment, ref, asked, theirs=False)
    loops.release_asked(deployment, ref, asked, theirs=True)

    assert loops.release_answered(deployment, ref, "theirs-worked") == "1 closed as worked"
    assert _releases(deployment, ref) == {(room, "run-1"): "open", (THEIRS, "run-1"): "worked"}
    assert loops.release_answered(deployment, ref, "worked") == "1 closed as worked"
    assert loops.release_answered(deployment, ref, "worked") == \
        "no question about its release was open"


def test_a_correction_before_pickup_is_edited_through_the_card_s_door(deployment, told):
    """The text written in the transition's act, the note its comment — the door's (D6)."""
    ref = _filed(deployment)

    fixed = _module(deployment).correct_card(ref, actor=ADMIN, text="a weekly export")

    assert fixed.ok, fixed.detail
    edited = _history(deployment, ref).rows[-1]
    assert (edited.event, edited.before, edited.after) == ("edited", "backlog", "backlog")
    assert "a weekly export" in _body(deployment, ref)
    assert edited.facts["note"] in _said_on_the_card(deployment, ref)


def _parked_at_the_last_gate(project, monkeypatch) -> tuple[str, list]:
    """A card the factory holds at its production gate, asked about in the room, and the engine's
    client the release rows reach — every signal recorded, the gate always parked."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.lifecycle import loops
    from openfactory.product import events

    ref = _filed(project)
    build_tracker(project).set_state(ref, JobState.AWAITING_PROD_APPROVAL)
    loops.release_asked(project, ref, {"asked_at": "2026-10-05T10:00:00+00:00", "run": "run-1",
                                       "where": QA, "room": events.room_of(project)},
                        theirs=False)
    signals: list = []

    async def _approve_job(client, name, issue, **kw):
        signals.append((name, str(issue), kw.get("approver")))

    async def _connect():
        return object()

    monkeypatch.setattr("openfactory.runtime.temporal.view.connect", _connect)
    monkeypatch.setattr("openfactory.runtime.temporal.view.approve_job", _approve_job)
    return ref, signals


async def test_an_operators_approval_is_released_through_the_card_s_door(deployment, told,
                                                                          monkeypatch):
    """`approve_prod`, the floor's row: the signal is `released`'s act, and the question the room
    was asked closes as worked — a release nobody answered there is not left to be chased."""
    from openfactory import actions
    from openfactory.actions import catalog
    from openfactory.product import events

    ref, signals = _parked_at_the_last_gate(deployment, monkeypatch)
    monkeypatch.setattr(catalog, "_prod_allowlist", lambda project: ["alice"])
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **kw: True)

    out = await actions.perform("approve_prod", by=actions.SYSTEM, project=ROOM, issue=ref,
                                version="1.2.0", approver="alice", password="s3cret")

    assert out.ok, out.message
    assert signals == [(ROOM, ref, "alice")]
    released = _history(deployment, ref).rows[-1]
    assert (released.event, released.after) == ("released", "running"), released
    assert _releases(deployment, ref) == {(events.room_of(deployment), "run-1"): "worked"}


async def test_a_product_admins_release_is_released_through_the_card_s_door(deployment, told,
                                                                            monkeypatch):
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor
    from openfactory.product import events, release

    ref, _ = _parked_at_the_last_gate(deployment, monkeypatch)
    calls: list = []

    def _release(project, issue, *, approver, comment=""):
        calls.append((str(issue), approver))
        return True, ""

    monkeypatch.setattr(release, "release", _release)

    out = await catalog._product_release(project=ROOM, issue=ref,
                                         by=Actor(id=ADMIN, display="PO", admin=False),
                                         yes=True)

    assert out.ok, out.message
    assert calls == [(ref, ADMIN)]
    assert _history(deployment, ref).rows[-1].event == "released"
    assert _releases(deployment, ref) == {(events.room_of(deployment), "run-1"): "worked"}

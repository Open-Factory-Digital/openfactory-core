"""The box hands its outcomes back, and the worker applies them through the card's door
(ADR-0055 D7, #414).

THE DEFECT. The box — the job's runner, on a remote machine, in a worker thread or under
`openfactory run` — wrote every state it reached on the card itself: the pull request, the merge,
the delivery, the refusal, the park. Those writes reached the board and nothing else: no record of
the card's life held them, the role's snapshot did not forget, and the door could not be the one
writer of a transition's comment while the box wrote its own. The box cannot call the door — it
may run with no ledger, no conversation and no store of the record.

WHAT IS HELD HERE:

  · the box writes only its PROGRESS MARKS on the card, and hands every OUTCOME back on its result,
    in the order it reached them — the job's runner and the promotion's alike;
  · the worker applies each through the door, on the real local rows and the real card record:
    the column it always reached, one row in the record, no comment said twice (the box said it
    as it reached it), and a retried activity answered from that row;
  · the park the worker applied is the one the workflow's reconcile finds — one park, one row;
  · every activity that runs a box applies what it handed back, and so does the attended driver;
  · a result from a box before this — no `handed_back` — parses, and the worker applies nothing.

The guard's half — a progress mark admitted by rule, an outcome written from the box found — is in
`test_the_card_lifecycle_has_one_door.py`, beside the rest of the walk.

AND THE PROMISE A FILING OPENS (the other half of #414's second part): a reported defect, or a card
somebody asked for in a conversation, is owed its delivery, and the door's `filed` opens it —
once per card, recorded with the filing. A requirement's delivery, which spans several cards and
some the breakdown reused, goes through each of its cards' doors as `promised` (ADR-0055 amended
2026-10-04) — `test_the_life_of_a_card.py` drives it.
"""

from __future__ import annotations

import asyncio

import pytest
import test_walking_skeleton as spine
from temporalio.testing import ActivityEnvironment

from openfactory.contracts import AcceptanceCriterion, Environment, JobState, Manifest, Ticket
from openfactory.contracts.run import HandedBack, RunResult
from openfactory.contracts.state import PROGRESS_MARKS
from openfactory.lifecycle.handed_back import BY, recorded_park
from openfactory.runtime.temporal import activities

#: the real-git harness — a bare origin and a repo with one commit — borrowed rather than rebuilt
repo = spine.repo


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project, the board `project init` makes, and the SQLite store a
    deployment runs — the card's record lives in it."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.board import forget_board
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path), language="en",
                         tracker=ProviderRef(kind="local", repo="acme", options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs",
                                               admins=["ana-asked-77"])))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    forget_board()
    yield project
    forget_board()


def _tracker(project):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(project)


def _column(project, ref: str) -> str:
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key
    from openfactory.contracts.refs import canonical_ref

    board = build_board(project)
    return stage_key(board, (board.columns() or {}).get(canonical_ref(ref), ""))


def _said_on_the_card(project, ref: str) -> list[str]:
    return [c.body for c in _tracker(project).comments(ref) or []]


def _history(project, ref: str):
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record

    return record.read(record.keyed_sink(), project.name, canonical_ref(ref)).rows


def _a_card_the_box_is_working(project) -> str:
    """A card queued, picked up, and at the box's last progress mark — written by the box on the
    real row, as it still writes it."""
    from openfactory.adapters.board import build_board

    tracker = _tracker(project)
    ref = tracker.create_ticket(title="Export the report", body="## Objective\n\nExport it\n")
    build_board(project).set_column(issue=ref, issue_url="", name="TO-DO")
    tracker.set_state(ref, JobState.IMPLEMENTING)
    assert _column(project, ref) == "in_progress"
    return ref.lstrip("#")


def _handed(*back: HandedBack, state: JobState | None = None) -> RunResult:
    return RunResult(ticket_id="#1", state=state or back[-1].state, handed_back=list(back))


# ── the box: progress marks written, outcomes handed back ────────────────────────────────────

class _Recorded:
    def __init__(self):
        self.states: list[tuple[JobState, object]] = []

    def set_state(self, ref, state, reason=None, *, needs_person=None):
        self.states.append((state, needs_person))

    def remove_label(self, ref, label):
        pass

    def comment(self, ref, body):
        pass


def test_the_box_writes_its_progress_marks_and_hands_every_outcome_back():
    from openfactory.orchestrator.machine import JobRunner

    box = JobRunner.__new__(JobRunner)
    box.tracker = _Recorded()
    box._emit = lambda *a, **k: None
    ticket = Ticket(id="#7", title="t", objective="o", repo="o/r")

    for mark in sorted(PROGRESS_MARKS):
        box._set_state(ticket, mark)
    box._set_state(ticket, JobState.PR_OPEN, needs_person=True)
    box._set_state(ticket, JobState.ON_HOLD, reason="the CI is red twice")

    assert [s for s, _ in box.tracker.states] == sorted(PROGRESS_MARKS), (
        "an outcome reached the card from the box, or a progress mark did not")
    assert box._handed_back == [
        HandedBack(state=JobState.PR_OPEN, needs_person=True),
        HandedBack(state=JobState.ON_HOLD, reason="the CI is red twice")]


def test_a_job_s_pull_request_is_handed_back_on_its_result_and_not_written(repo, tmp_path):
    """The real runner, the whole spine: the box walks its progress marks on the card and the pull
    request a person decides travels in the result — and a second call hands back only its own."""
    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    tracker = spine.FakeTracker(ticket)
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true", "security": "true"}),
                           tmp_path)

    result = runner.run("#1")

    assert result.handed_back == [HandedBack(state=JobState.PR_OPEN, needs_person=True)]
    assert JobState.PR_OPEN not in tracker.states and JobState.IMPLEMENTING in tracker.states
    again = runner.review_pr("#1", pr_url="https://forge/pr/1")
    assert again.handed_back == [], "a call handed back what an earlier call reached"


class _Forge:
    def __init__(self):
        self.tags: list[str] = []

    def create_tag(self, *, tag, ref):
        self.tags.append(tag)


class _Observer:
    def __init__(self, healthy=True):
        self.healthy = healthy

    def deploy_status(self, *, env, ref):
        return "success"

    def health(self, *, url, timeout=10):
        return self.healthy


def _promotion(environments, healthy=True):
    from openfactory.orchestrator.promotion import PromotionRunner

    return PromotionRunner(tracker=_Recorded(), forge=_Forge(), observer=_Observer(healthy),
                           manifest=Manifest(environments=environments, prod_approvers=["a"]))


@pytest.mark.parametrize("environments,healthy,reached,marks", [
    ({}, True, [JobState.MERGED, JobState.DONE], []),
    ({"staging": Environment(health_url="http://s/h"), "prod": Environment(health_url="http://p/h")},
     True, [JobState.MERGED, JobState.AWAITING_PROD_APPROVAL], [JobState.STAGING_VERIFYING]),
    ({"staging": Environment(health_url="http://s/h")}, False,
     [JobState.MERGED, JobState.ON_HOLD], [JobState.STAGING_VERIFYING]),
], ids=["nothing-follows", "the-production-gate", "a-red-stage"])
def test_the_promotion_hands_back_the_merge_and_where_it_ended(environments, healthy, reached,
                                                               marks):
    promotion = _promotion(environments, healthy)

    result = promotion.promote("#5")

    assert [b.state for b in result.handed_back] == reached
    assert [s for s, _ in promotion.tracker.states] == marks


def test_a_release_hands_back_its_delivery_and_writes_its_steps():
    promotion = _promotion({"prod": Environment(health_url="http://p/h")})

    result = promotion.release_prod("#5", version="1.4.0", approver="a")

    assert [b.state for b in result.handed_back] == [JobState.DONE]
    assert [s for s, _ in promotion.tracker.states] == [JobState.PROD_RELEASING,
                                                       JobState.PROD_VERIFYING]


# ── the worker: each outcome through the door, once ──────────────────────────────────────────

OUTCOMES = [
    (HandedBack(state=JobState.PR_OPEN, needs_person=True), "needs_action", "pr_opened",
     "waiting_on_a_person"),
    (HandedBack(state=JobState.PR_OPEN, needs_person=False), "in_review", "pr_opened", "running"),
    (HandedBack(state=JobState.MERGED), "in_review", "merged", "merged"),
    (HandedBack(state=JobState.DONE), "done", "delivered", "delivered"),
    (HandedBack(state=JobState.NEEDS_REFINEMENT, reason="no acceptance criteria"),
     "needs_action", "refused", "waiting_on_a_person"),
    (HandedBack(state=JobState.ON_HOLD, reason="the CI is red twice"), "needs_action", "parked",
     "waiting_on_a_person"),
    (HandedBack(state=JobState.BLOCKED), "needs_action", "parked", "waiting_on_a_person"),
    (HandedBack(state=JobState.FAILED), "needs_action", "parked", "waiting_on_a_person"),
    # A PRODUCTION GATE IS A STAGE since #448 slice 6 — the same column, and the record says it
    (HandedBack(state=JobState.AWAITING_PROD_APPROVAL), "needs_action", "staged", "staged"),
]


@pytest.mark.parametrize("back,column,event,after", OUTCOMES,
                         ids=[f"{b.state.value}-{c}" for b, c, _, _ in OUTCOMES])
def test_each_outcome_the_box_wrote_is_applied_by_the_worker_through_the_door_once(
        deployment, back, column, event, after):
    ref = _a_card_the_box_is_working(deployment)
    result = _handed(back)

    activities._the_worker_applies("acme", ref, "handed-back-run-1-act-1", result)

    if column == "done":
        ticket = _tracker(deployment).get_ticket(ref)
        assert (ticket.state, ticket.state_reason) == ("closed", "completed")
    else:
        assert _column(deployment, ref) == column
    [row] = _history(deployment, ref)
    assert (row.event, row.by, row.before, row.after) == (event, BY, "running", after)
    assert result.handed_back[0].event_id == row.event_id
    assert _said_on_the_card(deployment, ref) == [], (
        "the door said the outcome again — the box said it on the card as it reached it")

    # the same activity again — a box that re-attaches to the work it did: one transition
    activities._the_worker_applies("acme", ref, "handed-back-run-1-act-1", _handed(back))
    assert len(_history(deployment, ref)) == 1


def test_a_merge_and_its_delivery_are_applied_in_the_order_the_box_reached_them(deployment):
    ref = _a_card_the_box_is_working(deployment)

    activities._the_worker_applies("acme", ref, "handed-back-run-1-act-2", _handed(
        HandedBack(state=JobState.MERGED), HandedBack(state=JobState.DONE)))

    assert [r.event for r in _history(deployment, ref)] == ["merged", "delivered"]
    assert _tracker(deployment).get_ticket(ref).state == "closed"


def test_the_park_the_worker_applied_is_the_one_the_workflow_reconciles(deployment):
    """The workflow reconciles every park to Needs Action (#394) — for a crash the box never
    reported, and for a park it did. One the box handed back was applied already, and its id makes
    the reconcile the same transition: one park, one row, nothing said twice."""
    from openfactory.runtime.temporal.io import HoldSyncInput

    ref = _a_card_the_box_is_working(deployment)
    result = _handed(HandedBack(state=JobState.ON_HOLD, reason="the CI is red twice"))
    activities._the_worker_applies("acme", ref, "handed-back-run-1-act-3", result)

    asyncio.run(activities.mark_needs_action(HoldSyncInput(
        project="acme", issue=ref, state="on_hold", note="the CI is red twice",
        event_id=recorded_park(result))))

    assert [r.event for r in _history(deployment, ref)] == ["parked"]
    assert _said_on_the_card(deployment, ref) == []
    assert recorded_park(RunResult(ticket_id="#1", state=JobState.ON_HOLD)) == "", (
        "a park the workflow made itself was taken for one the worker applied")


def test_a_box_result_from_before_the_hand_back_parses_and_the_worker_applies_nothing(
        deployment):
    """A result in a job's history, or from a box image older than the worker, has no
    `handed_back`: that box wrote its own outcomes, and the worker does what it did — nothing."""
    from openfactory.runtime.temporal.io import HoldSyncInput

    ref = _a_card_the_box_is_working(deployment)
    old = RunResult.model_validate_json(
        '{"ticket_id": "#1", "state": "on_hold", "note": "validations failed"}')

    assert old.handed_back is None
    assert activities._the_worker_applies("acme", ref, "handed-back-run-1-act-4", old) is old
    assert _history(deployment, ref) == () and _column(deployment, ref) == "in_progress"
    assert recorded_park(old) == ""
    assert HoldSyncInput.model_validate({"project": "acme", "issue": ref}).event_id == ""


# ── every driver of a box applies what it handed back ────────────────────────────────────────

def _runs_the_box(name: str, back: HandedBack):
    """`(the activity, its input, the inner function to stand in for the box)`."""
    from openfactory.runtime.temporal import io

    def returned(*_a, **_k):
        return _handed(back)

    cases = {
        "run_job": (activities.run_job, io.RunJobInput(project="acme", issue="", sandbox="x"),
                    "_do_run_job"),
        "repair_ci": (activities.repair_ci, io.CiRepairInput(project="acme", issue="",
                                                             pr_url="https://x/pr/1"),
                      "_run_ci_repair"),
        "adjust_pr": (activities.adjust_pr, io.AdjustInput(project="acme", issue="",
                                                           pr_url="https://x/pr/1",
                                                           instruction="bigger"),
                      "_run_adjust"),
        "review_pr": (activities.review_pr, io.ReviewPassInput(project="acme", issue="",
                                                               pr_url="https://x/pr/1"),
                      "_run_review_pass"),
        "promote_staging": (activities.promote_staging, io.PromoteInput(project="acme",
                                                                        issue=""),
                            "_run_promotion"),
        "release_prod": (activities.release_prod, io.ReleaseInput(
            project="acme", issue="", version="1.0.0", approver="a"), "_run_promotion"),
    }
    activity, inp, inner = cases[name]
    return activity, inp, inner, returned


@pytest.mark.parametrize("name", ["run_job", "repair_ci", "adjust_pr", "review_pr",
                                  "promote_staging", "release_prod"])
def test_every_activity_that_runs_a_box_applies_what_it_handed_back(deployment, monkeypatch,
                                                                     name):
    ref = _a_card_the_box_is_working(deployment)
    activity, inp, inner, returned = _runs_the_box(
        name, HandedBack(state=JobState.PR_OPEN, needs_person=True))
    monkeypatch.setattr(activities, inner, returned)
    monkeypatch.setattr(activities, "_watch_for", lambda inp: None)
    monkeypatch.setattr(activities, "_the_checks_went_red", lambda inp: None)
    monkeypatch.setattr(activities, "_a_preview_starts_on_its_own",
                        lambda *a: asyncio.sleep(0, result=""))

    result = asyncio.run(ActivityEnvironment().run(activity, inp.model_copy(update={"issue": ref})))

    assert [r.event for r in _history(deployment, ref)] == ["pr_opened"], name
    assert _column(deployment, ref) == "needs_action"
    assert result.handed_back[0].event_id, "the result does not say which transition applied it"


def test_the_attended_driver_applies_what_the_box_handed_back(deployment, monkeypatch):
    """`openfactory run` and `poll` drive the runner with no worker in between: the CLI is the
    worker there, or nothing would move the card past its last progress mark."""
    from openfactory import cli

    ref = _a_card_the_box_is_working(deployment)

    class _Box:
        def run(self, issue):
            return _handed(HandedBack(state=JobState.PR_OPEN, needs_person=True))

    monkeypatch.setattr(cli, "build_runner", lambda *a, **k: _Box())
    monkeypatch.setattr("openfactory.observability.job_record.record_job", lambda **k: None)

    cli._drive_one(deployment, ref, sandbox="worktree", image="")

    assert [r.event for r in _history(deployment, ref)] == ["pr_opened"]
    assert _column(deployment, ref) == "needs_action"


# ── the promise one card's filing opens, through its door (#414) ─────────────────────────────

ANA, HERS = "ana-asked-77", "person:ana-asked-77"


def _pen(project, tmp_path):
    """The product role's real pen, over the project's own tracker and board."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from tests.test_card_maintenance import COMMIT, REQUIREMENTS_DIR, _corpus, _Harness

    ctx = ProductContext(link=ProductLink(active=True, docs_repo="acme/acme-docs", kind="ok",
                                          reason="fine"),
                         corpus=_corpus(), docs_path=str(tmp_path), docs_commit=COMMIT,
                         requirements_dir=REQUIREMENTS_DIR)
    return ProductModule(project, context=ctx, agent=_Harness("{}"))


def _owed(project) -> list:
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, waiting

    return [x for x in waiting(loop_store.read(project.name)) if x.kind == DELIVERY]


@pytest.mark.parametrize("verb,subject", [("ticket", "cartao"), ("defect", "defeito")])
def test_one_card_s_filing_opens_the_delivery_it_is_owed_through_its_door_once(
        deployment, tmp_path, verb, subject):
    from openfactory.product.speaker import sealed

    pen = _pen(deployment, tmp_path)
    file = (lambda: pen.file_ticket(title="Export the report", described="the report",
                                    reported_by=ANA, conversation=HERS, requester=ANA)) \
        if verb == "ticket" else \
        (lambda: pen.file_defect(restated="the export repeats the last line", reported_by=ANA,
                                 violates=None, conversation=HERS, requester=ANA))

    filed = file()

    ref = filed.ref.lstrip("#")
    [loop] = _owed(deployment)
    assert (loop.subject, loop.context["issues"]) == (f"{subject}-{ref}", ref)
    assert (loop.context["conversation"], loop.context["requester"]) == (HERS, sealed(ANA))
    [row] = _history(deployment, ref)
    assert row.event == "filed" and "loops:open" in row.effects, row.effects
    assert row.outcome(row.effects.index("loops:open")) == f"{subject}-{ref} owed"
    assert ANA not in repr(row.facts["owed"]).replace(HERS, ""), (
        "the promise the record keeps names who asked, where the ledger keeps a digest")

    # the same filing again — a retried "sim", the same title: one card, one promise
    assert file().existed
    assert [x.subject for x in _owed(deployment)] == [f"{subject}-{ref}"]


def test_a_card_filed_with_no_conversation_is_owed_to_nobody(deployment, tmp_path):
    filed = _pen(deployment, tmp_path).file_ticket(title="Tidy the logs", described="tidy them",
                                                   reported_by=ANA)

    assert filed.ok and _owed(deployment) == []
    [row] = _history(deployment, filed.ref)
    assert "loops:open" not in row.effects


def test_a_promise_the_ledger_did_not_take_is_opened_by_the_hourly_round(deployment, tmp_path,
                                                                        monkeypatch):
    """Where it was a line in the log — "it will ship without anyone announcing it" — a promise
    the ledger refused is a failed effect of a recorded filing, and the sweep opens it."""
    from openfactory.lifecycle import converge
    from openfactory.memory import store as loop_store

    real = loop_store.write
    monkeypatch.setattr(loop_store, "write", lambda name, rows: 0)
    filed = _pen(deployment, tmp_path).file_ticket(
        title="Export the report", described="the report", reported_by=ANA, conversation=HERS,
        requester=ANA)
    [row] = _history(deployment, filed.ref)
    assert row.outcome(row.effects.index("loops:open")).startswith("failed")
    assert _owed(deployment) == []

    monkeypatch.setattr(loop_store, "write", real)
    converge(deployment)

    assert [x.subject for x in _owed(deployment)] == [f"cartao-{filed.ref.lstrip('#')}"]

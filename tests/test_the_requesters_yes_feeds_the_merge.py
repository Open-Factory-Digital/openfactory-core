"""The requester's "that's it" is recorded against the head they tried, and it matters (#448,
slice 3, behaviour 4; ADR-0055 D1's `accepted`).

WHAT WAS WRONG, measured on #448's run (card #1000007, 2026-09-30) and in the code. The requester
tried the preview, and a "that's it" reached nothing:

  · nothing recorded it — the product role had no gesture for a yes, and no store held one;
  · the person merging was never shown it — the floor bar, the inbox and the tech-lead all read
    the merge gate, and the gate knew nothing of the requester;
  · on `merge_policy: auto` with a required preview (ADR-0050 D9), `should_auto_merge` refused, and
    the pull request waited for a person who, on that path, nobody had appointed;
  · and the requester heard nothing when the change went in, unless the merge happened to complete
    a delivery on a project with no stages.

WHAT IS PROVEN HERE, on the real local board, the real staging and confirmation path, the real
preview record in the real metrics store, the real `JobWorkflow` on a time-skipping engine and the
real `JobRunner` on a git repository — doubled only where something leaves the machine or spends:
the model's reading of a message, the forge's answer about a branch's head, and the engine's
client where the workflow is not the thing under test:

  · the machine says when the look is ALL that holds a merge, with every other hold still holding;
  · the job publishes it on its merge wait, and withdraws it when a pass rewrote what was judged;
  · the yes is recorded against the head the preview was BUILT from, refused by name when nothing
    was tried or the change moved since, and stored in the platform's own store;
  · with a human merge the person merging sees it — floor, inbox, tech-lead; when the look is all
    that holds it, the yes answers the gate with a sealed `merge`, and the real job lands it;
  · the requester hears the change went in, once per card and pull request, where the delivery
    does not already say it — and the job's new telling replays behind its marker.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import time
from types import SimpleNamespace

import pytest
from temporalio import activity

import openfactory.product.channel as pc
from openfactory import preview
from openfactory.contracts import JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.contracts.review import ReviewResult
from openfactory.preview import demand
from openfactory.product import accept, events, voice
from openfactory.runtime.temporal.io import (
    AdjustInput,
    CoordinatorSayInput,
    HoldSyncInput,
    MergeCheckInput,
    MergedInput,
    RunJobInput,
    TicketRef,
)
from openfactory.runtime.temporal.workflow import JobWorkflow
from tests import test_the_requester_asks_for_another_pass as slice_1
from tests import test_walking_skeleton
from tests.test_the_requester_asks_for_another_pass import (
    ADMIN,
    ASKER,
    KEY,
    PR,
    STRANGER,
    _act,
    _Job,
    _waiting_card,
)

#: SLICE 1'S OWN DEPLOYMENT, the same parts: a registered local project with a product role and
#: the board `project init` made, its tracker and board, and the engine's client doubled where the
#: product side keeps it (`release._client`) — fixtures, bound here so this file reads them by name
deployment, tracker, board, engine = (slice_1.deployment, slice_1.tracker, slice_1.board,
                                      slice_1.engine)
#: a git repository the real `JobRunner` opens a pull request from
repo = test_walking_skeleton.repo

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")

#: The head the card's preview was built from — what the requester tried — and a later push.
HEAD = "c0ffee1234567890abcdef1234567890abcdef12"
LATER = "beef00009876543210fedcba9876543210fedcba"


@pytest.fixture(autouse=True)
def _nothing_staged_nothing_cached():
    pc._PENDING.clear()
    demand._CACHE.clear()
    yield
    pc._PENDING.clear()
    demand._CACHE.clear()


@pytest.fixture
def store(monkeypatch, tmp_path):
    """The platform's own store, as a local deployment runs it: SQLite on disk."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))


@pytest.fixture
def forge(monkeypatch) -> dict:
    """The forge's answer about where each pull request's branch points NOW — the one read that
    leaves the machine. Doubled at the read the preview's own judgement makes (`demand.
    _forge_state`), so the minute of cache in front of it is the real one."""
    heads: dict[str, str] = {PR: HEAD}

    def _state(project, token, was, *, forge_of=None, heads_of=None):
        return demand.ForgeState(open=tuple(heads), heads=dict(heads), branches={})

    monkeypatch.setattr(demand, "_forge_state", _state)
    return heads


def _tried(card: str, *, head: str = HEAD, state: str = preview.LIVE) -> None:
    """The preview of `card`'s change as the worker records it once it is up (`steps.up`)."""
    assert preview.record(preview.Preview(
        project="acme", unit=card, cards=(card,), state=state, services={"web": 3000},
        heads={PR: head} if head else {}, pr_urls=(PR,), expires_at=int(time.time()) + 3600))


class _Waiting(_Job):
    """The job at its merge gate, saying — as `JobWorkflow` does — whether the look is all that
    holds its merge."""

    def __init__(self, *, look: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.look = look

    def merge_wait(self) -> dict:
        return {**super().merge_wait(), "auto_but_for_the_look": self.look}


def _sealed_merge(job: _Job, ref: str, *, by: str) -> str:
    """The one answer the job was sent, which must be a `merge` by `by` whose seal the worker's own
    check passes (`gate_seal.refusal`, which `verify_gate_seal` asks) — "" when it does."""
    from openfactory import gate_seal
    from openfactory.runtime.temporal.view import job_id

    [(answer, instruction, said_by, seal)] = job.signals
    assert (answer, said_by) == ("merge", by), job.signals
    return gate_seal.refusal(seal, gate_seal.MERGE_GATE, job_id("acme", ref), answer,
                             instruction, said_by)


class _Role:
    """The product role's READING of a message, scripted — the one thing a model decides in a turn.
    Everything it hands the engine to act on is the real module's."""

    def __init__(self, module, *, says: str, card: str, gesture: str = "accept") -> None:
        self.module, self.says, self.card, self.gesture = module, says, card, gesture

    def __getattr__(self, name):
        return getattr(self.module, name)

    def context(self):
        return SimpleNamespace(available=True, reason="")

    def settle_acceptance(self, text, **_):
        return None

    def close_decisions_answered(self, **_):
        return 0

    def confirmed(self, reply, *, proposal):
        return "neither"

    def answer(self, question, **_):
        from openfactory.product.role import ProductAnswer

        return ProductAnswer(ok=True, text=self.says, gesture=self.gesture,
                             gesture_card=self.card)


THATS_IT = "I tried the preview. That's it — the export button is on the toolbar, as I asked."
GLAD = "Good — the button is where you wanted it."


def _module(project):
    from openfactory.product.module import ProductModule

    return ProductModule(project, via="panel")


def _say(project, card: str, text: str, *, who: str = ASKER) -> str:
    from tests.the_chat_turn import chat_turn

    return str(chat_turn(project, text=text, user=who, thread=KEY,
                         module=_Role(_module(project), says=GLAD, card=card)))


def _staged(project):
    return pc.find_waiting(KEY, KEY, project=project, person=ASKER)[1]


# ── 1. the machine says when the look is ALL that holds a merge ─────────────────────────────────

def _clean(**kw) -> RunResult:
    from openfactory.contracts import ValidationResult

    base = dict(ticket_id="#1", state="pr_open",
                validations=[ValidationResult(name="test", command="pytest -q", exit_code=0,
                                              passed=True)])
    base.update(kw)
    return RunResult(**base)


def test_the_look_alone_holding_a_merge_is_said_and_any_other_hold_still_holds():
    from openfactory.contracts import Manifest
    from openfactory.orchestrator.merge_policy import auto_but_for_the_look, should_auto_merge

    auto = Manifest(merge_policy="auto", review_mode="blocking")
    held = _clean(preview_required=True)
    assert not should_auto_merge(auto, held), "ADR-0050 D9's block is gone"
    assert auto_but_for_the_look(auto, held)
    # a person's merge, no look required, or another hold beside the look: never "only the look"
    assert not auto_but_for_the_look(Manifest(merge_policy="human"), held)
    assert not auto_but_for_the_look(auto, _clean())
    for other in ({"protected_hits": [".openfactory/project.yaml"]}, {"floor_unreadable": True},
                  {"review": ReviewResult(decision="rejected", score=10)},
                  {"added_suppressions": ["noqa"]}):
        assert not auto_but_for_the_look(auto, _clean(preview_required=True, **other)), other


@pytest.mark.parametrize("policy,merges", [("auto", True), ("human", False)])
def test_the_real_runner_carries_it_and_the_pull_request_says_who_merges(
        policy, merges, tmp_path, repo):
    """The real `JobRunner` on a git repository, `preview.required` in the registry."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from openfactory.contracts import AcceptanceCriterion, Manifest, Ticket
    from openfactory.contracts.project import PreviewPolicy, Project
    from tests.test_walking_skeleton import FakeReviewer, FakeTracker
    from tests.test_walking_skeleton import _runner as skeleton_runner

    ticket = Ticket(id="#31", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    manifest = Manifest(merge_policy=policy, validate={"test": "true", "security": "true"})
    runner = skeleton_runner(repo, FakeTracker(ticket), manifest, tmp_path,
                             reviewer=FakeReviewer(), sandbox=WorktreeSandbox(root=tmp_path / "wt"))
    runner.project = Project(name="app", repo_path=str(repo), preview=PreviewPolicy(required=True))

    result = runner.run("#31")

    assert result.state is JobState.PR_OPEN, "a required look still sends it to a person first"
    assert result.auto_but_for_the_look is merges
    body = runner.forge.opened["body"]
    assert ("when they accept the head they tried, the factory merges it" in body) is merges
    assert ("nobody merges this for you" in body) is not merges


# ── 2. the reading standing now still admits it ─────────────────────────────────────────────────

@pytest.mark.parametrize("verdict,judged,admits", [
    (None, "", True),                                               # no review: as judged
    ({"decision": "approved"}, "approved", True),
    ({"decision": "approved", "stale": "a pass rewrote it"}, "approved", False),
    ({"decision": "rejected"}, "approved", False),                  # worse than when judged
    ({"decision": "rejected"}, "rejected", True),                   # advisory: never held it
    ({"decision": "approved", "evidence_checked": True,             # #447: nothing executed it
      "acceptance": [{"criterion": "c", "status": "met", "executed_by": ""}]}, "approved", False),
])
def test_a_pass_that_rewrote_what_was_judged_is_read_again(verdict, judged, admits):
    from openfactory.review.verdict import still_admits_the_merge

    assert still_admits_the_merge(verdict, judged=judged) is admits


# ── 3. the real job publishes it, withdraws it, and lands the merge its yes gives ────────────────

TQ = "test-the-requesters-yes"
JOB_PR = "https://x/pr/9"

_LOOK = [True]
_MERGED: list[str] = []
_TOLD: list[MergedInput] = []
_READS = [0]


@activity.defn(name="run_job")
async def _run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=JOB_PR,
                     branch="openfactory/9", auto_merge=False, preview_required=True,
                     auto_but_for_the_look=_LOOK[0],
                     review=ReviewResult(decision="approved", score=90))


@activity.defn(name="read_ci_checks")
async def _green(inp: MergeCheckInput) -> CiDecision:
    _READS[0] += 1
    return CiDecision(verdict="success")


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
    return "blocked"


@activity.defn(name="check_pr_status")
async def _status(inp: MergeCheckInput) -> str:
    return "merged" if _MERGED else "open"


@activity.defn(name="merge_pr_saying_why")
async def _merge(inp: MergeCheckInput) -> str:
    _MERGED.append(inp.pr_url)
    return ""


@activity.defn(name="adjust_pr")
async def _adjust(inp: AdjustInput) -> RunResult:
    # a pass that rewrote the change and came back with no reading of it
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url,
                     code_changed=True)


@activity.defn(name="close_pr")
async def _close(inp: MergeCheckInput) -> None:
    return None


@activity.defn(name="tell_the_requester_it_merged")
async def _told(inp: MergedInput) -> bool:
    _TOLD.append(inp)
    return True


@activity.defn(name="settle_ticket")
async def _settle(inp: HoldSyncInput) -> str:
    return inp.state


@activity.defn(name="mark_needs_action")
async def _mark(inp: HoldSyncInput) -> str:
    return "somebody"


@activity.defn(name="fetch_ticket_title")
async def _title(inp: TicketRef) -> str:
    return "Export the list"


@activity.defn(name="notify_coordinator_say")
async def _say_it(inp: CoordinatorSayInput) -> None:
    return None


@activity.defn(name="refresh_knowledge")
async def _refresh(inp) -> str:
    return "published"


_JOB_MOCKS = [_run_job, _green, _blocked, _status, _merge, _adjust, _close, _told, _settle, _mark,
              _title, _say_it, _refresh]


@pytest.fixture
async def env():
    """This file's own ephemeral engine, started and disposed of here: the barrier is lifted for a
    server the test owns (`test_the_suite_cannot_reach_a_live_engine`), not for one it borrows."""
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    _LOOK[0] = True
    _MERGED.clear(), _TOLD.clear()
    _READS[0] = 0
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _until(check, *, what: str = "the job at its gate"):
    for _ in range(400):
        got = await check()
        if got:
            return got
        await asyncio.sleep(0.05)
    raise AssertionError(f"never saw: {what}")


async def _at_the_gate(h, *, after: int = 0) -> dict:
    """The gate as the job rebuilds it after reading its checks again — never the one before."""
    async def look():
        gate = await h.query(JobWorkflow.awaiting_merge)
        return gate if (gate and _READS[0] > after and not gate.get("working")
                        and "auto_but_for_the_look" in gate) else None
    return await _until(look)


async def _accept_and_land(env, *, issue: str = "9") -> tuple[dict, RunResult, object]:
    """A real job held at its human gate; the yes's `merge` given through the real seam
    (`view.answer_merge_gate`: query, deaf check, seal), and the job run to its end."""
    from gate_answers import SEAL_CHECK
    from temporalio.worker import Worker

    from openfactory.runtime.temporal import view as tv
    from openfactory.runtime.temporal.io import JobParams

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[SEAL_CHECK, *_JOB_MOCKS]):
        h = await env.client.start_workflow(
            "JobWorkflow", JobParams(project="acme", issue=issue, merge_deadline_days=3650),
            id=tv.job_id("acme", issue), task_queue=TQ, result_type=RunResult)
        gate = await _at_the_gate(h)
        await tv.answer_merge_gate(env.client, "acme", issue, answer="merge", by=ASKER)
        result = await h.result()
        history = await h.fetch_history()
    return gate, result, history


@pytest.mark.owns_its_engine
async def test_the_job_publishes_that_the_look_alone_holds_it_and_lands_the_yes(env):
    gate, result, _ = await _accept_and_land(env)

    assert gate["auto_but_for_the_look"] is True and gate["auto"] is False, gate
    assert gate["gate_live"] is True
    assert result.state is JobState.MERGED and _MERGED == [JOB_PR], (
        "the merge the yes gave was not acted on")
    # …and the requester hears it went in, once, with nothing staged after it
    assert [(t.issue, t.pr_url, t.stages_follow) for t in _TOLD] == [("9", JOB_PR, False)]


@pytest.mark.owns_its_engine
async def test_a_job_whose_result_does_not_say_publishes_no_such_thing(env):
    """A result written before the field — or a look that is not the only hold — is a person's."""
    _LOOK[0] = False
    gate, result, _ = await _accept_and_land(env, issue="10")

    assert gate["auto_but_for_the_look"] is False
    assert result.state is JobState.MERGED, "a person's merge must still land"


@pytest.mark.owns_its_engine
async def test_a_pass_that_rewrote_the_change_unread_withdraws_it(env):
    """The machine judged the first reading. A pass the requester asked for rewrote it and came
    back with no reading: the yes is shown to a person, and the factory merges nothing on it."""
    from gate_answers import SEAL_CHECK, answer_merge_gate
    from temporalio.worker import Worker

    from openfactory.runtime.temporal import view as tv
    from openfactory.runtime.temporal.io import JobParams

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=[SEAL_CHECK, *_JOB_MOCKS]):
        h = await env.client.start_workflow(
            "JobWorkflow", JobParams(project="acme", issue="11", merge_deadline_days=3650),
            id=tv.job_id("acme", "11"), task_queue=TQ, result_type=RunResult)
        before = await _at_the_gate(h)
        read = _READS[0]
        await answer_merge_gate(h, "adjust", "the button on the right", ASKER)
        after = await _at_the_gate(h, after=read)
        await answer_merge_gate(h, "discard", "", ASKER)
        await h.result()

    assert before["auto_but_for_the_look"] is True
    assert after["auto_but_for_the_look"] is False, after


@pytest.mark.owns_its_engine
async def test_the_telling_is_a_new_command_behind_its_marker_and_the_replay_proves_it(
        env, monkeypatch):
    """Recorded with `patched` answering False for the marker — the arm a job that reached its
    merge before this change selects — and replayed through the real `patched()`. The same history
    through the marker's arm must DIVERGE, or the green replay verified nothing."""
    from temporalio import workflow as tw
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer

    marker = "the-requester-hears-it-went-in"
    real = tw.patched
    with monkeypatch.context() as m:
        m.setattr(tw, "patched", lambda name: False if name == marker else real(name))
        _, result, history = await _accept_and_land(env, issue="12")
    assert result.state is JobState.MERGED
    assert _TOLD == [], "the recording ran the new command it claims to predate"

    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

    monkeypatch.setattr(tw, "patched", lambda name: True if name == marker else real(name))
    with pytest.raises(Exception) as caught:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)
    said = str(caught.value)
    assert "determinis" in said.lower() or "TMPRL1100" in said or "Nondeterminism" in said, (
        f"the marker's arm failed the replay for another reason: {said[:400]}")


def test_the_job_says_whether_stages_follow_with_the_promotions_own_condition():
    """The telling is told `stages_follow` from the very condition the promotion runs on — a
    second spelling of it would tell a project with stages that nothing follows."""
    import inspect

    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._lifecycle)
    assert "should_promote = params.promote or bool(result.environments)" in src
    assert "self._tell_the_requester_it_merged(params, result, stages_follow=should_promote)" in src
    assert src.index("should_promote = params.promote") < src.index(
        "self._tell_the_requester_it_merged(")


# ── 4. the conversation: "that's it", recorded against the head they tried ──────────────────────

def test_the_marker_is_read_into_the_answer_and_never_reaches_the_person(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _ = _answering_module(tmp_path, answer="Good, it is right.\n[[ACEITE: #1000007]]")
    answer = mod.answer("that's it")
    assert (answer.gesture, answer.gesture_card) == ("accept", "1000007")
    assert answer.text == "Good, it is right."

    # A REPLY THAT COULD NOT DECIDE is a "not yet": nothing is recorded the person may still want
    mod, _ = _answering_module(tmp_path, answer="Hm.\n[[AJUSTE: #7]]\n[[ACEITE: #7]]")
    answer = mod.answer("it is right but move the button")
    assert (answer.gesture, answer.gesture_card) == ("adjust", "7")
    assert "[[" not in answer.text


def test_with_a_person_merging_the_yes_is_recorded_and_said_on_the_card(
        deployment, tracker, board, engine, store, forge):
    """BEHAVIOUR 4, a human merge: recorded against what they tried, never answered for them."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=False))
    _tried(ref)

    asked = _say(deployment, ref, THATS_IT)

    staged = _staged(deployment)
    assert staged["kind"] == "accept_change" and staged["number"] == ref, staged
    assert (staged["head"], staged["pr_url"], staged["conversation"]) == (HEAD, PR, KEY)
    assert asked.startswith(GLAD), "the role's own reply is not in front"
    assert (f"I'll record that *#{ref}*, as you tried it in its preview, is what you asked for, "
            f"for whoever puts this project's changes into the product to see") in asked, asked
    assert accept.standing("acme", ref) is None, "something was recorded before the yes"

    said = _say(deployment, ref, "yes")

    assert said.startswith(f"recorded: #{ref}, as you tried it, is what you asked for. Whoever "
                           f"puts this project's changes into the product sees your yes"), said
    got = accept.standing("acme", ref, PR)
    assert (got.by, got.head, got.pr_url, got.where) == (ASKER, HEAD, PR, KEY), got
    assert job.signals == [], "a person's merge was answered in the requester's name"
    [note] = [c.body for c in tracker.comments(f"#{ref}")]
    assert f"`{HEAD[:7]}` of {PR}" in note and ASKER in note, note
    assert "the factory merges it" not in note
    assert _staged(deployment) is None


def test_when_the_look_is_all_that_holds_it_the_yes_lands_the_merge_sealed(
        deployment, tracker, board, engine, store, forge):
    """BEHAVIOUR 4, `merge_policy: auto` with a required preview: the acceptance is what lets the
    factory merge — given through the seam every answer crosses, sealed in the requester's name."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)

    asked = _say(deployment, ref, THATS_IT)
    assert "is what you asked for, and with that it goes into the product. Confirm?" in asked
    said = _say(deployment, ref, "yes")

    assert said.startswith(f"recorded: #{ref}, as you tried it, is what you asked for — so it "
                           f"goes into the product now."), said
    assert _sealed_merge(job, ref, by=ASKER) == "", "the worker would refuse the yes's merge"
    assert accept.standing("acme", ref, PR).head == HEAD
    [note] = [c.body for c in tracker.comments(f"#{ref}")]
    assert "so the factory merges it now" in note, note


def test_a_head_the_forge_cannot_confirm_is_recorded_and_merged_by_nobody(
        deployment, tracker, board, engine, store, forge):
    """The yes stands for what was tried; a merge needs the pull request to still BE that."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)
    forge.clear()                                   # the forge did not answer for the branch

    _say(deployment, ref, THATS_IT)
    said = _say(deployment, ref, "yes")

    assert "Whoever puts this project's changes into the product sees your yes" in said, said
    assert job.signals == [] and accept.standing("acme", ref, PR).head == HEAD


@pytest.mark.parametrize("what,heard", [
    ("untried", "I can only record your yes against a version you tried in its preview"),
    ("rebuilding", "I can only record your yes against a version you tried in its preview"),
    ("moved", "change moved since the preview you tried was built"),
])
def test_nothing_tried_or_a_change_that_moved_is_refused_by_name(
        deployment, tracker, board, engine, store, forge, what, heard):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    if what == "rebuilding":
        _tried(ref, head="", state=preview.STARTING)   # a start resets what was built
    elif what == "moved":
        _tried(ref)
        forge[PR] = LATER

    said = _say(deployment, ref, THATS_IT)

    assert heard in said, said
    assert _staged(deployment) is None and job.signals == [] and accept.standing("acme", ref) is None


def test_a_preview_rebuilt_between_the_proposal_and_the_yes_is_not_accepted_in_their_name(
        deployment, tracker, board, engine, store, forge):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)
    _say(deployment, ref, THATS_IT)
    _tried(ref, head=LATER)                         # rebuilt from a later push meanwhile
    forge[PR] = LATER

    said = _say(deployment, ref, "yes")

    assert "change moved since the preview you tried was built" in said, said
    assert accept.standing("acme", ref) is None and job.signals == []


@pytest.mark.parametrize("job,heard", [
    (_Waiting(working=True), "is in a pass right now"),
    (_Waiting(running=False), "is waiting on you right now"),
    (_Waiting(auto=True), "is waiting on you right now"),
])
def test_a_change_nobody_is_asked_about_has_nothing_to_accept(
        deployment, tracker, board, engine, store, forge, job, heard):
    ref = _waiting_card(tracker, board)
    engine.holds(ref, job)
    _tried(ref)

    said = _say(deployment, ref, THATS_IT)

    assert heard in said and _staged(deployment) is None and job.signals == []


def test_past_the_budget_a_yes_is_still_a_yes(deployment, tracker, board, engine, store, forge):
    """The passes are spent: the person decides — and the requester's yes is what they decide on."""
    ref = _waiting_card(tracker, board)
    engine.holds(ref, _Waiting(look=False, passes=2, spent=2))
    _tried(ref)

    _say(deployment, ref, THATS_IT)
    assert _staged(deployment)["kind"] == "accept_change"


def test_somebody_who_did_not_ask_for_the_card_cannot_accept_it(
        deployment, tracker, board, engine, store, forge):
    from openfactory.product.confirm import _may_say_yes

    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)

    said = _say(deployment, ref, THATS_IT, who=STRANGER)

    assert f"only the person who asked for #{ref}, or someone with permission to approve, can " \
           f"accept its change" in said, said
    assert job.signals == [] and accept.standing("acme", ref) is None
    # and a yes on the requester's own proposal from somebody else is refused in the act's words
    other = SimpleNamespace(may_send_back=lambda number, actor: actor == ASKER)
    assert "can accept its change" in _may_say_yes(
        deployment, {"kind": "accept_change", "number": ref}, STRANGER, via="panel", module=other)


def test_a_yes_that_could_not_be_written_down_is_refused_and_merges_nothing(
        deployment, tracker, board, engine, store, forge, monkeypatch):
    """The record is the yes: one that did not land is said, and nothing after it runs."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)
    _say(deployment, ref, THATS_IT)
    monkeypatch.setattr(accept, "record", lambda *a, **k: False)

    said = _say(deployment, ref, "yes")

    assert f"I could not write your yes down for #{ref} just now" in said, said
    assert job.signals == [] and tracker.comments(f"#{ref}") == []


def test_two_yeses_to_two_builds_of_the_preview_are_two_proposals():
    from openfactory.product.staging import proposal_token

    one = {"kind": "accept_change", "number": "7", "head": HEAD}
    assert proposal_token("k", one) != proposal_token("k", {**one, "head": LATER})


# ── 5. the card on the product view: the same act, the same people ──────────────────────────────

def test_the_card_offers_this_is_it_to_its_requester_with_the_head_they_tried(
        deployment, tracker, board, engine, store, forge):
    ref = _waiting_card(tracker, board)
    engine.holds(ref, _Waiting(look=True))
    _tried(ref)

    view = _act("product_board", who=ASKER, project="acme", card=ref).data["card"]["accept"]

    assert view["offered"] and view["head"] == HEAD, view
    assert view["words"]["accept"] == "This is it — accept"
    assert "With that it goes into the product." in view["words"]["note"]
    assert _act("product_board", who=STRANGER, project="acme",
                card=ref).data["card"]["accept"] == {"offered": False}


def test_a_card_whose_change_nobody_tried_says_so_and_offers_nothing(
        deployment, tracker, board, engine, store, forge):
    ref = _waiting_card(tracker, board)
    engine.holds(ref, _Waiting())

    view = _act("product_board", who=ASKER, project="acme", card=ref).data["card"]["accept"]

    assert view["offered"] is False
    assert "I can only record your yes against a version you tried" in view["note"]


def test_the_requester_accepts_from_the_card_and_the_merge_is_sealed(
        deployment, tracker, board, engine, store, forge):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)

    out = _act("product_accept_change", who=ASKER, project="acme", number=ref, head=HEAD)

    assert out.ok and out.message.startswith(f"recorded: #{ref}"), out.message
    assert _sealed_merge(job, ref, by=ASKER) == ""
    assert accept.standing("acme", ref, PR).by == ASKER


def test_the_forge_is_asked_again_at_the_yes_not_read_from_the_cards_minute(
        deployment, tracker, board, engine, store, forge):
    """The card read the forge through the preview's minute of cache. A push lands after it; the
    yes asks again, and a yes on the head the card showed is refused, never recorded for a push."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=True))
    _tried(ref)
    assert _act("product_board", who=ASKER, project="acme",
                card=ref).data["card"]["accept"]["offered"]
    forge[PR] = LATER

    out = _act("product_accept_change", who=ASKER, project="acme", number=ref, head=HEAD)

    assert not out.ok and "change moved since the preview you tried was built" in out.message
    assert job.signals == [] and accept.standing("acme", ref) is None


def test_an_operator_may_accept_from_the_product_view_and_a_stranger_may_not(
        deployment, tracker, board, engine, store, forge):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Waiting(look=False))
    _tried(ref)

    out = _act("product_accept_change", who=STRANGER, project="acme", number=ref)
    assert not out.ok and "can accept its change" in out.message, out.message
    out = _act("product_accept_change", who="op-1", product=False, admin=True, project="acme",
               number=ref)
    assert out.ok, out.message
    assert accept.standing("acme", ref).by == "op-1" and job.signals == []


def test_the_product_view_is_DRIVEN_the_card_says_this_is_it_and_the_click_carries_the_head():
    from tests.test_a_refusal_is_not_an_answer import run

    words = {"close": "Close card", "remove": "Remove", "confirm": "Confirm", "cancel": "Cancel",
             "reason": "Why?", "ask_close": "c", "ask_remove": "r", "note": "n"}
    card = {"ref": "7", "readable": True, "title": "Export the list", "body": "asked",
            "state": "open", "column": "In review", "opened_by_product": "request",
            "started": True, "removes": True, "words": words, "adjust": {"offered": False},
            "accept": {"offered": True, "head": HEAD,
                       "words": {"accept": "This is it — accept", "note": "If it is right."}}}
    stubs = ("let _prod={project:'acme'},_bd={};"
             "let _pv={board:undefined,boardMsg:'',card:null,ask:null,said:null,adjusting:null};"
             f"const CARD={json.dumps(card)};const acts=[];"
             "async function act(name,params){acts.push([name,params]);"
             "if(name==='product_accept_change'){CARD.accept={offered:false};"
             "return {ok:true,message:'recorded: #7, as you tried it',data:{}}}"
             "return {ok:true,message:'',data:{cards:[{ref:'7',title:CARD.title,"
             "column:'In review'}],card:params.card?CARD:null}}}")
    got = run("nodes['#pvBoard']=node();"
              "await pvCardOpen('7');const opened=nodes['#pvBoard'].innerHTML;"
              "await pvAcceptSend();return {opened,after:nodes['#pvBoard'].innerHTML,acts}",
              "pvCardOpen", "pvCardRead", "paintPvBoard", "_bcontrols", "pvAdjustBlock",
              "pvAcceptBlock", "pvAcceptSend", stubs=stubs)

    assert "This is it — accept" in got["opened"] and "If it is right." in got["opened"]
    assert ["product_accept_change", {"project": "acme", "number": "7", "head": HEAD}] in (
        got["acts"]), got["acts"]
    assert "recorded: #7, as you tried it" in got["after"], "the answer did not stay on the card"
    assert "This is it — accept" not in got["after"], (
        "the server says nothing is left to accept, and the page still draws the button")


# ── 6. the person merging sees it: floor, inbox, tech-lead ──────────────────────────────────────

def _gate_job(issue: str = "7", **action) -> dict:
    return {"project": "acme", "issue": issue, "title": "t", "state": "awaiting_your_merge",
            "action": {"kind": "merge_wait", "pr_url": PR, "auto": False, **action}}


def test_every_gate_a_person_is_asked_carries_the_acceptance_with_its_head(store):
    accept.record("acme", accept.Acceptance(card="7", pr_url=PR, head=HEAD, by=ASKER))
    _tried("7")
    other = {"project": "acme", "issue": "8", "state": "running", "action": None}

    got = accept.at_the_gates([_gate_job("7"), other, _gate_job("7", working=True),
                               _gate_job("7", auto=True)])

    assert got[1:] == [None, None, None], "a gate nobody is asked about carries it"
    assert got[0] == {"by": ASKER, "head": HEAD, "at": got[0]["at"], "current": True,
                      "said": f"accepted by {ASKER} on {HEAD[:7]}"}, got[0]
    # the preview rebuilt from a later push: the yes stands for an earlier head, and says so
    _tried("7", head=LATER)
    [later] = accept.at_the_gates([_gate_job("7")])
    assert later["current"] is False and "an earlier head than the preview shows now" in (
        later["said"])
    # newest wins, and another pull request's yes is not this one's
    accept.record("acme", accept.Acceptance(card="7", pr_url=PR, head=LATER, by=ADMIN))
    accept.record("acme", accept.Acceptance(card="7", pr_url=PR + "0", head=HEAD, by=STRANGER))
    assert accept.standing("acme", "7", PR).by == ADMIN


def test_the_inbox_shows_the_person_merging_who_accepted_and_on_which_head(
        store, tmp_path, monkeypatch):
    """`/api/inbox`, executed: every channel renders this item."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)
    accept.record("acme", accept.Acceptance(card="7", pr_url=PR, head=HEAD, by=ASKER))

    async def _connect():
        return object()

    async def _jobs(_client, _ns):
        return [_gate_job("7")]

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "list_jobs", _jobs)

    row = next(r for r in TestClient(app).get("/api/inbox").json() if r["kind"] == "merge")

    assert row["accepted"]["said"] == f"accepted by {ASKER} on {HEAD[:7]}", row
    # …and the page draws it on the item's own line, executed
    from tests.test_a_refusal_is_not_an_answer import run

    got = run(f"return inboxQuestion({json.dumps(row)})", "inboxQuestion")
    assert got.endswith(f"— accepted by {ASKER} on {HEAD[:7]}"), got


def test_the_floor_bar_draws_it_beside_the_gates_answers():
    """The floor row, where it draws a human gate: the server's sentence, amber when stale."""
    from tests.test_a_refusal_is_not_an_answer import run

    gate = PANEL.split('parked.action.kind=="merge_wait"')[1].split("} else if(parked)")[0]
    assert gate.index("gateAcceptedLine(parked)") < gate.index('data-k="merge"'), (
        "the acceptance is not drawn where the person merging decides")
    got = run("return {now:gateAcceptedLine({accepted:{said:'accepted by ana on c0ffee1',"
              "current:true}}),old:gateAcceptedLine({accepted:{said:'s',current:false}}),"
              "none:gateAcceptedLine({})}", "gateAcceptedLine")
    assert "accepted by ana on c0ffee1" in got["now"] and "b-ok" in got["now"]
    assert "b-warn" in got["old"] and got["none"] == ""


def test_the_tech_lead_is_told_who_accepted_and_on_which_head():
    from openfactory.techlead.conversation import state_snapshot

    said = state_snapshot([{**_gate_job("7"), "accepted": {
        "by": ASKER, "head": HEAD, "said": f"accepted by {ASKER} on {HEAD[:7]}"}}])

    assert f"ACCEPTED: accepted by {ASKER} on {HEAD[:7]}" in said, said
    assert "tried that head in its preview" in said


# ── 7. the requester hears it went in ───────────────────────────────────────────────────────────

LANG, AGENT = "en", "Nina"
REQUESTERS = "person:ana-asked-77"


@pytest.fixture
def product(monkeypatch, tmp_path):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project
    from openfactory.memory import store as loop_store

    project = Project(name="acme", repo_path=str(tmp_path), language=LANG,
                      product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN],
                                            agent_name=AGENT))
    book = SimpleNamespace(rows=[], told=[], delivered=set())
    monkeypatch.setattr(loop_store, "read", lambda name, **_k: list(book.rows))
    monkeypatch.setattr(events, "_tell", lambda project, **kw: book.told.append(kw) or True)
    monkeypatch.setattr(events, "_title_of", lambda project, card: "Export the list")
    monkeypatch.setattr(events, "_delivered_now", lambda project: set(book.delivered))
    monkeypatch.setattr(events, "_store_path",
                        lambda project: tmp_path / "memory" / "events.json")
    return project, book


def _delivery(card: str, *also: str, defect: bool = False):
    from openfactory.memory.ledger import DELIVERY, open_loop
    from openfactory.product import followup

    return open_loop(DELIVERY, f"defeito-{card}" if defect else "7", owner="product",
                     ts="2026-10-01T10:00:00+00:00",
                     context={"issues": ",".join([card, *also]),
                              **followup.delivered_to(REQUESTERS, ASKER)})


def test_with_stages_to_pass_the_requester_hears_it_went_in_once(product, store):
    project, book = product
    book.rows = [_delivery("500")]

    assert events.merged_for_you(project, card="500", pr_url=PR, stages_follow=True)
    assert not events.merged_for_you(project, card="500", pr_url=PR, stages_follow=True), (
        "told twice for one card and pull request")

    [told] = book.told
    assert told["conversation"] == REQUESTERS
    assert told["text"] == voice.merged_for_you(ref="500", title="Export the list",
                                                stages_follow=True, language=LANG,
                                                agent_name=AGENT)
    assert "still goes through this project's stages" in told["text"]


def test_with_no_stage_the_delivery_says_it_and_this_says_nothing(product, store):
    """MEASURED: with no stage the job ends Done at this merge and `card_finished` announces the
    delivery to the same conversation — a second message would be the same news twice."""
    project, book = product
    book.rows = [_delivery("500")]

    assert not events.merged_for_you(project, card="500", pr_url=PR)
    assert book.told == []


def test_a_card_whose_delivery_waits_on_other_cards_is_told_on_its_own(product, store):
    """The requirement's other card is still open: no delivery completes at this merge, and the
    requester would hear nothing until the last one lands."""
    project, book = product
    book.rows = [_delivery("500", "501")]

    assert events.merged_for_you(project, card="500", pr_url=PR)
    assert [t["conversation"] for t in book.told] == [REQUESTERS]
    assert "stages" not in book.told[0]["text"]


def test_a_card_with_no_delivery_is_told_where_its_requester_accepted_it(product, store):
    """A card the role opened from a request opens no delivery loop: the acceptance's conversation
    is the way back to the person who asked."""
    project, book = product
    accept.record("acme", accept.Acceptance(card="500", pr_url=PR, head=HEAD, by=ASKER,
                                            where=KEY))

    assert events.merged_for_you(project, card="500", pr_url=PR)
    assert [t["conversation"] for t in book.told] == [KEY]


def test_a_card_nobody_asked_for_in_a_conversation_is_told_to_nobody(product, store):
    project, book = product
    assert not events.merged_for_you(project, card="500", pr_url=PR, stages_follow=True)
    assert book.told == []


async def test_the_activity_is_registered_and_reaches_the_event(monkeypatch, tmp_path):
    from temporalio.testing import ActivityEnvironment

    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.worker import WORKER_ACTIVITIES

    assert acts.tell_the_requester_it_merged in WORKER_ACTIVITIES
    heard: list = []
    monkeypatch.setattr(acts.ProjectRegistry, "get",
                        lambda self, name: SimpleNamespace(name=name))
    monkeypatch.setattr(events, "merged_for_you",
                        lambda project, **kw: heard.append((project.name, kw)) or True)

    assert await ActivityEnvironment().run(
        acts.tell_the_requester_it_merged,
        MergedInput(project="acme", issue="500", pr_url=PR, stages_follow=True))
    assert heard == [("acme", {"card": "500", "pr_url": PR, "stages_follow": True})]
    assert events.PRODUCERS[events.MERGED].endswith("::tell_the_requester_it_merged")


# ── 8. in the client's words ────────────────────────────────────────────────────────────────────

def test_every_sentence_the_requester_reads_is_free_of_delivery_jargon():
    """`CLIENT_JARGON`: "what you tried in its preview", never the commit; "goes into the product",
    never the forge's verb. The card's note is the team's, and names both."""
    from openfactory.product.voice import (
        _ACCEPT_CHANGE_SAID,
        accept_change_confirmation,
        accept_change_controls,
        accept_change_done,
        accept_change_said,
        jargon_in,
        merged_for_you,
    )

    reasons = {"not_yours", accept.UNTRIED, accept.MOVED, accept.UNRECORDED, "unnoted",
               *accept.NOTHING_TO_ACCEPT}
    assert reasons <= set(_ACCEPT_CHANGE_SAID), "a reason the yes can be refused for has no words"
    for lang in ("en", "pt-BR"):
        said = [accept_change_said(r, ref="7", language=lang) for r in _ACCEPT_CHANGE_SAID]
        said += [accept_change_confirmation(number="7", merges=m, language=lang)
                 for m in (True, False)]
        said += [accept_change_done(ref="7", merging=m, unmerged=u, language=lang)
                 for m, u in ((True, False), (False, False), (False, True))]
        said += [*accept_change_controls(merges=True, language=lang).values()]
        said += [merged_for_you(ref="7", title="t", stages_follow=s, language=lang)
                 for s in (True, False)]
        leaked = {s: jargon_in(s) for s in said if jargon_in(s)}
        assert not leaked, leaked


def test_the_words_are_in_the_projects_language():
    from openfactory.product.voice import accept_change_controls, accept_change_said

    assert accept_change_controls(language="pt-BR")["accept"] == "Está certo — aceitar"
    assert "a prévia que você experimentou" in accept_change_said(
        accept.MOVED, ref="7", language="pt-BR")
    assert voice.merged_for_you(ref="7", stages_follow=True, language="pt-BR").startswith(
        "O #7: a mudança que você pediu agora faz parte do código do produto.")


def test_a_new_row_uses_one_definition_of_a_merge_wait_kind():
    """The stamp reads the gate the way the rows are written: a merge-wait action on a job whose
    state is a person's merge (`view._domain_state`)."""
    from openfactory.runtime.temporal import view as tv

    assert tv.MERGE_WAIT == "merge_wait"
    assert accept.at_the_gates([{**_gate_job("7"), "state": "merging"}]) == [None]


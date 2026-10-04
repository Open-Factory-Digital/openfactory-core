"""The requester's "not yet" at the last gate goes back into the loop as another pass — a new change
of the card — and never into a promise nobody keeps (#448, slice 4, behaviour 5).

WHAT WAS WRONG, read in the code slice 4's first part left. A change that merged and passed its
stages parks at the last gate before the product's users, and its requester is asked to try it.
Their "não funcionou" there:

  · closed the question and answered *"I will take this back to the team with what you said, and
    come back when it is fixed for you to check again"* (`voice.release_declined`) — and nothing
    took anything to anybody: no signal, no card, no record a pass could read;
  · left the job parked at the gate until its approval window elapsed, and then ON_HOLD;
  · could not be sent back the way slice 1 sends a change back, because the gate a person sends a
    card back from (`adjust.gate_of`) read only the merge gate — "nothing is waiting on you".

WHAT IS PROVEN HERE, on the real local board, the real ledger and acceptance store, the real
staging and confirmation path, the real `ProductModule` and the real `JobWorkflow` on a
time-skipping engine of its own — doubled only where something spends or leaves the machine: the
model's draft (slice 1's `_Drafter`), the engine's client where a workflow is not the thing under
test, and the activities a job runs:

  · "not yet" on the release question stages slice 1's proposal, drafted from the conversation and
    worded for a change already in — "as a new change; what is live stays as it is" — and promises
    nothing; where no pass can be sent it says why (spent, deaf, not theirs, nothing waiting);
  · their yes corrects the card's bar first, then delivers the last gate's own answer, sealed;
  · the seam refuses what the job would refuse, before any signal;
  · the job, on a sealed "not yet" with a pass left, continues as new: a NEW change of the card,
    from the base, on a branch of its own, with the words in its brief and the pass counted on the
    project's one budget; without the seal, or with the budget spent, it stays at the gate;
  · a run parked at the gate before the code existed replays, and is deaf, and says so.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import subprocess
import uuid
from types import SimpleNamespace

import pytest
from temporalio import activity

import openfactory.product.channel as pc
from openfactory.contracts import AgentRunResult, JobState, Manifest, RunResult, Ticket
from openfactory.contracts.checks import CiDecision
from openfactory.runtime.temporal.io import (
    AdjustInput,
    CoordinatorSayInput,
    HoldSyncInput,
    KnowledgeRefreshInput,
    MergeCheckInput,
    PreflightInput,
    PreflightVerdict,
    PromoteInput,
    ReleaseInput,
    ReviewPassInput,
    RunJobInput,
    TicketRef,
)
from openfactory.runtime.temporal.workflow import JobWorkflow

# SLICE 1'S PEOPLE, CARD AND DRAFTER — the same requester, the same pass and the same bar, so the
# last gate is proven to send back exactly what the merge gate does
from tests.test_the_requester_asks_for_another_pass import (
    ADMIN,
    ASKER,
    BAR,
    GOOD,
    INSTRUCTION,
    KEY,
    STRANGER,
    _criteria,
    _Drafter,
    _waiting_card,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT = "Nina"
URL = "https://qa.acme.example"
T0 = "2026-10-01T10:00:00+00:00"
NOT_YET = "not yet, the export button is still under the menu"
EARLIER = "I opened the list and looked for the export button on the toolbar"


# ── the deployment ───────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _nothing_staged():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Slice 1's deployment — a registered local project with a product role, whose board `project
    init` created — with the platform's own store, which holds the ledger the release question
    lives in."""
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
                         product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN],
                                               agent_name=AGENT)))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
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


# ── the engine's client, doubled: a job parked at its LAST gate ─────────────────────────────────

class _NotFound(Exception):
    """What the engine raises for a workflow that never ran (an `RPCError` in the SDK)."""


class _Parked:
    """One job parked at the last gate, publishing what `JobWorkflow` publishes there: no merge
    gate, the approval gate open, and the last gate's own word about "not yet" (`release_wait`)."""

    def __init__(self, *, passes: int = 2, spent: int = 0, hears: bool = True,
                 running: bool = True) -> None:
        self.passes, self.spent, self.hears, self.running = passes, spent, hears, running
        self.signals: list[tuple[str, list]] = []
        #: what the new change would READ when it starts — the run reads the card first
        self.reads = None
        self.read_at_signal: list = []

    def answer(self, query: str):
        if query == "awaiting_merge":
            return None
        if query == "awaiting_approval":
            return self.running
        if query == "release_wait":
            return {"adjust_passes": self.passes,
                    "adjusts_left": max(0, self.passes - self.spent), "hears": self.hears}
        raise AssertionError(f"the product side asked the job {query!r}")


def _name(what) -> str:
    return what if isinstance(what, str) else what.__name__


class _Handle:
    def __init__(self, engine: _Engine, wf_id: str) -> None:
        self.engine, self.wf_id = engine, wf_id

    def _job(self) -> _Parked:
        job = self.engine.jobs.get(self.wf_id)
        if job is None:
            raise _NotFound(f"workflow not found for ID: {self.wf_id}")
        return job

    async def describe(self):
        from temporalio.client import WorkflowExecutionStatus

        return SimpleNamespace(status=WorkflowExecutionStatus.RUNNING if self._job().running
                               else WorkflowExecutionStatus.COMPLETED)

    async def query(self, what):
        return self._job().answer(_name(what))

    async def signal(self, what, *, args):
        job = self._job()
        job.signals.append((_name(what), list(args)))
        if job.reads is not None:
            job.read_at_signal.append(job.reads())


class _Engine:
    def __init__(self) -> None:
        self.jobs: dict[str, _Parked] = {}

    def holds(self, card: str, job: _Parked) -> _Parked:
        from openfactory.runtime.temporal.view import job_id

        self.jobs[job_id("acme", str(card).lstrip("#"))] = job
        return job

    def get_workflow_handle(self, wf_id: str, run_id=None) -> _Handle:
        return _Handle(self, wf_id)


@pytest.fixture
def engine(monkeypatch) -> _Engine:
    """The client the product side keeps for its answers (`release._client`), doubled; the
    standing loop it runs on is the real one, forgotten before and after."""
    from openfactory.product import release
    from openfactory.runtime.temporal import standing

    fake = _Engine()

    async def _client():
        return fake

    monkeypatch.setattr(release, "_client", _client)
    standing._forget_the_standing_loop()
    yield fake
    standing._forget_the_standing_loop()


def _module(project, *drafts):
    from openfactory.product.module import ProductModule

    return ProductModule(project, agent=_Drafter(*drafts), via="panel")


def _at_the_last_gate(deployment, tracker, board, engine, job: _Parked | None = None):
    """A card asked for by ASKER, its change merged and parked at the last gate, and the release
    question asked in the room and of them, in their conversation — as the hourly round asks it."""
    from openfactory.memory import store as loop_store
    from openfactory.product import events, followup
    from openfactory.product.speaker import sealed

    card = _waiting_card(tracker, board, column="Needs Action")
    parked = engine.holds(card, job or _Parked())
    room = events.room_of(deployment)
    loop_store.write(deployment.name, [
        followup.release_of(card, channel=room, ts=T0, where=URL, run="run-1"),
        followup.release_of(card, channel=room, ts=T0, where=URL, conversation=KEY,
                            requester=sealed(ASKER), run="run-1")])
    return card, parked


def _say(deployment, module, text: str, *, who: str = ASKER, where: str = KEY) -> str:
    from tests.the_chat_turn import chat_turn

    return str(chat_turn(deployment, text=text, user=who, thread=where, module=module))


def _questions(deployment) -> dict:
    """Every release question's latest state, by where it was asked."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import ACCEPTANCE, fold
    from openfactory.product import followup

    return {x.about: x.outcome or x.state for x in fold(loop_store.read(deployment.name))
            if x.kind == ACCEPTANCE and followup.is_release(x)}


def _head() -> str:
    from openfactory.product.voice import engine_said

    return f"{AGENT}: " + engine_said("nothing_released", language="en") + "\n\n"


# ── 1. "not yet" is another pass, staged from the conversation ──────────────────────────────────

def test_the_requesters_not_yet_stages_another_pass_as_a_new_change_and_promises_nothing(
        deployment, tracker, board, engine):
    from openfactory.memory import transcript
    from openfactory.product import events

    card, job = _at_the_last_gate(deployment, tracker, board, engine)
    transcript.record(deployment, thread=KEY, role="person", text=EARLIER, actor=ASKER)
    module = _module(deployment, GOOD)

    asked = _say(deployment, module, NOT_YET)

    assert asked.startswith(_head()), asked
    assert (f"I'll send *#{card}* back for another pass (pass 1 of the 2 this project allows), "
            f"with these criteria as the bar:") in asked, asked
    assert "as a new change — what is live stays as it is — and correct the card to match" in asked
    assert all(f"- {c}" in asked for c in BAR) and INSTRUCTION in asked
    assert asked.rstrip().endswith("Confirm?")
    for promise in ("take this back to the team", "come back when"):
        assert promise not in asked, f"the reply still promises: {promise!r}"
    staged = pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1]
    assert (staged["kind"], staged["number"], staged["instruction"]) == ("adjust", card,
                                                                        INSTRUCTION)
    # DRAFTED FROM THE CONVERSATION, for a change already in (ADR-0054 D1)
    [(phase, prompt)] = module._agent.prompts
    assert phase == "product_adjust_draft" and NOT_YET in prompt and EARLIER in prompt
    assert "NEW change of the card" in prompt and "SAME pull request" not in prompt
    # THE QUESTION IS ANSWERED — both copies, the record that matters — and nothing moved yet
    assert _questions(deployment) == {events.room_of(deployment): "did-not-work",
                                      KEY: "did-not-work"}
    assert job.signals == [] and _criteria(tracker, card) != BAR


def test_their_yes_corrects_the_bar_then_sends_the_merged_change_back_sealed(
        deployment, tracker, board, engine):
    from openfactory import gate_seal
    from openfactory.runtime.temporal.view import job_id

    card, job = _at_the_last_gate(deployment, tracker, board, engine)
    job.reads = lambda: _criteria(tracker, card)
    module = _module(deployment, GOOD)
    _say(deployment, module, NOT_YET)

    said = _say(deployment, module, "yes")

    assert _criteria(tracker, card) == BAR, "the yes did not correct the card"
    assert job.read_at_signal == [BAR], (
        "the job was told before the bar moved — the new change reads the card when it starts")
    [(signal, (instruction, by, seal))] = job.signals
    assert (signal, instruction, by) == ("not_yet", INSTRUCTION, ASKER)
    assert gate_seal.refusal(seal, gate_seal.NOT_YET, job_id("acme", card), instruction, by) == ""
    assert said.startswith(f"sent #{card} back for pass 1 of 2, to change:"), said
    assert "It becomes a new change; what is live stays as it is" in said
    assert "same change" not in said
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None


@pytest.mark.parametrize("job,why", [
    (_Parked(passes=2, spent=2), "spent"),
    (_Parked(hears=False), "deaf"),
    (_Parked(running=False), "not_waiting"),
])
def test_where_no_pass_can_be_sent_the_reply_says_why_and_nothing_is_drafted(
        deployment, tracker, board, engine, job, why):
    from openfactory.product.voice import adjust_said

    card, _ = _at_the_last_gate(deployment, tracker, board, engine, job)
    module = _module(deployment, GOOD)

    said = _say(deployment, module, NOT_YET)

    reason = adjust_said(why, ref=card, passes=job.passes if why == "spent" else None,
                         language="en")
    assert said == _head() + reason[:1].upper() + reason[1:], said
    assert module._agent.prompts == [], "a draft was paid for that could not be sent"
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None
    assert job.signals == []


def test_somebody_who_did_not_ask_for_the_card_hears_it_is_not_theirs(deployment, tracker,
                                                                     board, engine):
    from openfactory.product.voice import adjust_said

    card, job = _at_the_last_gate(deployment, tracker, board, engine)
    module = _module(deployment, GOOD)

    said = _say(deployment, module, NOT_YET, who=STRANGER, where=f"person:{STRANGER}")

    reason = adjust_said("not_yours", ref=card, language="en")
    assert said == _head() + reason[:1].upper() + reason[1:], said
    assert module._agent.prompts == [] and job.signals == []


def test_the_card_offers_the_pass_at_the_last_gate_too(deployment, tracker, board, engine):
    card, _ = _at_the_last_gate(deployment, tracker, board, engine)

    view = _module(deployment).adjust_view(card, actor=ASKER)

    assert view["offered"] is True and (view["left"], view["passes"]) == (2, 2)


def test_a_that_s_it_at_the_last_gate_is_not_a_preview_acceptance(deployment, tracker, board,
                                                                   engine):
    """The requester's "that's it" (slice 3) is recorded against what they tried in a pull
    request's preview, and at the last gate there is none: it asks the merge gate alone, as before.
    Their yes there is the release question's (`engine._maybe_release`)."""
    from openfactory.product.voice import accept_change_said

    card, _ = _at_the_last_gate(deployment, tracker, board, engine)

    prepared = _module(deployment).prepare_acceptance(card, actor=ASKER)

    assert prepared.said == accept_change_said("not_waiting", ref=card, language="en")


# ── 2. the gate, read; the seam, refusing ───────────────────────────────────────────────────────

def test_the_last_gate_is_read_with_the_merge_gates_refusals():
    from openfactory.product import adjust

    assert adjust.read_release(None, card="7").why == adjust.NOT_WAITING
    assert adjust.read_release({"adjust_passes": 2, "adjusts_left": 2}, card="7").why == (
        adjust.DEAF), "a job that does not say it hears was read as one that does"
    assert adjust.read_release({"adjust_passes": 2, "adjusts_left": 0, "hears": True},
                               card="7").why == adjust.SPENT
    gate = adjust.read_release({"adjust_passes": 3, "adjusts_left": 1, "hears": True}, card="7")
    assert gate.open and gate.merged and (gate.passes, gate.left) == (3, 1)


class _OneHandle:
    """A job's handle as the seam reaches it, answering one set of queries."""

    def __init__(self, *, awaiting: bool = True, wait: dict | None = None,
                 running: bool = True) -> None:
        self.awaiting, self.wait, self.running = awaiting, wait, running
        self.id = ""
        self.signalled: list = []

    def get_workflow_handle(self, wf_id, run_id=None):
        self.id = wf_id
        return self

    async def describe(self):
        from temporalio.client import WorkflowExecutionStatus

        return SimpleNamespace(status=WorkflowExecutionStatus.RUNNING if self.running
                               else WorkflowExecutionStatus.COMPLETED)

    async def query(self, what):
        return self.awaiting if _name(what) == "awaiting_approval" else self.wait

    async def signal(self, what, *, args):
        self.signalled.append((_name(what), list(args)))


def _another_change(handle: _OneHandle):
    from openfactory.runtime.temporal import view as tv

    return asyncio.run(tv.another_change(handle, "acme", "7", instruction="x", by="ana"))


def test_the_seam_refuses_what_the_job_would_refuse_before_any_signal():
    from openfactory.runtime.temporal import view as tv

    with pytest.raises(RuntimeError, match="not waiting at its last gate"):
        _another_change(_OneHandle(awaiting=False))
    deaf = _OneHandle(wait={"adjust_passes": 2, "adjusts_left": 2, "hears": False})
    with pytest.raises(tv.GateDeaf):
        _another_change(deaf)
    spent = _OneHandle(wait={"adjust_passes": 2, "adjusts_left": 0, "hears": True})
    with pytest.raises(tv.AdjustsSpent):
        _another_change(spent)
    assert deaf.signalled == spent.signalled == []


def test_the_seam_seals_the_not_yet_for_this_job_alone():
    from openfactory import gate_seal

    handle = _OneHandle(wait={"adjust_passes": 2, "adjusts_left": 1, "hears": True})
    _another_change(handle)

    [(signal, (instruction, by, seal))] = handle.signalled
    assert (signal, instruction, by) == ("not_yet", "x", "ana")
    assert gate_seal.refusal(seal, gate_seal.NOT_YET, handle.id, "x", "ana") == ""
    assert gate_seal.refusal(seal, gate_seal.APPROVE_PROD, handle.id, "x", "ana") != "", (
        "a seal over a not-yet answers the release gate too")


def test_the_last_gate_is_read_only_of_a_running_job_parked_there():
    from openfactory.runtime.temporal import view as tv

    wait = {"adjust_passes": 2, "adjusts_left": 2, "hears": True}

    def read(**kw):
        return asyncio.run(tv.release_gate(_OneHandle(**kw), "acme", "7"))

    assert read(wait=wait) == wait
    assert read(wait=wait, running=False) is None, "a finished job was read as one still waiting"
    assert read(wait=wait, awaiting=False) is None


# ── 3. the job: a new change, from the base, on the one budget ──────────────────────────────────

TQ = "test-not-yet-at-the-last-gate"
#: every run of the job's agent, as `(another_pass, change)` — what reached the brief, and which
#: change of the card it built
_RUNS: list[tuple[str, int]] = []
_PREFLIGHTS: list[str] = []
_SAID: list[str] = []
#: a run of the agent that waits for the test — to send an answer before the job reaches its gate
_HOLD: list[asyncio.Event] = []


@activity.defn(name="run_job")
async def _run_job(inp: RunJobInput) -> RunResult:
    if _HOLD:
        await _HOLD[0].wait()
    _RUNS.append((inp.another_pass, inp.change))
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN,
                     pr_url=f"https://x/pr/{inp.change + 1}")


@activity.defn(name="preflight_check")
async def _preflight(inp: PreflightInput) -> PreflightVerdict:
    _PREFLIGHTS.append(inp.issue)
    return PreflightVerdict(verdict="fit")


@activity.defn(name="check_pr_status")
async def _merged(inp: MergeCheckInput) -> str:
    return "merged"


@activity.defn(name="read_ci_checks")
async def _green(inp: MergeCheckInput) -> CiDecision:
    return CiDecision(verdict="success")


@activity.defn(name="promote_staging")
async def _staged(inp: PromoteInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.AWAITING_PROD_APPROVAL)


@activity.defn(name="release_prod")
async def _released(inp: ReleaseInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.DONE)


@activity.defn(name="stop_job")
async def _stopped(inp: RunJobInput) -> int:
    return 1


@activity.defn(name="refresh_knowledge")
async def _refreshed(inp: KnowledgeRefreshInput) -> str:
    return "ok"


@activity.defn(name="fetch_ticket_title")
async def _title(inp: TicketRef) -> str:
    return "Export the list"


@activity.defn(name="notify_coordinator_say")
async def _say_it(inp: CoordinatorSayInput) -> None:
    _SAID.append(inp.text)


@activity.defn(name="record_outcome")
async def _journalled(inp: HoldSyncInput) -> None:
    return None


@activity.defn(name="tell_the_requester")
async def _told(inp) -> bool:
    return True


@activity.defn(name="tell_the_requester_it_merged")
async def _told_it_merged(inp) -> bool:
    return True


def _activities():
    from gate_answers import SEAL_CHECK

    return [SEAL_CHECK, _run_job, _preflight, _merged, _green, _staged, _released, _stopped,
            _refreshed, _title, _say_it, _journalled, _told, _told_it_merged]


@pytest.fixture
async def env():
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    for kept in (_RUNS, _PREFLIGHTS, _SAID, _HOLD):
        kept.clear()
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


async def _until(check):
    for _ in range(1500):
        got = await check()
        if got:
            return got
        await asyncio.sleep(0.02)
    raise AssertionError("the job never reached what the test waits for")


async def _at_the_gate(handle, *, runs: int):
    """The job's latest run parked at the last gate, after `runs` runs of its agent."""

    async def parked():
        if len(_RUNS) < runs or not await handle.query(JobWorkflow.awaiting_approval):
            return None
        return await handle.query(JobWorkflow.release_wait)

    return await _until(parked)


async def _not_yet(handle, instruction: str, by: str, *, seal: str | None = None) -> None:
    from openfactory import gate_seal

    sealed = gate_seal.seal(gate_seal.NOT_YET, handle.id, instruction, by) if seal is None else seal
    await handle.signal(JobWorkflow.not_yet, args=[instruction, by, sealed])


#: the first run of the last job started — the one a continued job leaves behind
_FIRST_RUN: list[str] = []


async def _start(env, params):
    h = await env.client.start_workflow(JobWorkflow.run, params, id=f"wf-{uuid.uuid4()}",
                                        task_queue=TQ)
    _FIRST_RUN[:] = [h.first_execution_run_id or h.result_run_id or ""]
    # THE LATEST RUN, whichever it is — the job continues as new under the same id
    return env.client.get_workflow_handle(h.id, result_type=RunResult)


def _params(**kw):
    from openfactory.runtime.temporal.io import JobParams

    return JobParams(project="p", issue="10", promote=True, approval_deadline_days=30,
                     **{"adjust_passes": 2, **kw})


@pytest.mark.owns_its_engine
async def test_a_sealed_not_yet_continues_the_job_as_a_new_change_from_the_base(env):
    from gate_answers import approve_prod
    from temporalio.worker import Worker

    from openfactory.techlead import voice as tl_voice

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, _params())
        first = await _at_the_gate(h, runs=1)
        assert first == {"adjust_passes": 2, "adjusts_left": 2, "hears": True}

        await _not_yet(h, INSTRUCTION, ASKER)
        second = await _at_the_gate(h, runs=2)
        await approve_prod(h, "1.0.0", "ana", "")
        result = await h.result()

    assert _RUNS == [("", 0), (INSTRUCTION, 1)], (
        "the new change did not carry the words, or was not a new change of the card")
    assert second["adjusts_left"] == 1, "the pass was not counted, or the budget started again"
    assert _PREFLIGHTS == ["10"], "a merged card was sized again — a split would close it"
    assert tl_voice.say(tl_voice.NARRATION, "prod.another-change", "", issue="10", n=1,
                        of=2) in _SAID
    assert result.state == JobState.DONE


@pytest.mark.owns_its_engine
async def test_a_not_yet_without_the_seal_is_dropped_and_the_gate_waits_on(env):
    from gate_answers import approve_prod, seal_checks_done
    from temporalio.worker import Worker


    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, _params())
        await _at_the_gate(h, runs=1)
        await _not_yet(h, INSTRUCTION, "mallory", seal="v1.0.forged.0")
        await _until(lambda: _checked(h, seal_checks_done))
        refused = await h.query(JobWorkflow.gate_refused)
        wait = await h.query(JobWorkflow.release_wait)
        await approve_prod(h, "1.0.0", "ana", "")
        result = await h.result()

    assert _RUNS == [("", 0)], "an unsealed not-yet sent the change back"
    assert refused and wait["refused"] == refused and wait["adjusts_left"] == 2
    assert result.state == JobState.DONE


async def _checked(h, seal_checks_done) -> bool:
    return await seal_checks_done(h) >= 1


@pytest.mark.owns_its_engine
async def test_past_the_budget_the_job_stays_at_the_last_gate_and_says_a_person_decides(env):
    from gate_answers import approve_prod, seal_checks_done
    from temporalio.worker import Worker

    from openfactory.runtime.temporal.vocabulary import release_passes_spent_note

    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, _params(adjust_passes=0))
        wait = await _at_the_gate(h, runs=1)
        # SENT STRAIGHT TO THE JOB, past the seam that would have refused it
        await _not_yet(h, INSTRUCTION, ASKER)
        await _until(lambda: _checked(h, seal_checks_done))
        still = await h.query(JobWorkflow.release_wait)
        await approve_prod(h, "1.0.0", "ana", "")
        result = await h.result()

    assert wait == {"adjust_passes": 0, "adjusts_left": 0, "hears": True,
                    "note": release_passes_spent_note(0)}
    assert still["adjusts_left"] == 0 and still["note"] == release_passes_spent_note(0)
    assert _RUNS == [("", 0)], "a pass past the project's budget was spent"
    assert result.state == JobState.DONE


@pytest.mark.owns_its_engine
async def test_a_not_yet_sent_before_the_job_reaches_its_gate_is_dropped(env):
    from gate_answers import approve_prod
    from temporalio.worker import Worker


    _HOLD.append(asyncio.Event())
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, _params())
        await _until(lambda: _picked_up(h))
        await _not_yet(h, INSTRUCTION, ASKER)
        _HOLD[0].set()
        await _at_the_gate(h, runs=1)
        assert await h.query(JobWorkflow.release_wait) == {
            "adjust_passes": 2, "adjusts_left": 2, "hears": True}
        await approve_prod(h, "1.0.0", "ana", "")
        result = await h.result()

    assert _RUNS == [("", 0)], "a not-yet that arrived before the gate fired when it opened"
    assert result.state == JobState.DONE


async def _picked_up(h) -> bool:
    from temporalio.api.enums.v1 import EventType

    async for event in h.fetch_history_events():
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
            return True
    return False


@pytest.mark.owns_its_engine
async def test_a_run_parked_before_it_could_hear_is_deaf_says_so_and_replays(env, monkeypatch):
    """A history recorded before the gate heard "not yet" — the patch absent at the gate, an input
    with none of the new fields — replays on this code, and the gate says it is deaf rather than
    taking an answer it cannot act on."""
    from gate_answers import approve_prod
    from temporalio import workflow as wf
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer, Worker

    from openfactory.runtime.temporal import view as tv
    from openfactory.runtime.temporal.workflow import _NOT_YET_AT_THE_LAST_GATE

    real = wf.patched
    monkeypatch.setattr(wf, "patched", lambda id: False if id == _NOT_YET_AT_THE_LAST_GATE
                        else real(id))
    old_input = _params().model_dump(mode="json")
    for field in ("another_pass", "passes_spent", "change"):
        del old_input[field]
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, old_input)
        wait = await _at_the_gate(h, runs=1)
        # past the seam, which would have refused it by name
        await _not_yet(h, INSTRUCTION, ASKER)
        with pytest.raises(tv.GateDeaf):
            await _raise_deaf(wait)
        await approve_prod(h, "1.0.0", "ana", "")
        result = await h.result()
        history = await h.fetch_history()
    monkeypatch.setattr(wf, "patched", real)

    assert wait == {"adjust_passes": 2, "adjusts_left": 2, "hears": False}
    assert _RUNS == [("", 0)] and result.state == JobState.DONE
    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)


async def _raise_deaf(wait: dict) -> None:
    """The seam's own reading of what a deaf gate published (`view.another_change`)."""
    from openfactory.runtime.temporal import view as tv

    await tv.another_change(_OneHandle(wait=wait), "p", "10", instruction="x", by="ana")


@pytest.mark.owns_its_engine
async def test_a_new_change_replays_on_this_code(env):
    from gate_answers import approve_prod
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer, Worker


    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow],
                      activities=_activities()):
        h = await _start(env, _params())
        await _at_the_gate(h, runs=1)
        await _not_yet(h, INSTRUCTION, ASKER)
        await _at_the_gate(h, runs=2)
        await approve_prod(h, "1.0.0", "ana", "")
        await h.result()
        first = env.client.get_workflow_handle(h.id, run_id=_FIRST_RUN[0])
        histories = [await first.fetch_history(), await h.fetch_history()]

    assert histories[0].events != histories[1].events, "the job did not continue as new"
    for history in histories:
        await Replayer(workflows=[JobWorkflow],
                       data_converter=pydantic_data_converter).replay_workflow(history)


# ── 4. the new change: its own branch, the words in its brief ───────────────────────────────────

def test_a_later_change_of_a_card_has_a_branch_of_its_own():
    from openfactory import namespace
    from openfactory.orchestrator.machine import JobRunner

    assert namespace.job_branch("#9") == namespace.job_branch("9", change=0) == "openfactory/9"
    assert namespace.job_branch("#9", change=1) == "openfactory/9-2"
    assert namespace.job_branch("CONT-12", change=2) == "openfactory/CONT-12-3"
    later = JobRunner.__new__(JobRunner)
    later.change = 1
    assert later._job_branch(Ticket(id="#9", title="t", objective="o", repo="o/app")) == (
        "openfactory/9-2")


def _git(args: list[str], cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_the_new_change_is_built_from_the_base_and_never_pushed_over_the_merged_one(tmp_path):
    """End to end, on a real repository: the card's first change is on `openfactory/1`, merged;
    the second is built from the base on `openfactory/1-2`, with the words in the agent's brief,
    and the first branch is exactly where it was."""
    from openfactory.adapters.agent.base import AgentContext
    from tests.test_walking_skeleton import FakeForge, FakeTracker, _runner

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t.dev"],
                 ["config", "user.name", "t"], ["remote", "add", "origin", str(origin)]):
        _git(args, repo)
    (repo / "README.md").write_text("# app\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "init"], repo)
    _git(["push", "-u", "origin", "main"], repo)
    _git(["checkout", "-b", "openfactory/1"], repo)
    (repo / "first.py").write_text("FIRST = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "the first change"], repo)
    _git(["push", "-u", "origin", "openfactory/1"], repo)
    merged = _git(["rev-parse", "HEAD"], repo)
    _git(["checkout", "main"], repo)
    _git(["merge", "--no-ff", "-m", "merge the first change", "openfactory/1"], repo)
    _git(["push", "origin", "main"], repo)

    seen: list[AgentContext] = []

    class _Agent:
        def execute(self, *, sandbox, workspace, context):
            seen.append(context)
            (workspace.path / "second.py").write_text("SECOND = 2\n")
            return AgentRunResult(ok=True, summary="the export button on the toolbar",
                                  cost_usd=0.01, actions=["Edit: second.py"])

        def repair(self, *, sandbox, workspace, context, failure_log):
            return AgentRunResult(ok=True)

    forge = FakeForge()
    from openfactory.contracts import AcceptanceCriterion

    ticket = Ticket(id="#1", title="export", objective="export it", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="the export is on the toolbar")])
    runner = _runner(repo, FakeTracker(ticket),
                     Manifest(validate={"test": "true", "security": "true"}), tmp_path,
                     agent=_Agent(), forge=forge)
    runner.change = 1

    result = runner.run("#1", another_pass=INSTRUCTION)

    assert result.state is JobState.PR_OPEN, result.note
    assert forge.opened["head"] == "openfactory/1-2" and forge.opened["base"] == "main"
    [context] = seen
    assert context.another_pass == INSTRUCTION
    assert _git(["rev-parse", "refs/heads/openfactory/1"], origin) == merged, (
        "the merged change's branch was pushed over")
    second = _git(["rev-parse", "refs/heads/openfactory/1-2"], origin)
    assert _git(["merge-base", "--is-ancestor", "main", second], origin) == "", (
        "the new change was not built from the base")


def test_the_brief_carries_the_words_fenced_beside_the_card():
    from openfactory.adapters.agent.base import AgentContext, ticket_brief

    ticket = Ticket(id="#1", title="export", objective="export it", repo="o/app")
    brief = ticket_brief(AgentContext(ticket=ticket, another_pass=INSTRUCTION))
    plain = ticket_brief(AgentContext(ticket=ticket))

    heading = "### Still wrong in this card's last change, which is already merged"
    assert heading in brief and INSTRUCTION in brief
    assert brief.index(heading) < brief.index(INSTRUCTION)
    assert heading not in plain


# ── 5. every runner of the job finds the change's branch ────────────────────────────────────────

@pytest.fixture
def worker_side(monkeypatch):
    """The worker's activities with the card's runner doubled — what they build it with, kept."""
    import openfactory.runtime.temporal.activities as acts

    built: list[dict] = []
    project = SimpleNamespace(name="p", knowledge_experiment=False)
    monkeypatch.setattr(acts, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: project))
    monkeypatch.setattr(acts, "_ref_repo", lambda _p, _i: ("acme/x", ""))
    monkeypatch.setattr(acts, "_runner_view", lambda _p, _i: (project, ""))
    monkeypatch.setattr(acts, "_resolved_image", lambda _p, sandbox: "")
    monkeypatch.setattr(acts, "installed_box_traits", lambda _s: SimpleNamespace(remote=False))

    def runner(*a, **kw):
        built.append({"change": kw.get("change", 0)})

        def run(issue, **ran):
            built[-1].update(ran)
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN)

        def repair_ci(issue, ci_log, pr_url="", human=False):
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)

        def review_pr(issue, pr_url=""):
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)

        return SimpleNamespace(run=run, repair_ci=repair_ci, review_pr=review_pr,
                               knowledge_arm=lambda: None)

    monkeypatch.setattr(acts, "build_runner", runner)
    return SimpleNamespace(acts=acts, built=built)


def test_the_run_the_adjust_and_the_re_review_are_built_for_the_same_change(worker_side):
    acts = worker_side.acts

    acts._do_run_job(RunJobInput(project="p", issue="12", sandbox="worktree", change=1,  # noqa: SLF001
                                 another_pass=INSTRUCTION))
    acts._run_adjust(AdjustInput(project="p", issue="12", pr_url="https://x/pr/2",  # noqa: SLF001
                                 sandbox="worktree", instruction="move it", change=1))
    acts._run_review_pass(ReviewPassInput(project="p", issue="12",  # noqa: SLF001
                                          pr_url="https://x/pr/2", sandbox="worktree", change=1))

    assert [b["change"] for b in worker_side.built] == [1, 1, 1]
    assert worker_side.built[0]["another_pass"] == INSTRUCTION


def test_a_remote_box_is_told_which_change_and_what_is_still_wrong():
    import openfactory.runtime.temporal.activities as acts
    from openfactory.runtime import boxed_job

    assert acts._the_change_env(0) == {}  # noqa: SLF001 — a first change launches as before
    env = acts._the_change_env(1, INSTRUCTION)  # noqa: SLF001
    assert env == {"OPENFACTORY_CHANGE": "1", "OPENFACTORY_ANOTHER_PASS": INSTRUCTION}
    cfg = boxed_job.config_from_env({"OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "12",
                                     "OPENFACTORY_REPO": "acme/x", **env})
    assert (cfg.change, cfg.another_pass) == (1, INSTRUCTION)
    assert boxed_job._of_the_change(cfg) == {"change": 1}  # noqa: SLF001
    first = boxed_job.config_from_env({"OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "12",
                                       "OPENFACTORY_REPO": "acme/x",
                                       "OPENFACTORY_CHANGE": "junk"})
    assert (first.change, boxed_job._of_the_change(first)) == (0, {})  # noqa: SLF001


def test_every_input_for_the_cards_pull_request_says_which_change_it_is():
    """PARSED, so a repair, an adjust or a re-review added later without the change number fails
    here: its runner would recalculate the FIRST change's branch and push a fix nobody watches."""
    missing, sites = [], []
    for rel in ("openfactory/runtime/temporal/workflow.py",
                "openfactory/runtime/temporal/activities.py"):
        for node in ast.walk(ast.parse((ROOT / rel).read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("CiRepairInput", "AdjustInput", "ReviewPassInput")):
                sites.append(f"{rel}:{node.lineno}")
                if "change" not in {kw.arg for kw in node.keywords}:
                    missing.append(f"{rel}:{node.lineno}")
    assert len(sites) >= 4, f"the scan found {sites} — it is looking at the wrong tree"
    assert not missing, f"these build a pass for the first change's branch: {missing}"

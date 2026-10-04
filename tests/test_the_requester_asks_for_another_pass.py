"""The person who asked for a card sends its change back for another pass — from the conversation
and from the card — and the number of passes is the project's (#448, slice 1).

WHAT WAS WRONG, measured live on card #1000007 (2026-09-30). The requester tried the preview and
said in the conversation what was still wrong. The product role understood — it named the loose
criterion it had written and rewrote the two criteria — then said *"I can't edit the card or its
acceptance criteria myself; that has to go back through #1000007 as a request for changes."* The
requester could not do that either:

  · the merge gate's `adjust` was a floor row, an operator's alone (`actions/base.py`: FLOOR, admin);
  · the product role had no gesture for it;
  · `correct_card` refused every card the factory had taken up, so the bar the re-review judges
    against could not be corrected;
  · a third pass was refused by a constant (`_ADJUST_MAX = 2`) with "2 adjust passes already spent".

WHAT IS PROVEN HERE, on the real local board, the real staging and confirmation path and the real
`JobWorkflow` on a time-skipping engine — doubled only where something spends or leaves the
machine: the model's reading and its draft, and the engine's client where a workflow is not the
thing under test:

  · the budget is the project's (`adjust_passes` in the registry), stamped on every job a door
    starts, and a job whose input predates it keeps today's 2 and replays;
  · past the budget a person decides — said by the job, refused at the seam every answer crosses,
    and said to the requester in their conversation and on their card, never a bare refusal;
  · `correct_card` corrects the bar of a card ONLY at its merge gate, by the engine's word, and only
    the bar; a job running on the card still refuses it;
  · the requester, a product admin and a vouched operator may send a card back; nobody else may;
  · the conversation: the role's `[[AJUSTE: #N]]` stages the pass and the bar drafted from the
    conversation, the requester's own yes corrects the card and sends the pass, sealed;
  · the card on the product view offers the same act to the same people, in the project's language.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import uuid
from types import SimpleNamespace

import pytest
from temporalio import activity

import openfactory.product.channel as pc
from openfactory.contracts import AgentRunResult, JobState, RunResult
from openfactory.contracts.checks import CiDecision
from openfactory.runtime.temporal.io import (
    AdjustInput,
    CoordinatorSayInput,
    HoldSyncInput,
    MergeCheckInput,
    RunJobInput,
    TicketRef,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL = (ROOT / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")

#: The person who asked for the card, the product admin, and somebody who is neither.
ASKER, ADMIN, STRANGER = "ana-asked-77", "po-admin-12", "somebody-else-42"
KEY = "person:ana-asked-77"
PR = "https://forge.example/acme/pull/7"
INSTRUCTION = "Put the export button on the right of the toolbar, beside the print button."
BAR = ["The export button sits on the right of the toolbar, beside the print button",
       "Exporting downloads a CSV with every row the list shows"]


@pytest.fixture(autouse=True)
def _nothing_staged():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a product role, whose board `project init` created."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.board import forget_board
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path), language="en",
                         tracker=ProviderRef(kind="local", repo="acme", options={}),
                         product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN])))
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


# ── the engine's client, doubled: the jobs it holds and every answer it was sent ────────────────

class _NotFound(Exception):
    """What the engine raises for a workflow that never ran (an `RPCError` in the SDK)."""


class _Job:
    """One job at its merge gate, publishing what `JobWorkflow` publishes there (`awaiting_merge`)
    and counting the passes it was sent, as the workflow does."""

    def __init__(self, *, passes: int = 2, spent: int = 0, working: bool = False,
                 running: bool = True, auto: bool = False, numbers: bool = True) -> None:
        self.passes, self.spent, self.working = passes, spent, working
        self.running, self.auto, self.numbers = running, auto, numbers
        self.signals: list[list] = []
        #: what the pass would READ when it starts — `machine.repair_ci` reads the card first
        self.reads = None
        self.read_at_signal: list = []

    def merge_wait(self) -> dict:
        wait = {"pr_url": PR, "auto": self.auto, "gate_live": True,
                "note": "waiting for your merge"}
        if self.numbers:
            wait.update(adjust_passes=self.passes, adjusts_left=max(0, self.passes - self.spent))
        if self.working:
            wait["working"] = True
        return wait


class _Handle:
    def __init__(self, engine: _Engine, wf_id: str) -> None:
        self.engine, self.wf_id = engine, wf_id

    def _job(self) -> _Job:
        job = self.engine.jobs.get(self.wf_id)
        if job is None:
            raise _NotFound(f"workflow not found for ID: {self.wf_id}")
        return job

    async def describe(self):
        from temporalio.client import WorkflowExecutionStatus

        return SimpleNamespace(status=WorkflowExecutionStatus.RUNNING if self._job().running
                               else WorkflowExecutionStatus.COMPLETED)

    async def query(self, _what):
        return self._job().merge_wait()

    async def signal(self, _what, *, args):
        job = self._job()
        job.signals.append(list(args))
        if job.reads is not None:
            job.read_at_signal.append(job.reads())
        if args and args[0] == "adjust":
            job.spent += 1


class _Engine:
    def __init__(self) -> None:
        self.jobs: dict[str, _Job] = {}

    def holds(self, card: str, job: _Job) -> _Job:
        from openfactory.runtime.temporal.view import job_id

        self.jobs[job_id("acme", str(card).lstrip("#"))] = job
        return job

    def get_workflow_handle(self, wf_id: str, run_id=None) -> _Handle:
        return _Handle(self, wf_id)


@pytest.fixture
def engine(monkeypatch) -> _Engine:
    """The client the product side keeps for its answers (`release._client`, #201), doubled; the
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


class _Drafter:
    """The model the pass is drafted with: hands back the drafts it was given, in order, and keeps
    every prompt, so a test proves what the model was shown — and that it was not asked at all."""

    name = "drafter"

    def __init__(self, *drafts) -> None:
        self.drafts, self.prompts = list(drafts), []

    def ask(self, *, sandbox, workspace, prompt, phase="ask"):
        self.prompts.append((phase, prompt))
        answer = self.drafts.pop(0) if self.drafts else "{}"
        return AgentRunResult(ok=True, summary=answer if isinstance(answer, str)
                              else json.dumps(answer))


GOOD = {"instruction": INSTRUCTION, "criteria": BAR}


def _module(project, *drafts):
    from openfactory.product.module import ProductModule

    return ProductModule(project, agent=_Drafter(*drafts), via="panel")


def _waiting_card(tracker, board, *, column: str = "In review", body: str = "") -> str:
    """A card the product role opened from a request, asked for by ASKER, in `column`."""
    from openfactory.product.authoring import ticket_body

    body = body or (ticket_body(described="an export button on the list", reported_by=ASKER,
                                source="chat")
                    + "\n## Acceptance criteria\n\n- There is a way to export the list\n")
    ref = tracker.create_ticket(title="Export the list", body=body, requester=ASKER)
    board.set_column(issue=ref, issue_url="", name=column)
    return ref.lstrip("#")


def _criteria(tracker, ref: str) -> list[str]:
    return [c.text for c in tracker.get_ticket(ref).acceptance_criteria]


def _act(name: str, *, who: str, product: bool = True, admin: bool = False, **params):
    from openfactory import actions
    from openfactory.policy.authz import PRODUCT

    by = actions.Actor(id=who, display=who, via="panel", admin=admin,
                       scopes=frozenset({PRODUCT}) if product else None)
    return asyncio.run(actions.perform(name, by=by, **params))


def _sealed(job: _Job, ref: str, *, by: str) -> tuple[str, str]:
    """The one answer the job was sent: its instruction, and whether the worker's own check passes
    its seal (`gate_seal.refusal`, which `verify_gate_seal` asks)."""
    from openfactory import gate_seal
    from openfactory.runtime.temporal.view import job_id

    [(answer, instruction, said_by, seal)] = job.signals
    assert answer == "adjust" and said_by == by, job.signals
    return instruction, gate_seal.refusal(seal, gate_seal.MERGE_GATE, job_id("acme", ref),
                                          answer, instruction, said_by)


# ── 1. the budget is the project's ──────────────────────────────────────────────────────────────

def test_a_project_that_says_nothing_keeps_todays_two_passes():
    from openfactory.contracts.project import ADJUST_PASSES, Project
    from openfactory.runtime.temporal.io import JobParams
    from openfactory.runtime.temporal.workflow import JobWorkflow

    assert ADJUST_PASSES == 2 == JobWorkflow._ADJUST_MAX
    assert Project(name="a", repo_path=".").adjust_passes == 2
    # A HISTORY THAT PREDATES THE FIELD is deserialised exactly like this: the payload has no key
    assert JobParams.model_validate({"project": "a", "issue": "1"}).adjust_passes == 2


@pytest.mark.parametrize("said,kept", [(5, 5), (0, 0), (99, 10), (-3, 0), ("three", 2),
                                       (None, 2)])
def test_the_registrys_budget_is_clamped_and_a_bad_one_is_the_default(said, kept):
    """One bad line in a registry nobody can open must not make every project unloadable."""
    from openfactory.contracts.project import Project

    assert Project(name="a", repo_path=".", adjust_passes=said).adjust_passes == kept


def test_every_door_that_starts_a_job_stamps_the_projects_budget():
    """PARSED, so a launch site added later without the budget fails here: a job started without
    it silently runs on 2 whatever the project says — measured, the panel's scan and start rows
    never stamped the project's `language` either, which is the shape of this defect."""
    sites, missing = [], []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "JobParams"):
                where = f"{path.relative_to(ROOT)}:{node.lineno}"
                sites.append(where)
                if "adjust_passes" not in {kw.arg for kw in node.keywords}:
                    missing.append(where)
    assert len(sites) >= 4, f"the scan found {sites} — it is looking at the wrong tree"
    assert not missing, f"these doors start a job without the project's budget: {missing}"


def test_the_poller_starts_a_job_with_the_budget_its_project_declares(monkeypatch):
    """Behavioural, from the launch site the unattended factory uses (`start_jobs`)."""
    import openfactory.runtime.temporal.activities as acts
    from openfactory.contracts.project import Project
    from openfactory.runtime.temporal.io import StartJobsInput
    from tests.in_a_worker import run_in_a_worker

    started: list = []

    class _Client:
        async def start_workflow(self, _name, params, **kw):
            started.append(params)

    monkeypatch.setattr(acts.ProjectRegistry, "get",
                        lambda self, name: Project(name="acme", repo_path="/tmp/acme",
                                                   adjust_passes=5))
    run_in_a_worker(acts.start_jobs, StartJobsInput(project="acme", issues=["12"],
                                                    sandbox="container"), client=_Client())

    assert [p.adjust_passes for p in started] == [5]


# ── 2. the seam every answer crosses refuses a pass the job would refuse ────────────────────────

class _GateOnly:
    def __init__(self, gate: dict) -> None:
        self.gate, self.signalled = gate, []

    def get_workflow_handle(self, *a, **k):
        outer = self

        class _H:
            async def query(self, *a, **k):
                return outer.gate

            async def signal(self, _what, *, args):
                outer.signalled.append(args)

        return _H()


def test_an_adjust_past_the_budget_is_refused_before_the_signal():
    from openfactory.runtime.temporal import view as tv

    spent = _GateOnly({"pr_url": PR, "auto": False, "adjust_passes": 3, "adjusts_left": 0})
    with pytest.raises(tv.AdjustsSpent) as caught:
        asyncio.run(tv.answer_merge_gate(spent, "acme", "7", answer="adjust",
                                         instruction="x", by="op"))
    assert caught.value.passes == 3 and spent.signalled == [], "the doomed answer was delivered"

    # a job whose binary predates the numbers is sent the answer, and its own branch decides
    older = _GateOnly({"pr_url": PR, "auto": False})
    asyncio.run(tv.answer_merge_gate(older, "acme", "7", answer="adjust", instruction="x",
                                     by="op"))
    assert len(older.signalled) == 1
    # and the other answers are never refused for it: past the budget a person merges or discards
    other = _GateOnly({"pr_url": PR, "auto": False, "adjust_passes": 3, "adjusts_left": 0})
    asyncio.run(tv.answer_merge_gate(other, "acme", "7", answer="discard", by="op"))
    assert len(other.signalled) == 1


def test_the_floor_is_told_what_happens_next_not_only_what_was_refused(monkeypatch):
    from openfactory.actions import catalog

    spent = _GateOnly({"pr_url": PR, "auto": False, "adjust_passes": 2, "adjusts_left": 0})

    async def _connected():
        return spent, None

    monkeypatch.setattr(catalog, "_connected", _connected)
    monkeypatch.setattr(catalog, "_project", lambda p: (SimpleNamespace(name="acme"), None))
    gate, bad = asyncio.run(catalog._answer_gate(project="acme", issue="7", by="op",
                                                 answer="adjust", instruction="x"))

    assert gate is None and bad.code == "conflict"
    assert "the 2 extra passes this project allows" in bad.message
    assert "a person decides now" in bad.message and "discard" in bad.message
    assert "may have merged already" not in bad.message, "a waiting job read as one that ended"


# ── 3. `correct_card` moves the bar at the merge gate, and only there ───────────────────────────

def _gate(ref: str, **kw):
    from openfactory.product.adjust import Gate

    return Gate(card=ref, pr_url=PR, passes=2, left=2, **kw)


def test_the_bar_of_a_card_at_its_merge_gate_is_corrected_and_what_it_said_is_kept(
        deployment, tracker, board):
    from openfactory.product.module import ProductModule

    ref = _waiting_card(tracker, board)
    before = tracker.get_ticket(ref).raw

    done = ProductModule(deployment).correct_card(ref, actor=ADMIN, criteria=BAR,
                                                  gate=_gate(ref))

    assert done.ok and not done.existed, done.detail
    assert _criteria(tracker, ref) == BAR
    after = tracker.get_ticket(ref).raw
    assert after.count("## Acceptance criteria") == 1, "a second set of criteria was appended"
    assert before.split("## Acceptance criteria")[0] == after.split("## Acceptance criteria")[0], (
        "the correction of the bar rewrote what was asked")
    [note] = [c.body for c in tracker.comments(ref)]
    assert "There is a way to export the list" in note, "the note lost what the bar said before"
    assert "another pass" in note, "the note does not say the bar moved with a pass"


@pytest.mark.parametrize("why", ["working", "spent", "not_waiting"])
def test_a_card_whose_job_is_not_waiting_on_a_person_is_refused_as_today(
        deployment, tracker, board, why):
    """A pass rewriting the change, no pass left, or no job waiting: the column says the factory
    took the card up, and nothing says a person is being asked — the target must not move."""
    from openfactory.product.module import ProductModule

    ref = _waiting_card(tracker, board)
    out = ProductModule(deployment).correct_card(ref, actor=ADMIN, criteria=BAR,
                                                 gate=_gate(ref, why=why))

    assert not out.ok and "the factory has picked it up" in out.detail, out.detail
    assert _criteria(tracker, ref) == ["There is a way to export the list"]


def test_no_gate_and_another_cards_gate_and_a_text_change_are_all_refused(
        deployment, tracker, board):
    from openfactory.product.module import ProductModule

    ref = _waiting_card(tracker, board)
    module = ProductModule(deployment)
    for out in (module.correct_card(ref, actor=ADMIN, criteria=BAR),
                module.correct_card(ref, actor=ADMIN, criteria=BAR, gate=_gate("9999")),
                module.correct_card(ref, actor=ADMIN, text="another export", gate=_gate(ref)),
                module.correct_card(ref, actor=ADMIN, text="x", criteria=BAR, gate=_gate(ref))):
        assert not out.ok and "the factory has picked it up" in out.detail, out.detail
    assert _criteria(tracker, ref) == ["There is a way to export the list"]


def test_a_portuguese_card_keeps_the_name_its_criteria_were_written_under(
        deployment, tracker, board):
    """#429: the card keeps the language it was written in."""
    from openfactory.product.authoring import ticket_body
    from openfactory.product.module import ProductModule

    body = (ticket_body(described="um botão de exportar", reported_by=ASKER, source="chat")
            + "\n## Critérios de aceite\n\n- Dá para exportar a lista\n")
    ref = _waiting_card(tracker, board, body=body)

    assert ProductModule(deployment).correct_card(ref, actor=ADMIN, criteria=BAR,
                                                  gate=_gate(ref)).ok
    raw = tracker.get_ticket(ref).raw
    assert "## Critérios de aceite" in raw and "## Acceptance criteria" not in raw
    assert _criteria(tracker, ref) == BAR


def test_the_requester_may_move_their_own_cards_bar_at_the_gate_and_nobody_else(
        deployment, tracker, board):
    from openfactory.product.module import ProductModule

    ref = _waiting_card(tracker, board)
    module = ProductModule(deployment)

    assert not module.correct_card(ref, actor=STRANGER, criteria=BAR, gate=_gate(ref)).ok
    assert not module.correct_card(ref, actor=ASKER, criteria=BAR).ok, (
        "the requester moved the bar with no gate — outside the pass it travels with")
    assert module.correct_card(ref, actor=ASKER, criteria=BAR, gate=_gate(ref)).ok
    assert _criteria(tracker, ref) == BAR


# ── 4. the conversation: the role reads "not yet", the requester's yes sends the pass ───────────

class _Role:
    """The product role's READING of a message, scripted — the one thing a model decides in a turn.
    Everything it hands the engine to act on is the real module's: the gate, the draft from the
    conversation, the correction, the pass."""

    def __init__(self, module, *, says: str, card: str) -> None:
        self.module, self.says, self.card = module, says, card

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

        return ProductAnswer(ok=True, text=self.says, gesture="adjust", gesture_card=self.card)


TRIED = "I tried it. The export button is hidden under the menu; it should be on the toolbar."
UNDERSTOOD = ("You are right — the criterion I wrote only said there is a way to export, so the "
              "button under the menu met it. It should be on the toolbar, beside print.")


def _say(deployment, role, text: str, *, who: str = ASKER) -> str:
    from tests.the_chat_turn import chat_turn

    return str(chat_turn(deployment, text=text, user=who, thread=KEY, module=role))


def test_the_requester_says_not_yet_and_their_yes_corrects_the_card_and_sends_the_pass(
        deployment, tracker, board, engine):
    """THE ISSUE'S BEHAVIOUR 1, end to end: no operator is needed."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job(passes=2))
    job.reads = lambda: _criteria(tracker, ref)
    module = _module(deployment, GOOD)
    role = _Role(module, says=UNDERSTOOD, card=ref)

    asked = _say(deployment, role, TRIED)

    staged = pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1]
    assert staged["kind"] == "adjust" and staged["number"] == ref, staged
    assert staged["criteria"] == BAR and staged["instruction"] == INSTRUCTION
    assert asked.startswith(UNDERSTOOD), "the role's own understanding is not in front"
    assert (f"I'll send *#{ref}* back for another pass (pass 1 of the 2 this project allows), "
            f"with these criteria as the bar:") in asked, asked
    assert all(f"- {c}" in asked for c in BAR) and "and correct the card to match" in asked
    assert INSTRUCTION in asked and asked.rstrip().endswith("Confirm?")
    [(phase, prompt)] = module._agent.prompts
    assert phase == "product_adjust_draft" and TRIED in prompt and UNDERSTOOD in prompt
    assert "There is a way to export the list" in prompt, "the draft did not see the card's bar"
    assert job.signals == [] and _criteria(tracker, ref) != BAR, "something moved before the yes"

    said = _say(deployment, role, "yes")

    assert _criteria(tracker, ref) == BAR, "the yes did not correct the card"
    assert job.read_at_signal == [BAR], (
        "the pass was sent before the bar moved — it reads the card when it starts, and would "
        "build to the old criteria")
    instruction, refused = _sealed(job, ref, by=ASKER)
    assert instruction == INSTRUCTION and refused == "", f"the worker would refuse it: {refused}"
    assert said.startswith(f"sent #{ref} back for pass 1 of 2, to change:"), said
    assert "I corrected the card to say what it must meet" in said
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None


def test_past_the_budget_the_requester_hears_what_happens_next_and_nothing_is_spent(
        deployment, tracker, board, engine):
    """BEHAVIOUR 3: the wall is a conversation, not an error — and no draft is paid for."""
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job(passes=3, spent=3))
    module = _module(deployment, GOOD)

    said = _say(deployment, _Role(module, says=UNDERSTOOD, card=ref), TRIED)

    assert said.startswith(UNDERSTOOD)
    assert f"#{ref} has had the 3 extra passes this project allows for one change" in said
    assert "What happens next is a person's decision" in said and "Nothing more is spent" in said
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None, (
        "a pass that cannot be sent was staged for a yes")
    assert module._agent.prompts == [] and job.signals == []


@pytest.mark.parametrize("job,heard", [
    (_Job(working=True), "is in a pass right now"),
    (_Job(running=False), "is waiting on you right now"),
    (_Job(auto=True), "is waiting on you right now"),
    (None, "is waiting on you right now"),
])
def test_a_card_no_change_of_which_waits_on_the_person_is_said_so(
        deployment, tracker, board, engine, job, heard):
    ref = _waiting_card(tracker, board)
    if job is not None:
        engine.holds(ref, job)

    said = _say(deployment, _Role(_module(deployment, GOOD), says=UNDERSTOOD, card=ref), TRIED)

    assert heard in said, said
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None


def test_somebody_who_did_not_ask_for_the_card_cannot_send_it_back(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job())

    said = _say(deployment, _Role(_module(deployment, GOOD), says="I see.", card=ref), TRIED,
                who=STRANGER)

    assert f"only the person who asked for #{ref}" in said, said
    assert job.signals == []


def test_a_requesters_yes_on_somebody_elses_proposal_is_still_refused(deployment, engine):
    """The requester rule admits THEIR OWN card's pass — never a yes on another kind of proposal,
    which still needs an approver, and never another card's pass."""
    from openfactory.product.confirm import _may_say_yes

    other = SimpleNamespace(may_send_back=lambda number, actor: number == "7")
    assert _may_say_yes(deployment, {"kind": "adjust", "number": "7"}, ASKER, via="panel",
                        module=other) == ""
    assert "only the person who asked for #8" in _may_say_yes(
        deployment, {"kind": "adjust", "number": "8"}, ASKER, via="panel", module=other)
    assert _may_say_yes(deployment, {"kind": "close", "number": "7"}, ASKER, via="panel",
                        module=other) != ""
    assert _may_say_yes(deployment, {"kind": "close", "number": "7"}, ADMIN, via="panel",
                        module=other) == ""


def test_two_passes_with_different_words_are_two_proposals():
    """The click's fingerprint is the proposal's summary: a button posted for one pass must not
    send another with other words or another bar."""
    from openfactory.product.staging import proposal_token

    one = {"kind": "adjust", "number": "7", "instruction": "a", "criteria": ["x"]}
    assert proposal_token("k", one) != proposal_token("k", {**one, "instruction": "b"})
    assert proposal_token("k", one) != proposal_token("k", {**one, "criteria": ["x", "y"]})


def test_a_draft_that_fails_the_floor_is_redrafted_once_then_the_person_is_asked(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job())
    module = _module(deployment, {"instruction": "", "criteria": []}, "not json at all")

    said = _say(deployment, _Role(module, says=UNDERSTOOD, card=ref), TRIED)

    assert len(module._agent.prompts) == 2, "the floor's problems were not handed to a redraft"
    assert "`instruction` is empty" in module._agent.prompts[1][1]
    assert f"I could not turn what is still wrong with #{ref} into a pass" in said
    assert pc.find_waiting(KEY, KEY, project=deployment, person=ASKER)[1] is None
    assert job.signals == []


def test_the_floor_refuses_a_pass_with_no_bar_or_more_words_than_it_takes():
    """No model can switch it off: a draft with no criteria, or an instruction the pass would be
    cut at, is never shown for a yes."""
    from openfactory.product.adjust import INSTRUCTION_LIMIT, floor

    assert floor({"instruction": "x", "criteria": ["c"]})[0] is not None
    none, problems = floor({"instruction": "x", "criteria": ["  ", ""]})
    assert none is None and any("`criteria` is empty" in p for p in problems)
    none, problems = floor({"instruction": "x" * (INSTRUCTION_LIMIT + 1), "criteria": ["c"]})
    assert none is None and any(f"at most {INSTRUCTION_LIMIT}" in p for p in problems)
    assert floor("an answer in prose")[0] is None


def test_an_instruction_longer_than_a_pass_takes_is_refused_by_its_size(
        deployment, tracker, board, engine):
    from openfactory.product.adjust import INSTRUCTION_LIMIT

    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job())

    out = _act("product_adjust", who=ASKER, project="acme", number=ref,
               instruction="x" * (INSTRUCTION_LIMIT + 1))

    assert not out.ok and f"that is {INSTRUCTION_LIMIT + 1} characters" in out.message
    assert job.signals == []


def test_the_marker_is_read_into_the_answer_and_never_reaches_the_person(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _harness = _answering_module(
        tmp_path, answer="Got it, the button is in the wrong place.\n[[AJUSTE: #1000007]]")

    answer = mod.answer("the export button is hidden under the menu")

    assert (answer.gesture, answer.gesture_card) == ("adjust", "1000007")
    assert "[[AJUSTE" not in answer.text and answer.text == (
        "Got it, the button is in the wrong place.")


# ── 5. the card on the product view: the same act, the same people ──────────────────────────────

def test_the_card_view_offers_the_pass_to_the_requester_with_its_bar_to_edit(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    engine.holds(ref, _Job(passes=3, spent=1))

    view = _act("product_board", who=ASKER, project="acme", card=ref).data["card"]["adjust"]

    assert view["offered"] and view["corrects"] and (view["left"], view["passes"]) == (2, 3)
    assert view["criteria"] == ["There is a way to export the list"]
    assert view["words"]["adjust"] == "Send back for another pass"
    assert "2 of the 3 this project allows are left" in view["words"]["note"]
    assert _act("product_board", who=STRANGER, project="acme",
                card=ref).data["card"]["adjust"] == {"offered": False}


def test_a_card_the_factory_has_not_taken_up_asks_the_engine_nothing(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board, column="Backlog")
    engine.holds(ref, _Job())

    card = _act("product_board", who=ASKER, project="acme", card=ref).data["card"]

    assert "adjust" not in card


def test_the_requester_sends_it_back_from_the_card_and_the_bar_moves_with_it(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job(passes=2))

    out = _act("product_adjust", who=ASKER, project="acme", number=ref, instruction=INSTRUCTION,
               criteria="\n".join(f"- {c}" for c in BAR))

    assert out.ok, out.message
    assert out.message.startswith(f"sent #{ref} back for pass 1 of 2, to change:"), out.message
    assert _criteria(tracker, ref) == BAR
    instruction, refused = _sealed(job, ref, by=ASKER)
    assert instruction == INSTRUCTION and refused == ""


def test_an_operator_may_send_it_back_from_the_product_view_and_a_stranger_may_not(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job())

    out = _act("product_adjust", who=STRANGER, project="acme", number=ref, instruction="x")
    assert not out.ok and f"only the person who asked for #{ref}" in out.message, out.message
    assert job.signals == []

    out = _act("product_adjust", who="op-1", product=False, admin=True, project="acme",
               number=ref, instruction=INSTRUCTION)
    assert out.ok, out.message
    _sealed(job, ref, by="op-1")


def test_past_the_budget_the_card_says_a_person_decides_and_offers_no_button(
        deployment, tracker, board, engine):
    ref = _waiting_card(tracker, board)
    job = engine.holds(ref, _Job(passes=2, spent=2))

    view = _act("product_board", who=ASKER, project="acme", card=ref).data["card"]["adjust"]
    assert view["offered"] is False and "What happens next is a person's decision" in view["note"]

    out = _act("product_adjust", who=ASKER, project="acme", number=ref, instruction=INSTRUCTION,
               criteria="\n".join(BAR))
    assert not out.ok and "What happens next is a person's decision" in out.message
    assert job.signals == [] and _criteria(tracker, ref) != BAR, (
        "the bar moved for a pass that was never sent")


def test_the_controls_words_are_in_the_projects_language():
    from openfactory.product.voice import adjust_controls, adjust_said

    pt = adjust_controls(left=1, passes=2, language="pt-BR")
    assert pt["adjust"] == "Mandar para mais uma passada" and "Restam 1 das 2" in pt["note"]
    assert "decisão de uma pessoa" in adjust_said("spent", ref="7", passes=2, language="pt-BR")


def test_every_sentence_the_requester_reads_is_free_of_delivery_jargon():
    """`CLIENT_JARGON`: the change, never the forge's pull request; never the template's heading."""
    from openfactory.product import adjust
    from openfactory.product.voice import (
        _ADJUST_SAID,
        adjust_confirmation,
        adjust_controls,
        adjust_said,
        adjust_sent,
        jargon_in,
    )

    assert adjust.WHY <= set(_ADJUST_SAID), "a reason the gate can give has no sentence"
    for lang in ("en", "pt-BR"):
        said = [adjust_said(r, ref="7", passes=2, length=9, limit=8, language=lang)
                for r in _ADJUST_SAID]
        said += [adjust_sent(ref="7", instruction="i", number=1, passes=2, corrected=True,
                             language=lang),
                 adjust_confirmation(number="7", instruction="i", criteria=["c"], pass_number=1,
                                     passes=2, language=lang),
                 *[adjust_confirmation(number="7", instruction="i", keeps=k, language=lang)
                   for k in ("requirement", "board")],
                 *adjust_controls(left=1, passes=2, language=lang).values()]
        leaked = {s: jargon_in(s) for s in said if jargon_in(s)}
        assert not leaked, leaked


def test_the_instruction_limit_is_the_one_the_workflow_cuts_at():
    from openfactory.actions import catalog
    from openfactory.product.adjust import INSTRUCTION_LIMIT
    from openfactory.runtime.temporal import workflow

    assert INSTRUCTION_LIMIT == workflow._ADJUST_CHARS == catalog._ADJUST_MAX_CHARS


def test_the_product_view_is_DRIVEN_open_the_card_send_it_back_see_the_answer_there():
    """The card's control, executed under node on the page's own functions: offered with the
    server's words, the person types what is still wrong and edits the bar, the row is
    `product_adjust` with both, and the answer stays on the card."""
    from tests.test_a_refusal_is_not_an_answer import run

    words = {"close": "Close card", "remove": "Remove from the board", "confirm": "Confirm",
             "cancel": "Cancel", "reason": "Why?", "ask_close": "c", "ask_remove": "r",
             "note": "n"}
    adjust = {"offered": True, "corrects": True, "left": 2, "passes": 2,
              "criteria": ["There is a way to export the list"],
              "words": {"adjust": "Send back for another pass", "send": "Send",
                        "cancel": "Cancel", "instruction": "What is still wrong?",
                        "criteria": "What must be true", "ask": "Say what is still wrong.",
                        "note": "This change is waiting on you."}}
    card = {"ref": "7", "readable": True, "title": "Export the list", "body": "asked",
            "state": "open", "column": "In review", "opened_by_product": "request",
            "started": True, "removes": True, "words": words, "adjust": adjust}
    stubs = ("let _prod={project:'acme'},_bd={};"
             "let _pv={board:undefined,boardMsg:'',card:null,ask:null,said:null,adjusting:null};"
             f"const CARD={json.dumps(card)};const acts=[];"
             "async function act(name,params){acts.push([name,params]);"
             "if(name==='product_adjust'){CARD.adjust={offered:false};"
             "return {ok:true,message:'sent #7 back for pass 1 of 2, to change: the button',"
             "data:{}}}"
             "return {ok:true,message:'',data:{cards:[{ref:'7',title:CARD.title,"
             "column:'In review'}],card:params.card?CARD:null}}}")
    got = run("nodes['#pvBoard']=node();"
              "await pvCardOpen('7');const opened=nodes['#pvBoard'].innerHTML;"
              "pvAdjustAsk();const asking=nodes['#pvBoard'].innerHTML;"
              "_pv.adjusting.instruction='the button';"
              "_pv.adjusting.criteria='It sits on the toolbar';await pvAdjustSend();"
              "return {opened,asking,after:nodes['#pvBoard'].innerHTML,acts}",
              "pvCardOpen", "pvCardRead", "paintPvBoard", "_bcontrols", "pvAdjustBlock",
              "pvAdjustAsk", "pvAdjustSend", "pvAcceptBlock", stubs=stubs)

    assert "Send back for another pass" in got["opened"] and "This change is waiting on you." in (
        got["opened"]), got["opened"]
    assert 'id="pv_instruction"' in got["asking"] and 'id="pv_criteria"' in got["asking"]
    assert "There is a way to export the list" in got["asking"], "the bar is not there to edit"
    assert ["product_adjust", {"project": "acme", "number": "7", "instruction": "the button",
                               "criteria": "It sits on the toolbar"}] in got["acts"], got["acts"]
    assert "sent #7 back for pass 1 of 2" in got["after"], "the answer did not stay on the card"
    assert "Send back for another pass" not in got["after"], "a spent control is still offered"


@pytest.mark.parametrize("left,offered", [(0, ["merge", "discard"]),
                                           (1, ["merge", "adjust", "discard"]),
                                           (None, ["merge", "adjust", "discard"])])
def test_the_floors_inbox_offers_adjust_only_while_a_pass_is_left(tmp_path, monkeypatch, left,
                                                                    offered):
    """`/api/inbox`, executed: the options every channel renders read the job's `adjusts_left` —
    and a job too old to say keeps the answer it always had."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)

    async def _connect():
        return object()

    async def _jobs(_client, _ns):
        action = {"pr_url": PR, "auto": False}
        if left is not None:
            action.update(adjust_passes=2, adjusts_left=left)
        # `attention` as `view.list_jobs` answers it for a live run at a gate (#339)
        return [{"project": "acme", "issue": "7", "title": "t", "state": "awaiting_your_merge",
                 "attention": True, "action": action}]

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "list_jobs", _jobs)

    row = next(r for r in TestClient(app).get("/api/inbox").json() if r["kind"] == "merge")

    assert [o["key"] for o in row["options"]] == offered


@pytest.mark.parametrize("left,offered", [(0, ["merge", "discard"]),
                                           (1, ["merge", "adjust", "address", "discard"])])
def test_address_spends_the_same_budget_and_the_inbox_survives_it_spent(tmp_path, monkeypatch,
                                                                         left, offered):
    """`address` (#330) is the adjust pass with its words from the pull request, so it is offered
    beside `adjust` and only while a pass is left. Measured when #330 and this slice met: the
    inbox removed `adjust` past the budget and then looked it up to place `address` after it — a
    `ValueError`, and an inbox that answered nothing."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKEN", raising=False)

    async def _connect():
        return object()

    async def _jobs(_client, _ns):
        return [{"project": "acme", "issue": "7", "title": "t", "state": "awaiting_your_merge",
                 "attention": True,
                 "action": {"pr_url": PR, "auto": False, "can_address": True,
                            "adjust_passes": 2, "adjusts_left": left}}]

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "list_jobs", _jobs)

    row = next(r for r in TestClient(app).get("/api/inbox").json() if r["kind"] == "merge")

    assert [o["key"] for o in row["options"]] == offered


def test_the_floors_address_button_reads_the_same_number():
    gate = PANEL.split('parked.action.kind=="merge_wait"')[1].split("} else if(parked)")[0]
    assert "(a.can_address&&a.adjusts_left!==0?" in gate, (
        "the Address button is drawn whatever passes are left")


def test_the_floors_own_button_reads_the_same_number():
    """The panel's floor row, read where it draws the gate's buttons: no pass left, no Adjust."""
    gate = PANEL.split('parked.action.kind=="merge_wait"')[1].split("} else if(parked)")[0]
    adjust = gate[gate.index("a.adjusts_left===0"):]
    assert adjust.index('data-k="adjust"') < adjust.index("`)+"), (
        "the Adjust button is drawn outside the condition on the passes left")


# ── 6. the real job: the budget is read, and a job that predates it replays ────────────────────

TQ = "test-another-pass"


async def _run_to_the_gate(env, params, answers: list[tuple[str, str]]):
    """A real `JobWorkflow` on the human path, held at its gate (checks green, the merge blocked),
    answered in order — each answer once the job has READ THE CHECKS AGAIN after the last one, so
    the gate looked at is the one rebuilt after that answer was acted on, never the one before."""
    from gate_answers import SEAL_CHECK, answer_merge_gate
    from temporalio.worker import Worker

    from openfactory.runtime.temporal.workflow import JobWorkflow

    async def until(check):
        for _ in range(400):
            got = await check()
            if got:
                return got
            await asyncio.sleep(0.05)
        raise AssertionError("the job never reached what the test waits for")

    gates: list[dict] = []
    async with Worker(env.client, task_queue=TQ, workflows=[JobWorkflow], activities=[
            SEAL_CHECK, *_JOB_MOCKS]):
        h = await env.client.start_workflow("JobWorkflow", params, id=f"wf-{uuid.uuid4()}",
                                            task_queue=TQ, result_type=RunResult)
        read_at_answer = 0
        for n, (answer, by) in enumerate(answers):
            async def at_the_gate(after=read_at_answer):
                gate = await h.query(JobWorkflow.awaiting_merge)
                return gate if (gate and _READS[0] > after and not gate.get("working")
                                and "adjusts_left" in gate) else None
            gates.append(await until(at_the_gate))
            read_at_answer = _READS[0]
            await answer_merge_gate(h, answer, f"pass {n + 1}" if answer == "adjust" else "", by)
        result = await h.result()
        history = await h.fetch_history()
    return gates, result, history


@activity.defn(name="run_job")
async def _run_job(inp: RunJobInput) -> RunResult:
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=PR,
                     branch="openfactory/7", auto_merge=False)


#: how many times the job read its checks — once per round of its watch
_READS = [0]


@activity.defn(name="read_ci_checks")
async def _green(inp: MergeCheckInput) -> CiDecision:
    _READS[0] += 1
    return CiDecision(verdict="success")


@activity.defn(name="pr_mergeable_state")
async def _blocked(inp: MergeCheckInput) -> str:
    return "blocked"


@activity.defn(name="check_pr_status")
async def _still_open(inp: MergeCheckInput) -> str:
    return "open"


#: the instruction of every pass the job ran
_PASSES: list[str] = []


@activity.defn(name="adjust_pr")
async def _adjust_pr(inp: AdjustInput) -> RunResult:
    _PASSES.append(inp.instruction)
    return RunResult(ticket_id=inp.issue, state=JobState.PR_OPEN, pr_url=inp.pr_url)


@activity.defn(name="close_pr")
async def _close(inp: MergeCheckInput) -> None:
    return None


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


_JOB_MOCKS = [_run_job, _green, _blocked, _still_open, _adjust_pr, _close, _settle, _mark,
              _title, _say_it]


@pytest.fixture
async def env():
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    _PASSES.clear()
    _READS[0] = 0
    e = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    try:
        yield e
    finally:
        await e.shutdown()


@pytest.mark.owns_its_engine
async def test_the_job_spends_the_projects_budget_and_past_it_a_person_decides(env):
    """`adjust_passes: 1`: one pass, then the gate publishes none left, the seam refuses, and an
    answer that got past it anyway is refused by the job with what happens next."""
    from openfactory.runtime.temporal import view as tv
    from openfactory.runtime.temporal.io import JobParams

    params = JobParams(project="acme", issue="7", merge_deadline_days=3650, adjust_passes=1)
    gates, result, _ = await _run_to_the_gate(
        env, params, [("adjust", "ana"), ("adjust", "ana"), ("discard", "ana")])

    assert (gates[0]["adjust_passes"], gates[0]["adjusts_left"]) == (1, 1)
    assert "a person decides" not in gates[0]["note"], "a pass was left and the gate said none"
    assert (gates[1]["adjust_passes"], gates[1]["adjusts_left"]) == (1, 0)
    assert "a person decides now: merge it as it is, or discard it" in gates[1]["note"], gates[1]
    # the second adjust was sent straight to the job, past the seam: the job refused it itself
    assert _PASSES == ["pass 1"], f"the job spent {len(_PASSES)} passes on a budget of one"
    assert "a person decides now" in gates[2]["note"], gates[2]
    # and the seam refuses on what the job published, before any signal
    with pytest.raises(tv.AdjustsSpent):
        await tv.answer_merge_gate(_GateOnly(gates[1]), "acme", "7", answer="adjust",
                                   instruction="x", by="ana")
    assert result.state.value == "skipped"


@pytest.mark.owns_its_engine
async def test_a_job_whose_input_predates_the_budget_keeps_two_and_replays(env):
    """A job started before `adjust_passes` existed carries no such key in its input. It reads 2,
    spends two passes, refuses the third with what happens next — and its history replays on this
    code: reading a field with a default issued no command a recorded job did not."""
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer

    from openfactory.runtime.temporal.io import JobParams
    from openfactory.runtime.temporal.workflow import JobWorkflow

    # THE INPUT AS AN OLD STARTER WROTE IT: every field the model had then, and no budget
    old_input = JobParams(project="acme", issue="7", merge_deadline_days=3650).model_dump(
        mode="json")
    del old_input["adjust_passes"]
    gates, result, history = await _run_to_the_gate(
        env, old_input, [("adjust", "ana"), ("adjust", "ana"), ("adjust", "ana"),
                         ("discard", "ana")])

    assert [g["adjusts_left"] for g in gates[:3]] == [2, 1, 0]
    assert _PASSES == ["pass 1", "pass 2"]
    assert "the 2 extra passes this project allows" in gates[3]["note"]
    await Replayer(workflows=[JobWorkflow],
                   data_converter=pydantic_data_converter).replay_workflow(history)

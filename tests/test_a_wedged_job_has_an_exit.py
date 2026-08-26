"""A job nothing can reach can be ended, without opening the engine (#127).

Found while fixing sweep B5. A wedged job — a workflow-task failure loop — holds the single-slot
floor for ever, and no row in the catalogue could end one: `resume` and `skip` answer a PARK (the
engine refuses them with CONFLICT otherwise), the merge-gate verbs answer a GATE, and `stop_job`
existed as an activity about Fargate cleanup, reachable by no human surface.

So the tech-lead's rounds ended up saying, honestly, *"the way out is in the engine: open Temporal
and terminate #42's workflow"*. True — and a raw-engine operation asked of an operator on the one
surface this product promises they will never need. "Open the engine and terminate" is not a
sentence for a client's operator.

THE ROW REFUSES A JOB THAT IS MERELY WAITING, and that refusal is its whole safety. A park has
resume/skip; a merge gate has merge/adjust/discard; a production gate has an authenticated
approval. Terminating any of them would destroy a job somebody was about to advance, under a verb
that sounds like tidying up.

IT IS NOT REVERSIBLE AND EVERY SURFACE SAYS SO. `discard` can afford a softer sentence because
`gh pr close` leaves the branch; a terminated workflow does not resume — the ticket goes back to
the board and a fresh job starts from the beginning.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory import actions
from openfactory.actions.base import Actor
from openfactory.actions.floor_intents import FLOOR_ROWS, match_floor_intent

ADMIN = Actor(id="rob", display="Rob", via="panel", admin=True)


# ── 1. the row exists, is gated, and is reachable ───────────────────────────────────────────────

def test_the_catalogue_has_a_row_that_ends_a_RUNNING_job():
    spec = actions.spec("stop")
    assert spec is not None, "a wedged job's only exit is still the raw engine"
    assert spec.required == ("project", "issue")
    assert spec.needs_admin, "anybody can terminate a running job"
    assert spec.scope == "floor"


def test_the_summary_says_it_does_not_resume():
    """An operator picks from `openfactory actions` and from a button's tooltip. A verb that
    silently loses a run is one somebody presses to tidy up."""
    said = actions.spec("stop").summary.lower()
    assert "cannot resume" in said or "does not resume" in said or "back to the board" in said


def test_a_typed_sentence_reaches_it():
    """#120's plumbing — the same door the merge verbs use."""
    assert FLOOR_ROWS.get("stop") == "stop"
    assert match_floor_intent("mata o job #87") == ("stop", {"ref": "87"})


@pytest.mark.parametrize("said", [
    "stop", "para o #87", "o job parou", "pode matar?", "não mata o 87", "mata o job",
    "encerra o ticket", "stop the noise", "non-stop 3", "vamos abortar essa ideia",
])
def test_it_never_fires_on_a_sentence_that_is_not_an_ORDER_naming_a_job(said):
    """The asymmetry of mistakes, at its sharpest. A missed `merge` costs a rephrase; a false
    `stop` costs a run that cannot be brought back. So: the ref is REQUIRED, bare verbs are
    conversation, `para` (the Portuguese preposition "for") is excluded outright, and a hyphen is
    not a word boundary — `\\bstop` matched "non-stop 3" and read it as an order to kill job 3."""
    got = match_floor_intent(said)
    assert got is None or got[0] != "stop", f"{said!r} was read as an order to terminate: {got}"


def test_the_ref_is_REQUIRED_by_the_pattern_and_not_by_a_caller():
    """A caller-side check is one a second caller forgets. The pattern itself cannot match without
    a ticket — which is also why the routing does not need to disambiguate."""
    assert match_floor_intent("mata o job") is None
    assert match_floor_intent("mata o job 87") == ("stop", {"ref": "87"})


# ── 2. it refuses a job that is merely waiting ──────────────────────────────────────────────────

class _Handle:
    def __init__(self, status="running", answers=None, terminated=None):
        self._status = status
        self._answers = answers or {}
        self.terminated = terminated if terminated is not None else []
        self.id = "openfactory-p-87"

    async def describe(self):
        class D:
            status = self._status
        return D()

    async def query(self, name):
        return self._answers.get(name)

    async def terminate(self, reason=""):
        self.terminated.append(reason)


class _Client:
    def __init__(self, handle):
        self.handle = handle

    def get_workflow_handle(self, _wf_id):
        return self.handle


@pytest.fixture
def engine(monkeypatch):
    """A running job at no gate, with the project resolved and the tracker stubbed out."""
    from openfactory.actions import catalog

    class Project:
        name = "p"

    monkeypatch.setattr(catalog, "_project", lambda name: (Project(), None))
    holder: dict = {}

    def _connect(handle):
        async def _c():
            return _Client(handle), None
        monkeypatch.setattr(catalog, "_connected", _c)
        holder["handle"] = handle
        return handle

    monkeypatch.setattr(catalog, "_settle_after_stop",
                        lambda *a, **kw: _settled(holder))
    return _connect


async def _settled(holder):
    holder["settled"] = True
    return True


def _stop(**kw):
    import asyncio

    from openfactory.actions import catalog

    return asyncio.run(catalog._stop(by=ADMIN, project="p", issue="87", **kw))


def test_a_wedged_job_is_terminated_and_the_floor_is_freed(engine):
    from openfactory.runtime.temporal.view import WorkflowExecutionStatus

    handle = engine(_Handle(status=WorkflowExecutionStatus.RUNNING))

    outcome = _stop(reason="the worker was rebuilt under it")

    assert outcome.ok, outcome.message
    assert handle.terminated, "nothing was terminated"
    assert "Rob" in handle.terminated[0] and "rebuilt" in handle.terminated[0], (
        "the engine's own record does not say who stopped it or why")
    assert outcome.data["freed"] is True
    assert "does not resume" in outcome.message.lower() or "not resume" in outcome.message


@pytest.mark.parametrize("gate,verb", [
    ("awaiting_action", "resume"),
    ("awaiting_merge", "merge"),
    # NOT `prod_approval`. The first version of this refusal returned `HUMAN_GATES`' own values,
    # so it told the reader to "answer it with `prod_approval`" — an internal label no surface
    # parses. Teaching a verb nothing accepts is the defect the merge gate paid for, reproduced
    # inside the refusal written to prevent a worse one.
    ("awaiting_approval", "Approve button"),
])
def test_a_job_WAITING_ON_A_PERSON_is_refused_and_told_the_right_verb(engine, gate, verb):
    """The safety of the whole row. Every one of these has its own answer, and terminating one
    would destroy a job somebody was about to advance."""
    from openfactory.runtime.temporal.view import WorkflowExecutionStatus

    handle = engine(_Handle(status=WorkflowExecutionStatus.RUNNING,
                            answers={gate: {"pr_url": "x"} if gate != "awaiting_approval" else True}))

    outcome = _stop()

    assert not outcome.ok and outcome.code == "conflict"
    assert not handle.terminated, "it terminated a job that was waiting on a person"
    assert verb in outcome.message, (
        f"it refuses without naming the verb that DOES answer this: {outcome.message}")
    assert "not stuck" in outcome.message


def test_a_job_that_is_NOT_RUNNING_is_refused(engine):
    from openfactory.runtime.temporal.view import WorkflowExecutionStatus

    handle = engine(_Handle(status=WorkflowExecutionStatus.COMPLETED))

    outcome = _stop()
    assert not outcome.ok and outcome.code == "conflict"
    assert not handle.terminated


def test_the_gates_are_read_from_the_SHARED_table():
    """A second list of gate names here would mean a gate added to the workflow is silently
    terminable — the failure `test_the_round_asks_about_EVERY_gate` exists for, one door along."""
    from openfactory.actions import catalog

    src = inspect.getsource(catalog._what_it_is_waiting_on)
    assert "HUMAN_GATES" in src
    for literal in ('"awaiting_merge"', '"awaiting_approval"'):
        assert literal not in src.split("return {")[0], f"it re-spells {literal}"


# ── 3. the ticket is settled, and a failure to settle is REPORTED ───────────────────────────────

def test_the_outcome_says_when_the_TICKET_could_not_be_updated(engine, monkeypatch):
    """The workflow is already terminated. Refusing to say so because the tracker blinked would
    leave the operator believing nothing happened — worse than a card in the wrong column."""
    from openfactory.actions import catalog
    from openfactory.runtime.temporal.view import WorkflowExecutionStatus

    engine(_Handle(status=WorkflowExecutionStatus.RUNNING))

    async def _no(*_a, **_kw):
        return False

    monkeypatch.setattr(catalog, "_settle_after_stop", _no)
    outcome = _stop()

    assert outcome.ok, "the stop itself happened and must be reported as done"
    assert outcome.data["settled"] is False
    assert "by hand" in outcome.message


def test_settling_puts_the_ticket_somewhere_a_PERSON_finds_it():
    from openfactory.actions import catalog

    src = inspect.getsource(catalog._settle_after_stop)
    assert "JobState.SKIPPED" in src, (
        "a stopped job's ticket is left in whatever column the run had reached")
    assert "tracker.comment" in src, "nothing on the ticket says who stopped it or why"
    assert "return False" in src, "a tracker that refused is reported as success"


# ── 4. the surfaces ─────────────────────────────────────────────────────────────────────────────

def test_the_panel_offers_it_on_a_WEDGED_job():
    from pathlib import Path

    from openfactory.api import app as api

    code = "\n".join(ln for ln in
                     (Path(inspect.getfile(api)).parent / "panel.html").read_text().splitlines()
                     if not ln.lstrip().startswith("//"))
    assert "stopJob(" in code and "/api/act/stop" in code
    assert "j.wedged" in code, (
        "the panel decides for itself which job is stuck — the server and the tech-lead's rounds "
        "already agreed on one answer")
    # IN THE STOP HANDLER'S OWN BODY. Checked across the whole page, this passed because a
    # different button (accepting a requirement) has a confirm of its own — a guard satisfied by
    # somebody else's code. And the CONDITION, not the word: `if(false&&!confirm(…))` keeps the
    # substring and asks nothing.
    body = code[code.index("async function stopJob("):]
    body = body[:body.index("\n  }")]
    assert "if(!confirm(" in body, (
        "an irreversible action is one click away with no question asked")
    assert "not resume" in body.lower(), "the question does not say what pressing it costs"


def test_the_ENGINE_decides_what_wedged_means_and_uses_ONE_constant():
    """A number in the browser and a number in the rounds would disagree by next month, and the
    operator would be told a job is wedged on a screen that offers them nothing."""
    from openfactory.runtime.temporal import view as tv
    from openfactory.techlead.watch import LONG_RUNNING_HOURS

    assert tv._WEDGED == float(LONG_RUNNING_HOURS)
    # THE ASSIGNMENT, NOT THE SUBSTRING (guard audit, 2026-08-17): `"is_wedged(" in getsource`
    # was satisfied by this file's own comment inside `list_jobs` mentioning the call — the row
    # could stop carrying the answer while a comment kept the guard green.
    import ast
    import inspect as _inspect

    tree = ast.parse(_inspect.cleandoc("\n" + _inspect.getsource(tv.list_jobs)))
    carried = any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "wedged" for t in n.targets)
        and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "is_wedged"
        for n in ast.walk(tree))
    assert carried, "the row no longer carries is_wedged's answer"


def _row(hours, *, action=None, live=True):
    from datetime import UTC, datetime, timedelta

    return {"action": action, "start_time": (datetime.now(UTC) - timedelta(hours=hours))
            .isoformat()}, live


@pytest.mark.parametrize("hours,action,live,expect", [
    (30, None, True, True),                         # the case the card is about
    (1, None, True, False),                         # a job that is simply working
    (30, {"kind": "merge_wait"}, True, False),      # at a gate — the platform working
    (30, {"kind": "impediment"}, True, False),      # parked — resume/skip answer it
    (30, None, False, False),                       # already closed; nothing to terminate
])
def test_what_counts_as_WEDGED_is_a_rule_that_can_be_read(hours, action, live, expect):
    """ASSERTED BY CALLING IT. While this lived inline in `list_jobs`, the only thing a guard
    could check was that the assignment existed — and a mutation replacing it with `False` passed
    every one of them while the Stop button quietly vanished from a floor nobody could clear."""
    from openfactory.runtime.temporal.view import is_wedged

    row, is_live = _row(hours, action=action, live=live)
    assert is_wedged(row, live=is_live) is expect


def test_a_job_with_NO_START_TIME_is_never_called_wedged():
    """Zero, not infinity. Offering to terminate a job on the strength of an unparseable
    timestamp is the expensive direction of this feature."""
    from openfactory.runtime.temporal import view as tv

    assert tv._hours_since(None) == 0.0
    assert tv._hours_since("not a time") == 0.0


def test_the_TECH_LEAD_stops_telling_people_to_open_the_engine():
    from openfactory.techlead import voice

    for language in ("en", "pt-BR"):
        said = voice.say(voice.FINDING, "wedged.action", language, ticket="42")
        assert "Temporal" not in said and "engine" not in said.lower(), (
            f"[{language}] it still sends an operator to the raw engine: {said}")
        assert "stop" in said.lower()
        assert "42" in said


def test_the_tech_lead_may_PROPOSE_it_and_says_what_it_costs():
    """It is in the vocabulary because a wedged job is exactly the case where one click from a
    human is the whole remedy — and the guidance has to say the click is not undoable."""
    from openfactory.techlead import conversation as conv

    assert "stop" in actions.proposable(ADMIN)
    said = actions.CATALOG["stop"].choose_when.lower()
    assert said, "`stop` is offered with no word on when to choose it"
    assert "not resume" in said and "waiting" in said
    # …and it reaches the prompt, which is the half a map beside it could not guarantee (#172).
    assert said[:40] in conv._guidance(("stop",)).lower()


def test_the_snapshot_tells_a_WEDGED_job_apart_from_a_slow_one():
    """Without this the tech-lead proposes terminating work that is simply taking a while."""
    from openfactory.techlead import conversation as conv

    slow = conv.state_snapshot([{"issue": "5", "state": "running", "title": "big one"}])
    stuck = conv.state_snapshot([{"issue": "5", "state": "running", "title": "big one",
                                  "wedged": True}])
    assert "WEDGED" not in slow
    assert "WEDGED" in stuck and "stop" in stuck

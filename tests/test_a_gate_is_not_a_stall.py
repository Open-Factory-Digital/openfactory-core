"""A job waiting for a person is not a job that is stuck (pilot, 2026-08-16).

His pull request sat at the merge gate overnight — healthy, on screen, one button away — and the
hourly round announced it to him:

    *#87* rodando há 10h sem parar nem terminar — mais do que qualquer passada real leva
    Preciso de vocês: não consegui identificar a causa, então não vou tentar de novo às cegas.
    Responda `resume` para eu tentar de novo depois de ajustar, ou `skip` para liberar a fila.

Every clause of that is false. It was not running, there is no cause, and `resume`/`skip` are not
what a merge gate accepts — `contracts/commands.py` excludes merge and release from the channel
grammar on purpose, so following that instruction would have typed a command his own channel
cannot parse.

THE MECHANISM. The gatherer asked one query, `awaiting_action`, which is the PARK query.
`view.answer_merge_gate` states the trap in its own docstring — *"THE MERGE GATE IS NOT A PARK …
`awaiting_action` is None"* — so a job at a gate is indistinguishable from a job that is working,
and after `LONG_RUNNING_HOURS` it became the wedged-job alarm that `test_a_wedged_job_is_seen`
exists to raise. That alarm is right about a workflow-task failure loop and catastrophic about a
person taking a night to decide.

The production gate is the same shape and worse: it waits `approval_deadline_days` = 3 BY DESIGN.

The pure function was never wrong — `test_a_wedged_job_is_seen` passes a ready-made `long_running`
list. Nothing tested what PUT a job in it.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openfactory.runtime.temporal import view as tv
from openfactory.techlead.watch import (
    GATE_WAIT_HOURS,
    LONG_RUNNING_HOURS,
    STUCK,
    WAITING,
    AtAGate,
    FloorState,
    report,
    watch,
    worth_saying,
)


def _findings(*, language=None, **kw):
    return watch(FloorState(**kw), language=language)


# ── 1. the sentence ─────────────────────────────────────────────────────────────────────────────

def test_a_pull_request_waiting_for_its_author_is_not_reported_as_stuck():
    found = _findings(at_a_gate=[AtAGate(ticket="87", hours=LONG_RUNNING_HOURS + 4, gate="merge")])
    assert [f.kind for f in found] == [WAITING], (
        "a healthy gate is being announced with the wedged-job alarm")
    assert found[0].resumable is False, (
        "the factory must not offer to press a gate that is deliberately human")


@pytest.mark.parametrize("forbidden", ["resume", "skip", "não consegui identificar",
                                       "sem parar nem terminar"])
def test_the_gate_message_never_borrows_the_stall_vocabulary(forbidden):
    """Each of these is a sentence the pilot was actually sent about a healthy job."""
    f = _findings(at_a_gate=[AtAGate("87", 14.0, "merge")])[0]
    text = f"{f.detail} {f.action}".lower()
    assert forbidden.lower() not in text, (
        f"the gate message still says {forbidden!r} — the alarm survived its own fix")


def test_the_gate_message_points_at_a_surface_that_can_ACTUALLY_answer_it():
    """`contracts/commands.py` deliberately has exactly two verbs and neither is merge, so the
    remedy must name the panel. Derived from the grammar, so widening it later is what changes
    this test rather than somebody's memory of it."""
    from openfactory.contracts.commands import RESUME_VERBS, SKIP_VERBS

    f = _findings(at_a_gate=[AtAGate("87", 14.0, "merge")])[0]
    said = f"{f.detail} {f.action}".lower()
    for verb in RESUME_VERBS | SKIP_VERBS:
        assert f"`{verb}" not in said, f"it tells somebody to type `{verb}` at a merge gate"
    assert "painel" in said or "panel" in said


def test_an_ARMED_AUTO_MERGE_is_waiting_for_a_BUILD_and_is_not_told_it_is_a_person():
    """THE SAME FALSE ALARM, ONE SIZE SMALLER — and the first cut of this fix shipped it.

    A job with auto-merge armed sits in the identical merge watch and answers the identical query
    while it waits for CI. Told "o portão é de vocês", somebody goes looking for a button to press
    on a job nobody can advance. It gets the wedged-job's patience and a sentence of its own."""
    early = _findings(at_a_gate=[AtAGate("87", GATE_WAIT_HOURS + 1, "ci")])
    assert early == [], "an armed auto-merge is being chased on the human gate's clock"

    f = _findings(at_a_gate=[AtAGate("87", LONG_RUNNING_HOURS + 2, "ci")])[0]
    said = f"{f.detail} {f.action}".lower()
    assert "esperando vocês" not in said and "portão é de vocês" not in said, (
        f"a job waiting for a BUILD is being announced as waiting for a person: {said}")
    assert "nobody needs to do anything" in said
    assert "ninguém precisa fazer nada" in " ".join(
        f"{x.detail} {x.action}" for x in _findings(
            at_a_gate=[AtAGate("87", LONG_RUNNING_HOURS + 2, "ci")], language="pt-BR"))
    assert f.resumable is False


def test_a_gate_that_CANNOT_HEAR_is_never_offered_a_button():
    """`gate_cannot_hear` exists because a pre-patch replay accepts no answer at all: the panel
    showed the buttons, the click was accepted, and the answer sat unread until the deadline.
    Telling somebody to press one here would re-enact that with the tech-lead's voice."""
    f = _findings(at_a_gate=[AtAGate("87", 14.0, "merge", deaf="reabra o job — este não escuta")])[0]
    assert "Merge*" not in f.action, "it offers a button that is read by no code"
    assert "cannot hear" in f.detail and "reabra o job" in f.action


def test_the_deafness_is_read_from_the_ONE_function_that_decides_it():
    """A second opinion about whether a gate can hear is a second answer to a question the panel,
    the chat and the API all resolve in one place."""
    import inspect

    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities.techlead_watch)
    assert "gate_cannot_hear" in src, (
        "the round decides for itself whether a gate is answerable instead of asking `view`")


def test_the_production_gate_says_production_and_not_the_merge_sentence():
    f = _findings(at_a_gate=[AtAGate("91", 30.0, "prod_approval")])[0]
    assert "production approval" in f.detail
    assert "produção" in _findings(
        at_a_gate=[AtAGate("91", 30.0, "prod_approval")], language="pt-BR")[0].detail
    assert "Merge" not in f.action, "the production gate is offering the merge buttons"


def test_a_gate_answered_within_the_working_day_says_nothing():
    """THE POSITIVE TWIN, and the one that decides whether this survives. Chasing somebody the
    same afternoon their PR opened is how a channel gets muted."""
    assert _findings(at_a_gate=[AtAGate("87", GATE_WAIT_HOURS - 1, "merge")]) == []


def test_the_wedged_job_alarm_is_UNTOUCHED():
    """The alarm this splits away from is right about the case it was written for, and must keep
    firing — the fix is telling the two apart, not softening one of them."""
    found = _findings(running=1, long_running=[("42", LONG_RUNNING_HOURS + 2)])
    assert [f.kind for f in found] == [STUCK]

    # IT NAMES THE EXIT THAT WORKS, and that exit CHANGED (#127). It used to be "open Temporal and
    # terminate" — honest, and a raw-engine operation asked of an operator on the one surface this
    # product promises they will never need. There is a catalogue row now, so the assertion is
    # derived from the floor grammar rather than from a remembered sentence: whatever verb ends a
    # running job, the alarm has to say it, and it has to be one somebody can actually type.
    from openfactory.actions.floor_intents import FLOOR_ROWS, match_floor_intent

    said = found[0].action
    assert "stop" in FLOOR_ROWS, "nothing in the floor grammar ends a running job any more"
    assert "`stop #42`" in said, f"the wedged-job alarm does not name its exit: {said}"
    assert match_floor_intent("stop #42") == ("stop", {"ref": "42"}), (
        "the alarm dictates a command the matcher does not accept — the merge gate's own defect, "
        "one verb along")
    assert "does NOT resume" in said or "not resume" in said, (
        "it offers an irreversible action without saying it is irreversible")


def test_the_headline_does_not_contradict_the_lines_under_it():
    """A reader takes the alarm from the first line. "tem coisa parada" over a list of healthy
    gates is the same false alarm one level up."""
    gates = _findings(at_a_gate=[AtAGate("87", 14.0, "merge")])
    assert "nothing is stuck" in report(gates)
    assert "nada travado" in report(
        _findings(at_a_gate=[AtAGate("87", 14.0, "merge")], language="pt-BR"), language="pt-BR")
    mixed = _findings(at_a_gate=[AtAGate("87", 14.0, "merge")],
                      running=1, long_running=[("42", 30.0)])
    assert "something has stopped" in report(mixed), (
        "a genuinely stuck job is being announced under a reassuring headline")


def test_a_gate_is_not_re_announced_every_hour():
    """It is said again with the new number, not on the hour: `REPEAT_AFTER[WAITING]` is the
    loosest of them because a working gate is news once a shift."""
    first = _findings(at_a_gate=[AtAGate("87", 9.0, "merge")])
    say, remember = worth_saying(first, {})
    assert say, "the first mention never happened"
    again, _ = worth_saying(_findings(at_a_gate=[AtAGate("87", 12.0, "merge")]), remember)
    assert not again, "three hours later it repeats itself"
    later, _ = worth_saying(_findings(at_a_gate=[AtAGate("87", 22.0, "merge")]), remember)
    assert later, "a gate forgotten for a whole extra shift is never mentioned again"


# ── 2. the gatherer, which is where the defect actually lived ───────────────────────────────────

def test_the_round_asks_about_EVERY_gate_the_workflow_can_wait_at():
    """THE GUARD THAT WOULD HAVE PREVENTED THIS. `awaiting_action` was the only query asked, and
    the two gates that answer it falsy were therefore invisible. Derived from `JobWorkflow`'s own
    queries, so a third gate added there fails this test until the rounds learn about it."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    declared = {name for name, member in vars(JobWorkflow).items()
                if name.startswith("awaiting_") and callable(member)}
    assert declared, "JobWorkflow declares no awaiting_* query — this guard is measuring nothing"

    covered = set(tv.HUMAN_GATES) | {"awaiting_action"}  # the park query has its own handling
    assert declared <= covered, (
        f"these gates exist on the workflow and no reader knows about them: {declared - covered}. "
        f"A job sitting at one is counted as RUNNING and eventually announced as wedged.")


def test_the_gatherer_consults_the_shared_list_rather_than_its_own_names():
    """A second spelling would not raise — it would silently mean "no gate", which is the answer
    that produced the false alarm."""
    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities.techlead_watch)
    assert "HUMAN_GATES" in src, "the round re-spells the gate queries instead of importing them"
    for literal in ('"awaiting_merge"', '"awaiting_approval"'):
        assert literal not in src, f"the round hardcodes {literal}"


def test_a_job_at_a_gate_is_not_counted_as_RUNNING_by_the_gatherer():
    """The count is what the idle finding gates on, so a gate counted as work also hides a broken
    pickup path. Asserted on the source because the gatherer needs a live engine to execute:
    the branch must decrement `running` before recording the gate."""
    from openfactory.runtime.temporal import activities

    tree = ast.parse(inspect.getsource(activities.techlead_watch).lstrip())
    appends = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append"
               and getattr(n.func.value, "id", "") == "at_a_gate"]
    assert appends, "the gatherer never records a job at a gate"
    src = inspect.getsource(activities.techlead_watch)
    gate_block = src[src.index("if gate:"):]
    assert "running -= 1" in gate_block[:400], (
        "a job waiting on a person is still counted as work — the idle finding stays blind")

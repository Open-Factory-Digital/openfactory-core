"""A job that cannot progress is eventually seen and eventually dies (C-42, #85).

A workflow-task failure loop — TMPRL1100 after a deploy, an unregistered activity type — leaves a
`JobWorkflow` running and NOT parked. It answers `awaiting_action` falsy, so the hourly round
counted it as *running*, and nothing else in the watcher could ever see it:

    idle-floor finding   requires `running == 0`   → never fires while the wedged job is counted
    stuck-park finding   reads `parked`            → the job is not parked
    JobWorkflow          had no `execution_timeout` — the only workflow without one

And the floor is a single slot per project, so one such job stops the factory indefinitely while
looking exactly like work. The one subsystem built to notice a stuck floor was blind to it by
construction.
"""

from __future__ import annotations

from openfactory.techlead.watch import IDLE, LONG_RUNNING_HOURS, STUCK, FloorState, watch


def _kinds(state: FloorState) -> list[str]:
    return [f.kind for f in watch(state)]


def test_a_job_running_far_too_long_is_reported():
    found = watch(FloorState(running=1, long_running=[("42", LONG_RUNNING_HOURS + 2)]))
    assert [f.kind for f in found] == [STUCK]
    assert found[0].ticket == "42"


def test_the_report_gives_an_executable_way_out():
    """C-27's rule: an escalation without an executable option is a silent wait with a paragraph
    attached. A wedged job is precisely the case where nobody knows what to do.

    AND THE OPTION MUST BE ONE THE ENGINE ACCEPTS (sweep B5, 2026-08-16). This message used to
    dictate `skip 42` — which bounces CONFLICT for a job that is not parked — while
    `resumable=True` made the round press `resume`, a signal a failing workflow task never
    consumes, reported as RESUMED anyway. Both exits dead, announced as working. The one real
    exit for a wedged workflow is the engine's own terminate, so that is what the message names,
    and the factory claims no self-heal it cannot perform."""
    f = watch(FloorState(running=1, long_running=[("42", 30.0)]))[0]
    # THE EXIT MOVED, AND THAT IS THE POINT OF #127. It used to be the engine's own terminate —
    # true, and a raw-engine operation asked of an operator on the one surface this product
    # promises they will never need. There is a catalogue row now, so the assertion asks the floor
    # grammar what ends a running job rather than remembering a sentence.
    from openfactory.actions.floor_intents import FLOOR_ROWS, match_floor_intent

    assert "stop" in FLOOR_ROWS, "nothing ends a running job any more"
    assert "`stop #42`" in f.action, f"the message does not name its exit: {f.action}"
    assert match_floor_intent("stop #42") is not None, (
        "it dictates a command no matcher accepts — the merge gate's own defect, one verb along")
    assert "not resume" in f.action.lower(), (
        "an irreversible exit is offered without saying it is irreversible")
    assert f.resumable is False, (
        "the factory claims it can heal a wedged job — the resume signal is never consumed and "
        "the round reports RESUMED about a job nothing touched")
    for dead_verb in ("skip", "resume"):
        assert f"`{dead_verb}" not in f.action, (
            f"the message dictates `{dead_verb}`, which the engine refuses for a running job")


def test_an_ordinary_long_job_is_not_reported():
    """The positive twin, and the one that decides whether this alarm survives. A real job can
    legitimately run for hours — plan, execute, repair, review — and an alarm that fires on those
    is an alarm somebody mutes."""
    assert _kinds(FloorState(running=1, long_running=[])) == []


def test_a_busy_floor_still_reports_nothing():
    assert _kinds(FloorState(running=2, queued=["7"], idle_minutes=99)) == []


def test_the_idle_finding_is_untouched():
    """It could not fire while a wedged job was counted as running; that is fixed by seeing the
    wedged job, not by weakening this."""
    assert IDLE in _kinds(FloorState(running=0, queued=["7"], idle_minutes=60))


def test_the_bound_is_past_a_real_agent_pass():
    """`AGENT_TIMEOUT` is 4h and a job makes several passes. A bound near that would fire on
    healthy work; the cost of being late here is one message, the cost of being wrong is a muted
    alarm."""
    from openfactory.adapters.sandbox.timeouts import AGENT_TIMEOUT

    assert LONG_RUNNING_HOURS * 3600 > AGENT_TIMEOUT


# ── and the workflow itself has a ceiling ────────────────────────────────────────────────────────

def test_the_job_workflow_is_started_with_an_execution_timeout():
    """It was the only workflow without one — the poller, the product sweep and the tech-lead
    rounds all carry one for exactly this reason."""
    import ast
    import inspect

    from openfactory.runtime.temporal import activities

    src = inspect.getsource(activities.start_jobs)
    tree = ast.parse(src.lstrip())
    starts = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "start_workflow"]
    assert starts, "start_jobs no longer starts a workflow"
    for call in starts:
        kw = {k.arg for k in call.keywords}
        assert "execution_timeout" in kw, "a JobWorkflow can run for ever"


def test_the_ceiling_is_past_the_longest_LEGITIMATE_wait():
    """A job parked on a human merge waits up to 14 days by default. This wall is for the job that
    cannot progress at all — setting it near an agent pass would kill healthy waits."""
    from openfactory.runtime.temporal.activities import JOB_EXECUTION_CEILING_DAYS
    from openfactory.runtime.temporal.io import JobParams

    assert JOB_EXECUTION_CEILING_DAYS > JobParams(project="p", issue="1").merge_deadline_days

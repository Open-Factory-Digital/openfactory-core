"""The factory resolving what is its own to resolve (ADR-0020).

The park path is inside a durable workflow, so these assert the WIRING rather than run it: that the
classification happens before anybody is troubled, that the retry reuses the mechanism the
rate-limit pause has used for months, and — the one that becomes an incident if it is wrong — that
the new branch is guarded so a job already parked on the old path replays the old path.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path("openfactory/runtime/temporal/workflow.py").read_text()


def _park_block() -> str:
    """The self-heal stanza, bounded by what FOLLOWS it rather than by a character count.

    It was `start + 2600`, and comments added to the code inside pushed the assertions' own
    subject out of the window — a guard failing because the code around it grew, which teaches
    everyone to widen the number instead of reading the failure (third time in one day,
    2026-08-16)."""
    start = WORKFLOW.index("ADR-0020: is this ours to fix?")
    end = WORKFLOW.index("RECONCILE THE BOARD", start)
    return WORKFLOW[start:end]


def test_the_failure_is_classified_BEFORE_anybody_is_troubled():
    """Marking the board, running a diagnosis and alerting a channel are all things a self-healing
    failure should never cause. So the question "is this ours?" is asked first.

    Measured inside the PARK PATH, not the whole file: the same activity names appear in the import
    block at the top, and comparing against those would pass no matter where the calls actually
    sit."""
    park = WORKFLOW[WORKFLOW.index("if result.state in (JobState.NEEDS_REFINEMENT"):]
    classified_at = park.index("verdict = classify(")
    for later in ('workflow.patched("park-marks-needs-action")',
                  'workflow.patched("park-techlead-diagnosis")',
                  'workflow.patched("park-says-needs-action")'):
        assert classified_at < park.index(later), f"{later} runs before the classification"
    block = _park_block()
    # BOTH HALVES OF THE QUESTION, and neither pinned to one line's shape: `classify` decides what
    # the failure is and `remedy_for` decides whose it is. The previous anchor was the literal
    # `remedy_for(verdict`, which broke the day the call wrapped across two lines — a guard
    # failing on formatting rather than on behaviour.
    assert "classify(" in block and "remedy_for(" in block, (
        "the park no longer classifies before it troubles anybody")


def test_a_retry_reuses_the_mechanism_that_already_works():
    """`_wait_operator(..., default="resume")` is how the rate-limit pause has held the floor,
    burned no compute and woken on a timer for months. Inventing a second retry loop beside it would
    be two things to get wrong instead of one."""
    block = _park_block()
    assert '_wait_operator(' in block
    assert '"resume"' in block
    assert "timedelta(seconds=remedy.wait_seconds)" in block


def test_the_new_branch_is_GUARDED_for_replay():
    """A job parked on the old path must replay the old path. This codebase has been bitten by an
    unguarded workflow change before, and the symptom is a nondeterminism error on a ticket that was
    running fine."""
    assert 'workflow.patched("techlead-self-heal")' in WORKFLOW
    guard_at = WORKFLOW.index('workflow.patched("techlead-self-heal")')
    assert guard_at < WORKFLOW.index("verdict = classify(")


def test_the_budget_is_per_JOB_and_survives_between_parks():
    """A budget that resets on every park is not a budget — it is a loop that pauses."""
    assert "self._remedied: dict[str, int] = {}" in WORKFLOW
    block = _park_block()
    assert "self._remedied.get(verdict.cause, 0)" in block
    assert "self._remedied[verdict.cause] = tried + 1" in block


def test_it_SPEAKS_while_it_works():
    """A channel that goes quiet during an incident teaches people to check the panel instead —
    which is the habit this whole layer exists to remove."""
    block = _park_block()
    assert "_coord_say(" in block
    assert "remedy.say" in block


def test_a_human_who_says_skip_is_OBEYED_mid_remedy():
    """Someone who pressed Skip has decided. Resurrecting their ticket because a timer fired is the
    fastest way to make an operator distrust the whole thing."""
    block = _park_block()
    assert 'if act == "skip":' in block
    # IT RETURNS THROUGH `_skip`, which is what makes the obedience VISIBLE (2026-08-16). It used
    # to `return parked` — the ticket kept the state it had before the person answered, so the
    # decision was obeyed on the floor and invisible everywhere else. The property this test
    # guards is unchanged: their answer ends the job then and there.
    assert "self._skip(" in block, (
        "the self-heal wait no longer records the skip — the floor frees and the board goes on "
        "showing what was true before somebody decided")
    assert "by_a_person=by_a_person" in block, (
        "it would report the timer expiring as a person's decision")


def test_only_a_RETRY_short_circuits_the_park():
    """`escalate` and `product` must fall through to the existing path — board marked, diagnosis
    attempted, humans told. Skipping that for anything but a self-healing cause would lose the
    escalation entirely."""
    block = _park_block()
    assert 'remedy.action == "retry"' in block
    assert "remedy.wait_seconds > 0" in block

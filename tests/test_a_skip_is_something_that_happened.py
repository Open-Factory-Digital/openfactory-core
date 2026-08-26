"""A human acted; the record must move (pilot, 2026-08-16).

He skipped `#89` and the panel went on showing what was true before he touched it:

    #89 feat(billing): validate real Stripe checkout end-to-end in staging
    openfactory-podbeam-89 · shipped 2026-08-16 15:53 · took 16m 10s        [on_hold]

*"depois do skip ela fica em on hold, não fica histórico em comentários no ticket e continua em
Needs Action… o status não on_hold e sim skipped, ou seja, o que realmente aconteceu."*

He is right, and this is the SECOND time in two days the same shape has been found: a person takes
a decision, the floor moves, and the board keeps reporting the state that preceded them. The merge
was the first (`7c277b8` — `MERGED` mapped to *In review* and nothing ever wrote `DONE`), and the
two now share `JobWorkflow._settle` rather than each growing its own copy.

WHERE THE CARD GOES IS A PRODUCT DECISION AND IT IS NOT `DONE`. Nothing was delivered — a board
where Done means "shipped" is the one report an operator has to be able to trust, and a skipped
ticket in it corrupts every "what went out this week" reading. It is not *Needs Action* either:
nobody is waiting on it. It is open work nobody is working on, which is what a backlog is. The
ticket keeps its own comment trail, so the history the operator asked for is on the ticket.

THE DEADLINE IS DELIBERATELY NOT THIS. When the impediment window elapses nobody acted, and
`on_hold` with a note about an expired window is exactly what happened.
"""

from __future__ import annotations

import inspect
import re

import pytest

from openfactory.adapters.tracker.base import STATE_KEYS
from openfactory.adapters.tracker.github_project import STATUS_MAP
from openfactory.contracts import JobState
from openfactory.runtime.temporal import workflow as wf


def test_skipping_has_a_state_of_its_own():
    """`on_hold` is what the job was BEFORE the person decided. Reusing it makes the panel report
    the decision as if it had not been taken."""
    assert JobState.SKIPPED.value == "skipped"
    assert JobState.SKIPPED not in (JobState.ON_HOLD, JobState.DONE, JobState.FAILED)


def test_a_skipped_card_leaves_the_column_that_asks_for_a_human():
    """Nobody is waiting on it any more — that is the whole point of pressing skip."""
    assert STATE_KEYS[JobState.SKIPPED] != STATE_KEYS[JobState.ON_HOLD]
    assert STATE_KEYS[JobState.SKIPPED] != "needs_action"


def test_a_skipped_card_does_NOT_land_in_the_shipped_column():
    """The property that decides whether the board's own report stays trustworthy. Nothing was
    delivered; a Done column that includes abandoned work answers "what shipped" wrongly for ever."""
    assert STATE_KEYS[JobState.SKIPPED] != STATE_KEYS[JobState.DONE]
    assert STATUS_MAP[JobState.SKIPPED] != STATUS_MAP[JobState.DONE]
    assert STATUS_MAP[JobState.SKIPPED] == "Backlog"


def test_every_state_a_JOB_can_END_in_is_mapped_to_a_column():
    """Derived from the enum: a terminal state with no column is a card that silently stays where
    it was, which is the defect this file exists for. The mid-flight states a board never shows
    (`paused`, `ci_waiting`, the deploy stages) are excluded by name, so adding one of THOSE does
    not fail this — and adding a new ENDING does."""
    endings = {JobState.DONE, JobState.MERGED, JobState.SKIPPED, JobState.FAILED,
               JobState.ON_HOLD, JobState.NEEDS_REFINEMENT, JobState.BLOCKED}
    missing = sorted(s.value for s in endings if s not in STATE_KEYS)
    assert not missing, f"a job can end in these and no board column is mapped: {missing}"


# ── the workflow records it ─────────────────────────────────────────────────────────────────────

def _flat(src: str) -> str:
    """Source with its line wrapping flattened.

    THE WRAP IS NOT PART OF THE CLAIM, and this is the third guard in one day to fail on it: an
    f-string split as `"…goes back to "` + `"the backlog."` does not contain "back to the backlog"
    until the break is removed. A guard that fails on where the editor wrapped a line teaches
    people to widen it rather than read it."""
    return re.sub(r'"\s*\n\s*f?"', "", src)


def test_the_skip_branch_settles_the_ticket():
    branch = _flat(inspect.getsource(wf.JobWorkflow._skip))
    assert "JobState.SKIPPED" in branch, "the run still ends carrying the parked state"
    assert "_settle(" in branch, "nothing tells the tracker a person decided"
    assert "back to the backlog" in branch, (
        "the comment does not say where the ticket went — the history the operator asked for")


def test_EVERY_place_a_person_can_skip_ends_the_same_way():
    """THE CLASS, NOT THE INSTANCE. There are five: the impediment gate, a rate-limit pause, CI
    repair, a PR falling behind, and a PR conflicting with its base. The first fix caught one, and
    the other four went on reporting `on_hold` — which is how this defect survived being fixed."""
    import re

    src = inspect.getsource(wf.JobWorkflow)
    ends = re.findall(r'_skip\(\n?\s*params', src)
    assert len(ends) >= 6, (
        f"only {len(ends)} skip endings route through the one helper — a branch was added or a "
        f"fix caught fewer places than there are")
    for stanza in re.finditer(r'act == "skip"[^\n]*:\n(.{0,400}?)(?=\n\s{16}\S)', src, re.S):
        body = stanza.group(1)
        assert "_skip(" in body or "JobState.SKIPPED" in body, (
            f"a skip branch still ends without saying so:\n{body[:200]}")


def test_the_skip_is_behind_a_patch_marker():
    """TMPRL1100: a new command on a path in-flight jobs already replay. #89 was parked when this
    shipped, and a job parked at an impediment is exactly the one that reaches this line."""
    assert 'workflow.patched("a-skip-is-recorded")' in inspect.getsource(wf.JobWorkflow._skip)


def test_the_DEADLINE_is_not_reported_as_a_decision():
    """Nobody acted there, so nothing may be claimed — and the first cut of this fix got it wrong.

    `_wait_operator` returns its DEFAULT when the window elapses, and at the impediment gate that
    default is `"skip"` — so `act == "skip"` was true for an expired deadline too, and an elapsed
    window was recorded on the client's ticket as somebody's decision. The distinction existed
    only in a log line: the return value said the same thing either way, which is why the answer
    shape now carries it.

    The behavioural twin is `test_temporal_workflow::test_impediment_deadline_auto_frees_the_floor`,
    which runs a real workflow to its deadline; this asserts the mechanism it depends on."""
    assert "by_a_person: bool" in inspect.getsource(wf.JobWorkflow._skip), (
        "`_skip` no longer takes who answered — a deadline and a decision are the same value again")
    assert "if not by_a_person" in inspect.getsource(wf.JobWorkflow._skip), (
        "`_skip` records a decision without checking that a person made one")
    waiter = _flat(inspect.getsource(wf.JobWorkflow._wait_operator))
    assert "return act, choice, answered" in waiter, (
        "the wait no longer reports whether anybody answered — the log said it and the return "
        "value did not, which is exactly how this defect shipped")


def test_it_does_not_claim_WHO_skipped():
    """`act_on_impediment` carries the action and a decision key, never an actor. Naming a person
    the signal never delivered is the class of lie this session spent the day removing."""
    branch = inspect.getsource(wf.JobWorkflow._skip)
    assert "Skipped by {" not in branch and "skipped by {" not in branch, (
        "it interpolates a name into the comment — `choice` is a decision option key, not a person")


def test_both_endings_share_ONE_settle():
    """The merge and the skip are the same defect twice. Two copies would drift, and the second
    copy is how the first one was missed for a day."""
    src = inspect.getsource(wf.JobWorkflow)
    assert src.count("settle_ticket,") == 1, (
        "the settle activity is scheduled from more than one place — they will diverge")
    assert "_settle(params, JobState.DONE" in src, "the merge no longer goes through the helper"


@pytest.mark.parametrize("state,forbidden", [
    (JobState.SKIPPED, "Done"),
    (JobState.SKIPPED, "Needs Action"),
])
def test_the_default_board_rendering_says_neither_shipped_nor_waiting(state, forbidden):
    assert STATUS_MAP[state] != forbidden

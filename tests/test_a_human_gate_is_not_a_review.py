"""The panel said *Needs you* and the client's board said *In review* (#166).

Measured on the pilot's own screen, about the same card:

    panel : Needs you — podbeam #103 — a pull request is waiting on your review
    board : #103 in "In review"   ·   Needs Action: 0

The product owner lives on the board. It told him nothing was waiting on him.

`awaiting_prod_approval` was the easy half and moved buckets. `pr_open` cannot: it is TWO
situations under one name — an armed auto-merge, where the machine watches CI and nobody is
needed, and a human merge gate, where the READER is the blocker. The engine writes the same
`JobState.PR_OPEN` for both, and only `view._domain_state` could tell them apart, by reading a
fact the tracker port never received.

So the port receives it. `needs_person` is additive with a default of `None` — "the state
decides", which is what every existing caller means — and `column_key` is the one place the two
readings live, for three trackers and two boards.

A NEW `JobState` WAS THE OTHER WAY AND THE CARD REJECTS IT: `RunResult.state` travels into the
Temporal workflow, so a new member changes what in-flight jobs replay — and one was parked at this
exact gate when the card was written.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.adapters.tracker.base import STATE_KEYS, column_key
from openfactory.contracts import JobState

# ── 1. the resolution, and its default ──────────────────────────────────────────────────────────

def test_a_human_merge_gate_lands_where_a_person_looks():
    assert column_key(JobState.PR_OPEN, needs_person=True) == "needs_action"


def test_and_an_armed_auto_merge_stays_in_review():
    assert column_key(JobState.PR_OPEN, needs_person=False) == "in_review"


def test_saying_NOTHING_answers_exactly_what_it_answered_before():
    """The parameter is additive. Every caller that does not know keeps the answer it had, or this
    is not a widening — it is a migration nobody asked for."""
    for state in STATE_KEYS:
        assert column_key(state) == STATE_KEYS[state]


def test_a_state_that_is_a_persons_by_NATURE_stays_theirs():
    """The asymmetry is deliberate. Only the review bucket holds two situations; `on_hold` is a
    person's however a caller answers, and a caller saying otherwise is contradicting the
    platform's own record."""
    for state in (JobState.ON_HOLD, JobState.BLOCKED, JobState.NEEDS_REFINEMENT,
                  JobState.FAILED, JobState.AWAITING_PROD_APPROVAL):
        assert column_key(state, needs_person=False) == "needs_action"


def test_and_a_finished_job_is_not_moved_by_the_answer_either():
    assert column_key(JobState.DONE, needs_person=True) == "done"


def test_no_new_JobState_was_minted_for_this():
    """`RunResult.state` travels into the Temporal workflow: a new member changes what in-flight
    jobs replay, and one was parked at this exact gate when the card was written."""
    assert not any(m.name.startswith("AWAITING_YOUR_MERGE") for m in JobState)


# ── 2. every vendor takes it, and none decides for itself ───────────────────────────────────────

@pytest.mark.parametrize("module,symbol", [
    ("openfactory.adapters.tracker.github", "GitHubIssuesTracker"),
    ("openfactory.adapters.tracker.jira", "JiraTracker"),
    ("openfactory.adapters.tracker.azure_devops", "AzureBoardsTracker"),
])
def test_every_tracker_ACCEPTS_the_distinction(module, symbol):
    import importlib

    cls = getattr(importlib.import_module(module), symbol)

    assert "needs_person" in inspect.signature(cls.set_state).parameters, (
        f"{symbol} cannot be told a person is the blocker — its board keeps saying In review")


@pytest.mark.parametrize("module,symbol", [
    ("openfactory.adapters.tracker.github_project", "GitHubProjectBoard"),
    ("openfactory.adapters.board.jira", "JiraProjectBoard"),
    ("openfactory.adapters.board.azure_devops", "AzureBoardsBoard"),
    ("openfactory.adapters.board.base", "BoardAdapter"),
])
def test_and_so_does_every_board(module, symbol):
    import importlib

    cls = getattr(importlib.import_module(module), symbol)

    assert "needs_person" in inspect.signature(cls.set_status).parameters


@pytest.mark.parametrize("module", [
    "openfactory.adapters.tracker.jira",
    "openfactory.adapters.tracker.azure_devops",
    "openfactory.adapters.tracker.github_project",
    "openfactory.adapters.board.azure_devops",
])
def test_nobody_reads_the_TABLE_around_the_resolver(module):
    """The reading is the point. A `STATE_KEYS.get(state)` anywhere is an adapter that cannot see a
    human merge gate — and it would look correct, because the table it reads is the right one."""
    import importlib

    from conftest import code_only

    assert "STATE_KEYS" not in code_only(inspect.getsource(importlib.import_module(module)))


# ── 3. the engine says which situation it is in ─────────────────────────────────────────────────

def _pr_open_calls():
    """Every `_set_state(..., PR_OPEN, ...)` in the machine, with what it says about a person."""
    import ast

    from openfactory.orchestrator import machine

    src = inspect.getsource(machine)
    out = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_set_state"):
            continue
        text = ast.get_source_segment(src, node) or ""
        if "PR_OPEN" not in text:
            continue
        said = next((k.value for k in node.keywords if k.arg == "needs_person"), None)
        out.append((node.lineno, getattr(said, "value", None)))
    return out


def test_every_PR_OPEN_transition_says_whose_move_it_is():
    """Three call sites, three meanings: reviewers requested (a person), auto-merge armed (the
    machine), CI re-running after a repair push (the machine). A default here is the ambiguity
    this card is about, left in the one place that knows the answer."""
    calls = _pr_open_calls()

    assert len(calls) >= 3, f"the machine's PR_OPEN sites moved — this guard sees {calls}"
    unsaid = [line for line, said in calls if said is None]
    assert not unsaid, f"these PR_OPEN transitions say nothing about who is blocked: {unsaid}"


def test_and_the_human_gate_is_one_of_them():
    """The positive twin: three `needs_person=False` would satisfy the guard above and leave the
    pilot's own screenshot unfixed."""
    assert any(said is True for _line, said in _pr_open_calls()), (
        "no PR_OPEN transition claims a person — the board still reads In review for the gate")


def test_and_the_ARMED_watch_is_one_too():
    """The other twin, and the one that keeps the fix honest: three `needs_person=True` would pass
    both guards above and put every armed auto-merge in the column a person watches — which is the
    original defect facing the other way, and it would fill `Needs Action` with work nobody is
    blocked on until the operator stops reading the column."""
    import inspect

    from openfactory.orchestrator import machine

    # ANCHORED ON THE SITE, not on "at least one of the three". Three sites and two answers means
    # `any(... is False)` stays true while the ARMED one flips — the mutation that proved it. The
    # arming branch is the one that sets `result.auto_merge = True`, which is a fact about the
    # code that cannot drift without the meaning drifting with it.
    src = inspect.getsource(machine)
    lines = src.splitlines()
    armed = next(n for n, ln in enumerate(lines, start=1)
                 if ln.strip() == "result.auto_merge = True")
    after = "\n".join(lines[armed:armed + 6])

    assert "_set_state" in after and "needs_person=False" in after, (
        "the armed auto-merge no longer says the machine is working — it would sit in the column "
        f"a person watches, filling Needs Action with work nobody is blocked on:\n{after}")


def test_the_GITHUB_tracker_hands_it_to_its_board():
    """GitHub is the only vendor where the tracker and the board are two objects, so the argument
    has one more hop to survive — and it is the vendor the pilot is on."""
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    seen: dict = {}

    class _Board:
        def set_status(self, *, issue, issue_url, state, needs_person=None):
            seen.update(state=state, needs_person=needs_person)
            return True

    tracker = GitHubIssuesTracker("o/r", token="t")
    # The board is BUILT from coordinates, not injected — set it on the instance, which is the
    # shape `build_tracker` produces for a project whose registry row names one.
    tracker.board = _Board()
    tracker._gh = lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    tracker.set_state("#7", JobState.PR_OPEN, needs_person=True)

    assert seen.get("needs_person") is True, (
        "the tracker takes the distinction and its board never hears it")


def test_the_machine_hands_it_DOWN(monkeypatch):
    """Reachability. The guards above read the machine's own calls; this one watches what reaches
    the tracker, because a `_set_state` that accepted the argument and dropped it would satisfy
    every one of them."""
    from openfactory.orchestrator.machine import JobRunner

    seen: dict = {}

    class _Tracker:
        def set_state(self, ref, state, reason=None, *, needs_person=None):
            seen.update(state=state, needs_person=needs_person)

    machine = JobRunner.__new__(JobRunner)
    machine.tracker = _Tracker()
    machine._emit = lambda *a, **k: None
    machine.forge = None
    ticket = type("T", (), {"id": "#7"})()
    machine._drop_working_label = lambda *a, **k: None

    JobRunner._set_state(machine, ticket, JobState.PR_OPEN, needs_person=True)

    assert seen.get("needs_person") is True, (
        "the machine takes the distinction and does not pass it on")

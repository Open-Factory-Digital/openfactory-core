"""A wait nobody is being asked about is not a question (#151).

MEASURED ON THE PILOT, minutes after #148 shipped. The operator answered the merge gate with
`adjust`; the engine started a repair pass on the PR; and for the two minutes that agent was
rewriting the branch, every surface still said a person was needed:

    floor : Needs you — podbeam #101 — a pull request is waiting on your review
    census: {'working': 0, 'needs': 1, ...}          ← an agent was working
    inbox : awaiting_your_merge · options merge / adjust / discard

Merge and Discard were live buttons the whole time. A click would have landed — or closed — a pull
request that was being rewritten as it was read.

THE CAUSE IS ONE FIELD'S MEANING. `_merge_wait` is what every surface reads to decide a job is at
a gate, and the adjust branch left it set across the whole activity. Presence of a merge wait was
taken to mean "a person is being asked", when what it really means is "there is an open PR this job
is watching" — true both while asking and while acting on the answer.

This file states the distinction from BOTH sides: a pass in flight is work, and a PR genuinely
waiting on a person is still a gate. A guard that only asserted the first would be satisfied by a
platform that never asks anybody anything.
"""

from __future__ import annotations

import pytest
from temporalio.client import WorkflowExecutionStatus

from openfactory.runtime.temporal import view as tv


class _Handle:
    """Answers the three queries `_domain_state` asks, in its order."""

    def __init__(self, *, merge_wait: dict | None, action=None, approval=False):
        self._answers = {"awaiting_action": action, "awaiting_merge": merge_wait,
                         "awaiting_approval": approval}

    async def describe(self):
        class _D:
            status = WorkflowExecutionStatus.RUNNING
        return _D()

    async def query(self, q, *a, **k):
        name = getattr(q, "__name__", None) or str(q).rsplit(".", 1)[-1]
        return self._answers[name]


class _Client:
    def __init__(self, handle):
        self._h = handle

    def get_workflow_handle(self, *a, **k):
        return self._h


class _WF:
    id, run_id, status = "job-demo-7", "r1", WorkflowExecutionStatus.RUNNING


GATE = {"pr_url": "https://x/pr/9", "auto": False, "note": "waiting for your review and merge"}
IN_FLIGHT = {"pr_url": "https://x/pr/9", "auto": False, "working": True,
             "note": "somebody asked for a change — one more pass on the same PR"}


async def test_a_repair_pass_in_flight_is_WORK_not_a_question():
    state, action, live = await _domain(IN_FLIGHT)

    assert state == "repairing", (
        f"an agent is rewriting the PR and the job reads as {state!r} — the floor says a person is "
        f"needed and offers Merge and Discard on a branch that is moving")
    assert live is True
    assert action and action["kind"] == tv.MERGE_WAIT, "the PR it is working on is still named"


async def test_a_PR_actually_waiting_on_a_person_is_still_a_gate():
    """The twin, and the one that matters more: a platform that called every merge wait `repairing`
    would pass the test above and never ask anybody anything."""
    state, action, _ = await _domain(GATE)

    assert state == "awaiting_your_merge", state
    assert action["note"] == GATE["note"]


async def test_an_armed_AUTO_merge_is_neither():
    state, _, _ = await _domain({**GATE, "auto": True})
    assert state == "merging", state


async def test_the_state_a_pass_in_flight_reports_is_one_the_product_KNOWS():
    """`repairing` is a declared `JobState`, not a word invented here — an unknown state renders as
    `unknown` on the panel, which is how a fix for a wrong answer becomes a missing one."""
    from openfactory.contracts.state import JobState

    state, _, _ = await _domain(IN_FLIGHT)
    assert state in {s.value for s in JobState}
    assert state not in tv.ATTENTION_STATES, "it would still be counted as needing a human"


@pytest.mark.parametrize("flag", [False, None, 0, ""])
async def test_only_a_TRUE_working_flag_moves_it(flag):
    """A merge wait written before this field existed carries no `working` key at all, and an
    in-flight job replaying that history must keep reading as the gate it was."""
    state, _, _ = await _domain({**GATE, "working": flag})
    assert state == "awaiting_your_merge", f"{flag!r} was read as a pass in flight"


async def _domain(merge_wait: dict):
    return await tv._domain_state(_Client(_Handle(merge_wait=merge_wait)), _WF())


# ── and what the operator ends up reading ───────────────────────────────────────────────────────
#
# The two halves joined: the state the view reports is fed to the ladder that writes the headline.
# Asserting only the state would leave the sentence unproven, and the sentence is the product.

async def _headline(merge_wait: dict, **over):
    """The whole chain the operator actually reads: query → state → row → ladder → sentence."""
    from openfactory import floor
    from tests.test_the_floor_is_a_platform_capability import world

    state, action, _ = await _domain(merge_wait)
    job = {"project": "acme", "issue": "7", "status": "running", "wedged": False,
           "attention": state in tv.ATTENTION_STATES, "state": state, "action": action}
    return floor.state(world(jobs=[job], **over), "acme"), floor.state(world(jobs=[job], **over))


async def test_the_headline_says_the_MACHINE_has_it():
    """THE ASSERTION THAT CAUGHT MY OWN FIX. Moving the state to `repairing` was not enough: rung 7
    excluded any job carrying an `action` payload, so the in-flight job matched no rung at all and
    the floor answered `Armed — nothing is running` over an agent at full throttle. That is the
    same lie as the one this card fixes, pointing the other way."""
    got, whole = await _headline(IN_FLIGHT, inbox=[])

    assert got.word == "Working", got.line
    assert whole.census["working"] == 1, (
        f"an agent is rewriting the PR and the census counts {whole.census}")
    assert whole.census["needs"] == 0, "and nobody is being asked anything"


async def test_the_same_row_a_moment_LATER_is_a_gate_again():
    """The pass ends, `working` is gone, and the operator is asked — the loop's whole point. The
    inbox is left UNREAD here so the fallback path is the one under test: an empty inbox beside a
    job at a gate is a world that cannot happen, and asserting on it proves nothing."""
    got, whole = await _headline(GATE, inbox=None)

    assert got.word == "Needs you", got.line
    assert "review" in got.clause, got.clause
    assert whole.census["needs"] == 1 and whole.census["working"] == 0, whole.census


# ── the flag has to be SET, not merely understood ───────────────────────────────────────────────

@pytest.mark.parametrize("act,asked", [
    ({"kind": "merge_wait", "working": True}, False),      # the machine is acting on the answer
    ({"kind": "merge_wait", "auto": False}, True),          # the operator is asked to merge
    ({"kind": "merge_wait", "auto": True}, True),           # a clock is being waited on
    ({"kind": "impediment", "note": "needs a credential"}, True),
    ({"kind": "rate_limit", "wakes_at": "2026-08-19T23:00:00+00:00"}, True),
    ({"decision": {"question": "which shape?"}}, True),
    ({}, False),                                            # no payload — plain work
])
def test_only_ONE_payload_is_the_engine_talking_about_ITSELF(act, asked):
    """Every other payload names somebody or something being waited on, and a job carrying one is
    not Working however busy the workflow looks. Stated payload by payload because the census is
    blind here: rung 5 is pinned and rung 6 outranks rung 7, so a park wrongly admitted to Working
    still reads correctly on screen — right answer, broken reason, and it would rot."""
    from openfactory.floor.ladder import _is_asked_of_somebody

    assert _is_asked_of_somebody(act) is asked


def test_the_ENGINE_actually_raises_the_flag_before_it_starts_the_pass():
    """The reachability half. Everything above states what the surfaces do with `working: True`;
    nothing above proves anybody ever sets it, and a mutation removing it from the workflow left
    all of it green ([[built-tested-reached-by-nothing]]).

    Read from source rather than by driving Temporal: this is one assignment on one line, and the
    claim is about its ORDER — the flag must be up before the activity is launched, not after."""
    import ast
    import inspect

    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.cleandoc("\n" + inspect.getsource(JobWorkflow._answer_merge_gate))
    tree = ast.parse(src)

    # BY LINE, NOT BY WALK ORDER. `ast.walk` is breadth-first, so the first version of this read
    # the launch before the assignment that precedes it in the file and failed on correct code.
    launches = [n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == "adjust_pr"]
    assert launches, "no adjust pass is launched here — this guard is measuring nothing"

    waits = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict)
                and "self._merge_wait" in {ast.unparse(t) for t in n.targets}):
            keys = {k.value: v for k, v in zip(n.value.keys, n.value.values, strict=True)
                    if isinstance(k, ast.Constant)}
            flag = keys.get("working")
            waits[n.lineno] = isinstance(flag, ast.Constant) and flag.value is True

    before = [ln for ln in waits if ln < min(launches)]
    assert before, "the pass is launched with no merge wait published at all"
    assert waits[max(before)], (
        "the repair pass is launched while `_merge_wait` still reads as a question — every "
        "surface will say a person is needed, with Merge and Discard live, over a branch an "
        "agent is rewriting")

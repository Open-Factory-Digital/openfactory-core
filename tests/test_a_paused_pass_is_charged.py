"""A pass that pauses is charged like every other pass (#262).

THE DEFECT. The rate-limit arm returned before the pass was counted:

    if agent_result.pause_reason:
        return self._paused(…)                  # ← returned here
    self._count(agent_result, "executor")       # ← never reached

so a ticket that spent real money and then hit the usage limit came back with `agent_runs == []`
and `total_cost_usd is None`. A paused ticket is the one an operator most wants the spend for: it
is coming back, and the resume runs another pass on top of whatever the first one burned.

IT WAS NOT ONE PLACE. Every way out of the walk that returns after a pass, measured on `main` at
`cf204fc` with doubles that report a price and then stop:

    planner   pauses      no row, no total, and not in the journal either
    executor  pauses      no row, no total                  (the journal had it)
    recovery  pauses      a row, and still no total — `_paused` never carried one
    repair, suppression-repair, review-repair  pause
                          the pass missing from the result AND the journal
    suppression-repair    never counted on ANY way out: the journal and `/api/jobs` summed it,
                          the result, the telemetry and the pull request's `Cost:` did not
    planner   sends the ticket back (SPLIT)
                          the plan's row, and a total of None beside it
    a merge the forge refused, after the review
                          a total taken before the review, beside rows that include it (and the
                          knowledge gate's hold took its total the same way, read not measured)

WHAT IS HELD HERE, by driving the real runner over a real repository and the real route over the
journal it wrote: every pass is counted once, whichever way out it takes, and the result, the
journal and the dashboard say the same number. Unknown stays unknown — a paused pass that reported
no price is a row with no price, never `0.0`.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    Finding,
    JobState,
    Manifest,
    ReviewResult,
    Ticket,
)
from openfactory.observability import InMemoryEventSink
from tests.test_one_cost_for_a_ticket_on_every_surface import _jobs
from tests.test_walking_skeleton import (
    FakeAgent,
    FakeForge,
    FakeTracker,
    _runner,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

#: What the pass that pauses had already burned when the limit hit. Distinct from every other
#: price here, so a row carrying it can only be that pass.
SPENT = 0.37
#: What the executor's double reports on a pass that finishes, from `test_walking_skeleton`.
EXECUTOR_COST = 0.01
#: A priced review, for the holds that come after one.
REVIEW_COST = 0.25
#: The turns the paused executor had taken — effort, which the ticket's budget is counted in.
TURNS = 7

_LIMIT = {"ok": False, "pause_reason": "rate_limit", "retry_at": "16:00",
          "summary": "usage limit reached"}


def _ticket() -> Ticket:
    return Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


# ═══ the doubles: each one does real work, reports what it cost, and then hits the limit ════════

class _PlannerPauses(FakeAgent):
    def plan(self, *, sandbox, workspace, context):   # noqa: ARG002 — the port's shape
        return AgentRunResult(cost_usd=SPENT, **_LIMIT)


class _ExecutorPauses(FakeAgent):
    def __init__(self, cost: float | None = SPENT) -> None:
        self.cost = cost

    def execute(self, *, sandbox, workspace, context):   # noqa: ARG002
        (workspace.path / "feature.py").write_text("VALUE = 4\n")   # half-done, and paid for
        return AgentRunResult(cost_usd=self.cost, num_turns=TURNS, **_LIMIT)


class _RecoveryPauses(FakeAgent):
    def execute(self, *, sandbox, workspace, context):   # noqa: ARG002
        return AgentRunResult(ok=False, summary="stopped at the turn cap", cost_usd=EXECUTOR_COST)

    def recover(self, *, sandbox, workspace, context, brief):   # noqa: ARG002
        return AgentRunResult(cost_usd=SPENT, **_LIMIT)


class _RepairPauses(FakeAgent):
    def repair(self, *, sandbox, workspace, context, failure_log):   # noqa: ARG002
        return AgentRunResult(cost_usd=SPENT, **_LIMIT)


class _SuppressionRepairPauses(_RepairPauses):
    def execute(self, *, sandbox, workspace, context):   # noqa: ARG002
        (workspace.path / "feature.py").write_text("VALUE = 42  # pragma: no cover\n")
        return AgentRunResult(ok=True, summary="added (pragma'd)", cost_usd=EXECUTOR_COST)


class _Rejects:
    """A blocking rejection with a finding to act on — the review-repair loop's way in.

    UNPRICED ON PURPOSE. A priced review reaches the result through `_count_review` and never
    reaches the journal — the `review` event carries no `cost_usd` — so the journal and the
    result would disagree here by the review's price, on every reviewed ticket and not only a
    paused one. That is its own defect, not this one; this double keeps it out of the way."""

    def review(self, *, sandbox, workspace, review_input):   # noqa: ARG002
        return ReviewResult(
            decision="rejected", score=40, summary="not done as submitted",
            findings=[Finding(severity="critical", description="asserts the wrong value",
                              file="feature.py", line=1)])


class _Approves:
    def review(self, *, sandbox, workspace, review_input):   # noqa: ARG002
        return ReviewResult(decision="approved", score=95, summary="looks right",
                            cost_usd=REVIEW_COST, model="a-dearer-model", harness="claude_code")


_GREEN = {"test": "true", "security": "true"}

#: (the role the paused pass is counted under, the agent, the manifest, the reviewer, what the
#: passes BEFORE it cost) — one row per way a pass can pause inside `run`.
PAUSES = {
    "planner": ("planner", _PlannerPauses, {"validate": _GREEN, "planner_stage": True},
                None, 0.0),
    "executor": ("executor", _ExecutorPauses, {"validate": _GREEN}, None, 0.0),
    "recovery": ("recovery", _RecoveryPauses, {"validate": _GREEN}, None, EXECUTOR_COST),
    "repair": ("repair", _RepairPauses,
               {"validate": {"test": "false", "security": "true"}, "repair_max_attempts": 1},
               None, EXECUTOR_COST),
    "suppression-repair": ("suppression_repair", _SuppressionRepairPauses, {"validate": _GREEN},
                           None, EXECUTOR_COST),
    "review-repair": ("review_repair", _RepairPauses,
                      {"validate": _GREEN, "review_mode": "blocking",
                       "review_repair_max_attempts": 1},
                      _Rejects, EXECUTOR_COST),
}


def _drive(clone: Path, tmp_path: Path, path: str, events=None):
    _, agent, manifest, reviewer, _ = PAUSES[path]
    return _runner(clone, FakeTracker(_ticket()), Manifest(**manifest), tmp_path,
                   agent=agent(), reviewer=reviewer() if reviewer else None,
                   events=events).run("#1")


def _journalled(events: InMemoryEventSink) -> list[float]:
    return [e.data["cost_usd"] for e in events.events
            if isinstance(e.data.get("cost_usd"), (int, float))]


# ═══ the result carries the pass that paused ════════════════════════════════════════════════════

def test_an_executor_that_spent_and_then_paused_is_charged_to_the_ticket(repo, tmp_path):  # noqa: F811
    """THE ISSUE, as filed: an executor double that reports `cost_usd` and then pauses."""
    result = _drive(repo, tmp_path, "executor")

    assert result.state is JobState.PAUSED, result.note
    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [("executor", SPENT)], (
        "the pass that paused is charged to nobody")
    assert result.total_cost_usd == pytest.approx(SPENT)


def test_the_turns_a_paused_pass_took_reach_the_budget_the_resume_is_measured_against(
        repo, tmp_path):  # noqa: F811
    """`_count` is the effort budget's door as well as the telemetry's (ADR-0013 D4): the resume
    carries `spent_turns` forward, and the budget governs the TICKET, not one attempt. Skipping
    the count handed the resume a budget that had never heard of the paused pass."""
    result = _drive(repo, tmp_path, "executor")

    assert result.state is JobState.PAUSED, result.note
    assert result.spent_turns == TURNS


@pytest.mark.parametrize("path", list(PAUSES))
def test_every_pass_that_pauses_is_counted_on_the_way_out(repo, tmp_path, path):  # noqa: F811
    """One row per way a pass can pause inside `run`. The row is the paused pass's own, the
    total is what every counted pass reported — the paused one included."""
    role, _, _, _, before = PAUSES[path]

    result = _drive(repo, tmp_path, path)

    assert result.state is JobState.PAUSED, result.note
    assert [m.cost_usd for m in result.agent_runs if m.role == role] == [SPENT], (
        f"the {path} pass paused and was charged to nobody — the result carries "
        f"{[(m.role, m.cost_usd) for m in result.agent_runs]}")
    assert result.total_cost_usd == pytest.approx(before + SPENT)


@pytest.mark.parametrize("path", list(PAUSES))
def test_the_journal_says_what_the_result_says(repo, tmp_path, path):  # noqa: F811
    """`/api/jobs` and the panel read the journal, not the result. A pass that paused before it
    wrote its line was spend the dashboard never saw, beside a result that did not see it
    either — two surfaces agreeing on the wrong number."""
    events = InMemoryEventSink()

    result = _drive(repo, tmp_path, path, events=events)

    assert SPENT in _journalled(events), f"the paused {path} pass never reached the journal"
    assert sum(_journalled(events)) == pytest.approx(result.total_cost_usd)


def test_the_dashboard_says_what_the_paused_ticket_spent(repo, tmp_path, monkeypatch):  # noqa: F811
    """The real route over the journal the real runner wrote. The repair path, because on it the
    journal lost the paused pass too — the dashboard said $0.01 for a ticket that spent $0.38."""
    from openfactory.contracts.project import Project
    from openfactory.observability.events import FileEventSink
    from openfactory.paths import events_file

    journal = FileEventSink(events_file(Project(name="demo", repo_path=str(repo)), "#1"))
    result = _drive(repo, tmp_path, "repair", events=journal)

    jobs = _jobs(repo, tmp_path, monkeypatch)

    assert len(jobs) == 1, jobs
    assert jobs[0]["cost_usd"] == pytest.approx(EXECUTOR_COST + SPENT)
    assert jobs[0]["cost_usd"] == pytest.approx(result.total_cost_usd)


def test_a_paused_pass_that_reported_no_price_is_unknown_and_not_free(repo, tmp_path):  # noqa: F811
    """The property `_reported_cost` exists for, which this must not spend: counting the paused
    pass is not pricing it. A harness that reports no cost still has its row — turns and tokens
    are real — and the ticket's total reads as unknown, not as `$0.00`."""
    result = _runner(repo, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
                     agent=_ExecutorPauses(cost=None)).run("#1")

    assert result.state is JobState.PAUSED, result.note
    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [("executor", None)]
    assert result.total_cost_usd is None, "a pass that reported no price was priced"


# ═══ a pass is counted on every way out, not only on the pause ══════════════════════════════════

def test_a_suppression_repair_is_counted_like_every_other_pass(repo, tmp_path):  # noqa: F811
    """It never was, on any way out. The journal carried its price — so `/api/jobs` summed it —
    and the result, the telemetry and the pull request's `Cost:` did not."""

    class _RemovesThePragma(_SuppressionRepairPauses):
        def repair(self, *, sandbox, workspace, context, failure_log):   # noqa: ARG002
            (workspace.path / "feature.py").write_text("VALUE = 42\n")
            return AgentRunResult(ok=True, summary="removed the pragma", cost_usd=0.02)

    events = InMemoryEventSink()
    forge = FakeForge()
    result = _runner(repo, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
                     agent=_RemovesThePragma(), events=events, forge=forge).run("#1")

    assert result.state is JobState.PR_OPEN, result.note
    assert [m.cost_usd for m in result.agent_runs if m.role == "suppression_repair"] == [0.02]
    assert result.total_cost_usd == pytest.approx(EXECUTOR_COST + 0.02)
    assert sum(_journalled(events)) == pytest.approx(result.total_cost_usd)
    assert "Cost: $0.0300" in forge.opened["body"]


def test_a_ticket_the_planner_sends_back_is_charged_for_the_plan(repo, tmp_path):  # noqa: F811
    """The planner's other early return: SPLIT NEEDED. The plan's row went out on the result and
    the total beside it said nobody had reported anything."""

    class _Splits(FakeAgent):
        def plan(self, *, sandbox, workspace, context):   # noqa: ARG002
            return AgentRunResult(ok=True, summary="SPLIT NEEDED: spans three services",
                                  cost_usd=SPENT)

    result = _runner(repo, FakeTracker(_ticket()),
                     Manifest(validate=_GREEN, planner_stage=True), tmp_path,
                     agent=_Splits()).run("#1")

    assert result.state is JobState.NEEDS_REFINEMENT, result.note
    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [("planner", SPENT)]
    assert result.total_cost_usd == pytest.approx(SPENT)


def test_a_hold_after_the_review_is_charged_for_the_review(repo, tmp_path):  # noqa: F811
    """The reviewer's early returns: a merge the forge refuses parks the job, and the hold took
    its total from the result as it stood BEFORE the review — beside rows that included it."""
    result = _runner(repo, FakeTracker(_ticket()),
                     Manifest(validate=_GREEN, merge_policy="auto"), tmp_path,
                     reviewer=_Approves(), forge=FakeForge(merge_fails=5)).run("#1")

    assert result.state is JobState.ON_HOLD, result.note
    assert "review" in [m.role for m in result.agent_runs]
    assert result.total_cost_usd == pytest.approx(EXECUTOR_COST + REVIEW_COST)


# ═══ the guard against the next one ═════════════════════════════════════════════════════════════

def _pauses_before_the_count(method) -> list[str]:
    """Every `if <pass>.pause_reason:` in `method` whose pass was not `_count`ed between the line
    that produced it and the check — the shape the defect had, at five places at once."""
    tree = ast.parse(inspect.getsource(method).lstrip())
    produced: dict[str, list[int]] = {}
    counted: dict[str, list[int]] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    produced.setdefault(t.id, []).append(n.lineno)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_count" and n.args and isinstance(n.args[0], ast.Name)):
            counted.setdefault(n.args[0].id, []).append(n.lineno)
    bad = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
                and n.test.attr == "pause_reason" and isinstance(n.test.value, ast.Name)):
            continue
        name = n.test.value.id
        since = max((ln for ln in produced.get(name, []) if ln < n.lineno), default=0)
        if not any(since < ln < n.lineno for ln in counted.get(name, [])):
            bad.append(f"`{name}` at line {n.lineno} of `{method.__name__}`")
    return bad


def test_no_pass_is_asked_whether_it_paused_before_it_is_counted():
    """THE ORDER IS THE RULE. A pause is a way out, and whatever is asked after it is skipped on
    it — so the count comes first, at every pass, in every walk that can pause. A pass somebody
    adds tomorrow with the check above its `_count` fails here instead of reaching the telemetry
    as spend nobody made."""
    from openfactory.orchestrator.machine import JobRunner

    bad = _pauses_before_the_count(JobRunner.run) + _pauses_before_the_count(JobRunner.repair_ci)

    assert not bad, f"a pass asked whether it paused before it was counted: {bad}"

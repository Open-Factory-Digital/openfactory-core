"""A ticket costs one number, and every surface says that number (#257).

THE TWO DEFECTS, both reported from a live deployment with the default `review_mode: advisory`.

**The review was charged to nobody.** `_count_review` does append the review to `_agent_runs` —
that was fixed once, and its docstring records why: *"the PR's `Cost:` line understated every
ticket while presenting itself as the total"*. The loss moved one layer out. `RunResult` is a
pydantic model, so `agent_runs=self._agent_runs` at construction **copies the list**:

    runs = [AgentRunMetric(...)]
    r = RunResult(ticket_id="1", state="validating", agent_runs=runs)
    runs.append(AgentRunMetric(...))
    len(runs), len(r.agent_runs)          # -> (2, 1)

The result is built at `machine.py:1030`; the review runs after it, at `:1153` and `:1222`. And
`total_cost_usd` was refreshed only at `:1120` and `:1194`, both inside repair loops that run
BEFORE the review — so on the default path nothing refreshed it at all. The review's spend reached
neither the pull request's `Cost:` line nor the per-model telemetry, which is what makes a
reviewer configured to a dearer model invisible.

**And the dashboard reported one pass.** `api/app.py` took the most recent event carrying a cost,
so `GET /api/jobs` showed the LAST pass rather than the ticket: a job with no repairs looked right
by coincidence, and one repair made it wrong. The reporter measured `$4.0265` on the pull request
against `cost_usd: 0.6126` on the dashboard, for the same job.

WHAT IS HELD HERE, by driving the real runner over a real repository and the real route over a
real journal:

    the result     carries every pass this runner counted, the review included
    the total      is the sum of what was reported, and the two cannot drift — the invariant is
                   asked of the result rather than of a number somebody wrote down
    unknown        stays unknown: a harness that reports no cost does not become $0.00, which
                   would make it the cheapest one on the dashboard
    the dashboard  reports the ticket, not its last pass
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openfactory.contracts import (
    AcceptanceCriterion,
    JobState,
    Manifest,
    ReviewResult,
    Ticket,
)
from tests.test_walking_skeleton import (
    FakeTracker,
    _runner,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

#: What the executor's double reports on every pass, from `test_walking_skeleton`'s agent.
EXECUTOR_COST = 0.01
#: The review is its own pass over the whole diff, and on a real deployment often a dearer model.
REVIEW_COST = 0.25


class _PricedReviewer:
    """A reviewer that approves and says what it cost — which is the only thing that makes the
    review visible to the telemetry at all."""

    def __init__(self, cost: float | None = REVIEW_COST) -> None:
        self.cost = cost

    def review(self, *, sandbox, workspace, review_input):   # noqa: ARG002 — the port's shape
        return ReviewResult(
            decision="approved", score=9, acceptance=[], findings=[],
            summary="looks right", cost_usd=self.cost, num_turns=3,
            model="a-dearer-model", harness="claude_code")


def _ticket() -> Ticket:
    return Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


def _drive(clone: Path, tmp_path: Path, reviewer) -> object:
    tracker = FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "security": "true"})
    return _runner(clone, tracker, manifest, tmp_path, reviewer=reviewer).run("#1")


# ═══ the result carries every pass, the review included ═════════════════════════════════════════

def test_the_review_is_charged_to_the_ticket_like_every_other_pass(repo, tmp_path):  # noqa: F811
    """THE DEFECT. The review ran, reported a cost, and `_count_review` recorded it on the runner
    — and the result the caller is handed never heard, because it holds a copy taken before."""
    result = _drive(repo, tmp_path, _PricedReviewer())

    assert result.state is JobState.PR_OPEN, result.note
    roles = [m.role for m in result.agent_runs]
    assert "review" in roles, f"the review is charged to nobody — the result carries {roles}"


def test_the_total_is_the_sum_of_what_was_reported(repo, tmp_path):  # noqa: F811
    """The number the pull request prints as `Cost:`."""
    result = _drive(repo, tmp_path, _PricedReviewer())

    assert result.total_cost_usd == pytest.approx(EXECUTOR_COST + REVIEW_COST)


def test_the_total_and_the_rows_cannot_drift(repo, tmp_path):  # noqa: F811
    """THE INVARIANT, asked of the result rather than of a figure written down here: the two are
    derived separately in the runner, which is exactly how they came apart. A future pass that
    reaches the rows and not the total, or the other way, fails here whatever the number is."""
    result = _drive(repo, tmp_path, _PricedReviewer())

    reported = [m.cost_usd for m in result.agent_runs if m.cost_usd is not None]
    assert result.total_cost_usd == pytest.approx(sum(reported))


def test_a_harness_that_reports_no_cost_is_still_unknown_and_not_free(repo, tmp_path):  # noqa: F811
    """The property `_reported_cost` exists for, which this change must not spend: summing to
    `0.0` renders `$0.00` on the dashboard and makes that harness look FREE — it would win every
    cost comparison, which is the opposite of what the telemetry is for.

    Driven with a reviewer that reports nothing AND an executor that does: the total is the
    executor's alone, and the review is not counted as zero."""
    result = _drive(repo, tmp_path, _PricedReviewer(cost=None))

    assert result.total_cost_usd == pytest.approx(EXECUTOR_COST)
    assert all(m.cost_usd != 0.0 for m in result.agent_runs), "an unreported pass was priced at 0"


def test_a_ticket_nobody_charged_reads_as_unknown(repo, tmp_path):  # noqa: F811
    """No reviewer at all, and nothing anywhere reported: `None`, never `0.0`."""
    from tests.test_walking_skeleton import FakeAgent

    class _Free(FakeAgent):
        def execute(self, **kw):
            res = super().execute(**kw)
            res.cost_usd = None
            return res

        def plan(self, **kw):
            res = super().plan(**kw)
            res.cost_usd = None
            return res

    tracker = FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "security": "true"})
    result = _runner(repo, tracker, manifest, tmp_path, agent=_Free()).run("#1")

    assert result.total_cost_usd is None, "unknown was rendered as a price"


# ═══ the dashboard reports the ticket, not its last pass ════════════════════════════════════════

def _journal(clone: Path, costs: list[float | None]) -> None:
    """A job's events, one per pass, each carrying what that pass cost — the shape the runner
    writes and the shape the reporter measured against."""
    from openfactory.contracts.project import Project
    from openfactory.paths import project_log_dir

    log = project_log_dir(Project(name="demo", repo_path=str(clone)))
    log.mkdir(parents=True, exist_ok=True)
    rows = [{"ts": "2026-09-22T10:00:00+00:00", "job_id": "#5", "ticket_id": "#5",
             "kind": "state", "message": "implementing", "data": {}}]
    rows += [{"ts": f"2026-09-22T10:0{i + 1}:00+00:00", "job_id": "#5", "ticket_id": "#5",
              "kind": "note", "message": f"pass {i}",
              "data": ({"cost_usd": c} if c is not None else {})}
             for i, c in enumerate(costs)]
    rows.append({"ts": "2026-09-22T10:30:00+00:00", "job_id": "#5", "ticket_id": "#5",
                 "kind": "state", "message": "pr_open", "data": {}})
    (log / "5-events.jsonl").write_text("\n".join(json.dumps(r) for r in rows))


def _jobs(clone: Path, tmp_path: Path, monkeypatch) -> list[dict]:
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    # THIS deployment's registry and nothing else: the suite's shared one spans two organisations,
    # which `ProjectRegistry` refuses by name — a refusal about the fixture, not about the cost.
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "t")
    registry = ProjectRegistry()
    registry.add(Project(name="demo", repo_path=str(clone),
                         tracker=ProviderRef(kind="local", repo="demo", options={})))
    return TestClient(app).get("/api/jobs", headers={"Authorization": "Bearer t"}).json()


def test_the_dashboard_reports_the_ticket_and_not_its_last_pass(repo, tmp_path, monkeypatch):  # noqa: F811
    """THE SECOND DEFECT, with the reporter's own figures: an executor pass and one repair. The
    route took the most recent event carrying a cost, so it showed the repair alone — 15% of the
    real figure, on a surface that calls the column `cost_usd` for the job."""
    _journal(repo, [3.4139, 0.6126])

    jobs = _jobs(repo, tmp_path, monkeypatch)

    assert len(jobs) == 1, jobs
    assert jobs[0]["cost_usd"] == pytest.approx(4.0265), (
        f"the dashboard reported one pass, not the ticket: {jobs[0]['cost_usd']}")


def test_a_job_nobody_charged_is_unknown_on_the_dashboard_too(repo, tmp_path, monkeypatch):  # noqa: F811
    """The same rule one surface over: no pass reported, so there is no number — not `0.0`."""
    _journal(repo, [None, None])

    assert _jobs(repo, tmp_path, monkeypatch)[0]["cost_usd"] is None


def test_no_way_out_of_the_walk_hands_back_a_result_it_did_not_charge():
    """THE GUARD AGAINST FORGETTING, because charging is asked of the result-builders rather than
    of one door — `run` returns from twenty-six places, and a decorator is not available: twenty-two
    guards across this suite parse a method's source with `ast.parse(src.lstrip())`, which any
    decorator turns into an `IndentationError`.

    So the rule is held here instead: nothing inside `run` hands back the result it has been
    filling without going through `_charged`. A branch nobody has written yet fails this rather
    than under-reporting a ticket in silence."""
    import ast
    import inspect

    from openfactory.orchestrator.machine import JobRunner

    tree = ast.parse(inspect.getsource(JobRunner.run).lstrip())
    bare = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Name)
            and n.value.id == "result"]

    assert not bare, (
        f"`return result` at line(s) {bare} of `run` hands back a result nobody charged — "
        f"the review's spend would be invisible to it. Use `return self._charged(result)`.")

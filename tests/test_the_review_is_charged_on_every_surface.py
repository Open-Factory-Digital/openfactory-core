"""The review is charged on every surface, so a ticket costs one number everywhere (#310).

#263 made the rule — a ticket costs one number, and every surface says it — and the review pass
broke it on two surfaces. Measured on the #262 branch with a review double priced at $0.25, on the
default advisory path:

    the result        0.26    `_count_review` puts the review in `_agent_runs`
    the journal       0.01    the `review` event carried no `cost_usd`, so `/api/jobs` and the
                              panel's live counter never heard of the review
    the pull request  $0.0100 `_pr_body` read `result.total_cost_usd` before the review was
                              charged; `_charged` ran only at the return, after the body

And the passes after the pull request is open said less again: `repair_ci`'s normal exit reported
`rep.cost_usd` without the review that followed it and carried no rows, `review_pr` carried no
rows, and neither brought the pull request's `Cost:` line up to what the ticket had spent since.

WHAT IS HELD HERE, by driving the real runner over a real repository, the real route over the
journal that runner wrote, and the pull request body the fake forge keeps: for a reviewed ticket
on the advisory path, the blocking path and through a CI repair, the journal's sum, the results'
total, `/api/jobs` and the pull request's `Cost:` line are one number.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    Finding,
    Manifest,
    ReviewResult,
    Ticket,
)
from tests.test_one_cost_for_a_ticket_on_every_surface import _jobs
from tests.test_walking_skeleton import (
    FakeAgent,
    FakeForge,
    FakeTracker,
    _runner,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

#: What the executor's double reports on a pass that finishes, from `test_walking_skeleton`.
EXECUTOR_COST = 0.01
#: Every review here is priced, and on a real deployment it is often the dearer model.
REVIEW_COST = 0.25
#: The review-repair pass on the blocking path.
REVIEW_REPAIR_COST = 0.05
#: The CI-repair pass, after the pull request is open.
CI_REPAIR_COST = 0.03

PR = "https://forge/pr/1"
_GREEN = {"test": "true", "security": "true"}


def _ticket() -> Ticket:
    return Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


def _verdict(decision: str, cost: float | None = REVIEW_COST) -> ReviewResult:
    findings = ([Finding(severity="critical", description="asserts the wrong value",
                         file="feature.py", line=1)] if decision == "rejected" else [])
    return ReviewResult(decision=decision, score=40 if decision == "rejected" else 92,
                        summary=f"{decision} by the double", findings=findings, cost_usd=cost,
                        num_turns=3, model="a-dearer-model", harness="claude_code")


class _Reviewer:
    """Each scripted verdict in turn, holding the last — every one of them priced."""

    def __init__(self, *verdicts: ReviewResult) -> None:
        self.verdicts = list(verdicts) or [_verdict("approved")]
        self.calls = 0

    def review(self, *, sandbox, workspace, review_input):   # noqa: ARG002 — the port's shape
        v = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        return v


class _ReviewFixer(FakeAgent):
    """The blocking path's repair: it edits the file the review rejected."""

    def repair(self, *, sandbox, workspace, context, failure_log):   # noqa: ARG002
        (workspace.path / "feature.py").write_text("VALUE = 43  # per review\n")
        return AgentRunResult(ok=True, summary="answered the finding", cost_usd=REVIEW_REPAIR_COST)


class _CiFixer(FakeAgent):
    """A CI repair that rewrites the pull request — a new file every pass, so it always pushes."""

    def __init__(self, cost: float | None = CI_REPAIR_COST, ok: bool = True) -> None:
        self.cost, self.ok, self.passes = cost, ok, 0

    def repair(self, *, sandbox, workspace, context, failure_log):   # noqa: ARG002
        self.passes += 1
        (workspace.path / f"ci_fix{self.passes}.py").write_text(f"FIXED = {self.passes}\n")
        return AgentRunResult(ok=self.ok, summary="made the check pass" if self.ok else "gave up",
                              cost_usd=self.cost)


# ═══ the three ways a reviewed ticket is walked, each into one journal and one pull request ═════

def _journal(clone: Path):
    from openfactory.contracts.project import Project
    from openfactory.observability.events import FileEventSink
    from openfactory.paths import events_file

    return FileEventSink(events_file(Project(name="demo", repo_path=str(clone)), "#1"))


def _open(clone: Path, tmp_path: Path, forge: FakeForge, **manifest) -> object:
    """The default path unless told otherwise: the executor, one priced review, a pull request."""
    agent = manifest.pop("agent", FakeAgent())
    reviewer = manifest.pop("reviewer", _Reviewer())
    return _runner(clone, FakeTracker(_ticket()), Manifest(validate=_GREEN, **manifest), tmp_path,
                   agent=agent, reviewer=reviewer, forge=forge, events=_journal(clone)).run("#1")


def _ci_repair(clone: Path, tmp_path: Path, forge: FakeForge, *, agent=None,
               reviewer=None) -> object:
    """A FRESH runner, as every activity builds one, against the pull request the first opened."""
    runner = _runner(clone, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
                     agent=agent or _CiFixer(), reviewer=reviewer or _Reviewer(), forge=forge,
                     events=_journal(clone))
    return runner.repair_ci("#1", "FAILED tests/test_app.py::test_value", pr_url=PR)


def _advisory(clone, tmp_path, forge):
    return [_open(clone, tmp_path, forge)], EXECUTOR_COST + REVIEW_COST


def _blocking(clone, tmp_path, forge):
    result = _open(clone, tmp_path, forge, review_mode="blocking", review_repair_max_attempts=1,
                   agent=_ReviewFixer(),
                   reviewer=_Reviewer(_verdict("rejected"), _verdict("approved")))
    return [result], EXECUTOR_COST + REVIEW_COST + REVIEW_REPAIR_COST + REVIEW_COST


def _through_a_ci_repair(clone, tmp_path, forge):
    opened = _open(clone, tmp_path, forge)
    return ([opened, _ci_repair(clone, tmp_path, forge)],
            EXECUTOR_COST + REVIEW_COST + CI_REPAIR_COST + REVIEW_COST)


PATHS = {"advisory": _advisory, "blocking": _blocking, "ci-repair": _through_a_ci_repair}


def _journalled(clone: Path) -> list[dict]:
    path = _journal(clone).path
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _journal_sum(clone: Path) -> float | None:
    costs = [(e.get("data") or {}).get("cost_usd") for e in _journalled(clone)]
    costs = [c for c in costs if isinstance(c, (int, float))]
    return sum(costs) if costs else None


def _pr_cost(forge: FakeForge) -> float | None:
    """What the pull request's own `Cost:` line says — the number a reviewer of it reads."""
    m = re.search(r"^Cost: \$([0-9.]+)$", (forge.opened or {}).get("body", ""), re.MULTILINE)
    return float(m.group(1)) if m else None


# ═══ the guard: one number, on every surface, on every path ═════════════════════════════════════

@pytest.mark.parametrize("path", list(PATHS))
def test_every_surface_says_one_number(repo, tmp_path, monkeypatch, path):  # noqa: F811
    """THE RULE #263 MADE, asked of all four surfaces at once rather than of each one alone —
    two surfaces agreeing on the wrong number is how this stayed open after #263 closed."""
    forge = FakeForge()
    results, spent = PATHS[path](repo, tmp_path, forge)

    surfaces = {
        "the results": sum(r.total_cost_usd or 0.0 for r in results),
        "the journal": _journal_sum(repo),
        "/api/jobs": _jobs(repo, tmp_path, monkeypatch)[0]["cost_usd"],
        "the pull request": _pr_cost(forge),
    }

    wrong = {name: n for name, n in surfaces.items() if n is None or round(n, 4) != round(spent, 4)}
    assert not wrong, f"the ticket spent {spent:.4f}; these surfaces say otherwise: {wrong}"


# ═══ each half of it ════════════════════════════════════════════════════════════════════════════

def test_every_review_event_carries_what_the_review_cost(repo, tmp_path):  # noqa: F811
    """All four `review` events: the first review and the re-review on the blocking path, the
    review after a CI repair, and a re-review a person asked for. Every other pass's line carried
    its price; these were the ones the journal could not sum."""
    forge = FakeForge()
    _blocking(repo, tmp_path, forge)
    _ci_repair(repo, tmp_path, forge)
    _runner(repo, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
            reviewer=_Reviewer(), forge=forge, events=_journal(repo)).review_pr("#1", pr_url=PR)

    reviews = [e for e in _journalled(repo) if e["kind"] == "review"]

    assert len(reviews) == 4, [e["message"] for e in reviews]
    unpriced = [e["message"] for e in reviews if (e.get("data") or {}).get("cost_usd") is None]
    assert not unpriced, f"these reviews reached the journal without their price: {unpriced}"
    assert all(e["data"]["cost_usd"] == REVIEW_COST for e in reviews)


def test_the_pull_request_is_opened_with_the_review_in_its_cost(repo, tmp_path):  # noqa: F811
    """THE SECOND HALF OF THE ISSUE, in its own measured figures: `Cost: $0.0100` against a result
    total of 0.26 — the body was written before the review was charged, and the review had
    already run."""
    forge = FakeForge()
    result = _open(repo, tmp_path, forge)

    assert f"Cost: ${EXECUTOR_COST + REVIEW_COST:.4f}" in forge.opened["body"], (
        f"the pull request prints {_pr_cost(forge)} for a ticket that cost "
        f"{result.total_cost_usd}")


def test_a_ci_repair_carries_its_rows_and_its_charged_total(repo, tmp_path):  # noqa: F811
    """`total_cost_usd=rep.cost_usd` and no rows: the review that follows the repair was charged
    to nobody on the result the workflow reads."""
    forge = FakeForge()
    _open(repo, tmp_path, forge)

    result = _ci_repair(repo, tmp_path, forge)

    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [
        ("ci_repair", CI_REPAIR_COST), ("review", REVIEW_COST)]
    assert result.total_cost_usd == pytest.approx(CI_REPAIR_COST + REVIEW_COST)


def test_a_re_review_carries_its_row_and_its_charged_total(repo, tmp_path):  # noqa: F811
    """`review_pr` is a whole reviewer pass a person paid for by pressing a button. It went on the
    journal, and the result and the pull request never heard of it."""
    forge = FakeForge()
    _open(repo, tmp_path, forge)

    result = _runner(repo, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
                     reviewer=_Reviewer(), forge=forge,
                     events=_journal(repo)).review_pr("#1", pr_url=PR)

    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [("review", REVIEW_COST)]
    assert result.total_cost_usd == pytest.approx(REVIEW_COST)
    assert _pr_cost(forge) == pytest.approx(EXECUTOR_COST + REVIEW_COST + REVIEW_COST)


def test_a_runner_asked_twice_charges_each_pass_once(repo, tmp_path):  # noqa: F811
    """Every activity builds a fresh runner, and nothing in `repair_ci` said it needed one: its
    rows accumulated on the runner across calls. Asked twice, the second result carried the first
    pass's rows as well — and the pull request's line went up by the first pass a second time."""
    forge = FakeForge()
    _open(repo, tmp_path, forge)
    runner = _runner(repo, FakeTracker(_ticket()), Manifest(validate=_GREEN), tmp_path,
                     agent=_CiFixer(), reviewer=_Reviewer(), forge=forge, events=_journal(repo))

    runner.repair_ci("#1", "FAILED tests/test_app.py::test_value", pr_url=PR)
    second = runner.repair_ci("#1", "FAILED tests/test_app.py::test_other", pr_url=PR)

    assert [m.role for m in second.agent_runs] == ["ci_repair", "review"]
    assert second.total_cost_usd == pytest.approx(CI_REPAIR_COST + REVIEW_COST)
    assert _pr_cost(forge) == pytest.approx(
        EXECUTOR_COST + REVIEW_COST + 2 * (CI_REPAIR_COST + REVIEW_COST))
    assert _pr_cost(forge) == pytest.approx(_journal_sum(repo))


def test_a_ci_repair_that_stops_still_reaches_the_cost_line(repo, tmp_path):  # noqa: F811
    """Every way out of the CI repair spends the pass, not only the one that pushes: an agent
    that stops is held — and its price still belongs on the pull request it was working on."""
    forge = FakeForge()
    _open(repo, tmp_path, forge)

    held = _ci_repair(repo, tmp_path, forge, agent=_CiFixer(ok=False))

    assert held.total_cost_usd == pytest.approx(CI_REPAIR_COST)
    assert _pr_cost(forge) == pytest.approx(EXECUTOR_COST + REVIEW_COST + CI_REPAIR_COST)


def test_a_republished_review_does_not_take_the_cost_line_with_it(repo, tmp_path):  # noqa: F811
    """The review section is read as running to the next `## ` heading, or to the END of the
    body. A body with nothing headed after its review — no knowledge section — carries its
    `Cost:` line inside that span, so a fresh verdict replaced it away and a dated one stamped it
    `was:`. The line is not the review's, and it is the one this repair must bring up to date."""
    from openfactory.orchestrator.machine import _review_lines

    forge = FakeForge()
    forge.opened = {"body": "\n".join([
        "Automated by OpenFactory for card 1.", "", "## Objective", "add a feature", "",
        *_review_lines(_verdict("rejected")), "", "Touched components: api", "",
        "Cost: $0.2600"])}
    _open_branch(repo)

    _ci_repair(repo, tmp_path, forge)

    body = forge.opened["body"]
    assert "was: Cost" not in body, "the cost line was dated as though the reviewer had said it"
    assert _pr_cost(forge) == pytest.approx(0.26 + CI_REPAIR_COST + REVIEW_COST), body


def test_a_pass_nobody_priced_leaves_the_cost_line_as_it_stands(repo, tmp_path):  # noqa: F811
    """UNKNOWN STAYS UNKNOWN on this surface too: a repair and a review that reported no price
    move the line by nothing, rather than by a zero somebody would read as free."""
    forge = FakeForge()
    _open(repo, tmp_path, forge)

    result = _ci_repair(repo, tmp_path, forge, agent=_CiFixer(cost=None),
                        reviewer=_Reviewer(_verdict("approved", cost=None)))

    assert result.total_cost_usd is None
    assert _pr_cost(forge) == pytest.approx(EXECUTOR_COST + REVIEW_COST)


def _open_branch(clone: Path) -> None:
    """The pull request's branch on the origin, for a repair driven without the run before it."""
    from tests.test_walking_skeleton import _git

    _git(["checkout", "-b", "openfactory/1"], clone)
    (clone / "feature.py").write_text("VALUE = 42\n")
    _git(["add", "-A"], clone)
    _git(["commit", "-m", "wip"], clone)
    _git(["push", "-u", "origin", "openfactory/1"], clone)
    _git(["checkout", "main"], clone)


# ═══ the panel's live counter sums what the dashboard sums ══════════════════════════════════════

def test_the_panels_live_counter_sums_every_priced_event_as_the_dashboard_does():
    """`/api/jobs` sums every event's `cost_usd`; the job view's running total summed only
    `note` events, so a priced `review` event would reach one and not the other — the same
    ticket, two numbers, one screen apart."""
    panel = (Path(__file__).resolve().parent.parent / "openfactory" / "api" / "panel.html")
    src = panel.read_text()

    adds = [line for line in src.splitlines() if "focus.cost+=" in line]
    assert len(adds) == 1, f"expected the one running total, found {len(adds)}"
    assert 'e.kind=="note"' not in adds[0], (
        f"the live counter still counts only `note` events: {adds[0].strip()}")

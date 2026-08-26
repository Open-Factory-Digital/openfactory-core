"""A commit that changes nothing does not make a review out of date (#179).

MEASURED ON THE PILOT, 2026-08-21. An adjust pass ran on podbeam #107 and pushed. Compared
against the commit before it:

    gh api repos/…/compare/98028947...3581e2ed  →  0 files changed, behind by 0

Identical trees. Nothing in the pull request had moved. And the gate answered:

    /api/inbox   review: "Review out of date"

The verdict that said REJECTED (score 42) — one finding, naming the exact stale migration, which
was the whole reason a person was standing at that gate — was gone from the card, replaced by "the
diff was rewritten after the reviewer read it" about a rewrite that rewrote nothing.

`Review out of date` is the right answer to the diff moving under the reviewer (#153, #149). The
defect was the test behind it: it asked whether a PASS HAD RUN, not whether the CODE HAD CHANGED.
A no-op push is not exotic — a pass that could not act (#178), a formatter that reformatted
nothing, an amend, a rebase that replays identically.

BOTH DIRECTIONS ARE GUARDED HERE, and the twin is the expensive one: a genuinely rewritten diff
must still read as stale, or the fix trades one wrong answer for presenting a rejected review as
current about code it never saw.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

import test_walking_skeleton as spine

from openfactory.contracts import AgentRunResult, JobState, Manifest, RunResult

#: the real-git harness: a bare origin, a repo with one commit pushed to `main`. Borrowed rather
#: than re-built, so this card's guards run against the same checkout shape the spine proves.
repo = spine.repo

STALE = "somebody asked for a change and a pass rewrote the pull request"
REJECTED = {"decision": "rejected", "score": 42,
            "findings": [{"severity": "critical", "description": "the alembic revision is stale",
                          "file": "migrations/env.py"}],
            "gates": [{"name": "test", "passed": True}]}


def _job(verdict: dict | None):
    from openfactory.runtime.temporal.workflow import JobWorkflow

    job = JobWorkflow.__new__(JobWorkflow)
    job._verdict = verdict
    return job


def _result(changed: bool | None) -> RunResult:
    return RunResult(ticket_id="#107", state=JobState.PR_OPEN, code_changed=changed)


# ── the workflow: what a pass reports decides whether the marker stands ──────────────────────────

def test_a_pass_that_changed_nothing_takes_the_marker_back_down():
    job = _job({**REJECTED, "stale": STALE})

    job._the_reviewed_code_is_still_here(_result(False))

    assert "stale" not in job._verdict, (
        "the pull request is byte-identical to the one the reviewer read and the verdict still "
        "declares itself out of date")
    assert job._verdict["decision"] == "rejected", "clearing the marker rewrote the verdict"
    assert job._verdict["findings"][0]["description"] == "the alembic revision is stale", (
        "the finding the person came to the gate to read did not survive")


def test_a_pass_that_DID_rewrite_the_diff_keeps_the_marker():
    """The twin, and the expensive direction. A verdict presented as current about code it never
    read is worse than one that says it is out of date."""
    job = _job({**REJECTED, "stale": STALE})

    job._the_reviewed_code_is_still_here(_result(True))

    assert job._verdict["stale"] == STALE


def test_a_pass_that_could_not_be_MEASURED_keeps_the_marker():
    """`None` is "git could not be asked", not "nothing happened". An unknown never clears."""
    job = _job({**REJECTED, "stale": STALE})

    job._the_reviewed_code_is_still_here(_result(None))

    assert job._verdict["stale"] == STALE


def test_clearing_a_marker_that_is_not_there_invents_nothing():
    job = _job(dict(REJECTED))
    job._the_reviewed_code_is_still_here(_result(False))
    assert "stale" not in job._verdict and job._verdict["decision"] == "rejected"

    absent = _job(None)
    absent._the_reviewed_code_is_still_here(_result(False))
    assert absent._verdict is None, "a job whose review never ran was given one"


def test_BOTH_repair_paths_can_take_the_marker_down():
    """The reachability half. #153's marker is raised in two places and #155's fresh verdict is
    published in two places; a clearing wired into only one of them leaves the other path with the
    defect this card exists to remove — and every behaviour test above would still pass.

    It must also come AFTER the pass: asked before, the answer is about a pass that has not run.
    """
    from openfactory.runtime.temporal.workflow import JobWorkflow

    for method, activity in ((JobWorkflow._ci_merge_loop, "repair_ci"),
                             (JobWorkflow._answer_merge_gate, "adjust_pr")):
        tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(method)))
        pushes = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Name) and n.id == activity]
        clears = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute)
                  and n.attr == "_the_reviewed_code_is_still_here"]
        assert pushes, f"{method.__name__} no longer launches {activity} — this guard is measuring nothing"
        assert clears, (
            f"{method.__name__} raises the stale marker and can never take it down: a pass that "
            f"changed nothing costs the person the verdict")
        assert max(clears) > min(pushes), (
            f"{method.__name__} asks whether the code moved BEFORE {activity} has run")


# ── the machine: the answer is MEASURED on the checkout the pass had in hand ─────────────────────

class _WritingAgent:
    """Repairs by actually writing a file — the pass that did rewrite the pull request."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        (workspace.path / "ci_fix.py").write_text("FIXED = True\n")
        return AgentRunResult(ok=True, summary="fixed it", cost_usd=0.02)


class _IdleAgent:
    """The pass that ran, cost money, and left the tree exactly as it found it."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=True, summary="nothing to do here", cost_usd=0.02)


class _AskingAgent:
    """#178's own case: the instruction could not be acted on, so the agent asked instead of
    inventing a change. It stops WITHOUT writing anything."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        return AgentRunResult(ok=False, summary='the instruction is just "__probe__"', cost_usd=0.01)


class _CommittingThenGivingUpAgent:
    """It committed on its own — it has the checkout and the push remote — and only then gave up.
    The branch it was taken out on says nothing about whether the code moved."""

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        return AgentRunResult(ok=True)

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        (workspace.path / "half.py").write_text("HALF = True\n")
        subprocess.run(["git", "add", "-A"], cwd=workspace.path, check=True, capture_output=True)
        subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=a",
                        "commit", "-m", "half of it"],
                       cwd=workspace.path, check=True, capture_output=True)
        return AgentRunResult(ok=False, summary="got half way and stopped", cost_usd=0.01)


def _pr_branch(repo: Path, name: str) -> None:
    """An open pull request's branch, already pushed, with no local copy left — the shape
    `repair_ci` checks out."""
    spine._git(["checkout", "-b", name], repo)
    (repo / "broken.py").write_text("x\n")
    spine._git(["add", "-A"], repo)
    spine._git(["commit", "-m", "wip"], repo)
    spine._git(["push", "-u", "origin", name], repo)
    spine._git(["checkout", "main"], repo)
    spine._git(["branch", "-D", name], repo)


def _repair(repo: Path, tmp_path: Path, agent, issue: str = "#9") -> RunResult:
    _pr_branch(repo, f"openfactory/{issue.lstrip('#')}")
    tracker = spine.FakeTracker(spine._sizing_ticket_id(issue))
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           agent=agent)
    return runner.repair_ci(issue, "CI failed: test_x broke")


def test_a_pass_that_wrote_a_file_reports_that_the_code_moved(repo: Path, tmp_path: Path):
    result = _repair(repo, tmp_path, _WritingAgent())

    assert result.state is JobState.PR_OPEN
    assert result.code_changed is True


def test_a_pass_that_wrote_nothing_reports_that_it_wrote_nothing(repo: Path, tmp_path: Path):
    result = _repair(repo, tmp_path, _IdleAgent())

    assert result.state is JobState.PR_OPEN
    assert result.code_changed is False, (
        "the pass pushed no change and the pull request will still be told its review is stale")


def test_a_pass_that_could_not_act_leaves_the_pull_request_where_it_was(repo: Path, tmp_path: Path):
    """#178's measured case, and the one that cost the verdict on the pilot: the agent read the
    instruction, said it could not act on it, and nothing was pushed."""
    result = _repair(repo, tmp_path, _AskingAgent())

    assert result.state is JobState.ON_HOLD
    assert result.code_changed is False


def test_giving_up_is_not_the_same_statement_as_changing_nothing(repo: Path, tmp_path: Path):
    """The measurement is taken at the EXIT, not inferred from the branch the pass left by. An
    agent holds the checkout and the push remote; it can commit before it gives up, and then the
    reviewed code really is gone."""
    result = _repair(repo, tmp_path, _CommittingThenGivingUpAgent())

    assert result.state is JobState.ON_HOLD
    assert result.code_changed is True, (
        "the pass committed its half and stopped, and the verdict would be presented as current "
        "about a diff that no longer exists")


def test_a_git_that_could_not_answer_is_not_a_diff(tmp_path: Path):
    """`None`, not the error text. Handing the caller git's stderr as if it were a diff scans
    clean for suppressions and compares unequal to everything — a silent "the code changed" every
    time git could not be asked."""
    class _MuteSandbox:
        def run(self, *, workspace, command, timeout):
            return 128, "fatal: bad revision 'main..HEAD'"

    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(tmp_path, tracker, Manifest(), tmp_path, sandbox=_MuteSandbox())

    assert runner._pr_diff(None, "main") is None


def test_a_diff_git_DID_answer_comes_back_whole(tmp_path: Path):
    """The positive twin: an empty diff from a healthy git is a real answer — "" is not None, and
    the difference between them is the whole point of the field."""
    class _QuietSandbox:
        def run(self, *, workspace, command, timeout):
            return 0, ""

    tracker = spine.FakeTracker(spine._sizing_ticket_id("#9"))
    runner = spine._runner(tmp_path, tracker, Manifest(), tmp_path, sandbox=_QuietSandbox())

    assert runner._pr_diff(None, "main") == ""

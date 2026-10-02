"""#448 slice 2 — a person's adjust pass is gated the way the first pass was.

MEASURED ON A LIVE RUN (#448, card #1000007). An adjust pass is `JobRunner.repair_ci` with a
person's words, and on that path `_validate` was never called: the pass rewrote the pull request,
pushed, and went to re-review with none of the project's gates re-run in the box. The requester was
then handed a preview of a head nothing had built or tested.

WHAT IS PROVEN HERE, on a real repository with a bare origin, the worktree box running the gates as
shell commands, and the machine's own repair loop:

  · a pass whose gates pass is pushed, and its gates travel on the result and into the re-review;
  · a red pass is repaired in the box before anything is pushed;
  · a pass still red after the repair budget is held, and NOTHING is pushed: the branch on the
    forge is the one the reviewer read, and `code_changed` is False;
  · a gate that could not run is not handed to an agent to "fix";
  · a check's repair (`human=False`) is not gated here: the forge re-runs that check on the push;
  · the verdict a gated pass brings back does not claim the gates were not re-run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from openfactory.contracts import AgentRunResult, JobState, Manifest, ValidationResult
from tests.test_walking_skeleton import (
    FakeForge,
    FakeReviewer,
    FakeTracker,
    _git,
    _runner,
    _sizing_ticket_id,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

PR = "https://forge/pr/1"
ASKED = "put the button on the right"
#: The project's one gate: red while `red.txt` exists in the tree.
GATED = Manifest(validate={"test": "test ! -e red.txt"})


class _Agent:
    """Writes the change it was asked for and, when told to, leaves the gate red.

    `fixes` is how many of the gate-repair passes may actually fix it; -1 never does."""

    def __init__(self, *, red: bool, fixes: int = 1):
        self.briefs: list[str] = []
        self.red, self.fixes = red, fixes

    def repair(self, *, sandbox, workspace, context, failure_log):
        self.briefs.append(failure_log)
        tree = Path(workspace.path)
        if len(self.briefs) == 1:
            (tree / "button.py").write_text("SIDE = 'right'\n")
            if self.red:
                (tree / "red.txt").write_text("the gate is red\n")
        elif self.fixes != -1 and len(self.briefs) - 1 <= self.fixes:
            (tree / "red.txt").unlink(missing_ok=True)
        return AgentRunResult(ok=True, summary=f"pass {len(self.briefs)}", cost_usd=0.01,
                              actions=[])


class _RecordingReviewer(FakeReviewer):
    def __init__(self):
        self.inputs = []

    def review(self, *, sandbox, workspace, review_input):
        self.inputs.append(review_input)
        return super().review(sandbox=sandbox, workspace=workspace, review_input=review_input)


def _an_open_pull_request(repo: Path) -> str:  # noqa: F811 — the fixture's value, by its name
    _git(["checkout", "-b", "openfactory/9"], repo)
    (repo / "feature.py").write_text("x = 1\n")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "the first pass"], repo)
    _git(["push", "-u", "origin", "openfactory/9"], repo)
    _git(["checkout", "main"], repo)
    _git(["branch", "-D", "openfactory/9"], repo)
    return _on_the_forge(repo)


def _on_the_forge(repo: Path) -> str:  # noqa: F811
    """The pull request's head as the forge holds it: the bare origin's branch."""
    return subprocess.run(
        ["git", "--git-dir", str(repo.parent / "origin.git"), "rev-parse", "openfactory/9"],
        check=True, capture_output=True, text=True).stdout.strip()


def _pushed_tree(repo: Path) -> set[str]:  # noqa: F811
    out = subprocess.run(
        ["git", "--git-dir", str(repo.parent / "origin.git"), "ls-tree", "--name-only",
         "openfactory/9"], check=True, capture_output=True, text=True).stdout
    return set(out.split())


def _gates(result) -> dict[str, bool]:
    """The gates a result carries, by name. `security` is the manifest's default gate."""
    return {v.name: v.passed for v in result.validations}


def _machine(repo: Path, tmp_path: Path, agent, manifest=GATED, reviewer=None):  # noqa: F811
    tracker = FakeTracker(_sizing_ticket_id("#9"))
    runner = _runner(repo, tracker, manifest, tmp_path, agent=agent, forge=FakeForge(),
                     reviewer=reviewer)
    return runner, tracker


def test_a_pass_whose_gates_pass_is_pushed_and_its_gates_reach_the_review(repo, tmp_path):  # noqa: F811
    first = _an_open_pull_request(repo)
    reviewer = _RecordingReviewer()
    runner, _ = _machine(repo, tmp_path, _Agent(red=False), reviewer=reviewer)

    got = runner.repair_ci("#9", ASKED, pr_url=PR, human=True)

    assert got.state is JobState.PR_OPEN and got.code_changed is True
    assert _on_the_forge(repo) != first and "button.py" in _pushed_tree(repo)
    assert _gates(got) == {"test": True, "security": True}
    (read,) = reviewer.inputs
    assert "test" in [v.name for v in read.validations], (
        "the re-review was handed no gates, so it can only read NOT VERIFIED")


def test_a_red_pass_is_repaired_in_the_box_before_anything_is_pushed(repo, tmp_path):  # noqa: F811
    _an_open_pull_request(repo)
    agent = _Agent(red=True, fixes=1)
    runner, _ = _machine(repo, tmp_path, agent)

    got = runner.repair_ci("#9", ASKED, pr_url=PR, human=True)

    assert len(agent.briefs) == 2, "the red gate was never handed back to the agent"
    assert "test" in agent.briefs[1] and ASKED not in agent.briefs[1]
    assert got.state is JobState.PR_OPEN and _gates(got)["test"] is True
    assert _pushed_tree(repo) >= {"button.py"} and "red.txt" not in _pushed_tree(repo)


def test_a_pass_still_red_is_held_and_nothing_is_pushed(repo, tmp_path):  # noqa: F811
    first = _an_open_pull_request(repo)
    agent = _Agent(red=True, fixes=-1)
    runner, tracker = _machine(repo, tmp_path, agent)

    got = runner.repair_ci("#9", ASKED, pr_url=PR, human=True)

    assert len(agent.briefs) == 1 + GATED.repair_max_attempts
    assert _on_the_forge(repo) == first, "a red head was pushed under the requester's preview"
    assert got.state is JobState.ON_HOLD
    # the pull request is the one the reviewer read, and a resume goes back to the merge watch
    assert got.code_changed is False and got.merge_refused is True
    assert "`test` exit 1" in got.note and "Nothing was pushed" in got.note
    assert any("Nothing was pushed" in c for c in tracker.comments)
    assert _gates(got)["test"] is False


def test_a_gate_that_could_not_run_is_not_handed_to_an_agent(repo, tmp_path):  # noqa: F811
    first = _an_open_pull_request(repo)
    agent = _Agent(red=False)
    runner, _ = _machine(repo, tmp_path, agent,
                         manifest=Manifest(validate={"test": "no-such-tool-in-this-box --run"}))

    got = runner.repair_ci("#9", ASKED, pr_url=PR, human=True)

    assert len(agent.briefs) == 1, "an agent was paid to fix a tool that is not installed"
    assert got.state is JobState.ON_HOLD and "could not run" in got.note
    assert _on_the_forge(repo) == first


def test_a_checks_repair_is_not_gated_here(repo, tmp_path):  # noqa: F811
    """The forge re-runs the check it answers on the push, and that run is its gate."""
    first = _an_open_pull_request(repo)
    runner, _ = _machine(repo, tmp_path, _Agent(red=True, fixes=-1))

    got = runner.repair_ci("#9", "FAILED tests/test_x.py::test_it", pr_url=PR)

    assert got.state is JobState.PR_OPEN and got.validations == []
    assert _on_the_forge(repo) != first


def test_the_verdict_of_a_gated_pass_does_not_say_the_gates_were_not_re_run():
    from tests.test_a_review_belongs_to_the_code_it_read import _job, _Passed

    class _Gated(_Passed):
        validations = (ValidationResult(name="test", command="t", exit_code=0, passed=True),)

    job = _job()
    job._reviewed_again(_Gated())
    assert "gates_note" not in job._verdict
    assert job._verdict["gates"] == [{"name": "test", "passed": True, "advisory": False}]

    job = _job()
    job._reviewed_again(_Passed())
    assert job._verdict["gates_note"], "a pass with no gates must still say so"

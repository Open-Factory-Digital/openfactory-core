"""The commit path strips any agent change under .github/workflows/ before committing — so a
push is never rejected for the bot's (deliberately withheld) `workflows` permission and the rest
of the ticket still lands. This mirrors the exact shell prefix in machine._commit; a
CI/workflow change is human-only. Also asserts the prefix is wired into machine._commit."""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

from openfactory.orchestrator import machine

# the exact strip machine._commit runs before `git add -A && git commit`
_STRIP = (
    "git checkout -- .github/workflows 2>/dev/null; "
    "git clean -fdq .github/workflows 2>/dev/null; "
)


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo)}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env={**env}).stdout


def test_commit_strips_workflow_changes_keeps_the_rest(tmp_path: Path):
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\n")  # tracked
    (repo / "app.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")

    # the "agent" now: modifies the tracked workflow, ADDS a new workflow, and edits real code
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: [push]\n# HACKED gate\n")
    (repo / ".github" / "workflows" / "deploy.yml").write_text("name: deploy\n")  # new, untracked
    (repo / "app.py").write_text("x = 2  # the real work\n")

    # run the exact strip + commit the pipeline uses
    subprocess.run(f"{_STRIP}git add -A && git commit -qm work || true", shell=True, cwd=repo,
                   check=True, env={"HOME": str(repo), "GIT_AUTHOR_NAME": "b",
                                    "GIT_AUTHOR_EMAIL": "b@b", "GIT_COMMITTER_NAME": "b",
                                    "GIT_COMMITTER_EMAIL": "b@b"})

    # the workflow modification was reverted, the new workflow removed — nothing under
    # .github/workflows/ would reach the push
    assert (repo / ".github" / "workflows" / "ci.yml").read_text() == "name: ci\non: [push]\n"
    assert not (repo / ".github" / "workflows" / "deploy.yml").exists()
    # …but the real code change DID land
    assert "the real work" in (repo / "app.py").read_text()
    files = _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert "app.py" in files
    assert not any(f.startswith(".github/workflows/") for f in files)


def test_strip_is_wired_into_machine_commit():
    # guard: the strip prefix must actually be in machine._commit (not just this test)
    src = inspect.getsource(machine.StateMachine._commit if hasattr(machine, "StateMachine")
                            else machine.JobRunner._commit)
    assert "git checkout -- .github/workflows" in src
    assert "git clean -fdq .github/workflows" in src


# ── the strip must never be SILENT: dropped CI work is scope loss a human has to see ────────────

class _RecordingSink:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


class _PorcelainSandbox:
    """A sandbox stub whose `git status --porcelain` reports pending workflow changes."""

    def __init__(self, porcelain: str) -> None:
        self.porcelain = porcelain

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        return (0, self.porcelain if "status --porcelain" in command else "")


def _runner(sandbox, sink):
    from openfactory.contracts import Manifest
    from openfactory.orchestrator import JobRunner

    r = JobRunner.__new__(JobRunner)
    r.sandbox, r.events, r.manifest = sandbox, sink, Manifest()
    return r


def _ticket():
    from openfactory.contracts import Ticket

    return Ticket(id="#447", title="t", objective="o", repo="o/r")


def test_stripped_workflows_are_announced_and_land_in_the_pr_body():
    """A ticket whose acceptance criteria included a CI change would otherwise merge green while
    that half quietly never happened. The drop must reach the journal AND the PR body."""
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import JobState, RunResult

    sink = _RecordingSink()
    sandbox = _PorcelainSandbox(" M .github/workflows/ci.yml\n?? .github/workflows/e2e.yml\n")
    r = _runner(sandbox, sink)
    ws = Workspace(path=Path("/tmp/x"), branch="b", base_branch="main")

    r._note_stripped_workflows(ws, _ticket())

    warn = [e for e in sink.events if e.kind == "warning"]
    assert len(warn) == 1
    assert ".github/workflows/ci.yml" in warn[0].message
    assert ".github/workflows/e2e.yml" in warn[0].message

    body = r._pr_body(_ticket(), RunResult(ticket_id="#447", state=JobState.PR_OPEN))
    assert "CI/workflow changes NOT included" in body
    assert "`.github/workflows/ci.yml`" in body and "`.github/workflows/e2e.yml`" in body
    assert "a human must apply them separately" in body.lower()

    # a second pass over the SAME paths must not spam the journal again
    r._note_stripped_workflows(ws, _ticket())
    assert len([e for e in sink.events if e.kind == "warning"]) == 1


def test_pr_body_is_unchanged_when_no_workflow_was_touched():
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import JobState, RunResult

    sink = _RecordingSink()
    r = _runner(_PorcelainSandbox(""), sink)
    r._note_stripped_workflows(Workspace(path=Path("/tmp/x"), branch="b", base_branch="main"),
                               _ticket())
    assert sink.events == []
    assert "NOT included" not in r._pr_body(_ticket(),
                                            RunResult(ticket_id="#447", state=JobState.PR_OPEN))


def test_a_brand_new_workflow_directory_is_reported_file_by_file(tmp_path: Path):
    """Against a REAL repo: git collapses a wholly-new untracked directory into one
    "?? .github/workflows/" line, which would tell the human a directory was dropped without
    naming a file they can re-apply."""
    repo = tmp_path
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    # the agent creates .github/ from scratch (the repo had no CI at all)
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    (repo / ".github" / "workflows" / "visual.yml").write_text("name: visual\n")

    class _RealSandbox:
        def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
            out = subprocess.run(command, shell=True, cwd=repo, capture_output=True, text=True,
                                 env={"HOME": str(repo)}, check=False)
            return out.returncode, out.stdout

    sink = _RecordingSink()
    r = _runner(_RealSandbox(), sink)
    from openfactory.adapters.sandbox.base import Workspace

    r._note_stripped_workflows(Workspace(path=repo, branch="b", base_branch="main"), _ticket())

    msg = sink.events[0].message
    assert ".github/workflows/ci.yml" in msg
    assert ".github/workflows/visual.yml" in msg

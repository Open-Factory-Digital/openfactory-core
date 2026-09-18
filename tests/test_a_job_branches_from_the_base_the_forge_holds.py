"""A job on the worktree box starts from the base the FORGE holds, not the copy last fetched (#168).

The worktree box cut every new job's branch from the LOCAL base branch of `repo_path`, and nothing
fetched it first. On a local forge that is right: the local base IS the base. On a hosted forge, a
project registered by path points at somebody's clone, and its `main` is whatever was last pulled —
measured on the first day of the deployment that reported this, already a merge behind. The card was
then planned, written, validated and reviewed against code that was no longer on the base, and its
pull request opened against the real one: with conflicts, or with the merged change missing from
everything the gates had proved.

Moving the start is half the fix. The job's diff — what the reviewer reads, what the suppression
scan and the protected-path gate judge, what decides "the agent changed nothing" — was read as
`<base>..HEAD` against that same stale local branch, so a branch cut from the forge's base would
have been judged on the merged change as well as its own. The diff is measured from where the job
left the forge's base.

Proven against REAL git repositories: a bare forge, and a clone of it that is a merge behind.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import AcceptanceCriterion, JobState, Manifest, Ticket

pytest_plugins = ["tests.test_walking_skeleton"]


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout.strip()


def _commit(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


@pytest.fixture
def behind(tmp_path):
    """forge (bare: main = base + the merged change) ← clone (main = base only).

    The clone is the person's checkout the project was registered from; it was cloned before
    somebody merged `merged.py` on the forge, and nobody has pulled since."""
    forge = tmp_path / "forge.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(forge)],
                   capture_output=True, check=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], capture_output=True, check=True)
    _commit(seed, "README.md", "# app\n", "base")
    _git(seed, "remote", "add", "origin", str(forge))
    _git(seed, "push", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(forge), str(clone)], capture_output=True, check=True)

    # It carries a suppression, as merged code may: a diff read against the stale base puts it
    # in front of the suppression gate as this job's own, which holds the job for a human.
    _commit(seed, "merged.py", "import os  # noqa\nMERGED = True\n",
            "the change a person merged on the forge")
    _git(seed, "push", "origin", "main")
    assert not (clone / "merged.py").exists(), "the clone must be a merge behind the forge"
    # `file://`, as the existing guards do, standing in for the forge's authenticated HTTPS URL:
    # it names somewhere OTHER than the clone, which is what makes this a hosted forge.
    return f"file://{forge}", clone, seed, tmp_path


# ── the start ───────────────────────────────────────────────────────────────────────────────────

def test_a_new_job_starts_from_the_base_the_forge_holds(behind):
    forge, clone, seed, tmp = behind

    ws = WorktreeSandbox(root=tmp / "wt").prepare(
        repo_path=clone, base_branch="main", branch="openfactory/1", remote_url=forge)

    assert (ws.path / "merged.py").exists(), (
        "the job started from the clone's stale `main` — it will be planned, written and "
        "validated against code that is no longer on the base")
    assert _git(ws.path, "rev-parse", "HEAD") == _git(seed, "rev-parse", "main")


def test_the_persons_checkout_is_not_moved(behind):
    """The clone is somebody's working copy. Its `main`, its `origin/main` and its working tree
    stay where they were: the job's own branch is the only ref that moves."""
    forge, clone, seed, tmp = behind
    main_before = _git(clone, "rev-parse", "refs/heads/main")
    tracking_before = _git(clone, "rev-parse", "refs/remotes/origin/main")

    WorktreeSandbox(root=tmp / "wt").prepare(
        repo_path=clone, base_branch="main", branch="openfactory/1", remote_url=forge)

    assert _git(clone, "rev-parse", "refs/heads/main") == main_before
    assert _git(clone, "rev-parse", "refs/remotes/origin/main") == tracking_before
    assert _git(clone, "status", "--porcelain") == ""


def test_a_forge_that_cannot_be_asked_stops_the_job_by_name(behind):
    """No network, an expired credential: the base cannot be read, and starting from the stale
    copy instead is the defect itself, arriving silently. Nothing after `prepare` can succeed
    without the forge either — the job ends by pushing to it — so refusing here costs nothing the
    job could have kept, and it refuses BEFORE an agent spends anything."""
    forge, clone, seed, tmp = behind

    with pytest.raises(RuntimeError, match=r"could not read 'main' from the forge"):
        WorktreeSandbox(root=tmp / "wt").prepare(
            repo_path=clone, base_branch="main", branch="openfactory/1",
            remote_url=f"file://{tmp / 'no-such-forge.git'}")

    assert _git(clone, "branch", "--list", "openfactory/1") == "", "a half-made branch was left"
    assert len(_git(clone, "worktree", "list").splitlines()) == 1, "a half-made worktree was left"


# ── the diff the gates judge ────────────────────────────────────────────────────────────────────

def test_the_jobs_diff_is_its_own_change_and_not_the_merge_it_started_after(behind):
    forge, clone, seed, tmp = behind
    box = WorktreeSandbox(root=tmp / "wt")
    ws = box.prepare(repo_path=clone, base_branch="main", branch="openfactory/1",
                     remote_url=forge)

    _commit(ws.path, "feature.py", "VALUE = 42\n", "the job's change")

    assert box.diff_paths(workspace=ws) == ["feature.py"], (
        "the diff was read against the clone's stale `main`, so the merged change is judged as "
        "this job's own: the protected-path gate and the risk assessment see files it never "
        "touched")


def test_a_pull_request_reopened_for_repair_is_measured_from_where_it_left_the_base(behind):
    """A CI repair or a review pass reopens the pull request's branch from the forge. Its diff is
    what the pull request holds — from where it left the base — not what separates it from the
    clone's stale `main`, and not what separates it from a base that has moved on since either."""
    forge, clone, seed, tmp = behind
    _git(seed, "checkout", "-b", "openfactory/2")
    _commit(seed, "pr.py", "PR = 1\n", "the pull request's change")
    _git(seed, "push", "origin", "openfactory/2")
    _git(seed, "checkout", "main")
    _commit(seed, "later.py", "LATER = 1\n", "merged on the forge after the pull request opened")
    _git(seed, "push", "origin", "main")

    box = WorktreeSandbox(root=tmp / "wt")
    ws = box.prepare(repo_path=clone, base_branch="main", branch="openfactory/2",
                     checkout_existing=True, remote_url=forge)

    assert (ws.path / "pr.py").exists(), "the repair must start from the pull request's own tip"
    assert box.diff_paths(workspace=ws) == ["pr.py"]


# ── where there is no forge to be behind ────────────────────────────────────────────────────────

def test_a_local_forge_reads_its_own_base(tmp_path):
    """On a local forge the forge's URL IS the repository (ADR-0049 D3): the local base is the
    base, and there is no `origin` to fetch from."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
    _commit(repo, "README.md", "# app\n", "base")
    box = WorktreeSandbox(root=tmp_path / "wt")

    ws = box.prepare(repo_path=repo, base_branch="main", branch="openfactory/1",
                     remote_url=str(repo))
    _commit(ws.path, "feature.py", "VALUE = 42\n", "the job's change")

    assert box.diff_paths(workspace=ws) == ["feature.py"]
    assert _git(repo, "for-each-ref", "refs/remotes") == "", "a remote-tracking ref was invented"


def test_a_caller_that_names_no_forge_is_not_sent_to_one(behind):
    """The box proof and the first-run rehearsal call `prepare` with no forge URL: they read the
    person's checkout and never push. Sending them to `origin` would reach a network remote with
    whatever ambient credential the person's git has — a prompt nobody is there to answer."""
    forge, clone, seed, tmp = behind

    ws = WorktreeSandbox(root=tmp / "wt").prepare(
        repo_path=clone, base_branch="main", branch="openfactory/1")

    assert not (ws.path / "merged.py").exists()


# ── the job, end to end ─────────────────────────────────────────────────────────────────────────

def test_the_reviewer_reads_the_jobs_own_change_on_a_clone_that_is_behind(behind):
    """Through the orchestrator, both halves at once. The branch the job pushes contains the
    forge's base — on `main`'s code it did not, and the pull request opened behind. And the
    reviewer is handed the job's own diff, which the "changed nothing" hold and the suppression
    scan read too: moving the start without moving what the diff is measured from hands the
    reviewer `merged.py`, a file this job never touched."""
    from tests.test_walking_skeleton import FakeForge, FakeTracker, _runner

    forge, clone, seed, tmp = behind

    class _HostedForge(FakeForge):
        def push_remote(self) -> str | None:
            return forge

    seen: list[str] = []

    class _Reviewer:
        def review(self, *, sandbox, workspace, review_input):
            from openfactory.contracts import ReviewResult

            seen.append(review_input.diff)
            return ReviewResult(decision="approved", score=90, findings=[], summary="ok")

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    runner = _runner(clone, FakeTracker(ticket), Manifest(validate={"test": "true"}), tmp,
                     reviewer=_Reviewer(), forge=_HostedForge())

    result = runner.run("#1")

    assert result.state is JobState.PR_OPEN, result
    assert seen and "feature.py" in seen[0]
    assert "merged.py" not in seen[0], "the reviewer judged a merged change as this job's own"
    assert result.added_suppressions == [], "the merged change's `# noqa` was judged as this job's"
    pushed = _git(Path(forge.removeprefix("file://")), "rev-parse", "openfactory/1")
    assert _git(Path(forge.removeprefix("file://")), "merge-base", "--is-ancestor",
                "main", pushed) == ""


def _hosted(forge: str):
    from tests.test_walking_skeleton import FakeForge

    class _HostedForge(FakeForge):
        def push_remote(self) -> str | None:
            return forge

    return _HostedForge()


def test_the_suppression_re_read_after_a_repair_is_the_jobs_own(behind):
    """The suppression-repair pass removes the job's own pragma and the diff is read again. Read
    against the stale base, that second read finds the merged change's `# noqa`, and a job whose
    only suppression was resolved is held for one it never wrote."""
    from tests.test_walking_skeleton import (
        FakeTracker,
        _PragmaRemovableAgent,
        _runner,
        _supp_ticket,
    )

    forge, clone, seed, tmp = behind
    runner = _runner(clone, FakeTracker(_supp_ticket("#50")),
                     Manifest(merge_policy="auto", validate={"test": "true"}), tmp,
                     agent=_PragmaRemovableAgent(), forge=_hosted(forge))

    result = runner.run("#50")

    assert result.added_suppressions == []
    assert result.state is JobState.DONE and runner.forge.merged is True


def test_the_re_review_after_a_review_repair_reads_the_jobs_own_change(behind):
    """A blocking review rejects, the executor repairs, and the diff is read again for the guard
    and the re-review — the third reader of the same range."""
    from openfactory.contracts import Finding, ReviewResult
    from tests.test_walking_skeleton import FakeAgent, FakeTracker, _runner

    forge, clone, seed, tmp = behind
    seen: list[str] = []

    class _RejectsOnce:
        def review(self, *, sandbox, workspace, review_input):
            seen.append(review_input.diff)
            if len(seen) == 1:
                return ReviewResult(decision="rejected", score=40, summary="name it",
                                    findings=[Finding(severity="high", description="rename")])
            return ReviewResult(decision="approved", score=90, findings=[], summary="ok")

    class _Repairs(FakeAgent):
        def repair(self, *, sandbox, workspace, context, failure_log):
            from openfactory.contracts import AgentRunResult

            (workspace.path / "feature.py").write_text("ANSWER = 42\n")
            return AgentRunResult(ok=True, summary="renamed", cost_usd=0.01, actions=["Edit"])

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    runner = _runner(clone, FakeTracker(ticket),
                     Manifest(merge_policy="auto", review_mode="blocking",
                              validate={"test": "true"}),
                     tmp, agent=_Repairs(), reviewer=_RejectsOnce(), forge=_hosted(forge))

    result = runner.run("#1")

    assert len(seen) == 2, "the review-repair loop did not run"
    assert "merged.py" not in seen[1]
    assert result.added_suppressions == []
    assert result.state is JobState.DONE and runner.forge.merged is True


def test_the_pull_requests_diff_is_read_from_where_it_left_the_base(behind):
    """`_pr_diff` and `_pr_diff_paths` are what a CI repair, a review pass and the knowledge gate
    read as "what is in this pull request" — the reviewer's identity check (#179) and the
    protected-path gate among them."""
    from tests.test_walking_skeleton import FakeTracker, _runner

    forge, clone, seed, tmp = behind
    _git(seed, "checkout", "-b", "openfactory/2")
    _commit(seed, "pr.py", "PR = 1\n", "the pull request's change")
    _git(seed, "push", "origin", "openfactory/2")
    ticket = Ticket(id="#2", title="t", objective="o", repo="o/app")
    runner = _runner(clone, FakeTracker(ticket), Manifest(validate={"test": "true"}), tmp,
                     forge=_hosted(forge))
    ws = runner.sandbox.prepare(repo_path=clone, base_branch="main", branch="openfactory/2",
                                checkout_existing=True, remote_url=forge)

    assert runner._pr_diff_paths(ws, "main") == ["pr.py"]
    assert "merged.py" not in (runner._pr_diff(ws, "main") or "")


def test_an_agent_that_changed_nothing_is_told_so_on_a_clone_that_is_behind(behind):
    """The first read of the job's diff decides "the agent changed nothing". Read against the
    stale base, the merged change makes it non-empty, and a pass that wrote nothing goes on to
    open a pull request instead of being handed back."""
    from openfactory.contracts import AgentRunResult
    from tests.test_walking_skeleton import FakeTracker, _runner

    forge, clone, seed, tmp = behind

    class _WritesNothing:
        def execute(self, *, sandbox, workspace, context):
            return AgentRunResult(ok=True, summary="nothing to do", cost_usd=0.01, actions=[])

        def repair(self, *, sandbox, workspace, context, failure_log):
            return AgentRunResult(ok=True)

    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    runner = _runner(clone, FakeTracker(ticket), Manifest(validate={"test": "true"}), tmp,
                     agent=_WritesNothing(), forge=_hosted(forge))

    result = runner.run("#1")

    assert result.state is JobState.NEEDS_REFINEMENT, result
    assert runner.forge.opened is None, "a pull request was opened for a pass that changed nothing"

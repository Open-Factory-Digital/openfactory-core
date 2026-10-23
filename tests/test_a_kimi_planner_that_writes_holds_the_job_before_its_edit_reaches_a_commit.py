"""A Kimi planner that writes holds the job before its edit reaches a commit (#788, criterion 1).

#783 made Kimi Code's planner read-only by instruction only: kimi-code 0.31.1 refuses `--plan`
beside `-p` and has no policy flag. The planner runs on the job's own workspace. `JobRunner.run`
prepares `ws` once, runs `_run_setup`, then `agent.plan(workspace=ws)` and `agent.execute(
workspace=ws)` on the same tree, and `_commit` sweeps it with `git add -A && git commit`. Measured
on 620bb577 (2026-10-20): a planner that writes `planted.txt` reaches `PR_OPEN` with the file in
the pushed branch. A planner that writes and then hits a rate limit goes through `_paused` →
`_preserve_partial`, which commits the file and pushes it to the forge before any pull request.

WHAT IS HELD HERE, by driving the real runner through the box's own `run` over a real repository
with a bare origin: after a Kimi plan pass the workspace is asked whether the pass wrote, against
the tree as setup left it, and a pass that wrote holds the job (`ON_HOLD`) naming each path, with
nothing committed or pushed and the executor never called. The ways in are the four a porcelain
read cannot all see: a new file, an edited tracked file, a planner `git commit` (porcelain clean,
HEAD moved) and an append to a file setup already left untracked (`?? build.log` before and after).
A workspace that cannot be asked holds the job too, with its own sentence (engineering lesson 2:
"could not see" is not "nothing was written"). Each hold declares its cause (`unknown` for a
planner that wrote, `environment` for a workspace that cannot be asked), because the workflow reads
a hold that declares none by its prose, and a path such as `src/rate_limit.py` reads as throttling.

THE REVERSES ARE GREEN ON MAIN BY DESIGN: what setup leaves is not charged to the planner, a planner
that writes nothing runs on, and a harness whose planner the CLI holds read-only (a double named
`codex`) is not asked at all (the scope is Kimi only, open question Q2's default). Each turns red
under a cut in `tools/mutations/788_a_kimi_planner_that_writes_holds_the_job.py`.

The `[container]` rows run through `ContainerSandbox` on the image `resolve_box_image` names, and
skip at run time, naming the image and the command that builds it, where it is not built (CI's
runners never build it). Without a daemon they skip, or fail under `TEST_REQUIRE_DOCKER`.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

from openfactory.adapters.agent.kimi import KimiAdapter
from openfactory.adapters.sandbox import WorktreeSandbox
from openfactory.adapters.sandbox.timeouts import TIMEOUT_EXIT, timeout_result
from openfactory.contracts import AcceptanceCriterion, AgentRunResult, JobState, Manifest, Ticket
from openfactory.observability import InMemoryEventSink
from openfactory.orchestrator import JobRunner
from tests.test_walking_skeleton import FakeForge, FakeTracker

#: What the fingerprint of a workspace runs, in the plan's words (task 12): the tree `git add -A`
#: would commit, written from a copy of the index. The doubles below recognise the fingerprint by
#: the command it executes, never by a module that does not exist on main, so the rows are red on
#: main for the behaviour and not for an import.
FINGERPRINT_RUNS = "write-tree"

#: What the paused planner had spent when the limit hit, distinct from every other price here.
SPENT = 0.37

#: git's own refusal on a mount it does not trust: a client image without `safe.directory`.
DUBIOUS = ("fatal: detected dubious ownership in repository at '/workspace'\n"
           "To add an exception for this directory, call:\n\n"
           "\tgit config --global --add safe.directory /workspace\n")


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one tracked `README.md`, pushed to a bare origin `publish_branch` pushes
    to for real (the walking skeleton's shape, copied rather than imported)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-b", "main"], r)
    _git(["config", "user.email", "t@t.dev"], r)
    _git(["config", "user.name", "t"], r)
    _git(["remote", "add", "origin", str(origin)], r)
    (r / "README.md").write_text("# app\n")
    _git(["add", "-A"], r)
    _git(["commit", "-m", "init"], r)
    _git(["push", "-u", "origin", "main"], r)
    return r


def _branches_on_origin(tmp_path: Path) -> set[str]:
    out = _git(["ls-remote", "--heads", str(tmp_path / "origin.git")], tmp_path)
    return {line.split()[1] for line in out.splitlines() if line.strip()}


# ── the boxes ─────────────────────────────────────────────────────────────────────────────────────

def _docker_answers() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _container_box():
    """The container box on the image this deployment would run, asked at run time so collection
    is the same on every machine (`tests/test_the_box_transmits_while_it_runs.py`'s pattern).

    A missing daemon skips, and fails under `TEST_REQUIRE_DOCKER` (CI's integration job), where a
    lost daemon must not read as a pass. A missing IMAGE skips everywhere, naming it: CI builds
    `docker/base-python.Dockerfile` only in `release.yml`, so no CI runner has it."""
    from openfactory.adapters.sandbox.container import ContainerSandbox
    from openfactory.factory import resolve_box_image

    if not _docker_answers():
        why = "the container box needs a docker daemon, and none answers `docker info` here"
        if os.environ.get("TEST_REQUIRE_DOCKER"):
            pytest.fail(why)
        pytest.skip(why)
    image = resolve_box_image(sandbox="container")
    if subprocess.run(["docker", "image", "inspect", image],
                      capture_output=True).returncode != 0:
        pytest.skip(f"the box image {image!r} is not built on this machine — `docker build -f "
                    f"docker/base-python.Dockerfile -t {image} .` makes it; the container box's "
                    f"row is unmeasured until it exists")
    # a name of its own per test: a leftover wearing a sibling's name is removed by `prepare`
    return ContainerSandbox(image=image, project=f"planprobe-{uuid.uuid4().hex[:8]}")


@pytest.fixture(params=["worktree", "container"])
def box(request, tmp_path: Path):
    if request.param == "container":
        return _container_box()
    return WorktreeSandbox(root=tmp_path / "wt")


class _Recording:
    """A box that records every command it is handed and delegates to the real one. With
    `refuse_fingerprint`, it answers git's dubious-ownership refusal, exit 128, to the fingerprint
    from its `refuse_from`-th asking on (1: every one) and runs everything else. With
    `wall_fingerprint`, it runs the fingerprint for real and answers what the box's own wall
    answers (`timeout_result`: its exit code, its marker, then the output so far), as if the wall
    hit after git had printed both hashes."""

    def __init__(self, inner, *, refuse_fingerprint: bool = False, refuse_from: int = 1,
                 wall_fingerprint: bool = False) -> None:
        self._inner = inner
        self._refuse = refuse_fingerprint
        self._refuse_from = refuse_from
        self._wall = wall_fingerprint
        self.commands: list[str] = []
        self.fingerprints = 0
        self.refused: list[str] = []

    def run(self, *, workspace, command: str, timeout: int, **kw):
        self.commands.append(command)
        if FINGERPRINT_RUNS in command:
            self.fingerprints += 1
            if self._refuse and self.fingerprints >= self._refuse_from:
                self.refused.append(command)
                return 128, DUBIOUS
            if self._wall:
                _, out = self._inner.run(workspace=workspace, command=command, timeout=timeout,
                                         **kw)
                return timeout_result(command, timeout, out)
        return self._inner.run(workspace=workspace, command=command, timeout=timeout, **kw)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ── the agents ────────────────────────────────────────────────────────────────────────────────────

class _Planner:
    """A planner that writes through the box's own `run`, as a harness CLI does, and an executor
    that records it was called and writes `feature.py` the same way."""

    def __init__(self, writes: str = "", *, name: str = "kimi", pauses: bool = False,
                 cost: float | None = None) -> None:
        self.name = name
        self.writes = writes
        self.pauses = pauses
        self.cost = cost
        self.planned = False
        self.executed = False

    def plan(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.planned = True
        if self.writes:
            rc, out = sandbox.run(workspace=workspace, command=self.writes, timeout=60)
            assert rc == 0, f"the planner double could not write: {out}"
        if self.pauses:
            return AgentRunResult(ok=False, pause_reason="rate_limit", retry_at="16:00",
                                  summary="usage limit reached", cost_usd=self.cost)
        return AgentRunResult(ok=True, summary="read the tree; add feature.py",
                              cost_usd=self.cost)

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.executed = True
        sandbox.run(workspace=workspace, command="echo 'VALUE = 42' > feature.py", timeout=60)
        return AgentRunResult(ok=True, summary="added feature.py", cost_usd=0.01,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log, **kw) -> AgentRunResult:
        return AgentRunResult(ok=True)


def _run(repo: Path, agent, sandbox, *, setup: list[str] | None = None,
         events: InMemoryEventSink | None = None):
    ticket = Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                    acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])
    runner = JobRunner(
        tracker=FakeTracker(ticket), forge=FakeForge(), agent=agent, sandbox=sandbox,
        manifest=Manifest(validate={"test": "true"}, planner_stage=True, setup=setup or []),
        repo_path=repo, events=events or InMemoryEventSink(),
    )
    return runner, runner.run("#1")


def _assert_held_naming(runner, result, agent, events: InMemoryEventSink, tmp_path: Path,
                        paths: list[str]) -> None:
    """Criteria 1a and 1b: held, the executor never ran, nothing pushed or opened, the note and
    one journal warning name every path the planner wrote, and the note offers both remedies
    (another harness for the executor, or `planner_stage` off in the project's manifest)."""
    assert result.state is JobState.ON_HOLD, (
        f"the planner wrote {paths} and the job went on to {result.state.value}: {result.note}")
    assert agent.executed is False, "the executor ran on the tree the planner wrote to"
    assert runner.forge.opened is None, f"a pull request was opened: {runner.forge.opened}"
    assert _branches_on_origin(tmp_path) == {"refs/heads/main"}, (
        f"the planner's edit was pushed: {_branches_on_origin(tmp_path)}")
    for path in paths:
        assert path in (result.note or ""), f"the hold does not name {path}: {result.note}"
    # THE REMEDY NAMES A ROLE THAT EXISTS: the planner runs on the executor's harness, and on
    # 6db1677c (2026-10-20) the note said "Give the planner another harness", a role
    # `harness_kind(None, "planner")` refuses (ValueError: unknown role 'planner').
    note = result.note or ""
    assert "executor" in note and "planner another harness" not in note, (
        f"the hold's remedy does not name the executor, whose harness the planner runs on: {note}")
    # THE SECOND REMEDY IS OFFERED TOO (#967): turning the planner stage off in the project's
    # manifest needs no second harness. On dc0efac4 (2026-10-20) a cut that dropped it from the
    # hold left every row green.
    assert "planner_stage" in note and ".openfactory/project.yaml" in note, note
    naming =[e for e in events.events
              if e.kind == "warning" and all(p in e.message for p in paths)]
    assert len(naming) == 1, (
        f"expected one journal warning naming {paths}, got "
        f"{[(e.kind, e.message) for e in events.events if e.kind == 'warning']}")


# ── 1a and 1b: a planner that writes holds the job and names what it wrote ────────────────────────

def test_a_planner_that_creates_a_file_holds_the_job_and_names_it(repo, tmp_path, box):
    """1a/1b. On main (620bb577) this reached PR_OPEN with `planted.txt` in the pushed branch's
    commit, beside the executor's `feature.py`."""
    agent, events = _Planner("echo x > planted.txt"), InMemoryEventSink()
    runner, result = _run(repo, agent, box, events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["planted.txt"])


def test_a_planner_that_edits_a_tracked_file_holds_the_job(repo, tmp_path, box):
    """1a/1b. On main the edited `README.md` was committed into the pull request."""
    agent, events = _Planner("echo y >> README.md"), InMemoryEventSink()
    runner, result = _run(repo, agent, box, events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["README.md"])


def test_a_planner_that_writes_the_project_manifest_holds_the_job_naming_it(repo, tmp_path, box):
    """1a/1b, a dot path. `.openfactory/project.yaml` is the file a planner is likeliest to
    "fix", and the remedy itself names it. On dc0efac4 (2026-10-20) the reviewer's cut that leaves
    top-level dot paths out of the fingerprint's add (`git add -A -- . ":(exclude).*"`) left every
    row green, 46 passed and 4 skipped, because no row wrote a dot path; measured by hand, such a
    planner was held."""
    agent, events = _Planner("mkdir -p .openfactory && echo 'planner_stage: false' > "
                             ".openfactory/project.yaml"), InMemoryEventSink()
    runner, result = _run(repo, agent, box, events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, [".openfactory/project.yaml"])


def test_a_planner_that_commits_its_edit_holds_the_job(repo, tmp_path):
    """1a/1b. A planner `git commit` leaves porcelain clean and moves HEAD; on main the pull
    request opened on top of the planner's commit."""
    agent, events = _Planner("echo x > committed.txt && git add -A && "
                             "git -c user.email=p@p -c user.name=p -c commit.gpgSign=false "
                             "commit -qm planner"), InMemoryEventSink()
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"), events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["committed.txt"])


def test_a_planner_that_commits_a_file_and_deletes_it_holds_the_job_naming_it(repo, tmp_path):
    """1a/1b, HEAD alone. A planner that commits `once.txt` and then deletes it leaves the tree
    `git add -A` would commit equal to the one before the pass; only HEAD moved, and `_commit`
    would have put the file in the branch's history (and its deletion after it). The tree half of
    the fingerprint cannot see it, so this row holds the HEAD half: red under the cut that reads
    no HEAD (task 17)."""
    agent, events = _Planner("echo x > once.txt && git add -A && "
                             "git -c user.email=p@p -c user.name=p -c commit.gpgSign=false "
                             "commit -qm planner && rm once.txt"), InMemoryEventSink()
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"), events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["once.txt"])
    assert "a commit made during the pass" in (result.note or ""), result.note


def test_a_planner_that_rewrites_what_setup_left_holds_the_job(repo, tmp_path):
    """1a/1b. Setup leaves `build.log` untracked and the planner appends to it: `git status
    --porcelain` reads `?? build.log` before and after (measured on git 2.43.0, 2026-10-20), so a
    porcelain-only check passes it. On main the job went on to PR_OPEN."""
    agent, events = _Planner("echo more >> build.log"), InMemoryEventSink()
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"),
                          setup=["echo built > build.log"], events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["build.log"])


# ── 1c: the pause road, the same defect sooner ───────────────────────────────────────────────────

def test_a_planner_that_writes_and_then_pauses_pushes_nothing(repo, tmp_path):
    """1c. On main the pause won: `_paused` → `_preserve_partial` committed `planted.txt` and pushed
    it to `origin/openfactory/…` (state PAUSED), and the resume restored it for the executor. The
    write is measured before the pause is asked, so the hold wins."""
    agent = _Planner("echo x > planted.txt", pauses=True)
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"))

    assert result.state is JobState.ON_HOLD, (
        f"the planner wrote and paused, and the job is {result.state.value}: {result.note}")
    assert _branches_on_origin(tmp_path) == {"refs/heads/main"}, (
        f"the planner's edit was pushed by the pause: {_branches_on_origin(tmp_path)}")
    assert "planted.txt" in (result.note or ""), result.note


# ── 1d: a workspace that cannot be asked is not clean ────────────────────────────────────────────

def test_a_workspace_that_cannot_be_asked_holds_the_job_rather_than_reading_as_clean(
        repo, tmp_path):
    """1d, engineering lesson 2. git refuses the fingerprint with exit 128 (a client image without
    `safe.directory` for the mount). That is "could not see", never "nothing was written", so the
    job holds with a sentence of its own that names git's cause. On main nothing asked, and the job
    went on to PR_OPEN."""
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"), refuse_fingerprint=True)
    agent = _Planner()
    runner, result = _run(repo, agent, sandbox)

    assert result.state is JobState.ON_HOLD, (
        f"the workspace could not be asked and the job went on to {result.state.value}")
    assert sandbox.refused, "the fingerprint was never asked of the box"
    assert agent.planned is False, "a pass nobody could check was run (and paid for)"
    assert agent.executed is False
    note = result.note or ""
    assert "could not" in note and "workspace" in note, note
    assert "dubious ownership" in note, f"the hold does not name git's cause: {note}"
    assert "wrote" not in note, f"an unreadable workspace is not a planner that wrote: {note}"


def test_a_workspace_that_cannot_be_asked_after_the_pass_holds_the_job(repo, tmp_path):
    """1d, the second asking. git answers the fingerprint before the pass and refuses it after
    (exit 128), so the pass ran and what it did cannot be seen. That is the same "could not see",
    said for after the pass, never read as "nothing was written". Green since the check landed;
    red under the cut in `tools/mutations/788_a_kimi_planner_that_writes_holds_the_job.py` that
    deletes the after-pass branch (task 17: no row drove it until then)."""
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"), refuse_fingerprint=True,
                         refuse_from=2)
    agent = _Planner()
    runner, result = _run(repo, agent, sandbox)

    assert result.state is JobState.ON_HOLD, (
        f"the workspace could not be asked after the pass and the job went on to "
        f"{result.state.value}: {result.note}")
    assert sandbox.fingerprints == 2 and len(sandbox.refused) == 1, (
        f"expected the first asking answered and the second refused: {sandbox.refused}")
    assert agent.planned is True and agent.executed is False
    assert _branches_on_origin(tmp_path) == {"refs/heads/main"}, _branches_on_origin(tmp_path)
    note = result.note or ""
    assert "became unreadable during the planner's pass" in note, note
    assert "dubious ownership" in note, f"the hold does not name git's cause: {note}"
    assert "wrote" not in note, f"an unreadable workspace is not a planner that wrote: {note}"


def test_a_fingerprint_the_box_walled_is_not_read_even_with_both_hashes_printed(repo, tmp_path):
    """1d, the exit code decides. The box's wall answers `TIMEOUT_EXIT` and the output so far
    (`timeout_result`), and a wall that hits after git printed both hashes leaves two hashes as the
    last two lines. Only an exit 0 is a fingerprint: the job holds before the pass, naming the
    exit. Green since the check landed; red under the cut that reads the hashes whatever the exit
    (task 17), where the walled answer read as a mark and the job went on to PR_OPEN."""
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"), wall_fingerprint=True)
    agent = _Planner()
    runner, result = _run(repo, agent, sandbox)

    assert result.state is JobState.ON_HOLD, (
        f"a walled fingerprint was read and the job went on to {result.state.value}")
    assert agent.planned is False, "a pass nobody could check was run (and paid for)"
    note = result.note or ""
    assert "could not be asked before the planner ran" in note, note
    assert f"exit {TIMEOUT_EXIT}" in note, f"the hold does not name the box's exit: {note}"


class _Distrusted:
    """The real worktree box, with git told the workspace belongs to someone else: the refusal
    real git gives a mount it does not trust, rather than a canned answer to the fingerprint."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def run(self, *, workspace, command: str, timeout: int, **kw):
        return self._inner.run(workspace=workspace, timeout=timeout, **kw,
                               command=f"export GIT_TEST_ASSUME_DIFFERENT_OWNER=1; {command}")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_a_workspace_git_refuses_holds_the_job_with_gits_exit_and_its_words_once(repo, tmp_path):
    """1d, against real git. Measured 2026-10-20 through the real `ContainerSandbox` on a client
    image whose HOME cannot hold a global config (so the box's own `safe.directory` write fails):
    the fingerprint asked git three times after the first refusal, and the hold read "exit 1:" and
    then "fatal: detected dubious ownership …" three times; as a uid that cannot enter the mount
    it also carried "rm: cannot remove '.openfactory-plan-14'". git itself exits 128, once."""
    probe = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True,
                           env={**os.environ, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"})
    if probe.returncode == 0:
        pytest.skip("this machine's git has no ownership check to refuse with (git 2.35.2 added "
                    "it; GIT_TEST_ASSUME_DIFFERENT_OWNER is how a test reaches it)")
    agent = _Planner()
    runner, result = _run(repo, agent, _Distrusted(WorktreeSandbox(root=tmp_path / "wt")))

    assert result.state is JobState.ON_HOLD, result.note
    note = result.note or ""
    assert note.count("detected dubious ownership") == 1, f"git's refusal is not said once: {note}"
    assert "exit 128" in note, f"the hold does not carry git's own exit code: {note}"
    assert "openfactory-plan" not in note, f"the hold carries the fingerprint's own debris: {note}"


# ── 1e: the reverses, green on main by design ────────────────────────────────────────────────────

def test_what_setup_leaves_in_the_tree_is_not_charged_to_the_planner(repo, tmp_path, box):
    """1e, a reverse. Setup leaves `build.log` untracked and the planner writes nothing: the job
    runs on. Green on main; red under a cut that takes the "before" ahead of `_run_setup` or
    compares against an empty porcelain."""
    agent = _Planner()
    runner, result = _run(repo, agent, box, setup=["echo built > build.log"])

    assert result.state is JobState.PR_OPEN, result.note
    assert agent.executed is True


def test_a_planner_that_leaves_the_tree_as_it_found_it_runs_on(repo, tmp_path, box):
    """1e, a reverse. Green on main; red if the check holds every job."""
    agent = _Planner()
    runner, result = _run(repo, agent, box)

    assert result.state is JobState.PR_OPEN, result.note
    assert agent.executed is True
    assert runner.forge.opened is not None


# ── 1f: the real Kimi row ────────────────────────────────────────────────────────────────────────

class _KimiThatRecordsItsExecutor(KimiAdapter):
    """The real `KimiAdapter`: its `plan`, its `name`, its command and its parsing. Only `execute`
    is replaced, by a recorder, so the stub's write can only have come from the plan pass."""

    executed = False

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        self.executed = True
        sandbox.run(workspace=workspace, command="echo 'VALUE = 42' > feature.py", timeout=60)
        return AgentRunResult(ok=True, summary="added feature.py", cost_usd=0.01)


def test_the_real_kimi_row_that_writes_while_planning_holds_the_job(repo, tmp_path, monkeypatch):
    """1f. The real `KimiAdapter.plan` on the worktree box starts a `kimi` that disobeys the
    read-only instruction: a stub on `PATH` where kimi-code 0.31.1 would be, which writes
    `planted.txt` into its working directory and prints the one `role: assistant` line the adapter
    reads, under an empty `HOME`. On main the job reached PR_OPEN with `planted.txt` committed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "kimi"
    stub.write_text("#!/bin/sh\n"
                    "echo disobeyed > planted.txt\n"
                    "echo '{\"role\":\"assistant\",\"content\":\"read the tree; add feature.py\"}'\n",
                    encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)

    agent, events = _KimiThatRecordsItsExecutor(), InMemoryEventSink()
    assert agent.name == "kimi"
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"), events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["planted.txt"])


# ── 1g: the scope, pinned ────────────────────────────────────────────────────────────────────────

def test_a_harness_whose_planner_cannot_write_is_not_asked(repo, tmp_path):
    """1g, open question Q2's default: only a harness whose planner is read-only by instruction
    is measured. A double named `codex` (whose CLI enforces `-s read-only`) that writes anyway is
    not asked and runs on. Green on main; red if the scope widens or the gate stops reading it."""
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"))
    agent = _Planner("echo x > planted.txt", name="codex")
    runner, result = _run(repo, agent, sandbox)

    assert [c for c in sandbox.commands if FINGERPRINT_RUNS in c] == [], (
        "the workspace of a planner its CLI holds read-only was fingerprinted")
    assert result.state is JobState.PR_OPEN, result.note
    assert agent.executed is True


# ── 1h: the new way out is charged (#262) ────────────────────────────────────────────────────────

def test_a_planner_held_for_writing_is_charged_for_its_pass(repo, tmp_path):
    """1h. A hold is a way out, and #262 counts every pass before every way out: the planner that
    wrote and spent `SPENT` is on the result's rows and in its total. Red on main only through 1a,
    where no hold exists."""
    agent = _Planner("echo x > planted.txt", cost=SPENT)
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"))

    assert result.state is JobState.ON_HOLD, (
        f"the planner wrote and the job went on to {result.state.value}: {result.note}")
    assert [(m.role, m.cost_usd) for m in result.agent_runs] == [("planner", SPENT)]
    assert result.total_cost_usd == pytest.approx(SPENT)


# ── 1i: the hold says what it is, so the workflow does not read its paths as a cause ─────────────

def test_a_planner_hold_is_not_read_as_throttling_whatever_the_path(repo, tmp_path):
    """1i. The hold names the planner's paths, and the workflow classifies a hold's prose when the
    hold declares no cause (`workflow.py`, `classify(note, cause=hold_cause)`). On e2b57dd1
    (2026-10-20, the branch review) a planner that wrote `src/rate_limit.py` was read as
    `('transient', 'throttled')` by `classify`'s rate-limit rule, so the workflow would re-run the
    paid planner at 900 s, 2700 s and 5400 s and tell the person it passes on its own: the
    2026-09-19 failure `classify`'s docstring records, which `hold_cause` exists to prevent."""
    from openfactory.techlead.classify import classify
    agent = _Planner("mkdir -p src && echo x > src/rate_limit.py")
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"))
    assert result.state is JobState.ON_HOLD
    verdict = classify(result.note or "", state=result.state.value, cause=result.hold_cause)
    assert verdict.cause != "transient", (verdict.cause, verdict.detail)


@pytest.mark.parametrize("refuse_from", [1], ids=["before-the-pass"])
def test_a_workspace_that_cannot_be_asked_is_held_as_the_environment(repo, tmp_path,
                                                                     refuse_from):
    """1i, the hold a workspace git refuses before the pass makes. Its remedy is to make git
    usable in the box, which no attempt does, so the hold declares `environment` rather than
    leaving its prose, git's words and all, to `classify`. On e2b57dd1 it declared nothing. The
    hold after the pass is the planner's doing (#981), held below."""
    from openfactory.techlead.classify import ENVIRONMENT, classify
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"), refuse_fingerprint=True,
                         refuse_from=refuse_from)
    runner, result = _run(repo, _Planner(), sandbox)
    assert result.state is JobState.ON_HOLD, result.note
    note = result.note or ""
    assert "could not be asked" in note, note
    assert "Make git usable on this workspace in the box" in note, note
    verdict = classify(note, state=result.state.value, cause=result.hold_cause)
    assert (result.hold_cause, verdict.cause) == (ENVIRONMENT, ENVIRONMENT), (
        result.hold_cause, verdict.cause, verdict.detail)


# ── #981: a workspace readable before the pass and not after it is the planner's doing ───────────

def _assert_held_as_the_planners_doing(result, tmp_path: Path) -> str:
    """#981. The before-mark was read, so git was usable in the box when the planner started; what
    made the after-mark unreadable happened during the pass. The hold says so, names the planner as
    the likely cause, keeps git's exit and words, and declares the cause the planner-wrote hold
    declares (`unknown`), not `environment` with "Make git usable in the box"."""
    from openfactory.techlead.classify import UNKNOWN, classify
    assert result.state is JobState.ON_HOLD, (
        f"the workspace became unreadable during the pass and the job went on to "
        f"{result.state.value}: {result.note}")
    assert _branches_on_origin(tmp_path) == {"refs/heads/main"}, _branches_on_origin(tmp_path)
    note = result.note or ""
    assert "became unreadable during the planner's pass" in note, note
    assert "the planner is the likely cause" in note, note
    assert "exit 128" in note, f"the hold does not keep git's exit: {note}"
    assert "Make git usable" not in note, f"the hold blames the box for the planner: {note}"
    assert "wrote" not in note, f"an unreadable workspace is not a planner that wrote: {note}"
    verdict = classify(note, state=result.state.value, cause=result.hold_cause)
    assert (result.hold_cause, verdict.cause) == (UNKNOWN, UNKNOWN), (
        result.hold_cause, verdict.cause, verdict.detail)
    return note


def test_a_planner_that_runs_git_init_in_the_workspace_is_held_as_its_doing(repo, tmp_path):
    """#981, on the real fingerprint. A planner that runs `git init sub` leaves an embedded
    repository with no commit, and the fingerprint's `git add -A` refuses it (exit 128, measured
    on git 2.43.0: "'sub/' does not have a commit checked out"). On main the job was held as the
    environment, telling the person to "Make git usable in the box"."""
    agent = _Planner("git init -q sub")
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"))
    assert agent.planned is True and agent.executed is False
    note = _assert_held_as_the_planners_doing(result, tmp_path)
    assert "does not have a commit checked out" in note, f"git's own words are lost: {note}"


def test_a_workspace_unreadable_only_after_the_pass_is_held_as_the_planners_doing(repo, tmp_path):
    """#981, the second asking refused (exit 128) after the first was answered: the after-pass
    hold declares `unknown`, keeps git's words, and does not say "Make git usable"."""
    sandbox = _Recording(WorktreeSandbox(root=tmp_path / "wt"), refuse_fingerprint=True,
                         refuse_from=2)
    runner, result = _run(repo, _Planner(), sandbox)
    note = _assert_held_as_the_planners_doing(result, tmp_path)
    assert "dubious ownership" in note, f"git's own words are lost: {note}"


# ── 1j: the fingerprint's own promises (review round 1 on e2b57dd1, not blocking) ────────────────
# Each row passes on 3e54a1cf by design and turns red under its cut in plan
# 788_a_kimi_planner_that_writes_holds_the_job: on e2b57dd1 the reviewer measured five cuts of
# `read_only_pass.py` that left all 19 rows green.

def test_the_fingerprint_leaves_the_real_index_and_no_copy_behind(repo, tmp_path):
    """The module's headline promise: the fingerprint's `git add -A` writes a copy of the index,
    removed in the same shell. Setup leaves `build.log` untracked, and the planner, run after the
    first fingerprint, still reads `?? build.log` (not `A  build.log`) and no copy in the git dir.
    A staged leftover would vanish from the executor's `git diff`."""
    agent, seen = _Planner(), {}
    inner = agent.plan

    def plan(*, sandbox, workspace, context):
        seen["status"] = sandbox.run(workspace=workspace, timeout=60,
                                     command="git status --porcelain")[1]
        seen["copies"] = sandbox.run(workspace=workspace, timeout=60,
                                     command='ls "$(git rev-parse --git-dir)"')[1]
        return inner(sandbox=sandbox, workspace=workspace, context=context)

    agent.plan = plan
    _, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"),
                     setup=["echo built > build.log"])
    assert result.state is JobState.PR_OPEN, result.note
    assert seen["status"].strip() == "?? build.log", seen["status"]
    assert "openfactory-plan" not in seen["copies"], seen["copies"]


def test_a_tree_that_changed_holds_even_when_git_names_no_path(repo, tmp_path):
    """Positive evidence is never lost: two trees that differ hold the job even when `git diff`
    names no path (here it answers exit 128), and git's words stand in for the paths."""
    class NoNames(_Recording):
        def run(self, *, workspace, command, timeout, **kw):
            if "diff --no-renames --name-only" in command:
                return 128, "fatal: bad object"
            return super().run(workspace=workspace, command=command, timeout=timeout, **kw)

    _, result = _run(repo, _Planner("echo x > planted.txt"),
                     NoNames(WorktreeSandbox(root=tmp_path / "wt")))
    assert result.state is JobState.ON_HOLD, result.note
    assert "git named no path" in (result.note or ""), result.note


def test_a_planner_that_writes_many_files_is_named_up_to_the_bound(repo, tmp_path):
    """A note a person reads names at most `SHOWN` (20) paths, then "and N more": 25 files give
    20 names and "and 5 more"."""
    _, result = _run(repo, _Planner("for i in $(seq 1 25); do echo x > f$i.txt; done"),
                     WorktreeSandbox(root=tmp_path / "wt"))
    assert result.state is JobState.ON_HOLD, result.note
    assert "and 5 more" in (result.note or ""), result.note


def test_a_planner_that_renames_a_file_holds_the_job_naming_both_paths(repo, tmp_path):
    """A rename names the path that left and the path that came: `diff.renames` is on by default
    since git 2.9, and without `--no-renames` `git diff --name-only` names only `DOCS.md`."""
    agent, events = _Planner("git mv README.md DOCS.md"), InMemoryEventSink()
    runner, result = _run(repo, agent, WorktreeSandbox(root=tmp_path / "wt"), events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["README.md", "DOCS.md"])


# ── 1k: what is measured is what is pushed (review round 2 on dc0efac4, point 2) ─────────────────
# `publish_branch` pushes the job's branch BY NAME (`worktree.py`, `container.py`: `git push
# --force <remote> <workspace.branch>`), and the mark read HEAD's commit and the tree only. On
# dc0efac4 (2026-10-20) the reviewer's double left both as they were and moved the job's branch:
# the job was not held, and the pushed branch was the planner's commit, not the executor's.

#: The reviewer's double: a commit carrying `planted.txt` is written without touching the index or
#: the working tree, HEAD is detached where it stood, and the job's branch is moved to the commit.
#: HEAD's commit and the tree `git add -A` would commit read the same before and after.
MOVES_THE_JOB_BRANCH = (
    'b="$(git symbolic-ref HEAD)" && '
    'blob="$(echo planted | git hash-object -w --stdin)" && '
    'tree="$( (git ls-tree HEAD; printf "100644 blob %s\\tplanted.txt\\n" "$blob") | git mktree)" && '
    'c="$(git -c user.name=p -c user.email=p@p commit-tree "$tree" -p HEAD -m planner)" && '
    'git checkout -q --detach && git update-ref "$b" "$c"'
)


def test_a_planner_that_moves_the_job_branch_holds_the_job_naming_it(repo, tmp_path, box):
    """1k, the job's branch. The planner leaves HEAD's commit and the tree as they were and moves
    the job's branch to a commit of its own carrying `planted.txt`. On 808b3825 the job was not
    held: the executor committed on the detached HEAD, and `publish_branch` pushed the job's branch,
    the planner's commit, to the forge. Held now, naming the branch and the path its commit
    carries, with nothing pushed."""
    agent, events = _Planner(MOVES_THE_JOB_BRANCH), InMemoryEventSink()
    runner, result = _run(repo, agent, box, events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["planted.txt"])
    assert "the job's branch" in (result.note or ""), (
        f"the hold does not say the job's branch moved: {result.note}")


def test_a_planner_that_puts_head_on_another_branch_holds_the_job_naming_it(repo, tmp_path, box):
    """1k, the branch HEAD is on. The planner checks out a branch of its own where HEAD stood:
    HEAD's commit, the tree and the job's branch are all as they were, and the executor's commit
    would land on `elsewhere` while `publish_branch` pushes the job's branch without it. On
    808b3825 nothing saw it. Held now, naming the branch HEAD was moved to."""
    agent, events = _Planner("git checkout -q -b elsewhere"), InMemoryEventSink()
    runner, result = _run(repo, agent, box, events=events)
    _assert_held_naming(runner, result, agent, events, tmp_path, ["refs/heads/elsewhere"])

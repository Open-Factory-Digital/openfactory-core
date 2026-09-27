"""A card that names its base starts from that base, or does not start at all (#354).

A ticket's front matter may carry `base_branch`, and the orchestrator hands it to the box as the
base of both the workspace and the pull request. Stacked work is the case it exists for: a ticket
whose predecessor is still in review starts from the predecessor's head. The clone a job runs in
is synced to the manifest's base alone, so a branch the card named was never in it. These tests
hold what a regression would cost:

  1. both boxes start a fresh job from the base the card named, read from the forge when the
     clone does not hold it;
  2. a base the forge does not have either is refused BY NAME, before an agent spends anything,
     and never replaced by another base;
  3. a project with no forge (its repository is the remote) refuses a base it does not hold;
  4. what the job is judged on — its diff — is measured from the base it started from, on the
     container box too, fresh or reopened (review of #355);
  5. a stale local copy of the card's base in the worker's cache is never where the job starts:
     with a forge, the forge is read first (review of #355).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import openfactory.adapters.sandbox.container as container
import openfactory.adapters.sandbox.worktree as worktree
from openfactory.adapters.sandbox.container import ContainerSandbox, _materialize_workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True)
    return done.stdout.strip()


@pytest.fixture
def forge(tmp_path: Path):
    """A forge holding `main` and a stacked branch one commit ahead of it, and the worker's cache:
    a clone that holds `main` only, the way the cache sync leaves it."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _git(seed, "config", "user.email", "t@example.invalid")
    _git(seed, "config", "user.name", "t")
    (seed / "app.py").write_text("A = 1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "base")
    _git(seed, "checkout", "-q", "-b", "box-takes-input")
    (seed / "stage.py").write_text("def stage_input(): ...\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "the predecessor, still in review")
    stacked = _git(seed, "rev-parse", "HEAD")
    bare = tmp_path / "forge.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
    cache = tmp_path / "cache"
    subprocess.run(["git", "clone", "-q", "--single-branch", "--branch", "main", str(bare),
                    str(cache)], check=True)
    with pytest.raises(subprocess.CalledProcessError):  # the cache never held the stacked branch
        _git(cache, "rev-parse", "--verify", "box-takes-input")
    return bare, cache, stacked


def _descends_from(path: Path, commit: str) -> bool:
    return subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", commit, "HEAD"],
                          capture_output=True).returncode == 0


# ── 1. the base the card named ──────────────────────────────────────────────────────────────────

def test_the_worktree_box_starts_from_the_card_s_base_read_from_the_forge(forge, tmp_path):
    bare, cache, stacked = forge
    ws = WorktreeSandbox(root=tmp_path / "wt").prepare(
        repo_path=cache, base_branch="box-takes-input", branch="openfactory/7",
        remote_url=str(bare))
    assert _descends_from(Path(ws.path), stacked), "the job did not start from the card's base"
    assert (Path(ws.path) / "stage.py").is_file()


def test_the_container_box_starts_from_the_card_s_base_read_from_the_forge(forge, tmp_path):
    bare, cache, stacked = forge
    clone = tmp_path / "box"
    _materialize_workspace(repo_path=cache, host_clone=clone, base_branch="box-takes-input",
                           branch="openfactory/7", checkout_existing=False, remote_url=str(bare))
    assert _descends_from(clone, stacked), "the job did not start from the card's base"
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "openfactory/7"


def test_the_manifest_s_base_still_starts_as_it_did(forge, tmp_path):
    bare, cache, _ = forge
    clone = tmp_path / "box"
    _materialize_workspace(repo_path=cache, host_clone=clone, base_branch="main",
                           branch="openfactory/8", checkout_existing=False, remote_url=str(bare))
    assert _git(clone, "rev-parse", "HEAD") == _git(cache, "rev-parse", "main")
    ws = WorktreeSandbox(root=tmp_path / "wt").prepare(
        repo_path=cache, base_branch="main", branch="openfactory/9", remote_url=str(bare))
    assert not (Path(ws.path) / "stage.py").exists()


# ── 2. a base nobody has is refused by name ────────────────────────────────────────────────────

@pytest.mark.parametrize("box", ["worktree", "container"])
def test_a_base_the_forge_does_not_have_is_refused_by_name(forge, tmp_path, box):
    bare, cache, _ = forge
    with pytest.raises(RuntimeError) as refused:
        if box == "worktree":
            WorktreeSandbox(root=tmp_path / "wt").prepare(
                repo_path=cache, base_branch="no-such-branch", branch="openfactory/7",
                remote_url=str(bare))
        else:
            _materialize_workspace(repo_path=cache, host_clone=tmp_path / "box",
                                   base_branch="no-such-branch", branch="openfactory/7",
                                   checkout_existing=False, remote_url=str(bare))
    said = str(refused.value)
    assert "no-such-branch" in said and "no branch" in said, said


# ── 3. a project with no forge ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("box", ["worktree", "container"])
def test_a_local_project_refuses_a_base_it_does_not_hold(forge, tmp_path, box):
    """The repository IS the remote: there is nowhere else to read the base from, and starting
    from the repository's own HEAD instead would be the substitution this refuses."""
    _bare, cache, _ = forge
    with pytest.raises(RuntimeError) as refused:
        if box == "worktree":
            WorktreeSandbox(root=tmp_path / "wt").prepare(
                repo_path=cache, base_branch="no-such-branch", branch="openfactory/7",
                remote_url=str(cache))
        else:
            _materialize_workspace(repo_path=cache, host_clone=tmp_path / "box",
                                   base_branch="no-such-branch", branch="openfactory/7",
                                   checkout_existing=False, remote_url=str(cache))
    assert "no-such-branch" in str(refused.value) and "no branch" in str(refused.value)


# ── 4. the diff is measured from the base the job started from ─────────────────────────────────

def _commit(path: Path, name: str, text: str, message: str) -> None:
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / name).write_text(text)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)


def _a_box_without_docker(monkeypatch, tmp_path) -> ContainerSandbox:
    """The container box with its daemon taken out: git runs for real on the host clone, `docker`
    answers as a daemon that holds no leftover, and a command meant for the box runs in the clone
    it bind-mounts — which is the checkout the box's `git` sees."""
    real = container._host

    def host(cmd, timeout=120):
        if cmd[0] != "docker":
            return real(cmd, timeout)
        return (1, "") if cmd[1] == "inspect" else (0, "")

    monkeypatch.setattr(container, "_host", host)
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path / "work"))
    box = ContainerSandbox(image="the-image")

    def run(*, workspace, command, timeout, **_):
        done = subprocess.run(["sh", "-c", command], cwd=workspace.host_path, capture_output=True,
                              text=True, timeout=timeout)
        return done.returncode, done.stdout + done.stderr

    monkeypatch.setattr(box, "run", run)
    return box


def test_the_container_box_measures_a_stacked_job_from_the_base_it_read(forge, tmp_path,
                                                                        monkeypatch):
    """`FETCH_HEAD` is kept by no ref, so the card's base has no name in the box's clone: the diff
    has to be spelled from the commit, or every stacked job is judged on no diff at all."""
    bare, cache, stacked = forge
    box = _a_box_without_docker(monkeypatch, tmp_path)
    ws = box.prepare(repo_path=cache, base_branch="box-takes-input", branch="openfactory/7",
                     remote_url=str(bare))
    assert ws.base_commit == stacked, "the box did not say which commit the job started from"
    _commit(Path(ws.host_path), "new.py", "N = 1\n", "the job's own change")
    assert box.diff_paths(workspace=ws) == ["new.py"]


def test_a_reopened_stacked_pull_request_is_measured_from_where_it_left_its_base(forge, tmp_path):
    """A repair or a review pass fetches the open pull request's branch back; its change is what
    separates it from the base it was cut from, which this clone does not hold by name either."""
    bare, cache, stacked = forge
    seed = tmp_path / "pr"
    subprocess.run(["git", "clone", "-q", "--branch", "box-takes-input", str(bare), str(seed)],
                   check=True)
    _git(seed, "checkout", "-q", "-b", "openfactory/7")
    _commit(seed, "new.py", "N = 1\n", "the pull request's change")
    _git(seed, "push", "-q", "origin", "openfactory/7")
    clone = tmp_path / "box"
    base_commit = _materialize_workspace(
        repo_path=cache, host_clone=clone, base_branch="box-takes-input", branch="openfactory/7",
        checkout_existing=True, remote_url=str(bare))
    assert base_commit == stacked, "the reopened pull request was not measured from its base"
    assert _git(clone, "diff", "--name-only", f"{base_commit}..HEAD") == "new.py"


# ── 5. a stale local copy of the card's base ───────────────────────────────────────────────────

@pytest.fixture
def stale_cache(tmp_path: Path):
    """A cache holding a LOCAL `develop` from before the forge's `develop` moved on — what a cache
    keeps of any branch other than the manifest's base, which is the only one it refreshes."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    _commit(seed, "app.py", "A = 1\n", "base")
    _git(seed, "checkout", "-q", "-b", "develop")
    _commit(seed, "d.py", "V = 1\n", "develop, v1")
    bare = tmp_path / "forge.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
    cache = tmp_path / "cache"
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(bare), str(cache)], check=True)
    _git(cache, "branch", "develop", "origin/develop")
    stale = _git(cache, "rev-parse", "develop")
    _git(seed, "remote", "add", "forge", str(bare))
    _commit(seed, "d.py", "V = 2\n", "develop, v2")
    _git(seed, "push", "-q", "forge", "develop")
    fresh = _git(bare, "rev-parse", "develop")
    assert fresh != stale
    return bare, cache, fresh


@pytest.mark.parametrize("box", ["worktree", "container"])
def test_a_stale_local_copy_of_the_card_s_base_is_not_where_the_job_starts(stale_cache, tmp_path,
                                                                          box):
    bare, cache, fresh = stale_cache
    if box == "worktree":
        path = Path(WorktreeSandbox(root=tmp_path / "wt").prepare(
            repo_path=cache, base_branch="develop", branch="openfactory/7",
            remote_url=str(bare)).path)
    else:
        path = tmp_path / "box"
        _materialize_workspace(repo_path=cache, host_clone=path, base_branch="develop",
                               branch="openfactory/7", checkout_existing=False,
                               remote_url=str(bare))
    assert _git(path, "rev-parse", "HEAD") == fresh, "the job started from the cache's stale copy"
    assert (path / "d.py").read_text() == "V = 2\n"


# ── the step that failed is the one named ──────────────────────────────────────────────────────

def test_a_reset_that_fails_is_not_said_as_a_failed_read_of_the_forge(forge, tmp_path,
                                                                     monkeypatch):
    bare, cache, _ = forge
    real = worktree._run

    def run(args, *a, **kw):
        if "reset" in args:
            return 1, "fatal: Unable to create '.git/index.lock': File exists."
        return real(args, *a, **kw)

    monkeypatch.setattr(worktree, "_run", run)
    with pytest.raises(RuntimeError) as refused:
        WorktreeSandbox(root=tmp_path / "wt").prepare(
            repo_path=cache, base_branch="box-takes-input", branch="openfactory/7",
            remote_url=str(bare))
    said = str(refused.value)
    assert "could not reset" in said and "could not read" not in said, said

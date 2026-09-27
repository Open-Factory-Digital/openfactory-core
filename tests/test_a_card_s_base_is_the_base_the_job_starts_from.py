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
  3. a project with no forge (its repository is the remote) refuses a base it does not hold.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.sandbox.container import _materialize_workspace
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

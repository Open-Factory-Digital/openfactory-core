"""A CI repair or human adjust starts from the ALREADY-PUSHED PR branch — and the sandbox must be
given the credential to fetch it (found live: fx-mono#1's adjust, 2026-08-04).

`prepare()` was the one git-fetching method on the sandbox port that took no `remote_url`, while
its siblings `publish_branch` and `rebase_onto_base` both did. So it could only ever reach
`origin` — and `origin` here is the worker's REPO CACHE, which (a) holds only the base branch its
syncs check out, and (b) deliberately carries no credential, because agents read that checkout and
a ticket can ask one to print `.git/config`.

On a private repository the fetch therefore failed for want of a password, and the two adapters
misreported it in different directions:

    container   raised "couldn't find remote ref sdlc/1" — blaming a branch that was right there
    worktree    silently started from BASE, and publish_branch then force-pushed that over the
                open PR, destroying the very work the repair was sent to fix

Proven against REAL git repositories (no docker, no network): remote → cache → box clone.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.adapters.sandbox.container import _materialize_workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout


@pytest.fixture
def topology(tmp_path):
    """remote (bare: main + sdlc/7) → cache (clone of main only — the RepoCache shape).

    The cache is what `repo_path` points at, and it never holds the PR branch: `RepoCache._reset`
    fetches exactly `+refs/heads/<base>:refs/remotes/origin/<base>`."""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], capture_output=True, check=True)
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / "a.py").write_text("x = 1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "main")
    # the PR branch exists ONLY on the remote — exactly the adjust-time shape
    _git(seed, "checkout", "-b", "sdlc/7")
    (seed / "a.py").write_text("x = 2\n")
    _git(seed, "commit", "-am", "the PR change")
    _git(seed, "push", "origin", "sdlc/7")

    cache = tmp_path / "cache"
    subprocess.run(["git", "clone", "--branch", "main", "--single-branch", str(remote), str(cache)],
                   capture_output=True, check=True)
    assert "sdlc/7" not in _git(cache, "branch", "-a"), "the cache must NOT hold the PR branch"
    return remote, cache, tmp_path


# ── the container box ───────────────────────────────────────────────────────────────────────────

def test_the_boxs_clone_reaches_a_pr_branch_the_cache_never_held(topology):
    """THE fx-mono#1 failure, fixed: given the forge's URL, the workspace starts from the PR's
    own tip even though nothing between here and the forge has ever seen that branch."""
    remote, cache, tmp = topology
    clone = tmp / "box-clone"

    _materialize_workspace(repo_path=cache, host_clone=clone, base_branch="main",
                           branch="sdlc/7", checkout_existing=True, remote_url=str(remote))

    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "sdlc/7"
    assert (clone / "a.py").read_text() == "x = 2\n", (
        "the workspace is on the branch NAME but not its CONTENT — the repair would run against "
        "code that does not contain the change it is repairing")


def test_without_the_credential_it_refuses_rather_than_running_on_base(topology):
    """Why the parameter has to be threaded at all: `origin` is the cache, and the cache cannot
    serve this branch. Refusing is correct — starting from base and force-pushing is not."""
    remote, cache, tmp = topology

    with pytest.raises(RuntimeError, match="fetching the existing branch"):
        _materialize_workspace(repo_path=cache, host_clone=tmp / "box-clone-nocred",
                               base_branch="main", branch="sdlc/7", checkout_existing=True)


def test_the_token_never_reaches_the_boxs_git_config(topology):
    """This clone is bind-mounted into the box, where untrusted code runs. The URL goes as an
    ARGUMENT — the same discipline RepoCache and publish_branch already follow — so git never
    persists it. A token in `.git/config` here is a token an agent can read and repeat."""
    remote, cache, tmp = topology
    clone = tmp / "box-clone-secret"
    credentialed = f"file://{remote}"  # stands in for https://x-access-token:TOKEN@github.com/...

    _materialize_workspace(repo_path=cache, host_clone=clone, base_branch="main",
                           branch="sdlc/7", checkout_existing=True, remote_url=credentialed)

    config = (clone / ".git" / "config").read_text()
    assert credentialed not in config, "the fetch URL was persisted into the box's own git config"


def test_a_fresh_branch_off_base_still_works(topology):
    remote, cache, tmp = topology
    clone = tmp / "box-clone-fresh"

    _materialize_workspace(repo_path=cache, host_clone=clone, base_branch="main",
                           branch="sdlc/9", checkout_existing=False)

    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "sdlc/9"
    assert (clone / "a.py").read_text() == "x = 1\n"


def test_a_branch_that_exists_NOWHERE_still_fails_loudly(topology):
    remote, cache, tmp = topology

    with pytest.raises(RuntimeError, match="fetching the existing branch"):
        _materialize_workspace(repo_path=cache, host_clone=tmp / "box-clone-none",
                               base_branch="main", branch="sdlc/404", checkout_existing=True,
                               remote_url=str(remote))


# ── the worktree box: the silent fallback that force-pushed over the PR ─────────────────────────

def test_a_resume_that_could_not_ASK_refuses_instead_of_starting_from_base(topology):
    """THE DATA-LOSS SHAPE. The fallback to base exists for a branch a human deleted — but it
    used to accept a fetch that merely FAILED as proof of absence. On a private repo that meant:
    start from base, let the agent work, then `publish_branch --force` over the open PR."""
    remote, cache, tmp = topology
    sandbox = WorktreeSandbox(root=tmp / "wt")
    _git(cache, "remote", "set-url", "origin", str(tmp / "no-such-remote.git"))

    with pytest.raises(RuntimeError, match="could not ask the remote"):
        sandbox.prepare(repo_path=cache, base_branch="main", branch="sdlc/7",
                        checkout_existing=True)


def test_a_branch_the_remote_says_is_GONE_still_degrades_to_a_fresh_start(topology):
    """The case the fallback was written for, preserved: the remote ANSWERED and has no such
    branch, so a resume starts fresh rather than bricking into a crash-park."""
    remote, cache, tmp = topology
    sandbox = WorktreeSandbox(root=tmp / "wt-gone")

    ws = sandbox.prepare(repo_path=cache, base_branch="main", branch="sdlc/404",
                         checkout_existing=True, remote_url=str(remote))

    assert (ws.path / "a.py").read_text() == "x = 1\n", "it should have started from base"


def test_the_worktree_resume_reaches_the_pr_branch_with_the_credential(topology):
    remote, cache, tmp = topology
    sandbox = WorktreeSandbox(root=tmp / "wt-ok")

    ws = sandbox.prepare(repo_path=cache, base_branch="main", branch="sdlc/7",
                         checkout_existing=True, remote_url=str(remote))

    assert (ws.path / "a.py").read_text() == "x = 2\n"


def test_only_a_missing_REF_counts_as_gone():
    """The discriminator, in isolation: everything that is not the remote saying "no such ref"
    means we could not ask, and could-not-ask is never it-is-not-there."""
    from openfactory.adapters.sandbox.worktree import _remote_has_no_such_branch

    assert _remote_has_no_such_branch("fatal: couldn't find remote ref sdlc/1")
    assert not _remote_has_no_such_branch(
        "fatal: could not read Username for 'https://github.com': No such device or address")
    assert not _remote_has_no_such_branch("fatal: Authentication failed for 'https://github.com/'")
    assert not _remote_has_no_such_branch("fatal: unable to access ...: Could not resolve host")
    assert not _remote_has_no_such_branch("")

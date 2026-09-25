"""A proposal whose base moved still lands on the local forge — rebased first, then fast-forwarded (#142).

WHAT WAS MEASURED, on a one-machine deployment at `da669de`: the baseline pull request waited for
a person's review, the knowledge pipeline's `chore(okf): refresh module map` landed on the context
repository's `main` by itself, and from then on the panel's Merge answered `! [rejected]
product/baseline -> main (non-fast-forward)` for ever. The two sides had changed disjoint files. The
only obstacle was that the context repository is BARE — git refuses a rebase with `this operation
must be run in a work tree` — and this row merges by fast-forward and nothing else.

So `merge_pr` rebases a proposal that fell behind in a scratch tree outside the repository, moves
the branch only if it is still where the rebase started, and then fast-forwards as it always did.
Every test here drives the real `LocalForge` against the bare repository `create_repository`
really makes, with real git: the claims are about which refs moved and which commits exist, and a
fake git cannot answer either.

NO AMBIENT IDENTITY. `HOME` is the test's own and every `GIT_*` identity variable is removed, so a
rebase that did not carry the bot's identity is refused here exactly as it is in a clean container
(measured: `Please tell me who you are`, exit 128).
"""

from __future__ import annotations

import subprocess
import tempfile

import pytest

from openfactory.adapters.forge.local import LocalForge

CONTEXT = "myapp-context"
BOT = "The Factory"


def _git(where, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True,
                          check=False)


def _ok(where, *args) -> None:
    """A setup step that must have happened — a test built on a push that silently failed proves
    nothing about the code it then calls."""
    done = _git(where, *args)
    assert done.returncode == 0, f"setup: git {' '.join(args)} — {done.stderr}"


def _sha(where, ref) -> str:
    return _git(where, "rev-parse", "--verify", "--quiet", ref).stdout.strip()


def _identity(where) -> None:
    _ok(where, "config", "user.email", "person@example.invalid")
    _ok(where, "config", "user.name", "A Person")


def _row(number: int) -> dict:
    from openfactory.adapters.board_db import connect

    with connect() as conn:
        return dict(conn.execute("SELECT * FROM pull_requests WHERE number = ?",
                                 (number,)).fetchone())


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """Where temporary directories go, and nothing else does — so a test can ask whether the
    rebase left one behind. Every identity git could fall back on is taken away."""
    monkeypatch.setenv("HOME", str(tmp_path))      # the context repository is made under it
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_BOT_NAME", BOT)
    monkeypatch.setenv("OPENFACTORY_BOT_EMAIL", "factory@example.invalid")
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                 "GIT_COMMITTER_EMAIL", "GIT_CONFIG_GLOBAL", "XDG_CONFIG_HOME", "EMAIL"):
        monkeypatch.delenv(name, raising=False)
    where = tmp_path / "tmp"
    where.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(where))
    return where


@pytest.fixture
def repo(tmp_path, scratch):
    """The person's repository: `main` with one commit, and the factory's job branch."""
    where = tmp_path / "myapp"
    where.mkdir()
    _ok(where, "init", "-q", "-b", "main")
    _identity(where)
    (where / "app.py").write_text("print('one')\n")
    _ok(where, "add", "-A")
    _ok(where, "commit", "-qm", "first")
    _ok(where, "checkout", "-q", "-b", "openfactory/1")
    (where / "app.py").write_text("print('two')\n")
    _ok(where, "commit", "-qam", "the factory's change")
    _ok(where, "checkout", "-q", "main")
    return where


@pytest.fixture
def forge(repo):
    return LocalForge("myapp", str(repo), base="main")


@pytest.fixture
def authoring(tmp_path):
    return tmp_path / "authoring"


@pytest.fixture
def context(forge, authoring):
    """The context repository as this row makes it — BARE, the installation's own — with a seeded
    `main`, and a clone to push proposals from the way the product role pushes them."""
    forge.create_repository(name=CONTEXT)
    bare = forge.clone_url(CONTEXT)
    subprocess.run(["git", "clone", "-q", bare, str(authoring)], capture_output=True, check=True)
    _identity(authoring)
    _ok(authoring, "symbolic-ref", "HEAD", "refs/heads/main")
    (authoring / "product.md").write_text("# myapp\n")
    _ok(authoring, "add", "-A")
    _ok(authoring, "commit", "-qm", "seed")
    _ok(authoring, "push", "-q", "origin", "main")
    return bare


def _commit(authoring, branch: str, files: dict[str, str], message: str) -> None:
    """`files` committed on `branch`, cut from the context repository's `main` as it is now."""
    _ok(authoring, "fetch", "-q", "origin")
    _ok(authoring, "checkout", "-q", "-B", branch, "origin/main")
    for name, text in files.items():
        (authoring / name).parent.mkdir(parents=True, exist_ok=True)
        (authoring / name).write_text(text)
    _ok(authoring, "add", "-A")
    _ok(authoring, "commit", "-qm", message)
    _ok(authoring, "push", "-q", "origin", branch)


def _propose(forge, authoring, branch: str, files: dict[str, str]) -> str:
    _commit(authoring, branch, files, f"propose {branch}")
    return forge.open_pr(head=branch, base="main", title=branch, body="why", repo=CONTEXT)


def _nothing_left_behind(context, scratch) -> None:
    """The scratch tree is gone from the disk AND from the repository's own list of worktrees —
    one without the other is a directory nobody deletes or a registration that blocks the next."""
    listed = _git(context, "worktree", "list", "--porcelain").stdout
    assert listed.count("worktree ") == 1, f"a scratch tree is still registered:\n{listed}"
    assert list(scratch.iterdir()) == [], f"left in the temp directory: {list(scratch.iterdir())}"


# ── the case that was stuck ─────────────────────────────────────────────────────────────────────

def test_the_BASELINE_the_module_map_refreshed_under_LANDS_when_merged(forge, context, authoring,
                                                                         scratch):
    """The reproduction, as the deployment had it: the baseline is proposed, the module map
    refreshes `main` by itself, and the person presses Merge. Before the fix this raised `!
    [rejected] … (non-fast-forward)` and nothing could ever change that."""
    pr = _propose(forge, authoring, "product/baseline",
                  {"baseline/inventory.md": "# what the code does\n",
                   "requirements/README.md": "# requirements\n"})
    opened = _row(1)["patch_id"]
    _commit(authoring, "main", {".okf/repos/myapp/modules.yaml": "modules: []\n"},
            "chore(okf): refresh module map")
    refreshed = _sha(context, "main")
    assert forge.mergeable_state(pr=pr) == "behind", "the setup must be the stuck baseline"

    forge.merge_pr(pr=pr)

    landed = _sha(context, "main")
    for path in ("baseline/inventory.md", "requirements/README.md",
                 ".okf/repos/myapp/modules.yaml"):
        assert _git(context, "cat-file", "-e", f"main:{path}").returncode == 0, f"{path} is missing"
    assert _sha(context, "main^") == refreshed, (
        "the base is not the refresh plus the proposal's one commit, in a line")
    assert _git(context, "rev-list", "--merges", "main").stdout == "", "a merge commit was made"
    assert forge.pr_status(pr=pr) == "merged" and forge.merge_commit_sha(pr=pr) == landed
    assert _row(1)["refused"] == ""
    assert _row(1)["patch_id"] == opened, "the change's identity did not survive the rebase"
    assert _git(context, "log", "-1", "--format=%an|%cn", "main").stdout.strip() == (
        f"A Person|{BOT}"), "the author must be kept and the rebase committed as the bot"
    _nothing_left_behind(context, scratch)


def test_the_sweep_lands_TWO_requirements_cut_from_the_same_main_in_ONE_pass(forge, context,
                                                                               authoring):
    """The sweep merges its branches in order, so the first to land moves `main` under the second.
    Before the fix the second was refused on that pass and on every pass after it."""
    from openfactory.product.authoring import land_open_proposals

    # under `requirements/`, as `propose_requirement` writes them: the sweep lands only those
    _commit(authoring, "req/0001-login", {"requirements/REQ-0001.md": "# log in\n"}, "propose 1")
    _commit(authoring, "req/0002-logout", {"requirements/REQ-0002.md": "# log out\n"},
            "propose 2")

    assert land_open_proposals(docs_repo=CONTEXT, forge=forge, base="main") == [
        "req/0001-login", "req/0002-logout"]
    for name in ("requirements/REQ-0001.md", "requirements/REQ-0002.md"):
        assert _git(context, "cat-file", "-e", f"main:{name}").returncode == 0, f"{name} is missing"


def test_update_branch_REBASES_a_bare_proposal_and_says_so(forge, context, authoring, scratch):
    """The merge watch's path: `behind`, then `update_branch`, then `clean`. It answered False on a
    bare repository and moved nothing — honest, and a dead end."""
    first = _propose(forge, authoring, "req/0001-login", {"REQ-0001.md": "# log in\n"})
    second = _propose(forge, authoring, "req/0002-logout", {"REQ-0002.md": "# log out\n"})
    forge.merge_pr(pr=first)
    assert forge.mergeable_state(pr=second) == "behind"

    assert forge.update_branch(pr=second) is True

    assert _git(context, "merge-base", "--is-ancestor", "main", "req/0002-logout").returncode == 0
    assert forge.mergeable_state(pr=second) == "clean"
    assert _row(2)["base_sha"] == _sha(context, "main")
    _nothing_left_behind(context, scratch)


# ── when it cannot ──────────────────────────────────────────────────────────────────────────────

def test_a_CONFLICTING_proposal_is_refused_NAMING_THE_FILE_and_nothing_moves(forge, context,
                                                                               authoring, scratch):
    """A REAL CONFLICT, not a planted file: both proposals change the same line of `product.md`.
    Git's `! [rejected]` names nothing the person can act on; the refusal names the file."""
    first = _propose(forge, authoring, "req/0001-login", {"product.md": "# myapp\nlog in\n"})
    second = _propose(forge, authoring, "req/0002-logout", {"product.md": "# myapp\nlog out\n"})
    forge.merge_pr(pr=first)
    base, head = _sha(context, "main"), _sha(context, "req/0002-logout")

    assert forge.update_branch(pr=second) is False
    with pytest.raises(RuntimeError, match="product.md"):
        forge.merge_pr(pr=second)

    assert _sha(context, "main") == base, "the base moved over a conflict"
    assert _sha(context, "req/0002-logout") == head, "the proposal was rewritten over a conflict"
    assert forge.pr_status(pr=second) == "open"
    assert "product.md" in forge.pr_refusal(pr=second), "the page has no file to show"
    _nothing_left_behind(context, scratch)


def test_a_proposal_pushed_AGAIN_during_the_rebase_is_KEPT_not_overwritten(forge, context,
                                                                              authoring,
                                                                              monkeypatch):
    """The branch moves only if it is still where the rebase started. A proposal pushed again while
    the rebase ran is the newer text; landing a rebase of the older one would lose it silently.

    The push is made at the one moment it matters — just before the branch is moved — by the real
    git, into the real repository."""
    first = _propose(forge, authoring, "req/0001-login", {"REQ-0001.md": "# log in\n"})
    second = _propose(forge, authoring, "req/0002-logout", {"REQ-0002.md": "# log out\n"})
    forge.merge_pr(pr=first)
    base = _sha(context, "main")
    real, newer = forge._git, []

    def pushed_again_meanwhile(*args, cwd=None):
        if args[:1] == ("update-ref",) and not newer:
            (authoring / "REQ-0002.md").write_text("# log out, rewritten\n")
            _ok(authoring, "commit", "-qam", "rewrite")
            _ok(authoring, "push", "-q", "origin", "req/0002-logout")
            newer.append(_sha(context, "req/0002-logout"))
        return real(*args, cwd=cwd)

    monkeypatch.setattr(forge, "_git", pushed_again_meanwhile)
    with pytest.raises(RuntimeError):
        forge.merge_pr(pr=second)

    assert newer, "the setup never reached the moment it exists for"
    assert _sha(context, "req/0002-logout") == newer[0], "the newer push was overwritten"
    assert _sha(context, "main") == base


def test_the_persons_OWN_branch_is_never_rebased_by_a_merge(forge, repo, scratch):
    """Only the installation's bare repository is rebased. In the person's repository a merge is a
    fast-forward and nothing else, as the module promises: a branch that fell behind there is
    refused, and nothing of theirs is rewritten or registered."""
    (repo / "other.py").write_text("print('theirs')\n")
    _ok(repo, "add", "-A")
    _ok(repo, "commit", "-qm", "their own work")
    pr = forge.open_pr(head="openfactory/1", base="main", title="t", body="b")
    job = _sha(repo, "openfactory/1")
    assert forge.mergeable_state(pr=pr) == "behind"

    with pytest.raises(RuntimeError):
        forge.merge_pr(pr=pr)

    assert _sha(repo, "openfactory/1") == job, "a merge rewrote the person's branch"
    assert _git(repo, "worktree", "list", "--porcelain").stdout.count("worktree ") == 1


def test_a_proposal_into_a_base_that_does_not_EXIST_yet_creates_it(forge, authoring):
    """A base that was never pushed is behind nothing, and the fast-forward creates it, as it did
    before any rebase existed. `merge-base --is-ancestor` exits non-zero for a ref that does not
    exist as well as for one that moved, and reading both as `behind` sent this proposal to a
    rebase that refused `fatal: invalid upstream 'main'` (found reviewing #144)."""
    forge.create_repository(name=CONTEXT)
    bare = forge.clone_url(CONTEXT)
    subprocess.run(["git", "clone", "-q", bare, str(authoring)], capture_output=True, check=True)
    _identity(authoring)
    _ok(authoring, "checkout", "-q", "-b", "req/0001-login")
    (authoring / "REQ-0001.md").write_text("# log in\n")
    _ok(authoring, "add", "-A")
    _ok(authoring, "commit", "-qm", "propose 1")
    _ok(authoring, "push", "-q", "origin", "req/0001-login")
    pr = forge.open_pr(head="req/0001-login", base="main", title="t", body="b", repo=CONTEXT)
    assert not _sha(bare, "main"), "the setup must be a base that was never pushed"

    forge.merge_pr(pr=pr)

    assert _sha(bare, "main") == _sha(bare, "req/0001-login"), "the fast-forward made no base"
    assert forge.pr_status(pr=pr) == "merged"

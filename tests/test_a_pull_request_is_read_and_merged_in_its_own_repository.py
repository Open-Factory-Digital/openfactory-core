"""A pull request on the local forge is read and merged in the repository it is against (#140).

WHAT WAS MEASURED, on a one-machine deployment: `openfactory product baseline <project> --yes`
opened pull request #1 against the product's CONTEXT repository, and the panel could neither read
it (`pr_diff() answered None`) nor merge it (`the branch … is gone from this repository`). The row
is built once per project with one `repo_path`, and every git command about a pull request ran
there — in the project's code — whatever repository the pull request had been opened against.
`open_pr` even wrote it down wrong: `base_sha` and `patch_id`, read in the project's repository,
came back empty.

NOTHING BEFORE THIS FILE COULD HAVE CAUGHT IT. Every test opened its pull request against the
project's own repository, where `cwd or self.repo_path` happens to be right. So every test here
opens one against a SECOND repository — the bare context repository this row really creates — and
asserts that the act happened THERE, and that nothing of the person's moved.

AGAINST REAL GIT, like `test_the_pull_request_lives_in_the_file.py`: the claims are about which
repository git read and which base it moved, and a fake git cannot answer either.
"""

from __future__ import annotations

import sqlite3
import subprocess

import pytest

from openfactory.adapters.forge.local import LocalForge

CONTEXT = "myapp-context"


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


def _row(number: int = 1) -> dict:
    from openfactory.adapters.board_db import connect

    with connect() as conn:
        return dict(conn.execute("SELECT * FROM pull_requests WHERE number = ?",
                                 (number,)).fetchone())


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The person's repository: `main` with one commit, and the factory's job branch."""
    monkeypatch.setenv("HOME", str(tmp_path))      # the context repository is made under it
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
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
    `main` and one requirement pushed on `req/0001-login`, the way the product role pushes it."""
    forge.create_repository(name=CONTEXT)
    bare = forge.clone_url(CONTEXT)
    subprocess.run(["git", "clone", "-q", bare, str(authoring)], capture_output=True, check=True)
    _identity(authoring)
    _ok(authoring, "symbolic-ref", "HEAD", "refs/heads/main")
    (authoring / "product.md").write_text("# myapp\n")
    _ok(authoring, "add", "-A")
    _ok(authoring, "commit", "-qm", "seed")
    _ok(authoring, "push", "-q", "origin", "main")
    _propose(authoring, "req/0001-login", "REQ-0001.md", "# REQ-0001 — a person can log in\n")
    return bare


def _propose(authoring, branch: str, name: str, text: str) -> None:
    """One requirement on its own branch, cut from the context repository's `main` as it is now."""
    _ok(authoring, "fetch", "-q", "origin")
    _ok(authoring, "checkout", "-q", "-B", branch, "origin/main")
    (authoring / name).write_text(text)
    _ok(authoring, "add", "-A")
    _ok(authoring, "commit", "-qm", f"propose {name}")
    _ok(authoring, "push", "-q", "origin", branch)


def _propose_login(forge) -> str:
    return forge.open_pr(head="req/0001-login", base="main", title="REQ-0001", body="why",
                         repo=CONTEXT)


# ── what the pull request records ───────────────────────────────────────────────────────────────

def test_it_records_its_repository_and_takes_its_shas_THERE(forge, context):
    """Read in the person's repository, a context pull request's `base_sha` and `patch_id` were
    both EMPTY — wrong at creation, before anybody asked it anything."""
    _propose_login(forge)
    row = _row()

    assert row["repo"] == CONTEXT
    assert row["base_sha"] == _sha(context, "main"), "read in the person's repository, it was ''"
    assert row["patch_id"], "an empty patch id reads as a pull request that changes nothing"


def test_the_projects_own_repository_is_ONE_key_however_it_is_spelled(forge):
    """`""` and the project's name are the same repository to `clone_url`, so they must be the same
    repository to the row — or a retried `open_pr` spelled the other way files a duplicate."""
    first = forge.open_pr(head="openfactory/1", base="main", title="t", body="b")
    again = forge.open_pr(head="openfactory/1", base="main", title="t", body="b", repo="myapp")

    assert again == first, "one repository, spelled twice, opened two pull requests"
    assert _row()["repo"] == ""
    assert forge.pr_for_head("openfactory/1", repo="myapp") == first


def test_one_head_name_in_two_repositories_is_TWO_pull_requests(forge, repo, context):
    """A head is a name inside one repository — `gh pr list --repo` scopes it the same way on the
    hosted row. Unscoped, the second `open_pr` answered the other repository's pull request and
    `pr_for_head` handed the sweep a pull request it would then try to merge in the wrong place."""
    _ok(repo, "branch", "req/0001-login")          # the same name, in the person's repository
    proposal = _propose_login(forge)
    own = forge.open_pr(head="req/0001-login", base="main", title="t", body="b")

    assert own != proposal, "the reuse check answered the other repository's pull request"
    assert forge.pr_for_head("req/0001-login", repo=CONTEXT) == proposal
    assert forge.pr_for_head("req/0001-login") == own


# ── reading and merging it, with only the number in hand ───────────────────────────────────────

def test_the_diff_is_read_in_THAT_repository(forge, context):
    """The panel calls `pr_diff(pr=ref)` holding a number and nothing else — which is why the
    repository has to live on the row rather than be passed."""
    pr = _propose_login(forge)
    diff = forge.pr_diff(pr=pr)

    assert diff is not None, "pr_diff() answered None — the change could not be read"
    assert "a person can log in" in diff


def test_the_merge_moves_THAT_repositorys_base_and_nothing_of_the_persons(forge, repo, context):
    """The activities call `merge_pr(pr=…)` and `mergeable_state(pr=…)` with no repository, and
    the panel's Merge button the same. Before the fix the merge said the branch was gone and the
    page's state said `dirty`."""
    pr = _propose_login(forge)
    theirs, proposed = _sha(repo, "main"), _sha(context, "req/0001-login")

    assert forge.mergeable_state(pr=pr) == "clean"
    forge.merge_pr(pr=pr)

    assert _sha(context, "main") == proposed, "the context repository's base did not move"
    assert _sha(repo, "main") == theirs, "the person's base moved"
    assert forge.pr_status(pr=pr) == "merged" and forge.merge_commit_sha(pr=pr) == proposed
    assert _row()["refused"] == ""


def test_the_persons_repository_MID_MERGE_does_not_block_a_proposal_in_another(forge, repo,
                                                                                context):
    """`_blocked` looked for `MERGE_HEAD` under the project's path whatever the pull request was
    against. The person's own pull request IS refused here — that is the setup proving itself —
    and the proposal is not, because nothing about the context repository is in the way.

    A REAL CONFLICT, not a planted file: the slice's own file learned that a merge which quietly
    fast-forwards leaves no `MERGE_HEAD` and proves nothing."""
    _ok(repo, "checkout", "-q", "-b", "other", "main")
    (repo / "app.py").write_text("print('theirs')\n")
    _ok(repo, "commit", "-qam", "theirs")
    _ok(repo, "checkout", "-q", "main")
    (repo / "app.py").write_text("print('ours')\n")
    _ok(repo, "commit", "-qam", "ours")
    assert _git(repo, "merge", "other").returncode != 0, "the setup must actually conflict"
    assert (repo / ".git" / "MERGE_HEAD").exists()

    own = forge.open_pr(head="openfactory/1", base="main", title="t", body="b")
    proposal = _propose_login(forge)

    assert forge.mergeable_state(pr=own) == "dirty", "the setup must block the person's own"
    assert forge.mergeable_state(pr=proposal) == "clean"
    forge.merge_pr(pr=proposal)
    assert forge.pr_status(pr=proposal) == "merged"


def test_a_proposal_whose_base_moved_is_BEHIND_and_no_rebase_is_attempted_without_a_tree(
        forge, context, authoring):
    """Two proposals cut from the same `main`: once the first lands the second is `behind`, read
    in the context repository. A rebase needs a working tree and a bare repository has none, so
    `update_branch` answers False and moves nothing.

    TODAY'S BEHAVIOUR, PINNED SO IT CANNOT CHANGE UNNOTICED — NOT A DECISION. #142 is the
    consequence: that proposal can then never land, and neither can a baseline a requirement
    landed under. Its fix flips the `False` below, and this test with it."""
    first = _propose_login(forge)
    _propose(authoring, "req/0002-logout", "REQ-0002.md", "# REQ-0002 — a person can log out\n")
    second = forge.open_pr(head="req/0002-logout", base="main", title="t", body="b", repo=CONTEXT)
    forge.merge_pr(pr=first)
    before = _sha(context, "req/0002-logout")

    assert forge.mergeable_state(pr=second) == "behind"
    assert forge.update_branch(pr=second) is False
    assert _sha(context, "req/0002-logout") == before, "a False that moved a ref"


def test_the_requirement_sweep_LANDS_a_proposal_on_this_row(forge, context):
    """The blast radius, through the sweep's own entry point. `_merge_and_confirm` catches the
    refusal, reads the state back as `open` and answers False — so on a local deployment every
    proposed requirement was proposed and never landed, once per sweep, for ever, with a warning
    as the only sign."""
    from openfactory.product.authoring import land_open_proposals

    assert land_open_proposals(docs_repo=CONTEXT, forge=forge, base="main") == ["req/0001-login"]
    assert _git(context, "cat-file", "-e", "main:REQ-0001.md").returncode == 0, "not in the base"
    assert "req/0001-login" not in (forge.list_branches(CONTEXT) or []), "the branch outlived it"


def test_a_baseline_the_OLD_ROW_stranded_can_be_proposed_again(forge, context, monkeypatch):
    """The remedy this fix gives a deployment for a baseline #140 stranded — propose it again — and
    MEASURED BEFORE IT WAS TRUE: the second `propose_baseline` failed with `could not push
    product/baseline … behind`. Its recovery arm asked `list_branches()` without naming a
    repository, so it looked for the already-pushed branch in the project's code, never saw it,
    cloned fresh and was refused against the branch the first attempt had left there. It asks
    `docs_repo` now, finds the branch, and opens the pull request the old row never recorded.

    The old row is made exactly the way the migration leaves one: `repo = ''`, and unreadable.

    A RE-RUN WRITES DIFFERENT TEXT, and the first version of this test did not. Two identical passes
    a second apart are the SAME commit, so the fresh push was a no-op, the recovery arm was never
    needed, and this guard stayed green over the very cut it exists for — the mutation run is what
    showed it. So the second pass writes other text, and the pull request must be for the first."""
    from openfactory.adapters.board_db import connect
    from openfactory.product.authoring import propose_baseline

    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "bot")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "bot@example.invalid")

    def baseline(text: str):
        return propose_baseline(docs_repo=CONTEXT, clone_url=forge.clone_url(CONTEXT),
                                files={"baseline/inventory.md": text},
                                product="myapp", observations=1, covered=["app"], forge=forge)

    first = baseline("# the first pass\n")
    assert first.ok, first.detail
    with connect(write=True) as conn:
        conn.execute("UPDATE pull_requests SET repo = '', base_sha = '', patch_id = '' "
                     "WHERE number = 1")
    assert forge.pr_diff(pr=first.url) is None, "the setup must be the unreadable old row"

    again = baseline("# a second pass, which a re-run writes differently\n")

    assert again.ok, f"proposing it again failed: {again.detail}"
    assert again.existed, "it pushed again instead of finding the branch the first pass left"
    assert again.url.endswith("/pr/2") and _row(2)["repo"] == CONTEXT
    assert forge.pr_diff(pr=again.url), "the new pull request cannot be read either"
    forge.merge_pr(pr=again.url)
    landed = _git(context, "show", "main:baseline/inventory.md")
    assert landed.stdout == "# the first pass\n", (
        f"what landed is not what the first pass pushed: {landed.stdout or landed.stderr!r}")


# ── a board.db that was already running ─────────────────────────────────────────────────────────

#: `pull_requests` exactly as `_SCHEMA` created it before the column existed — frozen here, because
#: the file a running deployment has is this one and not whatever the schema says today.
_BEFORE_THE_COLUMN = """CREATE TABLE pull_requests (
       project    TEXT NOT NULL,
       number     INTEGER NOT NULL,
       head       TEXT NOT NULL,
       base       TEXT NOT NULL,
       title      TEXT NOT NULL DEFAULT '',
       body       TEXT NOT NULL DEFAULT '',
       state      TEXT NOT NULL DEFAULT 'open',
       base_sha   TEXT NOT NULL DEFAULT '',
       patch_id   TEXT NOT NULL DEFAULT '',
       merge_sha  TEXT NOT NULL DEFAULT '',
       reviewers  TEXT NOT NULL DEFAULT '',
       events     TEXT NOT NULL DEFAULT '',
       refused    TEXT NOT NULL DEFAULT '',
       created_at TEXT NOT NULL,
       updated_at TEXT NOT NULL,
       PRIMARY KEY (project, number)
   )"""


def test_a_board_db_that_was_already_running_GAINS_the_column(forge, repo, tmp_path):
    """`CREATE TABLE IF NOT EXISTS` skips a table that is there, so a column added to the schema
    alone reaches only files made after it — and on every deployment that had been running, the
    first INSERT naming it fails with `table pull_requests has no column named repo`.

    The row written before the column reads as the project's own, which is what it was for every
    ordinary ticket, and it is still found, still read and still merged."""
    old = sqlite3.connect(tmp_path / "board.db")
    with old:
        old.execute(_BEFORE_THE_COLUMN)
        old.execute("INSERT INTO pull_requests(project, number, head, base, created_at, "
                    "updated_at) VALUES ('myapp', 1, 'openfactory/1', 'main', 'then', 'then')")
    old.close()

    proposal = forge.open_pr(head="req/0001-login", base="main", title="t", body="b",
                             repo=CONTEXT)
    assert proposal.endswith("/pr/2"), "the INSERT naming the column failed on the old file"
    assert forge.pr_for_head("openfactory/1").endswith("/pr/1"), "the old row is the project's"
    assert "print('two')" in (forge.pr_diff(pr="1") or "")
    forge.merge_pr(pr="1")
    assert forge.pr_status(pr="1") == "merged"


def test_a_LOST_race_to_add_the_column_is_not_a_failure(tmp_path, monkeypatch):
    """The worker and the panel opening the same old file after an upgrade both read the column as
    missing and both ALTER; the second is told `duplicate column name`, which is the post-condition
    it wanted. Driven without a race: the first read is made stale, so the ALTER runs against a
    table that already has the column."""
    from openfactory.adapters import board_db

    path = tmp_path / "board.db"
    with board_db.connect(path):
        pass                                        # a current file: the column is there
    real, reads = board_db._columns, []

    def stale_once(conn, table):
        reads.append(table)
        return set() if len(reads) == 1 else real(conn, table)

    monkeypatch.setattr(board_db, "_columns", stale_once)
    with board_db.connect(path) as conn:
        assert "repo" in real(conn, "pull_requests")


def test_any_OTHER_refusal_to_add_a_column_RAISES(tmp_path, monkeypatch):
    """Only the lost race is forgiven. A file this module could not add the column to must not be
    handed out as ready — the refusal would otherwise surface later, as an INSERT failing inside
    somebody's merge.

    ON A TABLE THAT HAS A ROW, because that is the only place SQLite refuses this declaration. The
    first version of this test used a fresh file: SQLite added a `NOT NULL` column with no default
    to the EMPTY table without a word, the test went red for the wrong reason, and a green run of
    it would have proved nothing. A running deployment's table has rows, so this one does too."""
    from openfactory.adapters import board_db

    path = tmp_path / "board.db"
    with board_db.connect(path, write=True) as conn:
        conn.execute("INSERT INTO pull_requests(project, number, head, base, created_at, "
                     "updated_at) VALUES ('myapp', 1, 'openfactory/1', 'main', 'now', 'now')")
    monkeypatch.setattr(board_db, "_ADDED_COLUMNS",
                        (("pull_requests", "impossible", "TEXT NOT NULL"),))
    with pytest.raises(sqlite3.OperationalError, match="NOT NULL"):
        with board_db.connect(path):
            pass

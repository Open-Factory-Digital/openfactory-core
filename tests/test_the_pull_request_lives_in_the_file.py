"""`forge.local` — the person's own repository, against REAL GIT (ADR-0049 D3, D4).

NOT A DOUBLE ANYWHERE IN THIS FILE. Every test here runs `git init`, makes commits and reads the
repository back, because the claims are all about what git does: which pushes land, which merges
are refused, and what is left in somebody's working tree afterwards. A fake git would prove that
this module calls the commands it calls, which is not the question.

WHAT IS PROVEN, and it is D3's table row by row:

  · the fast-forward lands on a clean tree, and over an UNRELATED edit;
  · it is refused, with git's own sentence, when the edit OVERLAPS, when a merge or rebase is in
    progress, and when the branch is gone;
  · a base nobody has checked out moves without touching any tree, dirty or not;
  · a base checked out in a linked worktree is refused — *checked out* is decided over
    `git worktree list`, never `HEAD` alone;
  · nothing else in the person's repository is written: no remote, no config, no hook.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.adapters.forge.local import LocalForge


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=False)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A person's repository: `main` with one commit, and a job branch with one more."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    where = tmp_path / "myapp"
    where.mkdir()
    _git(where, "init", "-q", "-b", "main")
    _git(where, "config", "user.email", "person@example.invalid")
    _git(where, "config", "user.name", "A Person")
    (where / "app.py").write_text("print('one')\n")
    (where / "README.md").write_text("# myapp\n")
    _git(where, "add", "-A")
    _git(where, "commit", "-qm", "first")
    _git(where, "checkout", "-q", "-b", "openfactory/1")
    (where / "app.py").write_text("print('two')\n")
    _git(where, "add", "-A")
    _git(where, "commit", "-qm", "the factory's change")
    _git(where, "checkout", "-q", "main")
    return where


@pytest.fixture
def forge(repo):
    return LocalForge("myapp", str(repo), base="main")


@pytest.fixture
def pr(forge):
    return forge.open_pr(head="openfactory/1", base="main", title="Make it two", body="why")


def _head(repo, ref="HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


# ── the pull request itself ─────────────────────────────────────────────────────────────────────

def test_the_address_is_a_route_on_the_panel(forge, pr):
    assert pr.endswith("/p/myapp/pr/1")


def test_opening_twice_from_one_head_reuses_the_open_one(forge, pr):
    """A retried activity must not double-file (D-16). The reuse is narrower than `pr_for_head`:
    it asks whether one is OPEN, so an abandoned pull request is no reason to refuse a fresh one."""
    assert forge.open_pr(head="openfactory/1", base="main", title="x", body="y") == pr
    forge.close_pr(pr=pr, reason="thought better of it")
    again = forge.open_pr(head="openfactory/1", base="main", title="x", body="y")
    assert again != pr and again.endswith("/pr/2")


def test_pr_for_head_answers_in_any_state_and_tells_none_from_unreadable(forge, pr, monkeypatch):
    """A caller writing `if not pr: open_one()` puts `""` and `None` together and files a
    duplicate on a transient error — so the two must not share a shape."""
    assert forge.pr_for_head("openfactory/1") == pr
    forge.close_pr(pr=pr)
    assert forge.pr_for_head("openfactory/1") == pr, "closed is still an answer of yes"
    assert forge.pr_for_head("never-proposed") == "", "read fine, none was ever opened"

    monkeypatch.setattr("openfactory.adapters.forge.local.connect",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk")))
    assert forge.pr_for_head("openfactory/1") is None, "could not look is its own answer"


def test_pr_status_RAISES_rather_than_guessing(forge):
    """"open" would send the sweep on to merge something already merged; "merged" would drop a
    live pull request out of its attention for ever. Both are worse than a retry."""
    with pytest.raises(KeyError):
        forge.pr_status(pr="http://localhost:8787/p/myapp/pr/404")


def test_the_body_and_the_review_events_are_the_records(forge, pr):
    assert forge.pr_body(pr=pr) == "why"
    assert forge.set_pr_body(pr=pr, body="a better why") is True
    assert forge.pr_body(pr=pr) == "a better why"
    assert forge.pr_body(pr="http://localhost:8787/p/myapp/pr/404") is None

    forge.review_pr(pr=pr, event="approve", body="looks right")   # ReviewEvent is a Literal
    forge.request_reviewers(pr=pr, reviewers=[])       # the runner passes this unconditionally
    forge.request_reviewers(pr=pr, reviewers=["mara"])


def test_there_is_no_CI_and_every_answer_says_so(forge, pr):
    assert forge.pr_ci_status(pr=pr) == "none", "the loop never waits on CI and never repairs it"
    assert forge.pr_checks(pr=pr) == [] and forge.failed_ci_logs(pr=pr) == ""
    assert forge.latest_run(workflow="e2e.yml") is None
    assert forge.deploy_run_status(sha="abc", workflow="deploy.yml") == ("none", None)
    assert forge.disabled_ci_paths() == [], "asked, and none are disabled — not 'cannot say'"

    with pytest.raises(RuntimeError, match="no CI to dispatch"):
        forge.dispatch_workflow(workflow="e2e.yml", ref="main")


def test_the_diff_tells_no_changes_from_could_not_look(forge, pr, repo):
    assert "print('two')" in (forge.pr_diff(pr=pr) or "")
    assert forge.pr_diff(pr="http://localhost:8787/p/myapp/pr/404") is None

    tiny = forge.pr_diff(pr=pr, max_chars=40)
    assert tiny and "truncated" in tiny, "a diff that stops mid-hunk reads as a change ending there"


# ── D3's table, against real git ────────────────────────────────────────────────────────────────

def test_the_merge_is_a_fast_forward_on_a_clean_tree(forge, pr, repo):
    before = _head(repo, "openfactory/1")
    forge.merge_pr(pr=pr)
    assert _head(repo, "main") == before, "the base is the head's own commit, not a new one"
    assert (repo / "app.py").read_text() == "print('two')\n"
    assert forge.pr_status(pr=pr) == "merged" and forge.merge_commit_sha(pr=pr) == before


def test_it_lands_over_an_UNRELATED_edit_and_keeps_it(forge, pr, repo):
    """Their work is not in the way of ours, and a merge that refused here would make the factory
    unusable to anybody who works while it works."""
    (repo / "notes.txt").write_text("mine\n")
    (repo / "README.md").write_text("# myapp\n\nmine\n")
    _git(repo, "add", "README.md")            # one staged, one untracked

    assert forge.mergeable_state(pr=pr) == "clean"
    forge.merge_pr(pr=pr)
    assert (repo / "app.py").read_text() == "print('two')\n"
    assert (repo / "notes.txt").exists(), "their untracked file survived"
    assert "mine" in (repo / "README.md").read_text(), "and their staged edit did"


def test_an_OVERLAPPING_edit_is_refused_with_gits_own_sentence(forge, pr, repo):
    """MEASURED, AND THIS IS THE TEST THAT FOUND A DEFECT. `mergeable_state` answered `clean` here
    while `merge_pr` refused — the worst pair this row could give, because a page would offer a
    merge button that cannot work. The cause was reading `git status --porcelain` through a helper
    that STRIPS: porcelain puts two significant columns before the path, so every name shifted by
    one character and nothing ever overlapped."""
    (repo / "app.py").write_text("print('mine')\n")

    assert forge.mergeable_state(pr=pr) == "dirty"
    with pytest.raises(RuntimeError) as caught:
        forge.merge_pr(pr=pr)
    assert "app.py" in str(caught.value), "git names the file and the paraphrase would not"
    assert (repo / "app.py").read_text() == "print('mine')\n", "their tree is untouched"
    assert forge.pr_status(pr=pr) == "open", "a refused merge is still open"


def test_the_refusal_is_written_on_the_pull_request(forge, pr, repo):
    """The sentence travels: the page and the hold print what git said."""
    (repo / "app.py").write_text("print('mine')\n")
    forge.mergeable_state(pr=pr)
    from openfactory.adapters.board_db import connect

    with connect() as conn:
        row = conn.execute("SELECT refused FROM pull_requests WHERE number = 1").fetchone()
    assert "app.py" in row["refused"]


def test_a_merge_in_progress_is_refused_BEFORE_anything_else(forge, pr, repo):
    """AND THE ORDER IS THE CLAIM. This repository is both `behind` and mid-merge, and `dirty` has
    to win: a tree with unmerged paths cannot be rebased either, so answering `behind` would spend
    the loop's bounded update attempts on a repository that refuses every one of them.

    The setup is fussy on purpose — the first version of this test merged a branch that
    FAST-FORWARDED, left no `MERGE_HEAD` at all, and proved nothing."""
    _git(repo, "checkout", "-q", "-b", "other", "main")
    (repo / "app.py").write_text("print('theirs')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "theirs")
    _git(repo, "checkout", "-q", "main")
    (repo / "app.py").write_text("print('ours')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ours")           # now the two genuinely diverge
    conflicted = _git(repo, "merge", "other")
    assert conflicted.returncode != 0, "the setup must actually conflict"
    assert (repo / ".git" / "MERGE_HEAD").exists()

    assert forge.mergeable_state(pr=pr) == "dirty"
    with pytest.raises(RuntimeError, match="merge in progress"):
        forge.merge_pr(pr=pr)


def test_a_branch_that_is_gone_is_dirty_and_not_a_crash(forge, pr, repo):
    _git(repo, "branch", "-D", "openfactory/1")
    assert forge.mergeable_state(pr=pr) == "dirty"
    with pytest.raises(RuntimeError, match="gone"):
        forge.merge_pr(pr=pr)


def test_a_base_NOBODY_has_checked_out_moves_without_touching_a_tree(forge, repo):
    """The ref moves; the working tree — dirty or not — is not written."""
    _git(repo, "checkout", "-q", "-b", "elsewhere")
    (repo / "app.py").write_text("print('working on something')\n")
    pr = forge.open_pr(head="openfactory/1", base="main", title="t", body="b")

    assert forge.mergeable_state(pr=pr) == "clean"
    forge.merge_pr(pr=pr)
    assert _head(repo, "main") == _head(repo, "openfactory/1")
    assert (repo / "app.py").read_text() == "print('working on something')\n", "untouched"


def test_a_base_checked_out_in_a_LINKED_WORKTREE_is_seen(forge, repo, tmp_path):
    """*Checked out* is decided over `git worktree list`, never `HEAD` alone: a linked worktree
    holds a branch this repository's HEAD never mentions, and git refuses to move it just the
    same."""
    _git(repo, "checkout", "-q", "openfactory/1")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", str(linked), "main")
    (linked / "app.py").write_text("print('mine, over there')\n")

    pr = forge.open_pr(head="openfactory/1", base="main", title="t", body="b")
    assert forge._worktree_of("main") == str(linked), "HEAD alone would have said nobody"
    assert forge.mergeable_state(pr=pr) == "dirty"
    with pytest.raises(RuntimeError, match="checked out in"):
        forge.merge_pr(pr=pr)
    assert (linked / "app.py").read_text() == "print('mine, over there')\n", "untouched"


def test_the_base_moving_under_it_is_BEHIND_and_not_a_refusal(forge, pr, repo):
    """A rebase would apply. `behind` is what the loop's bounded update path reads."""
    _git(repo, "commit", "-q", "--allow-empty", "-m", "somebody else's work")
    assert forge.mergeable_state(pr=pr) == "behind"

    assert forge.update_branch(pr=pr) is True
    assert forge.mergeable_state(pr=pr) == "clean"
    forge.merge_pr(pr=pr)
    assert forge.pr_status(pr=pr) == "merged"


def test_a_head_somebody_has_checked_out_is_not_rebased_under_them(forge, pr, repo):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "somebody else's work")
    _git(repo, "checkout", "-q", "openfactory/1")
    assert forge.update_branch(pr=pr) is False


def test_the_merge_is_idempotent(forge, pr):
    """A retried activity must not fail on work already done (D-16)."""
    forge.merge_pr(pr=pr)
    forge.merge_pr(pr=pr)
    assert forge.pr_status(pr=pr) == "merged"


def test_force_merge_is_the_same_act(forge, pr, repo):
    """There is no branch protection here to override, so a `force_merge` that did MORE would be
    a second way to write somebody's repository that nothing asked for."""
    forge.force_merge(pr=pr)
    assert _head(repo, "main") == _head(repo, "openfactory/1")


def test_mergeable_state_NEVER_raises(forge, monkeypatch):
    """The activity that calls it has no `try`, so a row that raised would take down a watch every
    other row survives."""
    monkeypatch.setattr(LocalForge, "_row",
                        lambda self, pr: (_ for _ in ()).throw(RuntimeError("disk")))
    assert forge.mergeable_state(pr="http://localhost:8787/p/myapp/pr/1") == "unknown"


# ── what it writes, and what it does not ────────────────────────────────────────────────────────

def test_nothing_is_added_to_the_persons_repository(forge, pr, repo):
    """The list in this module's docstring, checked: refs and the fast-forward, and nothing else."""
    before = (repo / ".git" / "config").read_text()
    forge.merge_pr(pr=pr)

    assert (repo / ".git" / "config").read_text() == before, "no remote, no config was written"
    assert _git(repo, "remote").stdout.strip() == "", "no remote was added"
    hooks = [h for h in (repo / ".git" / "hooks").iterdir() if not h.name.endswith(".sample")]
    assert hooks == [], "no hook was installed"


def test_push_remote_is_the_path_and_never_None(forge, repo):
    """`None` means *use the ambient origin* at nine call sites, and this repository has none."""
    assert forge.push_remote() == str(repo)


def test_a_clone_url_is_a_path_and_a_URL_is_left_alone(forge, repo):
    assert forge.clone_url("") == str(repo) and forge.clone_url("myapp") == str(repo)
    assert forge.clone_url("https://example.invalid/x.git") == "https://example.invalid/x.git"
    assert forge.clone_url("myapp-context").endswith("context/myapp-context.git")


def test_a_diff_with_no_merge_base_is_could_not_look(forge, repo):
    """Two roots have no common ancestor, so there is no three-dot diff to take. `""` would say
    *this pull request changes nothing*, which is a claim about somebody's work that no read made."""
    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "rm", "-rq", "--cached", ".")
    (repo / "other.py").write_text("print('unrelated')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a second root")
    _git(repo, "checkout", "-q", "main")

    pr = forge.open_pr(head="unrelated", base="main", title="t", body="b")
    assert forge.pr_diff(pr=pr) is None
    assert forge.mergeable_state(pr=pr) == "behind", "no ancestry is not a clean fast-forward"


def test_a_REFUSED_branch_delete_answers_False(forge, repo):
    """Already-gone and refused must not share a shape: `True` on a refusal would have the
    convergence sweep stop looking at a branch that is still there, for ever."""
    assert forge.delete_branch("openfactory/1") is True
    assert forge.delete_branch("openfactory/1") is True, "already gone is the post-condition"
    assert forge.delete_branch("main") is False, "git refuses to delete a checked-out branch"
    assert "main" in (forge.list_branches() or []), "and it is still there"


def test_conformance_NAMES_a_forge_that_cannot_say_where_to_push(forge):
    """The rule is only worth its runtime if it fails on the shape it forbids.

    A SUBCLASS RATHER THAN A HAND-BUILT DOUBLE, because `check_forge` returns early with
    `forge.protocol` for anything that does not satisfy the whole port — so a three-method double
    would test the protocol check and never reach this rule."""
    from openfactory.conformance.adapters import check_forge

    class _Mute(type(forge)):
        def push_remote(self):
            return "   "

    mute = _Mute("myapp", forge.repo_path)
    rules = {f.rule for f in check_forge(mute)}
    assert "forge.push-remote-is-a-remote" in rules, (
        "an empty string is not a remote, and it fails at the last step of a job that did all "
        "its work")


def test_a_credential_is_never_spliced_into_a_url(forge):
    foreign = "https://github.com/somebody/else.git"
    assert forge.authenticated_url(foreign) == foreign


def test_branches_tell_none_from_unreadable(forge, repo, tmp_path):
    assert sorted(forge.list_branches()) == ["main", "openfactory/1"]
    assert forge.list_branches(prefix="openfactory/") == ["openfactory/1"]
    assert LocalForge("x", str(tmp_path / "not-a-repo")).list_branches() is None



# ── the row is a row ────────────────────────────────────────────────────────────────────────────

def test_the_registry_builds_it_by_kind(tmp_path, monkeypatch, repo):
    from openfactory.adapters.forge.registry import FORGES, build_forge
    from openfactory.contracts.project import Project, ProviderRef

    assert "local" in FORGES
    project = Project(name="myapp", repo_path=str(repo),
                      tracker=ProviderRef(kind="local", repo="myapp", options={}),
                      forge=ProviderRef(kind="local", repo="myapp", options={}))
    assert isinstance(build_forge(project), LocalForge)


def test_it_is_conformant_and_answers_the_merge_watchs_three(forge):
    from openfactory.adapters.forge.base import ForgeAdapter
    from openfactory.conformance.adapters import check_forge

    assert check_forge(forge) == []
    assert isinstance(forge, ForgeAdapter)
    for name in ("mergeable_state", "update_branch", "force_merge"):
        assert hasattr(forge, name), f"the merge-watch calls {name} and would crash"


def test_the_watchs_three_are_on_the_port_for_EVERY_row():
    """They were called by name with no `getattr` and no fallback, so a row without them raised
    inside the durable watch — after the agent had run and the pull request was open."""
    from openfactory.adapters.forge.base import ForgeAdapter
    from openfactory.adapters.forge.registry import FORGES

    for name in ("mergeable_state", "update_branch", "force_merge"):
        assert hasattr(ForgeAdapter, name), f"{name} is not written down anywhere"
    assert set(FORGES) >= {"local", "github", "azure_devops"}


def test_the_local_row_owns_no_host(repo):
    """Its repositories are paths, so no URL is *on its host* — an empty set, not a missing key,
    which would have it refused as foreign on its own."""
    from openfactory.doors import shipped_hosts as _shipped_hosts

    assert _shipped_hosts()["local"] == set()

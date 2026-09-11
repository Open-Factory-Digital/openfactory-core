"""Knowledge Pipeline — publish the bundle into the project's CONTEXT repository, then consume it.

These run against REAL git repositories (bare repos as the "remotes", local clones as the source
project and the context repository), because everything that can go wrong here is git behaviour:
does the first publish land on the context repo's own default branch, does it coexist with
human-authored `docs/` already there, does a born-empty context repo get a real branch instead of
an orphan history, does a second source in the same multirepo project land in its own folder
without colliding, does an unchanged rebuild stay silent, and does the tokened remote get scrubbed
from the throwaway checkouts. Mocks would prove none of it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.knowledge import build_bundle, write_bundle
from openfactory.knowledge.bundle import BUNDLE_DIRNAME, MANIFEST_FILE
from openfactory.knowledge.pipeline import (
    discard_fetched_bundle,
    fetch_published_bundle,
    okf_subpath,
    publish_bundle,
)

_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}

#: the source identity every test in this file uses unless it cares about a second one
_SUBPATH = okf_subpath("owner/repo")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env={**_ENV, "HOME": str(cwd)}).stdout


def _client_repo(tmp: Path, branch: str = "main") -> tuple[Path, Path]:
    """A bare 'remote' + a working clone with some product code on `branch`.

    `branch` IS A PARAMETER because every client in this file used to be on `main`, and that is
    the one shape where a re-clone at the literal `main` cannot fail — so the suite was green over
    a refresh that died on its first line for everybody else."""
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", branch, str(remote)], check=True)
    work = tmp / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True)
    (work / "core").mkdir()
    (work / "core" / "__init__.py").write_text('"""Core domain."""\n')
    (work / "core" / "rules.py").write_text("def decide(x):\n    return x\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "init")
    _git(work, "push", "-q", "origin", branch)
    return remote, work


def _context_repo(tmp: Path, *, name: str = "context", with_docs: bool = True,
                  branch: str = "main") -> Path:
    """A bare 'remote' standing in for the project's context repository.

    `with_docs=True` (the common case — a project already onboarded) seeds it with a `docs/` file
    on `branch`, so tests can assert that publishing a bundle never disturbs it — the two now
    share one branch, where the old orphan-branch design made that structurally impossible to even
    ask. `with_docs=False` is a genuinely EMPTY bare repo — no commits YET, but with a real default
    branch name — exactly the state `create_context_repository` leaves a freshly created repo in.

    `-b <branch>` MATTERS even with zero commits: a real forge (GitHub/Azure/GitLab) tracks a
    repository's default branch name from creation, before any push. `git init --bare` with no
    `-b` does not — its symbolic HEAD stays wherever `init.defaultBranch` happens to point until
    the FIRST commit exists, so a raw bare repo silently does not reproduce what a real forge
    guarantees; omitting `-b` here reproduced a bug that only a git-server quirk, not the pipeline,
    would ever trigger.

    `branch` IS A PARAMETER for the same reason `_client_repo`'s is: every context repo in this
    file used to default to `main`, which is the one name a GUESSED `--branch main` clone can
    never fail to find — so a suite that only ever used `main` could not tell "the branch is
    discovered" from "the branch is guessed and happens to be right"."""
    remote = tmp / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", branch, str(remote)], check=True)
    if with_docs:
        seed = tmp / f"{name}-seed"
        subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
        _git(seed, "checkout", "-qb", branch)
        (seed / "docs").mkdir()
        (seed / "docs" / "survey.md").write_text("# Survey\n")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-qm", "onboarding: survey")
        _git(seed, "push", "-q", "origin", branch)
        shutil.rmtree(seed)
    return remote


def _refresh(work: Path, context: Path, *, subpath: Path = _SUBPATH) -> str:
    """One pipeline pass, mirroring the activity: materialize what's published → rebuild →
    publish only if the sources actually changed."""
    published = fetch_published_bundle(str(context), subpath=subpath)
    dest = work / BUNDLE_DIRNAME
    try:
        if published is not None:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(published, dest)
        commit = _git(work, "rev-parse", "HEAD").strip()
        bundle = build_bundle(work, commit=commit, generated_at="t")
        if write_bundle(bundle, work) is None:
            return "unchanged"
        return "published" if publish_bundle(dest, str(context), subpath=subpath,
                                             source_commit=commit) else "failed"
    finally:
        if published is not None:
            discard_fetched_bundle(published)
        shutil.rmtree(dest, ignore_errors=True)  # never leave it in the product checkout


def _branch_commits(remote: Path, branch: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(remote), "log", "--format=%s", branch],
                         capture_output=True, text=True, check=False)
    return [] if out.returncode != 0 else [ln for ln in out.stdout.splitlines() if ln.strip()]


def test_first_publish_lands_on_a_real_branch_with_only_the_bundle_at_its_subpath(
        tmp_path: Path):
    """A born-empty context repository (what `create_context_repository` leaves behind) gets its
    bundle on a real branch — not an orphan history disconnected from whatever the repo's actual
    default branch turns out to be."""
    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    assert _refresh(work, context) == "published"

    files = _git(context, "ls-tree", "-r", "--name-only", "main").split()
    assert sorted(files) == [f"{_SUBPATH}/manifest.yaml", f"{_SUBPATH}/modules.yaml"]
    assert len(_branch_commits(context, "main")) == 1


def test_the_branch_is_DISCOVERED_not_a_guess(tmp_path: Path):
    """A context repository already onboarded — real content, real default branch — whose branch
    is NOT `main`: the one name a guessed `--branch main` clone could never fail to find, so a
    suite that only ever used `main` could not tell discovery from a guess that happened to be
    right. A guessed clone would fail to find the already-published bundle on the second refresh,
    misread that as "nothing published", and republish even though nothing changed — an unborn
    empty repo genuinely defaulting to `main` (this platform's own choice on a repo it just
    created) is the OTHER, legitimate case; this test is about a repo that already has history
    elsewhere."""
    context = _context_repo(tmp_path, with_docs=True, branch="trunk")
    _, work = _client_repo(tmp_path)
    assert _refresh(work, context) == "published"
    files = _git(context, "ls-tree", "-r", "--name-only", "trunk").split()
    assert "docs/survey.md" in files
    assert f"{_SUBPATH}/modules.yaml" in files

    assert _refresh(work, context) == "unchanged"  # the fetch found the baseline on `trunk`
    assert len(_branch_commits(context, "trunk")) == 2  # onboarding's own commit + one refresh


def test_publishing_never_touches_docs_already_on_the_same_branch(tmp_path: Path):
    """`.okf/` and `docs/` are now SIBLINGS on one branch — the design docs' own tree. This is the
    property the old orphan-branch design made structurally impossible to even risk: prove a
    publish genuinely coexists with human-authored content rather than merely not conflicting
    with it by being elsewhere."""
    context = _context_repo(tmp_path, with_docs=True)
    _, work = _client_repo(tmp_path)
    _refresh(work, context)

    files = _git(context, "ls-tree", "-r", "--name-only", "main").split()
    assert "docs/survey.md" in files
    assert f"{_SUBPATH}/modules.yaml" in files
    content = subprocess.run(["git", "-C", str(context), "show", "main:docs/survey.md"],
                             capture_output=True, text=True, check=True).stdout
    assert content == "# Survey\n"


def test_second_pass_over_unchanged_sources_publishes_nothing(tmp_path: Path):
    """Convergence: the refresh is triggered by merges, and its own commit must not look like a
    reason to refresh again. Otherwise the pipeline feeds itself forever."""
    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    assert _refresh(work, context) == "published"
    assert _refresh(work, context) == "unchanged"
    assert _refresh(work, context) == "unchanged"
    assert len(_branch_commits(context, "main")) == 1


def test_a_real_source_change_publishes_a_second_commit_keeping_history(tmp_path: Path):
    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    _refresh(work, context)

    (work / "core" / "extra.py").write_text("def more():\n    return 2\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: extra")
    _git(work, "push", "-q", "origin", "main")

    assert _refresh(work, context) == "published"
    commits = _branch_commits(context, "main")
    # history ACCUMULATES — "what was the map at commit X?" stays answerable
    assert len(commits) == 2
    assert all(c.startswith("chore(okf): refresh module map @") for c in commits)


def test_two_sources_in_one_project_land_in_distinct_folders_without_colliding(tmp_path: Path):
    """D-2: one folder per source. A multirepo product's second source must not clobber the
    first's bundle — proven by publishing both into the SAME context repository and checking
    both survive."""
    context = _context_repo(tmp_path, with_docs=False)
    _, work_a = _client_repo(tmp_path)
    subpath_a = okf_subpath("owner/repo-a")
    assert _refresh(work_a, context, subpath=subpath_a) == "published"

    remote_b = tmp_path / "remote-b.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote_b)], check=True)
    work_b = tmp_path / "work-b"
    subprocess.run(["git", "clone", "-q", str(remote_b), str(work_b)], check=True)
    (work_b / "api").mkdir()
    (work_b / "api" / "__init__.py").write_text('"""API domain."""\n')
    _git(work_b, "add", "-A")
    _git(work_b, "commit", "-qm", "init")
    _git(work_b, "push", "-q", "origin", "main")
    subpath_b = okf_subpath("owner/repo-b")
    assert subpath_a != subpath_b
    assert _refresh(work_b, context, subpath=subpath_b) == "published"

    files = set(_git(context, "ls-tree", "-r", "--name-only", "main").split())
    assert f"{subpath_a}/modules.yaml" in files
    assert f"{subpath_b}/modules.yaml" in files
    # publishing the second source did not touch the first's commit history
    assert len(_branch_commits(context, "main")) == 2


def test_fetched_bundle_is_usable_and_scrubbed(tmp_path: Path):
    """A job consumes the published bundle from OUTSIDE its workspace, and the throwaway
    checkout must not keep a tokened remote on disk."""
    from openfactory.knowledge import is_trustworthy, read_bundle_dir

    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    _refresh(work, context)

    got = fetch_published_bundle(str(context), subpath=_SUBPATH)
    assert got is not None
    try:
        bundle = read_bundle_dir(got)
        assert bundle is not None
        # it verifies against the product checkout, which has NO knowledge/ dir of its own
        assert not (work / BUNDLE_DIRNAME).exists()
        assert is_trustworthy(bundle, work) is True
        config = (got.parents[2] / ".git" / "config").read_text()
        assert "invalid.local/scrubbed" in config and str(context) not in config
    finally:
        discard_fetched_bundle(got)


def test_fetch_returns_none_before_anything_is_published(tmp_path: Path):
    context = _context_repo(tmp_path, with_docs=False)
    assert fetch_published_bundle(str(context), subpath=_SUBPATH) is None  # normal, not an error
    assert fetch_published_bundle("", subpath=_SUBPATH) is None


def test_fetch_returns_none_when_the_context_repo_only_has_docs_so_far(tmp_path: Path):
    """A project that was onboarded (has `docs/`) but never had a knowledge refresh run yet — the
    bundle's subpath genuinely has nothing in it, distinct from the repo being unreachable."""
    context = _context_repo(tmp_path, with_docs=True)
    assert fetch_published_bundle(str(context), subpath=_SUBPATH) is None


def test_a_context_repo_that_cannot_be_READ_says_which_empty_it_is(tmp_path: Path):
    """THE TWO WAYS OF COMING BACK WITH NOTHING ARE DIFFERENT FACTS, and both used to be `None`.

    A consumer that RENDERS the absence to a reader — the tech-lead's fact pack does — turns "the
    clone failed" into "this project has no map", which is a claim about the client's codebase
    produced by a read that failed. The distinction costs one field and cannot be recovered
    afterwards: by the time the caller has `None`, the clone's exit code is gone."""
    from openfactory.knowledge.pipeline import fetch_bundle

    got = fetch_bundle(str(tmp_path / "no-such-repo.git"), subpath=_SUBPATH)

    assert got.path is None
    assert got.unreadable, "an unreachable context repository reads as 'nothing published'"


@pytest.mark.parametrize("with_docs", [False, True])
def test_nothing_published_is_an_ABSENCE_and_says_nothing(tmp_path: Path, with_docs: bool):
    """The twin, and the reason the distinction is worth having: every project is in this state
    until its first backfill, so reporting it would put a warning on all of them — and a warning
    on everything is a warning nobody reads. `with_docs=True` is the onboarded project whose
    knowledge refresh has simply not run yet; `False` is the born-empty repository."""
    from openfactory.knowledge.pipeline import fetch_bundle

    context = _context_repo(tmp_path, with_docs=with_docs)

    got = fetch_bundle(str(context), subpath=_SUBPATH)

    assert got.path is None and got.unreadable == ""


def test_the_path_only_form_still_answers_the_callers_that_ask_it_that(tmp_path: Path):
    """`fetch_published_bundle` is the same fetch with the reason dropped. Publishing is the caller
    that wants it: a refresh that cannot read what is live rebuilds from a tree without it and
    compares against nothing, exactly as a first-ever publish does."""
    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    _refresh(work, context)

    got = fetch_published_bundle(str(context), subpath=_SUBPATH)
    try:
        assert got is not None and (got / MANIFEST_FILE).is_file()
    finally:
        discard_fetched_bundle(got)


def test_stale_published_bundle_is_not_served(tmp_path: Path):
    """The §12 gate still rules: if the tree moved on after the map was published, the map is
    NOT injected — a fail-safe degrade, never a confidently wrong map."""
    from openfactory.knowledge import is_trustworthy, read_bundle_dir

    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    _refresh(work, context)
    (work / "core" / "rules.py").write_text("def decide(x):\n    return x + 99\n")

    got = fetch_published_bundle(str(context), subpath=_SUBPATH)
    try:
        assert is_trustworthy(read_bundle_dir(got), work) is False
    finally:
        discard_fetched_bundle(got)


# ── the ACTIVITY: where the registry, the repo cache, the build and the publish meet ─────────────

class _Forge:
    def __init__(self, repo: str) -> None:
        # `kind` BECAUSE THE REAL `ProviderRef` HAS IT. A double that omits a field the contract
        # carries proves the double: this one passed for as long as nothing asked which vendor the
        # project was on, and the day the clone URL moved behind the forge registry it resolved to
        # `""` and raised. Same shape as `Ticket.state`, which a whole suite validated against
        # fakes that invented it.
        self.repo, self.kind, self.options = repo, "github", {}


class _Tracker:
    def __init__(self, repo: str) -> None:
        self.repo, self.kind, self.options = repo, "github", {}


class _Product:
    def __init__(self, docs_repo: str) -> None:
        self.docs_repo = docs_repo


class _Project:
    def __init__(self, name: str, repo: str, repo_path: str = "/work/does-not-exist",
                docs_repo: str | None = "owner/repo-context") -> None:
        self.name, self.forge, self.tracker = name, _Forge(repo), _Tracker(repo)
        # The registry value: on the WORKER it names no real directory, which is exactly the
        # condition that made the refresh die on its first line. The fake carries it so the test
        # exercises the real shape rather than a friendlier one.
        self.repo_path = repo_path
        # `None` stands for a project never onboarded at all — `.product` itself absent, not just
        # `docs_repo` blank — the state a project that predates `create_context_repository` is in.
        self.product = _Product(docs_repo) if docs_repo is not None else None

    def model_copy(self, *, update: dict):
        """The real `Project` is a pydantic model and the activity uses `model_copy` to point the
        manifest loader at the SYNCED checkout. A fake without it hid that call entirely."""
        clone = _Project(self.name, self.forge.repo, self.repo_path,
                         self.product.docs_repo if self.product else None)
        for key, value in (update or {}).items():
            setattr(clone, key, value)
        return clone


def _patch_activity(monkeypatch, tmp_path: Path, source_remote: Path, context_remote: Path,
                    *, enabled: bool = True, base_branch: str = "",
                    docs_repo: str | None = "owner/repo-context"):
    from openfactory.runtime.temporal import activities as acts

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    # THE SEAM THE ACTIVITY ACTUALLY USES. This patched `entrypoint.clone_url`, which the
    # knowledge refresh stopped importing when the clone URL became a forge question — so the
    # patch went inert and the test started cloning for real. A monkeypatch that no longer
    # intercepts anything is a test that silently changed what it exercises.
    from openfactory.adapters.forge import registry as forge_registry

    def _clone_url_for(project, repo: str = "", *, token=None):
        # dispatches by repo identity, the same way the real forge registry would resolve two
        # different repositories to two different URLs — the source and the context repo are
        # NEVER the same remote once this activity is doing its real job.
        return str(context_remote) if (docs_repo and repo == docs_repo) else str(source_remote)

    monkeypatch.setattr(forge_registry, "clone_url_for", _clone_url_for)
    monkeypatch.setattr(acts.ProjectRegistry, "get",
                        lambda self, name: _Project(name, "owner/repo", docs_repo=docs_repo))

    # THE REAL MANIFEST, not a hand-built double. The double carried `base_branch="main"` — the
    # schema default spelled as if a client had written it — so this harness could not tell a
    # manifest that DECLARES `main` from one that says nothing, which is precisely the collapse
    # that let the re-sync below re-clone a `master` client at a branch it does not have. A double
    # that invents a field's value proves the double (adversarial review, 2026-08-20).
    import openfactory.loader
    from openfactory.contracts import Manifest
    declared = {"base_branch": base_branch} if base_branch else {}
    monkeypatch.setattr(openfactory.loader, "load_manifest",
                        lambda project: Manifest(version=1, knowledge_map=enabled, **declared))
    return acts


def test_activity_publishes_then_converges(tmp_path: Path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    inp = KnowledgeRefreshInput(project="p", issue="42")

    assert acts._do_refresh_knowledge(inp) == "published"
    # the refresh's OWN commit must not read as a reason to refresh again
    assert acts._do_refresh_knowledge(inp) == "unchanged"
    assert len(_branch_commits(context, "main")) == 1

    # a real merge lands new code on main → exactly one more knowledge commit
    (work / "core" / "extra.py").write_text("def more():\n    return 2\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: extra")
    _git(work, "push", "-q", "origin", "main")
    assert acts._do_refresh_knowledge(inp) == "published"
    assert acts._do_refresh_knowledge(inp) == "unchanged"
    assert len(_branch_commits(context, "main")) == 2


def test_activity_leaves_no_bundle_in_the_shared_repo_cache(tmp_path: Path, monkeypatch):
    """The cache is what every job's worktree is cut from. A leftover untracked `knowledge/`
    there would be swept into the next ticket's commit by `git add -A`."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _ = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "published"
    assert not (tmp_path / "cache" / "p" / BUNDLE_DIRNAME).exists()


def test_activity_is_inert_when_the_project_has_not_opted_in(tmp_path: Path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _ = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context, enabled=False)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "off"
    assert _branch_commits(context, "main") == []


def test_activity_never_raises_when_the_repo_is_unreachable(tmp_path: Path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, tmp_path / "does-not-exist.git", context)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "no-repo"


def test_activity_reports_no_context_when_the_project_was_never_onboarded(tmp_path: Path,
                                                                          monkeypatch):
    """A project with no context repository at all — `.product` itself absent, the state a
    project that predates `create_context_repository` (or was never onboarded) is in. Must never
    raise, and must not pay for a source-repo clone it cannot use the result of."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _ = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context, docs_repo=None)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "no-context"
    # nothing was cloned at all — the source repo cache was never populated
    assert not (tmp_path / "cache" / "p").exists()


# ── audit hardening ──────────────────────────────────────────────────────────────────────────────

def test_discard_refuses_to_delete_a_directory_it_did_not_create(tmp_path: Path):
    """Callers hand back what `fetch_published_bundle` gave them, and the layout knowledge lives
    in one place. The prefix guard is what stops a future layout change from turning this into a
    delete of somebody's repo."""
    mine = tmp_path / "openfactory-knowledge-xyz" / "pub" / BUNDLE_DIRNAME
    mine.mkdir(parents=True)
    theirs = tmp_path / "someones-repo" / "pub" / BUNDLE_DIRNAME
    theirs.mkdir(parents=True)

    discard_fetched_bundle(mine)
    assert not (tmp_path / "openfactory-knowledge-xyz").exists()

    discard_fetched_bundle(theirs)
    assert (tmp_path / "someones-repo").exists()  # untouched
    discard_fetched_bundle(None)  # and None is a no-op, not a crash


def test_discard_walks_the_deeper_subpath_a_fetched_context_bundle_sits_at(tmp_path: Path):
    """THE EXACT REGRESSION A FIXED HOP COUNT WOULD MISS. A locally-generated bundle sits two
    segments under its temp root (`<tmp>/pub/knowledge`); a bundle fetched from the context
    repository sits FOUR (`<tmp>/pub/.okf/repos/<source>`). A guard computed as `.parent.parent`
    finds the root for the first shape and silently finds nothing for the second — leaking one
    temp directory per job. This proves both shapes resolve to the same deletion."""
    root = tmp_path / "openfactory-knowledge-abc"
    shallow = root / "pub" / BUNDLE_DIRNAME
    shallow.mkdir(parents=True)
    discard_fetched_bundle(shallow)
    assert not root.exists()

    root2 = tmp_path / "openfactory-knowledge-def"
    deep = root2 / "pub" / ".okf" / "repos" / "owner--repo"
    deep.mkdir(parents=True)
    discard_fetched_bundle(deep)
    assert not root2.exists()


def test_a_rejected_push_is_retried_on_the_new_tip(tmp_path: Path, monkeypatch):
    """Two publishers racing means the loser's map is silently dropped and the project sits on a
    stale map until the next source-changing merge. One re-clone-and-reapply removes that."""
    from openfactory.knowledge import pipeline

    context = _context_repo(tmp_path, with_docs=False)
    _, work = _client_repo(tmp_path)
    bundle = build_bundle(work, commit="c", generated_at="t")
    write_bundle(bundle, work)

    real_git, pushes = pipeline._git, []

    def flaky(*args, **kwargs):
        if args and args[0] == "push":
            pushes.append(args)
            if len(pushes) == 1:
                return 1, "! [rejected] (non-fast-forward)"
        return real_git(*args, **kwargs)

    monkeypatch.setattr(pipeline, "_git", flaky)
    assert pipeline.publish_bundle(work / BUNDLE_DIRNAME, str(context), subpath=_SUBPATH,
                                   source_commit="c") is True
    assert len(pushes) == 2  # rejected once, then landed
    assert len(_branch_commits(context, "main")) == 1


def test_activity_preserves_a_bundle_the_client_keeps_committed(tmp_path: Path, monkeypatch):
    """Phase 1's shape is still supported: a project may keep `knowledge/` committed in its own
    repo. The pipeline writes into the shared cache and must restore tracked content afterwards,
    not blindly delete it. (Orthogonal to WHERE the published bundle lives — this is about the
    SOURCE repo's own cache clone, untouched by the context-repo relocation.)"""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path)
    context = _context_repo(tmp_path, with_docs=False)
    write_bundle(build_bundle(work, commit="c", generated_at="t"), work)
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "chore: commit the bundle in-repo")
    _git(work, "push", "-q", "origin", "main")

    acts = _patch_activity(monkeypatch, tmp_path, remote, context)
    acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p"))

    cached = tmp_path / "cache" / "p" / BUNDLE_DIRNAME
    assert (cached / "modules.yaml").is_file()  # the TRACKED bundle survived
    status = subprocess.run(["git", "-C", str(tmp_path / "cache" / "p"), "status",
                             "--porcelain", "--", BUNDLE_DIRNAME],
                            capture_output=True, text=True, check=True)
    assert status.stdout.strip() == ""  # and the cache is clean, not left modified


def test_a_job_injects_the_locally_generated_map_and_cleans_up_after_itself(tmp_path: Path):
    """The money path, end to end: ADR-0023's local generation (not the published bundle — that
    path is for a human/tool consuming the artefact, §11) — verified against the job's OWN
    workspace, with the bundle never landing inside the checkout, and the temp copy removed
    afterwards."""
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import Manifest, Ticket
    from openfactory.orchestrator import JobRunner

    remote, work = _client_repo(tmp_path)

    # the job's workspace: a branch off the same base commit (what a real sandbox hands over)
    job_ws = tmp_path / "job"
    subprocess.run(["git", "clone", "-q", str(remote), str(job_ws)], check=True)
    _git(job_ws, "checkout", "-qb", "openfactory/1")

    class _Forge:
        def push_remote(self):
            return str(remote)

    class _Sink:
        def emit(self, event):
            pass

    r = JobRunner.__new__(JobRunner)
    r.manifest, r.repo_path = Manifest(knowledge_map=True), tmp_path / "unused-base-clone"
    r.forge, r.events = _Forge(), _Sink()
    ticket = Ticket(id="#1", title="t", objective="o", repo="o/r")
    ws = Workspace(path=Path("/work"), host_path=job_ws, branch="openfactory/1", base_branch="main")

    ctx = r._build_context(ticket, ws)
    assert "### core" in ctx.knowledge_map  # the LOCALLY GENERATED map reached the agent
    assert "ground truth" in ctx.knowledge_map.lower()
    # …and it was NEVER planted in the workspace, so `git add -A` cannot sweep it into the PR
    assert not (job_ws / BUNDLE_DIRNAME).exists()
    assert _git(job_ws, "status", "--porcelain").strip() == ""

    fetched = r._bundle_dir
    assert fetched is not None and fetched.exists()
    r._drop_published_bundle()
    assert not fetched.exists()  # no per-job leak on the worker's disk


def test_a_job_on_a_moved_base_gets_a_map_OF_ITS_OWN_CHECKOUT(tmp_path: Path):
    """This test used to assert the opposite — that a job whose checkout had moved past the
    published map received NOTHING. That was the correct behaviour for a CACHE: serving a map of a
    different commit would mislead the agent, so the §12 gate withheld it.

    ADR-0023 removed the cache. The map is now generated from the tree the agent reads, so "the
    base moved" is no longer a condition that can exist: whatever main did, the job maps its own
    checkout. The scenario that used to produce a silent control arm — and that produced one for
    #478, the very ticket the A/B existed to measure — now produces a correct map including the
    file that moved."""
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import Manifest, Ticket
    from openfactory.orchestrator import JobRunner

    remote, work = _client_repo(tmp_path)
    # main moves on — once the reason this job got nothing, under the old cached-bundle design
    (work / "core" / "later.py").write_text("def later():\n    return 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: later")
    _git(work, "push", "-q", "origin", "main")

    job_ws = tmp_path / "job"
    subprocess.run(["git", "clone", "-q", str(remote), str(job_ws)], check=True)

    class _Forge:
        def push_remote(self):
            return str(remote)

    class _Sink:
        def emit(self, event):
            pass

    r = JobRunner.__new__(JobRunner)
    r.manifest, r.repo_path = Manifest(knowledge_map=True), tmp_path / "unused"
    r.forge, r.events = _Forge(), _Sink()
    ws = Workspace(path=Path("/work"), host_path=job_ws, branch="b", base_branch="main")
    try:
        text = r._build_context(Ticket(id="#1", title="t", objective="o", repo="o/r"),
                                ws).knowledge_map
        assert text, "the job got no map at all — generation should not depend on the base branch"
        assert "later" in text, (
            "the map does not describe the job's own checkout: it is missing the file that moved, "
            "which is the whole point of deriving instead of caching"
        )
        assert r.knowledge_arm() == "injected", (
            "a job with a perfectly good map was still recorded as a control — this is exactly "
            "how #478 was mis-bucketed"
        )
    finally:
        r._drop_published_bundle()

def test_the_refresh_syncs_BEFORE_it_reads_the_manifest():
    """The bug that meant no bundle was ever published, twice.

    `project.repo_path` is a REGISTRY value: on Fargate it is where the entrypoint clones to, on the
    WORKER it names no real directory. Loading the manifest from it raises "no manifest at
    /work/<project>/.sdlc/project.yaml" before the code ever reaches a checkout — and since the
    caller treats a refresh failure as best-effort, it died silently on its first line every time.

    `_do_preflight` already carries a comment about exactly this, having been fixed there first. A
    source-order assertion is crude, but it is the only thing that would have caught the repeat.
    """
    import re
    from pathlib import Path

    src = Path("openfactory/runtime/temporal/activities.py").read_text()
    body = src[src.index("def _do_refresh_knowledge("):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body

    sync_at = body.index("RepoCache().sync(")
    load_at = body.index("load_manifest(")
    assert sync_at < load_at, (
        "the manifest is being loaded before the repo is synced — it will raise on the worker, "
        "where project.repo_path names nothing"
    )
    # …and it must load from the SYNCED path, not from the registry value
    assert re.search(r'load_manifest\(project\.model_copy\(update=\{"repo_path"', body), (
        "load_manifest must be given the synced checkout, never `project` as registered"
    )


# ── the branch nobody declared (#162, adversarial review 2026-08-20) ─────────────────────────────

@pytest.mark.parametrize("branch", ["master", "develop", "main"])
def test_the_refresh_publishes_for_a_client_whose_default_is_not_main(tmp_path: Path, monkeypatch,
                                                                      branch):
    """BEHAVIOUR, where a source-text guard used to stand. The refresh resolved the right branch
    and then re-cloned at `manifest.base_branch` — the schema default `"main"` — so on a `master`
    client the cache was deleted and the round returned `no-repo`, on every merge, for ever."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _work = _client_repo(tmp_path, branch)
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context)

    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "published"
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "unchanged"


def test_a_manifest_that_DECLARES_a_base_branch_is_still_obeyed(tmp_path: Path, monkeypatch):
    """The reverse. `""` must mean "nobody said", never "ignore the file": a client whose default
    is `master` but whose manifest names `release` gets its bundle built from `release`."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path, "master")
    _git(work, "checkout", "-qb", "release")
    (work / "core" / "rules.py").write_text("def decide(x):\n    return x + 1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "on release")
    _git(work, "push", "-q", "origin", "release")
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context, base_branch="release")

    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "published"


def test_a_client_who_MOVES_their_default_branch_stops_being_served_the_old_one(tmp_path: Path):
    """`sync("")` resolved "nobody said" against the existing checkout, so a long-lived worker
    pinned whatever it landed on once. A client moving `main` → `develop` was served the abandoned
    branch for ever, with the tree looking perfectly healthy."""
    from openfactory.runtime.repo_cache import RepoCache, current_branch

    remote, work = _client_repo(tmp_path, "main")
    cache = RepoCache(root=tmp_path / "cache")
    assert current_branch(cache.sync("p", str(remote), "")) == "main"

    _git(work, "checkout", "-qb", "develop")
    _git(work, "commit", "-q", "--allow-empty", "-m", "moved")
    _git(work, "push", "-q", "origin", "develop")
    subprocess.run(["git", "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/develop"],
                   check=True)

    assert current_branch(cache.sync("p", str(remote), "")) == "develop"


def test_a_DECLARED_base_branch_is_obeyed_even_when_it_disagrees_with_the_repository(
        tmp_path: Path, monkeypatch):
    """A client on `master` whose manifest declares `main` gets an honest refusal, not a bundle
    built from a branch they did not name. This is where "compare to the literal `main`" and
    "compare to what the file declared" give different answers: the first quietly publishes from
    `master`, and nothing anywhere says the declared base was never read."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _work = _client_repo(tmp_path, "master")
    context = _context_repo(tmp_path, with_docs=False)
    acts = _patch_activity(monkeypatch, tmp_path, remote, context, base_branch="main")

    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "no-repo"

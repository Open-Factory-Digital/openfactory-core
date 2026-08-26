"""Knowledge Pipeline (Phase 2) — publish the bundle to the client repo, then consume it.

These run against REAL git repositories (a bare repo as the "remote", a local clone as the
project), because everything that can go wrong here is git behaviour: does the first publish
create the branch, does the second one accumulate history instead of overwriting it, does an
unchanged rebuild stay silent, does the published bundle stay OUT of the product branch, and does
the tokened remote get scrubbed from the throwaway checkouts. Mocks would prove none of it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openfactory.knowledge import build_bundle, write_bundle
from openfactory.knowledge.bundle import BUNDLE_DIRNAME
from openfactory.knowledge.pipeline import (
    KNOWLEDGE_BRANCH,
    discard_fetched_bundle,
    fetch_published_bundle,
    publish_bundle,
)

_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


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


def _refresh(work: Path, remote: Path) -> str:
    """One pipeline pass, mirroring the activity: materialize what's published → rebuild →
    publish only if the sources actually changed."""
    published = fetch_published_bundle(str(remote))
    dest = work / BUNDLE_DIRNAME
    try:
        if published is not None:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(published, dest)
        commit = _git(work, "rev-parse", "HEAD").strip()
        bundle = build_bundle(work, commit=commit, generated_at="t")
        if write_bundle(bundle, work) is None:
            return "unchanged"
        return "published" if publish_bundle(dest, str(remote), source_commit=commit) \
            else "failed"
    finally:
        if published is not None:
            discard_fetched_bundle(published)
        shutil.rmtree(dest, ignore_errors=True)  # never leave it in the product checkout


def _branch_commits(remote: Path, branch: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(remote), "log", "--format=%s", branch],
                         capture_output=True, text=True, check=False)
    return [] if out.returncode != 0 else [ln for ln in out.stdout.splitlines() if ln.strip()]


def test_first_publish_creates_the_branch_with_only_the_bundle(tmp_path: Path):
    remote, work = _client_repo(tmp_path)
    assert _refresh(work, remote) == "published"

    files = _git(remote, "ls-tree", "-r", "--name-only", KNOWLEDGE_BRANCH).split()
    # ONLY the bundle — no client code is carried onto the knowledge branch
    assert sorted(files) == [f"{BUNDLE_DIRNAME}/manifest.yaml", f"{BUNDLE_DIRNAME}/modules.yaml"]
    assert len(_branch_commits(remote, KNOWLEDGE_BRANCH)) == 1


def test_publishing_never_touches_the_product_branch(tmp_path: Path):
    """The whole reason for a dedicated branch: a knowledge commit on `main` would fire the
    client's deploy and put every open PR behind."""
    remote, work = _client_repo(tmp_path)
    before = _git(remote, "rev-parse", "main").strip()
    _refresh(work, remote)
    assert _git(remote, "rev-parse", "main").strip() == before
    assert BUNDLE_DIRNAME not in _git(remote, "ls-tree", "--name-only", "main")


def test_second_pass_over_unchanged_sources_publishes_nothing(tmp_path: Path):
    """Convergence: the refresh is triggered by merges, and its own commit must not look like a
    reason to refresh again. Otherwise the pipeline feeds itself forever."""
    remote, work = _client_repo(tmp_path)
    assert _refresh(work, remote) == "published"
    assert _refresh(work, remote) == "unchanged"
    assert _refresh(work, remote) == "unchanged"
    assert len(_branch_commits(remote, KNOWLEDGE_BRANCH)) == 1


def test_a_real_source_change_publishes_a_second_commit_keeping_history(tmp_path: Path):
    remote, work = _client_repo(tmp_path)
    _refresh(work, remote)

    (work / "core" / "extra.py").write_text("def more():\n    return 2\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: extra")
    _git(work, "push", "-q", "origin", "main")

    assert _refresh(work, remote) == "published"
    commits = _branch_commits(remote, KNOWLEDGE_BRANCH)
    # history ACCUMULATES — "what was the map at commit X?" stays answerable (§22 D-1)
    assert len(commits) == 2
    assert all(c.startswith("chore(knowledge): refresh module map @") for c in commits)


def test_fetched_bundle_is_usable_and_scrubbed(tmp_path: Path):
    """A job consumes the published bundle from OUTSIDE its workspace, and the throwaway
    checkout must not keep a tokened remote on disk."""
    from openfactory.knowledge import is_trustworthy, read_bundle_dir

    remote, work = _client_repo(tmp_path)
    _refresh(work, remote)

    got = fetch_published_bundle(str(remote))
    assert got is not None
    try:
        bundle = read_bundle_dir(got)
        assert bundle is not None
        # it verifies against the product checkout, which has NO knowledge/ dir of its own
        assert not (work / BUNDLE_DIRNAME).exists()
        assert is_trustworthy(bundle, work) is True
        config = (got.parent / ".git" / "config").read_text()
        assert "invalid.local/scrubbed" in config and str(remote) not in config
    finally:
        discard_fetched_bundle(got)


def test_fetch_returns_none_before_anything_is_published(tmp_path: Path):
    remote, _ = _client_repo(tmp_path)
    assert fetch_published_bundle(str(remote)) is None  # first-run: normal, not an error
    assert fetch_published_bundle("") is None


def test_a_publish_lands_on_the_ONE_knowledge_branch(tmp_path: Path):
    """The branch lives in the CLIENT's repository under the product's name, and there is exactly
    one of them: a refresh mints `openfactory-knowledge` and no second knowledge branch beside it."""
    from openfactory.knowledge.pipeline import KNOWLEDGE_BRANCH

    remote, work = _client_repo(tmp_path)
    _refresh(work, remote)

    heads = subprocess.run(["git", "ls-remote", "--heads", str(remote)],
                           capture_output=True, text=True).stdout
    # BY VALUE, not through the constant: the branch is a name the CLIENT sees in their own
    # repository, and a guard that asserts `KNOWLEDGE_BRANCH` against itself pins nothing —
    # a rename to `openfactory-knowledge-2` walked through it (review, 2026-08-25)
    assert KNOWLEDGE_BRANCH == "openfactory-knowledge"
    assert "refs/heads/openfactory-knowledge" in heads, heads
    knowledge_heads = [line for line in heads.splitlines() if "knowledge" in line]
    assert len(knowledge_heads) == 1, f"more than one knowledge branch was minted: {heads}"


def test_stale_published_bundle_is_not_served(tmp_path: Path):
    """The §12 gate still rules: if the tree moved on after the map was published, the map is
    NOT injected — a fail-safe degrade, never a confidently wrong map."""
    from openfactory.knowledge import is_trustworthy, read_bundle_dir

    remote, work = _client_repo(tmp_path)
    _refresh(work, remote)
    (work / "core" / "rules.py").write_text("def decide(x):\n    return x + 99\n")

    got = fetch_published_bundle(str(remote))
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


class _Project:
    def __init__(self, name: str, repo: str, repo_path: str = "/work/does-not-exist") -> None:
        self.name, self.forge, self.tracker = name, _Forge(repo), _Tracker(repo)
        # The registry value: on the WORKER it names no real directory, which is exactly the
        # condition that made the refresh die on its first line. The fake carries it so the test
        # exercises the real shape rather than a friendlier one.
        self.repo_path = repo_path

    def model_copy(self, *, update: dict):
        """The real `Project` is a pydantic model and the activity uses `model_copy` to point the
        manifest loader at the SYNCED checkout. A fake without it hid that call entirely."""
        clone = _Project(self.name, self.forge.repo, self.repo_path)
        for key, value in (update or {}).items():
            setattr(clone, key, value)
        return clone


def _patch_activity(monkeypatch, tmp_path: Path, remote: Path, *, enabled: bool = True,
                    base_branch: str = ""):
    from openfactory.runtime.temporal import activities as acts

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    # THE SEAM THE ACTIVITY ACTUALLY USES. This patched `entrypoint.clone_url`, which the
    # knowledge refresh stopped importing when the clone URL became a forge question — so the
    # patch went inert and the test started cloning for real. A monkeypatch that no longer
    # intercepts anything is a test that silently changed what it exercises.
    from openfactory.adapters.forge import registry as forge_registry

    monkeypatch.setattr(forge_registry, "clone_url_for",
                        lambda project, repo="", *, token=None: str(remote))
    monkeypatch.setattr(acts.ProjectRegistry, "get",
                        lambda self, name: _Project(name, "owner/repo"))

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
    acts = _patch_activity(monkeypatch, tmp_path, remote)
    inp = KnowledgeRefreshInput(project="p", issue="42")

    assert acts._do_refresh_knowledge(inp) == "published"
    # the refresh's OWN commit must not read as a reason to refresh again
    assert acts._do_refresh_knowledge(inp) == "unchanged"
    assert len(_branch_commits(remote, KNOWLEDGE_BRANCH)) == 1

    # a real merge lands new code on main → exactly one more knowledge commit
    (work / "core" / "extra.py").write_text("def more():\n    return 2\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "feat: extra")
    _git(work, "push", "-q", "origin", "main")
    assert acts._do_refresh_knowledge(inp) == "published"
    assert acts._do_refresh_knowledge(inp) == "unchanged"
    assert len(_branch_commits(remote, KNOWLEDGE_BRANCH)) == 2


def test_activity_leaves_no_bundle_in_the_shared_repo_cache(tmp_path: Path, monkeypatch):
    """The cache is what every job's worktree is cut from. A leftover untracked `knowledge/`
    there would be swept into the next ticket's commit by `git add -A`."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _ = _client_repo(tmp_path)
    acts = _patch_activity(monkeypatch, tmp_path, remote)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "published"
    assert not (tmp_path / "cache" / "p" / BUNDLE_DIRNAME).exists()


def test_activity_is_inert_when_the_project_has_not_opted_in(tmp_path: Path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, _ = _client_repo(tmp_path)
    acts = _patch_activity(monkeypatch, tmp_path, remote, enabled=False)
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "off"
    assert _branch_commits(remote, KNOWLEDGE_BRANCH) == []


def test_activity_never_raises_when_the_repo_is_unreachable(tmp_path: Path, monkeypatch):
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    acts = _patch_activity(monkeypatch, tmp_path, tmp_path / "does-not-exist.git")
    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "no-repo"


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


def test_a_rejected_push_is_retried_on_the_new_tip(tmp_path: Path, monkeypatch):
    """Two publishers racing means the loser's map is silently dropped and the project sits on a
    stale map until the next source-changing merge. One re-clone-and-reapply removes that."""
    from openfactory.knowledge import pipeline

    remote, work = _client_repo(tmp_path)
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
    assert pipeline.publish_bundle(work / BUNDLE_DIRNAME, str(remote), source_commit="c") is True
    assert len(pushes) == 2  # rejected once, then landed
    assert len(_branch_commits(remote, KNOWLEDGE_BRANCH)) == 1


def test_activity_preserves_a_bundle_the_client_keeps_committed(tmp_path: Path, monkeypatch):
    """Phase 1's shape is still supported: a project may keep `knowledge/` committed in its own
    repo. The pipeline writes into the shared cache and must restore tracked content afterwards,
    not blindly delete it."""
    from openfactory.runtime.temporal.io import KnowledgeRefreshInput

    remote, work = _client_repo(tmp_path)
    write_bundle(build_bundle(work, commit="c", generated_at="t"), work)
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "chore: commit the bundle in-repo")
    _git(work, "push", "-q", "origin", "main")

    acts = _patch_activity(monkeypatch, tmp_path, remote)
    acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p"))

    cached = tmp_path / "cache" / "p" / BUNDLE_DIRNAME
    assert (cached / "modules.yaml").is_file()  # the TRACKED bundle survived
    status = subprocess.run(["git", "-C", str(tmp_path / "cache" / "p"), "status",
                             "--porcelain", "--", BUNDLE_DIRNAME],
                            capture_output=True, text=True, check=True)
    assert status.stdout.strip() == ""  # and the cache is clean, not left modified


def test_a_job_injects_the_published_map_and_cleans_up_after_itself(tmp_path: Path):
    """The money path, end to end: the pipeline publishes to the client repo, then a JOB fetches
    that bundle and injects it — verified against the job's OWN workspace, with the bundle never
    landing inside the checkout, and the temp download removed afterwards."""
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import Manifest, Ticket
    from openfactory.orchestrator import JobRunner

    remote, work = _client_repo(tmp_path)
    assert _refresh(work, remote) == "published"

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
    assert "### core" in ctx.knowledge_map  # the published map reached the agent
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
    _refresh(work, remote)
    # main moves on AFTER the map was published — once the reason this job got nothing
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
    acts = _patch_activity(monkeypatch, tmp_path, remote)

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
    acts = _patch_activity(monkeypatch, tmp_path, remote, base_branch="release")

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
    acts = _patch_activity(monkeypatch, tmp_path, remote, base_branch="main")

    assert acts._do_refresh_knowledge(KnowledgeRefreshInput(project="p")) == "no-repo"

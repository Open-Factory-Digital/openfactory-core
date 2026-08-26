"""The preflight cloned `main` in order to LEARN which branch is the base (#162).

    # base_branch isn't known until the manifest loads — sync "main" first
    repo_path = RepoCache().sync(cache_key, url, "main")

The comment called it a guess that costs one extra fetch. It is not: `git clone --branch main`
against a repository whose branches are `master`, `develop` or `trunk` names nothing and FAILS.
The preflight then degrades — so every ticket on such a client proceeded UNSIZED, hourly, under a
message about reachability that sent somebody to check the URL and the credential.

AND IT IGNORED WHAT THE REGISTRY ALREADY SAID. `load_manifest_base_branch` exists precisely to
answer this before a checkout exists, and reads `tracker.options["base_branch"]`. This path never
called it, so a deployment that had declared its base branch was still cloned at `main`.

`factory.resolve_repo_path` had the same shape one layer over: it DID call the helper, and the
helper's own fallback was the literal `main`, so a URL-registered `master` project could not be
fetched at all.

The fix is one sentence in three places: ask, and when nobody has said, let the clone land where
the repository points. These tests use real `git`, because the defect is a git argument.
"""

from __future__ import annotations

import subprocess
import types

import pytest

from openfactory.runtime.repo_cache import _MASTERS_DIRNAME, RepoCache, current_branch


def _repo(tmp_path, branch: str):
    """A real repository whose default branch is `branch` — the whole point is the git argument."""
    at = tmp_path / f"origin-{branch}"
    at.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(at), *a], check=True,  # noqa: E731
                                    capture_output=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(at)], check=True, capture_output=True)
    (at / "a.txt").write_text("hi\n")
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return str(at)


# ── 1. the cache can be asked for a repository, not a branch ────────────────────────────────────

def test_asking_for_MAIN_on_a_master_repository_fails(tmp_path):
    """The defect, reproduced. Kept as a guard because it is what the caller used to do and the
    reason the failure read as unreachability."""
    cache = RepoCache(root=tmp_path / "cache")

    assert cache.sync("p", _repo(tmp_path, "master"), "main") is None


@pytest.mark.parametrize("branch", ["master", "develop", "trunk", "main"])
def test_asking_for_NOTHING_lands_where_the_repository_points(tmp_path, branch):
    cache = RepoCache(root=tmp_path / "cache")

    got = cache.sync("p", _repo(tmp_path, branch), "")

    assert got is not None, f"a {branch!r} repository could not be fetched"
    assert current_branch(got) == branch


def test_a_second_unnamed_sync_KEEPS_the_branch_it_is_on(tmp_path):
    """`_reset` needs a name for its refspec, so an unnamed sync of an existing checkout resolves
    it from the tree rather than recloning — otherwise every routine sync would throw the master
    away and clone again, which is the expensive rung of the degrade ladder run on the happy path.
    """
    cache = RepoCache(root=tmp_path / "cache")
    url = _repo(tmp_path, "develop")
    first = cache.sync("p", url, "")
    marker = (tmp_path / "cache" / _MASTERS_DIRNAME / "p" / ".git" / "openfactory-probe")
    marker.write_text("i survived")

    again = cache.sync("p", url, "")

    assert again == first and current_branch(again) == "develop"
    assert marker.exists(), "the master was recloned — an unnamed sync must not throw it away"


def test_a_named_branch_still_wins(tmp_path):
    """The reverse: `""` must mean "nobody said", never "ignore what the caller asked for"."""
    cache = RepoCache(root=tmp_path / "cache")
    url = _repo(tmp_path, "master")
    subprocess.run(["git", "-C", url, "branch", "release"], check=True, capture_output=True)

    got = cache.sync("p", url, "release")

    assert current_branch(got) == "release"


def test_a_detached_head_reads_as_UNKNOWN_not_as_a_branch_called_HEAD(tmp_path):
    """git prints the literal `HEAD` for a detached checkout. Returning it builds the refspec
    `refs/heads/HEAD`, which fetches nothing and resets to nothing."""
    at = _repo(tmp_path, "master")
    subprocess.run(["git", "-C", at, "checkout", "-q", "--detach"], check=True, capture_output=True)

    assert current_branch(at) == ""


@pytest.mark.parametrize("path", ["nowhere", "empty"])
def test_a_tree_that_is_not_a_checkout_reads_as_unknown(tmp_path, path):
    (tmp_path / "empty").mkdir()

    assert current_branch(tmp_path / path) == ""


# ── 2. the registry is asked before anything is assumed ─────────────────────────────────────────

def test_the_helper_reports_that_NOBODY_SAID(tmp_path):
    from openfactory.loader import load_manifest_base_branch

    quiet = types.SimpleNamespace(tracker=types.SimpleNamespace(options={}))

    assert load_manifest_base_branch(quiet, default="") == ""
    assert load_manifest_base_branch(quiet) == "main", "the old callers' answer changed"


def test_and_a_declared_base_branch_is_returned_whatever_the_default():
    from openfactory.loader import load_manifest_base_branch

    declared = types.SimpleNamespace(tracker=types.SimpleNamespace(
        options={"base_branch": "develop"}))

    assert load_manifest_base_branch(declared, default="") == "develop"


def test_the_preflight_ASKS_the_registry(monkeypatch):
    """Reachability: the guards above prove the helper, and the preflight never called it. Driven
    by watching what reaches `RepoCache.sync`."""
    import ast
    import inspect

    from openfactory.runtime.temporal import activities

    src = inspect.cleandoc("\n" + inspect.getsource(activities._do_preflight))
    called = {getattr(n.func, "id", "") for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call)}

    assert "load_manifest_base_branch" in called, (
        "the preflight still decides the base branch on its own")


def test_the_repo_fetch_asks_for_the_repositorys_own_default(monkeypatch):
    """`factory.resolve_repo_path` DID call the helper — and the helper answered `main`, so the
    guess merely moved one function away."""
    import openfactory.loader as loader
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime import repo_cache

    seen: list = []
    monkeypatch.setattr(loader, "load_manifest_base_branch",
                        lambda p, *, default="main": seen.append(default) or "")
    monkeypatch.setattr(repo_cache.RepoCache, "sync",
                        lambda self, key, url, branch: seen.append(("branch", branch)) or None)
    monkeypatch.setattr("openfactory.factory._authenticated", lambda p, u, t: u)

    from openfactory.factory import resolve_repo_path

    with pytest.raises(RuntimeError):
        resolve_repo_path(Project(name="p", repo_path="https://github.com/o/r.git",
                                  tracker=ProviderRef(kind="github", repo="o/r"),
                                  forge=ProviderRef(kind="github", repo="o/r")),
                          token="tok")

    assert seen == ["", ("branch", "")], seen


def test_the_RESYNC_lands_on_the_base_the_manifest_names(tmp_path, monkeypatch):
    """Survivor of the first mutation round, and the case where the comparison changes an answer.

    The registry names `release`, so the first sync lands there; the manifest inside that tree
    says the base is `main`. Comparing against the literal `main` — which is what this did — makes
    `manifest.base_branch != "main"` FALSE, so no re-sync happens and the sizing reads the
    `release` tree while believing it read the base. Comparing against what we actually landed on
    is the only version that can tell.
    """
    from openfactory.contracts import AcceptanceCriterion, Ticket
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime import repo_cache
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import PreflightInput

    origin = _repo(tmp_path, "main")
    subprocess.run(["git", "-C", origin, "branch", "release"], check=True, capture_output=True)

    asked: list[str] = []
    real = repo_cache.RepoCache.sync

    def _spy(self, key, url, branch="main"):
        asked.append(branch)
        return real(self, key, url, branch)

    monkeypatch.setattr(repo_cache.RepoCache, "sync", _spy)
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(acts, "_tracker_for", lambda project: _Tracker(Ticket(
        id="#37", title="a ticket", repo="o/app", objective="x",
        acceptance_criteria=[AcceptanceCriterion(text="c")])))
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: Project(
        name="books", repo_path="/nowhere",
        tracker=ProviderRef(kind="github", repo="o/app", options={"base_branch": "release"})))
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: str(origin))
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: None)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: None)
    # THE REAL MANIFEST MODEL, not a namespace: the round reads a dozen fields after this point
    # and a stand-in would fail on whichever one it forgot — which says nothing about branches.
    from openfactory.contracts.manifest import Manifest

    manifest = Manifest(base_branch="main")
    manifest.preflight.enabled = True
    monkeypatch.setattr("openfactory.loader.load_manifest", lambda project, **kw: manifest)

    acts._do_preflight(PreflightInput(project="books", issue="37"))

    assert asked[0] == "release", "the registry's declared base was not asked for first"
    assert asked[-1] == "main", (
        f"the sizing read the {asked[-1]!r} tree while the manifest says the base is 'main'")


class _Tracker:
    def __init__(self, ticket):
        self._ticket, self.comments = ticket, []

    def get_ticket(self, ref):
        return self._ticket

    def comment(self, ref, body):
        self.comments.append((ref, body))


# ── 3. one home for the git question ────────────────────────────────────────────────────────────

def test_onboardings_helper_reads_through_the_same_one(tmp_path):
    """Two copies of "which branch is this checkout on" existed and answered differently — one
    fell back to `main`, which is right for a manifest proposal and wrong for a cache. The reading
    has one home now; the fallback lives at the caller that needs it."""
    from openfactory.onboarding.propose_manifest import default_branch

    at = _repo(tmp_path, "develop")

    assert default_branch(at) == "develop"
    assert default_branch(tmp_path / "nowhere") == "main", (
        "a proposal has to name a branch, so this caller's unknown is still `main`")


def test_and_it_does_not_ask_git_ITSELF():
    import inspect

    from conftest import code_only

    from openfactory.onboarding import propose_manifest

    body = code_only(inspect.getsource(propose_manifest.default_branch))

    assert "rev-parse" not in body, "the second copy of the git question grew back"

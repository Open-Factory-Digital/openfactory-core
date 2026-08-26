"""The card named one `main`; there were five (#162, `product/module.py:767`).

`_source_checkout` synced the client's SOURCE repository at the literal `main`, and its failure is
silent by contract: the product role is told it cannot open the code and answers documentation-only
for ever. On a `master` or `develop` client that is not a degraded answer once, it is every answer.

The sweep found four more of the same shape, one of them under a comment that already knew:

    # This is the SAME bug `_do_preflight` above already carries a comment about. It was fixed
    # there and repeated here.
    repo_path = RepoCache().sync(project.name, url, "main")

— the knowledge refresh, which the comment says "died on its first line every time, silently".
The repetition included the `main`.

And `baseline()` did it twice over: it synced at `main` AND handed the judging workspace
`branch="main", base_branch="main"` regardless of what the checkout actually was, so on a `master`
client every judgement it produced described its branch by a name that does not exist there.

`docs_branch` is deliberately NOT in this sweep. It is a declared field on `ProductConfig` with a
documented default, which a client changes — the question here is the one nobody can answer in
advance, on repositories the platform did not create.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
from pathlib import Path

import pytest

from openfactory.runtime.repo_cache import current_branch


def _repo(tmp_path, branch: str) -> str:
    at = tmp_path / f"origin-{branch}"
    at.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch, str(at)], check=True, capture_output=True)
    (at / "app.py").write_text("x = 1\n")
    for args in (["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"]):
        subprocess.run(["git", "-C", str(at), *args], check=True, capture_output=True)
    return str(at)


def _project(base: str | None = None):
    from openfactory.contracts.project import Project, ProviderRef

    options = {"base_branch": base} if base else {}
    return Project(name="books", repo_path="/nowhere",
                   tracker=ProviderRef(kind="github", repo="o/app", options=options),
                   forge=ProviderRef(kind="github", repo="o/app"))


# ── 1. the product role can open a `master` client's code ───────────────────────────────────────

@pytest.fixture()
def module(tmp_path, monkeypatch):
    from openfactory.product.module import ProductModule

    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    mod = ProductModule.__new__(ProductModule)
    mod.project = _project()
    return mod


@pytest.mark.parametrize("branch", ["master", "develop", "main"])
def test_the_source_checkout_lands_on_the_repositorys_own_branch(module, tmp_path, monkeypatch,
                                                                 branch):
    """The card's site. A silent None here is the role answering documentation-only for ever."""
    url = _repo(tmp_path, branch)
    monkeypatch.setattr(type(module), "_source_repo", lambda self: "o/app")
    monkeypatch.setattr(type(module), "_clone_url", lambda self, repo: url)

    got = module._source_checkout()

    assert got is not None, f"a {branch!r} client's code could not be checked out at all"
    assert current_branch(got) == branch


def test_and_a_DECLARED_base_branch_still_wins(module, tmp_path, monkeypatch):
    """`""` means "nobody said", never "ignore the registry"."""
    url = _repo(tmp_path, "master")
    subprocess.run(["git", "-C", url, "branch", "release"], check=True, capture_output=True)
    module.project = _project(base="release")
    monkeypatch.setattr(type(module), "_source_repo", lambda self: "o/app")
    monkeypatch.setattr(type(module), "_clone_url", lambda self, repo: url)

    assert current_branch(module._source_checkout()) == "release"


# ── 2. the baseline tells the workspace the truth ───────────────────────────────────────────────

def test_the_baseline_workspace_names_the_branch_it_actually_has(module, tmp_path, monkeypatch):
    """Both fields said `main` whatever the checkout was — so a judgement made on a `master`
    client described its own branch by a name that does not exist there."""
    url = _repo(tmp_path, "develop")
    monkeypatch.setattr(type(module), "_source_repo", lambda self: "o/app")
    monkeypatch.setattr(type(module), "_clone_url", lambda self, repo: url)
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.judging_worktree",
                        lambda project, root=None: object())

    _judge, workspace = module._source_workspace()

    assert workspace.branch == "develop" and workspace.base_branch == "develop"


def test_and_an_unreadable_checkout_still_names_SOMETHING(module, monkeypatch, tmp_path):
    """`Workspace.branch` is not optional. `current_branch` answers `""` for a detached or corrupt
    tree, and an empty branch name downstream is a git argument that names nothing — the very
    failure this card is about, one layer along."""
    from openfactory.runtime import repo_cache

    monkeypatch.setattr(type(module), "_source_repo", lambda self: "o/app")
    monkeypatch.setattr(type(module), "_clone_url", lambda self, repo: "url")
    monkeypatch.setattr(repo_cache.RepoCache, "sync", lambda *a, **k: tmp_path)
    monkeypatch.setattr("openfactory.runtime.repo_cache.current_branch", lambda p: "")
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.judging_worktree",
                        lambda project, root=None: object())

    _judge, workspace = module._source_workspace()

    assert workspace.branch == "main", "the workspace was handed an empty branch name"


def test_the_baseline_obeys_a_DECLARED_base_branch_too(module, tmp_path, monkeypatch):
    """`_source_checkout` had both directions covered and `_source_workspace` only the unnamed one,
    so its `load_manifest_base_branch` call could have been `""` and nothing would have said."""
    url = _repo(tmp_path, "master")
    subprocess.run(["git", "-C", url, "branch", "release"], check=True, capture_output=True)
    module.project = _project(base="release")
    monkeypatch.setattr(type(module), "_source_repo", lambda self: "o/app")
    monkeypatch.setattr(type(module), "_clone_url", lambda self, repo: url)
    monkeypatch.setattr("openfactory.adapters.sandbox.registry.judging_worktree",
                        lambda project, root=None: object())

    _judge, workspace = module._source_workspace()

    assert workspace.branch == "release" and workspace.base_branch == "release"


# ── 3. the copy that already knew it was a copy ─────────────────────────────────────────────────

# The knowledge refresh's own guard is BEHAVIOURAL and lives with its harness —
# `tests/test_knowledge_pipeline.py::test_the_refresh_publishes_for_a_client_whose_default_is_not_main`
# drives `_do_refresh_knowledge` against a real bare `master` remote. A source-text assertion stood
# here first ("`main` is not spelled in this function"), and it was GREEN over the live failure:
# the function had stopped saying `main` and the re-sync two lines below re-introduced it from
# `manifest.base_branch`'s schema default. Behaviour was available and already wired.


# ── 4. the ratchet ─────────────────────────────────────────────────────────────────────────────

def _sync_calls(root: Path | None = None) -> list[tuple[str, int, ast.AST | None]]:
    """Every `.sync(…)` in the package, with the branch argument each one passes.

    ONE WALK, USED BY BOTH GUARDS BELOW. They had a walk each, so neutering the one that looks for
    offenders left the one that counts them green — a mutation caught exactly that, and it is the
    same reachability hole the offender list exists to close.
    """
    package = root or Path(inspect.getfile(current_branch)).parent.parent
    out: list[tuple[str, int, ast.AST | None]] = []
    for path in sorted(package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "sync"):
                continue
            branch = node.args[2] if len(node.args) > 2 else next(
                (k.value for k in node.keywords if k.arg == "base_branch"), None)
            out.append((str(path.relative_to(package.parent)), node.lineno, branch))
    return out


def test_no_checkout_in_the_package_ASSUMES_a_branch_name():
    """The ratchet. This class has now been repeated five times across three modules, once under a
    comment naming itself as a repeat — so the guard is not "the sites I fixed stay fixed", it is
    that a NEW one fails the suite.

    Read by AST, so the sentences above explaining the rule cannot satisfy or break it."""
    offenders = [f"{where}:{line} — {node.value!r}" for where, line, node in _sync_calls()
                 if isinstance(node, ast.Constant) and node.value]

    assert not offenders, (
        "a checkout names a branch nobody declared — pass the registry's base "
        "(`load_manifest_base_branch(project, default='')`) and let an unnamed one land where the "
        f"repository points: {offenders}")


def test_the_ratchet_walks_the_sites_it_claims_to():
    """A rglob that matched nothing would report no offenders either. The count is a floor: new
    call sites are fine, zero is the walk having stopped working."""
    seen = _sync_calls()

    assert len(seen) >= 6, f"the ratchet walked {len(seen)} sync calls — it is measuring nothing"
    assert any("product/module.py" in where for where, _l, _n in seen), (
        "the module this card is about is not in the walk at all")


def test_and_the_ratchet_can_SEE_one(tmp_path):
    """Verify the verifier — through `_sync_calls` ITSELF, not a re-implementation of its predicate.

    The first version of this parsed its own snippet and re-wrote the `.sync`/`args[2]` match
    inline. That proves the inline copy and nothing about the walk the other guard depends on: the
    argument extraction could be neutered entirely and this would stay green. Adversarial review
    caught it, 2026-08-20."""
    (tmp_path / "offender.py").write_text(
        'RepoCache().sync("k", url, "main")\n'
        'RepoCache().sync("k", url, resolved)\n'
        'RepoCache().sync("k", url, base_branch="develop")\n')

    found = _sync_calls(tmp_path)
    offenders = [(line, node.value) for _w, line, node in found
                 if isinstance(node, ast.Constant) and node.value]

    assert len(found) == 3, f"the walk missed a `.sync(` call: {found}"
    assert offenders == [(1, "main"), (3, "develop")], (
        f"the ratchet cannot see the shape it exists to reject: {offenders}")


# ── 5. what the adversarial review measured (2026-08-20) ────────────────────────────────────────
#
# Five lenses converged on one root cause: a pydantic DEFAULT read as a client's declaration. The
# fix above resolved the right branch and then a re-sync two lines later undid it.

def test_a_manifest_that_says_nothing_DECLARES_nothing():
    from openfactory.contracts import Manifest

    assert Manifest(version=1, setup=[]).declared_base_branch == ""
    assert Manifest(version=1, setup=[]).base_branch == "main", (
        "the schema default moved — the collapse this guards is gone or somewhere else now")


def test_and_a_manifest_that_DOES_declare_one_is_heard():
    from openfactory.contracts import Manifest

    assert Manifest(version=1, base_branch="master").declared_base_branch == "master"
    assert Manifest(version=1, base_branch="main").declared_base_branch == "main", (
        "a client who deliberately typed `main` is indistinguishable from one who typed nothing")


def test_the_same_question_on_the_product_contract():
    from openfactory.contracts.product import ProductConfig

    assert ProductConfig(docs_repo="o/d").declared_docs_branch == ""
    assert ProductConfig(docs_repo="o/d", docs_branch="master").declared_docs_branch == "master"


def test_the_PREFLIGHT_does_not_degrade_a_master_client_whose_manifest_is_silent(
        tmp_path, monkeypatch):
    """The sibling that shipped one commit earlier and is already deployed. It resolved `master`
    correctly and then re-cloned at `manifest.base_branch` — the schema default — which names
    nothing there, so the cache was deleted and EVERY ticket degraded unsized, hourly, with a
    message naming a branch the client does not have."""
    from openfactory.contracts import AcceptanceCriterion, Manifest, Ticket
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.runtime import repo_cache
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import PreflightInput

    origin = _repo(tmp_path, "master")
    asked: list[str] = []
    real = repo_cache.RepoCache.sync

    def _spy(self, key, url, branch=""):
        asked.append(branch)
        return real(self, key, url, branch)

    monkeypatch.setattr(repo_cache.RepoCache, "sync", _spy)
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(acts, "_tracker_for", lambda project: _Tracker(Ticket(
        id="#37", title="a ticket", repo="o/app", objective="x",
        acceptance_criteria=[AcceptanceCriterion(text="c")])))
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: Project(
        name="books", repo_path="/nowhere",
        tracker=ProviderRef(kind="github", repo="o/app")))
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda project, repo="", *, token=None: origin)
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: None)
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: None)
    silent = Manifest(version=1)            # NO base_branch — the shape a client actually ships
    silent.preflight.enabled = True
    monkeypatch.setattr("openfactory.loader.load_manifest", lambda project, **kw: silent)

    verdict = acts._do_preflight(PreflightInput(project="books", issue="37"))

    assert asked == [""], f"the preflight re-cloned at {asked[1:]!r} — nobody asked for that"
    assert (verdict.degraded or "").startswith("clone:") is False, (
        f"a `master` client degraded: {verdict.degraded!r}")


class _Tracker:
    def __init__(self, ticket):
        self._ticket, self.comments = ticket, []

    def get_ticket(self, ref):
        return self._ticket

    def comment(self, ref, body):
        self.comments.append((ref, body))


# ── the cache asks the remote, and survives one that will not answer ────────────────────────────

def test_the_remote_default_is_read_from_the_SYMREF_line(tmp_path):
    from openfactory.runtime.repo_cache import remote_default_branch

    assert remote_default_branch(_repo(tmp_path, "develop")) == "develop"


def test_and_a_remote_nobody_can_reach_answers_NOTHING(tmp_path):
    """`""`, never a raise: an unreachable remote must not become the reason a working checkout is
    thrown away."""
    from openfactory.runtime.repo_cache import remote_default_branch

    assert remote_default_branch(str(tmp_path / "does-not-exist")) == ""


def test_an_unreachable_remote_KEEPS_the_checkout_it_already_has(tmp_path, monkeypatch):
    from openfactory.runtime import repo_cache

    url = _repo(tmp_path, "develop")
    cache = repo_cache.RepoCache(root=tmp_path / "cache")
    first = cache.sync("p", url, "")
    assert current_branch(first) == "develop"

    monkeypatch.setattr(repo_cache, "remote_default_branch", lambda u: "")

    again = cache.sync("p", url, "")

    assert again == first and current_branch(again) == "develop", (
        "a remote that would not answer cost the worker its working checkout")


def test_a_remote_that_will_not_say_costs_a_FETCH_not_a_RECLONE(tmp_path, monkeypatch):
    """The fallback's real job, and it is about cost. Some hosts and older gits do not answer
    `ls-remote --symref`; the repository is perfectly reachable, only its opinion is not. Without
    the tree as a fallback `wanted` is empty, the master is judged unusable and `rmtree`d, and the
    whole repository is cloned again — on EVERY sync, for ever, on a path the preflight runs per
    ticket. The answer is identical; the bill is not."""
    from openfactory.runtime import repo_cache

    url = _repo(tmp_path, "develop")
    cache = repo_cache.RepoCache(root=tmp_path / "cache")
    cache.sync("p", url, "")
    master = tmp_path / "cache" / repo_cache._MASTERS_DIRNAME / "p"
    marker = master / ".git" / "openfactory-probe"
    marker.write_text("i survived")
    monkeypatch.setattr(repo_cache, "remote_default_branch", lambda u: "")

    again = cache.sync("p", url, "")

    assert current_branch(again) == "develop"
    assert marker.exists(), (
        "a remote that would not name its default cost a full reclone of the client's repository")


def test_a_cached_branch_DELETED_UPSTREAM_does_not_pin_the_reclone(tmp_path, monkeypatch):
    """The reclone took its branch name from the checkout it had just deleted. That is only
    visible when the inferred name is one the remote no longer has — a branch cached while it
    existed and removed upstream since, with the symref unreadable so the tree is the only
    fallback. The clone then fails on a name NOBODY asked for, and the caller's own answer
    ("nothing, let it land where the repository points") is discarded."""
    from openfactory.runtime import repo_cache

    url = _repo(tmp_path, "master")
    subprocess.run(["git", "-C", url, "branch", "feature"], check=True, capture_output=True)
    cache = repo_cache.RepoCache(root=tmp_path / "cache")
    assert current_branch(cache.sync("p", url, "feature")) == "feature"

    # master MOVES, so the served tree is genuinely stale — otherwise both branches point at the
    # same commit, nothing needs republishing, and the guard reads the old tree's branch name.
    subprocess.run(["git", "-C", url, "commit", "-q", "--allow-empty", "-m", "on master"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", url, "branch", "-D", "feature"], check=True, capture_output=True)
    monkeypatch.setattr(repo_cache, "remote_default_branch", lambda u: "")
    # THE RECLONE RUNG, forced by making the reset fail — which is what a fetch for a branch
    # neither side has any longer does. `_reset` is a neighbour of the line under test, not the
    # line itself: what this measures is which name the CLONE below it uses.
    master = tmp_path / "cache" / repo_cache._MASTERS_DIRNAME / "p"
    assert current_branch(master) == "feature", "the fixture stopped reproducing the inference"
    monkeypatch.setattr(repo_cache.RepoCache, "_reset", staticmethod(lambda *a, **k: False))

    got = cache.sync("p", url, "")

    assert got is not None, "the reclone asked for a branch the remote does not have"
    assert current_branch(got) == "master"


def test_a_CORRUPT_master_is_recloned_on_the_repositorys_own_default(tmp_path):
    """The reclone used the name inferred from the tree it had just deleted — a name nobody asked
    for, from a checkout already judged unusable."""
    from openfactory.runtime.repo_cache import _MASTERS_DIRNAME, RepoCache

    url = _repo(tmp_path, "master")
    cache = RepoCache(root=tmp_path / "cache")
    cache.sync("p", url, "")
    master = tmp_path / "cache" / _MASTERS_DIRNAME / "p"
    (master / ".git" / "HEAD").write_text("this is not a git head\n")

    got = cache.sync("p", url, "")

    assert got is not None and current_branch(got) == "master"

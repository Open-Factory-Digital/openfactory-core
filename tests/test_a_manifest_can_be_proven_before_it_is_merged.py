"""#112: the manifest is born in a pull request, and `box prove` could only read the base branch.

`onboard` is the only door that writes a manifest for a REMOTE repository — the other two forms
need a local checkout, which a deployment that clones for itself does not have. So the first
manifest a deployment ever owns is, by construction, on a branch; and a proof that reads only the
base branch cannot see it until the instant it is already merged, which is the instant the
question stops being useful.

The pull request `onboard` opens ends with *"Correct anything wrong and merge"*. Measured
2026-09-12 on a real client repository: the correction needed a `setup:` block that did not exist,
two new `validate:` entries and one proposed entry dropped — and none of it was measurable through
the product. It was measured by rebuilding the box by hand.

THE HALF THAT MUST NOT MOVE. A proof is what the poller consults before it picks a card up, and
that gate is a fact about the BASE branch. A branch proof recorded there would unlock work against
a manifest nobody merged — so `--ref` measures and never records, and the verdict says so in the
word it uses.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess

import pytest
from typer.testing import CliRunner

from openfactory.box_prove import Finding, Proof
from openfactory.cli import app

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Probes:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _deployment(tmp_path, monkeypatch, *, ok: bool = True):
    """A registered project, a stubbed box, and a record of what the command asked for."""
    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"demo": {
        "name": "demo", "repo": "acme/demo",
        "repo_path": "https://github.com/acme/demo.git"}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")

    import openfactory.box_prove as bp
    import openfactory.cli as cli
    import openfactory.factory as factory
    import openfactory.loader as loader

    seen: dict = {"resolved": [], "saved": []}

    monkeypatch.setattr(cli, "resolve_box_image", lambda *a, **k: "img:1")
    monkeypatch.setattr(bp, "box_probes", lambda *a, **k: _Probes())
    monkeypatch.setattr(bp, "prove", lambda *a, **k: Proof(
        project="demo", image="img:1", ok=ok,
        findings=[Finding("validate", ok, "4 gate(s) green" if ok else "test: exited 1",
                          "" if ok else "fix it")]))
    monkeypatch.setattr(bp, "save", lambda proof, **k: seen["saved"].append(proof)
                        or (tmp_path / "demo.json"))

    def fake_resolve(project, *, token=None, cache_key=None, ref=""):
        seen["resolved"].append({"cache_key": cache_key, "ref": ref})
        return tmp_path / "checkout"

    monkeypatch.setattr(factory, "resolve_repo_path", fake_resolve)
    monkeypatch.setattr(loader, "load_manifest", lambda *a, **k: object())
    return seen


# ── the ref is read, under a key of its own ─────────────────────────────────────────────────────

def test_a_ref_is_proven_against_that_ref(tmp_path, monkeypatch):
    seen = _deployment(tmp_path, monkeypatch)

    CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "openfactory/onboard"])

    assert seen["resolved"], "the command never resolved a checkout for the ref"
    assert seen["resolved"][0]["ref"] == "openfactory/onboard"


def test_a_ref_does_not_replace_the_base_branchs_checkout(tmp_path, monkeypatch):
    """Syncing a branch under the project's default key would REPLACE the base branch's checkout
    with it — the same hole this closes, entered from the other side, and the next proof would
    then measure a branch while reporting the base branch."""
    seen = _deployment(tmp_path, monkeypatch)

    CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "feat/x"])

    key = seen["resolved"][0]["cache_key"]
    assert key and key != "demo", "the ref shares the base branch's checkout key"
    assert "feat" in key and "x" in key, "the key does not distinguish WHICH ref it holds"


def test_a_ref_with_a_slash_or_a_slash_free_name_both_make_a_usable_key(tmp_path, monkeypatch):
    """Refs carry `/`, and a cache key becomes a directory name."""
    seen = _deployment(tmp_path, monkeypatch)

    CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "release/1.2"])

    key = seen["resolved"][0]["cache_key"]
    assert "/" not in key.split("@", 1)[1], "the ref's slash reached the directory name"


# ── measured, never recorded ────────────────────────────────────────────────────────────────────

def test_a_ref_proof_is_never_recorded(tmp_path, monkeypatch):
    """The gate that holds pickup is a fact about the base branch. A branch recorded there would
    unlock work against a manifest nobody merged."""
    seen = _deployment(tmp_path, monkeypatch, ok=True)

    CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "openfactory/onboard"])

    assert seen["saved"] == [], "a branch proof was written where the poller looks"


def test_a_base_branch_proof_still_records(tmp_path, monkeypatch):
    """The positive twin: a change that stopped recording always would silently hold every
    pickup on every deployment."""
    seen = _deployment(tmp_path, monkeypatch, ok=True)

    CliRunner().invoke(app, ["box", "prove", "demo"])

    assert len(seen["saved"]) == 1, "the ordinary proof stopped being recorded"


def test_the_verdict_says_it_is_a_measurement_and_which_ref(tmp_path, monkeypatch):
    _deployment(tmp_path, monkeypatch, ok=True)

    out = CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "openfactory/onboard"]).output

    assert "WOULD PROVE" in out
    assert "PROVEN —" not in out, "a measurement must not read as the recorded verdict"
    assert "openfactory/onboard" in out
    assert "Nothing was recorded" in out and "merging" in out


def test_a_failing_ref_says_WOULD_NOT_and_exits_nonzero(tmp_path, monkeypatch):
    """A script that proposes a manifest wants the exit code, not the prose."""
    _deployment(tmp_path, monkeypatch, ok=False)

    result = CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "feat/x"])

    assert result.exit_code == 1
    assert "WOULD NOT PROVE" in result.output


def test_a_passing_ref_exits_zero(tmp_path, monkeypatch):
    _deployment(tmp_path, monkeypatch, ok=True)

    assert CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "feat/x"]).exit_code == 0


def test_a_ref_that_cannot_be_read_refuses_by_name(tmp_path, monkeypatch):
    """`openfactory doctor` is the bar: the cause, and what to check — never a traceback."""
    _deployment(tmp_path, monkeypatch)
    import openfactory.factory as factory

    def boom(*a, **k):
        raise RuntimeError("couldn't find remote ref feat/typo")

    monkeypatch.setattr(factory, "resolve_repo_path", boom)
    result = CliRunner().invoke(app, ["box", "prove", "demo", "--ref", "feat/typo"])

    assert result.exit_code == 2
    assert "could not read" in result.output and "feat/typo" in result.output
    assert "Traceback" not in result.output


# ── the seam below the command ──────────────────────────────────────────────────────────────────

def test_resolve_repo_path_syncs_the_ref_when_given_one_and_the_base_branch_otherwise(monkeypatch):
    """Read at the seam rather than through the command, because this is the line that decides
    WHICH code the proof measures."""
    import openfactory.factory as factory
    from openfactory.registry import Project

    synced: list[tuple] = []

    class _Cache:
        def sync(self, key, url, branch=""):
            synced.append((key, branch))
            return pathlib.Path("/tmp/checkout")

    monkeypatch.setattr("openfactory.runtime.repo_cache.RepoCache", lambda *a, **k: _Cache())
    monkeypatch.setattr(factory, "load_manifest_base_branch", lambda *a, **k: "main", raising=False)
    monkeypatch.setattr("openfactory.loader.load_manifest_base_branch", lambda *a, **k: "main")
    project = Project(name="demo", repo_path="https://github.com/acme/demo.git")

    factory.resolve_repo_path(project, token="t", cache_key="demo", ref="feat/x")
    factory.resolve_repo_path(project, token="t", cache_key="demo")

    assert synced[0][1] == "feat/x", "the ref was not synced"
    assert synced[1][1] == "main", "the base branch path changed"


def test_the_command_cannot_record_a_ref_proof(monkeypatch):
    """Reachability, by AST — the sibling guard's technique, for the same reason: the helper
    being right is worth nothing if the command can still reach `save` with a ref in hand."""
    tree = ast.parse((ROOT / "openfactory" / "cli.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "box_prove_cmd")
    saves = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "save"]

    assert len(saves) == 1, f"`save` is reached {len(saves)} times; each one needs the ref guard"
    guarded = ast.unparse(next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                               and any(getattr(t, "id", "") == "where" for t in n.targets)))
    assert "if ref" in guarded or "if not ref" in guarded, (
        f"`where` is assigned without consulting the ref: {guarded}"
    )


# ── the shape the one-machine door creates: a project registered by PATH ────────────────────────
#
# Review of #119: `resolve_repo_path` returned the working tree before it could use the ref, so a
# `--ref` run on a local project proved whatever branch happened to be checked out and then said
# it had measured the branch. Confidently wrong about the single fact the flag exists to
# establish — #113's defect, one command over. Every fixture above registers a clone URL, which is
# exactly why the guards could not see it.

def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _repo_with_a_branch(tmp_path):
    """A repository on `main`, and `a-branch` carrying one gate `main` does not have."""
    repo = tmp_path / "myapp"
    (repo / ".openfactory").mkdir(parents=True)
    _git(["init", "-q", "."], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    manifest = repo / ".openfactory" / "project.yaml"
    manifest.write_text('version: 1\nbase_branch: main\nvalidate:\n  test: "pytest -q"\n')
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "main"], repo)
    _git(["branch", "-M", "main"], repo)
    _git(["checkout", "-q", "-b", "a-branch"], repo)
    manifest.write_text('version: 1\nbase_branch: main\nvalidate:\n  test: "pytest -q"\n'
                        '  branch_only: "echo yes"\n')
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "branch"], repo)
    _git(["checkout", "-q", "main"], repo)
    return repo


def _local_project(repo):
    from openfactory.registry import Project

    return Project(name="myapp", repo_path=str(repo))


def test_a_ref_on_a_locally_registered_project_measures_THAT_ref(tmp_path, monkeypatch):
    """The defect this section exists for. `openfactory project init myapp <path>` registers a
    path, and that door is the centre of the product — so this is the common shape, not an edge."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path
    from openfactory.loader import load_manifest

    repo = _repo_with_a_branch(tmp_path)
    project = _local_project(repo)

    on_ref = load_manifest(project, repo_root=resolve_repo_path(
        project, cache_key="myapp@a-branch", ref="a-branch"))
    on_tree = load_manifest(project, repo_root=resolve_repo_path(project, cache_key="myapp"))

    assert "branch_only" in on_ref.validation, (
        "the branch's own gate was not measured — the ref was ignored and the working tree read"
    )
    assert "branch_only" not in on_tree.validation, "the no-ref path stopped reading the tree"


def test_measuring_a_ref_does_not_disturb_the_tree_somebody_is_standing_in(tmp_path, monkeypatch):
    """The repository this reads may be a developer's own working copy, with their uncommitted
    work in it. `git worktree` is chosen over a checkout for exactly this."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path

    repo = _repo_with_a_branch(tmp_path)
    (repo / "uncommitted.txt").write_text("a person's work in progress")

    resolve_repo_path(_local_project(repo), cache_key="myapp@a-branch", ref="a-branch")

    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip() == "main"
    assert (repo / "uncommitted.txt").read_text() == "a person's work in progress"


def test_the_second_checkout_lives_outside_the_repository(tmp_path, monkeypatch):
    """Inside it, the proof would measure its own scratch directory as part of the project — and
    `RepoCache.sync` owns `root/<project>` and replaces it by atomic swap, so the worktree keeps
    its own prefix rather than sitting in a namespace something else may discard."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path

    repo = _repo_with_a_branch(tmp_path)
    where = resolve_repo_path(_local_project(repo), cache_key="myapp@a-branch", ref="a-branch")

    assert repo not in where.parents and where != repo
    assert "worktrees" in where.parts


def test_measuring_the_same_ref_twice_is_not_an_error(tmp_path, monkeypatch):
    """A stale worktree from the previous measurement is registered with git, and `add` refuses a
    path it still believes in — so a second run on one branch used to be the common failure."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path
    from openfactory.loader import load_manifest

    repo = _repo_with_a_branch(tmp_path)
    project = _local_project(repo)
    for _ in range(2):
        root = resolve_repo_path(project, cache_key="myapp@a-branch", ref="a-branch")

    assert "branch_only" in load_manifest(project, repo_root=root).validation


def test_a_ref_that_is_not_here_refuses_by_name_and_says_to_fetch(tmp_path, monkeypatch):
    """A colleague's branch that was never fetched is the ordinary case, and `git fetch` is the
    person's to run — never something this may do on their behalf."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path

    repo = _repo_with_a_branch(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        resolve_repo_path(_local_project(repo), cache_key="k", ref="feat/never-pushed-here")

    assert "feat/never-pushed-here" in str(exc.value) and "fetch" in str(exc.value)


def test_a_path_that_is_not_a_repository_refuses_by_name(tmp_path, monkeypatch):
    """Neither failure is guessable from a git error, and both are a person's to fix."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path

    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(RuntimeError) as exc:
        resolve_repo_path(_local_project(plain), cache_key="k", ref="a-branch")

    assert "not a git repository" in str(exc.value)


def test_the_branch_you_are_standing_on_can_be_measured(tmp_path, monkeypatch):
    """The most natural use, and the one that fails without `--detach`: you are ON the branch you
    want to prove. `git worktree add <path> <branch>` CLAIMS the branch and refuses when it is
    already checked out — *"fatal: 'a-branch' is already used by worktree at …"* — so the obvious
    thing to measure would have been the one thing this could not. A proof reads a tree; it never
    needs to own a ref."""
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    from openfactory.factory import resolve_repo_path
    from openfactory.loader import load_manifest

    repo = _repo_with_a_branch(tmp_path)
    _git(["checkout", "-q", "a-branch"], repo)          # standing on it
    project = _local_project(repo)

    root = resolve_repo_path(project, cache_key="myapp@a-branch", ref="a-branch")

    assert "branch_only" in load_manifest(project, repo_root=root).validation
    assert _git(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip() == "a-branch", (
        "measuring the branch moved the tree off it"
    )

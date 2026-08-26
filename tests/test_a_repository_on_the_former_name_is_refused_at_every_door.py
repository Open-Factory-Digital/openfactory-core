"""A repository still on the platform's former directory name is refused, BY NAME, at every door
that decides whether it has a manifest — and none of those doors writes a second one.

THE DEFECT CLASS. `namespace.resolve` is the ONE reader: a repository carrying `.sdlc/…` and
nothing under `.openfactory/` is refused with a sentence that says what to rename. The loader,
the doctor, onboarding and the box proof were routed through it in the first two rounds. Four
more doors decided "does this repository have a manifest?" with `exists()` on the CURRENT name
alone — `env read`, `env apply`, `product init` and `project init` — so a repository the platform
refuses to read was answered "nothing here", and the verbs that write then wrote a second
manifest beside the one it has; the loader answered from the new file and the client's own gates
were gone (review, 2026-08-25: reproduced on `env apply`, read on `product init`; the fifth door
was found by the search the review asked for).

EVERY DOOR IS DRIVEN, NOT READ. Each test calls the real action function, the real plan or the
real CLI command on a checkout carrying only the retired file, and asserts three things: the
outcome is a refusal, the sentence names the file it found and the rename, and NOT ONE BYTE of
the checkout changed. Each has its positive twin — the same door on the current name still does
what it is for — because a door that refuses everything would pass the negative half alone.

THE DOOR IS IMPORTED BEFORE ANYTHING IS PATCHED. The first cut of this file substituted the
registry on `openfactory.registry` and then performed the process's FIRST import of the CLI
under that patch: `cli.py` binds `ProjectRegistry` at import, so the binding was the test's
lambda, monkeypatch never knew about that second copy, and every CLI test that ran afterwards
in the same worker found a registry that could not `attach_board` or `get` (review, 2026-08-26:
two reds alone, two more in `test_doctor.py` after it, green only when a neighbour had imported
the CLI first). So the CLI is imported here, at module level, and the fixture patches the ONE
attribute the door reads at call time (`_get_project` resolves `registry.ProjectRegistry` from
the module, on purpose) — and asserts on the way out that the CLI's own binding is untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory import cli, namespace
from openfactory import registry as registry_module
from openfactory.actions.base import CONFLICT, Actor
from openfactory.actions.catalog import _env_apply_impl, _env_read

#: The class the CLI bound at import — what every test's patch must leave alone.
REAL_REGISTRY = registry_module.ProjectRegistry

RETIRED_MANIFEST = f"{namespace.RETIRED_DIR}/project.yaml"
RETIRED_PRODUCT = f"{namespace.RETIRED_DIR}/product.yaml"
#: A manifest a client tuned by hand — the thing a second manifest would shadow.
THEIRS = "version: 1\nbase_branch: develop\nvalidate:\n  test: pytest -q\n"
BY = Actor(id="tester", via="test")


def _checkout(root: Path, *, retired: bool = False, current: bool = False) -> Path:
    """A repository the inference can read something from, carrying its manifest under whichever
    name(s) the test says. `.git/HEAD` as text is how `infer` reads the base branch — no git."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'acme'\nversion = '0'\n")
    (root / "requirements.txt").write_text("pytest\n")
    (root / ".git").mkdir(exist_ok=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    for wanted, rel in ((retired, RETIRED_MANIFEST), (current, namespace.MANIFEST)):
        if wanted:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(THEIRS)
    return root


def _snapshot(root: Path) -> dict[str, str]:
    """Every file under `root`, by content — what "nothing was written" is measured against."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _says_rename(sentence: str) -> bool:
    """The loader's sentence: the file it found, and the directory to rename it to."""
    return (RETIRED_MANIFEST in sentence or RETIRED_PRODUCT in sentence) and (
        f"`{namespace.RETIRED_DIR}/` to `{namespace.DIR}/`" in sentence)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """No project registered anywhere the action layer looks — every target below is a PATH."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))


# ── door 1: `env read` ─────────────────────────────────────────────────────────────────────────

def test_env_read_refuses_a_repository_on_the_retired_name_by_name(tmp_path, isolated_registry):
    """The verb that PROPOSES: a proposal for a repository whose manifest the platform refuses to
    read is a proposal for a second manifest, so it does not propose — it says what to rename."""
    repo = _checkout(tmp_path / "acme", retired=True)
    before = _snapshot(repo)

    out = asyncio.run(_env_read(target=str(repo), by=BY))

    assert not out.ok and out.code == CONFLICT, out
    assert _says_rename(out.message), out.message
    assert "fields" not in out.data, "it still proposed"
    assert _snapshot(repo) == before


def test_env_read_still_proposes_on_the_current_name_and_reports_the_file_it_saw(
        tmp_path, isolated_registry):
    """The positive twin. On the current name the read proposes and says the file exists; with a
    stale retired twin BESIDE the current file nothing is refused — the current name wins."""
    repo = _checkout(tmp_path / "acme", current=True, retired=True)

    out = asyncio.run(_env_read(target=str(repo), by=BY))

    assert out.ok, out.message
    assert out.data["destination_exists"] is True
    assert str(out.data["destination"]).endswith(namespace.MANIFEST)
    assert not _says_rename(out.message)

    fresh = asyncio.run(_env_read(target=str(_checkout(tmp_path / "fresh")), by=BY))
    assert fresh.ok and fresh.data["destination_exists"] is False


# ── door 2: `env apply` ────────────────────────────────────────────────────────────────────────

def test_env_apply_refuses_a_repository_on_the_retired_name_and_writes_nothing(
        tmp_path, isolated_registry):
    """The ONLY verb here that writes. With consent, with every field accepted, it writes NOTHING
    into a repository on the retired name — not the manifest, not a `.bak` — and the refusal is
    the loader's own sentence. Measured on this function with `yes=True`, 2026-08-25: it wrote."""
    repo = _checkout(tmp_path / "acme", retired=True)
    before = _snapshot(repo)

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, accept=["all"],
                                      answers={"base_branch": "develop"}))

    assert not out.ok and out.code == CONFLICT, out
    assert _says_rename(out.message), out.message
    assert out.data.get("wrote") is None
    assert not (repo / namespace.MANIFEST).exists(), "a second manifest was written"
    assert _snapshot(repo) == before


def test_env_apply_refuses_even_when_the_file_would_land_elsewhere(tmp_path, isolated_registry):
    """`out=` moves the WRITE, not the question. A manifest proposed for a repository the platform
    refuses to read is still a second manifest for it, wherever it lands."""
    repo = _checkout(tmp_path / "acme", retired=True)
    elsewhere = tmp_path / "proposal.yaml"

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, accept=["all"],
                                      out=str(elsewhere)))

    assert not out.ok and _says_rename(out.message), out
    assert not elsewhere.exists()


def test_env_apply_on_the_current_name_is_the_conflict_it_always_was_and_not_a_rename(
        tmp_path, isolated_registry):
    """The positive twin, first half: a manifest on the CURRENT name is refused the old way —
    "already exists", `--force` — and the rename sentence is nowhere in it. A stale retired twin
    beside it changes nothing."""
    repo = _checkout(tmp_path / "acme", current=True, retired=True)
    before = _snapshot(repo)

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, accept=["all"],
                                      answers={"base_branch": "develop"}))

    assert not out.ok and out.code == CONFLICT, out
    assert "already exists" in out.message and not _says_rename(out.message), out.message
    assert _snapshot(repo) == before


def test_env_apply_still_writes_a_repository_that_has_no_manifest_at_all(
        tmp_path, isolated_registry):
    """The positive twin, second half: the door still WRITES when nothing is there under either
    name — or the refusal above is satisfied by a verb that can never write."""
    repo = _checkout(tmp_path / "acme")

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, accept=["all"],
                                      answers={"base_branch": "develop"}))

    assert out.ok, out.message
    written = repo / namespace.MANIFEST
    assert written.is_file() and "base_branch: develop" in written.read_text()


def test_env_apply_force_does_not_walk_around_the_refusal(tmp_path, isolated_registry):
    """`--force` is the flag an operator reaches for after reading "already exists" — and the
    rename refusal is not that conflict. Forcing must not turn it into a write: the manifest the
    repository has is under a name the platform does not read, so there is nothing here to
    replace, and a `.bak` of nothing beside a second manifest would be the defect with a backup.
    The review's survivor (2026-08-26): the resolve call gated on `not force` passed every test."""
    repo = _checkout(tmp_path / "acme", retired=True)
    before = _snapshot(repo)

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, force=True,
                                      accept=["all"], answers={"base_branch": "develop"}))

    assert not out.ok and out.code == CONFLICT, out
    assert _says_rename(out.message), out.message
    assert out.data.get("wrote") is None
    assert not (repo / namespace.MANIFEST).exists(), "force wrote a second manifest"
    assert _snapshot(repo) == before


def test_env_apply_force_still_replaces_a_manifest_on_the_current_name_with_a_backup(
        tmp_path, isolated_registry):
    """The positive twin: on the current name `--force` does what it always did — the previous
    file is copied to `.bak` and the proposal is written over it. A stale retired twin beside it
    changes nothing."""
    repo = _checkout(tmp_path / "acme", current=True, retired=True)
    current = repo / namespace.MANIFEST

    out = asyncio.run(_env_apply_impl(project=str(repo), by=BY, yes=True, force=True,
                                      accept=["all"], answers={"base_branch": "release"}))

    assert out.ok, out.message
    assert "base_branch: release" in current.read_text()
    assert current.with_suffix(".yaml.bak").read_text() == THEIRS


def _url_registered(tmp_path, monkeypatch, *, clone: Path, forge: _Forge):
    """`env apply --pr` for a project registered by clone URL, with the two seams that leave this
    machine doubled: the forge, and the clone `propose_manifest.clone_for_proposal` makes —
    answered by the directory the test shapes. Everything between them is production code, and
    `propose` is replaced by a recorder so the test can say whether the push was ever reached."""
    from openfactory.adapters.forge import registry as forge_registry
    from openfactory.onboarding import propose_manifest

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    added = CliRunner().invoke(cli.app, ["project", "add", "acme",
                                         "https://github.com/acme-corp/their-app.git"])
    assert added.exit_code == 0, added.output
    monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: forge)
    monkeypatch.setattr(propose_manifest, "clone_for_proposal",
                        lambda *, clone_url, base="": (clone, ""))
    proposed: list[dict] = []

    def _propose(**kw):
        proposed.append(kw)
        return propose_manifest.Proposal(ok=True, url="https://github.com/acme-corp/their-app/"
                                                      "pull/9", ref=propose_manifest.BRANCH)

    monkeypatch.setattr(propose_manifest, "propose", _propose)
    return proposed


def test_env_apply_pr_refuses_before_it_proposes_a_second_manifest(tmp_path, monkeypatch):
    """The other survivor: on the `--pr` path the write lands in a temporary clone and becomes a
    pull request, and a resolve call gated on "not a clone" passed every test. Driven through the
    clone: it carries only the retired file, so the verb refuses with the rename, writes nothing
    into the clone, and never reaches `propose` — a pull request proposing a second manifest is
    the round-2 defect wearing a reviewable shape."""
    clone = _checkout(tmp_path / "clone", retired=True)
    before = _snapshot(clone)
    proposed = _url_registered(tmp_path, monkeypatch, clone=clone, forge=_Forge())

    out = asyncio.run(_env_apply_impl(project="acme", by=BY, yes=True, pr=True, accept=["all"],
                                      answers={"base_branch": "develop"}))

    assert not out.ok and out.code == CONFLICT, out
    assert _says_rename(out.message), out.message
    assert out.data.get("wrote") is None
    assert not proposed, "a pull request was proposed for a second manifest"
    assert _snapshot(clone) == before


def test_env_apply_pr_still_proposes_for_a_clone_with_no_manifest(tmp_path, monkeypatch):
    """The positive twin through the same seams: a clone with nothing under either name gets the
    manifest written into it and proposed — `propose` is reached with that clone and the file."""
    clone = _checkout(tmp_path / "clone")
    proposed = _url_registered(tmp_path, monkeypatch, clone=clone, forge=_Forge())

    out = asyncio.run(_env_apply_impl(project="acme", by=BY, yes=True, pr=True, accept=["all"],
                                      answers={"base_branch": "develop"}))

    assert out.ok, out.message
    assert out.data["pull_request"].endswith("/pull/9")
    assert len(proposed) == 1 and proposed[0]["checkout"] == clone
    assert "base_branch: develop" in (clone / namespace.MANIFEST).read_text()


# ── door 3: `product init` — the CONTEXT repository's declaration ──────────────────────────────

def _product_project():
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name="acme", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="acme-corp/their-app"),
                   forge=ProviderRef(kind="github", repo="acme-corp/their-app"),
                   product=ProductConfig(docs_repo="acme-corp/acme-context"))


DECLARED = ("product: acme\nrequirements_dir: requirements\nsources:\n- acme-corp/their-app\n")


def _context(root: Path, *, retired: bool = False, current: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# context\n")
    for wanted, rel in ((retired, RETIRED_PRODUCT), (current, namespace.PRODUCT_MANIFEST)):
        if wanted:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(DECLARED)
    return root


def test_the_product_plan_refuses_a_context_repository_on_the_retired_name(tmp_path):
    """`plan` is the seam both callers stop on (`product init` exits, the `onboard` verb returns
    the detail): its `refusal` is the loader's sentence, and there is no file to write."""
    from openfactory.product.onboard import plan

    root = _context(tmp_path / "ctx", retired=True)
    before = _snapshot(root)

    result = plan(_product_project(), root, sources=["acme-corp/their-app"])

    assert result.refusal and _says_rename(result.refusal), result.refusal
    assert result.product_yaml == "" and not result.already_correct
    assert _snapshot(root) == before


def test_the_product_plan_reads_the_declaration_on_the_current_name(tmp_path):
    """The positive twin: on the current name the plan READS the declaration (already correct,
    nothing to write); a stale retired twin beside it changes nothing."""
    from openfactory.product.onboard import plan

    root = _context(tmp_path / "ctx", current=True, retired=True)

    result = plan(_product_project(), root, sources=["acme-corp/their-app"])

    assert not result.refusal, result.refusal
    assert result.already_correct

    empty = plan(_product_project(), _context(tmp_path / "empty"), sources=["acme-corp/their-app"])
    assert not empty.refusal and "product: acme" in empty.product_yaml


class _Forge:
    def __init__(self):
        self.opened: list[dict] = []

    def clone_url(self, repo, *, token=None):
        return f"https://github.com/{repo}"

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "repo": repo})
        return f"https://github.com/{repo}/pull/1"


class _Registry:
    def __init__(self, project):
        self._project = project

    def get(self, name):
        return self._project


@pytest.fixture
def product_init(monkeypatch):
    """`openfactory product init acme --write` with the two seams that leave this machine doubled
    — the forge and the registry — and `git clone` answered by a directory the test shapes.
    Everything between them is production code.

    The registry is substituted where the door READS it: `_get_project` resolves
    `ProjectRegistry` from `openfactory.registry` at call time, so that attribute is the seam,
    and the CLI (imported at the top of this file, before any patch) keeps its own binding. The
    teardown asserts exactly that — with the patch still live, since monkeypatch unwinds after
    this fixture — because a test that leaves the CLI holding a lambda fails its neighbours."""
    def _wire(shape):
        import subprocess as real_subprocess

        from openfactory.adapters.forge import registry as forge_registry

        forge = _Forge()
        monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **kw: forge)
        monkeypatch.setattr(registry_module, "ProjectRegistry",
                            lambda: _Registry(_product_project()))
        seen: list[list[str]] = []

        class _Done:
            returncode, stdout, stderr = 0, "main\n", ""

        def _fake_git(cmd, **kw):
            seen.append(list(cmd))
            if cmd[:2] == ["git", "clone"]:
                shape(Path(cmd[-1]))
            return _Done()

        monkeypatch.setattr(real_subprocess, "run", _fake_git)
        result = CliRunner().invoke(cli.app, ["product", "init", "acme", "--write"])
        return result, forge, seen
    yield _wire
    assert cli.ProjectRegistry is REAL_REGISTRY, (
        "the CLI's import-time binding is this test's registry double — it was first imported "
        "under the patch, and every CLI test after this one in the same process now reads it")


def test_product_init_write_stops_at_the_refusal_and_pushes_nothing(product_init):
    """Through the real command: the clone carries only the retired declaration, so `--write`
    exits non-zero with the rename in its output, and no branch is pushed, no review opened."""
    result, forge, seen = product_init(lambda clone: _context(clone, retired=True))

    assert result.exit_code == 1, result.output
    assert _says_rename(result.output), result.output
    assert not forge.opened, "a review request was opened for a second declaration"
    assert not any("push" in c for c in seen), "a branch was pushed"


def test_product_init_write_still_proposes_for_a_context_with_no_declaration(product_init):
    """The positive twin through the same command: an empty clone gets the declaration, pushed
    on the onboarding branch, with a review request open on it."""
    result, forge, seen = product_init(lambda clone: _context(clone))

    assert result.exit_code == 0, result.output
    assert forge.opened and forge.opened[0]["repo"] == "acme-corp/acme-context"
    assert any("push" in c for c in seen)


# ── door 4: `project init` — the manifest scaffold ─────────────────────────────────────────────

@pytest.fixture
def project_init(tmp_path, monkeypatch):
    """`openfactory project init acme <checkout> --repo acme/acme` against an empty registry, with
    the board creation — the one step that leaves this machine — answered locally."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.adapters.tracker import github_board_setup

    monkeypatch.setattr(github_board_setup, "create_board",
                        lambda **kw: ("7", "https://github.com/users/acme/projects/7"))

    def _run(checkout: Path):
        # one registration per checkout: a second `init` of a registered name converges on the
        # repo_path already recorded, which would be the previous test's checkout
        name = checkout.name
        return CliRunner().invoke(cli.app, ["project", "init", name, str(checkout),
                                            "--repo", f"acme/{name}"])
    return _run


def test_project_init_refuses_to_scaffold_over_a_checkout_on_the_retired_name(
        tmp_path, project_init):
    """The first command a new operator runs. It registers the project, and then — instead of
    scaffolding the template beside the manifest that is there — says what to rename and exits
    non-zero, so a script notices."""
    repo = _checkout(tmp_path / "acme", retired=True)
    before = _snapshot(repo)

    result = project_init(repo)

    assert result.exit_code == 1, result.output
    assert _says_rename(result.output), result.output
    assert "✓ wrote" not in result.output
    assert _snapshot(repo) == before


def test_project_init_scaffolds_an_empty_checkout_and_leaves_a_current_manifest_alone(
        tmp_path, project_init):
    """The positive twin: with nothing there the template is written; on the current name the
    scaffold is skipped as "already exists", byte for byte — and a stale retired twin beside it
    changes nothing."""
    empty = _checkout(tmp_path / "empty")
    result = project_init(empty)
    assert result.exit_code == 0, result.output
    assert "✓ wrote" in result.output and (empty / namespace.MANIFEST).is_file()

    theirs = _checkout(tmp_path / "theirs", current=True, retired=True)
    before = _snapshot(theirs)
    result = project_init(theirs)
    assert result.exit_code == 0, result.output
    assert "already exists" in result.output and not _says_rename(result.output)
    assert _snapshot(theirs) == before

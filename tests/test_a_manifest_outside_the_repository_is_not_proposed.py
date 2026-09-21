"""A `manifest_path` outside the repository is refused BEFORE anything is written (#259).

`Project.manifest_path` exists so a client can put the file where their own conventions say, and
an explicit value is never second-guessed — `openfactory/namespace.py` says so in its own
docstring, and reading honours it: the loader, setup, the gates, `box prove` and `doctor` all work
against a manifest that lives outside the checkout.

The two PR-creation paths cannot. A pull request carries only files that live in the repository it
is opened on — and both of them composed their destination as `checkout / manifest_path`, a join
an absolute right-hand operand wins outright. So the temporary clone's prefix disappeared, the
manifest was written over the REAL file that value names (rotating the one already there to
`.bak`), and only THEN was it refused — by `git add`, exit 128, in git's own words about a path
the platform had composed:

    could not stage /srv/openfactory/manifests/<project>.yaml: fatal: '…' is outside repository
    at '/tmp/openfactory-proposal-xxxx'

THE WRITE IS WHAT THESE GUARDS MEASURE, not the sentence: the clone, the origin and the write are
all real here (only the forge and the box are doubled), so a guard that merely watched the ordering
would pass over the very file being overwritten. Each one asserts the client's bytes are still
their own.

  1. `env apply --pr` refuses the row by name — the client's file unchanged, no `.bak` beside it,
     no pull request — and it does so before it clones, since the row alone decides it;
  2. …and an absolute path with nothing at it is not created either;
  3. `onboard` refuses before its clone, its box proof and its write;
  4. `propose()` itself stages nothing outside the checkout — the backstop under both callers,
     and under whoever calls it next;
  5. the rule is about the VALUE: `..` climbing out of the root leaves the repository too, and an
     ordinary relative path does not;
  6. and the promise the namespace docstring makes is untouched — reading a manifest outside the
     repository still works, and a LOCAL `env apply` still writes exactly where it was told to.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.contracts.project import Project, ProviderRef
from openfactory.onboarding import propose_manifest as pm

#: what the client's own file says, and has to keep saying
THEIRS = "# hand-written by the client\nversion: 1\nvalidate:\n  test: make check\n"

_ANSWER = ["--set", "validate.test=pytest -q"]


@pytest.fixture
def outside(tmp_path) -> Path:
    """A real manifest of a client's, on an absolute path that is nobody's checkout."""
    where = tmp_path / "srv" / "openfactory" / "manifests"
    where.mkdir(parents=True)
    theirs = where / "podbeam.yaml"
    theirs.write_text(THEIRS)
    return theirs


@pytest.fixture
def clones(monkeypatch) -> list[Path]:
    """Every temporary clone this run actually made — the REAL one, wrapped rather than replaced.

    Replacing it would make the write unreachable and the guard vacuous: the defect is a file
    written over, and only a run that reaches the write can prove it was not."""
    made: list[Path] = []
    real = pm.clone_for_proposal

    def _remember(**kw):
        path, why = real(**kw)
        if path is not None:
            made.append(path)
        return path, why

    monkeypatch.setattr(pm, "clone_for_proposal", _remember)
    return made


class _Forge:
    """The forge port, doubled at the methods these two paths reach."""

    def __init__(self):
        self.opened: list[dict] = []

    def pr_for_head(self, head, *, repo=""):
        return ""

    def pr_status(self, *, pr, repo=""):
        return "active"

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "repo": repo})
        return f"https://github.com/{repo}/pull/1"


def _origin(tmp_path: Path, name: str = "podbeam") -> Path:
    """A real repository to clone from — the git side of both verbs stays production code."""
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True,
                   capture_output=True)
    seed = tmp_path / f"seed-{name}"
    (seed / "pkg").mkdir(parents=True)
    (seed / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    (seed / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
    for args in (["init", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                 ["remote", "add", "origin", str(bare)], ["push", "-u", "origin", "main"]):
        subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)
    return bare


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A project registered by URL whose row names `manifest_path`, with a real origin behind it.

    The row is written by `project add` and then edited, because that door has no flag for this
    field — a registry a client hand-edits is exactly the shape the defect arrives in."""
    registry = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))
    assert CliRunner().invoke(
        app, ["project", "add", "podbeam", "https://github.com/solo-dev/podbeam.git"]
    ).exit_code == 0

    def _wire(manifest_path: str) -> _Forge:
        rows = yaml.safe_load(registry.read_text())
        rows["projects"]["podbeam"]["manifest_path"] = manifest_path
        registry.write_text(yaml.safe_dump(rows, sort_keys=False))
        forge = _Forge()
        origin = _origin(tmp_path)
        monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                            lambda *a, **kw: forge)
        # the only seam that would leave this machine: the URL git is handed
        monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                            lambda *a, **kw: str(origin))
        return forge

    return _wire


def _apply(*args):
    return CliRunner().invoke(app, ["env", "apply", "podbeam", "--yes", *_ANSWER, *args])


# ── 1-2. `env apply --pr` ───────────────────────────────────────────────────────────────────────

def test_env_apply_pr_refuses_the_row_instead_of_writing_over_the_clients_file(
        wired, outside, clones):
    """`--force` is what the defect was observed under: the file outside the clone was rotated to
    `.bak` and replaced, and the verb THEN reported FAILED in git's words."""
    forge = wired(str(outside))

    result = _apply("--pr", "--force")

    assert result.exit_code != 0, result.output
    assert outside.read_text() == THEIRS, "the client's own manifest was written over"
    assert [p.name for p in outside.parent.iterdir()] == ["podbeam.yaml"], (
        f"something was left beside it: {sorted(p.name for p in outside.parent.iterdir())}")
    assert forge.opened == [], "a pull request was opened for a file it cannot carry"
    assert clones == [], "the row alone decides this, so nothing needed to be cloned"


def test_an_absolute_path_with_nothing_at_it_is_not_created_either(wired, tmp_path, clones):
    """The `.bak` rotation needs a file to rotate; the WRITE needs nothing at all. A path nobody
    has created yet is the shape in which this leaves a manifest in a directory of the worker's
    own filesystem, with `mkdir(parents=True)` making the way for it."""
    nowhere = tmp_path / "srv" / "openfactory" / "manifests" / "fresh.yaml"
    wired(str(nowhere))

    result = _apply("--pr")

    assert result.exit_code != 0, result.output
    assert not nowhere.exists(), f"{nowhere} was created outside every repository"
    assert not nowhere.parent.exists(), "the directories were made for it, too"
    assert clones == []


def test_the_refusal_names_the_path_and_a_way_forward(wired, outside):
    """`openfactory doctor` is the bar: the cause in the platform's own words, and the remedy."""
    wired(str(outside))

    said = " ".join(_apply("--pr", "--force").output.split())

    assert str(outside) in said, said
    assert "outside the repository" in said, said
    assert "--out" in said, "the way to write that file anyway is not named"
    assert "is outside repository at" not in said, "git's own words are still the refusal"


# ── 3. the `onboard` verb ───────────────────────────────────────────────────────────────────────

@pytest.fixture
def onboarding(tmp_path, monkeypatch):
    """`onboard`'s own wiring: forge doubled, clone URL routed to a real origin, the box proof
    doubled at the Probes seam so no docker is needed. Everything the write touches is real."""
    forge = _Forge()
    origin = _origin(tmp_path, "api")
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge", lambda *a, **kw: forge)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origin))

    from contextlib import contextmanager

    @contextmanager
    def _fake_probes(view, image, *, repo_path=None, manifest=None, key=None):
        yield {"repo_path": repo_path, "key": key}

    class _Proof:
        def __init__(self, key):
            self.project, self.ok, self.findings = key, True, []

        def failures(self):
            return []

        def advisories(self):
            return []

    monkeypatch.setattr("openfactory.box_prove.box_probes", _fake_probes)
    monkeypatch.setattr("openfactory.box_prove.prove",
                        lambda key, image, probes, on_stage=None: _Proof(key))
    monkeypatch.setattr("openfactory.box_prove.save", lambda proof, **kw: Path("/x"))
    monkeypatch.setattr("openfactory.factory.resolve_box_image", lambda *a, **kw: "img:1")
    return forge


def test_onboard_refuses_before_it_clones_proves_or_writes(outside, onboarding, clones):
    from openfactory.onboarding.onboard import onboard_source_repo

    project = Project(name="podbeam", repo_path="https://github.com/acme/api.git",
                      tracker=ProviderRef(kind="github", repo="acme/api"),
                      forge=ProviderRef(kind="github", repo="acme/api"),
                      manifest_path=str(outside))

    result = onboard_source_repo(project, "acme/api")

    assert result.ok is False
    assert outside.read_text() == THEIRS, "the client's own manifest was written over"
    assert onboarding.opened == [], "a pull request was opened for a file it cannot carry"
    assert str(outside) in result.detail and "outside the repository" in result.detail
    assert result.pr == ""
    assert clones == [], "the clone and the box proof both happen after the write it refuses"


# ── 4. `propose()` itself — the backstop under every caller ─────────────────────────────────────

def _repo(where: Path) -> Path:
    """A git repository with one commit on `main` — the shape a proposal clone arrives in."""
    where.mkdir(parents=True)
    for args in (["init", "-b", "main"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed",
                  "--allow-empty"]):
        subprocess.run(["git", *args], cwd=where, check=True, capture_output=True)
    return where


def _branches(checkout: Path) -> list[str]:
    done = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=checkout,
                          capture_output=True, text=True, check=True)
    return done.stdout.split()


def test_propose_stages_nothing_and_asks_nobody(tmp_path, outside):
    """The cheap regression this defect asks for: `propose()` with an absolute `manifest_path`
    must not modify anything outside `checkout`. It also must not reach the forge — a proposal
    that cannot exist is not an idempotency question."""
    checkout = _repo(tmp_path / "clone")
    forge = _Forge()

    result = pm.propose(checkout=checkout, manifest_path=str(outside), repo="solo-dev/podbeam",
                        clone_url="https://example.invalid/podbeam.git", base="main",
                        forge=forge, project_name="podbeam")

    assert result.ok is False
    assert str(outside) in result.detail
    assert forge.opened == [], "a pull request was opened for a file it cannot carry"
    assert _branches(checkout) == ["main"], "a branch was cut for a file that cannot be staged"
    assert outside.read_text() == THEIRS


def test_an_extra_path_outside_the_checkout_is_refused_too(tmp_path, outside):
    """`extra_paths` is staged by the same loop, so it is the same defect one argument along."""
    checkout = _repo(tmp_path / "clone")
    (checkout / ".openfactory").mkdir()
    (checkout / ".openfactory" / "project.yaml").write_text("version: 1\n")

    result = pm.propose(checkout=checkout, manifest_path=".openfactory/project.yaml",
                        repo="solo-dev/podbeam", clone_url="https://example.invalid/p.git",
                        base="main", forge=_Forge(), project_name="podbeam",
                        extra_paths=[str(outside)])

    assert result.ok is False and str(outside) in result.detail
    assert _branches(checkout) == ["main"]


# ── 5. the rule is about the value ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [
    "/srv/openfactory/manifests/podbeam.yaml",
    "/.openfactory/project.yaml",
    "../elsewhere/project.yaml",
    "conf/../../elsewhere/project.yaml",
    "..",
    # A WINDOWS DRIVE, which `PurePosixPath` reads as an ordinary relative path (review,
    # 2026-09-21). It cannot reach a client's file — the join lands inside the clone — so what it
    # would do is commit a directory literally named `C:`. Both shapes: rooted, and drive-relative.
    "C:\\srv\\openfactory\\podbeam.yaml",
    "C:podbeam.yaml",
    # …and the UNC share, which already answered correctly and is pinned so it keeps doing so
    "\\\\server\\share\\podbeam.yaml",
])
def test_these_values_leave_the_repository(value):
    assert pm.leaves_the_repository(value) is True, value


@pytest.mark.parametrize("value", [
    ".openfactory/project.yaml",
    "conf/factory.yaml",
    "./conf/factory.yaml",
    "conf/../factory.yaml",
    "project.yaml",
])
def test_these_values_stay_inside_it(value):
    assert pm.leaves_the_repository(value) is False, value


# ── 6. and everything else still honours an explicit path ───────────────────────────────────────

def test_reading_a_manifest_outside_the_repository_still_works(tmp_path, outside):
    """The namespace docstring's promise, which this change is the single exception to: the
    loader resolves an absolute `manifest_path` through the same join and reads it."""
    from openfactory.loader import load_manifest

    project = Project(name="podbeam", repo_path=str(tmp_path), manifest_path=str(outside))

    assert load_manifest(project, repo_root=tmp_path).validation["test"] == "make check"


def test_a_local_env_apply_still_writes_exactly_where_it_was_told(tmp_path, monkeypatch, outside):
    """The refusal belongs to the PR arm alone. On a local checkout there is no pull request to
    carry anything — the file is written for the client to review in their own diff, and an
    absolute `manifest_path` is a destination like any other."""
    registry = tmp_path / "registry.yaml"
    checkout = tmp_path / "local"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname = "podbeam"\nversion = "0.1.0"\n')
    registry.write_text(f"projects:\n"
                        f"  podbeam:\n"
                        f"    name: podbeam\n"
                        f"    repo_path: {checkout}\n"
                        f"    manifest_path: {outside}\n")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))

    result = _apply("--force")

    assert result.exit_code == 0, result.output
    assert "pytest -q" in outside.read_text(), "an explicit path is never second-guessed"

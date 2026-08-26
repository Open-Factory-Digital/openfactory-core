"""`openfactory onboard` — the first-time setup happens where the factory lives, measured.

The operator's two observations, verbatim in the module's docstring, are the spec: the setup
must run in a BOX (manifest proposed AND proven, map generated) and the journey must be
multi-repo, because the reality at an enterprise client is a front end and a back end. What
these tests hold:

  1. one repository: the PR carries the manifest AND the module map, and the proof verdict is
     in the body — a failing proof does NOT withhold the PR, it informs it;
  2. the proof is SAVED under the repo's own key, so the pickup gate and the onboarding agree;
  3. a repository that already declares its manifest is proven as-is and not re-proposed;
  4. N repositories = N pull requests, each proven on its own manifest — the enterprise shape;
  5. nothing new → said, not performed (no empty PR, no "nothing to commit" refusal).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory import namespace
from openfactory.contracts.project import Project, ProviderRef
from openfactory.onboarding import onboard as ob


def _origin(tmp_path: Path, name: str, *, with_manifest: bool = False,
            default_branch: str = "main", retired: bool = False) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", default_branch, str(bare)], check=True,
                   capture_output=True)
    seed = tmp_path / f"seed-{name}"
    (seed / "pkg").mkdir(parents=True)
    (seed / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    (seed / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n')
    if with_manifest:
        (seed / ".openfactory").mkdir()
        (seed / ".openfactory" / "project.yaml").write_text(
            "version: 1\nvalidate:\n  test: pytest -q\n")
    if retired:
        # the manifest, complete and valid, under the directory's FORMER name and nothing
        # under the current one — the repository the platform refuses by name
        (seed / namespace.RETIRED_DIR).mkdir()
        (seed / namespace.RETIRED_DIR / "project.yaml").write_text(
            "version: 1\nvalidate:\n  test: pytest -q\n")
    for args in (["init", "-b", default_branch], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                 ["remote", "add", "origin", str(bare)],
                 ["push", "-u", "origin", default_branch]):
        subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)
    return bare


class _Forge:
    def __init__(self):
        self.opened: list[dict] = []

    def clone_url(self, repo, *, token=None):
        raise AssertionError("clone_url must come through the wired clone_url_for")

    def pr_for_head(self, head, *, repo=""):
        return ""

    def pr_status(self, *, pr, repo=""):
        return "active"

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body,
                            "repo": repo})
        return f"https://github.com/{repo}/pull/1"


def _project() -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"))


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Forge doubled; clone URL routed to a real local origin; the box proof doubled at the
    Probes seam so no docker is needed."""
    origins: dict[str, Path] = {}
    forge = _Forge()

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: forge)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins[repo]))

    class _FakeProof:
        def __init__(self, key, ok):
            self.project, self.ok = key, ok
            self.findings = []

        def failures(self):
            return [f for f in self.findings if not f.ok]

    proved: dict[str, object] = {"ok": True, "saved": []}

    from contextlib import contextmanager

    @contextmanager
    def _fake_probes(view, image, *, repo_path=None, manifest=None, key=None):
        yield {"repo_path": repo_path, "key": key}

    def _fake_prove(key, image, probes, on_stage=None):
        proof = _FakeProof(key, bool(proved["ok"]))
        if not proof.ok:
            from openfactory.box_prove import Finding

            proof.findings = [Finding("validate.test", False, "exit 2: 3 tests failed",
                                      "fix the tests")]
        return proof

    monkeypatch.setattr("openfactory.box_prove.box_probes", _fake_probes)
    monkeypatch.setattr("openfactory.box_prove.prove", _fake_prove)
    monkeypatch.setattr("openfactory.box_prove.save",
                        lambda proof, **kw: proved["saved"].append(proof.project) or Path("/x"))
    monkeypatch.setattr("openfactory.factory.resolve_box_image",
                        lambda *a, **kw: "img:1")
    return origins, forge, proved


def test_one_repo_gets_ONE_pr_carrying_manifest_map_and_verdict(tmp_path, wired):
    origins, forge, proved = wired
    origins["acme/api"] = _origin(tmp_path, "api")

    out = ob.onboard_source_repo(_project(), "acme/api")

    assert out.ok, out.detail
    assert forge.opened, "no pull request was opened"
    body = forge.opened[0]["body"]
    assert "PASSED" in body, "the proof verdict is not in the PR body"
    assert "knowledge/" in body, "the module map is not explained to the reviewer"
    assert out.modules >= 1, "no module map was generated"
    assert proved["saved"] == ["dsk"], "the proof was not saved under the repo's key"


def test_the_pushed_branch_actually_contains_both_artefacts(tmp_path, wired):
    origins, forge, _ = wired
    origins["acme/api"] = _origin(tmp_path, "api")

    assert ob.onboard_source_repo(_project(), "acme/api").ok

    shown = subprocess.run(["git", "show", "--name-only", "--format=",
                            "openfactory/onboard"],
                           cwd=origins["acme/api"], capture_output=True, text=True)
    assert ".openfactory/project.yaml" in shown.stdout
    assert "knowledge/modules.yaml" in shown.stdout, (
        f"the map is not in the pushed commit: {shown.stdout}")


def test_a_FAILING_proof_informs_the_pr_instead_of_withholding_it(tmp_path, wired):
    origins, forge, proved = wired
    origins["acme/api"] = _origin(tmp_path, "api")
    proved["ok"] = False

    out = ob.onboard_source_repo(_project(), "acme/api")

    assert out.ok, "a failing proof must not block the proposal — it is the measurement"
    assert out.proof == "failed"
    body = forge.opened[0]["body"]
    assert "FAILED" in body and "exit 2" in body, (
        "the reviewer is not shown what was measured")
    assert "fix the tests" in body, (
        "the finding's REMEDY must ride into the PR body — a bare `not found` in a shell's "
        "vocabulary is the reviewer blocked (pilot, 2026-08-13)")


def test_a_repo_that_already_declares_is_proven_and_not_reproposed(tmp_path, wired):
    """Also the positive twin of the refusal below: a repository on the product's own name
    is read, proven and never mistaken for one on the former name."""
    origins, forge, proved = wired
    origins["acme/api"] = _origin(tmp_path, "api", with_manifest=True)

    out = ob.onboard_source_repo(_project(), "acme/api")

    assert out.manifest_already_there
    assert proved["saved"], "the existing manifest was not proven"
    if forge.opened:  # the map may still be new — but never the manifest
        shown = forge.opened[0]["body"]
        assert "already declares its manifest" in shown


def test_TWO_repos_get_two_prs_each_proven_on_its_own_key(tmp_path, wired):
    """The enterprise shape: front + back, one product — N proofs, N pull requests."""
    origins, forge, proved = wired
    origins["acme/api"] = _origin(tmp_path, "api")
    origins["acme/web"] = _origin(tmp_path, "web", default_branch="master")

    project = _project()
    first = ob.onboard_source_repo(project, "acme/api")
    second = ob.onboard_source_repo(project, "acme/web")

    assert first.ok and second.ok, (first.detail, second.detail)
    assert len(forge.opened) == 2
    assert proved["saved"] == ["dsk", "dsk--acme--web"], (
        f"the proofs are not keyed per repo: {proved['saved']}")
    assert forge.opened[1]["base"] == "master", (
        "the second repo's PR base must be ITS default branch, not the first one's")


def test_the_temp_clone_is_removed_however_it_ends(tmp_path, wired, monkeypatch):
    origins, _, _ = wired
    origins["acme/api"] = _origin(tmp_path, "api")
    made: list[Path] = []
    from openfactory.onboarding import propose_manifest as pm

    real = pm.clone_for_proposal

    def _remember(**kw):
        path, why = real(**kw)
        if path is not None:
            made.append(path)
        return path, why

    monkeypatch.setattr("openfactory.onboarding.propose_manifest.clone_for_proposal", _remember)
    monkeypatch.setattr("openfactory.onboarding.onboard.clone_for_proposal", _remember,
                        raising=False)

    ob.onboard_source_repo(_project(), "acme/api")

    assert made and not made[0].exists(), "the onboarding clone survived"


def test_on_an_app_only_deployment_the_minted_token_reaches_the_clone(tmp_path, wired,
                                                                      monkeypatch):
    """The flagship GitHub shape holds NO static token (the guide says to leave
    OPENFACTORY_BOT_TOKEN empty) — without the `or github_app_token_from_env()` fallback the
    whole verb died at the first private clone (adversarial review, 2026-08-13)."""
    origins, forge, _ = wired
    origins["acme/api"] = _origin(tmp_path, "api")
    seen: dict[str, str | None] = {}

    def _record(view, repo, token=None):
        seen["token"] = token
        return str(origins[repo])

    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "")
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for", _record)

    out = ob.onboard_source_repo(_project(), "acme/api")

    assert out.ok, out.detail
    assert seen["token"] == "ghs_minted", (
        f"the clone was asked for with token={seen['token']!r} — the App mint never reached it")


# ── the door refuses a repository on the directory's former name — before it writes ────────────

def test_a_repository_on_the_retired_name_is_REFUSED_by_name_and_nothing_is_written(
        tmp_path, wired, monkeypatch):
    """The first door a new client walks through. The loader's refusal is a `FileNotFoundError`,
    and the "undeclared" arm read it as exactly that: inferred a manifest, wrote
    `.openfactory/project.yaml` over a repository that HAS one under the former name, proved the
    box on the inferred one and opened a pull request whose body never mentioned the file that
    exists (review, 2026-08-25 — reproduced through these seams). Refused by name instead, and
    NOTHING is inferred, proven, pushed or proposed: the sentence says what to rename."""
    origins, forge, proved = wired
    origins["acme/api"] = _origin(tmp_path, "api", retired=True)

    def _never_infer(*_a, **_k):
        raise AssertionError("a manifest was INFERRED for a repository that has one")

    # the MODULE, by import: the `openfactory.onboarding` package re-exports `infer` as a
    # function, so a dotted path resolves to the function and not to the module the verb imports
    import importlib

    monkeypatch.setattr(importlib.import_module("openfactory.onboarding.infer"), "infer",
                        _never_infer)

    out = ob.onboard_source_repo(_project(), "acme/api")

    assert not out.ok
    assert ".sdlc/project.yaml" in out.detail and ".openfactory/" in out.detail, (
        f"the refusal must name the file it found AND the directory to rename it to: {out.detail}")
    assert "rename" in out.detail.lower(), out.detail
    assert not out.manifest_already_there, (
        "a refused repository was reported as declaring its manifest")
    assert not proved["saved"], "a box proof was taken on a refused repository"
    assert not forge.opened, "a pull request was opened on a refused repository"
    heads = subprocess.run(["git", "ls-remote", "--heads", str(origins["acme/api"])],
                           capture_output=True, text=True).stdout
    assert "refs/heads/main" in heads, heads  # the remote is intact and readable …
    assert "openfactory/onboard" not in heads, (
        f"… and a branch was pushed to a refused repository: {heads}")

"""The module map is published beside the concepts — in the context repository, never into the
source.

THE FIRST LIVE ONBOARDING SHOWED THE HOLE (2026-09-06). The source pull request carried
`knowledge/` — 836 lines of generated YAML whose checksums go stale at the next merge, proposed
into a client's `main`, against D-2 (the source repositories are never written to) and D-3
(`.okf/`, not `knowledge/`) — while the context box published five concepts, an inventory and an
index and NO map. `pipeline.fetch_bundle` recognises a published bundle by `modules.yaml` +
`manifest.yaml`, so every job would have found "no bundle" at a path holding five concepts:
nothing injected, and the gate (ADR-0046) with nothing to judge, until a merge triggered the
refresh that publishes the map. A freshly onboarded project was dark exactly when it most needed
the map.

What this file holds:
  1. the context box writes `modules.yaml` + `manifest.yaml` at `.okf/repos/<source>/`, in the
     same commit as the documents and the concepts;
  2. OUTSIDE the concept budget — a project that budgets 0 concepts still gets its map, which
     costs nothing;
  3. the job's own reader finds what the onboarding published;
  4. `write_bundle_dir` writes exactly where it is told — no `knowledge/` appended.
The source pull request never carrying the map is pinned where that request is built:
`test_onboard_proposes_a_measured_setup.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.knowledge.bundle import (
    MANIFEST_FILE,
    MODULES_FILE,
    build_bundle,
    read_bundle_dir,
    write_bundle_dir,
)
from openfactory.knowledge.pipeline import discard_fetched_bundle, fetch_bundle, okf_subpath
from openfactory.onboarding import onboard as ob


def _bare(tmp_path: Path, name: str, *, seed: dict[str, str] | None = None) -> Path:
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True,
                   capture_output=True)
    if seed:
        work = tmp_path / f"seed-{name}"
        work.mkdir()
        for rel, body in seed.items():
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        for args in (["init", "-b", "main"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"],
                     ["remote", "add", "origin", str(bare)], ["push", "-u", "origin", "main"]):
            subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)
    return bare


class _Forge:
    def __init__(self):
        self.opened: list[dict] = []

    def pr_for_head(self, head, *, repo=""):
        return ""

    def list_branches(self, repo="", *, prefix=""):
        return []

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "body": body})
        return f"https://github.com/{repo}/pull/2"

    def push_remote(self):
        return None


def _project(docs_repo: str) -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind="github", repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"),
                   product=ProductConfig(docs_repo=docs_repo))


SEED = {"pkg/app.py": "def main():\n    return 1\n",
        "pkg/billing/rules.py": "def charge():\n    return 1\n"}


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A source repository, a context repository born empty, no harness credential — so the
    backfill is the deterministic half and the map is what this file measures."""
    origins: dict[str, Path] = {
        "acme/api": _bare(tmp_path, "api", seed=SEED),
        "acme/dsk-context": _bare(tmp_path, "ctx"),
    }
    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda view, repo, token=None: str(origins[repo]))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return origins


def _first_commit_files(bare: Path) -> str:
    return subprocess.run(["git", "show", "--name-only", "--format=", "main"], cwd=bare,
                          capture_output=True, text=True).stdout


HOME = okf_subpath("acme/api")


def test_the_context_box_publishes_the_map_beside_the_concepts(wired):
    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    shown = _first_commit_files(wired["acme/dsk-context"])
    for name in (MODULES_FILE, MANIFEST_FILE):
        assert f"{HOME}/{name}" in shown, f"{name} is not beside the concepts: {shown}"
        assert str(HOME / name) in out.documents, (
            f"{name} was written but not reported among the documents: {out.documents}")
    assert f"{HOME}/okf.yaml" in shown, "the concepts' manifest should share the commit"
    assert "knowledge/" not in shown, f"the map landed under `knowledge/` (D-3): {shown}"


def test_the_map_is_published_even_when_no_concept_is_budgeted(wired, monkeypatch):
    monkeypatch.setattr(ob, "_concept_budget", lambda project, source: 0)

    out = ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"])

    assert out.ok, out.detail
    shown = _first_commit_files(wired["acme/dsk-context"])
    assert f"{HOME}/{MODULES_FILE}" in shown, (
        f"a budget of 0 concepts must not withhold the map, which costs nothing: {shown}")
    assert f"{HOME}/okf.yaml" not in shown, "no concept was budgeted, none should be written"


def test_the_job_finds_the_map_the_onboarding_published(wired):
    assert ob.onboard_product_context(_project("acme/dsk-context"), sources=["acme/api"]).ok

    fetched = fetch_bundle(str(wired["acme/dsk-context"]), subpath=HOME)
    try:
        assert fetched.path is not None, (
            f"the job's reader sees no bundle where the onboarding published one ({fetched})")
        bundle = read_bundle_dir(fetched.path)
        assert bundle is not None and bundle.module_map.modules, "the published map is empty"
    finally:
        if fetched.path is not None:
            discard_fetched_bundle(fetched.path)


def test_write_bundle_dir_writes_exactly_where_it_is_told(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    dest = tmp_path / "ctx" / ".okf" / "repos" / "acme--api"

    written = write_bundle_dir(build_bundle(repo), dest)

    assert written == dest
    assert (dest / MODULES_FILE).is_file() and (dest / MANIFEST_FILE).is_file()
    assert not (dest / "knowledge").exists(), "`knowledge/` was appended to the directory named"
    assert write_bundle_dir(build_bundle(repo), dest) is None, (
        "unchanged sources must report nothing to commit, as write_bundle does")

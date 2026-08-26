"""`knowledge build` works on the project shape the compose worker actually has.

The third sighting of the same bug (the refresh activity's own comment records the first two):
`Path(project.repo_path)` — which for a project the factory cloned itself (registered by its
clone URL) is not a directory at all, so the command walked a nonexistent path and reported a
map of nothing. Found the moment the module map became a RECOMMENDED onboarding step
(2026-08-13): the step would have failed for exactly the operator it was recommended to.

And the half that makes the fix real: the cache clone is DISPOSABLE — a map written only there
evaporates at the next fetch — so for a factory-cloned project the command says so, and
`--publish` pushes the map to the repository's knowledge branch, where the next job reads it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openfactory.cli import app


@pytest.fixture
def url_registered(tmp_path, monkeypatch):
    """A URL-registered project whose 'clone' the cache resolves to a real local repo."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    src = tmp_path / "clone"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    for args in (["init", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True)
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    import openfactory.factory as factory

    monkeypatch.setattr(factory, "resolve_repo_path",
                        lambda project, **kw: src)
    return src


def test_build_resolves_through_the_cache_not_through_Path_of_a_url(url_registered):
    result = CliRunner().invoke(app, ["knowledge", "build", "demo"])

    assert result.exit_code == 0, result.output
    assert (url_registered / "knowledge" / "modules.yaml").is_file(), (
        "no bundle was written where the resolver pointed")
    assert "modules" in result.output


def test_without_publish_the_disposable_clone_warning_speaks(url_registered):
    result = CliRunner().invoke(app, ["knowledge", "build", "demo"])

    assert "--publish" in result.output
    assert "replaces" in result.output, (
        "the operator is not told the map lives in a directory the next fetch replaces")


def test_publish_pushes_through_the_pipeline_and_reports_the_branch(url_registered, monkeypatch):
    seen = {}

    def _publish(dest, url, *, source_commit="", author=("", "")):
        seen.update(dest=Path(dest), url=url, author=author)
        return True

    monkeypatch.setattr("openfactory.knowledge.pipeline.publish_bundle", _publish)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r, token=None: "https://github.com/acme/demo.git")
    result = CliRunner().invoke(app, ["knowledge", "build", "demo", "--publish"])

    assert result.exit_code == 0, result.output
    assert seen.get("url") == "https://github.com/acme/demo.git"
    assert "knowledge branch" in result.output


def test_a_failed_publish_is_a_failure_not_a_shrug(url_registered, monkeypatch):
    monkeypatch.setattr("openfactory.knowledge.pipeline.publish_bundle",
                        lambda *a, **kw: False)
    monkeypatch.setattr("openfactory.adapters.forge.registry.clone_url_for",
                        lambda p, r, token=None: "https://github.com/acme/demo.git")
    result = CliRunner().invoke(app, ["knowledge", "build", "demo", "--publish"])

    assert result.exit_code != 0
    assert "NOT published" in result.output
    assert "refresh will retry" in result.output, "the self-healing path must be named"


def test_a_local_checkout_still_works_exactly_as_before(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    src = tmp_path / "local"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    assert CliRunner().invoke(app, ["project", "add", "demo", str(src)]).exit_code == 0

    result = CliRunner().invoke(app, ["knowledge", "build", "demo"])

    assert result.exit_code == 0, result.output
    assert (src / "knowledge" / "modules.yaml").is_file()
    assert "--publish" not in result.output, (
        "a local checkout gets committed like any file — the warning is for the cache clone")


def test_write_bundle_replaces_inodes_never_truncating_a_hardlinked_master(tmp_path):
    """RepoCache snapshots are built with `copy_function=os.link`: every file shares its inode
    with the hidden master. An in-place truncate-write there rewrites the master and every
    snapshot a concurrent reader holds — os.replace of a fresh temp file swaps in a NEW inode
    instead (adversarial review, 2026-08-13)."""
    import os

    from openfactory.knowledge import build_bundle, write_bundle

    src = tmp_path / "repo"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "app.py").write_text("def main():\n    return 1\n")
    write_bundle(build_bundle(src, commit="c1"), src)

    master = tmp_path / "master-modules.yaml"
    os.link(src / "knowledge" / "modules.yaml", master)
    before = master.read_bytes()

    (src / "pkg" / "extra.py").write_text("def other():\n    return 2\n")
    write_bundle(build_bundle(src, commit="c2"), src, force=True)

    assert (src / "knowledge" / "modules.yaml").read_bytes() != before, (
        "the second write changed nothing, so this proves nothing")
    assert master.read_bytes() == before, (
        "the write went THROUGH the hardlink and mutated the master")

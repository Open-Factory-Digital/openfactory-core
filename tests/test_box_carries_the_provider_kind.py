"""Inside the sandbox, the tracker is the one the project configured (C-07).

The seam is honoured everywhere except in the one place the work actually happens. The box
re-registers its project from environment variables and hardcodes the answer:

    tracker=ProviderRef(kind="github", repo=cfg.repo, options=opts)

So a Jira deployment gets a correct tracker on the worker, launches a job, and the job builds a
GitHub client inside the container. The failure is the expensive shape ADR-0022 names: not a
missing provider but a WRONG one, authenticating against the wrong host with the wrong token, and
surfacing as a permissions problem.

`BoxConfig` is transported as environment variables, so this is a three-part change — the config
carries it, the launcher exports it, the box reads it — and any one of the three left out is a
silent revert. The tests below pin all three plus the seam between them.
"""

from __future__ import annotations

import add_ons
import pytest

from openfactory.contracts.project import Project, ProviderRef
from openfactory.runtime.boxed_job import BoxConfig, config_from_env


def _env(**over) -> dict[str, str]:
    base = {"OPENFACTORY_PROJECT": "demo", "OPENFACTORY_ISSUE": "CONT-412", "OPENFACTORY_REPO": "acme/app"}
    base.update(over)
    return base


# ── the config carries it ───────────────────────────────────────────────────────────────────────

def test_the_box_config_carries_the_tracker_and_forge_kinds():
    cfg = BoxConfig(project="demo", issue="1", repo="a/b",
                    tracker_kind="jira", forge_kind="gitlab")
    assert (cfg.tracker_kind, cfg.forge_kind) == ("jira", "gitlab")


def test_the_kinds_default_to_github_for_a_box_launched_by_an_older_worker():
    """A deploy replaces the worker while jobs are in flight. A box launched by the previous
    build has no `OPENFACTORY_TRACKER_KIND` in its environment, and must keep behaving exactly as it did
    rather than failing on an absent variable. The default is a MIGRATION window, not a
    preference — it is the one place a vendor name is still allowed to be assumed."""
    cfg = config_from_env(_env())
    assert cfg.tracker_kind == "github"
    assert cfg.forge_kind == "github"


# ── the box reads it ────────────────────────────────────────────────────────────────────────────

def test_the_box_reads_the_kinds_from_its_environment():
    cfg = config_from_env(_env(OPENFACTORY_TRACKER_KIND="jira", OPENFACTORY_FORGE_KIND="gitlab"))
    assert (cfg.tracker_kind, cfg.forge_kind) == ("jira", "gitlab")


def test_an_empty_kind_in_the_environment_is_treated_as_absent():
    """`env["X"] = ""` is what a shell exports for an unset variable, and an empty kind reaching
    the registry would raise `unknown tracker ''` deep inside the job instead of at the door."""
    cfg = config_from_env(_env(OPENFACTORY_TRACKER_KIND="", OPENFACTORY_FORGE_KIND=""))
    assert (cfg.tracker_kind, cfg.forge_kind) == ("github", "github")


# ── the launcher exports it ─────────────────────────────────────────────────────────────────────

def test_the_launcher_puts_the_kinds_in_the_boxs_environment():
    """The middle link. Config and box can both be right while the value never crosses."""
    build_env_overrides = add_ons.module("openfactory.runtime.fargate.launcher").build_env_overrides

    pairs = build_env_overrides(BoxConfig(project="demo", issue="1", repo="a/b",
                                          tracker_kind="jira", forge_kind="gitlab"))
    env = {e["name"]: e["value"] for e in pairs}
    assert env["OPENFACTORY_TRACKER_KIND"] == "jira"
    assert env["OPENFACTORY_FORGE_KIND"] == "gitlab"


def test_the_activity_reads_the_kinds_off_the_project(monkeypatch, tmp_path):
    """The source of truth is the registered project, not a constant."""
    from openfactory.runtime.temporal import activities

    project = Project(
        name="demo", repo_path=str(tmp_path),
        tracker=ProviderRef(kind="jira", repo="CONT"),
        forge=ProviderRef(kind="gitlab", repo="acme/app"),
    )
    monkeypatch.setattr(activities.ProjectRegistry, "get", lambda self, name: project)
    box = activities._box_for(
        activities.RunJobInput(project="demo", issue="CONT-412", sandbox="fargate"))
    assert (box.tracker_kind, box.forge_kind) == ("jira", "gitlab")


# ── the whole point: what gets built inside the box ─────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["github", "jira"])
def test_the_registered_project_inside_the_box_uses_the_configured_kind(tmp_path, monkeypatch, kind):
    """The reachability guard. Everything above can pass while `_register` still hardcodes the
    answer — which is exactly the state this card found."""
    from openfactory.runtime import boxed_job as entrypoint

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    cfg = BoxConfig(project="demo", issue="1", repo="acme/app", tracker_kind=kind,
                    forge_kind=kind)
    project = entrypoint._project_for(cfg, repo_dir=tmp_path / "repo")
    assert project.tracker.kind == kind
    assert (project.forge.kind if project.forge else None) == kind


def test_a_jira_box_builds_a_jira_tracker(tmp_path, monkeypatch):
    """One level further than the model: the REGISTRY dispatch inside the box must land on the
    right client. A correct `Project` handed to a builder that ignores it changes nothing."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.runtime import boxed_job as entrypoint

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    cfg = BoxConfig(project="demo", issue="CONT-1", repo="CONT", tracker_kind="jira",
                    forge_kind="jira")
    project = entrypoint._project_for(cfg, repo_dir=tmp_path / "repo")
    tracker = build_tracker(project, token="x")
    assert "jira" in type(tracker).__name__.lower()

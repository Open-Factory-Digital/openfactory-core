"""Smoke tests for the foundation: contracts parse, the cascade/conformance works,
the registry round-trips. No adapters/orchestrator logic is exercised yet."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from openfactory.contracts import JobState, Manifest, Ticket
from openfactory.contracts.project import Project
from openfactory.policy import available_stacks, check, load_preset
from openfactory.registry import ProjectRegistry


def test_manifest_rejects_unknown_fields():
    # A typo must fail loud at parse time, not silently apply a default (no surprises). The
    # `validate:` alias must still be accepted (populate_by_name), so alias ≠ unknown.
    Manifest(validate={"test": "pytest"})  # alias accepted
    with pytest.raises(ValidationError):
        Manifest(max_cost=8)  # typo for max_cost_usd — must NOT be silently dropped


def test_manifest_bounds_reject_history_bomb_timeout():
    from openfactory.contracts.manifest import PostMergeDeploy

    PostMergeDeploy(workflow="deploy.yml", timeout_minutes=30)  # in range
    with pytest.raises(ValidationError):
        PostMergeDeploy(workflow="deploy.yml", timeout_minutes=0)  # instant spurious timeout
    with pytest.raises(ValidationError):
        PostMergeDeploy(workflow="deploy.yml", timeout_minutes=100000)  # history-event bomb


def test_presets_ship_python_node_terraform():
    assert {"python", "node", "terraform"} <= set(available_stacks())
    assert "test" in load_preset("python")["validate"]


def test_state_machine_has_refinement_and_pr_states():
    assert JobState.NEEDS_REFINEMENT in JobState
    assert JobState.PR_OPEN in JobState


def test_conformance_flags_missing_floor_validation(tmp_path: Path):
    # A manifest with no test/security and no components fails the floor.
    report = check(Manifest(), tmp_path)
    assert report.ok is False
    assert any("test" in i.message for i in report.issues if i.level == "error")


def test_conformance_passes_when_floor_satisfied(tmp_path: Path):
    manifest = Manifest(validate={"test": "pytest", "security": "bandit -r ."})
    report = check(manifest, tmp_path)
    assert report.ok is True


def test_conformance_inherits_validation_from_preset(tmp_path: Path):
    # A python component satisfies the floor via the preset, without repo-wide decl.
    data = {"components": {"backend": {"path": "app/", "stack": "python"}}}
    report = check(Manifest(**data), tmp_path)
    assert report.ok is True  # python preset provides test + security


def test_registry_round_trip(tmp_path: Path):
    reg = ProjectRegistry(path=tmp_path / "registry.yaml")
    reg.add(Project(name="demo", repo_path="/tmp/demo"))
    assert [p.name for p in reg.list()] == ["demo"]
    assert reg.get("demo").repo_path == "/tmp/demo"
    reg.remove("demo")
    assert reg.list() == []


def test_provider_axes_default_independently():
    from openfactory.contracts.project import Project, ProviderRef

    # single vendor: all three axes inherit
    p = Project(name="a", repo_path="/tmp/a", tracker=ProviderRef(kind="github", repo="o/a"))
    assert (p.tracker.kind, p.forge.kind, p.ci.kind) == ("github", "github", "github")

    # split: Jira tracker + GitLab forge → CI follows the forge, not the tracker
    q = Project(
        name="b",
        repo_path="/tmp/b",
        tracker=ProviderRef(kind="jira", repo="PROJ"),
        forge=ProviderRef(kind="gitlab", repo="g/b"),
    )
    assert (q.tracker.kind, q.forge.kind, q.ci.kind) == ("jira", "gitlab", "gitlab")


def test_ticket_minimal_parse():
    t = Ticket(id="#1", title="t", objective="o", repo="owner/x")
    assert t.depends_on == [] and t.base_branch is None

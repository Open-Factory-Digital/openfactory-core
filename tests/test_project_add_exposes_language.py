"""`Project.language` — the tech-lead/product default for speaking first — was real and wired
(`agent/registry.py::_language_of` reaches every human-facing role) but invisible: absent from
both example files, from the CLI's manifest starter, and unsettable from `sdlc project add`. An
operator onboarding a client would only find it by reading the contract's source.

`--language` on `project add` is the fix for the CLI half. The other half (the two `.example`
files, the config doc) has no code to test — this locks in the one part that can regress silently.
"""

from __future__ import annotations

from typer.testing import CliRunner

from openfactory.cli import app


def _add(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path / "repo"), *args])


def test_language_defaults_to_the_model_s_own_default_when_omitted(tmp_path, monkeypatch):
    """UNSET, not 'pt-BR' passed explicitly — the same reason `sdlc run --image` defaults to
    unset (ADR-0037 D4): a flag that always carries a value can never let the model's own
    default win, so a caller who wants pt-BR and a caller who says nothing would be
    indistinguishable, and the default would live in two places instead of one."""
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    result = _add(tmp_path, monkeypatch)

    assert result.exit_code == 0, result.output
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    saved = ProjectRegistry().get("demo")
    assert saved.language == Project.model_fields["language"].default


def test_language_is_settable_from_the_cli(tmp_path, monkeypatch):
    result = _add(tmp_path, monkeypatch, "--language", "en-US")

    assert result.exit_code == 0, result.output
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("demo").language == "en-US"


def test_the_registry_example_documents_it():
    """The gap this whole fix responds to: the field existed and worked, but nobody configuring
    a deployment from the tracked template would ever see it."""
    from pathlib import Path

    example = Path("deploy/registry.yaml.example").read_text()
    assert "language" in example

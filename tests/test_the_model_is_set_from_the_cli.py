"""`model:` gets a CLI surface — the field existed and the only way in was YAML inside the worker.

The pilot operator, reading the whole first hour looking for it: "where do we select the harness's model… honestly I did not see it anywhere." The field has existed since 2026-08-05
(contracts/project.py `model`, two shapes) and was reachable only by editing the registry file —
on compose, `docker compose exec worker vi`, the exact by-hand step the product exists to remove.

`project add --model` writes the single shape at registration; `project set-model` changes it
later and builds the per-role shape. The str→dict narrowing REFUSES (a blanket value would be
silently dropped for the other roles) — that refusal is the guard proven here.
"""

from __future__ import annotations

from typer.testing import CliRunner

from openfactory.cli import app


def _run(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return CliRunner().invoke(app, ["project", *args])


def _saved(tmp_path, monkeypatch, name="demo"):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return ProjectRegistry().get(name)


def test_add_takes_a_model_and_the_registry_carries_it(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, "add", "demo", str(tmp_path / "repo"),
                  "--model", "claude-fable-5")

    assert result.exit_code == 0, result.output
    assert _saved(tmp_path, monkeypatch).model == "claude-fable-5"


def test_set_model_single_form_covers_every_role(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, "add", "demo", str(tmp_path / "repo")).exit_code == 0
    result = _run(tmp_path, monkeypatch, "set-model", "demo", "gpt-5")

    assert result.exit_code == 0, result.output
    assert _saved(tmp_path, monkeypatch).model == "gpt-5"


def test_set_model_role_calls_build_the_per_role_shape(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, "add", "demo", str(tmp_path / "repo")).exit_code == 0
    assert _run(tmp_path, monkeypatch, "set-model", "demo", "gpt-5",
                "--role", "executor").exit_code == 0
    assert _run(tmp_path, monkeypatch, "set-model", "demo", "claude-opus-5",
                "--role", "reviewer").exit_code == 0

    assert _saved(tmp_path, monkeypatch).model == {"executor": "gpt-5",
                                                   "reviewer": "claude-opus-5"}


def test_narrowing_a_blanket_model_refuses_with_both_forms_named(tmp_path, monkeypatch):
    """model: 'x' for every role + --role would silently drop x for the other roles — the
    method cannot know whether that is wanted, so it refuses and names both explicit forms."""
    assert _run(tmp_path, monkeypatch, "add", "demo", str(tmp_path / "repo"),
                "--model", "claude-fable-5").exit_code == 0
    result = _run(tmp_path, monkeypatch, "set-model", "demo", "gpt-5", "--role", "executor")

    assert result.exit_code == 2
    assert "EVERY role" in result.output
    assert "set-model demo" in result.output
    assert _saved(tmp_path, monkeypatch).model == "claude-fable-5", "the refusal must not write"


def test_a_role_typo_is_refused_instead_of_writing_a_dead_key(tmp_path, monkeypatch):
    """`--role executer` would write a dict key NOTHING ever reads — a model that looks
    configured and is not, the signature defect. Caught by the measurement pass before it
    shipped; refused naming the real roles."""
    assert _run(tmp_path, monkeypatch, "add", "demo", str(tmp_path / "repo")).exit_code == 0
    result = _run(tmp_path, monkeypatch, "set-model", "demo", "gpt-5", "--role", "executer")

    assert result.exit_code == 2
    assert "executer" in result.output
    assert "executor" in result.output and "product" in result.output
    assert _saved(tmp_path, monkeypatch).model is None, "the refusal must not write"


def test_an_unknown_project_is_refused_by_name_with_the_two_registries_reminder(tmp_path,
                                                                                monkeypatch):
    result = _run(tmp_path, monkeypatch, "set-model", "ghost", "gpt-5")

    assert result.exit_code == 2
    assert "ghost" in result.output
    assert "worker has its own registry" in result.output

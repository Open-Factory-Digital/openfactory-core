"""`env apply` accepts a checkout PATH, exactly as `env read` always has.

The pilot operator, told to register his project a second time on the laptop before §3:
*"mas quero entender o porquê disso se o código fica todo no docker"*. Two halves to that
answer, and only one of them was design.

DESIGN, and it stays: the manifest is the CLIENT's file. It is written into their checkout,
reviewed in their diff, committed by them — never into the worker's cache clone, which nobody
reviews and which the next fetch replaces.

A WART, and it goes: `env read <path>` accepted a path or a name, while `env apply <name>`
demanded a registered name — so the funnel grew a second registration whose only purpose was to
let this verb resolve a directory it was about to be handed anyway. One registration, one
concept ("the worker's registry"), and the adopter never has to learn there are two.

The URL refusal is untouched: a project registered by clone URL still has no checkout here, and
that message is what says so.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory.cli import app


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    repo = tmp_path / "podbeam"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "podbeam"\nversion = "0.1.0"\n')
    return repo


#: The one field with no default — the platform refuses to write a manifest that declares
#: nothing, so every apply in this file answers it, exactly as a real session does.
_ANSWER = ["--set", "validate.test=pytest -q"]


def test_a_path_needs_no_registration_at_all(checkout):
    result = CliRunner().invoke(app, ["env", "apply", str(checkout), "--yes", *_ANSWER])

    assert result.exit_code == 0, result.output
    written = checkout / ".openfactory" / "project.yaml"
    assert written.is_file(), f"nothing was written: {result.output}"
    assert "pytest -q" in written.read_text()
    assert "there is no project called" not in result.output


def test_the_written_file_lands_in_the_checkout_not_in_the_platform(checkout, tmp_path):
    CliRunner().invoke(app, ["env", "apply", str(checkout), "--yes", *_ANSWER])

    assert (checkout / ".openfactory" / "project.yaml").is_file()
    assert not (tmp_path / ".openfactory").exists(), "it wrote outside the checkout"


def test_a_registered_name_still_works_unchanged(checkout):
    assert CliRunner().invoke(
        app, ["project", "add", "podbeam", str(checkout)]).exit_code == 0

    result = CliRunner().invoke(app, ["env", "apply", "podbeam", "--yes", *_ANSWER])

    assert result.exit_code == 0, result.output
    assert (checkout / ".openfactory" / "project.yaml").is_file()


def test_a_name_that_is_neither_registered_nor_a_directory_still_refuses_BY_NAME(checkout):
    result = CliRunner().invoke(app, ["env", "apply", "ghost", "--yes"])

    assert result.exit_code != 0
    assert "ghost" in result.output


def test_a_URL_registered_project_still_refuses_with_the_checkout_sentence(checkout, monkeypatch):
    """The fence that must NOT loosen: the worker's clone is a cache, not a place to write a
    file a human is supposed to review and commit."""
    assert CliRunner().invoke(
        app, ["project", "add", "byurl", "https://github.com/acme/byurl.git"]).exit_code == 0

    result = CliRunner().invoke(app, ["env", "apply", "byurl", "--yes"])

    assert result.exit_code != 0
    assert "clone URL" in result.output
    assert "no checkout here" in result.output

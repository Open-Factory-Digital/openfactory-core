"""`project init`'s closing lines are for the person at the terminal, not for us.

Two lines the pilot read on a successful run (2026-08-12), both ours-not-theirs:

  "· repo_path is a URL — commit .openfactory/project.yaml in the repository itself
   (template: openfactory/cli.py _MANIFEST_TEMPLATE)"

     — a Python constant in a source file, cited to somebody inside a container who has no
       editor and no clone of THIS repository. The manifest is written FOR them by the
       environment session (`env read` → `env apply`); that is the answer, and the annotated
       reference is a document.

  "what remains is the irreducible pair: 1. authorise the GitHub App … 2. authenticate the
   harness …"

     — printed unconditionally, so an operator who had just installed the App and pasted the
       harness token was told both were still pending. The command cannot know; `doctor` can.

The rule these guard: this platform's own source layout is never a remedy, and a closing
checklist may not assert a state the command did not measure.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from openfactory.cli import app

#: Anything that names our own tree at somebody: a module path, or a private constant.
_OUR_SOURCE = re.compile(r"openfactory/[\w/]+\.py|\b_[A-Z][A-Z0-9_]{3,}\b")


@pytest.fixture
def registered(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    from openfactory.adapters.tracker import github_board_setup

    monkeypatch.setattr(github_board_setup, "create_board",
                        lambda **kw: ("7", "https://github.com/users/acme/projects/7"))
    return lambda: CliRunner().invoke(app, ["project", "init", "demo"])


def test_the_url_case_points_at_the_command_that_writes_the_manifest(registered):
    result = registered()

    assert result.exit_code == 0, result.output
    assert "onboard demo" in result.output, (
        "the URL case must name the verb that proposes the manifest, proven, as a PR")
    assert "env read" in result.output, "the with-a-checkout session form must still be offered"
    assert "docs/project.yaml.example" in result.output
    assert not _OUR_SOURCE.search(result.output), (
        f"init cites this platform's own source at the operator: "
        f"{_OUR_SOURCE.findall(result.output)}")


def test_the_closing_lines_claim_no_state_the_command_never_measured(registered):
    """"What REMAINS" is a claim about the world; init measured neither the App's grant nor the
    harness token. It may list what it cannot do — it may not report them as outstanding."""
    result = registered()

    assert "what remains" not in result.output.lower()
    assert "no command can do for you" in result.output
    assert "doctor demo" in result.output, "the thing that CAN measure must be the next line"

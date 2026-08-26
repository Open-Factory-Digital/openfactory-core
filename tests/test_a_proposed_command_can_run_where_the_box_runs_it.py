"""The working directory is the part a read command loses (pilot, 2026-08-14).

A command read out of a client's CI carries an implicit location — GitHub Actions'
`working-directory:`, Azure Pipelines' `workingDirectory:`, a `cd` in a Makefile — and this
module proposes the TEXT, which the box then runs at the repository root. The pilot's first
proven manifest carried `npm ci` from a job that ran it in a front-end folder: at the root
there is no lockfile, so `box prove` reported the client's own pipeline as broken, on a command
that runs green in their CI every day.

The synthesis half already refused exactly this ("NO LOCKFILE, NO PROPOSAL"). The OBSERVED half
— the stronger tier, the one we trust more — had no such rule, so better evidence produced the
worse manifest.

WRITTEN FOR THE NEXT CLIENT, NOT THIS ONE. The operator's standing instruction while this was
being fixed: *"vamos lembrando que colocaremos em ADO com c# front em typescript"*. So the rule
is a table of tool → the file it needs where it runs, covering every stack this module's own
classifier recognises, and the cases below lead with .NET + TypeScript in one repository.

  1. a bare command whose file is elsewhere is LEFT OUT of `setup:` and ASKED about, naming the
     directory the file is actually in — every item in `setup:` must run, and one that cannot
     takes the whole install down with it;
  2. a command that NAMES ITS TARGET is left alone: `dotnet restore src/Api/Api.csproj` runs
     from the root exactly as its pipeline runs it;
  3. a command whose file IS at the root is left alone;
  4. the question carries the evidence — which file it was read from — so a reviewer can check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.onboarding.infer import infer


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    return root


_ADO_PIPELINE = """
trigger: [main]
steps:
  - script: dotnet restore
    workingDirectory: src
  - script: npm ci
    workingDirectory: web
  - script: dotnet test src/Api.Tests/Api.Tests.csproj --nologo
"""


def test_a_bare_command_whose_file_lives_elsewhere_is_asked_about_not_proposed(tmp_path):
    """The enterprise shape: .NET under `src/`, TypeScript under `web/`, one Azure pipeline that
    changes directory for each. Neither install can run at the root, and proposing them means
    proposing a manifest whose own proof cannot pass."""
    root = _repo(tmp_path, {
        "azure-pipelines.yml": _ADO_PIPELINE,
        "src/Api/Api.csproj": "<Project />",
        "src/Api.Tests/Api.Tests.csproj": "<Project />",
        "web/package.json": '{"name": "ui"}',
        "web/package-lock.json": '{"lockfileVersion": 3}',
    })

    proposal = infer(root)

    setup = proposal.fields["setup"].value or []
    assert "npm ci" not in setup, (
        "a command that cannot run at the root was proposed anyway — its proof can only fail")
    asked = " ".join(proposal.questions)
    assert "npm ci" in asked, "the command was dropped silently"
    assert "package-lock.json" in asked, "the reason is not named"
    assert "web" in asked, "the directory the file IS in — the useful half — is not named"


def test_a_command_that_names_its_target_is_left_alone(tmp_path):
    """`dotnet restore src/Api/Api.csproj` is located by its own argument. Deferring it would
    delete a correct line over a file it never needed at the root."""
    root = _repo(tmp_path, {
        "azure-pipelines.yml": (
            "steps:\n"
            "  - script: dotnet restore src/Api/Api.csproj\n"
            "  - script: dotnet test src/Api.Tests/Api.Tests.csproj --nologo\n"
        ),
        "src/Api/Api.csproj": "<Project />",
        "src/Api.Tests/Api.Tests.csproj": "<Project />",
    })

    proposal = infer(root)

    setup = proposal.fields["setup"].value or []
    assert any("dotnet restore" in c for c in setup), (
        f"a self-locating command was deferred: {setup} / {proposal.questions}")


def test_a_command_whose_file_is_at_the_root_is_left_alone(tmp_path):
    root = _repo(tmp_path, {
        ".github/workflows/ci.yml": (
            "jobs:\n  test:\n    steps:\n"
            "      - run: npm ci\n"
            "      - run: npm test\n"
        ),
        "package.json": '{"name": "app"}',
        "package-lock.json": '{"lockfileVersion": 3}',
    })

    proposal = infer(root)

    assert "npm ci" in (proposal.fields["setup"].value or []), (
        "the rule fired on a repository where the lockfile is exactly where the box will look")


@pytest.mark.parametrize("command, marker, files", [
    ("dotnet restore", ".sln", {"src/App/App.csproj": "<Project />"}),
    ("mvn -B verify", "pom.xml", {"service/pom.xml": "<project/>"}),
    ("go mod download", "go.mod", {"api/go.mod": "module x"}),
    ("cargo fetch", "Cargo.toml", {"engine/Cargo.toml": "[package]"}),
    ("bundle install", "Gemfile", {"site/Gemfile": "source 'x'"}),
    ("poetry install", "poetry.lock", {"svc/poetry.lock": ""}),
])
def test_the_rule_is_a_table_every_stack_shares(tmp_path, command, marker, files):
    """Not a special case for one package manager: the same sentence for whatever the client
    brought. A stack missing from this table is a row to add, not a redesign."""
    from openfactory.onboarding.infer import _runs_somewhere_else

    class _Tree:
        def __init__(self, names):
            self.files = set(names)

    needs, where = _runs_somewhere_else(command, _Tree(files))

    assert needs, f"`{command}` was accepted with no {marker} anywhere the box will look"
    assert where == str(Path(next(iter(files))).parent), (
        f"the directory that DOES hold it is not reported for `{command}`")

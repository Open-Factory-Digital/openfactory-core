"""ADR-0049 slice 4a — a filesystem path registers as `local`, on every axis, at every door.

THREE DOORS REGISTER A PROJECT and they did not agree about what an address means:

  `openfactory project init`   refused a foreign host by name (#162) and wrote one or two axes
  `openfactory project add`    asked no host at all, and wrote `tracker=` alone
  `POST /api/projects`         asked no host at all, carried `provider="github"` as a MODEL
                               DEFAULT, and wrote `tracker=` alone

So the same GitLab URL was refused on one command line and written as a GitHub row from the panel
beside it — and the row is what hands a github.com credential to whatever host the URL actually
names. A path on the operator's own disk was written as GitHub by all three.

WHAT THE RULE IS (D2), in four readings, held by `doors.kind_for`:

  1. a kind the operator NAMED is theirs, and `foreign_host` judges whether it may claim the host;
  2. Azure DevOps coordinates in the URL name Azure DevOps;
  3. any other URL takes the kind whose host it belongs to, and a host nobody owns is refused BY
     NAME at the door before anything is written;
  4. a filesystem path is `local` — unless coordinates came with it, which is an operator saying
     this checkout is of a hosted repository, a shape that runs today and must keep running.

AND `local` IS WRITTEN ON EVERY AXIS. An axis left unwritten inherits `ProviderRef`'s `github`
default, so a local project would be handed the deployment's GitHub credential and asked to open
a pull request on a repository nobody named.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory import doors
from openfactory.cli import app
from openfactory.registry import ProjectRegistry

runner = CliRunner()


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return ProjectRegistry


@pytest.fixture
def a_repo(tmp_path):
    d = tmp_path / "myapp"
    d.mkdir()
    return str(d)


# ── 1. the rule itself ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("address, kw, expected, why", [
    ("/home/someone/code/myapp", {}, "local", "a bare path is the person's own repository"),
    ("/home/someone/code/myapp", {"repo": "o/r"}, "github",
     "a path WITH coordinates is a mounted checkout of a hosted repository"),
    ("/home/someone/code/myapp", {"provider": "azure_devops"}, "azure_devops",
     "a kind the operator named is theirs"),
    ("https://github.com/o/r.git", {}, "github", "a URL takes the kind whose host it is"),
    ("git@github.com:o/r.git", {}, "github", "an ssh remote is a URL too"),
    ("https://dev.azure.com/org/proj/_git/repo", {}, "azure_devops",
     "an Azure DevOps clone URL is on an Azure DevOps host"),
    ("https://dev.azure.com/org/proj", {}, "azure_devops",
     "an ADO address pasted without `_git` carries no coordinates and is STILL Azure DevOps — "
     "it used to fall through to a GitHub row on somebody's Azure organisation"),
    ("git@ssh.dev.azure.com:v3/org/proj/repo", {}, "azure_devops", "the ssh shape too"),
    ("https://acme.visualstudio.com/proj/_git/repo", {}, "azure_devops",
     "the legacy host is a SUBDOMAIN — an exact-match reading would call this nobody's"),
    ("https://gitlab.com/o/r.git", {}, "github",
     "a host nobody owns is refused BY NAME at the door — never silently typed as something"),
])
def test_the_kind_an_address_is(address, kw, expected, why):
    assert doors.kind_for(address, **kw) == expected, why


def test_a_relative_path_is_local_too():
    """`.` is what somebody standing in their own repository types."""
    assert doors.kind_for(".") == "local"


# ── 2. the three doors write it ─────────────────────────────────────────────────────────────────

def test_project_add_writes_every_axis_for_a_path(registry, a_repo):
    result = runner.invoke(app, ["project", "add", "myapp", a_repo])
    assert result.exit_code == 0, result.output

    p = registry().get("myapp")
    assert (p.tracker.kind, p.forge.kind, p.ci.kind) == ("local", "local", "none"), (
        "an axis left unwritten inherits `github` and takes the deployment's credential with it")
    assert p.tracker.repo == "myapp" and p.forge.repo == "myapp", (
        "four consumers need a non-empty repo — the tech-lead's conversation and diagnosis, the "
        "product board, the knowledge pipeline")


def test_project_add_keeps_the_hosted_kind_when_coordinates_come_with_the_path(registry, a_repo):
    """The shape that runs today: a mounted checkout of a GitHub repository."""
    result = runner.invoke(app, ["project", "add", "myapp", a_repo, "--repo", "o/r"])
    assert result.exit_code == 0, result.output
    assert registry().get("myapp").tracker.kind == "github"


def test_project_add_REFUSES_a_foreign_host_the_way_project_init_always_has(registry):
    """It asked nothing at all before, one command along in the same help text."""
    result = runner.invoke(app, ["project", "add", "x", "https://gitlab.com/o/r.git"])

    assert result.exit_code == 2, result.output
    assert "gitlab.com" in result.output and "not a forge this build implements" in result.output
    assert registry().list() == [], "a refused address must leave no row behind"


def test_the_api_door_writes_every_axis_for_a_path(registry, a_repo, monkeypatch):
    from fastapi.testclient import TestClient

    from openfactory.api.app import app as api

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "")
    r = TestClient(api).post("/api/projects", json={"name": "myapp", "repo_path": a_repo})
    assert r.status_code == 200, r.text

    p = registry().get("myapp")
    assert (p.tracker.kind, p.forge.kind, p.ci.kind) == ("local", "local", "none")


def test_the_api_door_REFUSES_a_foreign_host(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from openfactory.api.app import app as api

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "")
    r = TestClient(api).post("/api/projects",
                             json={"name": "x", "repo_path": "https://gitlab.com/o/r.git"})

    assert r.status_code == 422, r.text
    assert "gitlab.com" in r.json()["detail"]
    assert registry().list() == []


def test_the_api_model_carries_NO_vendor_default():
    """A default here is a door answering a question nobody asked it — every project registered
    from the panel, a path on the operator's own disk included, was written as GitHub."""
    from openfactory.api.app import NewProject

    assert NewProject(name="x", repo_path="/tmp/x").provider == ""


# ── 3. one definition, three doors ──────────────────────────────────────────────────────────────

def test_every_registering_door_asks_the_SAME_two_questions():
    """The reachability half. A door that stops asking passes every test above — it just quietly
    writes the wrong row, which is exactly how the three came to disagree."""
    import inspect

    from openfactory import cli
    from openfactory.api import app as api_module

    for where, src in (("project add / project init", inspect.getsource(cli)),
                       ("POST /api/projects", inspect.getsource(api_module.add_project))):
        assert "kind_for(" in src, f"{where} decides the kind on its own"
        assert "foreign_host(" in src, f"{where} does not ask whose host it is"

    assert inspect.getsource(cli).count("doors.kind_for(") == 2, (
        "the two CLI doors must each ask — a shared helper nobody calls twice is one door short")


def test_an_ADO_address_without_its_coordinates_is_REFUSED_by_name_not_written_as_github(
        registry):
    """The half a person actually meets. Before this, `project add` read no `_git` segment, fell
    to GitHub, and wrote a row whose credential belongs to another company's host — the failure
    then arrives at the first ticket, as a 404 on a repository that was never named."""
    result = runner.invoke(app, ["project", "add", "x", "https://dev.azure.com/org/proj"])

    assert result.exit_code == 2, result.output
    assert "coordinates" in result.output, result.output
    assert registry().list() == [], "a refused address must leave no row behind"

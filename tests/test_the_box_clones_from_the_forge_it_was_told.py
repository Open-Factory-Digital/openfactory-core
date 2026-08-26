"""The boxed job cloned from github.com whatever the forge (#162).

`boxed_job.clone_url` spelled `https://…@github.com/{repo}.git` by hand and never read
`BoxConfig.forge_kind` — a field carried into the box since the day it stopped hardcoding its
provider, consumed for the tracker and the project registration and by nobody for this. So a boxed
job on an Azure DevOps deployment cloned a github.com URL for a repository that lives at
`dev.azure.com/{org}/{project}/_git/{repo}`.

IT WAS NEVER A HOST SUBSTITUTION. Azure Repos nests THREE coordinates where GitHub's path takes
two, and the box was carrying neither of them: the kind travelled and the options did not, which
is half a seam. Building the URL through the port is the fix; carrying each axis's own coordinates
is what makes the port answerable at all.

And the credential class rides along. The box holds a GitHub App token and used to interpolate it
into whatever host the string named. `clone_url_for` exists precisely because the Azure row
refuses an ambient GitHub credential, so asking the port is also what stops a `ghs_…` secret from
being sent to dev.azure.com.
"""

from __future__ import annotations

import inspect
import json

import add_ons
import pytest

from openfactory.runtime import boxed_job as ep

GITHUB = ep.BoxConfig(project="p", issue="1", repo="o/r")
ADO = ep.BoxConfig(project="p", issue="1", repo="fx-ado", forge_kind="azure_devops",
                   forge_options={"organization": "contoso", "project": "Payments"})


# ── 1. the URL is the forge's, not this module's ────────────────────────────────────────────────

def test_an_azure_box_clones_from_AZURE():
    got = ep.clone_url(ADO, token=None)

    assert got == "https://dev.azure.com/contoso/Payments/_git/fx-ado"
    assert "github.com" not in got


def test_and_a_github_box_is_unchanged():
    assert ep.clone_url(GITHUB, token="tok") == "https://x-access-token:tok@github.com/o/r.git"


def test_a_github_ENTERPRISE_box_clones_from_their_own_host(monkeypatch):
    """The GitHub path paid for the weld too: the adapter has honoured `GH_HOST` for a while, so
    an Enterprise deployment read every other fact from their host and cloned from github.com."""
    monkeypatch.setenv("GH_HOST", "github.acme.com")

    assert "github.acme.com" in ep.clone_url(GITHUB, token="tok")


def test_the_box_never_sends_its_GITHUB_token_to_azure(monkeypatch):
    """The credential class. The box holds a GitHub App token and passes it to every clone; the
    Azure row refuses an ambient credential in favour of its own, and going through the port is
    what makes that refusal apply here."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)

    got = ep.clone_url(ADO, token="ghs_the_github_app_token")

    assert "ghs_the_github_app_token" not in got, (
        "a GitHub App secret was interpolated into a dev.azure.com URL")


def test_and_the_azure_credential_IS_used_when_the_deployment_has_one(monkeypatch):
    """The positive twin. Asserting only that the GitHub token is absent would pass on a URL that
    carries no credential at all, which is a clone that fails for everybody."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat_from_the_azure_axis")

    assert "pat_from_the_azure_axis" in ep.clone_url(ADO, token="ghs_github")


# ── 2. the remote the agent is left with carries nothing ────────────────────────────────────────

@pytest.mark.parametrize("cfg", [GITHUB, ADO], ids=["github", "azure"])
def test_the_origin_rewrite_is_CREDENTIAL_FREE_on_every_vendor(cfg, monkeypatch):
    """After cloning, `origin` is reset to a URL the sandboxed agent cannot push with. That
    property was a property of the GitHub spelling; it has to survive the port, and on Azure it
    nearly did not — the adapter's own credential would have come back had this asked
    `clone_url_for` for a tokenless URL instead of the adapter."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat_secret")

    got = ep.clone_url(cfg, token=None)

    assert "@" not in got, f"the agent is left with a credentialed remote: {ep.redact(got)}"


def test_the_clone_ACTUALLY_asks_for_both(monkeypatch, tmp_path):
    """Reachability. Every guard above calls `clone_url` directly, so a `_clone` still spelling a
    URL by hand would leave them all green. Driven through `_clone` with `git` stubbed."""
    asked: list = []

    def _fake(cmd, **kw):
        asked.append(cmd)
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ep.subprocess, "run", _fake)
    ep._clone(ADO, tmp_path / "repo", "ghs_token")

    urls = [c[c.index("clone") + 2] for c in asked if "clone" in c]
    assert urls and "dev.azure.com" in urls[0], f"the clone went to {urls}"
    resets = [c[-1] for c in asked if "set-url" in c]
    assert resets and "dev.azure.com" in resets[0] and "@" not in resets[0]


# ── 3. the coordinates travel, because the kind alone cannot be built from ──────────────────────

def test_a_kind_with_no_coordinates_REFUSES_rather_than_guessing():
    """The honest failure this replaced a wrong host with. An Azure adapter cannot be constructed
    without an organization and a project; saying so beats a 404 that reads like a repository
    somebody forgot to create."""
    naked = ep.BoxConfig(project="p", issue="1", repo="fx-ado", forge_kind="azure_devops")

    with pytest.raises(ValueError, match="organization"):
        ep.clone_url(naked, token=None)


def test_the_launcher_exports_each_axis_own_options():
    build_env_overrides = add_ons.module("openfactory.runtime.fargate.launcher").build_env_overrides

    env = {row["name"]: row["value"] for row in build_env_overrides(ADO)}

    assert json.loads(env["OPENFACTORY_FORGE_OPTIONS"]) == {"organization": "contoso",
                                                            "project": "Payments"}
    assert "OPENFACTORY_TRACKER_OPTIONS" not in env, (
        "an empty map is nothing to say and should not become a variable")


def test_and_the_box_reads_them_back():
    cfg = ep.config_from_env({
        "OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "1", "OPENFACTORY_REPO": "fx-ado",
        "OPENFACTORY_FORGE_KIND": "azure_devops",
        "OPENFACTORY_FORGE_OPTIONS": '{"organization": "contoso", "project": "Payments"}',
    })

    assert cfg.forge_options == {"organization": "contoso", "project": "Payments"}
    assert ep.clone_url(cfg, token=None) == "https://dev.azure.com/contoso/Payments/_git/fx-ado"


def test_a_malformed_options_map_is_ABSENT_rather_than_a_lost_run(capsys):
    """The box is the far end of a launch nobody is watching. Raising here loses a run over a
    variable; continuing loses at most the options the launcher meant to add — and says so."""
    cfg = ep.config_from_env({
        "OPENFACTORY_PROJECT": "p", "OPENFACTORY_ISSUE": "1", "OPENFACTORY_REPO": "o/r",
        "OPENFACTORY_TRACKER_OPTIONS": "{not json",
    })

    assert cfg.tracker_options == {}
    assert "could not read provider options" in capsys.readouterr().out


def test_a_box_launched_by_an_OLDER_worker_still_finds_its_board():
    """A deploy replaces the worker while jobs are in flight, so a box in the old shape — the two
    hand-picked keys and no map — has to keep working exactly as it did."""
    cfg = ep.BoxConfig(project="p", issue="1", repo="o/r",
                       board_owner="acme", board_number="7")

    project = ep._project_for(cfg, repo_dir=None)

    assert project.tracker.options == {"board_owner": "acme", "board_number": "7"}


def test_and_the_whole_map_wins_over_the_legacy_pair():
    """The merge order. A launcher that carries both is the new one, and its map already contains
    those two keys — letting the pair override would silently pin a moved board."""
    cfg = ep.BoxConfig(project="p", issue="1", repo="o/r",
                       board_owner="stale", board_number="1",
                       tracker_options={"board_owner": "acme", "board_number": "7"})

    assert ep._project_for(cfg, repo_dir=None).tracker.options["board_owner"] == "acme"


@pytest.mark.parametrize("axis", ["tracker", "forge"])
def test_the_two_axes_do_not_share_one_map(axis):
    """They were sharing `opts` before this, which is only invisible while both providers are the
    same vendor — a Jira-tracker / GitHub-forge project is the ordinary case the contract exists
    for."""
    cfg = ep.BoxConfig(project="p", issue="1", repo="o/r",
                       tracker_options={"site": "acme.atlassian.net"},
                       forge_options={"organization": "contoso"})

    got = getattr(ep._project_for(cfg, repo_dir=None), axis).options

    assert got == ({"site": "acme.atlassian.net"} if axis == "tracker"
                   else {"organization": "contoso"})


# ── 4. and the worker fills them in ─────────────────────────────────────────────────────────────

def test_the_worker_puts_the_projects_own_coordinates_ON_the_box():
    """Reachability again, and the half that would have kept every guard above green while no real
    deployment worked: the box can read options nobody ever sends."""
    import ast

    from openfactory.runtime.temporal import activities

    src = inspect.cleandoc("\n" + inspect.getsource(activities._box_for))
    given = {kw.arg for node in ast.walk(ast.parse(src)) if isinstance(node, ast.Call)
             for kw in node.keywords}

    assert {"forge_options", "tracker_options"} <= given, (
        "the worker builds a box that is told the KIND of each provider and none of its "
        "coordinates — the box then refuses, which is honest and still broken")

"""`credentials.*_token_for` finds the axis VENDOR's own variable before the generic pair.

The split the funnel review (2026-08-09) measured: the shared ADO client read `AZURE_DEVOPS_PAT`
on its own, so the adapters authenticated — while everything that asks "does this project HAVE a
credential" through `credentials.py` (the doctor's presence probe, the repo-cache fetch) answered
no. An ADO-only deployment with a perfectly good PAT was told "no forge credential is
configured", with a GitHub App remedy that could not have fixed it.

Order matters more than presence: the generic fallback (`OPENFACTORY_BOT_TOKEN`) is a GITHUB
credential on a mixed deployment, and handing it to an ADO axis presents it as HTTP Basic and
reads back a 401 — a configured-looking credential failing as if revoked. So the vendor default
sits BETWEEN the registry's `token_env` (always first: an explicit declaration) and the generic
pair (last: correct exactly while one vendor exists).
"""

from __future__ import annotations

import pytest

from openfactory.contracts.project import Project, ProviderRef
from openfactory.credentials import forge_token_for, tracker_token_for

_VENDOR_VARS = ("AZURE_DEVOPS_PAT", "JIRA_API_TOKEN", "OPENFACTORY_BOT_TOKEN",
                "OPENFACTORY_FORGE_TOKEN", "OPENFACTORY_TRACKER_TOKEN", "ACME_ADO_PAT")


@pytest.fixture(autouse=True)
def _clean_credential_env(monkeypatch):
    for name in _VENDOR_VARS:
        monkeypatch.delenv(name, raising=False)


def _ado(**options) -> Project:
    ref = ProviderRef(kind="azure_devops", repo="Deskline",
                      options={"organization": "acme", **options})
    return Project(name="dsk", repo_path="https://dev.azure.com/acme/Deskline/_git/api",
                   tracker=ref)


def test_an_ado_axis_finds_azure_devops_pat_with_nothing_named(monkeypatch):
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-pat")
    assert forge_token_for(_ado()) == "the-pat"
    assert tracker_token_for(_ado()) == "the-pat"


def test_the_vendor_default_beats_the_generic_github_shaped_fallback(monkeypatch):
    """Both set → the ADO axis gets the ADO credential, never the deployment's GitHub one."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-pat")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_github_shaped")
    assert forge_token_for(_ado()) == "the-pat"


def test_a_named_token_env_still_beats_the_vendor_default(monkeypatch):
    """The registry's declaration is explicit and always wins."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-shared-pat")
    monkeypatch.setenv("ACME_ADO_PAT", "this-project-s-own")
    assert forge_token_for(_ado(token_env="ACME_ADO_PAT")) == "this-project-s-own"


def test_a_github_axis_is_byte_for_byte_unchanged(monkeypatch):
    """AZURE_DEVOPS_PAT in the environment must never leak onto a GitHub axis."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-pat")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_mine")
    github = Project(name="gh", repo_path="/tmp/x",
                     tracker=ProviderRef(kind="github", repo="acme/api"))
    assert forge_token_for(github) == "ghp_mine"
    monkeypatch.delenv("OPENFACTORY_BOT_TOKEN")
    assert forge_token_for(github) is None


def test_a_jira_tracker_finds_jira_api_token(monkeypatch):
    monkeypatch.setenv("JIRA_API_TOKEN", "atlassian-token")
    jira = Project(name="j", repo_path="/tmp/x",
                   tracker=ProviderRef(kind="jira", repo="DAR",
                                       options={"site": "acme.atlassian.net"}))
    assert tracker_token_for(jira) == "atlassian-token"


def test_the_doctor_probe_without_any_credential_names_the_vendor(monkeypatch):
    """The consumer that made this matter: doctor's forge probe answers presence through
    `forge_token_for`. With nothing set, the failure must carry the axis's KIND so the Finding's
    remedy can name AZURE_DEVOPS_PAT rather than sending an ADO deployment to create a GitHub
    App — the exact wrong remedy the funnel review transcribed."""
    for name in ("OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_INSTALLATION_ID",
                 "OPENFACTORY_GH_APP_KEY_CONTENT", "OPENFACTORY_GH_APP_KEY"):
        monkeypatch.delenv(name, raising=False)
    from openfactory.doctor import _forge, probes_for

    probes = probes_for(_ado())
    reachable, detail = probes.forge_reachable()
    assert reachable is False
    assert "azure_devops" in detail

    finding = _forge(probes)
    assert "AZURE_DEVOPS_PAT" in finding.remedy
    assert "docs/setup/azure-devops.md" in finding.remedy
    assert "GitHub App" not in finding.remedy


def test_the_doctor_probe_with_the_pat_gets_past_presence(monkeypatch):
    """With AZURE_DEVOPS_PAT set the probe must reach the REACHABILITY half (a real HTTP call),
    not stop at 'no forge credential'. The call itself is stubbed at the adapter seam."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-pat")
    from openfactory.adapters.forge import azure_devops as forge_mod
    from openfactory.doctor import probes_for

    seen: dict = {}

    def _pr_status(self, *, pr):
        seen["asked"] = pr
        raise RuntimeError("TF401180: pull request not found")  # 404-shaped: allowed to ask

    monkeypatch.setattr(forge_mod.AzureReposForge, "pr_status", _pr_status, raising=True)
    reachable, _ = probes_for(_ado()).forge_reachable()
    assert seen["asked"] == "1"
    assert reachable is True

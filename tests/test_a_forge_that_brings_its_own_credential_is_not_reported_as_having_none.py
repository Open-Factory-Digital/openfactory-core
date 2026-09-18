"""The doctor asks the VENDOR'S ROW whether this deployment holds a forge credential (#170).

WHAT IT DID: presence was two readings, both in the doctor. A static token through
`forge_token_for`, and the three variables of ONE vendor's App (`app_id`, `app_installation_id`,
`app_private_key`), read by name in a check every vendor goes through. A vendor whose adapter
obtains its credential any other way was reported as having none, and the check returned before
its own reachability probe ran.

Reproduced on an Azure DevOps deployment with the static variable unset on purpose: the adapter
minted its token from the machine's `az` login, and in the same shell the deployment cloned a
repository, read back a declared context repository and opened pull requests. The doctor said
`FAIL forge_access  no forge credential is configured`, ended `NOT ready`, and told the operator
to create the static token the `az` path exists to avoid.

THE OTHER HALF OF THE SAME READING, and it was wrong in the opposite direction: the App variables
counted for EVERY vendor, so an Azure project on a machine that also holds a GitHub App was
reported as credentialed and walked on to its probe without one.

The row is where a vendor already declares its credential (`adapters/credential/registry.py`:
`env`, `mint`, `provider`, `discover`), so the presence check now asks it — `provider` for "can
this deployment produce one" — and the App test is GitHub's row answering. `az` is faked at the
process boundary (`subprocess.run`), under the real `_az_mint`, so the minter's own parsing and
caching are what answer.
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest

from openfactory.adapters import azure_devops as ado
from openfactory.contracts.project import Project, ProviderRef

#: The real minter, captured before `conftest._the_suite_never_borrows_this_machines_az_login`
#: replaces it for each test — the tests below that want an `az` login put it back and fake only
#: the subprocess, so what answers is the adapter's own path, not a stand-in for it.
_REAL_AZ_MINT = ado._az_mint

_CREDENTIAL_VARS = (
    "AZURE_DEVOPS_PAT", "OPENFACTORY_FORGE_TOKEN", "OPENFACTORY_BOT_TOKEN",
    "OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_INSTALLATION_ID",
    "OPENFACTORY_GH_APP_KEY", "OPENFACTORY_GH_APP_KEY_CONTENT", "ACME_FORGE_TOKEN",
)

JWT = "ey" + "J0eXAiOiJKV1QifQ.payload.signature"


@pytest.fixture(autouse=True)
def _no_credential_anywhere(monkeypatch):
    for name in _CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)


def _az(monkeypatch, *, logged_in: bool) -> list[list[str]]:
    """`az` at the process boundary: answers `get-access-token` like a logged-in CLI, or exits 1
    like one that is not. Every other command goes to the real `subprocess.run`. Returns the argv
    of each `az` call, so a test can count them."""
    real_run = subprocess.run
    calls: list[list[str]] = []

    def run(argv, *args, **kwargs):
        if isinstance(argv, list) and argv and argv[0] == "az":
            calls.append(list(argv))
            if not logged_in:
                return subprocess.CompletedProcess(argv, 1, "", "Please run 'az login'")
            body = json.dumps({"accessToken": JWT, "expires_on": int(time.time()) + 3600})
            return subprocess.CompletedProcess(argv, 0, body, "")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(ado, "_az_mint", _REAL_AZ_MINT)
    monkeypatch.setattr(ado, "_az_cached", None)
    monkeypatch.setattr(ado.subprocess, "run", run)
    return calls


def _probe_the_ado_forge(monkeypatch) -> dict:
    """The Azure forge's reachability read, stubbed at the adapter. Records the credential the
    adapter held when the doctor asked, so a test can tell the probe ran on the minted token."""
    from openfactory.adapters.forge import azure_devops as forge_mod

    seen: dict = {}

    def pr_status(self, *, pr, repo=""):
        seen["asked"] = pr
        seen["token"] = self.token
        raise RuntimeError("TF401180: pull request not found")  # 404-shaped: allowed to ask

    monkeypatch.setattr(forge_mod.AzureReposForge, "pr_status", pr_status, raising=True)
    return seen


def _ado() -> Project:
    ref = ProviderRef(kind="azure_devops", repo="api",
                      options={"organization": "acme", "project": "Deskline"})
    return Project(name="dsk", repo_path="https://dev.azure.com/acme/Deskline/_git/api",
                   tracker=ref, forge=ref)


def _app_trio(monkeypatch) -> None:
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----\nx\n")


# ── 1. the reported case: no static token, an `az` login, and the adapter mints from it ────────

def test_an_az_login_with_no_static_token_reaches_the_reachability_probe(monkeypatch):
    """The deployment that reported this: the variable unset on purpose, the CLI logged in. The
    doctor must go on to ask the forge — and the forge must be asked ON the minted token, which is
    what makes the green line mean something."""
    from openfactory.doctor import _forge, probes_for

    _az(monkeypatch, logged_in=True)
    seen = _probe_the_ado_forge(monkeypatch)

    reachable, detail = probes_for(_ado()).forge_reachable()

    assert "no forge credential" not in detail, (
        "an `az` login the adapter mints from is a credential this deployment holds; the doctor "
        f"reported none: {detail!r}")
    assert seen.get("asked") == "1", "the reachability probe never ran"
    assert seen.get("token") == JWT, "the probe ran without the credential the row provides"
    assert reachable is True
    finding = _forge(probes_for(_ado()))
    assert finding.ok, finding


def test_the_azure_row_declares_the_credential_its_adapter_brings(monkeypatch):
    """ON THE ROW, where every other vendor's credential path is declared — not only inside the
    forge registry's builder, where nothing that asks "does this deployment hold one" could see
    it. A provider, never a `mint`: see the row's docstring for what a `mint` would freeze."""
    from openfactory.adapters.credential.registry import credential_row

    row = credential_row("azure_devops")
    assert row is not None and row.provider is not None
    assert row.mint is None, (
        "a `mint` reaches `deployment_*_token`, whose value the tracker row freezes into its "
        "client for the whole job — an hour-long JWT captured at the start of a longer job")

    _az(monkeypatch, logged_in=True)
    provider = row.provider()
    assert provider is not None and provider() == JWT

    _az(monkeypatch, logged_in=False)
    assert row.provider() is None, "no login is no credential — the row must not claim one"


# ── 2. the true negative still refuses, and the remedy names BOTH paths ─────────────────────────

def test_no_static_token_and_no_az_login_still_fails_by_presence(monkeypatch):
    from openfactory.doctor import _forge, probes_for

    _az(monkeypatch, logged_in=False)
    seen = _probe_the_ado_forge(monkeypatch)

    reachable, detail = probes_for(_ado()).forge_reachable()

    assert reachable is False and "no forge credential" in detail and "azure_devops" in detail
    assert "asked" not in seen, "a deployment with no credential must not be probed as if it had one"
    finding = _forge(probes_for(_ado()))
    assert not finding.ok
    assert "az login" in finding.remedy, (
        "the remedy sent the operator to create a static token — the one thing the `az` path "
        f"exists to avoid — and never named the login: {finding.remedy!r}")
    assert "AZURE_DEVOPS_PAT" in finding.remedy
    assert "GitHub App" not in finding.remedy


def test_one_vendors_app_does_not_count_as_another_vendors_credential(monkeypatch):
    """The App trio is GITHUB's. An Azure project on a machine that also holds it has no Azure
    credential, and used to be walked past the presence check as if it did."""
    from openfactory.doctor import probes_for

    _app_trio(monkeypatch)
    _az(monkeypatch, logged_in=False)
    seen = _probe_the_ado_forge(monkeypatch)

    reachable, detail = probes_for(_ado()).forge_reachable()

    assert reachable is False and "no forge credential" in detail, detail
    assert "asked" not in seen


# ── 3. what must not move ────────────────────────────────────────────────────────────────────────

def test_a_static_token_never_spawns_az(monkeypatch):
    """The hosted deployment holds a PAT and no Azure CLI. Asking the row for its provider there
    would spawn `az` on every doctor run for nothing — the PAT already answers."""
    from openfactory.doctor import probes_for

    monkeypatch.setenv("AZURE_DEVOPS_PAT", "x" * 52)
    calls = _az(monkeypatch, logged_in=True)
    seen = _probe_the_ado_forge(monkeypatch)

    reachable, _ = probes_for(_ado()).forge_reachable()

    assert reachable is True and seen.get("asked") == "1"
    assert calls == [], f"the doctor spawned `az` with a PAT set: {calls}"


def test_the_github_app_is_still_a_credential_and_is_still_not_minted(monkeypatch):
    """GitHub's row answering what the doctor used to read by hand: the App trio is present, so
    the probe runs — and nothing is MINTED, because a diagnostic that mints spends."""
    from openfactory.adapters import github_app
    from openfactory.adapters.forge import github as gh_forge
    from openfactory.doctor import probes_for

    _app_trio(monkeypatch)
    monkeypatch.setattr(github_app, "mint_installation_token",
                        lambda **_: pytest.fail("the doctor minted an App token to check presence"))
    seen: dict = {}

    def pr_status(self, *, pr, repo=""):
        seen["asked"] = pr
        return "open"

    monkeypatch.setattr(gh_forge.GitHubForge, "pr_status", pr_status, raising=True)
    project = Project(name="gh", repo_path="/tmp/x",
                      tracker=ProviderRef(kind="github", repo="acme/api"),
                      forge=ProviderRef(kind="github", repo="acme/api"))

    reachable, detail = probes_for(project).forge_reachable()

    assert "no forge credential" not in detail
    assert seen.get("asked") == "1" and reachable is True


# ── 4. the reason it is asked of the row: a stranger's vendor answers the same way ─────────────

def test_a_strangers_row_that_provides_a_credential_is_believed(monkeypatch):
    """ASKED OF THE ROW, NEVER OF THE KIND. A third party's forge whose credential comes from its
    own provider — no variable, no App — declares that provider on its row and the doctor reads
    it the way it reads the shipped ones. Before, only one vendor's variables could make the
    check pass, so this vendor was told it had nothing."""
    from openfactory.adapters.credential import registry as cred
    from openfactory.adapters.forge import registry as forges
    from openfactory.doctor import probes_for

    seen: dict = {}

    class AcmeForge:
        def __init__(self, token=None):
            self.token = token

        def pr_status(self, *, pr, repo=""):
            seen["asked"] = pr
            return "open"

    monkeypatch.setitem(cred.CREDENTIALS, "acme",
                        lambda: cred.CredentialRow(env="ACME_FORGE_TOKEN",
                                                   provider=lambda: (lambda: "acme-minted")))
    monkeypatch.setitem(forges.FORGES, "acme", lambda project, **kw: AcmeForge(kw.get("token")))
    ref = ProviderRef(kind="acme", repo="acme/api")
    project = Project(name="acme", repo_path="/tmp/x", tracker=ref, forge=ref)

    reachable, detail = probes_for(project).forge_reachable()

    assert "no forge credential" not in detail, detail
    assert seen.get("asked") == "1" and reachable is True

"""The neutral path had a credential-forwarding primitive (#162, `factory.py`).

`_authenticated(url, token)` injected `x-access-token:<token>@` into ANY `https://` URL. One
vendor's spelling, no notion of whose host it was, on a path every checkout goes through.

TWO WAYS THAT GOES WRONG AND BOTH ARE REACHABLE:

  · A project registered as GitHub whose `repo_path` names another host receives this deployment's
    App token there. Not hypothetical — `project init` registers `kind="github"` for every URL
    that is not an Azure one, so a GitLab path arrives labelled GitHub.

  · An Azure project got GitHub's spelling, which Azure ACCEPTS (it ignores the username). So the
    weld looked correct on the second vendor while the thing actually at fault — an unconditional
    `github_app_token_from_env()` beside it — went on handing a `ghs_…` secret to dev.azure.com,
    where it comes back as a 401 that reads like a revoked credential.

The question "is this credential mine to put on this URL" belongs to the adapter, which is the
only thing that knows the host and the spelling. `authenticated_url` takes NO token for the same
measured reason `clone_url_for` ignores its caller's: every call site in this codebase hands the
forge axis a GitHub credential.
"""

from __future__ import annotations

import importlib
import inspect
import re

import pytest
from conftest import code_only

from openfactory.contracts.project import Project, ProviderRef
from openfactory.factory import _authenticated

GH_URL = "https://github.com/o/r.git"
ADO_URL = "https://dev.azure.com/contoso/Payments/_git/fx-ado"


def _github(repo_path=GH_URL):
    return Project(name="p", repo_path=repo_path,
                   tracker=ProviderRef(kind="github", repo="o/r"),
                   forge=ProviderRef(kind="github", repo="o/r"))


def _azure(repo_path=ADO_URL):
    return Project(name="p", repo_path=repo_path,
                   tracker=ProviderRef(kind="azure_devops", repo="fx-ado"),
                   forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                                     options={"organization": "contoso", "project": "Payments"}))


# ── 1. the leak, in both directions ─────────────────────────────────────────────────────────────

def test_a_github_token_does_not_reach_azure(monkeypatch):
    """The row the card calls a cross-vendor leak. An Azure project with no forge credential of
    its own used to be handed this deployment's GitHub App token, wrapped and sent."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)

    got = _authenticated(_azure(), ADO_URL, "ghs_the_app_token")

    assert "ghs_the_app_token" not in got
    assert got == ADO_URL, "an unauthenticated URL is the honest answer, and it is not what came back"


def test_and_the_azure_credential_IS_used_when_there_is_one(monkeypatch):
    """The positive twin. "The GitHub token is absent" is also true of a URL nobody authenticated,
    which would be a clone that fails for everyone."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat_from_the_azure_axis")

    got = _authenticated(_azure(), ADO_URL, "ghs_ignored")

    assert "pat_from_the_azure_axis" in got and "contoso:" in got


def test_a_gitlab_url_REGISTERED_AS_GITHUB_gets_no_token():
    """The other direction, and the reachable one: `project init` labels every non-Azure URL as
    GitHub, so the registry itself produces this row."""
    got = _authenticated(_github(repo_path="https://gitlab.com/o/r.git"),
                         "https://gitlab.com/o/r.git", "ghs_the_app_token")

    assert got == "https://gitlab.com/o/r.git"


def test_a_github_project_is_UNCHANGED():
    assert _authenticated(_github(), GH_URL, "ghs_tok") == (
        "https://x-access-token:ghs_tok@github.com/o/r.git")


def test_a_github_ENTERPRISE_host_is_this_deployments_github(monkeypatch):
    monkeypatch.setenv("GH_HOST", "github.acme.com")
    url = "https://github.acme.com/o/r.git"

    assert _authenticated(_github(repo_path=url), url, "ghs_tok").startswith(
        "https://x-access-token:ghs_tok@github.acme.com/")


def test_and_then_github_com_is_NOT(monkeypatch):
    """The reverse of the row above, and the one that matters: an Enterprise deployment's token
    must not be sent to public github.com because the URL happens to say GitHub."""
    monkeypatch.setenv("GH_HOST", "github.acme.com")

    assert _authenticated(_github(), GH_URL, "ghs_tok") == GH_URL


@pytest.mark.parametrize("url", [
    "git@github.com:o/r.git",
    "ssh://git@github.com/o/r.git",
    "https://someone:already@github.com/o/r.git",
])
def test_a_url_that_carries_its_own_auth_is_left_alone(url):
    """A deployment with a credential helper or a deploy key: rewriting either is how a working
    setup starts failing after an upgrade."""
    assert _authenticated(_github(repo_path=url), url, "ghs_tok") == url


def test_an_AZURE_project_does_not_send_its_PAT_to_github(monkeypatch):
    """The mirror of the first guard, and a survivor of the first mutation round: every Azure case
    above hands the adapter an Azure URL, so removing its host check changed nothing. The leak has
    two ends, and this is the one where the second vendor is the one holding the secret."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat_from_the_azure_axis")

    # A TRUTHY TOKEN OR THE ADAPTER IS NEVER REACHED — `_authenticated` returns early without one,
    # so the first version of this guard passed while measuring nothing. Which token does not
    # matter: the Azure row ignores the caller's and uses the PAT above.
    got = _authenticated(_azure(repo_path=GH_URL), GH_URL, "ghs_ignored")

    assert got == GH_URL, f"an Azure PAT was sent to github.com: {got}"
    assert "pat_from_the_azure_axis" not in got


@pytest.mark.parametrize("url,host", [
    ("https://github.com/o/r.git", "github.com"),
    ("https://GitHub.COM/o/r.git", "github.com"),
    ("https://github.acme.com:8443/o/r.git", "github.acme.com"),
    ("git@github.com:o/r.git", ""),
    ("ssh://github.com/o/r.git", ""),
    ("http://github.com/o/r.git", ""),
])
def test_what_counts_as_a_host_has_one_home(url, host):
    """Asserted directly, because at the two adapters this check cannot change an answer — a
    non-https URL survives `url.replace("https://", …)` untouched anyway. It is a shared helper
    with two callers today and it is the thing a third would get wrong: the hand-written version
    it replaced split on `/` and forgot that a URL may carry a port."""
    from openfactory.adapters.forge.base import host_of

    assert host_of(url) == host


def test_a_forge_nobody_implements_leaves_the_url_ALONE(caplog):
    """`build_forge` raises on an unknown kind on purpose. The fallback must not be the old
    injection — a registry row nobody implements would then be the one case that still forwards a
    credential to an arbitrary host."""
    naked = Project(name="p", repo_path="https://gitlab.com/o/r.git",
                    tracker=ProviderRef(kind="github", repo="o/r"),
                    forge=ProviderRef(kind="gitlab", repo="o/r"))

    with caplog.at_level("WARNING"):
        got = _authenticated(naked, "https://gitlab.com/o/r.git", "ghs_tok")

    assert got == "https://gitlab.com/o/r.git"
    assert "without a credential" in caplog.text, (
        "the clone will fail for a reason nothing in the log explains")


# ── 2. the port refuses to be handed the wrong axis's secret ────────────────────────────────────

def test_the_contract_takes_NO_token():
    """Structural, and the reason the leak above is impossible rather than merely discouraged: a
    method that authenticated with whatever it was passed would wrap a `ghs_…` secret in Azure's
    spelling the first time a caller got the axis wrong."""
    from openfactory.adapters.forge.base import ForgeAdapter

    assert "token" not in inspect.signature(ForgeAdapter.authenticated_url).parameters


def test_every_registered_forge_implements_it():
    """Walked from the registry, so a fifth forge added without it fails the suite rather than
    degrading on somebody's deployment."""
    from openfactory.adapters.forge.registry import FORGES

    missing = []
    for kind, builder in FORGES.items():
        found = re.search(r"from (openfactory\.adapters\.forge\.\w+) import (\w+)",
                          inspect.getsource(builder))
        assert found, f"cannot tell which adapter the {kind!r} row builds"
        cls = getattr(importlib.import_module(found.group(1)), found.group(2))
        if not callable(getattr(cls, "authenticated_url", None)):
            missing.append(kind)

    assert not missing, f"these forges cannot say whether a URL is theirs: {missing}"


def test_the_neutral_path_no_longer_SPELLS_a_credential():
    """The weld itself. `x-access-token` is GitHub's word for a password field and it has no
    business in a module that composes runners for every vendor."""
    import openfactory.factory as mod

    src = code_only(inspect.getsource(mod))

    assert "x-access-token" not in src, (
        "one vendor's credential spelling is back on the neutral path")


def test_and_the_stripper_can_SEE_that_spelling():
    """Verify the verifier. The guard above passes trivially if `code_only` eats the code as well
    as the prose — which is exactly what a docstring-stripper gets wrong."""
    assert "x-access-token" in code_only(
        'def f():\n    """A docstring naming x-access-token."""\n    return "x-access-token"\n'
    ).replace('"""A docstring naming x-access-token."""', "")


# ── 3. the deployment's own mint is asked by AXIS ───────────────────────────────────────────────

def test_the_repo_fetch_falls_back_to_what_the_DEPLOYMENT_can_mint(monkeypatch, tmp_path):
    """`resolve_repo_path` resolved its fallback as `… or github_app_token_from_env()`, which is
    one vendor's name in a neutral function. `deployment_forge_token` answers by axis: the App
    mint for a GitHub forge, and nothing for any other — a token from the wrong system being worse
    than none."""
    import openfactory.credentials as creds
    from openfactory.runtime import repo_cache

    seen: list = []
    monkeypatch.setattr(creds, "forge_token_for", lambda p: None)
    monkeypatch.setattr(creds, "deployment_forge_token",
                        lambda p: seen.append(getattr(p, "name", "?")) or "minted")
    monkeypatch.setattr(repo_cache.RepoCache, "sync", lambda self, key, url, branch: tmp_path)

    from openfactory.factory import resolve_repo_path

    resolve_repo_path(_azure())

    assert seen == ["p"], "the fallback did not ask what this deployment can mint for THIS forge"


def test_the_promotion_runner_asks_the_same_question():
    """It minted a GitHub App token unconditionally — for any vendor — and handed it to the repo
    fetch and to the observer. It also spent an HTTPS round trip minting a token a non-GitHub
    forge could never use."""
    import ast

    from openfactory.factory import build_promotion_runner

    src = inspect.cleandoc("\n" + inspect.getsource(build_promotion_runner))
    called = {getattr(n.func, "id", "") for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call)}

    assert "deployment_forge_token" in called
    assert "github_app_token_from_env" not in called, (
        "the promotion runner still mints a GitHub credential whatever the project's forge")

"""`product declare` + the context credential borrow (pilot, 2026-08-13).

An enterprise client arrives with BOTH shapes — some projects keep a documentation repository
and some do not — and the have-one shape had no command: the docs said "name it in the registry" and the only mechanism
was hand-editing YAML inside the worker container. What holds now:

  1. `openfactory product declare <name> <owner/repo>` records it, and later reads see it;
  2. an unregistered project refuses by name (no registry write to a ghost);
  3. the context credential borrows the tracker's classic PAT ONLY when both axes are the same
     GitHub — a personal-account deployment holds one for the board, and it is the only
     credential that can create/reach a user-owned repository; a mixed deployment never
     borrows (a Jira token on a GitHub call is the 401-that-looks-like-revocation).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory.cli import app
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product.onboard import _context_token


def test_declare_records_and_later_reads_see_it(tmp_path, monkeypatch):
    _declarable(tmp_path, monkeypatch, reachable_by={"pat", "app"})

    result = CliRunner().invoke(app, ["product", "declare", "demo", "acme/demo-docs"])

    assert result.exit_code == 0, result.output
    assert "acme/demo-docs" in result.output
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("demo").product.docs_repo == "acme/demo-docs"


def test_declare_refuses_an_unregistered_project_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))

    result = CliRunner().invoke(app, ["product", "declare", "ghost", "acme/docs"])

    assert result.exit_code != 0
    assert "ghost" in result.output


def _project(tracker_kind: str) -> Project:
    return Project(name="dsk", repo_path="https://github.com/acme/api.git",
                   tracker=ProviderRef(kind=tracker_kind, repo="acme/api"),
                   forge=ProviderRef(kind="github", repo="acme/api"))


def test_the_context_token_borrows_the_boards_pat_on_an_all_github_deployment(monkeypatch):
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "ghp_board_pat")
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert _context_token(_project("github")) == "ghp_board_pat"


def test_a_mixed_deployment_never_borrows_the_tracker_credential(monkeypatch):
    """The Jira token is a Jira credential; on a GitHub call it is a 401 in disguise."""
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "jira_token")
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert _context_token(_project("jira")) == "ghs_minted"


def test_an_explicit_forge_credential_still_wins(monkeypatch):
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "ghp_forge")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for",
                        lambda p: (_ for _ in ()).throw(AssertionError("asked when not needed")))
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert _context_token(_project("github")) == "ghp_forge"


# ── declared is not reached (the enterprise case: "I will have to create it by hand") ──────────

def _declarable(tmp_path, monkeypatch, *, reachable_by: set[str]):
    """A registered project whose context repo is a REAL local bare repo — reachable only by
    the credentials named in `reachable_by`."""
    import subprocess

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0
    origin = tmp_path / "docs.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "README.md").write_text("docs\n")
    for args in (["init", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "s"],
                 ["remote", "add", "origin", str(origin)], ["push", "-u", "origin", "main"]):
        subprocess.run(["git", *args], cwd=seed, check=True, capture_output=True)

    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "pat")
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "app")
    monkeypatch.setattr(
        "openfactory.adapters.forge.registry.clone_url_for",
        lambda project, repo, token=None: str(origin) if token in reachable_by
        else str(tmp_path / "nowhere.git"))
    return origin


def test_declare_confirms_the_repository_can_actually_be_READ(tmp_path, monkeypatch):
    _declarable(tmp_path, monkeypatch, reachable_by={"pat", "app"})

    result = CliRunner().invoke(app, ["product", "declare", "demo", "acme/demo-docs"])

    assert result.exit_code == 0, result.output
    assert "reachable" in result.output


def test_a_repo_the_RUNTIME_credential_cannot_read_is_caught_at_declare_time(tmp_path,
                                                                            monkeypatch):
    """THE SILENT GAP, measured 2026-08-13: onboarding writes with one credential and the
    product role reads with another. A repo the PAT reaches and the App does not records
    perfectly and goes mute hours later — it must fail HERE, while somebody is watching."""
    _declarable(tmp_path, monkeypatch, reachable_by={"pat"})

    result = CliRunner().invoke(app, ["product", "declare", "demo", "acme/demo-docs"])

    assert result.exit_code != 0
    assert "RECORDED, BUT NOT READABLE" in result.output
    assert "runtime credential" in result.output, "which credential failed is not named"
    assert "Only select repositories" in result.output, "the likeliest cause is not offered"
    from openfactory.registry import ProjectRegistry

    assert ProjectRegistry().get("demo").product.docs_repo == "acme/demo-docs", (
        "the declaration was rolled back — the operator would have to re-declare after "
        "fixing access, which the message says they need not")


def test_a_creation_a_credential_may_not_do_is_told_how_to_proceed(monkeypatch):
    """The enterprise case, 2026-08-14: creation cannot be done through the vendor CLI at all
    with the credential the client can issue. A provider's 403
    is the diagnosis, not the answer — the way forward is created-by-hand + declare."""
    from openfactory.adapters.azure_devops import AzureDevOpsError
    from openfactory.product import onboard as po

    class _Forge:
        def create_repository(self, *, name, private=True, description=""):
            raise AzureDevOpsError("POST git/repositories failed: HTTP 403 Forbidden")

        def push_remote(self):
            return None

    monkeypatch.setattr(po, "context_forge", lambda project: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.base.RepositoryCreatingForge",
                        type("_Any", (), {"__instancecheck__": lambda self, x: True})())

    with pytest.raises(AzureDevOpsError) as err:
        po.create_context_repository(_project("github"), "dsk")

    text = str(err.value)
    assert "HTTP 403" in text, "the vendor's own words are the diagnosis and must survive"
    assert "product declare dsk" in text, "no way forward was named"


def test_an_adapter_that_already_guides_is_not_doubled(monkeypatch):
    from openfactory.product import onboard as po

    class _Forge:
        def create_repository(self, *, name, private=True, description=""):
            raise RuntimeError("a personal account cannot — use `openfactory product declare`")

        def push_remote(self):
            return None

    monkeypatch.setattr(po, "context_forge", lambda project: _Forge())
    monkeypatch.setattr("openfactory.adapters.forge.base.RepositoryCreatingForge",
                        type("_Any", (), {"__instancecheck__": lambda self, x: True})())

    with pytest.raises(RuntimeError) as err:
        po.create_context_repository(_project("github"), "dsk")

    assert str(err.value).count("product declare") == 1, "the remedy was stated twice"


# ── the borrow is a PRODUCT rule, not a GitHub one (operator, 2026-08-14) ───────────────────────

def _ado_project() -> Project:
    return Project(name="dsk", repo_path="https://dev.azure.com/org/Deskline/_git/api",
                   tracker=ProviderRef(kind="azure_devops", repo="Deskline"),
                   forge=ProviderRef(kind="azure_devops", repo="api",
                                     options={"organization": "org", "project": "Deskline"}))


def test_a_same_vendor_deployment_borrows_whatever_that_vendor_is(monkeypatch):
    """The condition is SAME VENDOR, not "is GitHub": a credential is scoped to a vendor, so an
    all-Azure deployment that filled only the tracker's PAT must borrow it exactly as an
    all-GitHub one does. Naming one vendor here would be this pilot's account leaking into the
    product."""
    monkeypatch.setattr("openfactory.credentials.forge_token_for", lambda p: "")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: "ado_pat")

    assert _context_token(_ado_project()) == "ado_pat"


def test_the_deployments_own_credential_is_offered_only_to_the_vendor_it_belongs_to(monkeypatch):
    """`deployment_forge_token` is the vendor-aware replacement for `… or
    github_app_token_from_env()` in neutral code: a GitHub axis gets the App mint, anything else
    gets nothing, because a token from the wrong system is worse than none."""
    from openfactory.credentials import deployment_forge_token

    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert deployment_forge_token(_project("github")) == "ghs_minted"
    assert deployment_forge_token(_ado_project()) is None, (
        "a GitHub App token was offered to an Azure DevOps forge")

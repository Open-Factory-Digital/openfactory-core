"""One deployment, two forges, two credentials — the fx-jira defect on the other axis.

`tracker_token_for` exists because a worker serving a GitHub project and a Jira project
authenticated both with whichever process-wide token the environment carried, and the Jira board
came back with an empty queue. The forge axis had the identical hole; nothing had stepped in it
only because `FORGES` had one row. The Azure Repos row ends that, so the guard lands with it.

The reachability guard is the point. `forge_token_for` existing and being correct is worth nothing
if the composition root still calls `forge_token()` — this codebase's signature defect, ~19 times
over. It is written against the AST rather than the source text because a prose comment explaining
the rule contains the rule, and that trap has already cost this repository three green-but-blind
guards in a single day.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory.contracts.project import Project, ProviderRef

FACTORY = pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "factory.py"


def _project(**forge_options):
    return Project(
        name="fx-ado",
        repo_path="/tmp/fx-ado",
        tracker=ProviderRef(kind="azure_devops", repo="factory"),
        forge=ProviderRef(kind="azure_devops", repo="fx-ado", options=forge_options),
    )


def test_a_project_that_names_its_own_forge_credential_gets_THAT_one(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-github-token")
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-azure-token")
    from openfactory.credentials import forge_token_for

    assert forge_token_for(_project(token_env="AZURE_DEVOPS_PAT")) == "the-azure-token", (
        "an Azure Repos project handed the deployment's GitHub token presents it as HTTP Basic "
        "and reads back a 401 — a credential that LOOKS configured failing as if it were revoked"
    )


def test_a_project_that_names_nothing_still_gets_the_deployments_own(monkeypatch):
    """The whole migration cost: projects that exist today must not move a byte."""
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-github-token")
    from openfactory.credentials import forge_token_for

    assert forge_token_for(_project()) == "the-github-token"
    assert forge_token_for(Project(name="no-forge-axis-at-all", repo_path="/tmp/x")) == "the-github-token"


def test_a_named_variable_that_is_EMPTY_is_said_out_loud(monkeypatch, caplog):
    """Silence here is the expensive case: the fallback is the WRONG SYSTEM, not a smaller scope."""
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "the-github-token")
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    from openfactory.credentials import forge_token_for

    with caplog.at_level("WARNING"):
        assert forge_token_for(_project(token_env="AZURE_DEVOPS_PAT")) == "the-github-token"

    assert "AZURE_DEVOPS_PAT" in caplog.text and "wrong system" in caplog.text


# ---------------------------------------------------------------------------------------------
# reachability: the composition root must actually ASK the per-project question


ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every function that resolves a forge credential WITH A PROJECT IN HAND. One entry per site
#: because the guard has to name what it covers — a sweep over the whole package would be quietly
#: satisfied by a site being deleted, and the point is that these specific paths keep asking.
PER_PROJECT_SITES = [
    ("openfactory/factory.py", "build_runner"),
    ("openfactory/factory.py", "build_promotion_runner"),
    ("openfactory/factory.py", "resolve_repo_path"),
    ("openfactory/runtime/temporal/activities.py", "_forge_for"),
    ("openfactory/runtime/temporal/view.py", "_pr_checks"),
]

#: Sites that legitimately still read the process-wide value, each with the reason IN THE CODE.
#: They are not oversights and they are not exceptions to the rule — five are GitHub-specific BY
#: CONSTRUCTION (they shell out to `gh`, or build an `https://…@github.com/…` clone URL), so a
#: per-project credential there would be a fix that only looks like one. Un-hardcoding the vendor
#: is the real work and a different, larger change:
#:   openfactory/techlead/conversation.py  _forge_env    — GH_TOKEN for `gh` shell-outs
#:   openfactory/techlead/conversation.py  clone_repo    — https://…@github.com/<repo>.git
#:   openfactory/techlead/diagnosis.py     _token        — GH_TOKEN for `gh` reads
#:   openfactory/doctor.py                 _forge_credential — the product docs repo, github.com
#:   openfactory/cli.py                    product_init  — clones the docs repo from github.com
#: and the sixth is a genuine ordering constraint, argued at the call site:
#:   openfactory/runtime/boxed_job.py        main     — needs the token BEFORE the project exists
#:
#: THIS NUMBER WAS WRITTEN AS 4 FROM MEMORY AND THE TEST SAID 6. Which is the whole reason a
#: ratchet is a test and not a comment.
_KNOWN_VENDOR_BOUND = 6


def _calls_named(tree: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize(("path", "func_name"), PER_PROJECT_SITES)
def test_a_forge_credential_is_resolved_PER_PROJECT(path, func_name):
    """Where a forge credential is resolved for a known project, the project must be in the ask.

    AST, not substring: the docstring one function up explains this exact rule and therefore
    contains the very name a text search would match. Three guards in this repository went green
    while the thing they guarded was broken for precisely that reason.
    """
    source = (ROOT / path).read_text()
    func = next(
        (n for n in ast.walk(ast.parse(source))
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name),
        None,
    )
    assert func is not None, f"{func_name} vanished from {path} — this guard now guards nothing"

    called = _calls_named(func)
    assert "forge_token_for" in called, (
        f"{path}::{func_name} does not ask which project's forge it is resolving for"
    )
    assert "forge_token" not in called, (
        f"{path}::{func_name} still calls the process-wide forge_token(); a deployment hosting an "
        f"Azure Repos project beside a GitHub one hands one of them the other's credential"
    )


def test_the_remaining_process_wide_readers_do_not_grow():
    """A ratchet, not a ban. The four sites left are GitHub-bound by construction and say so.

    Without this the class comes back one call site at a time, which is exactly how it got to
    twenty in the first place. If this number goes UP, the new site either takes a project or
    earns its line in `_KNOWN_VENDOR_BOUND` above with the reason written where it is read.
    """
    hits = [
        f"{path.relative_to(ROOT)}::{node.name}"
        for path in sorted((ROOT / "openfactory").rglob("*.py"))
        if path.name != "credentials.py"
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "forge_token" in _calls_named(node)
    ]
    assert len(hits) <= _KNOWN_VENDOR_BOUND, (
        f"the process-wide forge credential is being read in {len(hits)} places, up from "
        f"{_KNOWN_VENDOR_BOUND}: {hits}"
    )


# ── the clone URL is the same question, and it leaked where the guard was not looking ──────────

def test_a_missing_ADO_credential_yields_a_TOKENLESS_url_not_someone_elses_secret(monkeypatch):
    """The case the first guard never ran: the Azure variable UNSET.

    `clone_url_for` resolved the token as `adapter.token or caller_token`. The adapter's own token
    is None whenever its credential is unset — an Azure project on a deployment that has not
    provisioned `AZURE_DEVOPS_PAT` yet, which is exactly the state during onboarding. The fallback
    then handed the caller's GitHub secret to dev.azure.com:

        https://openfactory:ghp_…@dev.azure.com/acme-ai/factory/_git/fx-ado

    Found by a reviewer working on a different card, because the guard I wrote for this only ever
    ran with the variable SET — it asserted the happy path and called it proof. A guard that cannot
    reach the failing configuration is not guarding the failure.
    """
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_a_github_secret")
    from openfactory.adapters.forge.registry import clone_url_for

    url = clone_url_for(_project(organization="acme-ai"), token="ghp_a_github_secret")

    assert "ghp_" not in url, f"a github.com secret reached a dev.azure.com URL: {url}"
    assert url == "https://dev.azure.com/acme-ai/factory/_git/fx-ado", (
        "a missing credential must yield a tokenless URL — the clone then fails saying so, which "
        "is honest, rather than failing with somebody else's secret in the request"
    )


def test_the_github_path_still_carries_its_own_credential(monkeypatch):
    """The positive twin: removing the fallback must not disarm the provider it was right for."""
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_a_github_secret")
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.contracts.project import Project, ProviderRef

    github = Project(name="g", repo_path="/tmp/g",
                     tracker=ProviderRef(kind="github", repo="AcmeCorp/app"),
                     forge=ProviderRef(kind="github", repo="AcmeCorp/app"))

    assert clone_url_for(github, token="ghp_a_github_secret") == (
        "https://x-access-token:ghp_a_github_secret@github.com/AcmeCorp/app.git")

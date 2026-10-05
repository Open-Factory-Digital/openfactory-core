"""`openfactory certify` reads the forge: what protects the branch, what the credential is granted,
and which releases are published — and a read nobody could make is `unknown`, never `pass` (#356).

THE ACCEPTANCE, from the issue: a forge read returns `None` when the credential lacks the scope,
and the control then reads `unknown`, never `pass`. Three optional capabilities on the forge port
(`adapters/forge/base.py`), each asked through one module function, each with the third answer
every read on this port has:

    branch_protection(repo, branch)   GitHub: the rulesets, the branch, classic protection when the
                                      branch says it has some, the repository's auto-merge switch.
                                      Azure Repos: the blocking branch policies that apply.
    credential_permissions()          GitHub: an App installation's permissions (signed with the
                                      App's own JWT, nothing minted), a classic token's or a login's
                                      `X-OAuth-Scopes`. Azure DevOps: never readable — None.
    published_releases(url)           GitHub, for a repository on its own host.

EVERY READ GOES THROUGH THE REAL ROW with its transport answered per route — `gh`'s `_gh_read` on
GitHub, the client on Azure DevOps (`test_the_ado_forge.FakeADO`), `httpx.get` for the App — and
nothing here reaches a network: a route nobody recorded fails the test.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge import base
from openfactory.adapters.forge.base import BranchProtection
from openfactory.adapters.forge.github import GitHubForge
from openfactory.adapters.forge.local import LocalForge
from openfactory.certify import controls as c
from openfactory.certify import pack
from tests import certify_bed as bed
from tests.test_certify_controls_answer_from_what_was_read import (
    PROTECTED,
    Names,
    _answer,
    _project,
    _reading,
    _repo,
)
from tests.test_the_ado_forge import FX_ADO_REPO, REPO_ID
from tests.test_the_ado_forge import forge as ado_forge
from tests.test_the_doctor_names_the_gates_only_a_person_settles import BRANCH, RULES
from tests.test_the_doctor_never_says_no_gate_about_a_branch_it_could_not_read import (
    BRANCH_UNDER_CLASSIC_PROTECTION,
    BRANCH_UNPROTECTED,
    FINE_GRAINED,
    NOT_FOUND,
    NOT_PROTECTED,
    PROTECTION,
)

HOME = "https://github.com/Open-Factory-Digital/openfactory-core"

# ═══ GitHub: the branch's protection ════════════════════════════════════════════════════════════


def _github(monkeypatch, routes: dict, *, repo="acme/x", **kw):
    """The real row, `_gh_read` answered PER ROUTE (the whole argument list, joined). A route this
    case did not record fails it: a read nobody expected is a finding, not a default."""
    f = GitHubForge(repo, **kw)
    asked: list[str] = []

    def gh_read(args, what):
        route = " ".join(args)
        asked.append(route)
        if route not in routes:
            pytest.fail(f"the row read {route}, which this case did not record")
        got = routes[route]
        return got if isinstance(got, SimpleNamespace) else bed.answered(got)

    monkeypatch.setattr(f, "_gh_read", gh_read)
    f.asked = asked
    return f


def _protection_routes(*, rules=RULES, branch=BRANCH, protection=None, settings=None,
                       repo="acme/x", name="main"):
    return {f"api repos/{repo}/rules/branches/{name}": rules,
            f"api repos/{repo}/branches/{name}": branch,
            f"api repos/{repo}/branches/{name}/protection": protection,
            f"api repos/{repo}": {"allow_auto_merge": True} if settings is None else settings}


def test_github_reads_a_branch_its_rulesets_protect(monkeypatch):
    """The live recording of a `main` gated by a ruleset — `pull_request`, `non_fast_forward`,
    `required_linear_history` — with no classic protection beside it, and auto-merge on."""
    f = _github(monkeypatch, _protection_routes())

    assert base.branch_protection_of(f, "main") == PROTECTED
    assert "api repos/acme/x/branches/main/protection" not in f.asked, (
        "a branch that says it has no classic protection was sent to be refused")


def test_github_reads_an_unprotected_branch_as_off_not_as_unread(monkeypatch):
    f = _github(monkeypatch, _protection_routes(rules=[], branch=BRANCH_UNPROTECTED,
                                                settings={"allow_auto_merge": False}))

    assert base.branch_protection_of(f, "main") == BranchProtection(
        pr_required=False, linear_history=False, force_push_blocked=False,
        auto_merge_enabled=False)


def test_github_reads_classic_protection_when_the_branch_says_it_has_some(monkeypatch):
    """GitHub's documented readable protection: reviews required, linear history, and force
    pushes ALLOWED — so a branch classic protection guards can still fail C-BRANCH."""
    f = _github(monkeypatch, _protection_routes(rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                                                protection=PROTECTION))

    assert base.branch_protection_of(f, "main") == BranchProtection(
        pr_required=True, linear_history=True, force_push_blocked=False, auto_merge_enabled=True)


def test_an_admin_told_branch_not_protected_reads_classic_as_off(monkeypatch):
    f = _github(monkeypatch, _protection_routes(rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                                                protection=NOT_PROTECTED))

    assert base.branch_protection_of(f, "main").pr_required is False


@pytest.mark.parametrize("refusal", [NOT_FOUND, FINE_GRAINED], ids=["non-admin", "fine-grained"])
def test_classic_protection_this_credential_may_not_read_leaves_its_facts_unread(monkeypatch,
                                                                                refusal):
    """Classic protection is shown to an administrator only. What the rulesets did not settle is
    then NOT READ — `None` — and never `False`: nobody saw the setting."""
    f = _github(monkeypatch, _protection_routes(rules=[], branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                                                protection=refusal))

    got = base.branch_protection_of(f, "main")

    assert (got.pr_required, got.linear_history, got.force_push_blocked) == (None, None, None)


def test_a_ruleset_settles_what_unreadable_classic_protection_cannot(monkeypatch):
    f = _github(monkeypatch, _protection_routes(branch=BRANCH_UNDER_CLASSIC_PROTECTION,
                                                protection=NOT_FOUND))

    assert base.branch_protection_of(f, "main") == PROTECTED


def test_an_auto_merge_switch_github_did_not_show_is_unread_not_off(monkeypatch):
    f = _github(monkeypatch, _protection_routes(settings={"name": "x"}))

    assert base.branch_protection_of(f, "main").auto_merge_enabled is None


def test_rulesets_the_credential_may_not_read_are_no_answer(monkeypatch):
    """THE ACCEPTANCE: a credential without the scope to ask reads `None`, and the control built
    on it is `unknown`."""
    f = _github(monkeypatch, _protection_routes(rules=FINE_GRAINED))

    got = base.branch_protection_of(f, "main")

    assert got is None
    reading = _reading(projects=[_project(_repo(protection=got))])
    assert _answer("C-BRANCH", reading).result == "unknown"


def test_a_foreign_repository_is_read_where_it_lives(monkeypatch):
    f = _github(monkeypatch, _protection_routes(repo="acme/other"))

    assert base.branch_protection_of(f, "main", repo="acme/other") == PROTECTED
    assert all("acme/other" in route for route in f.asked)


# ═══ GitHub: what the credential is granted ═════════════════════════════════════════════════════

SCOPES = "api --include rate_limit"


@pytest.mark.parametrize("header,granted", [
    ("repo, read:org", {"repo", "read:org"}),
    ("repo, workflow", {"repo", "workflow"}),
])
def test_a_classic_token_s_scopes_are_read_off_the_response_header(monkeypatch, header, granted):
    f = _github(monkeypatch, {SCOPES: bed.scopes_answer(header)}, token="ghp_x")

    assert base.credential_permissions_of(f) == frozenset(granted)


@pytest.mark.parametrize("header", [None, ""], ids=["no-header", "empty-header"])
def test_a_token_whose_grants_github_does_not_list_is_no_answer(monkeypatch, header):
    """A fine-grained token or an installation token handed in as a value: GitHub sends no
    scopes, or an empty list — neither may read as "granted nothing", which would pass."""
    f = _github(monkeypatch, {SCOPES: bed.scopes_answer(header)}, token="github_pat_x")

    assert base.credential_permissions_of(f) is None
    reading = _reading(projects=[_project(permissions=None)])
    assert _answer("C-WORKFLOWS", reading).result == "unknown"


def test_a_refused_scope_read_is_no_answer(monkeypatch):
    f = _github(monkeypatch, {SCOPES: bed.refused("Bad credentials", 401)}, token="ghp_x")

    assert base.credential_permissions_of(f) is None


def _app(monkeypatch, *, status=200, body=None):
    """A real App provider with a real key, its installation answered by a faked `httpx.get` —
    and a mint that fails the test: the permissions are read WITHOUT one."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from openfactory.adapters import github_app as ga

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    asked: list[tuple[str, dict]] = []

    def get(url, *, headers, timeout):
        asked.append((url, headers))
        return SimpleNamespace(status_code=status, json=lambda: body)

    monkeypatch.setattr(ga.httpx, "get", get)
    monkeypatch.setattr(ga, "mint_installation_token",
                        lambda **_: pytest.fail("a token was minted to read the permissions"))
    provider = ga.GitHubAppTokenProvider(app_id="918273", private_key=pem,
                                         installation_id="55512345")
    return provider, key, asked


def test_an_app_s_permissions_are_read_from_its_installation_signed_with_its_own_key(monkeypatch):
    provider, key, asked = _app(monkeypatch, body={"id": 55512345, "permissions": {
        "contents": "write", "pull_requests": "write", "metadata": "read"}})
    f = _github(monkeypatch, {}, token_provider=provider.token)

    assert base.credential_permissions_of(f) == {"contents:write", "pull_requests:write",
                                                 "metadata:read"}
    url, headers = asked[0]
    assert url == "https://api.github.com/app/installations/55512345"
    signed = headers["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(signed, key.public_key(), algorithms=["RS256"])["iss"] == "918273"


def test_an_app_that_can_write_workflows_fails_c_workflows(monkeypatch):
    provider, _, _ = _app(monkeypatch, body={"permissions": {"contents": "write",
                                                             "workflows": "write"}})
    f = _github(monkeypatch, {}, token_provider=provider.token)

    reading = _reading(projects=[_project(permissions=base.credential_permissions_of(f),
                                          ci_permissions=base.ci_write_permissions_of(f))])

    answer = _answer("C-WORKFLOWS", reading)
    assert answer.result == "fail" and "workflows:write" in answer.detail


@pytest.mark.parametrize("status,body", [(404, {"message": "Not Found"}), (200, {"id": 1})])
def test_an_installation_that_could_not_be_read_is_no_answer(monkeypatch, status, body):
    provider, _, _ = _app(monkeypatch, status=status, body=body)
    f = _github(monkeypatch, {}, token_provider=provider.token)

    assert base.credential_permissions_of(f) is None


def test_the_job_s_credential_is_the_one_asked__an_app_deployment_reads_its_installation(
        monkeypatch):
    """`pack._forge_of` builds the row with the credential a JOB holds: on a deployment whose
    only credential is the App, that is the App's re-minting provider — never a stored token,
    never nothing."""
    from openfactory.adapters.github_app import GitHubAppTokenProvider
    from openfactory.contracts.project import Project, ProviderRef

    for name in ("OPENFACTORY_BOT_TOKEN", "OPENFACTORY_FORGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"OPENFACTORY_GH_APP_ID": "1", "OPENFACTORY_GH_APP_INSTALLATION_ID": "2",
                        "OPENFACTORY_GH_APP_KEY_CONTENT": "k"}.items():
        monkeypatch.setenv(name, value)
    row = Project(name="p", repo_path="/x", tracker=ProviderRef(kind="github", repo="o/r"))

    forge = pack._forge_of(row)

    assert isinstance(getattr(forge._token_provider, "__self__", None), GitHubAppTokenProvider)


# ═══ GitHub: the platform's releases ════════════════════════════════════════════════════════════

RELEASES = "api repos/Open-Factory-Digital/openfactory-core/releases?per_page=100"


def test_github_lists_the_published_releases_and_leaves_out_drafts_and_candidates(monkeypatch):
    f = _github(monkeypatch, {RELEASES: bed.RELEASES})

    assert base.published_releases_of(f, HOME) == ["v0.5.1", "v0.5.0", "v0.4.2"]


@pytest.mark.parametrize("url", ["https://gitlab.com/Open-Factory-Digital/openfactory-core",
                                 "http://github.com/Open-Factory-Digital/openfactory-core",
                                 "https://github.com/Open-Factory-Digital"])
def test_a_repository_on_another_host_is_not_read_with_this_credential(monkeypatch, url):
    f = _github(monkeypatch, {})

    assert base.published_releases_of(f, url) is None
    assert f.asked == []


def test_releases_that_could_not_be_listed_are_no_answer(monkeypatch):
    f = _github(monkeypatch, {RELEASES: bed.refused("API rate limit exceeded", 403)})

    assert base.published_releases_of(f, HOME) is None


def test_the_releases_home_is_the_package_s_own_repository_url():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml")
                              .read_text())
    assert pack.releases_home() == pyproject["project"]["urls"]["Repository"]


# ═══ Azure Repos: the branch policies ═══════════════════════════════════════════════════════════

REVIEWERS = ("fa4e907d-c16b-4a4c-9dfa-4906e5d171dd", "Minimum number of reviewers")
MERGE_STRATEGY = ("fa4e907d-c16b-4a4c-9dfa-4916e5d171ab", "Require a merge strategy")
FILE_SIZE = ("2e26e725-8201-4edd-8bf5-978563c34a80", "File size restriction")


def _policy(kind, *, blocking=True, ref="refs/heads/main", **settings):
    """One `policy/configurations` record, in the shape Azure DevOps documents."""
    type_id, shown = kind
    scope = {"repositoryId": REPO_ID}
    if ref:
        scope.update(refName=ref, matchKind="Exact")
    return {"isEnabled": True, "isDeleted": False, "isBlocking": blocking,
            "type": {"id": type_id, "displayName": shown},
            "settings": {"scope": [scope], **settings}}


def _ado(configs):
    return ado_forge({"GET policy/configurations": {"value": configs},
                      "GET git/repositories/fx-ado": FX_ADO_REPO})


def test_azure_reads_a_branch_its_policies_protect():
    """Two reviewers and squash only: a pull request is required — so no push, forced or not —
    and history is linear. Auto-complete is no setting, so it is not read."""
    f = _ado([_policy(REVIEWERS, minimumApproverCount=2),
              _policy(MERGE_STRATEGY, allowSquash=True, allowNoFastForward=False,
                      allowRebase=False, allowRebaseMerge=False)])

    assert base.branch_protection_of(f, "main") == BranchProtection(
        pr_required=True, linear_history=True, force_push_blocked=True, auto_merge_enabled=None)


def test_azure_reads_a_branch_with_no_policy_as_open():
    got = base.branch_protection_of(_ado([]), "main")

    assert (got.pr_required, got.linear_history) == (False, False)
    assert got.force_push_blocked is None, "the Force push PERMISSION is not read"


def test_azure_counts_only_what_blocks_a_pull_request():
    """An optional policy is shown and ignored, and a repository setting that is also a policy
    configuration — a file size limit, unscoped by branch — is checked on every push and asks
    for no pull request."""
    f = _ado([_policy(REVIEWERS, blocking=False), _policy(FILE_SIZE, ref=None)])

    assert base.branch_protection_of(f, "main").pr_required is False


@pytest.mark.parametrize("settings,linear", [
    ({"allowSquash": True, "allowNoFastForward": True}, False),
    ({"allowRebase": True, "allowRebaseMerge": True}, False),
    ({"allowRebase": True}, True),
    ({"useSquashMerge": True}, True),
    ({}, False),
], ids=["merge-commits", "semi-linear", "rebase", "legacy-squash", "nothing-allowed"])
def test_azure_history_is_linear_only_without_merge_commits(settings, linear):
    f = _ado([_policy(MERGE_STRATEGY, **settings)])

    assert base.branch_protection_of(f, "main").linear_history is linear


def test_azure_policies_that_could_not_be_read_are_no_answer():
    f = ado_forge({}, raises={"GET policy/configurations": AzureDevOpsError("GET … → 403")})

    assert base.branch_protection_of(f, "main") is None


def test_azure_never_reads_a_credential_s_scopes_and_says_so_without_asking():
    f = _ado([])

    assert base.credential_permissions_of(f) is None
    assert f.fake.calls == [], "a read was made that cannot answer"


def test_a_fully_protected_azure_branch_is_unknown_for_c_branch_never_pass():
    """THE PRICE OF NOT INFERRING: Azure Repos has no auto-merge switch to read, so a branch whose
    policies say everything else still reads `unknown` — until somebody decides that a vendor
    fact counts as a read."""
    f = _ado([_policy(REVIEWERS), _policy(MERGE_STRATEGY, allowSquash=True)])
    reading = _reading(projects=[_project(_repo(protection=base.branch_protection_of(f, "main")))])

    answer = _answer("C-BRANCH", reading)
    assert answer.result == "unknown" and "auto-merge" in answer.detail


# ═══ the port: only a real answer is believed ═══════════════════════════════════════════════════

class _Raises:
    def branch_protection(self, repo, branch):
        raise RuntimeError("boom")

    def credential_permissions(self):
        raise RuntimeError("boom")

    def published_releases(self, url):
        raise RuntimeError("boom")


@pytest.mark.parametrize("forge", [LocalForge("p", "/nowhere"), MagicMock(), _Raises(), None],
                         ids=["a-row-without-them", "a-double", "a-row-that-raises", "no-forge"])
def test_a_forge_that_cannot_answer_is_no_answer(forge):
    assert base.branch_protection_of(forge, "main") is None
    assert base.credential_permissions_of(forge) is None
    assert base.ci_write_permissions_of(forge) == frozenset()
    assert base.published_releases_of(forge, HOME) is None


def test_the_rows_that_answer_declare_which_grants_reach_the_ci_definitions():
    assert base.ci_write_permissions_of(GitHubForge("acme/x")) == {"workflow", "workflows:write"}


# ═══ the controls: pass and fail from the data, unknown from None ═══════════════════════════════

@pytest.mark.parametrize("permissions,ci,result", [
    (frozenset({"contents:write"}), frozenset({"workflows:write"}), "pass"),
    (frozenset(), frozenset({"workflows:write"}), "pass"),
    (frozenset({"repo", "workflow"}), frozenset({"workflow", "workflows:write"}), "fail"),
    (None, frozenset({"workflows:write"}), "unknown"),
    (frozenset({"repo"}), frozenset(), "unknown"),
], ids=["no-workflows", "granted-nothing", "workflow-scope", "unread", "row-cannot-say"])
def test_c_workflows(permissions, ci, result):
    reading = _reading(projects=[_project(permissions=permissions, ci_permissions=ci)])

    assert _answer("C-WORKFLOWS", reading).result == result


def _protected(**over) -> BranchProtection:
    return PROTECTED.model_copy(update=over)


@pytest.mark.parametrize("protection,result", [
    (PROTECTED, "pass"),
    (_protected(pr_required=False), "fail"),
    (_protected(force_push_blocked=False, auto_merge_enabled=None), "fail"),
    (_protected(linear_history=None), "unknown"),
    (None, "unknown"),
], ids=["protected", "no-pr", "off-beats-unread", "a-fact-unread", "unread"])
def test_c_branch(protection, result):
    reading = _reading(projects=[_project(_repo(protection=protection))])

    assert _answer("C-BRANCH", reading).result == result


def test_c_branch_never_names_the_branch():
    reading = _reading(projects=[_project(_repo(protection=_protected(pr_required=False)))])

    assert "main" not in _answer("C-BRANCH", reading).detail


def test_c_branch_reads_every_repository():
    reading = _reading(projects=[_project(_repo(), _repo(identity="o/s", default=False,
                                                         protection=None))])

    assert _answer("C-BRANCH", reading).result == "unknown"


@pytest.mark.parametrize("version,releases,result", [
    ("0.6.0", ["v0.6.0", "v0.5.1"], "pass"),
    ("0.5.1", ["v0.6.0", "v0.5.1", "v0.5.0"], "pass"),
    ("0.5.0", ["v0.6.0", "v0.5.1", "v0.5.0"], "fail"),
    ("0.5.1", ["v0.5.0", "v0.6.0", "v0.5.1", "v0.4.9"], "pass"),
    ("0.5.0", ["v0.5.0", "v0.6.0", "v0.5.1"], "fail"),
    ("0.6.0.dev0", ["v0.6.0", "v0.5.1"], "fail"),
    ("0.6.0rc1", ["v0.6.0-rc.1", "v0.5.1"], "fail"),
    ("0.7.0", ["v0.6.0", "v0.5.1"], "fail"),
    ("0.6.0", None, "unknown"),
    ("0.6.0", ["v0.6.0-rc.1"], "unknown"),
], ids=["latest", "one-before", "two-before", "listed-out-of-order", "out-of-order-two-before",
        "a-development-build", "a-candidate", "not-published", "unread", "no-release"])
def test_c_version(version, releases, result):
    assert _answer("C-VERSION", _reading(version=version, releases=releases)).result == result


# ═══ end to end: the deployment's forge, read by `gather` ═══════════════════════════════════════

def _results(tmp_path, monkeypatch, *, version: str = "", **answers) -> dict[str, c.Control]:
    bed.build(tmp_path, monkeypatch)
    if answers:
        bed.forge_answers(monkeypatch, **answers)
    if version:
        import openfactory

        monkeypatch.setattr(openfactory, "__version__", version)
    reading = pack.gather()
    return {x.id: x for x in c.evaluate(reading, "standard", Names())}


def test_a_deployment_whose_forge_answers_everything_is_certified_from_it(tmp_path, monkeypatch):
    results = _results(tmp_path, monkeypatch, version="0.5.1")

    assert {k: results[k].result for k in ("C-BRANCH", "C-WORKFLOWS", "C-VERSION")} == {
        "C-BRANCH": "pass", "C-WORKFLOWS": "pass", "C-VERSION": "pass"}


def test_every_repository_is_asked_where_it_lives(tmp_path, monkeypatch):
    """The bed's foreign repository (a proof recorded under its own key) is asked about its own
    branch, not the project's default repository's."""
    asked: list[str] = []
    bed.build(tmp_path, monkeypatch)
    real = GitHubForge._gh_read

    def recording(self, args, what):
        asked.append(" ".join(args))
        return real(self, args, what)

    monkeypatch.setattr(GitHubForge, "_gh_read", recording)
    pack.gather()

    assert f"api repos/{bed.WEB}/rules/branches/main" in asked


def test_a_credential_that_may_not_read_the_rules_reads_unknown_never_pass(tmp_path, monkeypatch):
    results = _results(tmp_path, monkeypatch, rules=FINE_GRAINED)

    assert results["C-BRANCH"].result == "unknown"


def test_a_token_whose_scopes_github_does_not_list_reads_unknown_never_pass(tmp_path,
                                                                          monkeypatch):
    results = _results(tmp_path, monkeypatch, scopes=bed.scopes_answer(None))

    assert results["C-WORKFLOWS"].result == "unknown"


def test_a_credential_that_holds_workflow_fails(tmp_path, monkeypatch):
    results = _results(tmp_path, monkeypatch, scopes=bed.scopes_answer("repo, workflow"))

    assert results["C-WORKFLOWS"].result == "fail"
    assert "`workflow`" in results["C-WORKFLOWS"].detail


def test_offline_every_forge_read_is_unknown(tmp_path, monkeypatch):
    """No network: `gh` produces no answer at all, and the three controls say `unknown`."""
    bed.build(tmp_path, monkeypatch)
    monkeypatch.setattr(GitHubForge, "_gh_read", lambda self, args, what: None)

    results = {x.id: x.result for x in c.evaluate(pack.gather(), "standard", Names())}

    assert {k: results[k] for k in ("C-BRANCH", "C-WORKFLOWS", "C-VERSION")} == {
        "C-BRANCH": "unknown", "C-WORKFLOWS": "unknown", "C-VERSION": "unknown"}


def test_a_forge_that_cannot_be_built_reads_unknown(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)
    monkeypatch.setattr(pack, "_forge_of", lambda project: None)

    results = {x.id: x.result for x in c.evaluate(pack.gather(), "standard", Names())}

    assert {k: results[k] for k in ("C-BRANCH", "C-WORKFLOWS", "C-VERSION")} == {
        "C-BRANCH": "unknown", "C-WORKFLOWS": "unknown", "C-VERSION": "unknown"}


def test_what_the_forge_said_reaches_the_pack_and_names_nobody(tmp_path, monkeypatch):
    bed.build(tmp_path, monkeypatch)

    built = pack.assemble(pack.gather(), profile="standard", partner="altiva",
                          practitioner=bed.PRACTITIONER)

    document = json.loads(built.files["pack.json"])
    detail = {x["id"]: x["evidence"]["detail"] for x in document["controls"]}
    assert "`read:org`" in detail["C-WORKFLOWS"] and "auto-merge" in detail["C-BRANCH"]
    leaks = [w for w in bed.FORBIDDEN for t in built.files.values() if w.lower() in t.lower()]
    assert leaks == []

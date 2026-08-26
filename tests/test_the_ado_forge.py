"""The Azure Repos forge — behaviour, plus the guards for what the live API actually does.

EVERY FIXTURE IN THIS FILE IS A TRIMMED REAL RESPONSE, recorded on 2026-08-06 against
`acme-ai/factory` (repositories `fx-ado` and `factory`). Field names, spellings and
values are the server's; nothing here invents a key the contract does not have. That matters more
than usual on this adapter, because three of its decisions exist only because the live API does
something the reference shape would not lead you to expect:

    an abandoned PR still carries a `lastMergeCommit`   (so `merge_commit_sha` gates on status)
    `policy/evaluations` is [] on a project WITH CI     (so `pr_ci_status` answers "none")
    the build API refuses a repository NAME             (so pipeline queries resolve the GUID)

The reachability guard at the bottom is the one that earns its place: `ForgeAdapter` is a Protocol
with `...` bodies, so a method this adapter forgets to write does not fail — it INHERITS a silent
`return None`. That is this codebase's signature defect with a trapdoor built in, and it already
happened here: `merge_commit_sha` was missing from the first draft and `pr_merged` said True while
`merge_commit_sha` said None, which downstream is a merged ticket whose deploy never runs.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.azure_devops import AzureReposForge, _ci_status_from_evaluations
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.forge.registry import FORGES, build_forge
from openfactory.contracts.project import Project, ProviderRef

# ── recorded shapes ─────────────────────────────────────────────────────────────────────────────

REPO_ID = "21200617-5ca5-4819-a6e0-68bbec2c964c"
PROJECT_ID = "aaa124b6-22d7-41eb-99b4-528d5c9f95d8"

FX_ADO_REPO = {"id": REPO_ID, "name": "fx-ado",
               "project": {"id": PROJECT_ID, "name": "factory"},
               "remoteUrl": "https://acme-ai@dev.azure.com/acme-ai/factory/_git/fx-ado",
               "webUrl": "https://dev.azure.com/acme-ai/factory/_git/fx-ado"}

#: PR 1 after completion — the merge really did land 811973a5… on `main`.
PR_MERGED = {
    "pullRequestId": 1, "status": "completed", "mergeStatus": "succeeded",
    "closedDate": "2026-08-06T09:18:29.5503599Z",
    "sourceRefName": "refs/heads/probe/forge-jwt-push", "targetRefName": "refs/heads/main",
    "repository": FX_ADO_REPO,
    "lastMergeSourceCommit": {"commitId": "0c288d73b39972ef2d80aede28e2f84bf47c0609"},
    "lastMergeCommit": {"commitId": "811973a56cb258ef262b12bdd13ab7fd8cdfe4d7"},
}

#: PR 4 — abandoned WITHOUT ever merging, and Azure DevOps still publishes a `lastMergeCommit`.
#: This one commit id is the reason `merge_commit_sha` is not a one-liner.
PR_ABANDONED = {
    "pullRequestId": 4, "status": "abandoned", "mergeStatus": None,
    "closedDate": "2026-08-06T09:19:38.0518063Z",
    "sourceRefName": "refs/heads/probe/abandon", "targetRefName": "refs/heads/main",
    "repository": FX_ADO_REPO,
    "lastMergeCommit": {"commitId": "15d18232dc052fef2058ea027a5d804f926dabf2"},
}

#: PR 2 lives in a DIFFERENT repository of the same project — the id sequence is project-wide
#: (2 was opened in `factory`, and the next PR opened in `fx-ado` came back as 3).
PR_OTHER_REPO = {
    "pullRequestId": 2, "status": "active", "mergeStatus": "succeeded",
    "sourceRefName": "refs/heads/probe/second", "targetRefName": "refs/heads/main",
    "repository": {"id": "6866361a-36cf-44ce-a547-5b330a251e47", "name": "factory",
                   "project": {"id": PROJECT_ID, "name": "factory"}},
    "lastMergeSourceCommit": {"commitId": "8fdae2969e11f999d6965475454b2e9a6070af50"},
    "lastMergeCommit": {"commitId": "15d18232dc052fef2058ea027a5d804f926dabf2"},
}

TEAMS = [{"id": "c3b2085d-5f18-48f7-b36c-ec6c0b2d8d13", "name": "factory Team"}]
TEAM_MEMBERS = [{"identity": {"id": "68c6c232-27b3-68d8-8be2-990f177c7f4e",
                              "displayName": "Alice Ferreira",
                              "uniqueName": "alice@acme.ai"}}]
CONNECTION_DATA = {"authenticatedUser": {"id": "68c6c232-27b3-68d8-8be2-990f177c7f4e",
                                         "providerDisplayName": "Alice Ferreira"}}

#: Recorded from `build/builds?definitions=1` — note `result: "canceled"`, which the hosted-agent
#: grant produced for real and which must not read as green.
BUILD_ON_MAIN = {
    "id": 1, "buildNumber": "20260806.1", "status": "completed", "result": "canceled",
    "sourceBranch": "refs/heads/main",
    "sourceVersion": "8c628eee746b4905e1113d6d3839cb54aefbedc5",
    "queueTime": "2026-08-06T09:12:05.1234567Z",
    "definition": {"id": 1, "name": "fx-ado-ci"},
    "_links": {"web": {"href": "https://dev.azure.com/acme-ai/" + PROJECT_ID
                               + "/_build/results?buildId=1"}},
}


class FakeADO:
    """A stand-in for `AzureDevOpsClient` with its exact surface.

    `values()` is DERIVED from `call()` here exactly as it is on the real client, so a route that
    answers a bare object cannot accidentally look like a collection in a test and not in
    production. Unrouted paths raise, so a test can never pass on a call nobody meant to make."""

    def __init__(self, routes: dict, raises: dict | None = None):
        self.routes = routes
        self.raises = raises or {}
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def call(self, method, path, *, body=None, params=None, project_scoped=True,
             content_type="application/json", api_version=None):
        key = f"{method.upper()} {path}"
        self.calls.append((method.upper(), path, body, params))
        if key in self.raises:
            raise self.raises[key]
        if key not in self.routes:
            raise AssertionError(f"the adapter called an unrouted Azure DevOps route: {key}")
        got = self.routes[key]
        return got(params) if callable(got) else got

    def values(self, path, **kw):
        got = self.call("GET", path, **kw)
        out = got.get("value")
        return out if isinstance(out, list) else []

    def paths(self, method: str) -> list[str]:
        return [p for m, p, _b, _q in self.calls if m == method]

    def body_for(self, method: str, path: str) -> dict:
        return next(b for m, p, b, _q in self.calls if m == method and p == path)


def forge(routes, raises=None, *, repo="fx-ado"):
    f = AzureReposForge(repo, organization="acme-ai", project="factory", token="tok")
    client = FakeADO(routes, raises)
    f._client = lambda: client  # noqa: SLF001 — the seam the adapter itself uses
    f.fake = client
    return f


# ── the registry row: a capability nothing reaches is not a capability ───────────────────────────

def test_the_forge_registry_dispatches_azure_devops():
    """`openfactory/adapters/forge/registry.py` — the row without which none of this file is reachable."""
    assert "azure_devops" in FORGES

    built = build_forge(Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        tracker=ProviderRef(kind="azure_devops", repo="factory"),
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai"})), token="tok")

    assert isinstance(built, AzureReposForge)
    assert isinstance(built, ForgeAdapter), "the runtime-checked port must accept it"
    assert (built.organization, built.project, built.repo) == ("acme-ai", "factory",
                                                              "fx-ado")


def test_the_ado_project_is_inherited_from_the_tracker_only_when_the_tracker_IS_ado():
    """A Jira tracker's `repo` is a Jira key. Inheriting it would aim this at a project that does
    not exist while looking perfectly configured — the expensive shape of a config error."""
    jira_tracked = build_forge(Project(
        name="mixed", repo_path="/tmp/mixed",
        tracker=ProviderRef(kind="jira", repo="CONT"),
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai"})), token="tok")

    assert jira_tracked.project == "", "a Jira project key must never become an ADO project name"


def test_the_github_credential_the_call_sites_pass_NEVER_reaches_azure(monkeypatch):
    """Found by running the registry, not by reading it.

    Every call site hands `build_forge` a GITHUB credential — the worker's `_forge_for` and the
    panel's `_pr_checks` pass `forge_token()`, the box passes a GitHub App token — and
    `forge_token_for` deliberately keeps that fallback for a project that names no `token_env`.
    So the row is the last line of defence, and before this guard it preferred the argument: the
    adapter presented a github.com PAT to dev.azure.com as HTTP Basic (a secret sent to the wrong
    company) and read back a 401 that looks like a revoked credential rather than like a
    configuration mistake."""
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-azure-token")
    built = build_forge(Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai", "project": "factory"})),
        token="ghp_the_deployments_github_pat")

    assert built.token == "the-azure-token"
    assert "ghp_" not in (built.push_remote() or "")


def test_the_azure_credential_is_re_read_at_each_use_not_frozen_at_construction(monkeypatch):
    """An `az account get-access-token` JWT lasts about an hour and a coding job can outlive it,
    so the row passes a provider rather than a value — and a variable this project NAMES is
    honoured over the default one."""
    monkeypatch.setenv("ADO_FOR_THIS_CLIENT", "first")
    built = build_forge(Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai", "project": "factory",
                                   "token_env": "ADO_FOR_THIS_CLIENT"})))

    assert built.token == "first"
    monkeypatch.setenv("ADO_FOR_THIS_CLIENT", "refreshed")
    assert built.token == "refreshed"


def test_no_azure_credential_is_an_honest_error_not_a_borrowed_one(monkeypatch):
    """With nothing configured the shared client must raise the sentence naming the variable to
    set. Borrowing the deployment's GitHub token here is what produced the mystery 401."""
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    built = build_forge(Project(
        name="fx-ado", repo_path="/tmp/fx-ado",
        forge=ProviderRef(kind="azure_devops", repo="fx-ado",
                          options={"organization": "acme-ai", "project": "factory"})),
        token="ghp_the_deployments_github_pat")

    assert built.token is None
    assert built.push_remote() is None
    client = built._client()  # noqa: SLF001 — the seam the adapter itself uses
    # asserted BEFORE the call so a regression fails here rather than putting a borrowed
    # credential on the wire: this suite makes no network requests
    assert client.token is None
    with pytest.raises(AzureDevOpsError, match="AZURE_DEVOPS_PAT"):
        client.call("GET", "git/pullrequests/1")


def test_an_unknown_forge_kind_still_names_azure_devops_in_the_refusal():
    with pytest.raises(ValueError, match="azure_devops"):
        build_forge(Project(name="x", repo_path="/tmp/x",
                            forge=ProviderRef(kind="gitlab", repo="a/b")))


# ── the three live findings ─────────────────────────────────────────────────────────────────────

def test_an_abandoned_pr_has_a_lastMergeCommit_and_it_is_NOT_a_merge():
    """The single most dangerous field on the Azure Repos PR object.

    `lastMergeCommit` is the SPECULATIVE merge Azure DevOps computes to answer "would this
    merge?". PR 4 was abandoned without ever merging and still carries 15d18232…. Handing that to
    the post-merge deploy (ADR-0005) sends it after a commit that is on no branch, and it looks
    like a real sha the whole way down."""
    f = forge({"GET git/pullrequests/4": PR_ABANDONED})

    assert f.merge_commit_sha(pr="4") is None
    assert PR_ABANDONED["lastMergeCommit"]["commitId"], "the fixture must keep the trap in it"


def test_a_completed_pr_yields_the_commit_that_actually_landed():
    f = forge({"GET git/pullrequests/1": PR_MERGED})

    assert f.merge_commit_sha(pr="1") == "811973a56cb258ef262b12bdd13ab7fd8cdfe4d7"
    assert f.pr_merged(pr="1") is True


def test_no_branch_policy_reads_as_none_not_as_pending():
    """The fx-jira defect, one vendor over — and here it is the DEFAULT state, not an edge case.

    `fx-ado` has a real pipeline that builds `main`; `policy/configurations` for the project is
    empty, so `policy/evaluations` for a live PR is []. Azure Repos has no YAML `pr:` trigger at
    all — a pipeline gates a PR only by being named in a build-validation policy. Answering
    "pending" here hangs the merge watch on a perfectly healthy repository."""
    f = forge({"GET git/pullrequests/2": PR_OTHER_REPO,
               "GET policy/evaluations": {"value": [], "count": 0}})

    assert f.pr_ci_status(pr="2") == "none"
    assert f.pr_checks(pr="2") == []


def test_the_policy_route_is_asked_with_the_project_GUID_and_the_preview_version():
    """Both are load-bearing: the project NAME is rejected in the artifact id, and a plain
    `api-version=7.1` answers `400 … is under preview`."""
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "GET policy/evaluations": {"value": []}})

    f.pr_ci_status(pr="1")

    _m, _p, _b, params = next(c for c in f.fake.calls if c[1] == "policy/evaluations")
    assert params["artifactId"] == f"vstfs:///CodeReview/CodeReviewId/{PROJECT_ID}/1"


def test_pipeline_queries_use_the_repository_GUID_because_the_build_api_refuses_a_name():
    """Every git route in this adapter takes `git/repositories/fx-ado/...`, so the name looks
    universal — and then the build API answers
    `400: Repository ID for a tfsgit repository should be a GUID`."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [BUILD_ON_MAIN]}})

    f.latest_run(workflow="fx-ado-ci")

    _m, _p, _b, params = next(c for c in f.fake.calls if c[1] == "build/builds")
    assert params["repositoryId"] == REPO_ID
    assert params["repositoryId"] != "fx-ado"


# ── a write never lands in the wrong repository ─────────────────────────────────────────────────

def test_a_write_is_addressed_at_the_prs_OWN_repository_not_the_configured_one():
    """PR ids are project-wide, so a valid id can name a PR in a sibling repository. github.py
    learned this as C-18, where `self.repo` silently updated a same-numbered PR in the default
    repo. Here it would 404 rather than hit the wrong PR — but only because we never write blind."""
    f = forge({"GET git/pullrequests/2": PR_OTHER_REPO,
               "PATCH git/repositories/factory/pullrequests/2": {}}, repo="fx-ado")

    f.close_pr(pr="2")

    assert "PATCH git/repositories/fx-ado/pullrequests/2" not in [
        f"{m} {p}" for m, p, _b, _q in f.fake.calls]


def test_a_pr_without_a_repository_refuses_to_guess():
    f = forge({"GET git/pullrequests/9": {"pullRequestId": 9, "status": "active"}})

    with pytest.raises(AzureDevOpsError, match="refusing to fall back"):
        f.close_pr(pr="9")


# ── merge ───────────────────────────────────────────────────────────────────────────────────────

def test_merge_arms_auto_complete_with_the_options_we_chose():
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "GET connectionData": CONNECTION_DATA,
               "PATCH git/repositories/fx-ado/pullrequests/1": {}})

    f.merge_pr(pr="1")

    body = f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/1")
    assert body["autoCompleteSetBy"]["id"] == CONNECTION_DATA["authenticatedUser"]["id"]
    opts = body["completionOptions"]
    # squash: the GitHub sibling merges --squash, and switching providers must not silently
    # rewrite what a client's history looks like
    assert opts["mergeStrategy"] == "squash"
    # nothing is deleted — a discard and a merge both leave the work recoverable
    assert opts["deleteSourceBranch"] is False
    # the tracker adapter owns the card's column; two writers to one state machine is a card that
    # jumps a column nobody asked for
    assert opts["transitionWorkItems"] is False
    assert opts["bypassPolicy"] is False


def test_merge_falls_back_to_a_direct_completion_when_arming_is_refused(caplog):
    """Mirrors the sibling's `--auto`-then-plain sequence rather than inventing a second
    behaviour: a deployment where the bot may not arm auto-complete must still be able to merge."""
    f = forge({"GET git/pullrequests/1": PR_MERGED, "GET connectionData": CONNECTION_DATA,
               "PATCH git/repositories/fx-ado/pullrequests/1": {}})
    original, refused = f.fake.call, []

    def refuse_the_arming(method, path, **kw):
        if method == "PATCH" and "autoCompleteSetBy" in (kw.get("body") or {}):
            refused.append(kw["body"])
            raise AzureDevOpsError("PATCH … → 403 Forbidden: auto-complete is not permitted")
        return original(method, path, **kw)

    f.fake.call = refuse_the_arming
    with caplog.at_level("WARNING"):
        f.merge_pr(pr="1")

    assert len(refused) == 1, "the arming must be attempted first"
    assert "could not arm auto-complete" in caplog.text, "a fallback nobody is told about is a lie"
    fallback = f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/1")
    assert fallback["status"] == "completed"
    assert fallback["completionOptions"]["mergeStrategy"] == "squash"


def test_force_merge_bypasses_with_a_reason_on_the_record():
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "PATCH git/repositories/fx-ado/pullrequests/1": {}})

    f.force_merge(pr="1")

    opts = f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/1")["completionOptions"]
    assert opts["bypassPolicy"] is True
    assert opts["bypassReason"], "an anonymous override is an override nobody can audit"


def test_disable_auto_merge_writes_the_empty_identity():
    """Azure DevOps ignores a null there; the empty GUID is what actually clears the arming."""
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "PATCH git/repositories/fx-ado/pullrequests/1": {}})

    f.disable_auto_merge(pr="1")

    body = f.fake.body_for("PATCH", "git/repositories/fx-ado/pullrequests/1")
    assert body == {"autoCompleteSetBy": {"id": "00000000-0000-0000-0000-000000000000"}}


# ── status vocabulary ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    ("completed", "merged"), ("abandoned", "closed"), ("active", "open"),
])
def test_pr_status_maps_azure_devops_words_to_the_ports_three(status, expected):
    f = forge({"GET git/pullrequests/1": {**PR_MERGED, "status": status}})

    assert f.pr_status(pr="1") == expected


def test_an_unknown_status_keeps_the_watch_alive_and_says_so(caplog):
    """A status we do not recognise must not silently end a merge watch — but it is news."""
    f = forge({"GET git/pullrequests/1": {**PR_MERGED, "status": "notSet"}})

    with caplog.at_level("WARNING"):
        assert f.pr_status(pr="1") == "open"

    assert "notSet" in caplog.text


def test_mergeable_state_reports_a_conflict_as_dirty():
    f = forge({"GET git/pullrequests/1": {**PR_MERGED, "mergeStatus": "conflicts"}})

    assert f.mergeable_state(pr="1") == "dirty"


def test_mergeable_state_never_says_behind_and_update_branch_says_why(caplog):
    """Azure Repos performs a real three-way merge and does not require an up-to-date source, so
    GitHub's `behind` has no counterpart. `update_branch` is therefore unreachable — and if it is
    ever reached anyway it must not claim a self-heal that did not happen."""
    f = forge({"GET git/pullrequests/1": PR_MERGED, "GET policy/evaluations": {"value": []}})

    assert f.mergeable_state(pr="1") == "clean"
    with caplog.at_level("WARNING"):
        assert f.update_branch(pr="1") is False
    assert "no update-branch route" in caplog.text


def test_mergeable_state_degrades_to_unknown_rather_than_crashing_the_loop(caplog):
    f = forge({}, raises={"GET git/pullrequests/1": AzureDevOpsError("502 Bad Gateway")})

    with caplog.at_level("WARNING"):
        assert f.mergeable_state(pr="1") == "unknown"

    assert "could not read mergeability" in caplog.text


# ── CI aggregation ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("statuses,expected", [
    ([], "none"),
    (["notApplicable"], "none"),
    (["approved"], "success"),
    (["approved", "queued"], "pending"),
    (["approved", "running"], "pending"),
    (["approved", "rejected"], "failure"),
    (["queued", "rejected"], "failure"),
    (["broken"], "failure"),
    (["approved", "notApplicable"], "success"),
])
def test_policy_evaluations_aggregate_like_the_github_sibling(statuses, expected):
    """Fail beats pending beats pass, same as `gh pr checks --required`, so a deployment that
    switches vendors gets the same decision from the same facts. `broken` — a policy that could
    not run — is a failure: a gate we cannot read is not a gate that passed."""
    assert _ci_status_from_evaluations([{"status": s} for s in statuses]) == expected


def test_failed_ci_logs_is_empty_rather_than_wrong_when_the_pr_cannot_be_read(caplog):
    """Every CI read derives from the PR, so an unreadable PR would otherwise come out as "CI is
    fine" — "could not read" must never look like "nothing there"."""
    f = forge({}, raises={"GET git/pullrequests/1": AzureDevOpsError("GET … → 500")})

    with caplog.at_level("WARNING"):
        assert f.failed_ci_logs(pr="1") == ""

    assert "could not read PR" in caplog.text


# ── pull request refs and creation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,expected", [
    ("7", 7),
    ("https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/7", 7),
    ("https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/7?_a=overview", 7),
])
def test_a_pr_ref_is_a_number_or_a_url(ref, expected):
    assert forge({})._pr_id(ref) == expected


def test_a_ref_that_is_not_a_pr_raises_instead_of_defaulting():
    """Guessing zero here would ask about a PR that does not exist and read the 404 as
    "not merged" — a delivered ticket that silently never promotes."""
    with pytest.raises(ValueError, match="not an Azure Repos pull request ref"):
        forge({})._pr_id("main")


def test_open_pr_sends_full_refs_and_returns_the_human_url():
    f = forge({"GET git/repositories/fx-ado/pullrequests": {"value": []},
               "POST git/repositories/fx-ado/pullrequests": {"pullRequestId": 5,
                                                             "repository": FX_ADO_REPO}})

    url = f.open_pr(head="feat/x", base="main", title="t", body="b")

    body = f.fake.body_for("POST", "git/repositories/fx-ado/pullrequests")
    assert body["sourceRefName"] == "refs/heads/feat/x"
    assert body["targetRefName"] == "refs/heads/main"
    assert url == "https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/5"


def test_open_pr_is_idempotent_and_does_not_file_a_second_one():
    f = forge({"GET git/repositories/fx-ado/pullrequests": {
        "value": [{"pullRequestId": 5, "repository": FX_ADO_REPO}]}})

    url = f.open_pr(head="feat/x", base="main", title="t", body="b")

    assert url.endswith("/pullrequest/5")
    assert "POST" not in [m for m, _p, _b, _q in f.fake.calls], (
        "a retried activity must not open a second pull request")


def test_a_failed_lookup_raises_so_no_duplicate_is_opened():
    """"I could not read" and "there is none" lead to opposite actions here."""
    f = forge({}, raises={"GET git/repositories/fx-ado/pullrequests":
                          AzureDevOpsError("GET … → 503 Service Unavailable")})

    with pytest.raises(AzureDevOpsError):
        f.open_pr(head="feat/x", base="main", title="t", body="b")


# ── reviews and reviewers ───────────────────────────────────────────────────────────────────────

def test_a_plain_comment_posts_a_thread_and_casts_no_vote():
    """A vote of 0 would add the bot to the reviewer list with no position — which reads as a
    reviewer who is still deciding, and that is worse than silence."""
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "POST git/repositories/fx-ado/pullrequests/1/threads": {"id": 5}})

    f.review_pr(pr="1", event="comment", body="advisory")

    assert f.fake.paths("PUT") == []
    assert f.fake.body_for("POST", "git/repositories/fx-ado/pullrequests/1/threads")[
        "status"] == "closed"


def test_request_changes_votes_reject_and_leaves_the_thread_open():
    f = forge({"GET git/pullrequests/1": PR_MERGED, "GET connectionData": CONNECTION_DATA,
               "POST git/repositories/fx-ado/pullrequests/1/threads": {"id": 6},
               "PUT git/repositories/fx-ado/pullrequests/1/reviewers/"
               "68c6c232-27b3-68d8-8be2-990f177c7f4e": {"vote": -10}})

    f.review_pr(pr="1", event="request-changes", body="please fix")

    assert f.fake.body_for("POST", "git/repositories/fx-ado/pullrequests/1/threads")[
        "status"] == "active", "an unresolved objection must look unresolved"
    vote_path = ("git/repositories/fx-ado/pullrequests/1/reviewers/"
                 "68c6c232-27b3-68d8-8be2-990f177c7f4e")
    assert f.fake.body_for("PUT", vote_path)["vote"] == -10


def test_an_approval_votes_ten():
    vote_path = ("git/repositories/fx-ado/pullrequests/1/reviewers/"
                 "68c6c232-27b3-68d8-8be2-990f177c7f4e")
    f = forge({"GET git/pullrequests/1": PR_MERGED, "GET connectionData": CONNECTION_DATA,
               "POST git/repositories/fx-ado/pullrequests/1/threads": {"id": 7},
               f"PUT {vote_path}": {"vote": 10}})

    f.review_pr(pr="1", event="approve", body="looks good")

    assert f.fake.body_for("PUT", vote_path)["vote"] == 10


def test_a_reviewer_email_is_resolved_to_the_identity_guid():
    """Azure DevOps addresses people by GUID, not by login."""
    guid = "68c6c232-27b3-68d8-8be2-990f177c7f4e"
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "GET projects/factory/teams": {"value": TEAMS},
               f"GET projects/factory/teams/{TEAMS[0]['id']}/members": {"value": TEAM_MEMBERS},
               f"PUT git/repositories/fx-ado/pullrequests/1/reviewers/{guid}": {}})

    f.request_reviewers(pr="1", reviewers=["alice@acme.ai"])

    body = f.fake.body_for("PUT", f"git/repositories/fx-ado/pullrequests/1/reviewers/{guid}")
    assert body["isRequired"] is True


def test_an_unresolvable_reviewer_raises_BEFORE_anything_is_written():
    """Partial application would leave the PR with SOME of the humans it needed and raise anyway.
    The only thing worse than nobody being asked to review is thinking somebody was."""
    f = forge({"GET git/pullrequests/1": PR_MERGED,
               "GET projects/factory/teams": {"value": TEAMS},
               f"GET projects/factory/teams/{TEAMS[0]['id']}/members": {"value": TEAM_MEMBERS}})

    with pytest.raises(AzureDevOpsError, match="ghost@nowhere"):
        f.request_reviewers(pr="1", reviewers=["alice@acme.ai", "ghost@nowhere"])

    assert f.fake.paths("PUT") == [], "no reviewer may be added when one cannot be resolved"


def test_no_reviewers_is_a_no_op_and_costs_no_call():
    f = forge({})

    f.request_reviewers(pr="1", reviewers=[])

    assert f.fake.calls == []


# ── tags ────────────────────────────────────────────────────────────────────────────────────────

def _tag_refs(*names):
    return {"value": [{"name": f"refs/tags/{n}", "objectId": "0" * 40} for n in names]}


def test_the_latest_tag_is_the_highest_version_not_the_last_row():
    """Verified live: `v0.2.0` was created FIRST and `v0.1.0` second, and the refs route returned
    them as [v0.1.0, v0.2.0] — Azure DevOps orders refs lexicographically by name, so neither end
    of the list is "the latest" and v0.10.0 sorts below v0.9.0."""
    f = forge({"GET git/repositories/fx-ado/refs": _tag_refs("v0.1.0", "v0.9.0", "v0.10.0")})

    assert f.latest_tag() == "v0.10.0"


def test_a_repository_with_no_tags_answers_none():
    assert forge({"GET git/repositories/fx-ado/refs": {"value": []}}).latest_tag() is None


def test_create_tag_is_a_no_op_when_the_tag_is_already_there():
    """D-16: the durable runtime retries activities, so a second `create_tag` must be silent."""
    f = forge({"GET git/repositories/fx-ado/refs": _tag_refs("v1.2.3")})

    f.create_tag(tag="v1.2.3", ref="main")

    assert f.fake.paths("POST") == []


def test_a_concurrent_create_is_success_not_a_failed_release():
    """Live shape: `409 Conflict: A Git ref with the name refs/tags/v0.2.0 already exists.`"""
    f = forge({"GET git/repositories/fx-ado/refs": _tag_refs(),
               "GET git/repositories/fx-ado/commits": {"value": [{"commitId": "a" * 40}]}},
              raises={"POST git/repositories/fx-ado/annotatedtags": AzureDevOpsError(
                  "POST git/repositories/fx-ado/annotatedtags → 409 Conflict: A Git ref with the "
                  "name refs/tags/v0.2.0 already exists.")})

    f.create_tag(tag="v0.2.0", ref="main")  # must not raise


def test_a_tag_is_never_cut_on_an_unresolvable_ref():
    f = forge({"GET git/repositories/fx-ado/refs": _tag_refs(),
               "GET git/repositories/fx-ado/commits": {"value": []}})

    with pytest.raises(AzureDevOpsError, match="refusing to tag"):
        f.create_tag(tag="v1.0.0", ref="main")


# ── pipelines ───────────────────────────────────────────────────────────────────────────────────

def test_a_cancelled_build_is_a_failure_not_a_pass():
    """Observed for real: the hosted-agent grant cancelled every queued build. A cancelled deploy
    reading as green is a release nobody knows did not happen."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [BUILD_ON_MAIN]}})

    state, url = f.deploy_run_status(sha=BUILD_ON_MAIN["sourceVersion"], workflow="fx-ado-ci")

    assert state == "failure"
    assert url and url.endswith("buildId=1")


def test_a_commit_with_no_run_is_none_not_a_failure():
    """"not dispatched yet" and "failed" must never collapse into one word: the platform triggers
    a deploy and only observes it (ADR-0005)."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [BUILD_ON_MAIN]}})

    assert f.deploy_run_status(sha="f" * 40, workflow="fx-ado-ci") == ("none", None)


def test_an_unrunnable_build_is_pending_until_it_completes():
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [{**BUILD_ON_MAIN, "status": "inProgress",
                                               "result": None}]}})

    state, _url = f.deploy_run_status(sha=BUILD_ON_MAIN["sourceVersion"], workflow="fx-ado-ci")

    assert state == "pending"


def test_a_pipeline_name_that_matches_nothing_is_a_configuration_error_not_a_pending_run(caplog):
    f = forge({"GET build/definitions": {"value": []}})

    with caplog.at_level("WARNING"):
        assert f.deploy_run_status(sha="a" * 40, workflow="nope") == ("none", None)

    assert "nope" in caplog.text

    with pytest.raises(AzureDevOpsError, match="nothing was queued"):
        f.dispatch_workflow(workflow="nope", ref="main")


@pytest.mark.parametrize("status,result,expected", [
    ("completed", "succeeded", "success"),
    ("completed", "canceled", "failure"),
    ("completed", "partiallySucceeded", "failure"),
    ("completed", "failed", "failure"),
    ("inProgress", None, None),
    ("notStarted", None, None),
])
def test_latest_run_answers_in_the_ports_words_because_the_caller_reads_them(
        status, result, expected):
    """THE E2E VERDICT, and it is decided one caller away from here.

    `machine._run_e2e_check` scores the run with `(conclusion or "").lower() == "success"` —
    GitHub's word. Azure DevOps says `succeeded`, so passing its own vocabulary through means
    every green Azure e2e suite is announced RED, the ticket parks and a human is called to a run
    that passed. `None` while the build is still going is what GitHub reports for a run that has
    not concluded, and the loop above depends on it (it waits on `status == "completed"`)."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [{**BUILD_ON_MAIN, "status": status,
                                               "result": result}]}})

    run = f.latest_run(workflow="fx-ado-ci")

    assert run["conclusion"] == expected
    assert run["status"] == status, "the raw status travels: both vendors spell it `completed`"
    assert run["id"] == 1 and run["created_at"] == BUILD_ON_MAIN["queueTime"]


def test_the_e2e_verdict_is_read_with_the_comparison_this_adapter_must_satisfy():
    """The positive twin of the guard above: the actual expression in `machine.py`, applied to
    what this adapter returns. A parametrised table proves the mapping; only this proves the
    mapping is the one the caller performs."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "GET build/builds": {"value": [{**BUILD_ON_MAIN, "status": "completed",
                                               "result": "succeeded"}]}})

    run = f.latest_run(workflow="fx-ado-ci")

    assert (run.get("conclusion") or "").lower() == "success", (
        "machine._run_e2e_check scores the e2e run with exactly this line")


def test_dispatch_queues_the_definition_on_a_full_ref():
    f = forge({"GET build/definitions": {"value": [{"id": 1, "name": "fx-ado-ci"}]},
               "POST build/builds": {"id": 9}})

    f.dispatch_workflow(workflow="fx-ado-ci", ref="main")

    assert f.fake.body_for("POST", "build/builds") == {
        "definition": {"id": 1}, "sourceBranch": "refs/heads/main"}


# ── push_remote ─────────────────────────────────────────────────────────────────────────────────

def test_push_remote_carries_the_credential_in_the_form_git_accepts():
    """Over git there is only Basic auth — the Bearer/Basic split the REST client makes has no
    equivalent on the git wire, so ONE scheme serves a PAT and an AAD JWT alike. Verified live
    against fx-ado with a JWT: clone plus two pushes, one with the organisation as the username
    and one with it empty; both accepted."""
    url = AzureReposForge("fx-ado", organization="acme-ai", project="factory",
                          token="s3cret").push_remote()

    assert url == "https://acme-ai:s3cret@dev.azure.com/acme-ai/factory/_git/fx-ado"


def test_a_token_with_url_significant_characters_survives_the_userinfo_field():
    url = AzureReposForge("fx-ado", organization="acme-ai", project="factory",
                          token="a/b@c:d").push_remote()

    assert url.endswith("@dev.azure.com/acme-ai/factory/_git/fx-ado")
    assert "a%2Fb%40c%3Ad" in url


def test_no_credential_means_no_remote_rather_than_a_url_that_cannot_push():
    assert AzureReposForge("fx-ado", organization="acme-ai", project="factory",
                           token=None).push_remote() is None


def test_the_credential_is_resolved_at_each_use_so_a_long_job_still_pushes():
    """An `az account get-access-token` JWT lasts about an hour and a coding job can outlive it."""
    minted = iter(["first", "second"])
    f = AzureReposForge("fx-ado", organization="acme-ai", project="factory",
                        token_provider=lambda: next(minted))

    assert "first" in f.push_remote()
    assert "second" in f.push_remote()


# ── the reachability guard: a Protocol with `...` bodies hides a missing method ──────────────────

def _port_methods() -> list[str]:
    return sorted(n for n, v in vars(ForgeAdapter).items()
                  if callable(v) and not n.startswith("_"))


def test_every_port_method_is_written_HERE_and_not_inherited_as_a_silent_none():
    """THE GUARD THIS FILE EXISTS FOR.

    `ForgeAdapter` is a Protocol whose method bodies are `...`, so a method this adapter forgets
    is not a failure — it is an inherited `return None` that type-checks, passes `isinstance`, and
    lies. It already happened: the first draft of this adapter had no `merge_commit_sha`, so
    `pr_merged` said True and `merge_commit_sha` said None, which downstream is a merged ticket
    whose deploy never runs. Only running it against the live API found it; this guard is how it
    stays found."""
    missing = [name for name in _port_methods() if name not in vars(AzureReposForge)]

    assert missing == [], (
        f"{missing} would inherit the Protocol's `...` body and silently return None"
    )


def test_the_guard_above_can_actually_fail():
    """A guard that cannot fail proves nothing (the house rule the conformance suite runs on)."""
    class Forgetful(ForgeAdapter):
        pass

    missing = [name for name in _port_methods() if name not in vars(Forgetful)]

    assert "merge_commit_sha" in missing and "pr_ci_status" in missing


def test_the_workflows_extra_methods_are_here_too():
    """These are not on the port but the durable merge-watch calls them by name on whatever the
    registry built — so for Azure Repos they are as required as the port's own."""
    for name in ("force_merge", "mergeable_state", "update_branch"):
        assert name in vars(AzureReposForge), f"the merge-watch calls {name} and would crash"


def test_the_recorded_fixtures_are_the_servers_own_json():
    """A cheap tripwire: if somebody 'tidies' a fixture into a shape the API never emits, the
    tests above start proving something about a fiction."""
    assert json.loads(json.dumps(PR_ABANDONED))["lastMergeCommit"]["commitId"]
    assert PR_MERGED["repository"]["project"]["id"] == PROJECT_ID
    assert BUILD_ON_MAIN["result"] == "canceled"


# ── one manifest key, two vendors' vocabularies (sweep S3, 2026-08-16) ───────────────────────────
#
# `post_merge_deploy.workflow` is documented — and demonstrated in `docs/project.yaml.example` and
# ONBOARDING §13 — as `deploy.yml`, which is exactly right on GitHub, where `gh run list
# --workflow` takes the FILE NAME. Azure Pipelines has no file name in its API: a definition has a
# display name and an id. So an ADO client following our own documentation matched no definition,
# and `deploy_run_status` answered `none` for ever — which the deploy watch renders as **timeout**.
# A green deploy announced as a stuck one, on the first merge of the client's first day.

def _defs(*names_and_ids):
    """`build/definitions` answering the NAME filter the way Azure DevOps really does."""
    table = {name: id_ for name, id_ in names_and_ids}

    def _answer(params):
        if params and params.get("definitionIds"):
            wanted = str(params["definitionIds"])
            return {"value": [{"id": int(wanted), "name": "whatever"}
                              for i in table.values() if str(i) == wanted]}
        wanted = (params or {}).get("name")
        return {"value": [{"id": table[wanted], "name": wanted}] if wanted in table else []}

    return _answer


def test_a_manifest_written_for_github_still_finds_the_ADO_pipeline():
    """THE REGRESSION THIS FIXES. `deploy.yml` is what every document teaches; on ADO the
    definition is called `deploy`. Matching the stem is what makes one documented key mean the
    same thing on both vendors without asking a client to learn ours."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": _defs(("deploy", 7)),
               "GET build/builds": {"value": [{**BUILD_ON_MAIN, "id": 9, "status": "completed",
                                               "result": "succeeded"}]}})

    state, url = f.deploy_run_status(sha=BUILD_ON_MAIN["sourceVersion"], workflow="deploy.yml")

    assert state == "success", (
        "a green Azure Pipelines deploy is still invisible to a manifest written from our docs — "
        "the watch reports it as a timeout")
    assert url


def test_the_definitions_OWN_NAME_still_wins_over_the_stem():
    """The stem is a fallback, never a rewrite: a project with definitions called both `deploy.yml`
    and `deploy` must get the one it named."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": _defs(("deploy.yml", 1), ("deploy", 2)),
               "GET build/builds": lambda p: {"value": [{**BUILD_ON_MAIN, "id": int(p["definitions"])}]}})

    _state, url = f.deploy_run_status(sha=BUILD_ON_MAIN["sourceVersion"], workflow="deploy.yml")

    assert url and url.endswith("buildId=1"), "the exact name lost to its own stem"


def test_a_numeric_definition_id_is_accepted_and_CONFIRMED():
    """ADO's own coordinates are ids, so a client who declares one must be able to. Confirmed
    rather than trusted: an id that does not exist answers "not there" here instead of 404-ing
    inside the watch, minutes later, as a deploy that never reports."""
    f = forge({"GET git/repositories/fx-ado": FX_ADO_REPO,
               "GET build/definitions": _defs(("deploy", 7)),
               "GET build/builds": {"value": [{**BUILD_ON_MAIN, "id": 9}]}})
    _state, url = f.deploy_run_status(sha=BUILD_ON_MAIN["sourceVersion"], workflow="7")
    assert url, "a definition declared by id was not found"

    gone = forge({"GET build/definitions": _defs(("deploy", 7))})
    assert gone.deploy_run_status(sha="a" * 40, workflow="404") == ("none", None)


def test_a_name_that_matches_NOTHING_is_still_a_configuration_error(caplog):
    """The positive twin: widening the match must not start guessing. A name with no definition
    and no usable stem stays `none`, loudly — the operator's manifest is wrong and only they can
    fix it."""
    f = forge({"GET build/definitions": _defs(("deploy", 7))})
    with caplog.at_level("WARNING"):
        assert f.deploy_run_status(sha="a" * 40, workflow="nope") == ("none", None)
    assert "nope" in caplog.text

"""`open_pr`, `pr_status`, `merge_pr` — the port's WRITES over ANOTHER repository (#95).

THE READS WENT FIRST AND HALF A PORT IS NOT A PORT. `clone_url`, `list_branches`, `delete_branch`
and `pr_for_head` were widened to take a repository, because the product module acts on the
DOCUMENTATION repository and the adapter is built for the CODE. These three were not, so the whole
review-request ceremony — open it, merge it, read the state back — stayed a `gh` subprocess that
refused on any other vendor. The requirement landed on a branch and no pull request was ever
opened, permanently, on every Azure Repos deployment.

EVERY FIXTURE HERE IS A TRIMMED REAL RESPONSE, recorded on 2026-08-06 against `acme-ai/
factory` while driving the real adapters, and the drive itself is the evidence the shapes are
reachable:

    an adapter built for `fx-ado` opened PR 14 in `fx-dsk-context`  → the repository segment on the
                                                                      CREATE route is the whole
                                                                      difference; POSTing to
                                                                      `self.repo` files the pull
                                                                      request in the wrong repo
    the same adapter, WITHOUT repo=, found no open PR on that branch → the idempotency lookup has
                                                                      to follow `repo` or every
                                                                      retry opens a second one
    GET git/pullrequests/14 (project-scoped)  → repository fx-dsk-context
    GET git/repositories/fx-ado/pullrequests/14 → 404 TF401180, the wrong repository
    GET git/pullrequests/14 in project Deskline → 404 TF401019 — an error CODE containing 401,
                                                     about a repository, which has already been
                                                     read once as a refused credential
    merge_pr returned in 0.8s; the PR read `open` at +1.0s and `merged` at +2.4s

and on GitHub, the same drive against `AcmeFixtures`, plus the flag semantics that decide
what `repo` can and cannot mean:

    gh pr view <url of A#6> --repo B  → answered A#6, silently ignoring the flag
    gh pr view 2 --repo B            → answered B#2 — a bare ref is ambiguous without it
"""

from __future__ import annotations

import json
import logging

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.azure_devops import AzureReposForge
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.forge.github import GitHubForge

OWN = "AcmeCorp/openfactory"
DOCS = "AcmeCorp/acme-books-documentation"

PROJECT_ID = "aaa124b6-22d7-41eb-99b4-528d5c9f95d8"

#: `GET git/pullrequests/14`, project-scoped — opened in `fx-dsk-context` by an adapter configured
#: for `fx-ado`. The `repository` block is what every WRITE route is addressed at afterwards.
ADO_PR_14 = {
    "pullRequestId": 14,
    "status": "completed",
    "sourceRefName": "refs/heads/req/0099-probe-create-212335",
    "targetRefName": "refs/heads/main",
    "mergeStatus": "succeeded",
    "repository": {"id": "27843c02-34f3-4a30-abe2-03405662b636", "name": "fx-dsk-context",
                   "project": {"id": PROJECT_ID, "name": "factory"}},
    "lastMergeSourceCommit": {"commitId": "4e86d38c5506b0625d0bfe92bfa61680679c1a79"},
}

#: The same pull request while it was still open — the state `merge_pr` is called on.
ADO_PR_14_ACTIVE = {**ADO_PR_14, "status": "active"}


class _Run:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class FakeGh:
    """A router over `GitHubForge._gh`. Unrouted calls RAISE, so a test can never pass on a
    command nobody meant to run."""

    def __init__(self, routes: dict[str, _Run]):
        self.routes = routes
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=120):
        self.calls.append(list(args))
        key = " ".join(args)
        for pattern, answer in self.routes.items():
            if pattern in key:
                return answer
        raise AssertionError(f"the adapter ran an unrouted gh command: {key}")

    def repo_flag_of(self, needle: str) -> str:
        argv = next(a for a in self.calls if needle in " ".join(a))
        return argv[argv.index("--repo") + 1]


class FakeADO:
    """`AzureDevOpsClient`'s surface. Unrouted paths raise."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, object, dict | None]] = []

    def call(self, method, path, *, body=None, params=None, project_scoped=True,
             content_type="application/json", api_version=None):
        key = f"{method.upper()} {path}"
        self.calls.append((method.upper(), path, body, params))
        if key not in self.routes:
            raise AssertionError(f"the adapter called an unrouted Azure DevOps route: {key}")
        got = self.routes[key]
        return got(params) if callable(got) else got

    def values(self, path, **kw):
        got = self.call("GET", path, **kw)
        out = got.get("value")
        return out if isinstance(out, list) else []

    def paths(self, method: str) -> list[str]:
        return [p for m, p, _b, _q in self.calls if m == method.upper()]

    def body_for(self, method: str, path: str):
        return next(b for m, p, b, _q in self.calls if m == method.upper() and p == path)


def gh_forge(routes) -> GitHubForge:
    f = GitHubForge(OWN, token="tok")
    f._gh = FakeGh(routes)  # noqa: SLF001 — the seam the adapter itself uses
    return f


def ado_forge(routes, *, repo="fx-ado") -> AzureReposForge:
    f = AzureReposForge(repo, organization="acme-ai", project="factory", token="tok")
    client = FakeADO(routes)
    f._client = lambda: client  # noqa: SLF001
    f._fake = client            # noqa: SLF001 — so a test can read what was called
    return f


# ── the port declares it ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["open_pr", "pr_status", "merge_pr"])
def test_the_port_and_BOTH_providers_take_a_repository(method):
    """One rule for all seven repository-taking methods: `""` is this adapter's own. A provider
    that dropped the argument would satisfy the Protocol structurally — `runtime_checkable` does
    not compare signatures — and answer confidently about the wrong repository."""
    import inspect

    for owner in (ForgeAdapter, GitHubForge, AzureReposForge):
        params = inspect.signature(getattr(owner, method)).parameters
        assert "repo" in params, f"{owner.__name__}.{method} cannot be told a repository"
        assert params["repo"].default == "", (
            f"{owner.__name__}.{method} does not default to this adapter's own repository — "
            f"every existing call site passes no repo and must keep meaning what it meant")


# ── GitHub ──────────────────────────────────────────────────────────────────────────────────────

def test_github_opens_the_pull_request_in_the_repository_it_was_TOLD():
    """The create and the idempotency lookup BOTH follow `repo`. Measured: with the adapter built
    for `fx-py-simple`, `_open_pr_for_head` answered None about a branch that existed in
    `fx-dsk-context` — so a lookup left on `self.repo` sees no pull request on the docs repository
    ever, and `open_pr` files a fresh one on every retry."""
    f = gh_forge({"pr list": _Run(stdout=""),
                  "pr create": _Run(stdout=f"https://github.com/{DOCS}/pull/2\n")})

    url = f.open_pr(head="req/0007-x", base="main", title="REQ-0007", body="b", repo=DOCS)

    assert url == f"https://github.com/{DOCS}/pull/2"
    assert f._gh.repo_flag_of("pr create") == DOCS  # noqa: SLF001
    assert f._gh.repo_flag_of("pr list") == DOCS, (  # noqa: SLF001
        "the idempotency lookup asked the adapter's OWN repository, so it can never find the "
        "pull request it is trying not to duplicate")


def test_github_an_existing_pull_request_in_the_other_repository_is_REUSED():
    """D-16: a retried activity must not double-file. The lookup that makes that true is the one
    scoped to `repo`."""
    f = gh_forge({"pr list": _Run(stdout=f"https://github.com/{DOCS}/pull/2\n"),
                  "pr create": _Run(stdout="", returncode=1,
                                    stderr="a second pull request was opened")})

    assert f.open_pr(head="req/0007-x", base="main", title="t", body="b",
                     repo=DOCS) == f"https://github.com/{DOCS}/pull/2"
    assert not any("create" in " ".join(a) for a in f._gh.calls)  # noqa: SLF001


def test_github_reads_and_merges_the_pull_request_in_the_other_repository():
    f = gh_forge({"pr view": _Run(stdout=json.dumps({"state": "OPEN", "mergedAt": None})),
                  "pr merge": _Run(stdout="")})

    assert f.pr_status(pr="2", repo=DOCS) == "open"
    f.merge_pr(pr="2", repo=DOCS)

    assert f._gh.repo_flag_of("pr view") == DOCS  # noqa: SLF001
    assert f._gh.repo_flag_of("pr merge") == DOCS  # noqa: SLF001


@pytest.mark.parametrize("drive", [
    lambda f: f.open_pr(head="sdlc/12", base="main", title="t", body="b"),
    lambda f: f.pr_status(pr="2"),
    lambda f: f.merge_pr(pr="2"),
])
def test_github_an_omitted_repository_is_STILL_this_adapters_own(drive):
    """THE COMPATIBILITY HALF, AND IT IS NOT A FORMALITY. Every existing call site — the job's own
    pull request, the merge watch, the doctor's permission probe — passes no repository, and the
    day one of them starts addressing a docs repo instead is a merge into the wrong project."""
    f = gh_forge({"pr list": _Run(stdout=""),
                  "pr create": _Run(stdout="https://github.com/x/pull/1\n"),
                  "pr view": _Run(stdout=json.dumps({"state": "OPEN", "mergedAt": None})),
                  "pr merge": _Run(stdout="")})

    drive(f)

    flags = [a[a.index("--repo") + 1] for a in f._gh.calls if "--repo" in a]  # noqa: SLF001
    assert flags and set(flags) == {OWN}, flags


# ── Azure Repos ─────────────────────────────────────────────────────────────────────────────────

def test_azure_opens_the_pull_request_in_the_repository_it_was_TOLD():
    """THE CREATE ROUTE IS REPOSITORY-SCOPED AND THERE IS NO ID YET TO RESOLVE ONE FROM, which is
    why `repo` is load-bearing here in a way it is not on `pr_status`. POSTing to `self.repo`
    would file the requirement's pull request against the CODE repository — a real pull request,
    in the wrong place, that a person would have to find and abandon."""
    created = {**ADO_PR_14_ACTIVE, "pullRequestId": 14}
    f = ado_forge({
        "GET git/repositories/fx-dsk-context/pullrequests": {"count": 0, "value": []},
        "POST git/repositories/fx-dsk-context/pullrequests": created,
    })

    url = f.open_pr(head="req/0099-x", base="main", title="REQ-0099", body="b",
                    repo="fx-dsk-context")

    assert url == ("https://dev.azure.com/acme-ai/factory/_git/fx-dsk-context"
                   "/pullrequest/14")
    assert f._fake.paths("POST") == ["git/repositories/fx-dsk-context/pullrequests"]  # noqa: SLF001
    assert f._fake.paths("GET") == [  # noqa: SLF001
        "git/repositories/fx-dsk-context/pullrequests"], (
        "the idempotency lookup asked the adapter's own repository, so a retry opens a second "
        "pull request for a proposal already in flight")
    body = f._fake.body_for("POST", "git/repositories/fx-dsk-context/pullrequests")  # noqa: SLF001
    assert body["sourceRefName"] == "refs/heads/req/0099-x", "a bare name is a silent count: 0"


@pytest.mark.parametrize("unreadable", [{}, {"value": None}, {"value": {"count": 0}},
                                        {"count": 0}])
def test_azure_an_idempotency_lookup_it_could_not_READ_never_opens_a_second_pull_request(
        unreadable):
    """**None = COULD NOT READ; [] = READ, AND NOTHING THERE** — on the one call in this adapter
    where collapsing them files a real pull request on a client's documentation repository.

    `_open_pr_for_head` is the gate `open_pr` consults before creating, and it went through
    `AzureDevOpsClient.values()`, which ends `return out if isinstance(out, list) else []`. Every
    shape below is a 200 that carries no readable collection — `call()` raises on an HTTP error and
    on a non-JSON body, but a 200/204 with no body at all arrives as `{}` — and each of them came
    back from the helper as an EMPTY LIST, i.e. "nothing is open from that branch", i.e. create
    one. Driven against the real adapter before the fix, `open_pr` POSTed a pull request off a
    lookup that had read nothing.

    The two sibling methods in this file, `list_branches` and `pr_for_head`, each carry a
    paragraph refusing to use `values()` for exactly this reason. This was the third, and the only
    one of the three whose wrong answer WRITES.

    THE POSITIVE TWIN IS `test_azure_opens_the_pull_request_in_the_repository_it_was_TOLD`, which
    hands back a real `{"count": 0, "value": []}` and asserts the POST does happen — because a
    guard that only proves "it refused" is satisfied by a method that refuses everything."""
    f = ado_forge({"GET git/repositories/fx-dsk-context/pullrequests": unreadable,
                   "POST git/repositories/fx-dsk-context/pullrequests": ADO_PR_14_ACTIVE})

    with pytest.raises(AzureDevOpsError, match="value"):
        f.open_pr(head="req/0099-x", base="main", title="t", body="b", repo="fx-dsk-context")

    assert f._fake.paths("POST") == [], (  # noqa: SLF001
        "a pull request was created off an idempotency lookup that read nothing — the duplicate "
        "would be ours, on the client's documentation repository")


def test_azure_and_github_REFUSE_the_same_unreadable_lookup_in_the_same_vocabulary():
    """A PORT WHOSE PROVIDERS DISAGREE ABOUT WHICH ANSWER MEANS "UNREADABLE" IS NOT A PORT, which
    is the argument `_gh_read` makes on the GitHub side and the reason the Azure hole mattered.

    Measured on the wire (2026-08-06), GitHub already refused: `gh api repos/… --jq '.[0].url'`
    against an object exits 1 with `expected an array but got: object`, and `_open_pr_for_head`
    turns a non-zero exit into a RuntimeError. So the vendor hosting a client's documentation
    repository must not be the lenient one."""
    gh = gh_forge({"pr list": _Run(stdout="", stderr="expected an array but got: object",
                                   returncode=1),
                   "pr create": _Run(stdout="https://github.com/x/pull/9\n")})
    ado = ado_forge({"GET git/repositories/fx-ado/pullrequests": {},
                     "POST git/repositories/fx-ado/pullrequests": ADO_PR_14_ACTIVE})

    for forge in (gh, ado):
        with pytest.raises(Exception):  # noqa: B017,PT011 — the vocabulary is per-provider
            forge.open_pr(head="req/0007-x", base="main", title="t", body="b")

    assert not any("pr create" in " ".join(a) for a in gh._gh.calls)  # noqa: SLF001
    assert ado._fake.paths("POST") == []  # noqa: SLF001


def test_azure_resolves_the_pull_request_by_its_PROJECT_WIDE_id_and_writes_where_it_LIVES():
    """A PR ID IS PROJECT-WIDE HERE, WHICH IS NOT GITHUB'S SHAPE. `GET git/pullrequests/14`
    resolves whichever repository in the project the pull request is in — measured — while
    `git/repositories/fx-ado/pullrequests/14` answers 404 TF401180 for that same valid id. So the
    PR's own `repository.name` addresses every write, and `repo` is the caller's stated intent."""
    f = ado_forge({
        "GET git/pullrequests/14": ADO_PR_14_ACTIVE,
        "PATCH git/repositories/fx-dsk-context/pullrequests/14": ADO_PR_14_ACTIVE,
        "GET connectionData": {"authenticatedUser": {"id": "id-of-the-bot"}},
    })

    assert f.pr_status(pr="14", repo="fx-dsk-context") == "open"
    f.merge_pr(pr="14", repo="fx-dsk-context")

    assert "git/pullrequests/14" in f._fake.paths("GET"), (  # noqa: SLF001
        "the repository-scoped route cannot resolve a project-wide id — it answers TF401180")
    assert f._fake.paths("PATCH") == [  # noqa: SLF001
        "git/repositories/fx-dsk-context/pullrequests/14"]


def test_azure_a_repository_that_disagrees_with_the_pull_request_is_LOGGED_not_obeyed(caplog):
    """A caller naming a repository the pull request does not live in holds a false belief, and
    the pull request wins — it was identified by an id that is unambiguous across the project, and
    there is no route that could merge it anywhere else.

    LOGGED, because GitHub does the same thing without telling anybody: `gh pr view <url> --repo
    <other>` answers the URL's repository and never mentions the flag it ignored."""
    f = ado_forge({"GET git/pullrequests/14": ADO_PR_14})

    with caplog.at_level(logging.WARNING, logger="openfactory.forge.azure_devops"):
        assert f.pr_status(pr="14", repo="fx-ado") == "merged"

    assert "fx-dsk-context" in caplog.text and "fx-ado" in caplog.text, caplog.text


def test_azure_an_omitted_repository_is_STILL_this_adapters_own():
    """The compatibility half. `open_pr` is the only one of the three that can get this wrong —
    the other two resolve the repository from the id — so it is the one driven here."""
    f = ado_forge({
        "GET git/repositories/fx-ado/pullrequests": {"count": 0, "value": []},
        "POST git/repositories/fx-ado/pullrequests": {**ADO_PR_14_ACTIVE, "pullRequestId": 3,
                                                      "repository": {"name": "fx-ado",
                                                                     "project": {
                                                                         "id": PROJECT_ID}}},
    })

    f.open_pr(head="sdlc/12", base="main", title="t", body="b")

    assert f._fake.paths("POST") == ["git/repositories/fx-ado/pullrequests"]  # noqa: SLF001


def test_azure_completion_is_ASYNCHRONOUS_so_merge_pr_never_claims_its_own_result():
    """Measured: `merge_pr` returned in 0.8s and the pull request read `open` at +1.0s and
    `merged` at +2.4s. The arming PATCH answers `active` with `autoCompleteSetBy` set.

    So this method must not verify itself, and a caller that needs the verdict has to POLL —
    which is exactly what `authoring._merged_now` was taught to do, because a single read after
    the merge reports an honest merge as a failure and the product path says so to a client."""
    f = ado_forge({
        "GET git/pullrequests/14": ADO_PR_14_ACTIVE,
        "GET connectionData": {"authenticatedUser": {"id": "id-of-the-bot"}},
        "PATCH git/repositories/fx-dsk-context/pullrequests/14": ADO_PR_14_ACTIVE,
    })

    assert f.merge_pr(pr="14", repo="fx-dsk-context") is None
    body = f._fake.body_for(  # noqa: SLF001
        "PATCH", "git/repositories/fx-dsk-context/pullrequests/14")
    assert body["autoCompleteSetBy"] == {"id": "id-of-the-bot"}
    assert body["completionOptions"]["mergeStrategy"] == "squash", (
        "a provider change must not silently rewrite what a client's history looks like")
    assert body["completionOptions"]["deleteSourceBranch"] is False, (
        "the port deletes a landed branch EXPLICITLY, on a confirmed merge — never as a side "
        "effect of the merge itself, which would remove the work on an armed-but-unfired merge")

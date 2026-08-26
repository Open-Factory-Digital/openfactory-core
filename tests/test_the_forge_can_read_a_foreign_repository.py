"""`list_branches`, `delete_branch`, `pr_for_head` — the port's reads over ANOTHER repository.

WHY THESE THREE EXIST. The forge port was designed from what a job WRITES: open a pull request,
merge it, tag a release, all about `self.repo`. The product module does not fit that shape at all
— it proposes a requirement as a branch and a PR in the DOCUMENTATION repository — so it never
used the port and shells out to `gh` instead. The moment a deployment moved off GitHub, that
capability did not port, it vanished: `openfactory/product/authoring.py` now refuses (safely, rather than
exporting an Azure PAT to github.com) and the requirement lands on a branch with no pull request.

EVERY AZURE FIXTURE HERE IS A TRIMMED REAL RESPONSE recorded on 2026-08-06 against
`acme-ai/factory`, repository `fx-ado`, and three of them are the reason the implementations
are not one-liners:

    `searchCriteria` DEFAULTS TO ACTIVE            asked about `probe/abandon` with no status the
                                                   server said count: 0; with `status=all` it said
                                                   three pull requests. A "has this branch ever
                                                   been proposed?" that omits it answers no about
                                                   a branch proposed three times.

    A BRANCH DELETE IS `200 OK` EVEN WHEN REFUSED  the verdict is `value[0].success`, so a
                                                   provider trusting the HTTP status reports a
                                                   `permissionDenied` as a successful cleanup.

    THREE WORDS FOR ONE OUTCOME                    `succeeded`, `succeededCorruptRef` and
                                                   `succeededNonExistentRef`, produced live by
                                                   creating a scratch ref and taking it apart.

The GitHub side's own live finding is in `test_a_refused_delete_and_an_already_gone_branch_are_not
_the_same_answer`: `gh api -X DELETE` exits 1 for BOTH `422 Reference does not exist` and `403`,
which is the collapse this whole file is about, one vendor over.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.azure_devops import AzureReposForge
from openfactory.adapters.forge.base import ForgeAdapter
from openfactory.adapters.forge.github import GitHubForge

# ── recorded shapes ─────────────────────────────────────────────────────────────────────────────

REPO_ID = "21200617-5ca5-4819-a6e0-68bbec2c964c"
PROJECT_ID = "aaa124b6-22d7-41eb-99b4-528d5c9f95d8"
FX_ADO_REPO = {"id": REPO_ID, "name": "fx-ado",
               "project": {"id": PROJECT_ID, "name": "factory"}}

#: `GET git/repositories/fx-ado/refs?filter=heads/` — the server's own seven, in its own order.
ADO_HEADS = {"count": 7, "value": [
    {"name": "refs/heads/main", "objectId": "4c9cf9c56a9112a2aa41e117c537ff82b159f4db"},
    {"name": "refs/heads/probe/abandon", "objectId": "aea6f3c9e132c3f7a430ed39a15b6adccbd6bcc4"},
    {"name": "refs/heads/probe/auto-complete",
     "objectId": "ce7d186febbfda347088203fba4689a18fad3e48"},
    {"name": "refs/heads/probe/forge-jwt-push",
     "objectId": "0c288d73b39972ef2d80aede28e2f84bf47c0609"},
    {"name": "refs/heads/sdlc/12", "objectId": "1111111111111111111111111111111111111111"},
    {"name": "refs/heads/sdlc/13", "objectId": "2222222222222222222222222222222222222222"},
    {"name": "refs/heads/sdlc/14", "objectId": "3333333333333333333333333333333333333333"},
]}

#: The same route with `filter=heads/probe/` — the narrowing really happens on the server.
ADO_HEADS_PROBE = {"count": 3, "value": ADO_HEADS["value"][1:4]}

#: `searchCriteria.sourceRefName=refs/heads/probe/abandon&searchCriteria.status=all` — three pull
#: requests for ONE branch, newest first. With the status omitted this same call answered count: 0.
ADO_PRS_FOR_ABANDON = {"count": 3, "value": [
    {"pullRequestId": 7, "status": "abandoned", "sourceRefName": "refs/heads/probe/abandon",
     "repository": FX_ADO_REPO},
    {"pullRequestId": 6, "status": "completed", "sourceRefName": "refs/heads/probe/abandon",
     "repository": FX_ADO_REPO},
    {"pullRequestId": 4, "status": "abandoned", "sourceRefName": "refs/heads/probe/abandon",
     "repository": FX_ADO_REPO},
]}

#: `POST git/repositories/fx-ado/refs` with old=new=40 zeroes, on a ref that WAS there.
ADO_DELETED = {"count": 1, "value": [
    {"repositoryId": REPO_ID, "name": "refs/heads/probe/branch-port-scratch",
     "oldObjectId": "0" * 40, "newObjectId": "0" * 40,
     "isLocked": False, "updateStatus": "succeededCorruptRef", "success": True}]}

#: The same call a second time — the ref is gone, and Azure DevOps still answers 200/success.
ADO_ALREADY_GONE = {"count": 1, "value": [
    {"repositoryId": REPO_ID, "name": "refs/heads/probe/branch-port-scratch",
     "oldObjectId": "0" * 40, "newObjectId": "0" * 40,
     "isLocked": False, "updateStatus": "succeededNonExistentRef", "success": True}]}

#: A refusal. HTTP 200, `success: false` — the shape that makes the status code useless here.
ADO_REFUSED = {"count": 1, "value": [
    {"repositoryId": REPO_ID, "name": "refs/heads/main",
     "updateStatus": "permissionDenied", "success": False}]}

#: `GET repos/{o}/{r}/git/matching-refs/heads/` — GitHub always answers an ARRAY, even for one.
GH_MATCHING_REFS = [
    {"ref": "refs/heads/main", "object": {"sha": "185590f"}},
    {"ref": "refs/heads/req/0007-relatorio-mensal", "object": {"sha": "aaaaaaa"}},
]


# ── seams ───────────────────────────────────────────────────────────────────────────────────────

class _Run:
    """What `subprocess.run` hands back, with only the fields the adapter reads."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class FakeGh:
    """A router over `GitHubForge._gh`, keyed on the argv the adapter composes.

    Unrouted calls RAISE, so a test can never pass on a command nobody meant to run."""

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

    def argv_containing(self, needle: str) -> list[str]:
        return next(a for a in self.calls if needle in " ".join(a))


class FakeADO:
    """`AzureDevOpsClient`'s exact surface, with `values()` DERIVED from `call()` as on the real
    one — so a route that answers a bare object cannot look like a collection here and not in
    production. Unrouted paths raise."""

    def __init__(self, routes: dict, raises: dict | None = None):
        self.routes = routes
        self.raises = raises or {}
        self.calls: list[tuple[str, str, object, dict | None]] = []

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

    def params_for(self, method: str, path: str) -> dict:
        return next(q for m, p, _b, q in self.calls if m == method and p == path) or {}

    def body_for(self, method: str, path: str):
        return next(b for m, p, b, _q in self.calls if m == method and p == path)


def gh_forge(routes) -> GitHubForge:
    f = GitHubForge("AcmeCorp/openfactory", token="tok")
    f._gh = FakeGh(routes)  # noqa: SLF001 — the seam the adapter itself uses
    return f


def ado_forge(routes, raises=None, *, repo="fx-ado") -> AzureReposForge:
    f = AzureReposForge(repo, organization="acme-ai", project="factory", token="tok")
    client = FakeADO(routes, raises)
    f._client = lambda: client  # noqa: SLF001
    f.fake = client
    return f


# ── the port exists on BOTH vendors, or it is not a port ────────────────────────────────────────

@pytest.mark.parametrize("adapter", [GitHubForge, AzureReposForge])
@pytest.mark.parametrize("method", ["list_branches", "delete_branch", "pr_for_head"])
def test_both_adapters_write_the_method_instead_of_inheriting_a_silent_none(adapter, method):
    """`ForgeAdapter` is a Protocol with `...` bodies, and both adapters SUBCLASS it — so a method
    one of them forgets is not an error, it is an inherited `return None` that type-checks and
    passes `isinstance`. For `list_branches` that None is this port's word for "I could not read",
    which the product module would believe about a repository that is perfectly healthy.

    `test_the_ado_forge.py` already guards the Azure half against the whole port; this guards both
    halves against these three, because GitHub has no such guard of its own."""
    assert method in vars(adapter), (
        f"{adapter.__name__}.{method} would inherit the Protocol's `...` body and return None"
    )


def test_the_three_are_on_the_port_and_not_only_on_the_adapters():
    """A method two adapters happen to share is a coincidence; a method on the Protocol is a
    contract a third vendor is held to."""
    for name in ("list_branches", "delete_branch", "pr_for_head"):
        assert name in vars(ForgeAdapter), f"{name} is not on ForgeAdapter"


# ── list_branches ───────────────────────────────────────────────────────────────────────────────

def test_github_lists_bare_branch_names_and_filters_at_the_server():
    f = gh_forge({"matching-refs": _Run(stdout=json.dumps(GH_MATCHING_REFS))})

    assert f.list_branches(prefix="req/") == ["main", "req/0007-relatorio-mensal"]
    argv = f._gh.argv_containing("matching-refs")  # noqa: SLF001
    assert "repos/AcmeCorp/openfactory/git/matching-refs/heads/req/" in " ".join(argv)
    assert "--paginate" in argv, "without it a repository over 30 branches is silently truncated"


def test_github_answers_a_shape_it_does_not_understand_as_unreadable():
    """`[]` for an answer we cannot parse would tell the product module there are no proposals in
    flight, and it would mint a number an unlanded branch already claims — two requirement files
    under one identity, which is the citation corruption `next_number` exists to prevent."""
    html = gh_forge({"matching-refs": _Run(stdout="<!DOCTYPE html>")})
    an_object = gh_forge({"matching-refs": _Run(stdout='{"message": "Moved Permanently"}')})

    assert html.list_branches(prefix="req/") is None
    assert an_object.list_branches(prefix="req/") is None


def test_github_answers_the_empty_list_apart_from_the_unreadable_one():
    """The whole reason this method's return type has a None in it."""
    empty = gh_forge({"matching-refs": _Run(stdout="[]")})
    broken = gh_forge({"matching-refs": _Run(stderr="gh: Not Found (HTTP 404)", returncode=1)})

    assert empty.list_branches(prefix="req/") == []
    assert broken.list_branches(prefix="req/") is None


#: The three shapes that are NOT a collection, and the reason each one reaches an adapter.
#: `{}` is what `AzureDevOpsClient.call` returns for a 200 or 204 carrying no body at all; the
#: other two are an answer whose `value` never arrived or arrived as something else.
UNREADABLE_ADO_SHAPES = [{}, {"count": 0}, {"value": {"name": "refs/heads/main"}}]


@pytest.mark.parametrize("answer", UNREADABLE_ADO_SHAPES)
def test_azure_answers_a_shape_it_does_not_understand_as_unreadable(answer):
    """THE SIBLING OF THE GITHUB TEST TWO ABOVE, AND IT USED TO FAIL. `list_branches` went through
    `AzureDevOpsClient.values()`, whose last line is `return out if isinstance(out, list) else []`
    — so every shape here arrived as an empty COLLECTION, this port's word for "I read the
    repository and there is nothing in it", while the GitHub half answered None for the same
    input. One port, two dialects of "unreadable", and the caller that believes the empty one
    mints a requirement number a live `req/*` branch already claims."""
    branches = ado_forge({"GET git/repositories/fx-ado/refs": answer})
    prs = ado_forge({"GET git/repositories/fx-ado/pullrequests": answer})

    assert branches.list_branches(prefix="req/") is None
    assert prs.pr_for_head("req/0007-x") is None, "and `\"\"` here opens a duplicate pull request"


def test_azure_reads_a_non_empty_answer_of_rows_it_cannot_read_as_unreadable():
    """`count: 3` and not one row this adapter can index is not `count: 0`. The distinction is the
    whole port: an empty COLLECTION is an answer, rows we failed to parse are not one."""
    f = ado_forge({"GET git/repositories/fx-ado/pullrequests": {"count": 1,
                                                               "value": ["not a row"]}})

    assert f.pr_for_head("req/0007-x") is None


def test_azure_lists_bare_branch_names_and_asks_for_the_prefix():
    f = ado_forge({"GET git/repositories/fx-ado/refs": ADO_HEADS_PROBE})

    assert f.list_branches(prefix="probe/") == [
        "probe/abandon", "probe/auto-complete", "probe/forge-jwt-push"]
    assert f.fake.params_for("GET", "git/repositories/fx-ado/refs") == {"filter": "heads/probe/"}


def test_azure_answers_the_empty_list_apart_from_the_unreadable_one():
    """Verified live: `filter=heads/nosuch/` is `{"value": [], "count": 0}` and a repository that
    is not there is `404 TF401019`, so the server already separates these two."""
    empty = ado_forge({"GET git/repositories/fx-ado/refs": {"count": 0, "value": []}})
    broken = ado_forge({}, raises={"GET git/repositories/fx-ado/refs": AzureDevOpsError(
        "GET git/repositories/fx-ado/refs → 404 Not Found: TF401019")})

    assert empty.list_branches(prefix="req/") == []
    assert broken.list_branches(prefix="req/") is None


def test_the_repository_argument_is_honoured_on_both_and_defaults_to_the_adapters_own():
    """The point of all three methods: the product module asks about the DOCS repository, which is
    not the one the adapter was built for."""
    gh = gh_forge({"matching-refs": _Run(stdout="[]")})
    gh.list_branches("AcmeCorp/acme-docs", prefix="req/")
    gh.list_branches(prefix="req/")
    asked = [" ".join(a) for a in gh._gh.calls]  # noqa: SLF001
    assert "repos/AcmeCorp/acme-docs/git/matching-refs" in asked[0]
    assert "repos/AcmeCorp/openfactory/git/matching-refs" in asked[1]

    ado = ado_forge({"GET git/repositories/fx-docs/refs": {"value": []},
                     "GET git/repositories/fx-ado/refs": {"value": []}})
    # C-18 hands qualified `project/repo` refs around; the project is already in the adapter's
    # coordinates, so only the last segment is the repository.
    assert ado.list_branches("factory/fx-docs") == []
    assert ado.list_branches() == []


# ── delete_branch ───────────────────────────────────────────────────────────────────────────────

def test_azure_deletes_by_writing_forty_zeroes_and_says_so_when_the_ref_was_already_gone():
    deleted = ado_forge({"POST git/repositories/fx-ado/refs": ADO_DELETED})
    gone = ado_forge({"POST git/repositories/fx-ado/refs": ADO_ALREADY_GONE})

    assert deleted.delete_branch("probe/branch-port-scratch") is True
    assert gone.delete_branch("probe/branch-port-scratch") is True, (
        "already gone is the post-condition the sweep asked about — it must converge, not error")
    body = deleted.fake.body_for("POST", "git/repositories/fx-ado/refs")
    assert body == [{"name": "refs/heads/probe/branch-port-scratch",
                     "oldObjectId": "0" * 40, "newObjectId": "0" * 40}]


def test_azure_reads_the_verdict_out_of_the_body_because_a_refusal_is_also_200_ok():
    """THE ONE THAT MATTERS. `POST refs` answers `200 OK` whatever happens; the truth is in
    `value[0].success`. A provider that returned True on a successful HTTP call would report a
    `permissionDenied` as a cleaned-up branch — the sweep would stop looking at a branch it never
    deleted, and the log would say nothing at all."""
    refused = ado_forge({"POST git/repositories/fx-ado/refs": ADO_REFUSED})

    assert refused.delete_branch("main") is False


def test_azure_reports_an_empty_or_unreachable_answer_as_still_there():
    empty = ado_forge({"POST git/repositories/fx-ado/refs": {"count": 0, "value": []}})
    broken = ado_forge({}, raises={"POST git/repositories/fx-ado/refs": AzureDevOpsError(
        "POST git/repositories/fx-ado/refs → 403 Forbidden")})

    assert empty.delete_branch("req/0002-x") is False
    assert broken.delete_branch("req/0002-x") is False


def test_a_refused_delete_and_an_already_gone_branch_are_not_the_same_answer():
    """THE GITHUB HALF, AND ITS LIVE FINDING. `gh api -X DELETE .../git/refs/heads/<b>` exits 1 for
    a branch that does not exist (`422 Reference does not exist`, produced live against this very
    repository by deleting a name nobody has ever used) AND for one it will not touch (`403`).
    Reading the exit status alone makes every refusal look like a successful cleanup, and the
    sweep re-runs it hourly for ever with nothing to show. Re-reading the refs is the only
    evidence that settles which one happened."""
    already_gone = gh_forge({
        "-X DELETE": _Run(stderr="gh: Reference does not exist (HTTP 422)", returncode=1),
        "matching-refs": _Run(stdout="[]"),
    })
    protected = gh_forge({
        "-X DELETE": _Run(stderr="gh: Branch is protected (HTTP 403)", returncode=1),
        "matching-refs": _Run(stdout=json.dumps([{"ref": "refs/heads/req/0002-x"}])),
    })

    assert already_gone.delete_branch("req/0002-x") is True
    assert protected.delete_branch("req/0002-x") is False


def test_github_reports_a_delete_it_cannot_confirm_as_still_there():
    """Not knowing is not gone. A wrong True drops the branch out of the sweep's attention for
    good; a wrong False costs one more pass an hour later."""
    f = gh_forge({
        "-X DELETE": _Run(stderr="gh: Bad gateway (HTTP 502)", returncode=1),
        "matching-refs": _Run(stderr="gh: Bad gateway (HTTP 502)", returncode=1),
    })

    assert f.delete_branch("req/0002-x") is False


def test_github_takes_a_clean_delete_at_its_word():
    f = gh_forge({"-X DELETE": _Run(stdout="", returncode=0)})

    assert f.delete_branch("req/0002-x") is True


@pytest.mark.parametrize("build", [gh_forge, ado_forge])
def test_neither_adapter_deletes_an_unnamed_branch(build):
    """`delete_branch("")` composes `refs/heads/` — which on Azure DevOps is the PREFIX every head
    in the repository shares. Refused before any route is reached, which is why both fakes are
    routeless here: reaching one would raise."""
    assert build({}).delete_branch("  ") is False


# ── pr_for_head ─────────────────────────────────────────────────────────────────────────────────

def test_azure_asks_about_every_state_because_the_route_defaults_to_active():
    """RECORDED LIVE, AND THE ANSWER CHANGED THE SIGNATURE. `git/repositories/fx-ado/pullrequests`
    with `sourceRefName=refs/heads/probe/abandon` and NO status answered `count: 0`; the same call
    with `searchCriteria.status=all` answered three. The caller's question is "was this branch ever
    proposed", so the default would have said no about a branch proposed three times — and the
    product module would have opened a fourth."""
    f = ado_forge({"GET git/repositories/fx-ado/pullrequests": ADO_PRS_FOR_ABANDON})

    url = f.pr_for_head("probe/abandon")

    assert url == "https://dev.azure.com/acme-ai/factory/_git/fx-ado/pullrequest/7", \
        "the newest of the three, by the project-wide id"
    params = f.fake.params_for("GET", "git/repositories/fx-ado/pullrequests")
    assert params["searchCriteria.status"] == "all"
    assert params["searchCriteria.sourceRefName"] == "refs/heads/probe/abandon", (
        "a bare branch name answers count: 0 against the live API — verified")


def test_azure_separates_no_pull_request_from_an_unreadable_one():
    none = ado_forge({"GET git/repositories/fx-ado/pullrequests": {"count": 0, "value": []}})
    broken = ado_forge({}, raises={"GET git/repositories/fx-ado/pullrequests": AzureDevOpsError(
        "GET git/repositories/fx-ado/pullrequests → 401 Unauthorized")})

    assert none.pr_for_head("req/0007-x") == ""
    assert broken.pr_for_head("req/0007-x") is None


def test_azure_reports_a_pull_request_it_cannot_address_as_unreadable():
    """A PR row with no repository cannot be turned into a URL. Answering "" would say there is no
    pull request, and the caller opens a second one for work already proposed."""
    f = ado_forge({"GET git/repositories/fx-ado/pullrequests": {
        "count": 1, "value": [{"pullRequestId": 9, "repository": {}}]}})

    assert f.pr_for_head("req/0007-x") is None


def test_github_returns_the_newest_pull_request_rather_than_the_first_row():
    """A `req/*` branch really can carry several (three, live, on the Azure side). Ordering the
    rows here makes "the newest" a property of this method rather than of `gh pr list`'s default
    sort, which nothing in this repository pins."""
    rows = [{"url": "https://github.com/o/r/pull/4", "createdAt": "2026-08-01T10:00:00Z"},
            {"url": "https://github.com/o/r/pull/9", "createdAt": "2026-08-06T10:00:00Z"},
            {"url": "https://github.com/o/r/pull/6", "createdAt": "2026-08-03T10:00:00Z"}]
    f = gh_forge({"pr list": _Run(stdout=json.dumps(rows))})

    assert f.pr_for_head("req/0007-x") == "https://github.com/o/r/pull/9"
    argv = f._gh.argv_containing("pr list")  # noqa: SLF001
    assert "all" in argv, "a merged or closed proposal is still an answer of yes"


def test_github_separates_no_pull_request_from_an_unreadable_one():
    none = gh_forge({"pr list": _Run(stdout="[]")})
    broken = gh_forge({"pr list": _Run(stderr="gh: Not Found (HTTP 404)", returncode=1)})
    garbage = gh_forge({"pr list": _Run(stdout="<!DOCTYPE html>")})

    assert none.pr_for_head("req/0007-x") == ""
    assert broken.pr_for_head("req/0007-x") is None
    assert garbage.pr_for_head("req/0007-x") is None


@pytest.mark.parametrize("build,route,empty", [
    (gh_forge, "pr list", _Run(stdout="[]")),
    (ado_forge, "GET git/repositories/fx-ado/pullrequests", {"count": 0, "value": []}),
])
def test_both_vendors_spell_the_empty_answer_the_same_way(build, route, empty):
    """A provider is configuration only if the same fact reads the same from either vendor. `""`
    is falsy-but-known and `None` is falsy-but-unknown; a caller switching vendors must not have
    to learn a second dialect of "there is no pull request"."""
    assert build({route: empty}).pr_for_head("req/0007-x") == ""


@pytest.mark.parametrize("stdout", ['{"message": "Moved Permanently"}', "{}", "null", '"nope"'])
def test_github_reads_a_pull_request_answer_it_cannot_parse_as_unreadable(stdout):
    """ITERATING A JSON OBJECT YIELDS ITS KEYS, which is how this one hid. `{"message": …}`
    survives `json.loads`, filters down to no rows, and reads as `""` — "no pull request was ever
    opened from this branch", the single answer that sends the product module off to open a second
    one for work already in flight. `list_branches` guards the same shape two methods up in the
    same file; the guard was simply not carried across.

    THE EMPTY AND NULL CASES ARE THE ONES THAT PIN THE `isinstance` CHECK, and they are here
    because a mutation went green without them: `{}` and `null` are FALSY, so they never reach the
    row filter at all — they take the `no rows` exit and answer `""`. A guard that only the
    non-empty shapes exercise is a guard the empty ones walk straight past."""
    assert gh_forge({"pr list": _Run(stdout=stdout)}).pr_for_head("req/0007-x") is None


def test_github_reads_rows_it_cannot_parse_as_unreadable():
    """A non-empty answer we understood none of is not an empty answer."""
    assert gh_forge({"pr list": _Run(stdout='["not a row"]')}).pr_for_head("req/0007-x") is None


# ── the process itself failing is a failed READ, not an exception ───────────────────────────────

def _gh_that_never_answers(exc):
    def run(args, timeout=120):
        raise exc
    return run


@pytest.mark.parametrize("exc", [
    pytest.param(subprocess.TimeoutExpired(cmd="gh", timeout=120), id="gh hangs"),
    pytest.param(FileNotFoundError(2, "No such file or directory: 'gh'"), id="gh not installed"),
])
def test_github_folds_a_failed_process_into_the_ports_own_answers(exc):
    """`subprocess.run` DOES NOT ANSWER FOR EVERY FAILURE — it raises for two of them, and both
    escaped all three reads. The port forbids exactly that: `delete_branch` says NEVER RAISES
    because its caller is an hourly convergence sweep that must survive one bad hour, and both
    reads name None as the word for a failed read. An exception is a third answer nothing
    downstream is written for — the sweep dies part-way through, having deleted some branches and
    not others, and the next pass starts over."""
    f = gh_forge({})
    f._gh = _gh_that_never_answers(exc)  # noqa: SLF001

    assert f.list_branches("AcmeCorp/acme-docs", prefix="req/") is None
    assert f.delete_branch("req/0002-x") is False
    assert f.pr_for_head("req/0007-x") is None


def test_both_vendors_fail_in_the_same_vocabulary_when_the_transport_dies():
    """A provider is configuration only if a dead transport reads the same from either vendor.
    Azure's already did — its errors arrive as `AzureDevOpsError` — and this pins the pair."""
    gh = gh_forge({})
    gh._gh = _gh_that_never_answers(OSError("network is unreachable"))  # noqa: SLF001
    ado = ado_forge({}, raises={
        "GET git/repositories/fx-ado/refs": AzureDevOpsError("unreachable"),
        "POST git/repositories/fx-ado/refs": AzureDevOpsError("unreachable"),
        "GET git/repositories/fx-ado/pullrequests": AzureDevOpsError("unreachable"),
    })

    for f in (gh, ado):
        assert f.list_branches(prefix="req/") is None
        assert f.delete_branch("req/0002-x") is False
        assert f.pr_for_head("req/0007-x") is None


# ── the recorded fixtures are the server's own JSON ─────────────────────────────────────────────

def test_the_fixtures_are_shapes_the_live_api_really_emits():
    """A cheap tripwire: a fixture "tidied" into a shape the API never sends turns every test
    above into a proof about a fiction."""
    assert ADO_REFUSED["value"][0]["success"] is False, "a 200 OK that refused"
    assert ADO_ALREADY_GONE["value"][0]["updateStatus"] == "succeededNonExistentRef"
    assert [p["pullRequestId"] for p in ADO_PRS_FOR_ABANDON["value"]] == [7, 6, 4]
    assert isinstance(GH_MATCHING_REFS, list), "matching-refs answers an array even for one ref"
    assert all(r["name"].startswith("refs/heads/") for r in ADO_HEADS["value"])

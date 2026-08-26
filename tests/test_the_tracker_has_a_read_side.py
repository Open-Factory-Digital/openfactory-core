"""The tracker port can READ, and it can tell "nothing" from "I could not look" (#97).

EVERY FIXTURE HERE WAS RECORDED FROM A LIVE CALL on 2026-08-06, against the three deployments this
platform actually runs: `AcmeCorp/openfactory` on GitHub, `acme-team.atlassian.net`
project DAR on Jira, and `acme-ai/factory` on Azure Boards. They are trimmed — identity blobs
lose their avatar links — but no key here is invented. That rule is not ceremony: a suite once
validated `Ticket.state` against doubles that made the attribute up, and stayed green over a guard
that could never fire.

THE ONE RULE ALL OF THIS EXISTS FOR:

    None = I could not read.        [] = I read, and there is nothing.

Every assertion below is either that rule on a specific provider, or the vendor-shaped trap that
makes the rule hard to keep on that provider. The three traps were all found by CALLING, none by
reading documentation:

  * Jira's JQL accepts an ISO-8601 timestamp and matches NOTHING — 200, empty page, no error.
  * Jira's `search/jql` answers 200 and an empty page for a project key that does not exist.
  * Azure DevOps refuses a timestamped WIQL literal unless `timePrecision=true` is on the QUERY
    STRING; the same flag inside the request body, and the `$`-prefixed spelling, both 400.

The first two produce an empty board that reads as a fact. That is this codebase's most expensive
defect class, and both of them arrive through the front door of a correct-looking call.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.tracker.azure_devops import _LIST_CEILING, AzureBoardsTracker
from openfactory.adapters.tracker.base import (
    LIST_STATES,
    TicketComment,
    TicketSummary,
    TrackerAdapter,
    list_state,
)
from openfactory.adapters.tracker.github import GitHubIssuesTracker
from openfactory.adapters.tracker.jira import JiraTracker, _jql_since

# ── recorded shapes: GitHub ─────────────────────────────────────────────────────────────────────

#: `gh issue view 81 --json comments` — three comments, OLDEST FIRST (16:42 → 18:01 → 21:33), and
#: the author sub-object carries `login` and nothing else worth reading.
GH_COMMENTS = {"comments": [
    {"author": {"login": "alicecsp"}, "createdAt": "2026-08-05T16:42:16Z",
     "body": "## Implementado — 3 commits, 3760 testes verdes"},
    {"author": {"login": "openfactory-bot[bot]"}, "createdAt": "2026-08-05T18:01:50Z",
     "body": "🤖 tentei subir o índice para 1 — não resolveu"},
    {"author": {"login": "alicecsp"}, "createdAt": "2026-08-05T21:33:48Z",
     "body": "não é o índice, é o arredondamento"},
]}

#: `gh issue list --json number,title,body,state,stateReason,labels,assignees,updatedAt`.
#: **THE ENUMS ARRIVE SHOUTING** — `CLOSED`, `NOT_PLANNED` — which is the whole reason the adapter
#: folds them: `triage.Ticket.delivered` compares against the literal `not_planned`.
GH_ISSUES = [
    {"number": 92, "title": "telemetria", "body": "b", "state": "CLOSED",
     "stateReason": "COMPLETED", "labels": [{"name": "bug"}], "assignees": [],
     "updatedAt": "2026-08-06T13:57:19Z"},
    {"number": 96, "title": "duplicada de #93", "body": "b", "state": "CLOSED",
     "stateReason": "NOT_PLANNED", "labels": [], "assignees": [{"login": "alicecsp"}],
     "updatedAt": "2026-08-06T12:29:04Z"},
    {"number": 97, "title": "as portas não têm lado de leitura", "body": "b", "state": "OPEN",
     "stateReason": "", "labels": [], "assignees": [], "updatedAt": "2026-08-06T15:05:25Z"},
]

# ── recorded shapes: Jira ───────────────────────────────────────────────────────────────────────

#: `GET issue/DAR-1/comment` — oldest first, and unlike `search/jql` this endpoint DOES carry a
#: `total`, which is why the comment walk can compare and the board walk cannot.
JIRA_COMMENTS = {"startAt": 0, "maxResults": 100, "total": 2, "comments": [
    {"id": "10000", "created": "2026-08-05T09:07:17.543+0100",
     "author": {"displayName": "Alice Ferreira",
                "accountId": "712020:607081d5-b8cd-472d-9076-bc05245275fc"},
     "body": {"type": "doc", "version": 1, "content": [
         {"type": "paragraph", "content": [{"type": "text", "text": "a fábrica comentou aqui"}]}]}},
    {"id": "10001", "created": "2026-08-05T09:07:18.003+0100",
     "author": {"displayName": "Alice Ferreira",
                "accountId": "712020:607081d5-b8cd-472d-9076-bc05245275fc"},
     "body": {"type": "doc", "version": 1, "content": [
         {"type": "paragraph", "content": [{"type": "text", "text": "prova concluída"}]}]}},
]}


def _jira_issue(key: str, *, summary: str, category: str, status: str,
                updated: str) -> dict:
    """One `search/jql` row, in the shape the live endpoint returned. `statusCategory.key` is the
    vendor's own answer to "is this finished"; `status.name` is the client's label for it."""
    return {"id": "10071", "key": key, "fields": {
        "summary": summary, "labels": [], "assignee": None, "updated": updated,
        "status": {"name": status, "statusCategory": {"key": category}},
        "description": {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "corpo"}]}]}}}


#: The response shape that matters: `isLast` and `issues`, plus `nextPageToken` when there is more.
#: **THERE IS NO `total`.** Completeness is knowable only from `isLast`.
JIRA_PAGE_1 = {"isLast": False, "nextPageToken": "EAEY9_yrvf0zIiVwcm9qZWN0",
               "issues": [_jira_issue("DAR-3", summary="Cache-Control", category="indeterminate",
                                      status="Em análise",
                                      updated="2026-08-05T15:07:22.794+0100")]}
JIRA_PAGE_2 = {"isLast": True,
               "issues": [_jira_issue("DAR-1", summary="round-trip", category="done",
                                      status="Donee",
                                      updated="2026-08-05T09:10:19.214+0100")]}

# ── recorded shapes: Azure DevOps ───────────────────────────────────────────────────────────────

_ALICE = {"displayName": "Alice Ferreira", "uniqueName": "alice@acme.ai",
            "id": "68c6c232-27b3-68d8-8be2-990f177c7f4e"}

ADO_STATES = {"count": 5, "value": [
    {"name": "To Do", "category": "Proposed"}, {"name": "Doing", "category": "InProgress"},
    {"name": "Needs Action", "category": "InProgress"},
    {"name": "In review", "category": "Resolved"}, {"name": "Done", "category": "Completed"},
]}

#: A Scrum-shaped process — the one that HAS a Removed state, so `not_planned` can be read back.
ADO_SCRUM_STATES = {"count": 3, "value": [
    {"name": "New", "category": "Proposed"}, {"name": "Done", "category": "Completed"},
    {"name": "Removed", "category": "Removed"},
]}

#: `GET wit/workItems/12/comments?api-version=7.1-preview.4` — NEWEST FIRST as the service returns
#: it with no `order` (the opposite of GitHub and Jira), each comment carrying its own `format`, and
#: the platform's own 🤖 coming back as a numeric character reference because the sanitiser rewrote
#: it on the way in.
ADO_COMMENTS_DESC = {"totalCount": 3, "count": 3, "comments": [
    {"id": 4686377, "format": "markdown", "createdDate": "2026-08-06T11:27:50.503Z",
     "createdBy": _ALICE,
     "text": "&#129302; PR ready for review: a &lt;div&gt; renders"},
    {"id": 4686114, "format": "markdown", "createdDate": "2026-08-06T11:21:34.88Z",
     "createdBy": _ALICE, "text": "[on_hold] agent stopped"},
    {"id": 4680457, "format": "html", "createdDate": "2026-08-06T09:11:43.653Z",
     "createdBy": _ALICE, "text": "<div>escrito no navegador</div><h2>Nota</h2>"},
]}


def ado_comments(_body, params):
    """The comments route as the SERVICE behaves, not as a fixed recording — it honours `order` and
    `$top` the way the live endpoint does (measured: `order=asc` reverses the default, `$top=2`
    returns two plus a `continuationToken`).

    A stand-in that ignored the parameters would let the adapter send anything, or nothing, and
    still pass: the ordering assertions would all be re-reading one hardcoded list."""
    rows = list(ADO_COMMENTS_DESC["comments"])
    if str((params or {}).get("order", "desc")).lower() == "asc":
        rows.reverse()
    top = (params or {}).get("$top")
    page = rows[:int(top)] if top else rows
    out = {"totalCount": len(rows), "count": len(page), "comments": page}
    if top and len(page) < len(rows):
        out["continuationToken"] = "eyJ0b3AiOjJ9"
    return out

ADO_WIQL_THREE = {"queryType": "flat", "workItems": [{"id": 1}, {"id": 12}, {"id": 9}]}

ADO_BATCH_THREE = {"count": 3, "value": [
    {"id": 1, "fields": {"System.Id": 1, "System.WorkItemType": "Issue", "System.State": "Doing",
                         "System.Title": "probe: the ADO tracker adapter",
                         "System.Tags": "e2e; sdlc working", "System.AssignedTo": _ALICE,
                         "System.ChangedDate": "2026-08-06T15:19:27.093Z",
                         "System.Description": "## Objective\nA &amp; B, 5 &lt; 6"},
     "multilineFieldsFormat": {"System.Description": "markdown"}},
    {"id": 12, "fields": {"System.Id": 12, "System.WorkItemType": "Issue",
                          "System.State": "In review", "System.Title": "order_total",
                          "System.ChangedDate": "2026-08-06T11:27:51.75Z",
                          "System.Description": "<div>Intro</div><h2>Objective</h2>"},
     "multilineFieldsFormat": {"System.Description": "html"}},
    {"id": 9, "fields": {"System.Id": 9, "System.WorkItemType": "Issue", "System.State": "Done",
                         "System.Title": "entregue", "System.ChangedDate":
                             "2026-08-06T10:00:00.0Z"},
     "multilineFieldsFormat": {}},
]}


# ── the stand-ins ───────────────────────────────────────────────────────────────────────────────

class _Gh(GitHubIssuesTracker):
    """The real adapter with only `_gh` replaced, so `_locate`, the token plumbing and the ref
    handling stay the adapter's own. An unrecorded argv FAILS — an adapter reaching a command
    nobody recorded is reaching one nobody has seen answer."""

    def __init__(self, answers: dict, repo: str = "AcmeCorp/openfactory") -> None:
        super().__init__(repo)
        self._answers = answers
        self.argv: list[list[str]] = []

    def _gh(self, args, timeout: int = 60):  # noqa: ARG002 — the timeout is the adapter's business
        self.argv.append(list(args))
        answer = self._answers.get(args[0])
        if answer is None:
            raise AssertionError(f"the adapter ran `gh {' '.join(args)}`, which this test never "
                                 f"recorded")
        out, code, err = answer if isinstance(answer, tuple) else (answer, 0, "")
        return subprocess.CompletedProcess(
            args=args, returncode=code,
            stdout=out if isinstance(out, str) else json.dumps(out), stderr=err)

    def search_terms(self) -> list[str]:
        """The `--search` query of the last list, or [] when the adapter did not use search."""
        for args in reversed(self.argv):
            if args[0] == "issue" and "--search" in args:
                return args[args.index("--search") + 1].split()
        return []


class _Jira(JiraTracker):
    """The real adapter with only `_call` replaced."""

    def __init__(self, answers: dict, project_key: str = "DAR") -> None:
        super().__init__(site="https://acme-team.atlassian.net", project_key=project_key,
                         email="alice@acme.ai", token="t")
        self._answers = dict(answers)
        self.calls: list[tuple[str, str, dict | None]] = []

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.calls.append((method, path, payload))
        answer = self._answers.get((method, path))
        if answer is None:
            raise AssertionError(f"the adapter called {method} {path}, a route this test never "
                                 f"recorded — record it or stop calling it")
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, list):  # a page sequence
            return answer.pop(0) if answer else {"isLast": True, "issues": []}
        return answer

    def jql(self) -> str:
        return str((self.calls[0][2] or {}).get("jql", ""))


class _Ado(AzureDevOpsClient):
    """The real client with only `call` replaced, so `values()` and the constructor's validation
    stay the vendor's."""

    def __init__(self, routes: dict) -> None:
        super().__init__(organization="acme-ai", project="factory", token="pat")
        self.routes = routes
        self.calls: list[dict] = []

    def call(self, method, path, *, body=None, params=None, project_scoped=True,
             content_type="application/json", api_version=None):
        self.calls.append({"method": method.upper(), "path": path, "body": body,
                           "params": params or {}, "api_version": api_version})
        answer = self.routes.get((method.upper(), path))
        if answer is None:
            raise AssertionError(f"the adapter called {method.upper()} {path}, a route this test "
                                 f"never recorded — record it or stop calling it")
        if isinstance(answer, Exception):
            raise answer
        return answer(body, params) if callable(answer) else answer


def _ado_tracker(routes: dict | None = None, *, states=ADO_STATES, **kw) -> AzureBoardsTracker:
    base = {("GET", "wit/workitemtypes/Issue/states"): states}
    base.update(routes or {})
    client = _Ado(base)
    tracker = AzureBoardsTracker(organization="acme-ai", project="factory",
                                 client=client, **kw)
    tracker.recorded = client
    return tracker


# ── the port itself ─────────────────────────────────────────────────────────────────────────────

_ADAPTERS = {
    "github": lambda: _Gh({}),
    "jira": lambda: _Jira({}),
    "azure_devops": lambda: _ado_tracker(),
}


#: The vendor classes themselves, not the stand-ins above — the reachability check below has to
#: look at the class the registry builds, not at a test subclass that could satisfy it by accident.
_VENDOR_CLASSES = {"github": GitHubIssuesTracker, "jira": JiraTracker,
                   "azure_devops": AzureBoardsTracker}


@pytest.mark.parametrize("kind", sorted(_ADAPTERS))
def test_every_tracker_really_implements_the_read_side(kind):
    """`isinstance` against a runtime_checkable Protocol only checks that the NAME is there, and
    `GitHubIssuesTracker` INHERITS the Protocol — so it inherits its `...` bodies, which return
    None, which is this port's word for "I could not read". An adapter that forgot to implement
    `comments` would therefore satisfy `isinstance` AND answer the contract's most conservative
    value on every call, for ever, with nothing logged: a provider that has quietly stopped
    reading, wearing a green suite. So the check is that each name is defined in the vendor's own
    class, not merely reachable through it."""
    assert isinstance(_ADAPTERS[kind](), TrackerAdapter)
    for name in ("comments", "list_tickets"):
        assert name in vars(_VENDOR_CLASSES[kind]), (
            f"the {kind} tracker inherits {name} from the Protocol instead of implementing it — "
            f"it will answer None to every caller and look like a provider that cannot read")


@pytest.mark.parametrize("kind", sorted(_ADAPTERS))
def test_an_unknown_state_filter_is_the_callers_bug_and_says_so(kind):
    """The one place the read side raises. Widening `state='opne'` to "all" hands somebody asking
    for the open queue every closed card as well, and nothing anywhere makes that visible."""
    with pytest.raises(ValueError, match="all, open, closed"):
        _ADAPTERS[kind]().list_tickets(state="opne")


def test_the_state_vocabulary_is_the_ports_not_a_vendors():
    assert LIST_STATES == ("all", "open", "closed")
    assert list_state(" OPEN ") == "open", "the filter is not normalised, so casing decides"


# ── GitHub ──────────────────────────────────────────────────────────────────────────────────────

def test_github_comments_come_back_oldest_first_with_who_and_when():
    """`gh issue view --json comments` answers ascending (verified on #81: 16:42 → 18:01 → 21:33).
    The author and the timestamp are the whole point of the shape — the tech-lead's prompt says
    *"VERIFY these — a prior fix may be wrong"*, and a bare list of bodies cannot tell the
    platform's own earlier note from the instruction a person left afterwards."""
    tracker = _Gh({"issue": GH_COMMENTS})

    got = tracker.comments("#81")

    assert [c.created_at for c in got] == ["2026-08-05T16:42:16Z", "2026-08-05T18:01:50Z",
                                           "2026-08-05T21:33:48Z"]
    assert [c.author for c in got] == ["alicecsp", "openfactory-bot[bot]", "alicecsp"]
    assert all(isinstance(c, TicketComment) for c in got)


def test_a_limit_takes_the_LAST_comments_and_still_reads_forwards():
    """Most recent, because "has somebody already tried this?" is answered at the end of a thread.
    Still oldest-first, because the caller renders them into a prompt as a conversation and an
    argument read backwards is a different argument."""
    tracker = _Gh({"issue": GH_COMMENTS})

    got = tracker.comments("#81", limit=2)

    assert [c.created_at for c in got] == ["2026-08-05T18:01:50Z", "2026-08-05T21:33:48Z"]


def test_a_ticket_with_no_comments_is_EMPTY_and_a_failed_read_is_NONE():
    """The rule, on the method where breaking it costs most: both answers reach a model as the
    same silence, and the model resolves both as "nobody has looked at this"."""
    assert _Gh({"issue": {"comments": []}}).comments("#97") == []
    assert _Gh({"issue": ("", 1, "GraphQL: Could not resolve to an issue")}).comments("#99") is None


def test_a_two_hundred_without_the_comments_field_is_not_a_ticket_without_comments():
    """A shape this adapter does not recognise is an unread ticket, not a quiet one. `gh` changing
    a field name would otherwise silently empty every comment history on the platform."""
    assert _Gh({"issue": {"number": 81}}).comments("#81") is None
    assert _Gh({"issue": ("not json at all", 0, "")}).comments("#81") is None


def test_github_folds_its_shouting_enums_into_the_ports_vocabulary():
    """`CLOSED`/`NOT_PLANNED` on the wire (verified live). `triage.Ticket.delivered` compares
    against the literal `not_planned`, so an unfolded value makes a card closed as a duplicate read
    as delivered work — the eleven-duplicates incident, restaged."""
    rows = _Gh({"issue": GH_ISSUES}).list_tickets()

    by_ref = {t.ref: t for t in rows}
    assert by_ref["96"].state == "closed"
    assert by_ref["96"].state_reason == "not_planned"
    assert by_ref["92"].state_reason == "completed"
    assert by_ref["97"].state == "open" and by_ref["97"].state_reason == ""


def test_the_board_comes_back_newest_updated_first_whatever_route_ran():
    """A limit without a promised order is an arbitrary subset dressed as an answer. The plain `gh
    issue list` orders by CREATION (verified: #96 before #95, while their update times run the
    other way), so the order cannot be inherited from the route."""
    shuffled = [GH_ISSUES[1], GH_ISSUES[2], GH_ISSUES[0]]

    rows = _Gh({"issue": shuffled}).list_tickets()

    assert [t.ref for t in rows] == ["97", "92", "96"]


def test_the_search_api_is_only_paid_for_when_it_buys_something():
    """`--search sort:updated-desc` is the only way to order `gh issue list`, and it routes the
    read through GitHub's SEARCH — a narrower quota on the credential the poller and every job
    share, already exhausted once on this deployment (2026-07-27, and the first casualty was a real
    job). When nothing is being dropped there is nothing to buy: everything comes back and the sort
    happens here."""
    everything = _Gh({"issue": GH_ISSUES})
    everything.list_tickets()
    assert everything.search_terms() == [], "a full read paid the search quota for nothing"

    truncated = _Gh({"issue": GH_ISSUES})
    truncated.list_tickets(limit=5)
    assert "sort:updated-desc" in truncated.search_terms(), (
        "a truncated read did not order by update, so `limit` drops whichever cards GitHub felt "
        "like returning last")

    incremental = _Gh({"issue": GH_ISSUES})
    incremental.list_tickets(updated_since="2026-08-06T12:00:00Z")
    assert "updated:>=2026-08-06T12:00:00Z" in incremental.search_terms()


def test_an_unreadable_repository_is_NONE_and_never_an_empty_board():
    """`gh issue list` on a repo the token cannot see exits 1. Answering `[]` there is how "nothing
    is queued", "no findings" and "the open questions resolved themselves" have all been said about
    a board nobody managed to read."""
    assert _Gh({"issue": ("", 1, "Could not resolve to a Repository")}).list_tickets() is None
    assert _Gh({"issue": ("", 0, "")}).list_tickets() == [], "an empty repo must read as empty"


def test_a_github_board_of_an_UNRECOGNISED_SHAPE_is_unreadable_too():
    """The exit-code arm above was asserted and the two shape arms were not — while `comments`, one
    method up the same file, asserts both. A zero exit code is not an answer: `gh` prints an error
    object rather than an array when a route or a field name moves under it, and `json.loads` will
    happily hand back a dict. Either of those emptying the board is the same collapse as the
    unreadable repository, arriving through a shape instead of through a status."""
    assert _Gh({"issue": ("not json at all", 0, "")}).list_tickets() is None
    assert _Gh({"issue": {"message": "Not Found"}}).list_tickets() is None


# ── Jira ────────────────────────────────────────────────────────────────────────────────────────

def test_jira_never_puts_an_iso_timestamp_into_jql():
    """**THE FINDING.** `list_tickets` is handed back a watermark this adapter itself produced —
    Jira spells `updated` as `2026-08-05T15:07:22.794+0100` — and JQL does not accept that shape.
    It does not reject it either. Measured live, same project, same afternoon:

        updated >= "2026-08-05 11:00"      →  200, DAR-3, DAR-2
        updated >= "2026-08-05T11:00:00Z"  →  200, []
        updated >= "-3d"                   →  200, DAR-3, DAR-2, DAR-1

    An ISO stamp reaching the query means every incremental board read answers "nothing changed",
    for ever, with a clean 200 — and `product/board.py` serves that as a fact about the board."""
    for stamp in ("2026-08-05T15:07:22.794+0100", "2026-08-06T15:05:25Z", "2026-08-06T11:27:51.75Z"):
        got = _jql_since(stamp)
        assert got.startswith("-") and got.endswith("m"), (
            f"{stamp!r} became {got!r}; JQL reads anything ISO-shaped as matching nothing at all")
        assert "T" not in got and ":" not in got


def test_the_relative_window_is_rounded_OUTWARDS():
    """A window a minute too wide re-reads cards the caller merges by ref anyway. A window a minute
    too narrow silently drops the ticket somebody just touched, which is the one the caller is
    refreshing for."""
    from datetime import UTC, datetime, timedelta

    ten_and_a_half = datetime.now(UTC) - timedelta(minutes=10, seconds=30)

    assert _jql_since(ten_and_a_half.isoformat()) == "-11m"


def test_a_watermark_that_cannot_be_parsed_widens_the_read_instead_of_emptying_it():
    """The two branches are not comparable: passing it through matches nothing (silent, wrong, and
    permanent), dropping it reads the whole board (loud in the log, slower, right)."""
    assert _jql_since("last tuesday") == ""
    assert _jql_since("") == ""


def test_a_watermark_from_the_future_never_becomes_a_forward_window():
    """A worker whose clock ran ahead would otherwise emit `updated >= "5m"`, which JQL reads as a
    date in the FUTURE — every card excluded, quietly."""
    from datetime import UTC, datetime, timedelta

    assert _jql_since((datetime.now(UTC) + timedelta(hours=2)).isoformat()) == "-1m"


def test_jira_walks_pages_by_isLast_because_there_is_no_total():
    """`/rest/api/3/search` is GONE (410, verified live). Its replacement returns `isLast`,
    `issues` and — only when there is more — `nextPageToken`. **No `total`.** A walk that stopped
    on a short page would report a partial board as a whole one."""
    tracker = _Jira({("POST", "search/jql"): [dict(JIRA_PAGE_1), dict(JIRA_PAGE_2)]})

    rows = tracker.list_tickets()

    assert [t.ref for t in rows] == ["DAR-3", "DAR-1"]
    assert len([c for c in tracker.calls if c[1] == "search/jql"]) == 2
    assert tracker.calls[1][2]["nextPageToken"] == "EAEY9_yrvf0zIiVwcm9qZWN0"


def test_jira_reads_finished_from_the_CATEGORY_and_not_from_the_column_name():
    """This deployment's own Jira board spells its done column "Donee". Reading the NAME would cost
    a full agent pass on a delivered card every time somebody renames a column."""
    tracker = _Jira({("POST", "search/jql"): [dict(JIRA_PAGE_1), dict(JIRA_PAGE_2)]})

    rows = {t.ref: t for t in tracker.list_tickets()}

    assert rows["DAR-1"].state == "closed", "the status is named 'Donee'; the CATEGORY says done"
    assert rows["DAR-3"].state == "open"


def test_an_empty_jira_page_is_confirmed_before_it_is_BELIEVED():
    """**THE SECOND FINDING.** `search/jql` answers 200 with an empty page for a project key that
    does not exist — measured live: `project = "NOPE"` → `{"issues":[],"isLast":true}`. So one typo
    in a registry row, or a token that lost Browse Projects, arrives at the product role as *the
    board is empty*. The confirmation costs one request and only when the answer was empty; a board
    that returned issues has proved its own existence."""
    missing = _Jira({("POST", "search/jql"): {"isLast": True, "issues": []},
                     ("GET", "project/NOPE"): RuntimeError("404 no project with the key 'NOPE'")},
                    project_key="NOPE")
    assert missing.list_tickets() is None

    genuinely_empty = _Jira({("POST", "search/jql"): {"isLast": True, "issues": []},
                             ("GET", "project/DAR"): {"key": "DAR", "id": "10001"}})
    assert genuinely_empty.list_tickets() == []


def test_jira_asks_the_server_for_the_LAST_comments_rather_than_slicing_the_thread():
    """A ticket argued over for a month is the exact one the tech-lead asks about; pulling its whole
    history to keep four comments is a page of ADF per comment for nothing. `orderBy=-created`
    reverses the wire order, so the adapter reverses it back."""
    tracker = _Jira({("GET", "issue/DAR-1/comment?maxResults=2&orderBy=-created"): {
        "total": 2, "comments": list(reversed(JIRA_COMMENTS["comments"]))}})

    got = tracker.comments("DAR-1", limit=2)

    assert [c.created_at for c in got] == ["2026-08-05T09:07:17.543+0100",
                                           "2026-08-05T09:07:18.003+0100"]
    assert [c.body for c in got] == ["a fábrica comentou aqui", "prova concluída"]


def test_a_jira_comment_author_is_a_NAME_and_not_an_account_guid():
    """`assignees()` returns `accountId` because it gets written back; a comment author never does.
    The consumer is a model deciding whether a human already told it something, and
    `712020:607081d5-b8cd-472d-9076-bc05245275fc` tells it nothing."""
    tracker = _Jira({("GET", "issue/DAR-1/comment?startAt=0&maxResults=100"): JIRA_COMMENTS})

    assert [c.author for c in tracker.comments("DAR-1")] == ["Alice Ferreira", "Alice Ferreira"]


def test_an_unreadable_jira_thread_is_NONE():
    tracker = _Jira({("GET", "issue/DAR-9/comment?startAt=0&maxResults=100"):
                     RuntimeError("404 O item não existe")})

    assert tracker.comments("DAR-9") is None


def test_a_jira_ticket_NOBODY_HAS_COMMENTED_ON_reads_as_empty_and_not_as_unreadable():
    """The positive twin of the test above, and the one easy to leave out because its direction is
    the conservative one — the caller is merely told it could not look. It is still wrong, and it is
    wrong on the COMMON case: most tickets carry no comments, so a `None` here has the tech-lead
    saying *"the comment history is not available to me"* about the ordinary card, for ever. That is
    the platform answering worse with nothing to report, which is the failure shape this whole card
    was opened for. GitHub and Azure DevOps both assert this pair; Jira asserted only half."""
    tracker = _Jira({("GET", "issue/DAR-2/comment?startAt=0&maxResults=100"):
                     {"startAt": 0, "maxResults": 100, "total": 0, "comments": []}})

    assert tracker.comments("DAR-2") == []


def test_an_unreadable_jira_BOARD_is_NONE_and_never_an_empty_one():
    """**THE RULE THIS CARD EXISTS FOR, ON THE ONE BOARD READ THAT NEVER ASSERTED IT.** Jira's
    `_call` raises on every HTTPError, and the ordinary ones are not exotic: a rotated token is a
    401, a project that lost Browse Projects is a 403, a busy site is a 429. Each of those has to
    arrive as *I could not look*.

    The sibling case — an empty page from a project key that does not exist — was guarded, so the
    exotic path was covered while the plain one was not. Left unasserted, this arm could be
    "simplified" to `[]` and the whole suite would stay green while `product/board.py` was told the
    client's board is empty and said so out loud."""
    unreadable = _Jira({("POST", "search/jql"):
                        RuntimeError("jira POST search/jql failed: 401 Unauthorized")})

    assert unreadable.list_tickets() is None


# ── Azure DevOps ────────────────────────────────────────────────────────────────────────────────

def test_ado_comments_are_read_on_the_PREVIEW_api_version():
    """The pinned 7.1 answers 400 on this resource — *"The requested version 7.1 … is under
    preview. The -preview flag must be supplied"* — which would be a 400 on every comment read the
    platform ever does. The write side already knew; the read side is the same route."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments})

    tracker.comments("12")

    (call,) = [c for c in tracker.recorded.calls if c["path"].endswith("/comments")]
    assert call["api_version"] == "7.1-preview.4"


def test_ado_asks_for_an_ORDER_because_its_default_is_the_opposite_of_everyone_elses():
    """Measured on work item 1: no `order` gives `[4680928, 4680780, 4680525, 4680457]` — newest
    first, the reverse of GitHub and Jira. A port that inherited each vendor's default would hand
    its caller a thread that reads backwards on one provider in three."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments})

    tracker.comments("12")

    (call,) = [c for c in tracker.recorded.calls if c["path"].endswith("/comments")]
    assert call["params"].get("order") == "asc"


def test_a_limited_ado_read_asks_for_the_newest_N_and_hands_back_the_oldest_first():
    """`order=asc&$top=N` would give the OLDEST N — the wrong end of a thread whose last word is
    what the caller came for."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments})

    got = tracker.comments("12", limit=3)

    (call,) = [c for c in tracker.recorded.calls if c["path"].endswith("/comments")]
    assert call["params"] == {"order": "desc", "$top": 3}
    assert [c.created_at for c in got] == ["2026-08-06T09:11:43.653Z", "2026-08-06T11:21:34.88Z",
                                           "2026-08-06T11:27:50.503Z"]


def test_an_ado_comment_survives_the_sanitiser_on_the_way_back():
    """Azure Boards HTML-sanitises every long-text write, comments included. The platform's own
    `🤖` is stored as `&#129302;` and a `<div>` as `&lt;div&gt;` (both verified on work item 12), and
    a comment typed in the browser is stored as HTML. Raw, a thread reaches the model spelling its
    emoji as entities and its prose as tags."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments})

    got = tracker.comments("12")

    assert got[2].body == "🤖 PR ready for review: a <div> renders"
    assert got[0].body == "escrito no navegador\n## Nota", "the html comment was not converted"


def test_ado_comments_empty_versus_unreadable():
    assert _ado_tracker({("GET", "wit/workItems/2/comments"):
                         {"totalCount": 0, "count": 0, "comments": []}}).comments("2") == []
    assert _ado_tracker({("GET", "wit/workItems/99999/comments"):
                         AzureDevOpsError("404 TF401231: Work item 99999 does not exist.")
                         }).comments("99999") is None
    # a ref this vendor cannot even address — `work_item_id` raises before any request
    assert _ado_tracker().comments("CONT-412") is None


def test_an_ado_thread_of_an_UNRECOGNISED_SHAPE_is_unreadable_and_not_quiet():
    """The arm GitHub asserts in `test_a_two_hundred_without_the_comments_field…`, on the provider
    that had it in code and not in a test. A 200 whose shape this adapter does not recognise — the
    preview resource moving under the pinned version is exactly how that happens here — is a thread
    it did not manage to read, and `[]` would tell a model nobody has commented."""
    assert _ado_tracker({("GET", "wit/workItems/12/comments"):
                         {"totalCount": 3, "count": 3}}).comments("12") is None


def test_the_watermark_needs_timePrecision_ON_THE_QUERY_STRING():
    """**THE THIRD FINDING.** A WIQL literal carrying a time is refused by default — *"You cannot
    supply a time with the date when running a query using date precision"*. Measured live, same
    query three ways:

        body {"query": …, "timePrecision": true}  →  400
        ?$timePrecision=true                      →  400
        ?timePrecision=true                       →  200, the six items changed since 11:00

    The `$`-prefixed spelling sits next to `$top` and `$expand` and looks right. Without the flag
    every incremental board read on Azure DevOps is a 400."""
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})

    tracker.list_tickets(updated_since="2026-08-06T11:00:00Z")

    (wiql,) = [c for c in tracker.recorded.calls if c["path"] == "wit/wiql"]
    assert wiql["params"].get("timePrecision") == "true", (
        "without this the query is a 400 and the board reads as unreachable on every refresh")
    assert "$timePrecision" not in wiql["params"], "the $-prefixed spelling is the one that 400s"
    assert "'2026-08-06T11:00:00Z'" in wiql["body"]["query"]
    assert "timePrecision" not in (wiql["body"] or {}), "in the body it is ignored and 400s"


def test_no_watermark_means_no_flag_and_no_date_clause():
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})

    tracker.list_tickets()

    (wiql,) = [c for c in tracker.recorded.calls if c["path"] == "wit/wiql"]
    assert "ChangedDate] >=" not in wiql["body"]["query"]
    assert "timePrecision" not in wiql["params"]


def test_ado_reads_not_planned_from_the_REMOVED_CATEGORY():
    """`close_ticket(delivered=False)` writes the Removed state; this reads it back. The two halves
    have to agree, or a card the platform closed as NOT delivered comes back downstream reading as
    delivered work."""
    removed = {"count": 1, "value": [
        {"id": 8, "fields": {"System.Id": 8, "System.WorkItemType": "Issue",
                             "System.State": "Removed", "System.Title": "duplicada",
                             "System.ChangedDate": "2026-08-06T10:00:00Z"},
         "multilineFieldsFormat": {}}]}
    tracker = _ado_tracker({("POST", "wit/wiql"): {"workItems": [{"id": 8}]},
                            ("GET", "wit/workitems"): removed}, states=ADO_SCRUM_STATES)

    (card,) = tracker.list_tickets()

    assert card.state == "closed"
    assert card.state_reason == "not_planned"


def test_a_process_without_a_removed_state_still_answers_completed_not_blank():
    """The Basic process has no Removed state for an Issue (verified on the live board), so every
    closed card there is `completed`. Blank would read downstream as "the tracker does not say",
    which is a different claim."""
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})

    rows = {t.ref: t for t in tracker.list_tickets()}

    assert rows["9"].state == "closed" and rows["9"].state_reason == "completed"
    assert rows["1"].state == "open" and rows["1"].state_reason == ""


def test_a_closed_card_whose_state_vanished_is_still_COMPLETED_and_not_BLANK():
    """The defensive arm of `_closed_reason`, asserted rather than assumed — it is unreachable
    through `list_tickets` today (`_is_closed` only answers True for a state it just found in the
    process's own table, and refreshes that table before giving up), so nothing else can see it.

    It is kept, and it answers `"completed"`, because the two blanks are not the same claim: `""`
    means *the tracker does not say*, and downstream that is read as delivered anyway
    (`triage.Ticket.delivered` excludes `not_planned` by name rather than requiring `completed`, so
    a tracker that omits the reason does not silently stop announcing real deliveries). Reaching
    here means the state table changed under a running worker; the card is closed and there is no
    evidence it was cancelled, which is exactly what `"completed"` says."""
    tracker = _ado_tracker()

    assert tracker._closed_reason("Issue", "A State The Process Dropped") == "completed"
    assert tracker._closed_reason("Issue", "Done") == "completed"


def test_ado_keeps_the_querys_order_and_not_the_batchs():
    """WIQL is asked for `ORDER BY [System.ChangedDate] DESC`; the batch field read answers in
    whatever order it likes. Rebuilding from the id list is what keeps the port's promise."""
    scrambled = {"count": 3, "value": list(reversed(ADO_BATCH_THREE["value"]))}
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): scrambled})

    assert [t.ref for t in tracker.list_tickets()] == ["1", "12", "9"]


def test_the_ado_state_filter_is_applied_by_CATEGORY_after_the_read():
    """No WIQL predicate can express open-versus-closed without hardcoding the client's state
    names, which is the reading this module refuses everywhere else."""
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})
    assert [t.ref for t in tracker.list_tickets(state="open")] == ["1", "12"]

    again = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                          ("GET", "wit/workitems"): ADO_BATCH_THREE})
    assert [t.ref for t in again.list_tickets(state="closed")] == ["9"]


def test_a_LIMIT_is_spent_on_the_cards_that_SURVIVE_the_state_filter():
    """**FOUND LIVE, AND IT WAS ANSWERING WRONG.** Because open-versus-closed is decided after the
    field read, a WIQL `$top` equal to the caller's limit spends the limit on cards the filter then
    throws away. Driven against `acme-ai/factory` before the fix:

        list_tickets(state="closed", limit=3)  →  []      (the board holds FIVE closed cards)

    The three most recently changed work items were all open, the limit was gone, and `[]` is this
    port's word for *I read, and there is nothing*. So the codebase's signature collapse was
    arriving through a paging parameter — and data-dependently, which is how it survived a live
    drive: the same call is correct on any board whose newest cards happen to be closed.

    GitHub spends its limit on the filtered set (`--state` goes to the server, verified) and so does
    Jira (a `statusCategory` clause inside the JQL). A port whose product claim is that a provider
    is configuration cannot have the third one answer a different question."""
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})

    # the ids come back [1, 12, 9] = open, open, closed. One closed card is asked for, and the two
    # open ones in front of it must not be what the limit is spent on.
    assert [t.ref for t in tracker.list_tickets(state="closed", limit=1)] == ["9"]

    (wiql,) = [c for c in tracker.recorded.calls if c["path"] == "wit/wiql"]
    assert wiql["params"]["$top"] == _LIST_CEILING, (
        "the caller's limit reached the query, so it was spent before the filter ever ran")


def test_the_filtered_walk_STOPS_as_soon_as_the_limit_is_filled():
    """The other half of that fix. Scanning every card up to the ceiling to answer somebody who
    asked for five would trade a wrong answer for a slow one, and the batch read is chunked at the
    service's own 200-id cap — so "stops early" is measurable in requests, not in intent."""
    ids = list(range(1, 601))
    rows = [{"id": n, "fields": {"System.Id": n, "System.WorkItemType": "Issue",
                                 "System.State": "To Do", "System.Title": f"t{n}",
                                 "System.ChangedDate": "2026-08-06T10:00:00Z"},
             "multilineFieldsFormat": {}} for n in ids]

    def _batch(_body, params):
        wanted = set(str(params["ids"]).split(","))
        return {"count": len(wanted), "value": [r for r in rows if str(r["id"]) in wanted]}

    tracker = _ado_tracker({("POST", "wit/wiql"): {"workItems": [{"id": n} for n in ids]},
                            ("GET", "wit/workitems"): _batch})

    assert len(tracker.list_tickets(state="open", limit=5)) == 5
    assert len([c for c in tracker.recorded.calls if c["path"] == "wit/workitems"]) == 1, (
        "600 ids were read to answer a caller who asked for five")


def test_ado_body_and_tags_arrive_in_the_platforms_shapes():
    """`System.Tags` is ONE semicolon-separated string, the description is entity-escaped whatever
    format it declares, and a browser-authored one is HTML that `parse_ticket_body` cannot read."""
    tracker = _ado_tracker({("POST", "wit/wiql"): ADO_WIQL_THREE,
                            ("GET", "wit/workitems"): ADO_BATCH_THREE})

    rows = {t.ref: t for t in tracker.list_tickets()}

    assert rows["1"].labels == ["e2e", "sdlc working"]
    assert rows["1"].assignees == ["alice@acme.ai"]
    assert rows["1"].body == "## Objective\nA & B, 5 < 6"
    assert rows["12"].body == "Intro\n## Objective"


def test_a_batch_read_is_chunked_at_the_services_own_cap():
    """`GET wit/workitems?ids=…` is capped at 200 by the service, and a 201st is a 400, not a
    truncation — so a board bigger than that arrives in pieces or not at all."""
    ids = list(range(1, 251))
    rows = [{"id": n, "fields": {"System.Id": n, "System.WorkItemType": "Issue",
                                 "System.State": "To Do", "System.Title": f"t{n}",
                                 "System.ChangedDate": "2026-08-06T10:00:00Z"},
             "multilineFieldsFormat": {}} for n in ids]
    served = {"first": True}

    def _batch(_body, params):
        wanted = str(params["ids"]).split(",")
        assert len(wanted) <= 200, f"the adapter asked for {len(wanted)} ids in one call — a 400"
        served["first"] = False
        return {"count": len(wanted), "value": [r for r in rows if str(r["id"]) in set(wanted)]}

    tracker = _ado_tracker({("POST", "wit/wiql"): {"workItems": [{"id": n} for n in ids]},
                            ("GET", "wit/workitems"): _batch})

    assert len(tracker.list_tickets()) == 250
    assert len([c for c in tracker.recorded.calls if c["path"] == "wit/workitems"]) == 2


def test_an_unreadable_ado_board_is_NONE():
    tracker = _ado_tracker({("POST", "wit/wiql"):
                            AzureDevOpsError("404 TF200016: the project does not exist")})

    assert tracker.list_tickets() is None


# ── the conformance suite can see an offender ───────────────────────────────────────────────────

class _FaithfulTracker:
    """A tracker double that answers the REAL contract and invents no field. Everything it is asked
    about is absent, so every read is either `None` (could not look) or `[]` (nothing there) — the
    two answers the suite is checking apart."""

    def get_ticket(self, ref):
        raise RuntimeError("no such ticket")

    def set_state(self, ref, state, reason=None, *, needs_person=None): ...
    def comment(self, ref, body): ...
    def ticket_url(self, ref): return ""
    def budget(self): return "not_reported"
    def person(self, ref): return {"id": ref, "name": "", "email": ""}
    def assignees(self, ref): return []
    def set_assignees(self, ref, logins): ...
    def add_label(self, ref, label): ...
    def remove_label(self, ref, label): ...
    def create_ticket(self, *, title, body): return "1"
    def find_ticket(self, *, title): return None
    def update_body(self, ref, body): ...
    def close_ticket(self, ref, reason, *, delivered=True): ...
    def link_child(self, parent_ref, child_ref): ...
    def children_of(self, parent_ref): return []

    def comments(self, ref, *, limit=0):
        return None  # nothing here is readable, so nothing here may answer []

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        return [TicketSummary(ref="CONT-412")] if list_state(state) != "closed" else []


def test_a_faithful_tracker_is_conformant():
    from openfactory.conformance.adapters import check_tracker

    assert check_tracker(_FaithfulTracker()) == []


def test_a_tracker_that_answers_EMPTY_for_UNREADABLE_is_caught():
    """The rule this whole card exists for, as a stranger's adapter would break it — and the break
    is invisible without the suite: nothing raises, nothing logs, the platform answers worse."""
    from openfactory.conformance.adapters import check_tracker

    class _Collapses(_FaithfulTracker):
        def comments(self, ref, *, limit=0):
            return []  # "I could not read" spelled as "there is nothing"

    rules = {f.rule for f in check_tracker(_Collapses())}

    assert "tracker.unreadable-is-not-empty" in rules


def test_a_tracker_that_answers_comments_as_BARE_DICTS_is_caught():
    """`tracker.comments-are-typed` had NO DRIVER AT ALL. Every double in this file answers `None`
    or `[]` from `comments`, so the branch that judges the shape was never entered: the rule could
    neither fire nor be shown able to fire, and inverting its condition left the suite green. That
    is *built, tested, reached by nothing* — this codebase's most-repeated defect — living inside
    the suite written to catch it.

    The shape matters, not just the coverage. A bare `{"author": …, "body": …}` is the natural first
    thing a stranger's adapter returns, and it is what the port refuses: the caller is a model
    deciding whether a HUMAN already told it something, and a dict that loses `TicketComment`'s
    guarantees is a dict whose `author` may not be there at all."""
    from openfactory.conformance.adapters import check_tracker

    class _Bare(_FaithfulTracker):
        def comments(self, ref, *, limit=0):
            return [{"author": "alice", "body": "já tentei isso, não é o índice"}]

    assert "tracker.comments-are-typed" in {f.rule for f in check_tracker(_Bare())}


def test_a_tracker_with_int_refs_is_caught():
    from openfactory.conformance.adapters import check_tracker

    class _IntRefs(_FaithfulTracker):
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            return [TicketSummary.model_construct(ref=412)]  # the C-05 collapse

    assert "tracker.refs-are-strings" in {f.rule for f in check_tracker(_IntRefs())}


def test_a_tracker_that_widens_an_unknown_filter_is_caught():
    from openfactory.conformance.adapters import check_tracker

    class _Generous(_FaithfulTracker):
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            return []  # accepts anything, including 'opne'

    assert "tracker.refuses-an-unknown-filter" in {f.rule for f in check_tracker(_Generous())}


def test_a_tracker_that_raises_the_WRONG_exception_for_a_bad_filter_is_caught():
    """`ValueError` specifically, because the caller's own bug and the provider's failure are
    handled in different places: a `RuntimeError` here reads as "the tracker is down" and sends
    somebody to check a credential over a typo in their own call."""
    from openfactory.conformance.adapters import check_tracker

    class _WrongKind(_FaithfulTracker):
        def list_tickets(self, *, state="all", updated_since="", limit=0):
            raise RuntimeError("bad state")

    findings = {f.rule: f.detail for f in check_tracker(_WrongKind())}

    assert "tracker.refuses-an-unknown-filter" in findings
    assert "RuntimeError" in findings["tracker.refuses-an-unknown-filter"]


def test_a_tracker_whose_reads_RAISE_is_caught():
    from openfactory.conformance.adapters import check_tracker

    class _Explodes(_FaithfulTracker):
        def comments(self, ref, *, limit=0):
            raise RuntimeError("boom")

    assert "tracker.reads-degrade" in {f.rule for f in check_tracker(_Explodes())}


def test_a_half_implemented_tracker_is_caught_before_it_reaches_a_job():
    from openfactory.conformance.adapters import check_tracker

    class _WriteOnly:
        def comment(self, ref, body): ...

    findings = check_tracker(_WriteOnly())

    assert [f.rule for f in findings] == ["tracker.protocol"]
    assert "list_tickets" in findings[0].detail


def test_the_published_cli_door_runs_a_tracker():
    """The suite's claim is that a STRANGER can run it. `CHECKS` is the published surface and the
    CLI is the door; a check reachable only from our own tests is the house's signature defect."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    result = CliRunner().invoke(app, [
        "conformance-adapter", "tracker",
        "tests.test_the_tracker_has_a_read_side:_FaithfulTracker"])

    assert result.exit_code == 0, result.output
    assert "CONFORMANT" in result.output

"""Azure Boards as a tracker — the second vendor on the axis, held to the same contract as Jira.

EVERY FIXTURE BELOW WAS RECORDED FROM A LIVE CALL against `acme-ai/factory` (process
"Factory Basic", type Issue, states To Do → Doing → Needs Action → In review → Done) while the
adapter was being written. They are trimmed — the identity blobs lose their avatar links — but no
key here is invented, and the stand-in client is the REAL `AzureDevOpsClient` with only its one
request method replaced. A double that answers with a field the vendor does not send is how a suite
stays green over an adapter that cannot work; this file's rule is that an unrecorded route is an
error, not an empty answer.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker, description_text
from openfactory.adapters.tracker.base import TrackerAdapter
from openfactory.adapters.tracker.registry import build_tracker
from openfactory.contracts import JobState
from openfactory.contracts.project import Project, ProviderRef

# ── recorded shapes ─────────────────────────────────────────────────────────────────────────────

#: GET wit/workitemtypes/Issue/states — the vendor's own classification of the client's columns.
ISSUE_STATES = {"count": 5, "value": [
    {"name": "To Do", "color": "b2b2b2", "category": "Proposed"},
    {"name": "Doing", "color": "007acc", "category": "InProgress"},
    {"name": "Needs Action", "color": "ff7b00", "category": "InProgress"},
    {"name": "In review", "color": "b2b2b2", "category": "Resolved"},
    {"name": "Done", "color": "339933", "category": "Completed"},
]}

_ALICE = {"displayName": "Alice Ferreira", "id": "68c6c232-27b3-68d8-8be2-990f177c7f4e",
            "uniqueName": "alice@acme.ai",
            "descriptor": "aad.NjhjNmMyMzItMjdiMy03OGQ4LThiZTItOTkwZjE3N2M3ZjRl"}

#: GET wit/workitems/1 — a body the PLATFORM wrote, stored as markdown.
WORK_ITEM_MARKDOWN = {
    "id": 1, "rev": 11,
    "fields": {
        "System.AreaPath": "factory", "System.TeamProject": "factory",
        "System.WorkItemType": "Issue", "System.State": "Doing", "System.Reason": "Started",
        "System.AssignedTo": _ALICE, "System.CreatedBy": _ALICE, "System.ChangedBy": _ALICE,
        "System.CommentCount": 2, "System.Title": "probe: the ADO tracker adapter",
        "System.BoardColumn": "Doing", "System.BoardColumnDone": False,
        "System.Description": (
            "---\ndepends_on: []\nbase_branch: main\n---\n\n"
            "## Objective\nProve the Azure Boards tracker adapter against the live API.\n\n"
            "## Acceptance criteria\n"
            "- get_ticket parses the body through parse_ticket_body\n"
            "- Ticket.state comes from the state CATEGORY\n"),
        "System.Tags": "e2e; sdlc working",
    },
    "multilineFieldsFormat": {"System.Description": "markdown"},
    "url": "https://dev.azure.com/acme-ai/aaa124b6-22d7-41eb-99b4-528d5c9f95d8/_apis/wit/workItems/1",
}

#: GET wit/workitems/5 — a body a HUMAN wrote in the browser. Azure DevOps stores it as HTML, and
#: this exact string came back off the wire (note the trailing spaces and the escaped `&lt;tag&gt;`).
WORK_ITEM_HTML = {
    "id": 5, "rev": 3,
    "fields": {
        "System.TeamProject": "factory", "System.WorkItemType": "Issue",
        "System.State": "To Do", "System.CreatedBy": _ALICE,
        "System.Title": "probe: an O'Brien \"quoted\" title",
        "System.Description": (
            "<div>Some intro </div><h2>Objective </h2><div>Prove the HTML read path </div>"
            "<h2>Acceptance criteria </h2><ul><li>criteria survive HTML </li>"
            "<li>a &lt;tag&gt; is unescaped </li> </ul><div><br> </div><div>tail </div>"),
    },
    "multilineFieldsFormat": {"System.Description": "html"},
    "url": "https://dev.azure.com/acme-ai/aaa124b6-22d7-41eb-99b4-528d5c9f95d8/_apis/wit/workItems/5",
}

#: POST wit/wiql — a flat query answers with ids and nothing else, which is why find_ticket reads
#: the fields in a second call.
WIQL_ONE_HIT = {"queryType": "flat", "asOf": "2026-08-06T09:14:21.227Z", "workItems": [
    {"id": 5, "url": "https://dev.azure.com/acme-ai/_apis/wit/workItems/5"}]}

#: GET wit/workitems?ids=…&fields=… — the batch read behind that second call.
BATCH_TWO = {"count": 2, "value": [
    {"id": 1, "rev": 9, "fields": {"System.Id": 1, "System.State": "Doing",
                                   "System.WorkItemType": "Issue",
                                   "System.Title": "probe: the ADO tracker adapter"},
     "multilineFieldsFormat": {}},
    {"id": 5, "rev": 3, "fields": {"System.Id": 5, "System.State": "To Do",
                                   "System.WorkItemType": "Issue",
                                   "System.Title": "probe: an O'Brien \"quoted\" title"},
     "multilineFieldsFormat": {}},
]}

#: POST wit/workitems/$Issue — trimmed; the id is the only part a caller uses.
CREATED = {"id": 7, "rev": 1, "fields": {"System.Title": "child", "System.State": "To Do"},
           "multilineFieldsFormat": {"System.Description": "markdown"},
           "url": "https://dev.azure.com/acme-ai/aaa/_apis/wit/workItems/7"}

#: PATCH wit/workitems/1 — the write echoes the item back; the adapter reads nothing from it.
PATCHED = {"id": 1, "rev": 12, "fields": {"System.State": "Doing"}}

#: POST wit/workItems/1/comments under 7.1-preview.4 with ?format=markdown.
COMMENT_MADE = {"id": 4680457, "workItemId": 1, "version": 1, "text": "hello", "format": "markdown"}

#: GET wit/workitems/1?$expand=relations — the native hierarchy, as the live board returned it.
WITH_RELATIONS = dict(WORK_ITEM_MARKDOWN, relations=[
    {"rel": "System.LinkTypes.Hierarchy-Forward",
     "url": "https://dev.azure.com/acme-ai/aaa/_apis/wit/workItems/5", "attributes": {}},
    {"rel": "System.LinkTypes.Hierarchy-Forward",
     "url": "https://dev.azure.com/acme-ai/aaa/_apis/wit/workItems/7", "attributes": {}},
])

#: A variant of ISSUE_STATES, not a recording: the same shape on a board whose owner misspelled the
#: done column and named an in-progress one "Done". Reading a NAME gets both of these backwards.
TYPOED_STATES = {"count": 3, "value": [
    {"name": "Done", "color": "007acc", "category": "InProgress"},
    {"name": "Donee", "color": "339933", "category": "Completed"},
    {"name": "A Fazer", "color": "b2b2b2", "category": "Proposed"},
]}

#: A Scrum-shaped process: no Resolved category at all, and a real Removed state.
SCRUM_STATES = {"count": 5, "value": [
    {"name": "New", "category": "Proposed"}, {"name": "Approved", "category": "Proposed"},
    {"name": "Committed", "category": "InProgress"}, {"name": "Done", "category": "Completed"},
    {"name": "Removed", "category": "Removed"},
]}


# ── the stand-in ────────────────────────────────────────────────────────────────────────────────

class _Recorded(AzureDevOpsClient):
    """The real client with only `call` replaced, so `values()` and the constructor's validation
    stay the vendor's. An unrecorded route FAILS the test — an adapter reaching a route nobody
    recorded is reaching one nobody has seen answer."""

    def __init__(self, routes: dict, **kw):
        super().__init__(organization="acme-ai", project="factory", token="pat", **kw)
        self.routes = routes
        self.calls: list[dict] = []

    def call(self, method, path, *, body=None, params=None, project_scoped=True,
             content_type="application/json", api_version=None):
        self.calls.append({"method": method.upper(), "path": path, "body": body,
                           "params": params or {}, "content_type": content_type,
                           "api_version": api_version})
        answer = self.routes.get((method.upper(), path))
        if answer is None:
            raise AssertionError(f"the adapter called {method.upper()} {path}, a route this test "
                                 f"never recorded — record it or stop calling it")
        if isinstance(answer, Exception):
            raise answer
        return answer(body, params) if callable(answer) else answer

    def writes(self) -> list[dict]:
        return [c for c in self.calls if c["method"] in ("PATCH", "POST", "PUT")]


def _tracker(routes: dict | None = None, **kw) -> AzureBoardsTracker:
    base = {("GET", "wit/workitemtypes/Issue/states"): ISSUE_STATES}
    base.update(routes or {})
    client = _Recorded(base)
    tracker = AzureBoardsTracker(organization="acme-ai", project="factory",
                                 client=client, **kw)
    tracker.recorded = client  # the test reads the requests back off it
    return tracker


def _project(**options):
    return Project(name="factory", repo_path="/t",
                   tracker=ProviderRef(kind="azure_devops", repo="factory", options=options),
                   forge=ProviderRef(kind="github", repo="a/b"))


# ── reachability: the registry row is the only way in ───────────────────────────────────────────

def test_the_registry_builds_this_tracker_and_it_satisfies_the_port():
    """The signature defect of this codebase is code written, tested and reached by nothing. An
    adapter behind no registry row is exactly that, and `isinstance` is what catches a half
    implementation — the board protocol's own implementation failed this check once."""
    tracker = build_tracker(_project(organization="acme-ai", project="factory"))
    assert isinstance(tracker, AzureBoardsTracker)
    assert isinstance(tracker, TrackerAdapter)


def test_the_registry_row_carries_the_coordinates_and_the_state_map():
    """Wiring, not behaviour: a `state_map` configured and read by nothing is this house's
    signature defect wearing a different hat — the Jira `status_map` shipped that way."""
    tracker = build_tracker(_project(
        organization="https://dev.azure.com/acme-ai", project="factory",
        work_item_type="User Story",
        state_map='{"in_progress": "Fazendo", "needs_action": "Precisa de Ação"}'))
    assert tracker.ado.organization == "acme-ai"  # a pasted URL is still a coordinate
    assert tracker.ado.project == "factory"
    assert tracker.work_item_type == "User Story"
    assert tracker.state_map["needs_action"] == "Precisa de Ação"


def test_the_project_NAMES_its_credential_and_the_environment_holds_it(monkeypatch):
    """The registry names the variable, the environment holds the value — so a token cannot reach a
    manifest, a log or a proof file. A `token_env` nothing reads is a deployment authenticating
    with nothing and reading a bare 401."""
    monkeypatch.setenv("ADO_PAT_FOR_THIS_CLIENT", "the-secret")
    tracker = build_tracker(_project(organization="acme-ai", project="factory",
                                     token_env="ADO_PAT_FOR_THIS_CLIENT"))
    assert tracker.ado.token == "the-secret"


def test_a_malformed_state_map_is_logged_and_never_crashes_the_build(caplog):
    """A typo in one option must not take the deployment down — but it must not be silent either,
    because the symptom is cards that quietly stop moving."""
    with caplog.at_level(logging.ERROR, logger="openfactory.tracker"):
        tracker = build_tracker(_project(organization="o", project="p", state_map="{not json"))
    assert tracker.state_map == {}
    assert "state_map" in caplog.text


def test_nothing_outside_the_registry_names_this_class():
    """The seam's whole claim: adding Azure DevOps is one row plus one module, not a sweep through
    the composition root. This is the same guard the GitHub and Jira classes carry."""
    allowed = {"openfactory/adapters/tracker/registry.py", "openfactory/adapters/tracker/azure_devops.py"}
    stray, scanned = set(), 0
    for path in Path("openfactory").rglob("*.py"):
        scanned += 1
        if str(path) in allowed:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if ((isinstance(node, ast.ImportFrom)
                 and any(a.name == "AzureBoardsTracker" for a in node.names))
                    or (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "AzureBoardsTracker")):
                stray.add(str(path))
    assert scanned > 80, f"scanned only {scanned} files — run from the repo root"
    assert not stray, f"these construct the ADO tracker by name: {sorted(stray)}"


def test_the_lifecycle_table_is_the_contracts_not_a_copy():
    """One bucketing for every vendor, and one reading of it. The adapter imported the table by
    identity; it calls the contract's resolver now, so the `needs_person` distinction (#166) is
    not something each vendor could answer differently."""
    import inspect

    from openfactory.adapters.tracker import azure_devops
    from openfactory.adapters.tracker.base import column_key

    assert azure_devops._column_key is column_key
    # PROSE STRIPPED FIRST: the paragraph explaining this rule names the very symbol
    # it forbids, which is how a guard comes to fail on its own explanation.
    from conftest import code_only

    assert "STATE_KEYS" not in code_only(inspect.getsource(azure_devops))


# ── reading a ticket ────────────────────────────────────────────────────────────────────────────

def test_a_ticket_the_platform_wrote_parses_into_the_contract():
    """`Ticket` is the PARSED contract, not `{id,title,body}` — the Jira adapter shipped a version
    that built it directly and every job would have died on its first step."""
    tracker = _tracker({("GET", "wit/workitems/1"): WORK_ITEM_MARKDOWN})
    ticket = tracker.get_ticket("#1")

    assert ticket.id == "1"
    assert ticket.objective == "Prove the Azure Boards tracker adapter against the live API."
    assert [c.text for c in ticket.acceptance_criteria] == [
        "get_ticket parses the body through parse_ticket_body",
        "Ticket.state comes from the state CATEGORY"]
    assert ticket.base_branch == "main"          # the front matter survived
    assert ticket.labels == ["e2e", "sdlc working"]
    assert ticket.author == "alice@acme.ai"  # uniqueName, the half that can be written back


def test_a_human_written_html_description_still_carries_its_criteria():
    """Azure DevOps stores a description as HTML by default, and `parse_ticket_body` reads markdown.
    Unconverted, EVERY ticket a person writes in the browser parses as one with no objective and no
    acceptance criteria — and the platform then tells its author the ticket says nothing."""
    tracker = _tracker({("GET", "wit/workitems/5"): WORK_ITEM_HTML})
    ticket = tracker.get_ticket("5")

    assert ticket.objective == "Prove the HTML read path"
    assert [c.text for c in ticket.acceptance_criteria] == [
        "criteria survive HTML", "a <tag> is unescaped"]


@pytest.mark.parametrize("html,expected", [
    ("<div>## Objective </div><div>typed as markdown </div>", "## Objective\ntyped as markdown"),
    ("<h2>Objective</h2><div>styled with the toolbar</div>", "## Objective\nstyled with the toolbar"),
    ("<div>a&nbsp;b</div>", "a b"),
    ("plain text with no tags at all", "plain text with no tags at all"),
])
def test_both_ways_a_person_writes_a_heading_survive(html, expected):
    """Somebody who types `## Objective` and somebody who uses the toolbar's Heading 2 must both
    end up with a heading. The second was the one that would have been lost."""
    assert description_text(html, "html") == expected


def test_a_markdown_description_is_never_run_through_the_html_reader():
    """`multilineFieldsFormat` is the vendor saying which it stored. A markdown body put through an
    HTML parser loses whatever looks like a tag."""
    body = "## Objective\nkeep <this> exactly\n"
    assert description_text(body, "markdown") == body


# ── the sanitiser runs whatever the format says ─────────────────────────────────────────────────

#: The body a splitter child carries — LLM prose about code, which is where the angle brackets in a
#: real ticket come from.
BODY_WITH_ANGLES = ("## Objective\nRender a List<String> & a <placeholder>.\n\n"
                    "## Acceptance criteria\n- the <div> renders\n- a & b\n")

#: RECORDED, by writing `BODY_WITH_ANGLES` unescaped to acme-ai/factory #9 and reading it
#: back. `multilineFieldsFormat` said `markdown` on both the write and the read. This is the DEFECT:
#: `List<String>` lost its type argument, `<placeholder>` was deleted whole, and `&` became an
#: entity. `<div>` survived only because it happens to be a tag the sanitiser knows.
STORED_UNESCAPED = ("## Objective\nRender a List &amp; a .\n\n"
                    "## Acceptance criteria\n- the <div> renders\n- a &amp; b\n")

#: RECORDED from the same item, written through the adapter. Byte-identical after `html.unescape`.
STORED_ESCAPED = ("## Objective\nRender a List&lt;String&gt; &amp; a &lt;placeholder&gt;.\n\n"
                  "## Acceptance criteria\n- the &lt;div&gt; renders\n- a &amp; b\n")

#: RECORDED from POST wit/workItems/9/comments — an escaped comment is stored verbatim.
COMMENT_STORED = ("pre-flight: List&lt;String&gt; &amp; a &lt;placeholder&gt;; if (a&lt;b) { x }"
                  "  -- tail must survive\nsecond line")


def test_what_the_platform_writes_comes_back_as_what_it_wrote():
    """Saying `markdown` changes how the field RENDERS, not that it is sanitised. Live, a body
    written raw comes back mutilated — so it goes in escaped and comes out unescaped, and the round
    trip has to be the identity or the platform is editing its own tickets."""
    written = _tracker({("PATCH", "wit/workitems/1"): PATCHED})
    written.update_body("1", BODY_WITH_ANGLES)
    (write,) = written.recorded.writes()
    sent = next(op["value"] for op in write["body"]
                if op["path"] == "/fields/System.Description")
    assert sent == STORED_ESCAPED, "the body reached the sanitiser unescaped"

    read = _tracker({("GET", "wit/workitems/1"): dict(
        WORK_ITEM_MARKDOWN,
        fields=dict(WORK_ITEM_MARKDOWN["fields"], **{"System.Description": STORED_ESCAPED}))})
    ticket = read.get_ticket("1")
    assert ticket.objective == "Render a List<String> & a <placeholder>."
    assert [c.text for c in ticket.acceptance_criteria] == ["the <div> renders", "a & b"]


def test_the_body_the_sanitiser_ate_is_what_this_escape_exists_for():
    """The positive twin, and the reason the assertion above cannot be deleted as fussiness: this is
    the RECORDED answer to the same write sent raw. A child's criteria come back naming a type that
    has no argument and a `<placeholder>` that is not there — and an unterminated `<` eats the rest
    of the field outright, so the sizing gate then tells the ticket's author it says nothing."""
    lost = description_text(STORED_UNESCAPED, "markdown")
    assert "List<String>" not in lost and "<placeholder>" not in lost
    assert description_text(STORED_ESCAPED, "markdown") == BODY_WITH_ANGLES


def test_a_created_ticket_is_escaped_too_and_not_only_an_edited_one():
    """Both writers of this field, because covering one is how the other stays broken: the splitter
    CREATES its children and the product role EDITS them."""
    tracker = _tracker({("POST", "wit/workitems/$Issue"): CREATED})
    tracker.create_ticket(title="child", body=BODY_WITH_ANGLES)
    (write,) = tracker.recorded.writes()
    assert {"op": "add", "path": "/fields/System.Description",
            "value": STORED_ESCAPED} in write["body"]


def test_a_comment_is_escaped_before_the_same_sanitiser_cuts_it():
    """The comment route sanitises identically — recorded live, `List<String> & a <placeholder>;
    if (a<b) …` is STORED as `List &amp; a ; if (a`. What this method carries is the platform's
    whole voice to a person: the park explanation, the sizing reasons, and the one sentence that
    says a card was closed WITHOUT being delivered."""
    tracker = _tracker({("POST", "wit/workItems/1/comments"): COMMENT_MADE})
    tracker.comment("1", "pre-flight: List<String> & a <placeholder>; if (a<b) { x }"
                         "  -- tail must survive\nsecond line")
    (posted,) = tracker.recorded.writes()
    assert posted["body"]["text"] == COMMENT_STORED


# ── the state is the CATEGORY ───────────────────────────────────────────────────────────────────

def test_state_comes_from_the_category_and_never_from_the_name():
    """This deployment has seen a done column typo'd "Donee". A tracker that reads the NAME calls a
    delivered card open — and the platform re-runs it, burning a full agent pass and parking the
    single job slot. Here the same board also has an IN-PROGRESS state literally called "Done"."""
    routes = {("GET", "wit/workitemtypes/Issue/states"): TYPOED_STATES,
              ("GET", "wit/workitems/1"): dict(
                  WORK_ITEM_MARKDOWN,
                  fields=dict(WORK_ITEM_MARKDOWN["fields"], **{"System.State": "Donee"})),
              ("GET", "wit/workitems/2"): dict(
                  WORK_ITEM_MARKDOWN,
                  fields=dict(WORK_ITEM_MARKDOWN["fields"], **{"System.State": "Done"}))}
    tracker = _tracker(routes)

    assert tracker.get_ticket("1").state == "closed", "the misspelled Completed state read as open"
    assert tracker.get_ticket("2").state == "open", "a state NAMED Done read as delivered work"


def test_a_removed_card_is_closed_too():
    """`Removed` is the vendor's word for a cancelled card. Closed, and closed without delivery."""
    tracker = _tracker({("GET", "wit/workitemtypes/Issue/states"): SCRUM_STATES,
                        ("GET", "wit/workitems/1"): dict(
                            WORK_ITEM_MARKDOWN,
                            fields=dict(WORK_ITEM_MARKDOWN["fields"],
                                        **{"System.State": "Removed"}))})
    assert tracker.get_ticket("1").state == "closed"


def test_a_state_the_process_does_not_declare_reads_as_open_and_SAYS_SO(caplog):
    """"I could not tell" must never look like an answer. Open is the recoverable side — a card
    read as closed is one the factory ignores for ever — but it is only safe because it is loud."""
    item = dict(WORK_ITEM_MARKDOWN,
                fields=dict(WORK_ITEM_MARKDOWN["fields"], **{"System.State": "Em Análise"}))
    tracker = _tracker({("GET", "wit/workitems/1"): item})
    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.azure_devops"):
        assert tracker.get_ticket("1").state == "open"
    assert "Em Análise" in caplog.text


# ── moving a card ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state,expected", [
    (JobState.TODO, "To Do"),
    (JobState.IMPLEMENTING, "Doing"),
    (JobState.REVIEWING, "In review"),
    (JobState.DONE, "Done"),
    (JobState.BLOCKED, "Needs Action"),
])
def test_an_unconfigured_deployment_still_moves_the_card_to_the_right_column(state, expected):
    """Jira needs a `status_map` before it can move anything, because Jira only exposes status
    names. Azure DevOps publishes each state's CATEGORY, so the client's own column names are
    honoured with no configuration at all — the exact board this was proven against."""
    tracker = _tracker({("PATCH", "wit/workitems/1"): PATCHED})
    tracker.set_state("1", state)

    (write,) = tracker.recorded.writes()
    assert write["body"] == [{"op": "add", "path": "/fields/System.State", "value": expected}]
    assert write["content_type"] == "application/json-patch+json", (
        "Azure DevOps refuses a work item write that is not JSON Patch")


def test_the_configured_map_beats_the_derived_one():
    """A client whose board has two InProgress columns pins the ambiguous one; nothing else should
    have to change."""
    tracker = _tracker({("PATCH", "wit/workitems/1"): PATCHED},
                       state_map={"in_progress": "Needs Action"})
    tracker.set_state("1", JobState.IMPLEMENTING)
    assert tracker.recorded.writes()[0]["body"][0]["value"] == "Needs Action"


def test_nothing_is_invented_when_no_state_answers(caplog):
    """A Scrum-shaped process has no Resolved category. An invented state name is a 400 at best and
    a card moved somewhere nobody watches at worst — so it is a no-op that says why."""
    tracker = _tracker({("GET", "wit/workitemtypes/Issue/states"): SCRUM_STATES})
    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.azure_devops"):
        tracker.set_state("1", JobState.REVIEWING)

    assert tracker.recorded.writes() == [], "it guessed a state this process does not have"
    assert "state_map" in caplog.text, "the warning does not say what to configure"


def test_the_reason_still_lands_when_the_card_could_not_be_moved():
    """The positive twin of the no-op: a caller's explanation dropped because the move failed is the
    silent half of a failure, and the park it explains is the one a human is meant to act on."""
    tracker = _tracker({("GET", "wit/workitemtypes/Issue/states"): SCRUM_STATES,
                        ("POST", "wit/workItems/1/comments"): COMMENT_MADE})
    tracker.set_state("1", JobState.REVIEWING, reason="the reviewer asked for a rebase")

    (comment,) = tracker.recorded.writes()
    assert "the reviewer asked for a rebase" in comment["body"]["text"]


def test_a_refused_write_raises_instead_of_reporting_success():
    """`None` is this port's only way of saying "it landed". An adapter that swallowed the refusal
    would have the platform announce a card was moved while it sits where it was."""
    tracker = _tracker({("PATCH", "wit/workitems/1"):
                        AzureDevOpsError("PATCH wit/workitems/1 → 400 Bad Request")})
    with pytest.raises(AzureDevOpsError):
        tracker.set_state("1", JobState.IMPLEMENTING)


# ── comments ────────────────────────────────────────────────────────────────────────────────────

def test_a_comment_goes_to_the_preview_api_version_and_as_markdown():
    """Recorded live: the pinned 7.1 answers *"The requested version 7.1 of the resource is under
    preview"* on this route — a 400 on every comment the platform would ever post. And the default
    html format renders a multi-line park explanation as one run-on line."""
    tracker = _tracker({("POST", "wit/workItems/1/comments"): COMMENT_MADE})
    tracker.comment("#1", "line one\nline two")

    (posted,) = tracker.recorded.writes()
    assert posted["api_version"] == "7.1-preview.4"
    assert posted["params"]["format"] == "markdown"
    assert posted["body"] == {"text": "line one\nline two"}


# ── tags ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,expected", [
    ("🤖 sdlc-working", "sdlc-working"),
    ("🤖sdlc-working", "sdlc-working"),
    ("needs review", "needs review"),   # a space is legal here, unlike Jira
    ("a;b", "a b"),                     # `;` separates tags, so one label would become two
    ("🤖", "openfactory"),
])
def test_a_tag_loses_only_what_azure_devops_refuses(label, expected):
    """Verified one character at a time against the live board: Azure DevOps accepts `✓ done` and
    `→ next` but answers TF401407 for anything outside the BMP, so the platform's own marker
    `🤖 sdlc-working` is rejected whole. This is the exact inverse of Jira, which takes the emoji
    and rejects the space — which is why the sanitiser belongs to the adapter, not to the caller."""
    assert AzureBoardsTracker.ado_tag(label) == expected


def test_adding_a_tag_is_one_union_write_and_not_a_read_merge_write():
    """`add` on System.Tags unions with what is there — proved live. A read-merge-write would drop
    whatever a person added in the browser between the read and the write, and we would have
    introduced that race for nothing."""
    tracker = _tracker({("PATCH", "wit/workitems/1"): PATCHED})
    tracker.add_label("1", "🤖 sdlc-working")

    assert [c["method"] for c in tracker.recorded.calls] == ["PATCH"], "it read before writing"
    assert tracker.recorded.writes()[0]["body"] == [
        {"op": "add", "path": "/fields/System.Tags", "value": "sdlc-working"}]


def test_removing_a_tag_writes_the_remainder_back():
    """There is no remove op for System.Tags, so removal is read-modify-`replace`."""
    tracker = _tracker({("GET", "wit/workitems/1"): WORK_ITEM_MARKDOWN,
                        ("PATCH", "wit/workitems/1"): PATCHED})
    tracker.remove_label("1", "e2e")

    assert tracker.recorded.writes()[0]["body"] == [
        {"op": "replace", "path": "/fields/System.Tags", "value": "sdlc working"}]


def test_removing_a_tag_the_card_does_not_carry_writes_nothing():
    """A no-op by contract — and a `replace` here would rewrite the whole tag string for nothing."""
    tracker = _tracker({("GET", "wit/workitems/1"): WORK_ITEM_MARKDOWN})
    tracker.remove_label("1", "never-was-here")
    assert tracker.recorded.writes() == []


# ── assignees ───────────────────────────────────────────────────────────────────────────────────

def test_the_assignee_is_read_as_the_address_that_can_be_written_back():
    """Azure DevOps answers an identity object. `displayName` cannot be written back;
    `uniqueName` can, and it is the value a park hands the ticket back to."""
    tracker = _tracker({("GET", "wit/workitems/1"): WORK_ITEM_MARKDOWN})
    assert tracker.assignees("1") == ["alice@acme.ai"]


def test_an_unassigned_card_answers_with_nobody():
    tracker = _tracker({("GET", "wit/workitems/5"): WORK_ITEM_HTML})
    assert tracker.assignees("5") == []


def test_clearing_the_assignees_unassigns_rather_than_leaving_the_bot_on_the_card():
    tracker = _tracker({("PATCH", "wit/workitems/1"): PATCHED})
    tracker.set_assignees("1", [])
    assert tracker.recorded.writes()[0]["body"] == [
        {"op": "add", "path": "/fields/System.AssignedTo", "value": ""}]


# ── creating and finding ────────────────────────────────────────────────────────────────────────

def test_a_created_work_item_stores_its_body_as_markdown():
    """The bodies this platform writes are markdown. Stored as html — the default — a person reads
    `## Objective` as literal text on the card."""
    tracker = _tracker({("POST", "wit/workitems/$Issue"): CREATED})
    assert tracker.create_ticket(title="child", body="## Objective\nx") == "7"

    (write,) = tracker.recorded.writes()
    assert {"op": "add", "path": "/multilineFieldsFormat/System.Description",
            "value": "markdown"} in write["body"]


def test_a_create_that_answered_without_an_id_is_a_failure_not_a_ref():
    """A card nobody can address is a card the splitter files again on the next pass."""
    tracker = _tracker({("POST", "wit/workitems/$Issue"): {"rev": 1, "fields": {}}})
    with pytest.raises(AzureDevOpsError, match="no id"):
        tracker.create_ticket(title="child", body="x")


def test_find_ticket_escapes_the_title_before_it_reaches_the_query():
    """WIQL is SQL-shaped. Unescaped, `an O'Brien "quoted" title` answers *400 Expecting closing
    quote* — verified live — and the splitter's one guard against filing a duplicate is the thing
    that fails."""
    tracker = _tracker({("POST", "wit/wiql"): WIQL_ONE_HIT,
                        ("GET", "wit/workitems"): BATCH_TWO})
    assert tracker.find_ticket(title="probe: an O'Brien \"quoted\" title") == "5"

    query = tracker.recorded.calls[0]["body"]["query"]
    assert "O''Brien" in query, f"an unescaped quote reached the query: {query}"


def test_find_ticket_ignores_a_card_that_is_already_closed():
    """It answers with an OPEN ticket. A closed one reused as the splitter's child would attach new
    work to a delivered card."""
    closed_batch = {"count": 1, "value": [
        {"id": 5, "fields": {"System.Id": 5, "System.State": "Done",
                             "System.WorkItemType": "Issue",
                             "System.Title": "probe: an O'Brien \"quoted\" title"}}]}
    tracker = _tracker({("POST", "wit/wiql"): WIQL_ONE_HIT,
                        ("GET", "wit/workitems"): closed_batch})
    assert tracker.find_ticket(title="probe: an O'Brien \"quoted\" title") is None


def test_find_ticket_compares_the_title_exactly_after_the_case_insensitive_query():
    """WIQL's `=` is case-insensitive, so the query is the net and the comparison is the decision."""
    tracker = _tracker({("POST", "wit/wiql"): WIQL_ONE_HIT,
                        ("GET", "wit/workitems"): BATCH_TWO})
    assert tracker.find_ticket(title="PROBE: AN O'BRIEN \"QUOTED\" TITLE") is None


def test_a_lookup_that_could_not_be_performed_raises_instead_of_answering_None():
    """"I could not ask" and "there is none" are different answers, and this is the gate in front of
    a create — so returning the second for the first files the duplicate it exists to prevent."""
    tracker = _tracker({("POST", "wit/wiql"):
                        AzureDevOpsError("POST wit/wiql → 503 Service Unavailable")})
    with pytest.raises(AzureDevOpsError):
        tracker.find_ticket(title="anything")


def test_no_hit_is_a_real_None_with_no_second_call():
    tracker = _tracker({("POST", "wit/wiql"): {"queryType": "flat", "workItems": []}})
    assert tracker.find_ticket(title="nothing has this title") is None


# ── closing ─────────────────────────────────────────────────────────────────────────────────────

def test_a_card_closed_as_not_delivered_lands_in_Removed_when_the_process_has_one():
    """CLOSED IS NOT DELIVERED. Azure DevOps says the difference with the Removed category."""
    tracker = _tracker({("GET", "wit/workitemtypes/Issue/states"): SCRUM_STATES,
                        ("POST", "wit/workItems/1/comments"): COMMENT_MADE,
                        ("PATCH", "wit/workitems/1"): PATCHED})
    tracker.close_ticket("1", "duplicate of #4", delivered=False)

    patch = [c for c in tracker.recorded.writes() if c["method"] == "PATCH"][0]
    assert patch["body"] == [{"op": "add", "path": "/fields/System.State", "value": "Removed"}]


def test_when_the_process_cannot_say_not_delivered_the_comment_does():
    """The Basic process has no Removed state for an Issue — verified live. The card can only show
    Done, so the sentence a person reads has to carry the difference: eleven cards closed as
    duplicates coming back downstream as delivered work is the incident behind this rule."""
    tracker = _tracker({("POST", "wit/workItems/1/comments"): COMMENT_MADE,
                        ("PATCH", "wit/workitems/1"): PATCHED})
    tracker.close_ticket("1", "duplicate of #4", delivered=False)

    comment = [c for c in tracker.recorded.writes() if c["method"] == "POST"][0]
    assert "duplicate of #4" in comment["body"]["text"]
    assert "not delivered" in comment["body"]["text"].lower()


def test_the_not_delivered_sentence_survives_a_reason_with_an_angle_bracket():
    """RECORDED: posted raw, `duplicate: the a<b guard was wrong` + the NOT-delivered sentence is
    STORED by Azure DevOps as `duplicate: the a` — an unterminated `<` in the CALLER's own reason
    deletes the sentence saying the work did not happen, on a card the board now shows as Done.
    Eleven cards closed as duplicates reading downstream as delivered work is the incident that
    sentence exists for, and the vendor's sanitiser was quietly reproducing it."""
    tracker = _tracker({("POST", "wit/workItems/1/comments"): COMMENT_MADE,
                        ("PATCH", "wit/workitems/1"): PATCHED})
    tracker.close_ticket("1", "duplicate: the a<b guard was wrong", delivered=False)

    text = [c for c in tracker.recorded.writes() if c["method"] == "POST"][0]["body"]["text"]
    assert "NOT delivered" in text, "the sanitiser would have eaten the sentence that matters"
    assert "a&lt;b" in text, "the `<` reached the sanitiser and took the rest of the comment"


def test_a_delivered_close_says_nothing_extra():
    """Every existing caller closes because the work IS done; their message must arrive unchanged."""
    tracker = _tracker({("POST", "wit/workItems/1/comments"): COMMENT_MADE,
                        ("PATCH", "wit/workitems/1"): PATCHED})
    tracker.close_ticket("1", "shipped in #12")

    comment = [c for c in tracker.recorded.writes() if c["method"] == "POST"][0]
    assert comment["body"]["text"] == "shipped in #12"


def test_a_process_with_no_closing_state_refuses_rather_than_reporting_a_close():
    """A caller announces this act to a human — "fechei o #511" — and has no second signal to
    consult."""
    tracker = _tracker({("GET", "wit/workitemtypes/Issue/states"):
                        {"count": 1, "value": [{"name": "Open", "category": "Proposed"}]}})
    with pytest.raises(AzureDevOpsError, match="state_map"):
        tracker.close_ticket("1", "done")


# ── refs and links ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref", ["1", "#1", " 1 ", 1])
def test_a_ref_arrives_in_several_shapes_and_means_the_same_work_item(ref):
    assert AzureBoardsTracker.work_item_id(ref) == "1"


@pytest.mark.parametrize("ref", ["CONT-412", "", "abc", None])
def test_a_ref_that_is_not_a_number_is_refused_with_a_sentence(ref):
    """The raw API answers *"The controller for path … was not found"*, which reads as a routing bug
    in the platform rather than as a bad ref."""
    with pytest.raises(AzureDevOpsError, match="work item ref"):
        AzureBoardsTracker.work_item_id(ref)


def test_the_url_is_the_page_a_person_opens():
    """The API's own `_links.html.href` addresses the project by GUID; a human needs the name."""
    tracker = _tracker()
    assert tracker.ticket_url("#1") == \
        "https://dev.azure.com/acme-ai/factory/_workitems/edit/1"


def test_children_come_back_as_refs_this_platform_can_use():
    """Hierarchy-Forward is "my children"; the relation carries a URL and the ref is its last
    segment."""
    tracker = _tracker({("GET", "wit/workitems/1"): WITH_RELATIONS})
    assert tracker.children_of("1") == ["5", "7"]


def test_a_child_listing_that_failed_falls_back_instead_of_claiming_there_are_none(caplog):
    """The one place this port lets empty mean "cannot say" — safe only because the caller's
    fallback (`find_ticket` by title) tells the two apart, and only if it is logged."""
    tracker = _tracker({("GET", "wit/workitems/1"): AzureDevOpsError("403 Forbidden")})
    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.azure_devops"):
        assert tracker.children_of("1") == []
    assert "children" in caplog.text


def test_linking_a_child_points_at_the_parent_and_never_takes_the_split_down(caplog):
    tracker = _tracker({("GET", "wit/workitems/1"): WORK_ITEM_MARKDOWN,
                        ("PATCH", "wit/workitems/7"): CREATED})
    tracker.link_child("1", "7")

    (write,) = tracker.recorded.writes()
    assert write["body"][0]["value"]["rel"] == "System.LinkTypes.Hierarchy-Reverse"
    assert write["body"][0]["value"]["url"].endswith("/workItems/1")

    refusing = _tracker({("GET", "wit/workitems/1"): AzureDevOpsError("400 link not allowed")})
    with caplog.at_level(logging.INFO, logger="openfactory.tracker.azure_devops"):
        refusing.link_child("1", "7")  # best-effort by contract: the split holds through titles
    assert "still holds through titles" in caplog.text

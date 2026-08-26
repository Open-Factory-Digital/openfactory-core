"""An Azure Boards board IS the pickup queue — the fourth axis a second vendor had to reach.

Every payload below was recorded from `acme-ai/factory` on 2026-08-06, and the tests that
matter most here are the ones a fake could never have suggested:

  * `System.BoardColumn` is READ-ONLY (`400 TF401326`), so the move is a STATE change
  * the board routes take a TEAM segment and `wit/workitems` refuses one (`404 The controller for
    path … was not found`), so the reads and the writes are scoped differently
  * WIQL answers `[]` for a column name that does not exist, so a one-character typo in the pickup
    column is a factory standing still and reporting a quiet day

No network: the shared client is replaced by a recorder, and what the tests assert is the request
this adapter SENDS plus what it makes of the response Azure DevOps really returned.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.board.azure_devops import AzureBoardsBoard
from openfactory.adapters.board.base import BoardAdapter
from openfactory.contracts import JobState
from openfactory.contracts.project import Project, ProviderRef

# ── recorded live, 2026-08-06, acme-ai/factory ──────────────────────────────────────────────────

#: GET _apis/projects/factory — this is where the team comes from instead of a guess.
PROJECT = {"id": "aaa124b6-22d7-41eb-99b4-528d5c9f95d8", "name": "factory",
           "state": "wellFormed",
           "defaultTeam": {"id": "c3b2085d-5f18-48f7-b36c-ec6c0b2d8d13",
                           "name": "factory Team"}}

#: GET {project}/{team}/_apis/work/boards — lowest backlog level first.
BOARDS = {"count": 2, "value": [{"id": "a7d8ffb5", "name": "Issues"},
                                {"id": "cada9f00", "name": "Epics"}]}

#: GET {project}/{team}/_apis/work/boards/Issues/columns
COLUMNS = {"count": 5, "value": [
    {"id": "fc60d33c", "name": "To Do", "itemLimit": 0,
     "stateMappings": {"Issue": "To Do"}, "columnType": "incoming"},
    {"id": "5f16ddd5", "name": "Doing", "itemLimit": 0, "isSplit": False, "description": "",
     "stateMappings": {"Issue": "Doing"}, "columnType": "inProgress"},
    {"id": "d733fd21", "name": "Needs Action", "itemLimit": 0, "isSplit": False,
     "description": "Stopped and waiting on a person",
     "stateMappings": {"Issue": "Needs Action"}, "columnType": "inProgress"},
    {"id": "f7debdc0", "name": "In review", "itemLimit": 0, "isSplit": False,
     "description": "PR open through prod approval",
     "stateMappings": {"Issue": "In review"}, "columnType": "inProgress"},
    {"id": "3f2291c3", "name": "Done", "itemLimit": 0,
     "stateMappings": {"Issue": "Done"}, "columnType": "outgoing"},
]}

#: GET {project}/{team}/_apis/work/teamsettings/teamfieldvalues
TEAM_FIELDS = {"field": {"referenceName": "System.AreaPath"}, "defaultValue": "factory",
               "values": [{"value": "factory", "includeChildren": False}]}


def _wiql(*ids):
    """A POST wit/wiql response — the real shape, trimmed to what this adapter reads."""
    return {"queryType": "flat", "queryResultType": "workItem",
            "asOf": "2026-08-06T09:11:36.8Z",
            "columns": [{"referenceName": "System.Id", "name": "ID"}],
            "workItems": [{"id": i,
                           "url": f"https://dev.azure.com/acme-ai/_apis/wit/workItems/{i}"}
                          for i in ids]}


def _card(number, kind="Issue", state="To Do"):
    """GET {project}/_apis/wit/workitems/{id}?fields=System.WorkItemType,System.State"""
    return {"id": number, "rev": 2,
            "fields": {"System.WorkItemType": kind, "System.State": state},
            "url": f"https://dev.azure.com/acme-ai/_apis/wit/workItems/{number}"}


# ── the recorder that replaces the shared client ────────────────────────────────────────────────

class _Call:
    def __init__(self, method, path, scope, body, params, project_scoped, content_type):
        self.method, self.path, self.scope = method, path, scope
        self.body, self.params = body, params
        self.project_scoped, self.content_type = project_scoped, content_type

    @property
    def query(self) -> str:
        return str((self.body or {}).get("query", "")) if isinstance(self.body, dict) else ""

    def __repr__(self):  # pragma: no cover — only ever read from a failing assertion
        return f"<{self.method} {self.scope}/_apis/{self.path}>"


class _World:
    """One fake Azure DevOps, recording every request and its SCOPE.

    Deliberately not a WIQL engine: it looks the query's column name up in a dict a test wrote,
    so nothing here can invent server behaviour the real API does not have. What the tests assert
    is the request this adapter sends and what it makes of a response ADO really returned."""

    def __init__(self, *, columns=COLUMNS, boards=BOARDS, project=PROJECT, fields=TEAM_FIELDS,
                 by_column=None, everything=(), cards=None, fail=(), patch=None,
                 areas_of=None):
        self.calls: list[_Call] = []
        self.columns, self.boards, self.project, self.fields = columns, boards, project, fields
        self.by_column = by_column or {}
        self.areas_of = areas_of or {}
        self.everything = everything
        self.cards = cards or {}
        self.fail = dict(fail)
        self.patch = patch

    def client(self, *, organization, project, token=None, options=None):
        world = self

        class _Client:
            def __init__(self):
                self.organization, self.project, self.token = organization, project, token

            def call(self, method, path, *, body=None, params=None, project_scoped=True,
                     content_type="application/json", api_version=None):
                return world._answer(_Call(method.upper(), path, project, body, params,
                                           project_scoped, content_type))

            def values(self, p, **kw):
                got = self.call("GET", p, **kw)
                out = got.get("value")
                return out if isinstance(out, list) else []

        return _Client()

    def _answer(self, call: _Call):
        self.calls.append(call)
        for marker, message in self.fail.items():
            if marker in call.path:
                raise AzureDevOpsError(message)
        if call.path.startswith("projects/"):
            return self.project
        if call.path == "work/boards":
            return self.boards
        if call.path.endswith("/columns"):
            return self.columns
        if call.path == "work/teamsettings/teamfieldvalues":
            return self.fields
        if call.path == "wit/wiql":
            for name, ids in self.by_column.items():
                if f"'{name}'" in call.query:
                    return _wiql(*ids)
            return _wiql(*self.everything)
        if call.path == "wit/workitems":
            # THE BATCH ROUTE `_qualify` READS AREA PATHS THROUGH. Absent from this recorder, the
            # qualification silently degraded to bare refs — and the property test written to prove
            # "the board accepts what it mints" then proved it about `'3'`, the one shape that
            # never had the bug. Found by mutating the fix and watching that test stay green.
            ids = [i for i in str((call.params or {}).get("ids", "")).split(",") if i]
            return {"count": len(ids),
                    "value": [{"id": int(i),
                               "fields": {"System.Id": int(i),
                                          "System.AreaPath": self.areas_of.get(i, "")}}
                              for i in ids]}
        if call.path.startswith("wit/workitems/"):
            number = int(call.path.rsplit("/", 1)[-1])
            if call.method == "PATCH":
                return self.patch or _card(number)
            if number not in self.cards:
                raise AzureDevOpsError(
                    f"GET {call.path} → 404 Not Found: TF401232: Work item {number} does not "
                    f"exist, or you do not have permissions to read it.")
            return self.cards[number]
        raise AssertionError(f"the adapter called a route this recorder does not know: {call!r}")

    # -- readers a test asserts with ----------------------------------------------------------
    def sent(self, method, marker) -> list[_Call]:
        return [c for c in self.calls if c.method == method and marker in c.path]


@pytest.fixture
def world(monkeypatch):
    def _make(**kw):
        w = _World(**kw)
        monkeypatch.setattr("openfactory.adapters.board.azure_devops.AzureDevOpsClient", w.client)
        return w
    return _make


def _board(**kw):
    kw.setdefault("organization", "acme-ai")
    kw.setdefault("project", "factory")
    return AzureBoardsBoard(**kw)


# ── the capability is REACHED, not merely written ───────────────────────────────────────────────

def test_the_registry_actually_builds_this_board():
    """THE guard this codebase needs most: ~19 capabilities have been written, tested and called
    by nothing. A board nobody can construct from a project is a file, not a provider."""
    from openfactory.adapters.board import BOARD_KINDS, build_board

    project = Project(name="fx-ado", repo_path="/tmp",
                      tracker=ProviderRef(kind="azure_devops", repo="fx-ado",
                                          options={"organization": "acme-ai",
                                                   "project": "factory"}),
                      forge=ProviderRef(kind="github", repo="a/b"))

    board = build_board(project)

    assert isinstance(board, AzureBoardsBoard)
    assert isinstance(board, BoardAdapter), "the vendor-agnostic claim rests on this seam"
    assert "azure_devops" in BOARD_KINDS


def test_the_registry_passes_the_clients_OWN_column_names_all_the_way_to_the_request(world):
    """C-14, end to end — registry row, adapter, request. `options` is `dict[str, str]` by
    contract, so the map travels as JSON, and a registry that never passed it in is exactly how
    the Jira `status_map` feature was found to be unreachable: implemented, tested, dead."""
    import json

    from openfactory.adapters.board import build_board

    w = world(columns={"value": [{"name": "A Fazer", "stateMappings": {"Issue": "A Fazer"}},
                                 {"name": "Concluído", "stateMappings": {"Issue": "Concluído"}}]},
              cards={3: _card(3, state="A Fazer")})
    project = Project(name="fx-ado", repo_path="/tmp",
                      tracker=ProviderRef(kind="azure_devops", repo="fx-ado",
                                          options={"organization": "acme-ai",
                                                   "project": "factory", "board": "Issues",
                                                   "columns": json.dumps({"todo": "A Fazer",
                                                                          "done": "Concluído"})}),
                      forge=ProviderRef(kind="github", repo="a/b"))

    assert build_board(project).set_status(issue="3", issue_url="", state=JobState.DONE) is True

    assert w.sent("PATCH", "wit/workitems/3")[0].body[0]["value"] == "Concluído"


def test_the_board_reads_the_SAME_COORDINATES_the_tracker_registry_does():
    """ONE REGISTRY ROW CONFIGURES BOTH AXES, so both must read it the same way.

    `tracker/registry.py:_azure_devops` accepts `org` as an alias for `organization` and falls
    back to `tracker.repo` for the ADO project. The board read only the long spellings, so a row
    written the way the tracker registry documents produced a working tracker and a board whose
    constructor raised `ValueError` — out of `scan_todo`, which does not catch it
    (`runtime/temporal/activities.py`): a poller tick with a stack trace where the queue goes.

    And the crash is the SECOND-worst outcome. Two axes reading the same row into different
    coordinates would have the board reporting on a project the tracker never writes to."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker

    project = Project(name="fx-ado", repo_path="/tmp",
                      tracker=ProviderRef(kind="azure_devops", repo="factory",
                                          options={"org": "acme-ai"}),
                      forge=ProviderRef(kind="github", repo="a/b"))

    board, tracker = build_board(project), build_tracker(project)

    assert (board.organization, board.project) == ("acme-ai", "factory")
    assert (board.organization, board.project) == (tracker.organization, tracker.project), (
        "the board and the tracker resolved one registry row to different ADO projects")


def test_a_columns_map_that_will_not_parse_is_LOUD_and_falls_back(caplog):
    from openfactory.adapters.board import build_board

    project = Project(name="fx-ado", repo_path="/tmp",
                      tracker=ProviderRef(kind="azure_devops", repo="fx-ado",
                                          options={"organization": "acme-ai",
                                                   "project": "factory",
                                                   "columns": "todo: A Fazer"}),
                      forge=ProviderRef(kind="github", repo="a/b"))

    with caplog.at_level("ERROR"):
        board = build_board(project)

    assert board._names["todo"] == "To Do"
    assert "not a JSON object" in caplog.text


def test_nothing_outside_the_factory_names_this_vendors_board():
    """The same rule the GitHub board is held to: a caller that constructs a vendor board by name
    is a caller a second deployment has to edit."""
    allowed = {"openfactory/adapters/board/factory.py", "openfactory/adapters/board/azure_devops.py"}
    stray = set()
    for path in Path("openfactory").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Call)
                     and getattr(node.func, "id", "") == "AzureBoardsBoard")
            imported = (isinstance(node, ast.ImportFrom)
                        and any(a.name == "AzureBoardsBoard" for a in node.names))
            if named or imported:
                stray.add(str(path))
    assert not stray - allowed, f"these name the ADO board directly: {sorted(stray - allowed)}"


def test_missing_coordinates_fail_when_the_BOARD_IS_BUILT_not_mid_job():
    """A board that resolves to something unusable is a poller tick that logs a stack trace where
    a queue should be. Azure DevOps nests organization/project, so both are structural."""
    with pytest.raises(ValueError, match="organization and a project"):
        AzureBoardsBoard(organization="", project="factory")
    with pytest.raises(ValueError, match="organization and a project"):
        AzureBoardsBoard(organization="acme-ai", project="  ")


# ── the routes, exactly as the live API accepts them ────────────────────────────────────────────

def test_the_board_reads_are_TEAM_scoped_and_the_work_item_writes_are_NOT(world):
    """The route split that only a live call reveals. `work/…` and `wit/wiql` take a team segment;
    every other `wit/…` route answers *404 The controller for path
    '/factory/factory Team/_apis/wit/workitems/3' was not found* under one. Written from
    the documentation, this adapter would have scoped them all the same way and half of it would
    have 404'd on a board that was there all along."""
    w = world(by_column={"To Do": [3]}, cards={3: _card(3)})
    board = _board(board="Issues")

    board.items_in_status("To Do")
    board.set_column(issue="3", issue_url="", name="Doing")

    team_scoped = {"work/boards/Issues/columns", "work/teamsettings/teamfieldvalues", "wit/wiql"}
    seen = {c.path for c in w.calls}
    assert team_scoped <= seen and "wit/workitems/3" in seen, f"the split was never exercised: {seen}"
    for call in w.calls:
        if call.path in team_scoped:
            assert call.scope == "factory/factory Team", f"{call!r} lost its team"
        elif call.path.startswith("wit/workitems"):
            assert call.scope == "factory", f"{call!r} carries a team the route rejects"


def test_the_team_is_ASKED_FOR_not_guessed_from_the_naming_convention(world):
    """A wrong team is a 404 that reads exactly like a missing board, so the default team is read
    off the project rather than assembled from `"<project> Team"`."""
    w = world(by_column={"To Do": [3]})

    _board().items_in_status("To Do")

    assert w.sent("GET", "projects/factory"), "nothing asked ADO which team owns this project"
    assert any(c.scope == "factory/factory Team" for c in w.calls)


def test_when_the_project_cannot_be_read_the_convention_is_used_AND_SAID(world, caplog):
    """Degrading is allowed; degrading silently is not — the warning is what lets somebody connect
    a 404 on every board route to a guessed team name."""
    w = world(by_column={"To Do": [3]}, fail={"projects/": "GET projects/x → 403 Forbidden"})

    with caplog.at_level("WARNING"):
        _board().items_in_status("To Do")

    assert any(c.scope == "factory/factory Team" for c in w.calls)
    assert "naming convention" in caplog.text and "declare `team`" in caplog.text


def test_a_declared_team_is_never_second_guessed(world):
    w = world(by_column={"To Do": []})

    _board(team="Platform Team").items_in_status("To Do")

    assert not w.sent("GET", "projects/"), "a declared team must cost no discovery call"
    assert all(c.scope in ("factory", "factory/Platform Team") for c in w.calls)


def test_the_default_board_is_the_lowest_backlog_level(world, caplog):
    """`work/boards` lists a team's boards lowest level first — `['Issues', 'Epics']` here — and
    the lowest is where day-to-day cards live. Logged, because a default nobody sees is a default
    nobody corrects."""
    world(by_column={"To Do": [3]})

    with caplog.at_level("INFO"):
        _board().items_in_status("To Do")

    assert "'Issues'" in caplog.text and "Declare `board`" in caplog.text


# ── unreadable is never empty ───────────────────────────────────────────────────────────────────

def test_an_unreadable_board_answers_None_and_not_an_empty_one(world):
    """The port's hardest rule. Three separate bugs in this codebase came from collapsing these:
    an unreadable board became *"nothing is queued"*."""
    world(fail={"columns": "GET work/boards/Issues/columns → 401 Unauthorized"})
    board = _board(board="Issues")

    assert board.columns() is None
    assert board.column_names() is None


def test_one_unreadable_COLUMN_makes_the_whole_board_unreadable(world, caplog):
    """A partial board is worse than an admitted failure: it reports the cards it could not see as
    having left the board."""
    calls = {"n": 0}
    w = world(by_column={"To Do": [3]})
    real = w._answer

    def flaky(call):
        if call.path == "wit/wiql":
            calls["n"] += 1
            if calls["n"] == 2:
                raise AzureDevOpsError("POST wit/wiql → 503 Service Unavailable")
        return real(call)

    w._answer = flaky
    with caplog.at_level("WARNING"):
        assert _board(board="Issues").columns() is None
    assert "unreadable" in caplog.text


def test_a_board_that_reports_NO_COLUMNS_is_unreadable_and_not_an_empty_board(world, caplog):
    """A Kanban board always has columns — verified live: `work/boards/Nope/columns` answers
    `404 TF401501: The board does not exist`, it does not answer an empty list. So `value: []` is
    a 200 the payload never arrived in, and `values()` cannot tell that from a real collection.

    Let through, it breaks the port's hardest rule in its worst direction: `columns()` answers
    `{}` — an unreadable board reported as one every card has left — and `column_names()` answers
    `[]`, which sends somebody to create the columns they are looking straight at."""
    w = world(columns={"count": 0, "value": []})
    board = _board(board="Issues")

    with caplog.at_level("ERROR"):
        assert board.columns() is None
        assert board.column_names() is None
        assert board.items_in_status("To Do") == []

    assert "no columns at all" in caplog.text and "UNREADABLE" in caplog.text
    assert not w.sent("POST", "wit/wiql"), (
        "with no columns there is no work item TYPE filter either, so a query here would ask the "
        "whole project — an Epic's 'To Do' joining the pickup queue")


def test_a_wiql_response_without_workItems_is_unreadable_not_empty(world):
    w = world()
    w._answer = lambda call: ({"queryType": "flat"} if call.path == "wit/wiql"
                              else _World._answer(w, call))

    assert _board(board="Issues").columns() is None


def test_the_pickup_queue_still_DEGRADES_to_empty_rather_than_raising(world, caplog):
    """`items_in_status` is the poller's hottest read and `scan_todo` already treats an empty
    queue as "nothing this tick". It may not raise — but the log must say which happened."""
    world(fail={"columns": "GET work/boards/Issues/columns → 500"})

    with caplog.at_level("WARNING"):
        assert _board(board="Issues").items_in_status("To Do") == []

    assert "UNREADABLE" in caplog.text


def test_a_MISSPELLED_pickup_column_is_loud_instead_of_a_quiet_factory(world, caplog):
    """WIQL answers `[]` for `System.BoardColumn = 'Todo'` without complaint, so one missing space
    is an entire factory standing still and reporting a quiet day. Verified live: the query
    returns 200 with an empty result, not an error."""
    w = world(by_column={"To Do": [3, 4]})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").items_in_status("Todo") == []

    assert "OPENFACTORY_BOARD_UNKNOWN_COLUMN" in caplog.text
    assert "'To Do'" in caplog.text, "the message must name the columns that DO exist"
    assert not w.sent("POST", "wit/wiql"), "a name that cannot match must not cost a query"


def test_the_boards_own_spelling_goes_into_the_query(world):
    """The match here is case-insensitive; Azure DevOps's comparison need not be, so what travels
    is the board's spelling rather than the caller's."""
    w = world(by_column={"To Do": [3]})

    assert _board(board="Issues").items_in_status("to do") == ["3"]
    assert "'To Do'" in w.sent("POST", "wit/wiql")[0].query


# ── board order ─────────────────────────────────────────────────────────────────────────────────

def test_the_queue_follows_the_backlogs_own_STACK_RANK(world):
    """Azure DevOps's answer to Jira's `Rank`. `StackRank` is what Basic/Agile/CMMI order by and
    `BacklogPriority` is Scrum's — naming both sorts either process, because the one the process
    does not use is null on every card. `System.Id` is only the last resort, and it is creation
    order, which is precisely NOT the order a groomed backlog is in."""
    w = world(by_column={"To Do": [3, 4, 2]})

    refs = _board(board="Issues").items_in_status("To Do")

    assert refs == ["3", "4", "2"], "the board re-sorted what the humans had ranked"
    query = w.sent("POST", "wit/wiql")[0].query
    assert "ORDER BY [Microsoft.VSTS.Common.StackRank] ASC" in query
    assert "[Microsoft.VSTS.Common.BacklogPriority] ASC" in query


def test_an_organisation_without_those_fields_retreats_and_SAYS_SO(world, caplog):
    """`TF51005` is WIQL's *"the query references a field that does not exist"* — verified live by
    ordering on a nonexistent field. Falling back to id order loses board fidelity, so it is a
    warning rather than a silent equivalence."""
    w = world(by_column={"To Do": [3]})
    real = w._answer
    seen = {"n": 0}

    def picky(call):
        if call.path == "wit/wiql" and "StackRank" in call.query:
            seen["n"] += 1
            raise AzureDevOpsError("POST wit/wiql → 400 Bad Request: TF51005: The query "
                                   "references a field that does not exist.")
        return real(call)

    w._answer = picky
    board = _board(board="Issues")
    with caplog.at_level("WARNING"):
        refs = board.items_in_status("To Do")
        board.columns()  # five more queries, one per column

    assert refs == ["3"], "the retry must still produce a queue"
    # ONE failed attempt for the life of the board, not one per query. `columns()` is a query per
    # column, so a fallback that were not remembered would spend a guaranteed 400 on every one of
    # them and log this warning six times per read.
    assert seen["n"] == 1, "the fallback is rediscovered — and paid for — on every single query"
    assert "CREATION order" in caplog.text


def test_more_cards_than_one_page_is_REPORTED_not_silently_cut(world, caplog):
    """A queue quietly missing its tail looks exactly like a queue that is done — the same rule
    the Jira board follows at 200 and the GitHub one at 2000."""
    from openfactory.adapters.board.azure_devops import _MAX_ITEMS

    w = world(by_column={"To Do": list(range(1, _MAX_ITEMS + 40))})

    with caplog.at_level("WARNING"):
        refs = _board(board="Issues").items_in_status("To Do")

    assert len(refs) == _MAX_ITEMS
    assert "may be missing items" in caplog.text
    assert w.sent("POST", "wit/wiql")[0].params["$top"] == _MAX_ITEMS + 1, (
        "asking for exactly the cap makes truncation indistinguishable from a full page")


def test_columns_reads_the_board_COLUMN_BY_COLUMN_and_keeps_both_orders(world):
    """`{ref: column}` in board order, and within a column in rank order — `dict` preserves
    insertion, so the caller gets the board as a person reads it.

    Column by column because `System.BoardColumn` on a work item read is resolved for the
    project's DEFAULT team (no `wit/workitems` route takes a team segment), while `wit/wiql` does.
    On a project with more than one team that is the difference between this board and another."""
    world(by_column={"To Do": [3, 4], "Doing": [2], "Needs Action": [], "In review": [],
                     "Done": [7]})

    assert _board(board="Issues").columns() == {
        "3": "To Do", "4": "To Do", "2": "Doing", "7": "Done"}


def test_an_empty_board_is_an_empty_DICT(world):
    world(by_column=dict.fromkeys(["To Do", "Doing", "Needs Action", "In review", "Done"], []))

    assert _board(board="Issues").columns() == {}


def test_column_names_answers_even_when_no_card_is_on_the_board(world):
    """A different question from `columns()`: `sdlc doctor` asking *"is there a To Do?"* must not
    be answered "no" by a board nobody has filed against yet."""
    w = world()

    assert _board(board="Issues").column_names() == [
        "To Do", "Doing", "Needs Action", "In review", "Done"]
    assert not w.sent("POST", "wit/wiql"), "naming the columns must not cost a card query"


# ── which cards belong to this board at all ─────────────────────────────────────────────────────

def test_only_the_types_THIS_board_carries_are_queried(world):
    """`stateMappings` names them, so nothing is configured and nothing is guessed. Query the
    project broadly instead and an Epic's `To Do` — a DIFFERENT board's column of the same name —
    joins the pickup queue, and the factory starts coding an epic."""
    w = world(by_column={"To Do": [3]})

    _board(board="Issues").items_in_status("To Do")

    query = w.sent("POST", "wit/wiql")[0].query
    assert "[System.WorkItemType] IN ('Issue')" in query


def test_the_query_is_restricted_to_the_TEAMS_OWN_area_paths(world):
    """A board shows the team's areas, not the project's. Without this the queue on a multi-team
    project is a superset of the board somebody is looking at, and the factory picks up another
    team's card — work nobody asked it for, in the client's name."""
    w = world(by_column={"To Do": [3]})

    _board(board="Issues").items_in_status("To Do")

    assert "[System.AreaPath] = 'factory'" in w.sent("POST", "wit/wiql")[0].query


def test_includeChildren_is_HONOURED_rather_than_assumed(world):
    """The team's own answer to *"and everything under it?"*. Assuming `UNDER` hands the factory
    sub-team cards; assuming `=` hides the team's own."""
    w = world(by_column={"To Do": []},
              fields={"field": {"referenceName": "System.AreaPath"},
                      "values": [{"value": "factory\\Squad A", "includeChildren": True}]})

    _board(board="Issues").items_in_status("To Do")

    assert "[System.AreaPath] UNDER 'factory\\Squad A'" in w.sent("POST", "wit/wiql")[0].query


def test_a_custom_team_field_is_read_from_the_response(world):
    """An older project may be partitioned on something other than `System.AreaPath`, and the
    response names which — so the field is read, not assumed."""
    w = world(by_column={"To Do": []},
              fields={"field": {"referenceName": "Custom.Squad"},
                      "values": [{"value": "Blue", "includeChildren": False}]})

    _board(board="Issues").items_in_status("To Do")

    assert "[Custom.Squad] = 'Blue'" in w.sent("POST", "wit/wiql")[0].query


def test_unreadable_team_areas_widen_the_query_and_SAY_SO(world, caplog):
    """A superset queue beats no queue — but a superset nobody was told about is how another
    team's card gets picked up."""
    w = world(by_column={"To Do": [3]},
              fail={"teamfieldvalues": "GET work/teamsettings/teamfieldvalues → 403"})

    with caplog.at_level("WARNING"):
        assert _board(board="Issues").items_in_status("To Do") == ["3"]

    assert "SUPERSET" in caplog.text
    assert "AreaPath" not in w.sent("POST", "wit/wiql")[0].query


def test_a_column_name_with_an_apostrophe_is_ESCAPED(world):
    """WIQL doubles a quote to escape it. Unescaped, `Client's review` is not a wrong answer — it
    is a 400 in the middle of a poller tick."""
    columns = {"value": [{"name": "Client's review", "stateMappings": {"Issue": "Review"}}]}
    w = world(columns=columns, by_column={"Client''s review": []})

    _board(board="Issues").items_in_status("Client's review")

    assert "'Client''s review'" in w.sent("POST", "wit/wiql")[0].query


# ── moving a card ───────────────────────────────────────────────────────────────────────────────

def test_the_move_writes_the_STATE_because_the_COLUMN_IS_READ_ONLY(world):
    """`System.BoardColumn` is the obvious field to write — it is literally named after the column
    — and a PATCH of it answers `400 TF401326: Invalid field status 'ReadOnly'`. Verified live.
    So the column is an EFFECT of the state, and the board's `stateMappings` says which state."""
    w = world(cards={3: _card(3, state="To Do")})

    assert _board(board="Issues").set_column(issue="3", issue_url="", name="Doing") is True

    patch = w.sent("PATCH", "wit/workitems/3")[0]
    assert patch.body == [{"op": "add", "path": "/fields/System.State", "value": "Doing"}]
    assert patch.content_type == "application/json-patch+json"
    assert "BoardColumn" not in str(patch.body), "the read-only field is back in the write path"


def test_the_state_is_the_one_mapped_for_THIS_CARDS_type(world):
    """One board carries several work item types and a column maps a different state for each —
    which is why the card is read before it is written. The two-type shape is the live `Issues`
    board's, with the live `Epics` board's own `stateMappings` key alongside it."""
    columns = {"value": [{"name": "Doing",
                          "stateMappings": {"Issue": "Doing", "Bug": "Investigating"}}]}
    w = world(columns=columns, cards={9: _card(9, kind="Bug", state="To Do")})

    assert _board(board="Issues").set_column(issue="9", issue_url="", name="Doing") is True

    assert w.sent("PATCH", "wit/workitems/9")[0].body[0]["value"] == "Investigating"


def test_a_type_the_column_does_not_map_is_REFUSED_with_a_reason(world, caplog):
    columns = {"value": [{"name": "Doing", "stateMappings": {"Issue": "Doing"}}]}
    w = world(columns=columns, cards={9: _card(9, kind="Bug")})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(issue="9", issue_url="", name="Doing") is False

    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text and "'Bug'" in caplog.text
    assert not w.sent("PATCH", "wit/workitems/9"), "a card was written on a guessed state"


def test_a_card_already_in_the_column_is_not_written_again(world):
    """Idempotent, and compared on the STATE rather than on `System.BoardColumn`: state is the same
    answer for every team, and the column a work item read reports is the DEFAULT team's."""
    w = world(cards={3: _card(3, state="Doing")})

    assert _board(board="Issues").set_column(issue="3", issue_url="", name="Doing") is True

    assert not w.sent("PATCH", "wit/workitems/3"), "a no-op move spent a card revision"


def test_a_column_the_board_does_not_have_is_refused_naming_the_ones_it_does(world, caplog):
    w = world(cards={3: _card(3)})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(issue="3", issue_url="", name="Nope") is False

    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text and "'To Do'" in caplog.text
    assert not w.sent("PATCH", "wit/workitems/3")


def test_a_ref_this_provider_cannot_ADDRESS_is_refused_not_coerced(world, caplog):
    """C-05, and the conformance suite's own rule: reducing `CONT-412` to `412` moves somebody
    else's card, silently, in the client's name."""
    w = world(cards={412: _card(412)})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(
            issue="CONT-412", issue_url="", name="Done") is False

    assert not w.sent("PATCH", "wit/workitems/412")


def test_the_human_decoration_on_a_ref_is_accepted(world):
    """`#3` and `3` must never be two tickets — `canonical_ref` is the one spelling."""
    w = world(cards={3: _card(3)})

    assert _board(board="Issues").set_column(issue="#3", issue_url="", name="Doing") is True
    assert w.sent("PATCH", "wit/workitems/3")


def test_a_card_that_cannot_be_READ_is_never_written_blind(world, caplog):
    """Live: `404 TF401232: Work item 999999 does not exist`. Without the type there is no state
    to write, and guessing one is a card moved by rules nobody chose."""
    w = world(cards={})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(
            issue="999999", issue_url="", name="Doing") is False

    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text
    assert not w.sent("PATCH", "wit/workitems/999999")


def test_an_unreadable_board_refuses_the_move_rather_than_guessing_a_state(world, caplog):
    world(cards={3: _card(3)}, fail={"columns": "GET …/columns → 503"})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(issue="3", issue_url="", name="Doing") is False

    assert "refusing to guess" in caplog.text


def test_a_write_that_failed_returns_False_and_leaves_a_why(world, caplog):
    """A write that did not happen must never look like one that did."""
    world(cards={3: _card(3)},
          fail={"wit/workitems/3": "PATCH wit/workitems/3 → 403 Forbidden: no write scope"})

    with caplog.at_level("ERROR"):
        assert _board(board="Issues").set_column(issue="3", issue_url="", name="Doing") is False

    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text and "403" in caplog.text


# ── the lifecycle, in the client's own vocabulary ───────────────────────────────────────────────

@pytest.mark.parametrize("state,column", [
    (JobState.TODO, "To Do"),
    (JobState.READY, "To Do"),
    (JobState.IMPLEMENTING, "Doing"),
    (JobState.PR_OPEN, "In review"),
    # A PRODUCTION GATE IS A PERSON (#166). This pinned "In review" while the platform's own
    # `ATTENTION_STATES` named it as needing a human — so the floor said "Needs you" and the
    # client's board said "In review" with Needs Action reading zero, about the one gesture that
    # puts software in front of real users. The claim changed; the guard follows it.
    (JobState.AWAITING_PROD_APPROVAL, "Needs Action"),
    (JobState.BLOCKED, "Needs Action"),
    (JobState.FAILED, "Needs Action"),
    (JobState.DONE, "Done"),
])
def test_every_lifecycle_bucket_lands_on_the_column_it_maps_to(world, state, column):
    w = world(cards={3: _card(3, state="__nowhere__")})

    assert _board(board="Issues").set_status(issue="3", issue_url="", state=state) is True

    mapped = {c["name"]: c["stateMappings"]["Issue"] for c in COLUMNS["value"]}[column]
    assert w.sent("PATCH", "wit/workitems/3")[0].body[0]["value"] == mapped


def test_set_status_speaks_the_CLIENTS_column_names_not_english(world):
    """C-14: the lifecycle is the platform's, the vocabulary is the client's. A board that says
    `A Fazer` must not need a rename to be driven."""
    columns = {"value": [{"name": "A Fazer", "stateMappings": {"Issue": "A Fazer"}},
                         {"name": "Fazendo", "stateMappings": {"Issue": "Fazendo"}}]}
    w = world(columns=columns, cards={3: _card(3, state="A Fazer")})
    board = _board(board="Issues", columns={"todo": "A Fazer", "in_progress": "Fazendo"})

    assert board.set_status(issue="3", issue_url="", state=JobState.IMPLEMENTING) is True

    assert w.sent("PATCH", "wit/workitems/3")[0].body[0]["value"] == "Fazendo"


def test_an_unmapped_state_is_a_no_op_with_a_reason_never_a_guess(world, caplog):
    w = world(cards={3: _card(3)})
    board = _board(board="Issues", columns={"done": ""})

    with caplog.at_level("WARNING"):
        assert board.set_status(issue="3", issue_url="", state=JobState.DONE) is False

    assert "no Azure Boards column mapped" in caplog.text
    assert not w.sent("PATCH", "wit/workitems/3")


def test_add_item_is_a_no_op_because_a_work_item_is_already_on_the_board(world):
    """Kept explicit rather than omitted: a Projects v2 board is a separate object a card must be
    attached to, and no caller should have to know which of the two shapes it is holding."""
    w = world()

    assert _board(board="Issues").add_item(issue_url="https://dev.azure.com/x/_workitems/edit/3") \
        is None
    assert w.calls == []


# ── the ref this board MINTS is the ref this board must ACCEPT (sweep S1, 2026-08-16) ───────────
#
# `items_in_status` returns `_qualify`'d refs — `owner/repo#1234` — precisely so the repository
# travels with the ticket on a multi-repo product (C-18). `set_column` then handed that whole
# string to `ref_number`, got None, and refused its own output as "not an Azure DevOps work item
# id". On a multi-repo board — which is the enterprise mandate — every card move failed: the park
# never showed, the merge never settled, and the three-minute stale-card heal retried the same
# refusal for ever, logging OPENFACTORY_BOARD_MOVE_FAILED into a file nobody tails.
#
# The Azure TRACKER learned this at C-18 and its comment records that the GitHub one had had it
# since. The BOARD was the third place, and these 245 tests never caught it because every one of
# them used a bare ref.

def test_a_qualified_ref_moves_the_card(world):
    """The regression, in the shape a multi-repo board actually produces."""
    w = world(cards={3: _card(3)})
    assert _board().set_column(issue="acme/web#3", issue_url="", name="Doing") is True, (
        "the board refused the very ref its own pickup queue mints — on a multi-repo product "
        "no card can ever be moved")
    patched = w.sent("PATCH", "wit/workitems/3")
    assert patched, "no work item was patched at all"
    assert "/3" in patched[0].path, (
        f"the move went to the wrong work item: {patched[0].path}")


def test_the_repository_half_is_discarded_not_smuggled_into_the_id(world):
    """`acme/web#3` must move work item 3 — never 'web3', never a coerced digit soup. The tracker
    discards the repo for the same reason: which repo a card belongs to is the forge's question."""
    w = world(cards={3: _card(3)})
    _board().set_column(issue="acme/web#3", issue_url="", name="Doing")
    assert [c.path for c in w.sent("PATCH", "wit/workitems")] == ["wit/workitems/3"]


def test_set_status_carries_a_qualified_ref_through_too(world):
    """It delegates to `set_column`, so it inherits the fix — asserted rather than assumed, since
    it is the path the merge and the park actually take."""
    w = world(cards={3: _card(3)})
    assert _board().set_status(issue="acme/web#3", issue_url="", state=JobState.IMPLEMENTING)
    assert w.sent("PATCH", "wit/workitems/3")


def test_a_ref_from_ANOTHER_tracker_is_still_refused(world):
    """The positive twin. Widening the parse must not start coercing `CONT-412` — reducing it to
    412 moves somebody else's card, which is worse than refusing."""
    world(cards={412: _card(412)})
    assert _board().set_column(issue="acme/web#CONT-412", issue_url="", name="Doing") is False
    assert _board().set_column(issue="CONT-412", issue_url="", name="Doing") is False


def test_the_board_ACCEPTS_WHAT_IT_RETURNS_as_a_property(world):
    """The general statement, so the next ref shape cannot break the pair: whatever
    `items_in_status` hands out, `set_column` must take. Derived from the read rather than from a
    literal, which is what makes it survive a change to the qualification format."""
    w = world(by_column={"To Do": [3]}, cards={3: _card(3)}, areas_of={"3": "factory\\web"})
    board = _board(default_repo="acme/web", areas={"web": "acme/web"})
    minted = board.items_in_status("To Do")
    assert minted, "the pickup queue returned nothing — this property is untested as written"
    # AND IT MUST BE MINTING THE QUALIFIED SHAPE. Without this the world quietly degrades to bare
    # refs — an unreadable area, a route the recorder does not know — and the property below holds
    # about `'3'`, the one shape that never had the bug. Which is exactly what happened: mutating
    # the fix left this test green, and that is how a guard turns into decoration.
    assert any("#" in r for r in minted), (
        f"this world is not producing qualified refs ({minted}) — the property is vacuous")
    for ref in minted:
        assert board.set_column(issue=ref, issue_url="", name="Doing") is True, (
            f"the board mints {ref!r} and then refuses it")
    assert w.sent("PATCH", "wit/workitems/3")

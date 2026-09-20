"""#231: on a Jira board the stage gate could never place a card, so no card could be edited or
closed.

WHAT THE GATE ASKED, AND OF WHOM. `actions/catalog.py::_stage` turned a board's own column name
into a neutral key with `key_for(column, renamed=proj.tracker.options.get("columns"))`. A project's
tracker options are `dict[str, str]` (`contracts/project.py`), so that value is a STRING or absent,
and `key_for` wants a mapping. Both shapes fail, and Jira meets them on every card because a Jira
board's columns ARE the site's workflow statuses:

    absent   key_for("Concluído", renamed=None)                    -> ''      every edit and every
                                                                              close refused
    a string key_for("Concluído", renamed='{"done": "Concluído"}') -> TypeError: 'str' object is
                                                                     not a mapping, which reaches
                                                                     the operator as
                                                                     `could not card_close: …`

The deployment HAD declared its names — in the Jira row's own option, `status_map`, which this gate
never read. So the question moves to where the answer already lives: the BOARD ROW says which
neutral stage one of its columns is (`adapters/board/base.py::stage_key`), and generic code stops
reaching into one option name it hoped every tracker spelled alike.

WHAT IS DRIVEN HERE IS THE REAL `card_edit` AND `card_close`, over the real `JiraTracker` and the
real `JiraProjectBoard`, against a fake at the ONE place the adapter touches the network
(`urllib.request.urlopen`) — the shape #203's guard established. The site is a small Portuguese
Jira: its statuses are its own words, and the platform's six names appear nowhere on it.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error

import pytest

from openfactory.adapters.tracker.jira import JiraTracker

REF = "DAR-7"
TODO, RUNNING, DONE = "A Fazer", "Em andamento", "Concluído"
DONE_ID = "31"
#: A status this site really has and nobody maps — not in `status_map`, not one of the platform's
#: six names. Its refusal is a REAL answer and must survive the fix.
UNMAPPED = "Aguardando cliente"


class _Answer:
    def __init__(self, payload: dict | None) -> None:
        self._body = json.dumps(payload).encode() if payload is not None else b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _Site:
    """One Jira Cloud site: one issue, its status, its workflow."""

    def __init__(self, *, status: str = TODO) -> None:
        self.status = status
        self.category = "done" if status == DONE else "indeterminate"
        self.summary = "exportar o relatório"
        self.description = "## Objetivo\n\nExportar o relatório\n"
        self.requests: list[tuple[str, str, dict | None]] = []

    # -- what a case reads ---------------------------------------------------------------------
    def calls(self, method: str, suffix: str) -> list[dict]:
        return [body or {} for verb, path, body in self.requests
                if verb == method and path.split("?")[0].endswith(suffix)]

    def said(self) -> list[str]:
        return [JiraTracker._text(body.get("body")) for body in self.calls("POST", "/comment")]

    # -- the wire ------------------------------------------------------------------------------
    def _refuse(self, req, code: int, payload: dict):
        raise urllib.error.HTTPError(req.full_url, code, "refused", hdrs=None,
                                     fp=io.BytesIO(json.dumps(payload).encode()))

    def urlopen(self, req, timeout=0):  # noqa: ARG002 — urllib's own signature
        method = req.get_method()
        path = req.full_url.split("/rest/api/3/", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.requests.append((method, path, body))
        bare = path.split("?")[0]
        if (method, bare) == ("GET", f"issue/{REF}"):
            return _Answer(self._issue())
        if (method, bare) == ("PUT", f"issue/{REF}"):
            fields = (body or {}).get("fields") or {}
            if "summary" in fields:
                self.summary = fields["summary"]
            if "description" in fields:
                self.description = JiraTracker._text(fields["description"])
            return _Answer(None)
        if (method, bare) == ("GET", "search/jql"):
            return _Answer({"isLast": True, "issues": [self._issue()]})
        if (method, bare) == ("POST", f"issue/{REF}/comment"):
            return _Answer({"id": "10001"})
        if (method, bare) == ("GET", f"issue/{REF}/transitions"):
            return _Answer({"transitions": [
                {"id": "11", "name": "Reabrir", "to": {"name": TODO}},
                {"id": DONE_ID, "name": "Concluir",
                 "to": {"name": DONE, "statusCategory": {"key": "done"}}},
            ]})
        if (method, bare) == ("POST", f"issue/{REF}/transitions"):
            assert ((body or {}).get("transition") or {}).get("id") == DONE_ID, body
            self.status, self.category = DONE, "done"
            return _Answer(None)
        raise AssertionError(f"the adapter called {method} {path}, a route this site never had")

    def _issue(self) -> dict:
        return {"id": "10071", "key": REF, "fields": {
            "summary": self.summary, "description": JiraTracker._adf(self.description),
            "status": {"name": self.status, "statusCategory": {"key": self.category}},
            "labels": [], "assignee": None, "reporter": None,
            "updated": "2026-09-20T10:00:00.000+0100", "resolution": None}}


def _act(name: str, **params):
    import asyncio

    from openfactory import actions

    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=who, **params))


@pytest.fixture
def jira(tmp_path, monkeypatch):
    """A registered Jira project whose site speaks its own language, and the fake site behind it.

    `columns` is passed through too, because the whole point is that a deployment may have typed
    one and generic code must not read it: on a Jira row the map lives in `status_map`."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("JIRA_API_TOKEN", "t")

    def _open(*, status: str = TODO, status_map: dict | None = None, columns: str = "") -> _Site:
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry

        options = {
            "site": "https://acme-team.atlassian.net", "project_key": "DAR",
            "email": "alice@acme.ai",
            "status_map": json.dumps(status_map if status_map is not None else {
                "todo": TODO, "in_progress": RUNNING, "done": DONE}),
        }
        if columns:
            options["columns"] = columns
        registry = ProjectRegistry()
        registry.add(Project(name="acme", repo_path=str(tmp_path),
                             tracker=ProviderRef(kind="jira", repo="DAR", options=options)))
        site = _Site(status=status)
        monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
        return site
    return _open


# ── the card a Jira deployment could not touch ──────────────────────────────────────────────────

def test_a_card_in_the_sites_own_TODO_is_edited(jira):
    """`A Fazer` is what this deployment calls `todo`, and it said so in `status_map`."""
    site = jira(status=TODO)

    out = _act("card_edit", project="acme", issue=REF, title="exportar o relatório mensal")

    assert out.ok, out.message
    assert site.summary == "exportar o relatório mensal"


def test_a_card_in_the_sites_own_DONE_is_closed_as_delivered(jira):
    site = jira(status=DONE)

    out = _act("card_close", project="acme", issue=REF, reason="entregue na semana passada")

    assert out.ok, out.message
    assert "as delivered" in out.message and DONE in out.message, out.message
    # delivered closes with the BARE transition: no resolution field, and no note saying the work
    # was withdrawn (`JiraTracker.close_ticket`).
    assert site.calls("POST", "/transitions") == [{"transition": {"id": DONE_ID}}]


def test_a_card_in_a_status_the_deployment_mapped_to_RUNNING_is_still_refused(jira):
    """The gate that exists is not loosened: `Em andamento` is this site's `in_progress`."""
    site = jira(status=RUNNING)

    out = _act("card_close", project="acme", issue=REF, reason="não é mais necessário")

    assert not out.ok and "Stop the job first" in out.message, out.message
    assert site.calls("POST", "/transitions") == [], "the card was closed anyway"


def test_a_columns_option_a_person_typed_never_reaches_an_operator_as_a_TypeError(jira):
    """A `columns` option written the way `status_map` is documented used to raise straight
    through `perform`'s catch-all: `could not card_close: 'str' object is not a mapping`."""
    site = jira(status=DONE, columns=json.dumps({"done": "Entregue"}))

    out = _act("card_close", project="acme", issue=REF, reason="entregue")

    assert "not a mapping" not in out.message and "TypeError" not in out.message, out.message
    assert out.ok, out.message
    assert site.calls("POST", "/transitions") == [{"transition": {"id": DONE_ID}}]


# ── the refusal that is a real answer ───────────────────────────────────────────────────────────

def test_a_status_NOBODY_maps_keeps_its_honest_refusal(jira):
    site = jira(status=UNMAPPED)

    out = _act("card_close", project="acme", issue=REF, reason="não é mais necessário")

    assert not out.ok, out.message
    assert UNMAPPED in out.message and "not a column this platform maps" in out.message
    assert site.calls("POST", "/transitions") == [], (
        "a column nobody maps was closed anyway — and as not delivered")


def test_and_the_refusal_names_the_option_THIS_row_reads(jira):
    """`columns` is the wrong remedy on a Jira board: its map is `status_map`. A refusal whose
    remedy does not exist sends a person to edit an option that changes nothing."""
    jira(status=UNMAPPED)

    out = _act("card_edit", project="acme", issue=REF, title="qualquer coisa")

    assert "`status_map`" in out.message, out.message
    assert "`columns`" not in out.message, out.message


# ── the option a person typed, on the rows that DO read `columns` ───────────────────────────────

@pytest.fixture
def github(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghs_x")

    def _register(columns: str):
        from openfactory.contracts.project import Project, ProviderRef
        from openfactory.registry import ProjectRegistry

        registry = ProjectRegistry()
        registry.add(Project(name="acme", repo_path=str(tmp_path), tracker=ProviderRef(
            kind="github", repo="acme/app",
            options={"board_owner": "acme", "board_number": "4", "columns": columns})))
        return registry.get("acme")
    return _register


def test_a_columns_option_that_is_a_JSON_STRING_builds_a_board_that_maps_it(github):
    """The only shape the option CAN have: `ProviderRef.options` is `dict[str, str]`. The GitHub
    row was handed the raw string and did `(columns or {}).items()` on it."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key

    project = github(json.dumps({"done": "Entregue", "todo": "A Fazer"}))
    board = build_board(project)

    assert stage_key(board, "Entregue") == "done"
    assert stage_key(board, "A Fazer") == "todo"
    assert stage_key(board, "In review") == "in_review", "the defaults still answer under it"


def test_and_the_TRACKERS_github_row_takes_the_same_string(github):
    """`tracker/registry.py` hands the same option to `GitHubIssuesTracker(board_columns=…)`,
    which builds a board of its own out of it."""
    from openfactory.adapters.tracker.registry import build_tracker

    project = github(json.dumps({"todo": "A Fazer"}))
    tracker = build_tracker(project)

    assert tracker.board.pickup_column() == "A Fazer"


def test_a_columns_option_that_is_not_JSON_at_all_falls_back_and_says_so(github, caplog):
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key

    with caplog.at_level(logging.ERROR):
        board = build_board(github("todo: A Fazer"))

    assert stage_key(board, "TO-DO") == "todo", "the platform's own names still answer"
    said = [r.getMessage() for r in caplog.records]
    assert any("`columns`" in line and "not a JSON object" in line for line in said), said


def test_the_poll_tick_survives_a_columns_option_that_is_a_string(github):
    """`_pickup_column` read `(options.get("columns") or {}).get("todo")` OUTSIDE its own `except`,
    so one such project took down the whole work-list build — every project, every tick."""
    from openfactory.runtime.temporal.activities import _pickup_column

    assert _pickup_column(github(json.dumps({"todo": "A Fazer"}))) == "A Fazer"


# ── the seam, and the row that answers nothing ──────────────────────────────────────────────────

def test_a_board_row_that_says_nothing_degrades_to_the_platforms_own_names():
    """An add-on board written before this verb existed keeps working, honestly degraded."""
    from openfactory.adapters.board.base import stage_key, stage_option

    class _Stranger:
        def columns(self):
            return {"7": "Done"}

    row = _Stranger()
    assert stage_key(row, "Done") == "done"
    assert stage_key(row, "In review") == "in_review"
    assert stage_key(row, "Concluído") == "", "a name nobody maps is still *I do not know it*"
    assert stage_option(row) == "", "it declares no option, and the refusal must not invent one"


def test_a_row_that_answers_with_something_that_is_not_a_name_is_not_believed(caplog):
    """A `MagicMock` is not a declaration: it answers every call with another mock, and believing
    one would make the gate's key a mock object the columns table would silently reject."""
    from unittest.mock import MagicMock

    from openfactory.adapters.board.base import stage_key, stage_option

    row = MagicMock()
    with caplog.at_level(logging.WARNING):
        assert stage_key(row, "Done") == "done"
    assert stage_option(row) == ""
    assert "stage" in caplog.text.lower(), caplog.text


def test_every_shipped_board_row_answers_for_its_own_columns():
    """Not a `hasattr` sweep for its own sake: each of the four holds the deployment's names in a
    different place, and a row that forgot to answer degrades SILENTLY to the platform's six."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    for row in (LocalBoard, JiraProjectBoard, GitHubProjectBoard, AzureBoardsBoard):
        assert callable(getattr(row, "stage_key", None)), row.__name__
        assert isinstance(getattr(row, "stage_option", None), str), row.__name__


def test_the_jira_row_answers_from_the_map_its_own_deployment_declared():
    from openfactory.adapters.board.jira import JiraProjectBoard

    tracker = JiraTracker(site="https://acme-team.atlassian.net", project_key="DAR",
                          email="alice@acme.ai", token="t",
                          status_map={"todo": TODO, "done": DONE})
    board = JiraProjectBoard(tracker)

    assert board.stage_key(DONE) == "done" and board.stage_key(TODO) == "todo"
    assert board.stage_key(UNMAPPED) == ""
    assert board.stage_option == "status_map"


# ── the twin on a local board, which must not change ────────────────────────────────────────────

@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="acme", options={})))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    return project


def _local_card(project, column: str) -> str:
    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker

    tracker = build_tracker(project)
    ref = tracker.create_ticket(title="Lock the statement", body="## Objective\n\nLock it\n")
    assert build_board(project).set_column(issue=ref, issue_url="", name=column), column
    return ref


def test_the_local_board_gates_exactly_as_it_did(local):
    assert _act("card_close", project="acme", issue=_local_card(local, "Done"),
                reason="shipped").ok
    running = _act("card_close", project="acme", issue=_local_card(local, "In progress"),
                   reason="withdrawn")
    assert not running.ok and "Stop the job first" in running.message, running.message
    assert _act("card_edit", project="acme", issue=_local_card(local, "TO-DO"),
                title="renamed before pickup").ok


def test_a_local_board_whose_column_was_RENAMED_is_read_from_the_board_itself(local):
    """The row reads the names off its own rows, so a column renamed on the board is mapped
    without anybody writing a second copy of the map into the registry."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import stage_key
    from openfactory.adapters.board_db import connect

    ref = _local_card(local, "Done")
    with connect() as conn:
        conn.execute("UPDATE columns SET name = ? WHERE project = ? AND key = 'done'",
                     ("Entregue", local.name))
        conn.commit()

    assert stage_key(build_board(local), "Entregue") == "done"
    out = _act("card_close", project="acme", issue=ref, reason="shipped")
    assert out.ok and "as delivered" in out.message, out.message

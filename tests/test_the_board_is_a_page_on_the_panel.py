"""The Board is the panel's, through the ports — one read, for every kind (ADR-0049 D6).

WHAT IS PROVEN HERE:

  · the route answers through `BoardAdapter` and `TrackerAdapter` and compares NO provider kind;
  · the three answers survive the trip to the browser — `None` could not read, `[]`/`{}` read
    fine and empty — because a surface that collapses them is how the factory once reported
    itself idle with a queue in front of it;
  · **watching is the row's answer, not the panel's guess**: a board that is cheap to re-read
    says so through `Watchable`, and one that is silent is simply not watched;
  · the page reaches the board through the action layer and gains no capability of its own.
"""

from __future__ import annotations

import pathlib

import pytest

PANEL = (pathlib.Path(__file__).resolve().parent.parent
         / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project whose board `project init` has already created."""
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


@pytest.fixture
def tracker(deployment):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(deployment)


# ── the route ───────────────────────────────────────────────────────────────────────────────────

def test_the_board_is_one_read_through_the_two_ports(deployment, tracker):
    """The board says WHERE, the tracker says WHAT — two ports, one row on the page."""
    from openfactory.adapters.board import build_board
    from openfactory.api.app import board_view

    ref = tracker.create_ticket(title="Render the board", body="## Objective\nShow it\n")
    build_board(deployment).set_column(issue=ref, issue_url="", name="TO-DO")

    got = board_view("acme")
    assert got["columns"] == ["Backlog", "TO-DO", "In progress", "In review", "Needs Action",
                              "Done"]
    assert got["cards"] == [{"ref": "1", "column": "TO-DO", "title": "Render the board",
                             "labels": [], "updated_at": got["cards"][0]["updated_at"]}]


def test_a_card_the_board_does_not_place_is_still_listed(deployment, tracker):
    """Dropping it would hide work from the person looking for it — and the column it is not in
    is exactly what they would be looking for."""
    from openfactory.api.app import board_view

    tracker.create_ticket(title="filed, unplaced", body="", column="nowhere")
    assert board_view("acme")["cards"] == [
        {"ref": "1", "column": "", "title": "filed, unplaced", "labels": [],
         "updated_at": board_view("acme")["cards"][0]["updated_at"]}]


def test_an_empty_board_and_an_unreadable_one_are_different_answers(deployment, monkeypatch):
    """The distinction the whole read side is built on, carried all the way to the browser."""
    from openfactory.api.app import board_view

    empty = board_view("acme")
    assert empty["cards"] == [] and empty["columns"] != [], "read fine, nothing on it"

    class _Dark:
        def column_names(self):
            return None

        def columns(self):
            return None

        def poll_seconds(self):
            return 3

    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *a, **kw: _Dark())
    dark = board_view("acme")
    assert dark["columns"] is None and dark["cards"] is None, (
        "an unreadable board must not reach the page as an empty one")


def test_a_deployment_with_no_board_says_so_rather_than_showing_an_empty_one(deployment,
                                                                            monkeypatch):
    """Running on tickets alone is a first-class answer on this axis, not an error."""
    from openfactory.api.app import board_view

    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *a, **kw: None)
    got = board_view("acme")
    assert got["board"] is False and got["columns"] is None and got["cards"] is None


def test_an_unknown_project_is_a_404_naming_itself(deployment):
    from fastapi import HTTPException

    from openfactory.api.app import board_view

    with pytest.raises(HTTPException) as caught:
        board_view("not-a-project")
    assert caught.value.status_code == 404 and "not-a-project" in str(caught.value.detail)


# ── watching is the row's answer ────────────────────────────────────────────────────────────────

def test_the_row_says_how_often_it_may_be_watched_and_the_panel_never_guesses(deployment,
                                                                              monkeypatch):
    """`Watchable` exists for `Rankable`'s reason: the panel must not decide, by a provider's
    name, which boards are cheap to re-read. A new row would be decided about by a surface that
    has never met it."""
    from openfactory.adapters.board.base import Watchable
    from openfactory.adapters.board.jira import JiraProjectBoard
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.api.app import board_view

    assert board_view("acme")["poll_seconds"] == 3

    jira = JiraProjectBoard(type("T", (), {"site": "s", "project_key": "K",
                                           "status_map": {}})())
    assert not isinstance(jira, Watchable), "nothing that crosses a network claims this"
    assert isinstance(LocalBoard(type("T", (), {"project": "acme", "_db": None})()), Watchable)

    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *a, **kw: jira)
    assert board_view("acme")["poll_seconds"] is None, "a silent row is simply not watched"


def test_the_route_names_no_provider_kind():
    """The panel's standing rule, held over the code this slice adds."""
    import ast
    import inspect

    from openfactory.api import app as app_module

    src = inspect.getsource(app_module.board_view) + inspect.getsource(app_module._card_detail)
    tree = ast.parse(src)
    words = {"github", "jira", "azure_devops", "local"}
    prose = {n.value.lineno for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.body
             and isinstance(n.body[0], ast.Expr)
             and isinstance(getattr(n.body[0], "value", None), ast.Constant)
             for n in [n.body[0]]}
    offenders = [n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.lineno not in prose and n.value.strip().lower() in words]
    assert not offenders, f"the board route names a provider: {offenders}"


# ── the card's own read ─────────────────────────────────────────────────────────────────────────

def test_the_drawer_reads_the_body_and_the_thread(deployment, tracker):
    from openfactory.api.app import board_view

    body = "## Objective\nShow the queue\n"
    ref = tracker.create_ticket(title="one", body=body)
    tracker.say(ref, "why not link out?", author="mara")
    tracker.comment(ref, "because a person has to leave the floor to see it")

    card = board_view("acme", card="1")["card"]
    assert card["readable"] and card["title"] == "one" and card["body"] == body
    assert [(c["author"], c["body"]) for c in card["comments"]] == [
        ("mara", "why not link out?"),
        ("openfactory[bot]", "because a person has to leave the floor to see it")]


def test_a_thread_that_could_not_be_read_reaches_the_page_as_None(deployment, tracker,
                                                                  monkeypatch):
    """`[]` here would tell the reader nobody has commented, which is a fact this read did not
    establish."""
    from openfactory.api.app import board_view

    tracker.create_ticket(title="one", body="")
    monkeypatch.setattr("openfactory.adapters.tracker.local.LocalTracker.comments",
                        lambda self, ref, limit=0: None)
    assert board_view("acme", card="1")["card"]["comments"] is None


def test_a_card_that_is_not_there_is_an_answer_and_not_a_500(deployment, tracker):
    from openfactory.api.app import board_view

    tracker.create_ticket(title="one", body="")
    missing = board_view("acme", card="404")["card"]
    assert missing["readable"] is False and missing["comments"] is None


def test_the_board_is_not_read_for_a_card_nobody_asked_for(deployment, tracker):
    """The detail is opt-in, so opening the board costs one read and not one per card."""
    from openfactory.api.app import board_view

    tracker.create_ticket(title="one", body="")
    assert board_view("acme")["card"] is None


# ── the page ────────────────────────────────────────────────────────────────────────────────────

def test_the_deeper_addresses_are_SERVED(deployment):
    """A bookmarked board must land on the board, not on the server's own not-found — which is
    what a single-page app looks like when only its root is declared."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app

    client = TestClient(app)
    for path in ("/p/acme", "/p/acme/board", "/p/acme/card/7"):
        got = client.get(path)
        assert got.status_code == 200, f"{path} is not served: {got.status_code}"
        assert "<html" in got.text.lower(), f"{path} did not answer with the page"


# ── the page's own logic, asserted STRUCTURALLY ─────────────────────────────────────────────────
#
# NAMED AS A LIMITATION RATHER THAN LEFT AS ONE. Nothing in this repository executes the panel's
# JavaScript — there is no node in CI and no JS harness — so every guard over this file, this
# slice's included, reads it as TEXT. That is strong enough to see a branch deleted or a literal
# written back, and it is NOT strong enough to see a branch that runs wrongly. Measured: the first
# run of this slice's mutation plan cut four of these behaviours and every text-scan stayed green
# until the assertions below were made specific. Executing the page is its own card.

def test_the_page_tells_an_unreadable_board_from_an_empty_one():
    board = PANEL.split("function paintBoard()")[1].split("function _bcard")[0]
    assert "d.columns === null" in board and "d.cards === null" in board, (
        "the page renders a board it could not read the same way as one that is empty — the "
        "collapse the three answers exist to prevent")


def test_the_page_tells_an_unreadable_thread_from_an_empty_one():
    thread = PANEL.split("function _bthread(c)")[1].split("\n}")[0]
    assert "c.comments === null" in thread, "an unreadable thread reaches the reader as silence"
    assert "!c.comments.length" in thread, "and an empty one is not stated as a fact"


def test_the_page_polls_at_the_cadence_the_ROW_named():
    watch = PANEL.split("function _bwatch()")[1].split("\n}")[0]
    assert "poll_seconds" in watch, "the page invented a cadence instead of reading the row's"
    assert "if(!every || every <= 0) return;" in watch, (
        "a row that said nothing must not be polled at all")


def test_every_write_on_the_board_is_an_action_row():
    board = PANEL.split("// ══ THE BOARD")[1].split("function toast(")[0]
    for row in ("card_move", "card_create", "card_comment"):
        assert f'act("{row}"' in board, f"the board writes {row} some other way"
    assert "/api/board/move" not in board, "the page grew a verb of its own (ADR-0039)"


def test_the_page_reaches_the_board_through_the_action_layer(deployment):
    """The panel gains no capability of its own (ADR-0039). Every write on this surface is one of
    the three rows the catalogue holds."""
    for row in ("card_create", "card_move", "card_comment"):
        assert f'"{row}"' in PANEL, f"the Board never reaches {row}"
    assert '"/api/act/"' in PANEL, "and it reaches them through the generic route"


def test_the_page_asks_the_route_rather_than_the_adapters(deployment):
    assert "/api/board/" in PANEL


def test_the_board_pill_is_hidden_on_the_product_surface():
    """As `#costs` is: a floor button on the product surface is one that can only fail."""
    boot = PANEL.split("async function bootProduct()")[1].split("\n}")[0]
    assert "#board" in boot and "display" in boot


def test_the_page_watches_only_what_the_row_said_may_be_watched():
    """The number, never a kind — the panel's standing rule, held over the page as well as the
    route."""
    assert "poll_seconds" in PANEL
    for kind in ('"github"', '"jira"', '"azure_devops"', '"local"'):
        assert f"pollKind === {kind}" not in PANEL


def test_the_how_to_names_the_panels_own_board_first():
    """FREE FIRST. The paragraph used to teach the three hosted boards and never mention that this
    deployment can hold one — which is the default now."""
    how_to = PANEL.split("board &amp; tracker")[1][:900] if "board &amp; tracker" in PANEL else ""
    assert how_to, "the how-to paragraph is gone — the guard is measuring nothing"
    assert how_to.index("this panel") < min(
        (how_to.index(v) for v in ("GitHub", "Jira", "Azure") if v in how_to), default=10**6), (
        "the hosted boards are named before the one that needs no account")

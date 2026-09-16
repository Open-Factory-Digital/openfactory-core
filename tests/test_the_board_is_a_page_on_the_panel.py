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
    for row in ("card_move", "card_create", "card_comment", "card_edit", "card_close",
                "card_reopen"):
        assert f'act("{row}"' in board, f"the board writes {row} some other way"
    assert "/api/board/move" not in board, "the page grew a verb of its own (ADR-0039)"


def test_the_page_reaches_the_board_through_the_action_layer(deployment):
    """The panel gains no capability of its own (ADR-0039). Every write on this surface is one of
    the three rows the catalogue holds."""
    for row in ("card_create", "card_move", "card_comment", "card_edit", "card_close",
                "card_reopen"):
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


# ── correcting a card, and taking it off the board (#150) ───────────────────────────────────────

def _act(name: str, **params):
    """One action row, driven the way every front end drives it."""
    import asyncio

    from openfactory import actions

    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=who, **params))


def _queued(deployment, tracker, *, title="Lock the statement", body="## Objective\n\nLock it\n"):
    """A card on the board, in TO-DO — where the operator put it and the factory has not been."""
    from openfactory.adapters.board import build_board

    ref = tracker.create_ticket(title=title, body=body)
    build_board(deployment).set_column(issue=ref, issue_url="", name="TO-DO")
    return ref


def test_a_card_is_corrected_while_the_factory_has_not_taken_it_up(deployment, tracker):
    """The complaint this row answers: on `tracker: local` the board IS the tracker, so a card that
    the spec gate will refuse could not be fixed anywhere — the panel could only create, move and
    comment."""
    ref = _queued(deployment, tracker)

    out = _act("card_edit", project="acme", issue=ref, title="Lock a reconciled statement",
               body="## Objective\n\nLock it\n\n## Acceptance criteria\n\n- it locks\n")

    assert out.ok, out.message
    again = tracker.get_ticket(ref)
    assert again.title == "Lock a reconciled statement"
    assert again.acceptance_criteria, "the corrected body did not reach the card"
    thread = tracker.comments(ref) or []
    assert any("edited the title and description" in c.body for c in thread), (
        "an edit that leaves no record is a rewrite of somebody else's text with nobody seeing")


def test_a_card_the_factory_has_TAKEN_UP_is_not_edited(deployment, tracker):
    """Roberto's rule, and the reason it is a rule: an agent works from the text it read at pickup,
    so an edit afterwards moves the target under it. The refusal names the column and says what to
    do instead."""
    from openfactory.contracts import JobState

    ref = _queued(deployment, tracker)
    tracker.set_state(ref, JobState.IMPLEMENTING)   # `_WORKING` → the `in_progress` column

    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nsomething else\n")

    assert not out.ok
    assert "In progress" in out.message and "comment" in out.message, out.message
    assert tracker.get_ticket(ref).objective == "Lock it", "the card was edited anyway"


def test_a_closed_card_is_off_the_board_and_NOT_delivered(deployment, tracker):
    """An operator closing a card means "this should not be on my board", never "this shipped" —
    and `triage.Ticket.delivered` reads exactly that word. Eleven cards closed as duplicates once
    came back downstream as completed work."""
    ref = _queued(deployment, tracker)

    out = _act("card_close", project="acme", issue=ref, reason="asked for this by mistake")

    assert out.ok, out.message
    assert tracker.get_ticket(ref).state == "closed"
    assert _closed_reason(deployment, ref) == "not_planned", (
        "a card an operator withdrew was recorded as delivered work")
    assert any("by mistake" in c.body for c in (tracker.comments(ref) or [])), (
        "the reason is what the next reader of the card has")


def test_a_closed_card_can_be_REOPENED_because_nothing_was_deleted(deployment, tracker):
    """The undo a close on the only surface an operator has must have. Card numbers are
    `MAX(ref) + 1` and the thread is keyed by the number, so deleting would hand this card's
    number to the next one."""
    ref = _queued(deployment, tracker)
    _act("card_close", project="acme", issue=ref, reason="withdrawn")

    out = _act("card_reopen", project="acme", issue=ref)

    assert out.ok, out.message
    assert tracker.get_ticket(ref).state == "open"
    assert _closed_reason(deployment, ref) == "", "it is open, and still says why it was closed"
    thread = [c.body for c in (tracker.comments(ref) or [])]
    assert any("withdrawn" in b for b in thread), "reopening erased the record of the close"


def _closed_reason(deployment, ref: str) -> str:
    from openfactory.adapters.board_db import connect
    from openfactory.contracts.refs import canonical_ref

    with connect() as conn:
        row = conn.execute("SELECT closed_reason FROM cards WHERE project = ? AND ref = ?",
                           (deployment.name, int(canonical_ref(ref)))).fetchone()
    return (row["closed_reason"] if row else "") or ""


def test_a_tracker_that_cannot_RENAME_refuses_by_name(deployment, tracker, monkeypatch):
    """`update_title` and `reopen_ticket` are NOT on the port — measured: adding them made the
    faithful double answer `isinstance=False` and `check_tracker` report the missing method instead
    of the read-side findings it exists for. So a row without them is refused by name, the way this
    axis already reaches `say`."""
    ref = _queued(deployment, tracker)
    monkeypatch.delattr(type(tracker), "update_title")

    out = _act("card_edit", project="acme", issue=ref, title="a new name")

    assert not out.ok
    assert "cannot rename" in out.message and "description" in out.message, out.message


def test_a_board_that_could_not_be_READ_refuses_the_edit(deployment, tracker, monkeypatch):
    """One of the two "cannot tell" cases, and it refuses. A board that did not answer cannot say
    whether the factory has the card, and letting an edit through on a card that may already be
    running is the direction this gate must not fail in."""
    from openfactory.adapters.board.local import LocalBoard

    ref = _queued(deployment, tracker)
    monkeypatch.setattr(LocalBoard, "columns", lambda self: None)

    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nnew\n")

    assert not out.ok
    assert "could not be read" in out.message and "Nothing was changed" in out.message, out.message
    assert tracker.get_ticket(ref).objective == "Lock it", "the card was edited anyway"


def test_a_column_the_platform_does_not_MAP_refuses_the_edit(deployment, tracker):
    """The other "cannot tell" case. A board may legitimately carry a column this platform knows
    nothing about; what it may not do is have the gate guess which side of the line it is on."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_db import connect

    ref = _queued(deployment, tracker)
    with connect(write=True) as conn:
        conn.execute("INSERT INTO columns(project, key, name, position) VALUES (?,?,?,?)",
                     ("acme", "parking", "Parking", 9))
    assert build_board(deployment).set_column(issue=ref, issue_url="", name="Parking")

    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nnew\n")

    assert not out.ok
    assert "Parking" in out.message and "`columns`" in out.message, out.message


def test_closing_without_a_REASON_is_refused_before_the_row_runs(deployment, tracker):
    """`reason` is in this row's `required`, and `perform` refuses a required parameter that is
    missing or empty — which is why the action itself carries no check for it (the mutation that
    removed one survived, so the code was dead)."""
    ref = _queued(deployment, tracker)

    out = _act("card_close", project="acme", issue=ref, reason="")

    assert not out.ok and "reason" in out.message, out.message
    assert tracker.get_ticket(ref).state == "open"


def test_the_note_on_the_card_is_in_the_PROJECTS_language(tmp_path, monkeypatch):
    """#160's rule, held over the notes this row writes: a sentence composed at the call site is
    how an English-configured client received Portuguese and a Portuguese-configured one received
    English, from code sitting beside a working per-language catalogue."""
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    # ITS OWN REGISTRY AND ITS OWN BOARD, as the `deployment` fixture above takes care to do.
    # Without these two lines this case registered `brasil` in whatever registry the environment
    # pointed at, so it passed once and failed on every run after — which is exactly what happened:
    # the full suite went red and two mutation plans REFUSED TO START, because a plan needs a green
    # baseline before it cuts anything.
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))

    registry = ProjectRegistry()
    registry.add(Project(name="brasil", repo_path=str(tmp_path), language="pt-BR",
                         tracker=ProviderRef(kind="local", repo="brasil", options={})))
    project = registry.get("brasil")
    LocalBoardSetup().create(project=project, owner="", title="brasil", token=None)
    tracker = build_tracker(project)
    ref = _queued(project, tracker)

    assert _act("card_edit", project="brasil", issue=ref, title="Novo título").ok

    thread = [c.body for c in (tracker.comments(ref) or [])]
    assert any("corrigiu" in b for b in thread), (
        f"the note reached a pt-BR project in English: {thread}")


# ── a card the product role opened is the product owner's (#150, decided 2026-09-16) ─────────────

def _opened_by_product(kind: str) -> str:
    """The body each of the product role's writers puts on a card — the real writers, not a copy."""
    from openfactory.product.authoring import defect_body, issue_body, ticket_body
    from openfactory.product.role import IssueDraft

    if kind == "requirement":
        draft = IssueDraft(title="Lock", objective="Lock a reconciled statement",
                           acceptance_criteria=["it locks"], cites=7)
        return issue_body(draft, requirement_path="requirements/0007-lock.md",
                          docs_repo="acme-context", requester="<@U0PO>")
    if kind == "request":
        return ticket_body(described="um relatório mensal", reported_by="<@U0PO>", source="chat")
    return defect_body(restated="o fecho não gera o pacote", reported_by="<@U0PO>",
                       severity="alta", source="chat", requirement=None,
                       requirement_path="requirements/0007-lock.md", docs_repo="acme-context")


def _in_backlog(deployment, tracker, body: str) -> str:
    from openfactory.adapters.board import build_board

    ref = tracker.create_ticket(title="Filed by the product role", body=body)
    build_board(deployment).set_column(issue=ref, issue_url="", name="Backlog")
    return ref


@pytest.mark.parametrize("kind", ["requirement", "request", "defect"])
def test_every_card_the_product_role_writes_is_recognised_as_its_own(kind):
    from openfactory.product.authoring import filed_by_the_product_role

    assert filed_by_the_product_role(_opened_by_product(kind)) == kind


@pytest.mark.parametrize("kind", ["requirement", "request", "defect"])
def test_a_card_the_product_role_opened_is_NOT_edited_from_the_board_in_any_column(
        deployment, tracker, kind):
    """Backlog, not In progress: the stage is not why this refuses. What somebody asked for is
    changed by the person who asked, through the product role — a requirement card would otherwise
    say one thing and the promise in the context repository another."""
    ref = _in_backlog(deployment, tracker, _opened_by_product(kind))
    before = tracker.get_ticket(ref)

    out = _act("card_edit", project="acme", issue=ref, title="renamed",
               body="## Objective\n\nsomething nobody asked for\n")

    assert not out.ok
    assert "opened by the product role" in out.message and "product owner" in out.message, (
        out.message)
    after = tracker.get_ticket(ref)
    assert (after.title, after.raw) == (before.title, before.raw), "the card was changed anyway"
    assert not (tracker.comments(ref) or []), "a refused edit left a note claiming a change"


def test_the_refusal_on_a_requirement_card_says_the_requirement_changes_first(deployment, tracker):
    ref = _in_backlog(deployment, tracker, _opened_by_product("requirement"))

    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nx\n")

    assert "changes the requirement first" in out.message, out.message


@pytest.mark.parametrize("kind", ["requirement", "request", "defect"])
def test_a_card_the_product_role_opened_is_NOT_closed_or_reopened_from_the_board(
        deployment, tracker, kind):
    """Closing kills what somebody asked for as surely as editing changes it; reopening brings back
    what the product owner closed."""
    ref = _in_backlog(deployment, tracker, _opened_by_product(kind))

    closed = _act("card_close", project="acme", issue=ref, reason="not needed")
    assert not closed.ok and "only the product owner closes it" in closed.message, closed.message
    assert tracker.get_ticket(ref).state == "open"

    tracker.close_ticket(ref, "closed by the product owner")
    reopened = _act("card_reopen", project="acme", issue=ref)
    assert not reopened.ok and "only the product owner reopens it" in reopened.message, (
        reopened.message)
    assert tracker.get_ticket(ref).state == "closed"


def test_a_board_card_that_merely_QUOTES_a_marker_is_still_the_boards(deployment, tracker):
    """The marker is a whole line the writer composed. A person quoting it in a sentence wrote a
    card on the board, and that card stays correctable until pickup."""
    ref = _queued(deployment, tracker, body=(
        "## Objective\n\nThe old card said: Nothing in this issue may go beyond that requirement.\n"
        "Our template has a **Tipo:** defeito field too.\n"))

    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nclearer\n")

    assert out.ok, out.message


def test_a_card_that_could_not_be_READ_is_not_changed_blind(deployment, tracker, monkeypatch):
    """Whether the product role opened it is the question, and an answer nobody could read refuses —
    the same direction `_stage_refusal` fails in for a board it cannot read."""
    ref = _queued(deployment, tracker)

    def unreadable(self, ref):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(type(tracker), "get_ticket", unreadable)
    out = _act("card_edit", project="acme", issue=ref, body="## Objective\n\nx\n")

    assert not out.ok and "could not be read" in out.message, out.message


def test_the_drawer_offers_no_button_the_row_would_refuse(deployment, tracker):
    from openfactory.api.app import _card_detail

    theirs = _in_backlog(deployment, tracker, _opened_by_product("request"))
    ours = _queued(deployment, tracker)

    assert _card_detail(tracker, theirs)["opened_by_product"] == "request"
    assert _card_detail(tracker, ours)["opened_by_product"] == ""
    drawer = PANEL.split("function paintCard(){")[1].split("\nfunction ")[0]
    guard = drawer.index("c.opened_by_product")
    assert guard < drawer.index("boardEditCard()") and guard < drawer.index("boardCardClose()"), (
        "the drawer offers edit or close before asking who opened the card")

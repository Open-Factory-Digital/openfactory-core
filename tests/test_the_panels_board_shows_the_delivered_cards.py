"""The panel's board shows the cards the factory delivered in Done (#500, #195).

THE TWO HALVES OF ONE COLUMN DISAGREED. `/api/board` listed `tracker.list_tickets(state="open")`
and nothing else, and every row closes a card it delivers: GitHub since #180, the local board since
#500. So Done was empty on every row but for the moment between the move and the close — and #195
had kept the local board's delivered cards OPEN precisely so this page would show them, which is
what left their requesters untold (#500). The page now reads the recent cards closed as delivered
back into the board's own Done column.

WHAT IS HELD, on the real local board through the real route (`app.board_view`):

  · a card the factory finished is in Done, shaped like every other card, and opens on a closed
    card's controls;
  · a card closed as NOT delivered stays off the board, as it always has;
  · the read is bounded — the most recent `DELIVERED_SHOWN_AT_MOST`, within
    `DELIVERED_SHOWN_DAYS`;
  · Done is the board's OWN name for the stage, never the platform's literal (C-14), and one the
    board HAS — the row's map, then a real column of the board, else nowhere;
  · a closed read that failed leaves the open cards standing — never an unreadable board;
  · a person dragging a delivered card out of Done reopens it, through the same `card_move`, and a
    card dragged INTO Done stays the open card it was.

THE GITHUB ROW IS NOT DRIVEN HERE: no neighbour drives `/api/board` over a faked `gh`, and the
rule this adds compares no provider kind — the closed read is the port's `list_tickets`, and the
column is the row's own `stage_column` and `stage_key`, held for every row by
`test_the_product_role_moves_cards_by_key.py` and
`test_the_board_row_says_which_stage_its_column_is.py`.
"""

from __future__ import annotations

import json
import logging

import pytest

from openfactory.contracts import JobState


def _deployment(tmp_path, monkeypatch, options: dict | None = None):
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="acme", options=options or {})))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    return project


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project whose board `project init` has already created."""
    return _deployment(tmp_path, monkeypatch)


@pytest.fixture
def tracker(deployment):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(deployment)


def _board(**kw) -> dict:
    from openfactory.api.app import board_view

    return board_view("acme", **kw)


def _where(got: dict) -> dict[str, str]:
    return {c["ref"]: c["column"] for c in got["cards"]}


def _queued(deployment, tracker, title: str) -> str:
    from openfactory.adapters.board import build_board

    ref = tracker.create_ticket(title=title, body="## Objective\n\nDo it\n").lstrip("#")
    assert build_board(deployment).set_column(issue=ref, issue_url="", name="TO-DO")
    return ref


def _finished(deployment, tracker, title: str) -> str:
    """A card whose job ended Done — the tracker's `set_state`, as `settle_ticket` calls it."""
    ref = _queued(deployment, tracker, title)
    assert tracker.set_state(ref, JobState.PR_OPEN)
    assert tracker.set_state(ref, JobState.DONE)
    assert tracker.get_ticket(ref).state == "closed"
    return ref


def _stamp(deployment, ref: str, updated_at: str) -> None:
    from openfactory.adapters.board_db import connect

    with connect(write=True) as conn:
        conn.execute("UPDATE cards SET updated_at = ? WHERE project = ? AND ref = ?",
                     (updated_at, deployment.name, int(ref)))


def _days_ago(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _act(name: str, **params):
    import asyncio

    from openfactory import actions

    who = actions.Actor(id="me", display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=who, **params))


# ── 1. what the factory delivered is in Done ────────────────────────────────────────────────────

def test_a_card_the_factory_finished_is_in_Done(deployment, tracker):
    waiting = _queued(deployment, tracker, "Still to do")
    shipped = _finished(deployment, tracker, "Shipped")

    got = _board()

    assert _where(got) == {waiting: "TO-DO", shipped: "Done"}
    assert "Done" in got["columns"]


def test_it_is_drawn_like_every_other_card(deployment, tracker):
    """The page groups cards by `column` and draws each from the same five fields; a delivered card
    carrying a field the others do not would be a card the page treats differently."""
    _queued(deployment, tracker, "Still to do")
    _finished(deployment, tracker, "Shipped")

    shapes = {frozenset(c) for c in _board()["cards"]}

    assert shapes == {frozenset({"ref", "column", "title", "labels", "updated_at"})}


def test_opened_it_offers_what_a_closed_card_offers(deployment, tracker):
    """The drawer reads the card's state, so a delivered card offers Reopen, not Close."""
    shipped = _finished(deployment, tracker, "Shipped")

    detail = _board(card=shipped)["card"]

    assert detail["readable"] and detail["state"] == "closed"


def test_a_delivered_card_the_board_places_is_drawn_where_the_board_says(deployment, tracker,
                                                                         monkeypatch):
    """A GitHub project keeps its closed items in their Status: an issue closed while its move to
    Done failed is drawn where its board has it, as every card on this page is — Done is where a
    delivered card goes when the board places it nowhere."""
    from openfactory.adapters.board.local import LocalBoard

    shipped = _finished(deployment, tracker, "Shipped")
    monkeypatch.setattr(LocalBoard, "columns", lambda self: {shipped: "In review"})

    assert _where(_board()) == {shipped: "In review"}


def test_a_card_closed_as_NOT_delivered_is_not_on_the_board(deployment, tracker):
    withdrawn = _queued(deployment, tracker, "Asked for by mistake")
    tracker.close_ticket(withdrawn, "asked for by mistake", delivered=False)
    shipped = _finished(deployment, tracker, "Shipped")

    assert _where(_board()) == {shipped: "Done"}


# ── 2. bounded ──────────────────────────────────────────────────────────────────────────────────

def test_only_the_most_recent_delivered_cards_are_read(deployment, tracker):
    from datetime import UTC, datetime, timedelta

    from openfactory.api.app import DELIVERED_SHOWN_AT_MOST

    refs = [_finished(deployment, tracker, f"Shipped {n}")
            for n in range(DELIVERED_SHOWN_AT_MOST + 3)]
    # A MINUTE APART, newest last — and the oldest stamped first, so the order is the stamps' and
    # not the numbers'
    now = datetime.now(UTC)
    for minutes, ref in enumerate(reversed(refs)):
        _stamp(deployment, ref, (now - timedelta(minutes=minutes)).isoformat())

    shown = set(_where(_board()))

    assert len(shown) == DELIVERED_SHOWN_AT_MOST
    assert shown == set(refs[-DELIVERED_SHOWN_AT_MOST:]), "not the most recent ones"


def test_a_card_delivered_longer_ago_than_the_window_is_not_read_back(deployment, tracker):
    from openfactory.api.app import DELIVERED_SHOWN_DAYS

    old = _finished(deployment, tracker, "Shipped long ago")
    recent = _finished(deployment, tracker, "Shipped this sprint")
    _stamp(deployment, old, _days_ago(DELIVERED_SHOWN_DAYS + 1))
    _stamp(deployment, recent, _days_ago(DELIVERED_SHOWN_DAYS - 1))

    assert _where(_board()) == {recent: "Done"}


# ── 3. the board's own name for Done ────────────────────────────────────────────────────────────

def test_a_RENAMED_done_column_is_the_one_used(tmp_path, monkeypatch):
    """C-14: a board that says `Concluído` is drawn with `Concluído`, and a card placed in `Done`
    there would be placed in a column the page does not draw."""
    from openfactory.adapters.tracker.registry import build_tracker

    project = _deployment(tmp_path, monkeypatch,
                          {"columns": json.dumps({"done": "Concluído"})})
    tracker = build_tracker(project)
    shipped = _finished(project, tracker, "Entregue")

    got = _board()

    assert "Concluído" in got["columns"] and "Done" not in got["columns"]
    assert _where(got) == {shipped: "Concluído"}


def test_a_board_that_has_no_Done_column_shows_no_delivered_card(deployment, tracker):
    """Nowhere to show it is not a column to invent: the card is left off, never placed by the
    platform's literal on a board that does not draw it — though the row's map, which answers the
    platform's word for a stage nobody renamed, still says `Done` (review of #505/#506)."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_db import connect

    _finished(deployment, tracker, "Shipped")
    with connect(write=True) as conn:
        conn.execute("DELETE FROM columns WHERE project = ? AND key = 'done'", (deployment.name,))
    board = build_board(deployment)
    assert "Done" not in board.column_names() and board.stage_column("done") == "Done"

    assert _board()["cards"] == []


def test_a_Done_the_map_names_that_the_board_does_not_have_is_not_drawn(deployment, tracker,
                                                                         monkeypatch):
    """THE MAP IS BELIEVED FOR A COLUMN THE BOARD HAS (review of #505/#506). A name a deployment
    declared for `done` that is none of the board's columns is a card the page never draws, so the
    board's own column for that stage is the one used."""
    from openfactory.adapters.board.local import LocalBoard

    shipped = _finished(deployment, tracker, "Shipped")
    monkeypatch.setattr(LocalBoard, "stage_column",
                        lambda self, key: "Finalizado" if key == "done" else "")

    got = _board()

    assert "Finalizado" not in got["columns"]
    assert _where(got) == {shipped: "Done"}


def test_a_board_whose_map_is_silent_is_read_off_its_own_columns(tmp_path, monkeypatch):
    """THE MIDDLE LAYER: a row that declares no map still knows which stage each of its columns is,
    so a renamed Done is found among the board's own columns — never the platform's `Done`."""
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.registry import build_tracker

    project = _deployment(tmp_path, monkeypatch,
                          {"columns": json.dumps({"done": "Concluído"})})
    tracker = build_tracker(project)
    shipped = _finished(project, tracker, "Entregue")
    monkeypatch.setattr(LocalBoard, "stage_column", lambda self, key: "")

    assert _where(_board()) == {shipped: "Concluído"}


# ── 4. a closed read that failed is not an unreadable board ─────────────────────────────────────

@pytest.mark.parametrize("failure", ["unread", "raised"])
def test_a_failed_read_of_the_closed_cards_still_shows_the_open_ones(deployment, tracker,
                                                                     monkeypatch, caplog,
                                                                     failure):
    from openfactory.adapters.tracker.local import LocalTracker

    waiting = _queued(deployment, tracker, "Still to do")
    _finished(deployment, tracker, "Shipped")
    real = LocalTracker.list_tickets

    def _closed_unread(self, *, state="all", **kw):
        if state == "closed":
            if failure == "raised":
                raise RuntimeError("the file is locked")
            return None
        return real(self, state=state, **kw)

    monkeypatch.setattr(LocalTracker, "list_tickets", _closed_unread)

    with caplog.at_level(logging.WARNING):
        got = _board()

    assert got["cards"] is not None, "a closed read that failed made the whole board unreadable"
    assert _where(got) == {waiting: "TO-DO"}
    assert "OPENFACTORY_BOARD_DELIVERED_UNREAD" in caplog.text


def test_an_unreadable_board_is_still_unreadable(deployment, tracker, monkeypatch):
    """The closed read adds to an answer; it never turns `None` into one."""
    from openfactory.adapters.board.local import LocalBoard

    _finished(deployment, tracker, "Shipped")
    monkeypatch.setattr(LocalBoard, "columns", lambda self: None)

    assert _board()["cards"] is None


# ── 5. moving a delivered card ──────────────────────────────────────────────────────────────────

def test_a_delivered_card_dragged_out_of_Done_is_refused_by_its_door(deployment, tracker):
    """The page's drag is the catalogue's `card_move` (`boardMove`), and a person's move goes
    through the card's door (#414): a delivered card is not queued from Done by a drag — it is
    reopened, which is the door's own act (`reopened`). The drag changes nothing, and the card is
    still drawn in Done as delivered work."""
    from openfactory.adapters.board import build_board

    shipped = _finished(deployment, tracker, "Shipped")

    out = _act("card_move", project="acme", issue=shipped, column="TO-DO")

    assert not out.ok and "delivered" in out.message, out.message
    assert tracker.get_ticket(shipped).state == "closed"
    assert _where(_board()) == {shipped: "Done"}
    assert build_board(deployment).items_in_status("TO-DO") == []

    # THE BOARD'S OWN MOVE, which the door's effects use, keeps the tracker's rule: leaving Done
    # opens a delivered card, in the column it was put in, never closed in a column it claims
    board = build_board(deployment)
    assert board.set_column(issue=shipped, issue_url="", name="TO-DO")
    assert tracker.get_ticket(shipped).state == "open"
    assert _where(_board()) == {shipped: "TO-DO"}


def test_a_withdrawn_card_moved_on_the_board_stays_withdrawn(deployment, tracker):
    from openfactory.adapters.board import build_board

    withdrawn = _queued(deployment, tracker, "Asked for by mistake")
    tracker.close_ticket(withdrawn, "asked for by mistake", delivered=False)

    assert build_board(deployment).set_column(issue=withdrawn, issue_url="", name="TO-DO")

    assert tracker.get_ticket(withdrawn).state == "closed"
    assert _board()["cards"] == []


def test_a_card_dragged_INTO_Done_is_refused_by_its_door(deployment, tracker):
    """Recording a delivery is the close's (`card_close`, which the door comments on), not a
    drag's: Done is the factory's column, and a person's move into it is refused by the card's
    door (#414). The card stays open and queued, and is drawn once, where it was."""
    waiting = _queued(deployment, tracker, "Done by hand")

    out = _act("card_move", project="acme", issue=waiting, column="Done")

    assert not out.ok and "factory's column" in out.message, out.message
    assert tracker.get_ticket(waiting).state == "open"
    assert [c["ref"] for c in _board()["cards"]] == [waiting]
    assert _where(_board()) == {waiting: "TO-DO"}

    # THE BOARD'S OWN MOVE into Done records no delivery either: that is the close's, which the
    # door comments on — the card stays open, drawn once, in Done
    from openfactory.adapters.board import build_board

    assert build_board(deployment).set_column(issue=waiting, issue_url="", name="Done")
    assert tracker.get_ticket(waiting).state == "open"
    assert [c["ref"] for c in _board()["cards"]] == [waiting]
    assert _where(_board()) == {waiting: "Done"}

"""A queue a person confirmed is the queue the factory runs, first card first (#512).

THE ROLE SAID "A FÁBRICA COMEÇA PELO PRIMEIRO" AND NOTHING MADE IT TRUE. `promote` moved the
approved cards into the queue in the sequence approved, and #497 made the reply name them in it —
but the poller pulls the queue in BOARD order, and no board was told the order:

  · the local board served its queue by card number (`ORDER BY c.ref`, an INTEGER column, so
    numerically — #9 before #10, and #3 before #9 whatever was approved);
  · on Jira a card keeps its rank when it changes status, so the queue came back in whatever rank
    the backlog already gave it.

So a queue confirmed as #3, #1 started on #1, under a reply saying the factory starts with #3.

NOW THE QUEUE IS RANKED IN THE ORDER APPROVED, through `Rankable.place_after` on the module's own
watched board — a board write, not a card's transition, as #511's reorder writes the backlog's —
the first card at the top of the queue and each next one after it. The local board ranks by a
position in the column (`board_db`), and serves its queue in it. A board that keeps no order this
platform can write is said to, in the reply, for that board only; a rank the board refused is said
to have not landed, and the team is told.

WHAT IS DRIVEN HERE. The yes itself, `confirm.confirm`, with the product role's real pen:

  · on the local row, building its own board, over a queue confirmed as #3, #1 while #4 already
    waited in the queue — then the poller's own read, `activities.scan_todo` (the workflow takes
    `issues[:slots]` of it), and `openfactory poll`, the one-machine scheduler, whose first job is
    the first card approved;
  · the panel's board route draws that queue in the same order — a person sees as first the card
    the poller picks — and a hosted row's columns in the order the row returns, sorted by nothing
    of the panel's own;
  · on the Jira row, with the transport faked at `urllib.request.urlopen` by a site that ranks as
    Jira does (`test_a_queue_on_jira_says_what_it_queued._Site`), a queue confirmed as DAR-11,
    DAR-9 is read back by the board in that order — and a rank the site would not take is said;
  · a board that keeps no order says so, in pt-BR and in en;
  · and the local board's own order: a card joins its column at the bottom, a move to where it is
    keeps its place, a card or an anchor outside the column is refused, and a board file from
    before the position existed gains it without losing its cards.
"""

from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from openfactory.product import module as product_module
from openfactory.product import staging
from openfactory.product.confirm import confirm
from openfactory.product.module import _IMP_WRITE
from tests.test_a_queue_on_jira_says_what_it_queued import (
    BACKLOG,
    QUEUE,
    _memory,
    _pen,
    _Site,
)

ANA = "ana-requester-77"
ROOM, AGENT = "acme", "Nina"


@pytest.fixture(autouse=True)
def _clean():
    staging._PENDING.clear()
    yield
    staging._PENDING.clear()


@pytest.fixture
def told(monkeypatch) -> list[tuple[str, bool]]:
    """What the module's watched board reported to the factory's board about its writes."""
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(product_module, "_tell_the_factory",
                        lambda project, cause, detail, *, ok: seen.append((detail, ok))
                        if cause == _IMP_WRITE else None)
    return seen


def _yes(project, module, numbers: list[str], *, lang: str = "pt-BR") -> str:
    """The queue `numbers` is staged for Ana, as the proposal stages it, and Ana says yes."""
    staging.remember(ROOM, {"kind": "queue", "channel": ROOM, "numbers": list(numbers)},
                     lang=lang, project=project, person=ANA)
    key, waiting = staging.find_waiting(ROOM, ROOM, project=project, person=ANA)
    assert waiting is not None and waiting["kind"] == "queue", "nothing is staged"
    return confirm(project, key=key, entry=waiting, module=module, user=ANA, lang=lang)


# ── the local row ────────────────────────────────────────────────────────────────────────────────

def _local(monkeypatch, tmp_path, *, lang: str = "pt-BR"):
    """A registered project on the local row, its board created, #1–#3 filed in its Backlog and #4
    already waiting in the queue — a card somebody queued before this yes."""
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    _memory(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    registry = ProjectRegistry()
    registry.add(Project(name=ROOM, repo_path=str(tmp_path), language=lang,
                         tracker=ProviderRef(kind="local", repo=ROOM, options={}),
                         product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                               agent_name=AGENT)))
    project = registry.get(ROOM)
    LocalBoardSetup().create(project=project, owner="", title=ROOM, token=None)
    tracker = build_tracker(project)
    cards = [tracker.create_ticket(title=t, body="x") for t in ("Um", "Dois", "Três", "Quatro")]
    assert cards == ["#1", "#2", "#3", "#4"]
    board = build_board(project)
    assert board.set_column(issue="4", issue_url="", name=QUEUE) is True
    return project, board


@pytest.fixture
def local(monkeypatch, tmp_path):
    return _local(monkeypatch, tmp_path)


def test_a_queue_confirmed_out_of_number_order_is_the_queue_the_board_serves(local, tmp_path,
                                                                             told):
    project, board = local

    said = _yes(project, _pen(project, tmp_path), ["3", "1"])

    assert said == ("Nina: Coloquei na fila, nesta ordem: #3, #1. "
                    "A fábrica começa pelo primeiro."), said
    # THE FIRST APPROVED AT THE TOP, ahead of the card queued before this yes
    assert board.items_in_status(QUEUE) == ["3", "1", "4"]
    # and the rank went through the module's watched board, like every write it makes
    assert told.count(("place_after", True)) == 2, told


def test_the_poller_picks_up_the_first_card_approved(local, tmp_path, monkeypatch):
    """`scan_todo` is the poller's read of the queue, and the workflow starts `issues[:slots]` of
    what it answers — a floor of one starts the first."""
    import openfactory.runtime.temporal.activities as acts
    from openfactory.runtime.temporal.io import ScanInput

    project, _board = local
    _yes(project, _pen(project, tmp_path), ["3", "1"])
    # A WORKTREE BOX HAS NOTHING TO PROVE (ADR-0037 D5), so no proof gates this pickup
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")

    issues = asyncio.run(acts.scan_todo(ScanInput(project=ROOM, board_owner="", board_number="",
                                                  pickup_status=QUEUE)))

    assert issues == ["3", "1", "4"], issues
    assert issues[:1] == ["3"]


def test_openfactory_poll_drives_the_first_card_approved_first(local, tmp_path, monkeypatch):
    """`poll` is the one-machine deployment's scheduler: it drives the queue one card at a time, in
    the order the board serves it, and stops when one pauses."""
    from openfactory import cli
    from openfactory.contracts import JobState
    from tests.one_machine import cli as run

    project, _board = local
    _yes(project, _pen(project, tmp_path), ["3", "1"])
    driven: list[str] = []

    def _drive_one(view, issue, **_kw):
        driven.append(issue)
        return SimpleNamespace(state=JobState.PAUSED, note="stopped here by the test")

    monkeypatch.setattr(cli, "_drive_one", _drive_one)

    code, out = run("poll", ROOM, "--sandbox", "worktree")

    assert code == 0, out
    assert driven == ["3"], (driven, out)


# ── what a person sees: the panel's board ───────────────────────────────────────────────────────

def test_the_panel_draws_the_queue_in_the_order_the_poller_picks_it_up(local, tmp_path,
                                                                        monkeypatch):
    """The panel's board route is what a person looks at, and the page draws each column in the
    order its cards come. The tracker lists the most recently updated card first, so the queue
    confirmed as #3, #1 was drawn #1, #3, #4 while the poller picked #3. Drawn now in the board's
    own order, the order `items_in_status` serves."""
    import openfactory.runtime.temporal.activities as acts
    from openfactory.api.app import board_view
    from openfactory.runtime.temporal.io import ScanInput

    project, _board = local
    _yes(project, _pen(project, tmp_path), ["3", "1"])
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")

    drawn = [c["ref"] for c in board_view(ROOM)["cards"] if c["column"] == QUEUE]
    picked = asyncio.run(acts.scan_todo(ScanInput(project=ROOM, board_owner="", board_number="",
                                                  pickup_status=QUEUE)))

    assert drawn == ["3", "1", "4"], drawn
    assert drawn == picked and picked[:1] == ["3"], (drawn, picked)
    # and the Backlog left behind, in its own order
    assert [c["ref"] for c in board_view(ROOM)["cards"] if c["column"] == BACKLOG] == ["2"]


class _RankedElsewhere:
    """A hosted row's board, as the panel reaches it: its own order, which is neither by number
    nor by update — DAR-12 above DAR-9 above DAR-11."""

    def column_names(self) -> list[str]:
        return [BACKLOG, QUEUE]

    def columns(self) -> dict[str, str]:
        return {"DAR-12": QUEUE, "DAR-9": QUEUE, "DAR-11": QUEUE}


class _UpdatedFirst:
    """Its tracker, which lists the most recently updated card first."""

    def list_tickets(self, *, state: str = "open", **_kw):
        from openfactory.adapters.tracker.base import TicketSummary

        if state != "open":
            return []
        return [TicketSummary(ref=ref, title=ref) for ref in ("DAR-11", "DAR-9", "DAR-12")]


def test_a_hosted_row_is_drawn_in_the_order_it_returns_with_no_sort_of_the_panels(local,
                                                                                 monkeypatch):
    """The panel follows the board's answer and sorts by nothing of its own: not by number
    (DAR-9, DAR-11, DAR-12), not as strings (DAR-11, DAR-12, DAR-9), not by update."""
    import openfactory.adapters.board as board_package
    import openfactory.adapters.tracker.registry as tracker_registry
    from openfactory.api.app import board_view

    monkeypatch.setattr(board_package, "build_board", lambda *_a, **_k: _RankedElsewhere())
    monkeypatch.setattr(tracker_registry, "build_tracker", lambda *_a, **_k: _UpdatedFirst())

    assert [c["ref"] for c in board_view(ROOM)["cards"]] == ["DAR-12", "DAR-9", "DAR-11"]


# ── the Jira row ─────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def jira(monkeypatch, tmp_path):
    """A Jira project as the registry holds one: DAR-9, DAR-10 and DAR-11 in its Backlog, ranked in
    that order, and DAR-12 already in the queue below them — and the pen holding the row's real
    tracker and board."""
    import json

    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    _memory(monkeypatch, tmp_path)
    site = _Site("DAR-9", "DAR-10", "DAR-11", "DAR-12")
    site.status["DAR-12"] = QUEUE
    monkeypatch.setattr("urllib.request.urlopen", site.urlopen)
    options = {"site": "https://acme-team.atlassian.net", "email": "alice@acme.ai",
               "status_map": json.dumps({"todo": QUEUE, "in_progress": "Em andamento",
                                         "done": "Concluído"})}
    project = Project(name=ROOM, repo_path=str(tmp_path), language="pt-BR",
                      tracker=ProviderRef(kind="jira", repo="DAR", options=options),
                      product=ProductConfig(docs_repo="acme/acme-docs", admins=[ANA],
                                            agent_name=AGENT))
    tracker, board = build_tracker(project, token="t"), build_board(project, token="t")
    return project, site, board, _pen(project, tmp_path, tracker=tracker, board=board)


def test_a_queue_confirmed_on_jira_is_ranked_in_the_order_approved(jira, told):
    project, site, board, module = jira
    assert board.items_in_status(QUEUE) == ["DAR-12"]

    said = _yes(project, module, ["DAR-11", "DAR-9"])

    assert said == ("Nina: Coloquei na fila, nesta ordem: DAR-11, DAR-9. "
                    "A fábrica começa pelo primeiro."), said
    # WHAT THE POLLER READS: the queue, in the site's own rank
    assert board.items_in_status(QUEUE) == ["DAR-11", "DAR-9", "DAR-12"]
    assert site.status["DAR-10"] == BACKLOG, "a card nobody approved was moved"
    assert told.count(("place_after", True)) == 2, told


def test_a_rank_the_site_would_not_take_is_said_and_the_rest_follow_the_last_placed(jira, told):
    """The cards went in; one card's place did not. The reply does not promise the order, the
    watched board reported the refused write to the factory's board — and the card after the
    refused one still follows the last card that WAS placed, not one whose place is unknown."""
    project, site, board, module = jira
    ranked = site._ranked

    def _refuses_dar_9(method, path, payload):
        if payload["issues"] == ["DAR-9"]:
            raise OSError("the agile API would not rank DAR-9")
        return ranked(method, path, payload)

    site._ranked = _refuses_dar_9

    said = _yes(project, module, ["DAR-11", "DAR-9", "DAR-10"])

    assert said == ("Nina: Coloquei na fila: DAR-11, DAR-9, DAR-10, mas não consegui gravar essa "
                    "ordem no quadro — a fábrica os pega na ordem do próprio quadro. O time foi "
                    "avisado e resolve."), said
    assert board.items_in_status(QUEUE) == ["DAR-11", "DAR-10", "DAR-9", "DAR-12"]
    assert ("place_after recusou a escrita", False) in told, told


# ── a board that keeps no order this platform can write ──────────────────────────────────────────

class _KeepsNoOrder:
    """The local board with its rank taken away — a client's own adapter that reads and moves
    cards and has no `place_after`, so it does not claim `Rankable`."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def url(self) -> str:
        return self._inner.url()

    def columns(self):
        return self._inner.columns()

    def column_names(self):
        return self._inner.column_names()

    def pickup_column(self) -> str:
        return self._inner.pickup_column()

    def items_in_status(self, status: str) -> list[str]:
        return self._inner.items_in_status(status)

    def add_item(self, *, issue_url: str) -> None:
        self._inner.add_item(issue_url=issue_url)

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        return self._inner.set_column(issue=issue, issue_url=issue_url, name=name)

    def set_status(self, *, issue: str, issue_url: str, state, needs_person=None) -> bool:
        return self._inner.set_status(issue=issue, issue_url=issue_url, state=state,
                                      needs_person=needs_person)


@pytest.mark.parametrize(("lang", "expected"), [
    ("pt-BR", "Nina: Coloquei na fila: #3, #1. Este quadro não aceita uma ordem gravada daqui, "
              "então a fábrica os pega na ordem do próprio quadro."),
    ("en", "Nina: Queued: #3, #1. This board does not take an order from here, so the factory "
           "takes them in the board's own order."),
])
def test_a_board_that_keeps_no_order_is_said_to_for_that_board_only(monkeypatch, tmp_path, told,
                                                                    lang, expected):
    project, board = _local(monkeypatch, tmp_path, lang=lang)

    said = _yes(project, _pen(project, tmp_path, board=_KeepsNoOrder(board)), ["3", "1"],
                lang=lang)

    assert said == expected, said
    assert set(board.items_in_status(QUEUE)) == {"1", "3", "4"}, "the cards were not queued"
    assert not [d for d, _ in told if d.startswith("place_after")], told


# ── the local board's own order ──────────────────────────────────────────────────────────────────

@pytest.fixture
def rows(monkeypatch, tmp_path):
    """A local board with #1–#3 filed in its Backlog, and the file it lives in."""
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.local import LocalTracker

    db = tmp_path / "board.db"
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(db))
    project = SimpleNamespace(name="acme", tracker=SimpleNamespace(kind="local", repo="acme",
                                                                   options={}))
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    tracker = LocalTracker("acme", db_path=db)
    assert [tracker.create_ticket(title=t, body="") for t in ("um", "dois", "três")] == [
        "#1", "#2", "#3"]
    return tracker, LocalBoard(tracker), db


def test_a_card_joins_its_column_at_the_bottom_whoever_moves_it(rows):
    from openfactory.contracts import JobState

    tracker, board, _db = rows
    assert board.set_column(issue="3", issue_url="", name=QUEUE) is True      # a person
    assert tracker.set_state("1", JobState.TODO) is not False                  # the factory
    assert board.set_column(issue="2", issue_url="", name=QUEUE) is True
    assert board.items_in_status(QUEUE) == ["3", "1", "2"]
    # A MOVE TO WHERE IT IS CHANGES NOTHING — the first card stays first
    assert board.set_column(issue="3", issue_url="", name=QUEUE) is True
    assert board.items_in_status(QUEUE) == ["3", "1", "2"]
    # out and back in: it joins at the bottom again
    assert board.set_column(issue="3", issue_url="", name=BACKLOG) is True
    assert board.set_column(issue="3", issue_url="", name=QUEUE) is True
    assert board.items_in_status(QUEUE) == ["1", "2", "3"]


def test_a_card_is_placed_after_its_anchor_and_the_top_is_after_nothing(rows):
    _tracker, board, _db = rows
    assert board.items_in_status(BACKLOG) == ["1", "2", "3"]
    assert board.place_after(issue="3", issue_url="", after=None, column=BACKLOG) is True
    assert board.items_in_status(BACKLOG) == ["3", "1", "2"]
    assert board.place_after(issue="#1", issue_url="", after="#2", column=BACKLOG) is True
    assert board.items_in_status(BACKLOG) == ["3", "2", "1"]


@pytest.mark.parametrize(("issue", "after", "column"), [
    ("3", None, QUEUE),          # the card is not in the column
    ("3", "9", BACKLOG),         # its anchor is on no column
    ("3", None, "Parking"),      # the board has no such column
    ("CONT-3", None, BACKLOG),   # not a card of this board
])
def test_a_place_outside_the_column_is_refused_and_nothing_moves(rows, issue, after, column):
    _tracker, board, _db = rows
    assert board.place_after(issue=issue, issue_url="", after=after, column=column) is False
    assert board.items_in_status(BACKLOG) == ["1", "2", "3"]


def test_a_board_file_from_before_the_position_gains_it_and_keeps_its_cards(tmp_path,
                                                                            monkeypatch):
    """A running deployment's `board.db` has no `position`: opening it adds the column, its cards
    tie and keep the order they were served in, and a card that enters the column afterwards joins
    it below them."""
    from openfactory.adapters.board.local import LocalBoard
    from openfactory.adapters.tracker.local import LocalTracker

    db = tmp_path / "board.db"
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(db))
    old = sqlite3.connect(db)
    old.executescript("""
        CREATE TABLE cards (project TEXT NOT NULL, ref INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'open', closed_reason TEXT NOT NULL DEFAULT '',
            column_key TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
            requester TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY (project, ref));
        CREATE TABLE columns (project TEXT NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL,
            position INTEGER NOT NULL, PRIMARY KEY (project, key));
        INSERT INTO columns VALUES ('acme', 'backlog', 'Backlog', 0), ('acme', 'todo', 'TO-DO', 1);
        INSERT INTO cards (project, ref, column_key, created_at, updated_at) VALUES
            ('acme', 10, 'todo', 'then', 'then'), ('acme', 9, 'todo', 'then', 'then'),
            ('acme', 11, 'backlog', 'then', 'then');
    """)
    old.commit()
    old.close()
    board = LocalBoard(LocalTracker("acme", db_path=db))

    assert board.items_in_status(QUEUE) == ["9", "10"]
    assert board.set_column(issue="11", issue_url="", name=QUEUE) is True
    assert board.items_in_status(QUEUE) == ["9", "10", "11"]
    assert board.place_after(issue="11", issue_url="", after=None, column=QUEUE) is True
    assert board.items_in_status(QUEUE) == ["11", "9", "10"]

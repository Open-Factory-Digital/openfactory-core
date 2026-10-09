"""The board a reader sees is the board on disk, whichever process wrote it (#393).

Measured live on 0.4.1: a person removed a card through the panel, and the product role — running
in the worker — went on describing it as open in Backlog for three turns and a re-read request.
`product/board.py` kept a per-PROCESS snapshot and trusted it for six hours, refreshed only by
`list_tickets(updated_since=…)`; `forget_board` ran in the panel and never reached the worker. The
snapshot exists for a rate-limited hosted API, and a whole read of a 300-card `board.db` is 2.9 ms.

WHAT IS PINNED HERE IS AGREEMENT, NOT A LIST OF SYMPTOMS. Two `LocalTracker` instances on one file
stand in for two processes: the reader's snapshot is primed, the other instance writes — without
anybody calling `forget_board`, because the other process cannot — and the reader's next read must
EQUAL a fresh whole read. Every writer of both local rows is driven, and the list of writers is
derived from the classes, so the next writer somebody adds fails here until it is driven too.

And the other half, because the snapshot is right where reads cost something: a row that does not
declare its whole read cheap keeps the sweep-once-then-incremental read exactly as it was.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from unittest.mock import MagicMock

import pytest

from openfactory.adapters.board.base import Watchable
from openfactory.adapters.board.local import LocalBoard
from openfactory.adapters.board_setup.local import LocalBoardSetup
from openfactory.adapters.tracker.base import TicketSummary, whole_read_is_cheap
from openfactory.adapters.tracker.local import LocalTracker
from openfactory.contracts import JobState
from openfactory.product import board


@pytest.fixture(autouse=True)
def _clean():
    board.forget_board()
    yield
    board.forget_board()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "board.db"


@pytest.fixture
def project(db):
    return type("P", (), {
        "name": "acme", "forge": None,
        "tracker": type("T", (), {"kind": "local", "repo": "acme",
                                  "options": {"board_db": str(db)}})(),
    })()


@pytest.fixture
def cards(db, project):
    """Three cards, as `project init` and a morning of use leave them: #1 the OLDEST, labelled —
    the card an incremental read is least likely to meet again — #2 closed, #3 the newest."""
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    seed = LocalTracker("acme", db_path=db)
    seed.create_ticket(title="the oldest", body="b")
    seed.add_label("#1", "bug")
    seed.create_ticket(title="closed", body="b")
    seed.close_ticket("#2", "", delivered=False)
    seed.create_ticket(title="the newest", body="b")
    return project


def _seen(tickets) -> dict[str, dict]:
    """Every card a reader sees, by ref. BY REF AND NOT BY POSITION: a sweep hands the port's
    newest-updated-first order back and a refresh re-sorts by ref, and neither order is what this
    file is about — the cards and every field of each are."""
    return {t.number: t.model_dump() for t in tickets}


def _read(project, tracker, **kw):
    tickets, error = board.read_board(project, tracker=tracker, limit=0, **kw)
    assert error == ""
    return tickets


# ── every writer of the local rows, driven through "the other process" ────────────────────────

#: One drive per WRITE method of `LocalTracker` and `LocalBoard`: `(tracker, board) -> None`, run
#: on instances the reader does not hold. `remove_ticket` is driven where the row has it (#384).
_DRIVES = {
    "create_ticket": lambda t, b: t.create_ticket(title="made elsewhere", body=""),
    "update_body": lambda t, b: t.update_body("#1", "rewritten elsewhere"),
    "update_title": lambda t, b: t.update_title("#1", "renamed elsewhere"),
    "comment": lambda t, b: t.comment("#1", "a note"),
    "say": lambda t, b: t.say("#1", "a person's answer", author="someone"),
    "set_state": lambda t, b: t.set_state("#1", JobState.TODO),
    "add_label": lambda t, b: t.add_label("#1", "ux"),
    "remove_label": lambda t, b: t.remove_label("#1", "bug"),
    "close_ticket": lambda t, b: t.close_ticket("#1", "done elsewhere", delivered=True),
    "reopen_ticket": lambda t, b: t.reopen_ticket("#2"),
    "link_child": lambda t, b: t.link_child("#1", "#3"),
    "remove_ticket": lambda t, b: t.remove_ticket("#1", "a duplicate", by="someone"),
    "set_column": lambda t, b: b.set_column(issue="#1", issue_url="", name="TO-DO"),
    "set_status": lambda t, b: b.set_status(issue="#1", issue_url="",
                                            state=JobState.IMPLEMENTING),
    "place_after": lambda t, b: b.place_after(issue="#3", issue_url="", after=None,
                                              column="Backlog"),
}

#: The writes the board view does not show: a native parent link, and a card's place in its
#: column (#512) — an order among cards, which no card's fields carry.
_NOT_SHOWN = frozenset({"link_child", "place_after"})


def _writers(cls) -> set[str]:
    """The public methods of `cls` that write the file — derived from the class, never listed.

    A method writes when it opens a write transaction or goes through the row's one write helper
    (`_touch`). Read from the SOURCE because that is where the fact lives; a list kept beside it is
    a list the next writer is added to the class and not to."""
    out = set()
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        src = inspect.getsource(fn)
        if "write=True" in src or "self._touch(" in src:
            out.add(name)
    return out


def test_every_writer_of_the_local_rows_is_driven_below():
    """THE SCOPE, ASSERTED: a writer this file does not drive is a write nobody has shown a reader
    in another process can see. Non-empty and plausible first, so a derivation that silently found
    nothing cannot pass by covering nothing."""
    writers = _writers(LocalTracker) | _writers(LocalBoard)
    assert {"create_ticket", "close_ticket", "remove_label", "set_column"} <= writers, writers
    missing = writers - set(_DRIVES)
    assert not missing, (f"{sorted(missing)} write board.db and are not driven by "
                         f"test_a_write_by_another_process_is_seen_on_the_next_read — add a drive")


@pytest.mark.parametrize("writer", sorted(_DRIVES))
def test_a_write_by_another_process_is_seen_on_the_next_read(cards, db, writer):
    """The reader has swept; another process writes; nobody forgets anything. The reader's next
    read equals a fresh whole read — the board on disk, not the board remembered."""
    other = LocalTracker("acme", db_path=db)
    if not callable(getattr(other, writer, None)) and not callable(
            getattr(LocalBoard, writer, None)):
        pytest.skip(f"this row has no {writer}")
    reader = LocalTracker("acme", db_path=db)
    before = _seen(_read(cards, reader))

    _DRIVES[writer](other, LocalBoard(other))

    after = _seen(_read(cards, reader))
    truth = _seen(_read(cards, reader, fresh=True))
    assert after == truth, f"{writer} in another process was not seen on the next read"
    if writer not in _NOT_SHOWN:
        assert after != before, f"the drive for {writer} changed nothing a reader sees"


def test_a_card_stamped_before_the_watermark_is_still_seen(cards, db, monkeypatch):
    """A writer takes its stamp BEFORE the write lock (`create_ticket` and four others), so two
    writers can commit out of stamp order — and an incremental read keyed on the newest stamp it
    has seen never meets the older one. Measured on `main`: the card never appeared."""
    import openfactory.adapters.tracker.local as local

    reader = LocalTracker("acme", db_path=db)
    _read(cards, reader)
    monkeypatch.setattr(local, "now_iso", lambda: "2000-01-01T00:00:00+00:00")
    LocalTracker("acme", db_path=db).create_ticket(title="stamped early", body="")
    assert "stamped early" in [t.title for t in _read(cards, reader)]


def test_more_changes_than_one_refresh_merges_are_all_seen(cards, db):
    """An incremental read merges at most `_REFRESH_LIMIT` changed cards, newest first; the rest
    are older than the watermark it then keeps, and wait for the full sweep. On a board whose
    whole read is a query, nothing waits."""
    reader = LocalTracker("acme", db_path=db)
    _read(cards, reader)
    other = LocalTracker("acme", db_path=db)
    for i in range(board._REFRESH_LIMIT + 20):
        other.create_ticket(title=f"burst {i}", body="")
    for ref in range(4, 4 + board._REFRESH_LIMIT + 20):
        other.update_body(f"#{ref}", "touched")
    assert _seen(_read(cards, reader)) == _seen(_read(cards, reader, fresh=True))


# ── the snapshot stays where a read costs something ─────────────────────────────────────────────

class _Hosted:
    """A row that says nothing about what a read costs — every hosted row today."""

    def __init__(self):
        self.calls: list[dict] = []

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        self.calls.append({"updated_since": updated_since})
        return [] if updated_since else [TicketSummary(ref="1", title="t", body="", state="open",
                                                       updated_at="2026-07-27T00:00:00Z")]


class _HostedProject:
    name = "books"
    forge = None

    class tracker:
        kind = "github"
        repo = "o/r"
        options: dict = {}


def test_a_row_that_does_not_declare_it_still_reads_only_what_changed(monkeypatch):
    monkeypatch.setattr(board, "_columns", lambda p, t: {})
    hosted = _Hosted()
    board.read_board(_HostedProject(), tracker=hosted)
    board.read_board(_HostedProject(), tracker=hosted)
    assert [bool(c["updated_since"]) for c in hosted.calls] == [False, True], (
        "a row silent about its cost must keep the sweep-once-then-incremental read — it is what "
        "stands between a hosted board and its rate limit")


def test_only_a_literal_True_declares_it():
    """A double answers every attribute with something truthy; read as cheap, it would re-read a
    rate-limited API on every call."""
    assert whole_read_is_cheap(MagicMock()) is False
    assert whole_read_is_cheap(object()) is False
    assert whole_read_is_cheap(type("R", (), {"whole_read_is_cheap": 1})()) is False
    assert whole_read_is_cheap(type("R", (), {"whole_read_is_cheap": True})()) is True


# ── the two axes say the same thing about one board ────────────────────────────────────────────

def _classes(package: str) -> list[type]:
    pkg = importlib.import_module(package)
    out = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"{package}.{mod.name}")
        out += [c for _, c in inspect.getmembers(module, inspect.isclass)
                if c.__module__ == module.__name__]
    return out


def test_a_board_the_panel_watches_is_a_board_no_reader_keeps_a_copy_of(project):
    """`Watchable` on the board axis and `whole_read_is_cheap` on the tracker axis are ONE fact —
    "a re-read costs a query on this machine" — declared twice. Apart, the panel's page shows the
    board on disk while the product role describes the one it remembers, which is #393.

    The scope first: every class that declares either, found by scanning both packages, is a class
    the pairing below covers."""
    watched = {c for c in _classes("openfactory.adapters.board")
               + _classes("openfactory.adapters.tracker")
               if c is not Watchable and not getattr(c, "_is_protocol", False)
               and callable(getattr(c, "poll_seconds", None)) and issubclass(c, Watchable)}
    cheap = {c for c in _classes("openfactory.adapters.tracker")
             if getattr(c, "whole_read_is_cheap", False) is True}
    assert watched == {LocalBoard} and cheap == {LocalTracker}, (watched, cheap)

    from openfactory.adapters.board import build_board
    from openfactory.adapters.tracker.registry import build_tracker

    tracker, brd = build_tracker(project, token=None), build_board(project, token=None)
    assert isinstance(brd, Watchable) and whole_read_is_cheap(tracker)

"""`tracker.local`, `board.local` and `board.db` — the rows a deployment whose world is its own
machine has always needed (ADR-0049 D1, D5).

WHAT IS PROVEN HERE, and each of these is a promise some other part of the platform depends on:

  · the file's DISCIPLINE — WAL, a per-project number sequence taken under a write lock, and a
    rollback that leaves nothing behind;
  · the port's THREE ANSWERS on `comments()` and `columns()`, which is the distinction the whole
    read side is built on: `None` could not look, `[]` there is nothing;
  · the two SPELLINGS, `#N` from the ticket and bare `N` from the summary;
  · the timestamp SHAPE, because the answer sweep compares these as strings;
  · that a row needing no credential never reaches the deployment's own.

`tests/test_the_tracker_has_a_read_side.py` already runs the whole read-side contract over this
row through its own table; this file covers what is specific to it.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from openfactory.adapters.board.local import LocalBoard
from openfactory.adapters.board_db import connect, next_ref, now_iso
from openfactory.adapters.board_setup.local import LocalBoardSetup
from openfactory.adapters.tracker.local import BOT_AUTHOR, LocalTracker
from openfactory.contracts import JobState


@pytest.fixture
def db(tmp_path):
    return tmp_path / "board.db"


@pytest.fixture
def project(db):
    return type("P", (), {
        "name": "acme",
        "tracker": type("T", (), {"kind": "local", "repo": "acme",
                                  "options": {"board_db": str(db)}})(),
    })()


@pytest.fixture
def board(db, project):
    """A project in the state `project init` leaves it: six columns, no cards."""
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    tracker = LocalTracker("acme", db_path=db)
    return tracker, LocalBoard(tracker)


# ── the file ────────────────────────────────────────────────────────────────────────────────────

def test_the_file_is_where_the_registry_is(tmp_path, monkeypatch):
    """The registry's own resolution, for the registry's own reasons: an explicit path is never
    second-guessed, then the deployment's variable, then the operator's directory."""
    from openfactory.adapters.board_db import PATH_ENV, db_path

    monkeypatch.delenv(PATH_ENV, raising=False)
    monkeypatch.setattr("openfactory.namespace.operator_path",
                        lambda name: tmp_path / ".openfactory" / name)
    assert db_path().name == "board.db" and db_path().parent.name == ".openfactory"

    monkeypatch.setenv(PATH_ENV, str(tmp_path / "named.db"))
    assert db_path() == tmp_path / "named.db"
    assert db_path(tmp_path / "explicit.db") == tmp_path / "explicit.db", "explicit always wins"


def test_the_number_sequence_is_per_project_and_taken_under_the_write_lock(db):
    """`MAX(ref) + 1` is only safe inside the caller's transaction, which is why `next_ref` takes
    an open connection rather than opening its own."""
    with connect(db, write=True) as conn:
        assert next_ref(conn, "acme") == 1
        conn.execute("INSERT INTO cards(project, ref, created_at, updated_at) VALUES (?,?,?,?)",
                     ("acme", 1, now_iso(), now_iso()))
        assert next_ref(conn, "acme") == 2
        assert next_ref(conn, "other") == 1, "the sequence is per project, in one file"


def test_two_writers_never_take_the_same_number(db):
    """`BEGIN IMMEDIATE` is invisible to one process, which is why this one uses two.

    MEASURED: cutting it to a plain `BEGIN` survived every other test in this file. SQLite's
    default transaction takes its write lock at the FIRST WRITE, so two writers both read `1`,
    both decide the next number is `1`, and the second INSERT hits the primary key — a card the
    caller was told was opened and that is not there. With the lock taken at the top, the second
    waits its `busy_timeout` and reads `2`."""
    import threading

    started = threading.Barrier(2)
    seen: list[int] = []
    failed: list[BaseException] = []

    def _open_one() -> None:
        try:
            started.wait(timeout=5)
            with connect(db, write=True) as conn:
                ref = next_ref(conn, "acme")
                time.sleep(0.05)  # widen the window the deferred lock leaves open
                conn.execute(
                    "INSERT INTO cards(project, ref, created_at, updated_at) VALUES (?,?,?,?)",
                    ("acme", ref, now_iso(), now_iso()))
                seen.append(ref)
        except BaseException as exc:  # noqa: BLE001 — the failure IS the finding
            failed.append(exc)

    threads = [threading.Thread(target=_open_one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not failed, f"a writer lost its card: {failed[0]!r}"
    assert sorted(seen) == [1, 2], f"two writers took {seen} — the numbers collided"
    with connect(db) as conn:
        assert [r["ref"] for r in conn.execute("SELECT ref FROM cards ORDER BY ref")] == [1, 2]


def test_a_failed_write_leaves_nothing_behind(db):
    with connect(db, write=True) as conn:
        conn.execute("INSERT INTO cards(project, ref, created_at, updated_at) VALUES (?,?,?,?)",
                     ("acme", 1, now_iso(), now_iso()))
    with pytest.raises(RuntimeError), connect(db, write=True) as conn:
        conn.execute("INSERT INTO cards(project, ref, created_at, updated_at) VALUES (?,?,?,?)",
                     ("acme", 2, now_iso(), now_iso()))
        raise RuntimeError("the caller failed half way")
    with connect(db) as conn:
        assert [r["ref"] for r in conn.execute("SELECT ref FROM cards")] == [1]


def test_the_file_is_in_WAL_so_three_processes_can_share_it(db):
    with connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_a_second_connection_reads_what_the_first_committed(db):
    """The worker writes, the panel reads, the CLI does both — the whole reason this is a database
    rather than the registry's read-modify-replace."""
    tracker = LocalTracker("acme", db_path=db)
    ref = tracker.create_ticket(title="one", body="")
    assert LocalTracker("acme", db_path=db).get_ticket(ref).title == "one"


def test_the_timestamp_is_the_platforms_and_not_SQLites(db):
    """`T` and an offset, never SQLite's space-separated `CURRENT_TIMESTAMP`.

    THE COMPARISON IS A STRING COMPARISON and it decides whether an answer is newer than the
    question it answers. A space sorts below `T`, so an answer written five minutes AFTER the
    question would read as older — and the person would be chased for something they had already
    written."""
    stamp = now_iso()
    assert "T" in stamp and stamp.endswith("+00:00")
    with connect(db) as conn:
        sqlite_style = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
    assert sqlite_style < stamp, (
        "this is the ordering bug: SQLite's own stamp sorts BELOW the platform's for the same "
        "instant, so an answer would read as older than its question")


# ── the tracker row ─────────────────────────────────────────────────────────────────────────────

def test_the_two_spellings_are_the_ports(board):
    tracker, _ = board
    ref = tracker.create_ticket(title="Add a button", body="")
    assert ref == "#1", "the ticket's own id carries the hash"
    assert tracker.get_ticket(ref).id == "#1"
    assert [s.ref for s in tracker.list_tickets()] == ["1"], "a summary's ref is bare"
    assert tracker.get_ticket("1").id == "#1", "either spelling reaches the same card"


def test_comments_has_three_answers(board):
    """The distinction the port calls the most important on the read side: the consumer is a
    language model, and `[]` for an unreadable thread makes it conclude nobody has looked."""
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="")
    assert tracker.comments(ref) == [], "a card with no comments has none"
    assert tracker.comments("#404") is None, "a card this file does not hold could not be read"
    tracker.comment(ref, "the factory asks")
    assert [c.body for c in tracker.comments(ref)] == ["the factory asks"]


def test_an_unreadable_file_answers_could_not_look_rather_than_empty(board, db, monkeypatch):
    tracker, _ = board
    tracker.create_ticket(title="one", body="")

    def _refuse(*a, **kw):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("openfactory.adapters.tracker.local.connect", _refuse)
    assert tracker.comments("#1") is None
    assert tracker.list_tickets() is None


def test_the_factory_signs_its_own_comments_and_a_person_signs_theirs(board):
    """The answer sweep accepts an answer only from the requester and never from the platform's
    own posting identity, so a person's answer written as the bot is an answer that never counts
    (ADR-0048 §6)."""
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="")
    tracker.comment(ref, "what is this for?")
    tracker.say(ref, "late fees", author="mara")
    assert [(c.author, c.body) for c in tracker.comments(ref)] == [
        (BOT_AUTHOR, "what is this for?"), ("mara", "late fees")]


def test_the_comments_come_back_oldest_first_within_one_second(board):
    """By `seq`, not by the timestamp: two comments in the same second must still be ordered, and
    the sweep reads the order."""
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="")
    for n in range(5):
        tracker.say(ref, f"line {n}", author="mara")
    assert [c.body for c in tracker.comments(ref)] == [f"line {n}" for n in range(5)]
    assert [c.body for c in tracker.comments(ref, limit=2)] == ["line 3", "line 4"]


def test_the_requester_is_whoever_filed_it(board):
    """D7's whole point: on this row the person who filed the card is nameable in the tracker's
    own namespace, so the factory has somebody to ask."""
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="", author="panel", requester="panel")
    ticket = tracker.get_ticket(ref)
    assert ticket.author == "panel" and ticket.requester_forge == "panel"
    assert tracker.identity_of("panel") == "panel" and tracker.identity_of("") == ""
    assert tracker.mention("panel") == "panel", "no `@` this board resolves"


def test_a_state_the_board_cannot_place_answers_False_and_never_raises(board):
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="")
    assert tracker.set_state(ref, JobState.TODO) is True
    assert tracker.set_state("#404", JobState.TODO) is False, "no such card"
    assert tracker.set_state(ref, JobState.PAUSED) is False, "no column key for this state"


def test_a_column_the_board_does_not_have_is_False_and_never_a_raise(board, db):
    """THE OTHER HALF, and the one a single `PAUSED` never reaches: a state that HAS a column key
    on a board that does not have that column.

    MEASURED: cutting this branch to a raise survived, because every case in this file stopped at
    the key lookup one line earlier. The gather's park path reads a `False` here to decide whether
    to say the park did not land; a raise takes the whole activity down instead."""
    tracker, _ = board
    ref = tracker.create_ticket(title="one", body="")
    with connect(db, write=True) as conn:
        conn.execute("DELETE FROM columns WHERE project = ? AND key = 'needs_action'", ("acme",))
    assert tracker.set_state(ref, JobState.ON_HOLD) is False
    assert tracker.set_state(ref, JobState.TODO) is True, "the columns it does have still work"


def test_closed_is_not_delivered(board):
    """`triage.Ticket.delivered` reads exactly this word, and the conflation once had the platform
    announce eleven cards closed as duplicates as delivered work."""
    tracker, _ = board
    a = tracker.create_ticket(title="done", body="")
    b = tracker.create_ticket(title="dupe", body="")
    tracker.close_ticket(a, "shipped", delivered=True)
    tracker.close_ticket(b, "a duplicate of #1", delivered=False)
    by_ref = {s.ref: s for s in tracker.list_tickets(state="closed")}
    assert by_ref["1"].state_reason == "completed"
    assert by_ref["2"].state_reason == "not_planned"


def test_the_ticket_url_is_the_panels_own_route(board, monkeypatch):
    tracker, _ = board
    monkeypatch.setenv("OPENFACTORY_PANEL_URL", "http://box.local:9000/")
    assert tracker.ticket_url("#7") == "http://box.local:9000/p/acme/card/7"
    monkeypatch.delenv("OPENFACTORY_PANEL_URL")
    assert tracker.ticket_url("#7") == "http://localhost:8787/p/acme/card/7"


def test_the_filter_is_applied_before_the_limit(board):
    """A limit applied to the read would answer "the newest N cards, of which these few are open",
    which is a different question from the one asked."""
    tracker, _ = board
    for n in range(4):
        ref = tracker.create_ticket(title=f"card {n}", body="")
        if n < 2:
            tracker.close_ticket(ref, "", delivered=True)
    assert len(tracker.list_tickets(state="open", limit=2)) == 2
    assert {s.ref for s in tracker.list_tickets(state="open")} == {"3", "4"}


# ── the board row ───────────────────────────────────────────────────────────────────────────────

def test_the_board_has_the_platforms_six_columns_in_board_order(board):
    from openfactory.adapters.board.columns import column_names

    _, brd = board
    assert brd.column_names() == list(column_names())


def test_columns_has_three_answers_too(board, monkeypatch):
    tracker, brd = board
    assert brd.columns() == {}, "read fine, nothing on it"
    tracker.create_ticket(title="one", body="", column="todo")
    assert brd.columns() == {"1": "TO-DO"}

    def _refuse(*a, **kw):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr("openfactory.adapters.board.local.connect", _refuse)
    assert brd.columns() is None and brd.column_names() is None
    assert brd.items_in_status("TO-DO") == [], "a read that fails must not take the tick down"


def test_a_move_to_a_column_the_board_does_not_have_is_False_with_a_reason(board, caplog):
    tracker, brd = board
    ref = tracker.create_ticket(title="one", body="")
    assert brd.set_column(issue=ref, issue_url="", name="Sprint 4") is False
    assert "Sprint 4" in caplog.text, "a False always leaves a why behind it"
    assert brd.set_column(issue=ref, issue_url="", name="TO-DO") is True
    assert brd.items_in_status("TO-DO") == ["1"]


def test_set_status_goes_through_the_platforms_one_resolution(board):
    """`column_key`, so a `pr_open` a person is blocking on lands in Needs Action here exactly as
    it does on a vendor's board (#166)."""
    tracker, brd = board
    ref = tracker.create_ticket(title="one", body="")
    assert brd.set_status(issue=ref, issue_url="", state=JobState.PR_OPEN) is True
    assert brd.columns() == {"1": "In review"}
    assert brd.set_status(issue=ref, issue_url="", state=JobState.PR_OPEN,
                          needs_person=True) is True
    assert brd.columns() == {"1": "Needs Action"}


def test_the_pickup_column_is_the_boards_own_name_for_it(board, db):
    _, brd = board
    assert brd.pickup_column() == "TO-DO"
    with connect(db, write=True) as conn:
        conn.execute("UPDATE columns SET name = 'A Fazer' WHERE project = ? AND key = 'todo'",
                     ("acme",))
    assert brd.pickup_column() == "A Fazer", "the name that is actually on their board"


def test_the_board_declares_no_rank_it_cannot_write(board):
    """`Rankable` is a second protocol precisely so a board without a writable backlog order says
    so by not claiming it — `ProductModule.reorder` then answers in a sentence."""
    from openfactory.adapters.board.base import Rankable

    _, brd = board
    assert not isinstance(brd, Rankable)


# ── creating it ─────────────────────────────────────────────────────────────────────────────────

def test_creating_the_board_is_idempotent_and_renames_nothing(project, db):
    setup = LocalBoardSetup()
    assert setup.attached(project) == "", "nothing there yet"
    coordinate, url = setup.create(project=project, owner="", title="acme", token=None)
    assert coordinate == "", "this board has no second object to point at"
    assert url.endswith("/p/acme/board")
    assert "6 columns" in setup.attached(project)

    with connect(db, write=True) as conn:
        conn.execute("UPDATE columns SET name = 'A Fazer' WHERE project = ? AND key = 'todo'",
                     ("acme",))
    setup.create(project=project, owner="", title="acme", token=None)
    with connect(db) as conn:
        row = conn.execute("SELECT name FROM columns WHERE project = ? AND key = 'todo'",
                           ("acme",)).fetchone()
    assert row["name"] == "A Fazer", "a re-run must not undo somebody's rename (C-14)"


def test_the_github_row_refuses_an_empty_owner_in_its_own_words():
    """The refusal moved OUT of `init` and into the row: a board with no coordinate needs no
    owner, and the command cannot know which vendors do."""
    from openfactory.adapters.board_setup.base import BoardSetupError
    from openfactory.adapters.tracker.github_board_setup import GitHubBoardSetup

    with pytest.raises(BoardSetupError, match="user or an organisation"):
        GitHubBoardSetup().create(project=None, owner="  ", title="acme", token="tok")


def test_the_github_row_still_answers_from_its_own_coordinates():
    from openfactory.adapters.tracker.github_board_setup import GitHubBoardSetup

    attached = type("P", (), {"tracker": type("T", (), {
        "options": {"board_owner": "acme", "board_number": "7"}})()})()
    bare = type("P", (), {"tracker": type("T", (), {"options": {}})()})()
    assert GitHubBoardSetup().attached(attached) == "acme/#7"
    assert GitHubBoardSetup().attached(bare) == ""


# ── the credential that is not needed ───────────────────────────────────────────────────────────

def test_a_row_that_needs_no_credential_never_reaches_the_deployments_own(monkeypatch):
    """THE DEFECT THIS FIELD EXISTS FOR. `env=""` is GitHub's row and means the opposite — its
    default IS the generic pair — so a local project on a machine that also runs a GitHub project
    would have been handed that project's token."""
    from openfactory.credentials import tracker_token_for, vendor_needs_credential

    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "a-github-token")
    local = type("P", (), {"name": "a", "tracker": type("T", (), {"kind": "local",
                                                                  "options": {}})()})()
    hosted = type("P", (), {"name": "b", "tracker": type("T", (), {"kind": "github",
                                                                   "options": {}})()})()
    assert vendor_needs_credential(local.tracker) is False
    assert vendor_needs_credential(hosted.tracker) is True
    assert tracker_token_for(local) is None
    assert tracker_token_for(hosted) == "a-github-token"


def test_a_row_that_declares_nothing_still_needs_one(monkeypatch):
    """`needs=True` is the default, so no existing row changes meaning and no add-on is edited."""
    from openfactory.credentials import vendor_needs_credential

    assert vendor_needs_credential(type("T", (), {"kind": "a-stranger", "options": {}})()) is True


def test_the_doctor_does_not_report_a_credential_that_is_not_needed(monkeypatch, project):
    """A finding here would send somebody to configure a credential belonging to another system."""
    from openfactory import doctor

    monkeypatch.delenv("OPENFACTORY_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENFACTORY_FORGE_TOKEN", raising=False)
    reachable, detail = doctor.probes_for(project).forge_reachable()
    assert reachable and detail == "", f"the local row was told it is missing something: {detail}"

    hosted = type("P", (), {"name": "b", "repo_path": "/tmp/b",
                            "tracker": type("T", (), {"kind": "github", "repo": "o/b",
                                                      "options": {}})()})()
    ok, why = doctor.probes_for(hosted).forge_reachable()
    assert not ok and "no forge credential" in why, (
        "a vendor that DOES need one must still be told — the check was not simply switched off")


# ── both rows are conformant, which is the slice's own guard ────────────────────────────────────

def test_both_rows_are_conformant(board):
    from openfactory.conformance.adapters import check_board, check_tracker

    tracker, brd = board
    assert check_tracker(tracker) == []
    assert check_board(brd) == []


def test_an_empty_board_is_the_one_state_conformance_calls_out(db):
    """MEASURED, AND IT IS A DISAGREEMENT WORTH NAMING. `BoardAdapter.column_names` says `[]` means
    *read fine and the board genuinely defines none*; `conformance` treats `[]` as a finding,
    because for the three hosted vendors a board with no columns is unreachable-in-practice and
    `[]` therefore really does mean *could not read*.

    This row is the first that can produce an honest `[]` — a project whose `project init` has not
    created the columns — so it is also the first that can tell the two rules apart. The row stays
    honest, and the finding is CORRECT for the state it describes: a board with no columns will
    never pick anything up, and the remedy is to run `project init`."""
    from openfactory.conformance.adapters import check_board

    findings = check_board(LocalBoard(LocalTracker("never-initialised", db_path=db)))
    assert [f.rule for f in findings] == ["board.columns-unreadable-is-None"]

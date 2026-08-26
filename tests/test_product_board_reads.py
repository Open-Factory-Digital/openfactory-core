"""Sweep once, then only what changed — and read it through the PORT.

Every operation this role has wanted the whole board — 300 issues plus 400 project items, two heavy
GraphQL queries — and a single conversation could ask for it five times. On 2026-07-27 that helped
exhaust the GitHub App installation's hourly quota, and the first casualty was a real job: #478
parked with "API rate limit exceeded", and then the tech-lead could not diagnose the park, because
the same limit blocked it too.

The quota is shared by the poller, every job, and every human running `gh`. A read here is never
free.

AND UNTIL #97 THE WHOLE FILE ABOVE WAS ALSO GITHUB-ONLY. The tickets came from `gh issue list`, so
the reader failed on that line and returned before `_columns` — the provider-neutral half — was ever
reached. `TrackerAdapter.list_tickets` closes that, and it brings the one distinction this module is
built on: `None` is *I could not read* and `[]` is *I read, and there is nothing*. Both are asserted
here, because collapsing them is what turns an unreadable board into "nothing is queued".
"""

from __future__ import annotations

import pytest

from openfactory.adapters.tracker.base import TicketSummary
from openfactory.product import board


class _Project:
    name = "books"

    class tracker:
        kind = "github"
        repo = "o/r"
        options: dict = {"board_owner": "o", "board_number": "6"}

    forge = None


def _summary(ref="1", *, title="t", state="open", state_reason="", updated="2026-07-27T00:00:00Z",
             assignees=(), labels=()) -> TicketSummary:
    return TicketSummary(ref=ref, title=title, body="b", state=state, state_reason=state_reason,
                         labels=list(labels), assignees=list(assignees), updated_at=updated)


class _Tracker:
    """A `TrackerAdapter` stand-in that records exactly what it was asked for.

    ONLY `list_tickets` AND `comments`: those are the two reads this module makes, and a fake that
    answered more would be asserting a contract nobody here depends on. `None` is a first-class
    answer — half of these tests are about the difference between it and `[]`."""

    def __init__(self, *, full=None, changed=None, comments=None):
        self.full = full
        self.changed = changed if changed is not None else []
        self._comments = comments
        self.calls: list[dict] = []

    def list_tickets(self, *, state="all", updated_since="", limit=0):
        self.calls.append({"state": state, "updated_since": updated_since, "limit": limit})
        if updated_since:
            return self.changed
        return self.full

    def comments(self, ref, *, limit=0):
        return self._comments


@pytest.fixture(autouse=True)
def _clean():
    board.forget_board()
    yield
    board.forget_board()


def _columns(monkeypatch, calls: list, answer=None):
    """Stubs the module's own column seam — `{}` is an EMPTY board, deliberately not `None`: None
    means "could not read" and `read_board` refuses to hand back half a board."""
    monkeypatch.setattr(board, "_columns",
                        lambda p, t: (calls.append({"columns": True}) or (
                            {} if answer is None else answer)))


def _wired(monkeypatch, tracker: _Tracker, answer=None) -> list[dict]:
    """Everything the module asks the outside world, in one list: the tracker's own calls plus the
    column reads."""
    _columns(monkeypatch, tracker.calls, answer)
    return tracker.calls


def test_a_second_read_asks_only_for_UPDATES(monkeypatch):
    """A cache would only have made the same full read less often. Asking "what changed since?"
    costs one cheap query instead of two expensive ones, and on a quiet afternoon returns nothing."""
    tracker = _Tracker(full=[_summary()])
    calls = _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    assert any(c.get("columns") for c in calls)          # the full sweep, once
    calls.clear()

    board.read_board(p, tracker=tracker)
    assert calls, "the second read should still ask the tracker something"
    assert all(c.get("updated_since") for c in calls), "it must ask only for what changed"
    assert not any(c.get("columns") for c in calls), "the full sweep must not run again"


def test_nothing_changed_means_the_board_we_already_had(monkeypatch):
    tracker = _Tracker(full=[_summary()])
    _wired(monkeypatch, tracker)
    p = _Project()
    before, _ = board.read_board(p, tracker=tracker)
    after, error = board.read_board(p, tracker=tracker)
    assert error == ""
    assert [t.number for t in after] == [t.number for t in before]


def test_a_changed_ticket_is_merged_WITHOUT_re_reading_everything(monkeypatch):
    tracker = _Tracker(
        full=[_summary("1"), _summary("2", title="outro", updated="2026-07-26T00:00:00Z")],
        changed=[_summary("1", title="MUDOU", state="closed", state_reason="not_planned",
                          updated="2026-07-27T10:00:00Z")])
    _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    tickets, _ = board.read_board(p, tracker=tracker)

    by = {t.number: t for t in tickets}
    assert by["1"].title == "MUDOU" and by["1"].state == "closed"   # the update landed
    assert by["2"].title == "outro"                                 # the untouched one survived


def test_the_close_REASON_survives_the_port_into_the_ticket(monkeypatch):
    """CLOSED IS NOT DELIVERED (`triage.Ticket.delivered`), and the rule is worthless if the reason
    never arrives: every cancelled card would look completed again. It used to be `stateReason` off
    `gh --json`; it is `TicketSummary.state_reason` now, already folded to the port's lowercase
    vocabulary by each provider — so nothing here re-lowercases it and nothing here may drop it."""
    tracker = _Tracker(full=[_summary("1", state="closed", state_reason="not_planned"),
                             _summary("2", state="closed", state_reason="completed")])
    _wired(monkeypatch, tracker)
    tickets, _ = board.read_board(_Project(), tracker=tracker)

    by = {t.number: t for t in tickets}
    assert by["1"].state_reason == "not_planned" and by["1"].delivered is False
    assert by["2"].state_reason == "completed" and by["2"].delivered is True


def test_the_watermark_comes_from_the_TICKETS_not_the_clock(monkeypatch):
    """A clock watermark skips anything updated between the query and the write — which is exactly
    the ticket somebody just touched. It goes back in the PROVIDER's own spelling, because it is
    fed into that provider's own date syntax."""
    tracker = _Tracker(full=[_summary("1", updated="2026-07-27T09:30:00Z")])
    calls = _wired(monkeypatch, tracker)
    board.read_board(_Project(), tracker=tracker)
    calls.clear()
    board.read_board(_Project(), tracker=tracker)
    incremental = next(c for c in calls if c.get("updated_since"))
    assert incremental["updated_since"] == "2026-07-27T09:30:00Z"


def test_a_caller_that_needs_the_truth_can_force_a_full_sweep(monkeypatch):
    tracker = _Tracker(full=[_summary()])
    calls = _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    calls.clear()
    board.read_board(p, tracker=tracker, fresh=True)
    assert any(c.get("columns") for c in calls)


def test_a_write_makes_us_stop_describing_the_board_from_memory(monkeypatch):
    tracker = _Tracker(full=[_summary()])
    calls = _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    board.forget_board("books")
    calls.clear()
    board.read_board(p, tracker=tracker)
    assert any(c.get("columns") for c in calls)


def test_a_full_sweep_runs_again_eventually(monkeypatch):
    """The backstop for what incremental cannot see: a card dragged between columns changes nothing
    the tracker reports as an update.

    THE JUMP IS RELATIVE, AND IT USED TO BE THE LITERAL `10 ** 6`. `time.monotonic()` is uptime on
    this platform, not an epoch, so that constant is only "the future" while the machine has been
    up for less than about 11.6 days. Measured the day it stopped being true: monotonic had reached
    995,387, leaving a 4,613 s jump against a 21,600 s TTL, and this test failed on a clean tree
    with nothing to do with the change being made — an absolute value assumed to be ahead of a
    relative clock. A long-lived worker container is exactly where that assumption expires.
    """
    tracker = _Tracker(full=[_summary()])
    calls = _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    calls.clear()
    later = board.time.monotonic() + board._FULL_AFTER + 1
    monkeypatch.setattr(board.time, "monotonic", lambda: later)
    board.read_board(p, tracker=tracker)
    assert any(c.get("columns") for c in calls)


def test_a_FAILED_incremental_read_falls_back_to_a_full_sweep(monkeypatch):
    """Serving the snapshot we just failed to confirm would be reporting on a board we did not
    check. `None` from the incremental read is the failure; `[]` is a quiet afternoon."""
    tracker = _Tracker(full=[_summary("1")])
    _wired(monkeypatch, tracker)
    p = _Project()
    board.read_board(p, tracker=tracker)
    tracker.changed = None
    tickets, error = board.read_board(p, tracker=tracker)
    assert error == "" and [t.number for t in tickets] == ["1"]


def test_a_FAILED_first_read_is_not_remembered_as_an_answer(monkeypatch):
    tracker = _Tracker(full=None)
    _wired(monkeypatch, tracker)
    tickets, error = board.read_board(_Project(), tracker=tracker)
    assert error and tickets == []

    tracker.full = [_summary()]
    tracker.calls.clear()
    tickets, error = board.read_board(_Project(), tracker=tracker)
    assert error == "" and [t.number for t in tickets] == ["1"], "a failure was remembered"


# ── None is not empty, on the read that decides whether anybody is told anything ─────────────────

def test_an_UNREADABLE_board_is_an_error_and_an_EMPTY_one_is_an_answer(monkeypatch):
    """THE RULE THE PORT EXISTS FOR, at this module's own door. Every caller here branches on
    `error`: "nothing is queued", "no findings" and "the open questions resolved themselves" are
    three wrong answers this module has already produced from a board it could not read.

    Both arms in one test on purpose — a negative guard with no positive twin passes just as well
    when the reader is broken for everybody."""
    unreadable = _Tracker(full=None)
    _wired(monkeypatch, unreadable)
    tickets, error = board.read_board(_Project(), tracker=unreadable)
    assert tickets == [] and error, "an unreadable board answered like an empty one"

    board.forget_board()
    empty = _Tracker(full=[])
    _wired(monkeypatch, empty)
    tickets, error = board.read_board(_Project(), tracker=empty)
    assert tickets == [] and error == "", "a genuinely empty board was reported as a failure"


def test_a_board_whose_COLUMNS_could_not_be_read_is_UNREADABLE_not_column_less(monkeypatch):
    """THE OTHER HALF OF THE SAME RULE, AND IT HAD NO GUARD AT ALL. The tickets are one of two
    reads a sweep makes; the columns are the other, and `_columns` draws the same distinction —
    `None` = the read failed, `{}` = this project has no board.

    It was never asserted here, and until #97 that was almost harmless: on any non-GitHub
    deployment the ticket half failed first and this arm was unreachable. It is reached on every
    vendor now, so collapsing it is a live defect — and it is the WORST shape of it, because it
    produces no error. Every ticket comes back with `column=""`, which means `parked_with_diagnosis`
    filters the whole board away and the client is told *"Nada parado esperando decisão no
    momento."* about a board nobody could read, while `readiness()` reports an empty queue to the
    tech-lead's idle-floor check.

    Both arms, because a negative guard with no positive twin cannot see a reader broken for
    everybody: a project with no board configured is genuinely column-less and must still read."""
    tracker = _Tracker(full=[_summary("1")])
    monkeypatch.setattr(board, "_columns", lambda p, t: None)
    tickets, error = board.read_board(_Project(), tracker=tracker)
    assert tickets == [] and error, "a board whose columns failed to load answered like a board"
    assert "columns" in error, error

    board.forget_board()
    monkeypatch.setattr(board, "_columns", lambda p, t: {})
    tickets, error = board.read_board(_Project(), tracker=tracker)
    assert error == "" and [t.number for t in tickets] == ["1"], (
        "a project with no board was reported as a failure")
    assert tickets[0].column == ""


def test_a_refresh_whose_columns_go_unreadable_KEEPS_the_ones_it_had(monkeypatch):
    """Stale beats blank on the incremental path, and the reason is the same one the sweep refuses
    for: `""` would erase where every changed card sits, and a card with no column is a card no
    downstream judgement can see. The previous column is the last thing that WAS true.

    The refresh must also not report an error for this — it has a whole board and one stale field,
    which is a thinner answer rather than no answer. Asserted because the arm is invisible: the
    reader returns normally either way, and the only difference is one field on the cards that
    happened to change."""
    tracker = _Tracker(full=[_summary("1")],
                       changed=[_summary("1", title="MUDOU", updated="2026-07-28T00:00:00Z")])
    monkeypatch.setattr(board, "_columns", lambda p, t: {"1": "TO-DO"})
    p = _Project()
    first, error = board.read_board(p, tracker=tracker)
    assert error == "" and first[0].column == "TO-DO"

    monkeypatch.setattr(board, "_columns", lambda p, t: None)
    tickets, error = board.read_board(p, tracker=tracker)

    assert error == "", "one stale field is a thinner answer, not a failed read"
    assert tickets[0].title == "MUDOU", "the update did not land"
    assert tickets[0].column == "TO-DO", "a column was erased by a read that failed"


def test_the_sweep_asks_for_EVERY_state_and_a_bounded_window(monkeypatch):
    """`state="all"` is not a detail: triage's whole job includes what was closed and how. The
    limit is the port's window on the NEWEST-UPDATED cards, which is what makes 300 the right
    number — the plain issue list used to order by creation."""
    tracker = _Tracker(full=[_summary()])
    _wired(monkeypatch, tracker)
    board.read_board(_Project(), tracker=tracker)
    (call,) = [c for c in tracker.calls if "state" in c]
    assert call["state"] == "all"
    assert call["limit"] == board._LIMIT


# ── reachability: production hands no adapter in ──────────────────────────────────────────────────

def test_the_reader_builds_the_projects_OWN_tracker_when_nobody_hands_it_one(monkeypatch):
    """REACHABILITY. Both real entry points — a Slack message and the scheduled sweep — call
    `read_board(project)` with no adapter, so a reader that only worked when a tracker was injected
    would be green here and dead in production. This is the same defect the injected-only board
    placement had (ADR-0030), and it is the reason this test exists at all."""
    built: dict = {}
    tracker = _Tracker(full=[_summary()])

    def _build(project, *, token=None, token_provider=None):
        built["token"] = token
        return tracker

    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker", _build)
    monkeypatch.setattr(board, "_columns", lambda p, t: {})
    monkeypatch.setenv("OPENFACTORY_TRACKER_TOKEN", "the-deployments-token")

    tickets, error = board.read_board(_Project())

    assert error == "" and [t.number for t in tickets] == ["1"]
    assert built["token"] == "the-deployments-token"


def test_the_board_read_travels_on_the_TRACKER_credential_not_the_callers(monkeypatch):
    """The board is a tracker object, and so is every read below it. `ProductModule.token` is the
    FORGE credential (`forge_token_for`) — right for cloning the documentation repository, the
    wrong axis for asking a tracker anything, and on a worker serving two vendors the failure is
    silent: a token that authenticates against the wrong system answers an empty search."""
    seen: dict = {}

    class _AzureProject(_Project):
        name = "dsk"

        class tracker:
            kind = "azure_devops"
            repo = "factory"
            options: dict = {"token_env": "AZURE_DEVOPS_PAT"}

    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the-projects-azure-pat")
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghp_the_deployments_github_secret")
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda project, *, token=None, token_provider=None:
                            seen.update(token=token) or _Tracker(full=[]))
    monkeypatch.setattr(board, "_columns", lambda p, t: seen.update(columns=t) or {})

    board.read_board(_AzureProject(), token="a-github-token-the-caller-was-holding")

    assert seen["token"] == "the-projects-azure-pat"
    assert seen["columns"] == "the-projects-azure-pat"


def test_a_project_with_no_tracker_at_all_is_UNREADABLE_never_empty(monkeypatch):
    """`build_tracker` raises on an unknown kind rather than falling back to GitHub, and this
    reader turns that into the sentence rather than the traceback — its callers are a chat listener
    and an hourly sweep. What it must never turn it into is an empty board."""
    class _Nothing:
        name = "nada"

        class tracker:
            kind = ""
            repo = "o/r"
            options: dict = {}

        forge = None

    tickets, error = board.read_board(_Nothing())

    assert tickets == []
    assert "unreadable" in error and "never as an empty one" in error

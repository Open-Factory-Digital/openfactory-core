"""A terminated run stops asking for a person once a later run of its ticket ended it (#339).

A job is stopped, the same ticket runs again under the same workflow id, and the second run
merges. The engine then lists BOTH runs, and the first one kept asking in `/api/inbox` for ever —
`kind: impediment`, options `resume` and `skip` — while `view.list_jobs` had already answered
`attention: false` for it on its own row. Neither option could be executed: a closed workflow
answers no signal, so both came back `conflict: #N is not parked waiting for anybody`.

EVERY CASE HERE LISTS TWO RUNS OF ONE WORKFLOW ID and goes through the REAL `view.list_jobs`, so
`attention` and `wedged` are what the engine-side row computes from `live`, not a value a fixture
typed. The bug is invisible to any test that lists one run, or that hands the inbox a row nobody
derived.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from temporalio.client import WorkflowExecutionStatus

from openfactory.api import app as app_module
from openfactory.floor import ladder
from openfactory.runtime.temporal import view as tv
from openfactory.techlead import conversation

WF = "openfactory-books-69"
NOW = datetime.now(UTC)


class _Run:
    """One execution of `WF`, as the engine's visibility list answers it."""

    def __init__(self, run_id: str, status, *, started: datetime, result=None, park=None):
        self.id, self.run_id, self.status = WF, run_id, status
        self.result = result if result is not None else {}
        self.park = park  # what `awaiting_action` answers — only ever asked of a RUNNING run
        self.start_time, self.close_time = started, None

    async def memo(self):
        return {"title": "import the spreadsheet"}


class _Handle:
    def __init__(self, run: _Run):
        self._run = run

    async def describe(self):
        return SimpleNamespace(status=self._run.status, run_id=self._run.run_id)

    async def query(self, name, *_a, **_k):
        return self._run.park if getattr(name, "__name__", str(name)) == "awaiting_action" else None

    async def result(self):
        return self._run.result


class _Engine:
    """Both runs of one workflow id, each reachable by its own run id."""

    def __init__(self, *runs: _Run):
        self.runs = list(runs)

    def list_workflows(self, _query):
        async def listed():
            for run in self.runs:
                yield run

        return listed()

    def get_workflow_handle(self, wf_id, run_id=None):
        mine = [r for r in self.runs if r.id == wf_id and (run_id is None or r.run_id == run_id)]
        if not mine:
            raise RuntimeError(f"workflow not found for ID: {wf_id}")  # the deploy watch, here
        return _Handle(max(mine, key=lambda r: r.start_time))


STOPPED = _Run("run-1", WorkflowExecutionStatus.TERMINATED, started=NOW - timedelta(days=2))
MERGED = _Run("run-2", WorkflowExecutionStatus.COMPLETED, started=NOW - timedelta(hours=3),
              result={"state": "merged"})
PARKED = _Run("run-2", WorkflowExecutionStatus.RUNNING, started=NOW - timedelta(hours=3),
              park={"kind": "impediment", "state": "on_hold", "note": "no acceptance criteria"})
#: Running at no gate and in no park, for longer than any real pass takes (`view.is_wedged`).
STUCK = _Run("run-2", WorkflowExecutionStatus.RUNNING, started=NOW - timedelta(days=1))


@pytest.fixture(autouse=True)
def _an_engine_with_two_runs_of_one_ticket(monkeypatch):
    tv._answered()
    tv._state_cache.clear()
    engine: dict[str, _Engine] = {}

    async def _connect():
        return engine["now"]

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(app_module, "_temporal", lambda: (tv, "engine.example:7233", "default"))
    yield engine
    tv._state_cache.clear()
    tv._answered()


async def _read(engine: dict, *runs: _Run) -> tuple[list[dict], list[dict]]:
    """(the engine's rows, the inbox's items) for one listing of `runs`."""
    engine["now"] = _Engine(*runs)
    rows = await tv.list_jobs(engine["now"], "default")
    return rows, await app_module.inbox()


# ── the measured case ───────────────────────────────────────────────────────────────────────────

async def test_a_ticket_a_later_run_delivered_asks_nobody(_an_engine_with_two_runs_of_one_ticket):
    """The issue's table, measured on a one-machine deployment: the newer run completed `merged`,
    the older one terminated `failed`, both `attention: false` — and the older one was in the
    inbox with `resume` and `skip`, two answers the engine refuses."""
    rows, items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, MERGED)

    assert [(r["run_id"], r["state"], r["attention"]) for r in rows] == [
        ("run-2", "merged", False), ("run-1", "failed", False)], "the engine's rows moved"
    assert items == [], (
        f"a run the engine closed still asks for a person, with answers nothing can execute: "
        f"{[(i['state'], [o['key'] for o in i.get('options', [])]) for i in items]}")


async def test_and_the_floor_gives_the_same_answer_with_the_inbox_as_without_it(
        _an_engine_with_two_runs_of_one_ticket):
    """ONE ANSWER, TWO ROADS. The floor reads the inbox when it has one and the engine's own flags
    when it does not (`ladder.py` rung 5), and says the inbox is "a RENDERING of the same job
    rows". Before #339 the two roads parted on exactly this listing: Armed without the inbox,
    Needs you with it."""
    rows, items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, MERGED)

    without = ladder.state(ladder.FloorInputs(jobs=rows, inbox=None, now=NOW))
    with_it = ladder.state(ladder.FloorInputs(jobs=rows, inbox=items, now=NOW))

    assert without.rung != 5, f"the engine's own flags say a person is needed: {without.clause!r}"
    assert with_it.rung == without.rung, (
        f"the floor answers {with_it.rung} from the inbox and {without.rung} from the job rows")


# ── the positive twins: a LIVE run still asks, and only it ──────────────────────────────────────

async def test_a_later_run_that_is_PARKED_asks_and_the_older_one_does_not(
        _an_engine_with_two_runs_of_one_ticket):
    """The expensive direction. A gate that also dropped the live park would make the inbox
    quiet about the one run that IS holding the floor."""
    _rows, items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, PARKED)

    assert [(i["state"], i["kind"]) for i in items] == [("on_hold", "impediment")], (
        "the inbox did not list the live park, and only it")
    assert [o["key"] for o in items[0]["options"]] == ["resume", "skip"]


async def test_a_later_run_that_is_live_and_cannot_move_still_asks_for_a_stop(
        _an_engine_with_two_runs_of_one_ticket):
    """`wedged` is the engine's OTHER flag for a person, and it is not `attention`: the state is
    `running`. A gate that read `attention` alone would drop the one item whose answer is `stop`."""
    _rows, items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, STUCK)

    assert [(i["state"], i["kind"]) for i in items] == [("running", "wedged")], items
    assert [o["key"] for o in items[0]["options"]] == ["stop"]


# ── the tech-lead says the same thing ───────────────────────────────────────────────────────────

async def test_the_techlead_never_tells_anybody_to_skip_a_run_the_engine_closed(
        _an_engine_with_two_runs_of_one_ticket):
    """The snapshot the tech-lead answers from said `[ORPHANED: ticket closed but workflow still
    parked — skip to clean up]` about the stopped run, once its ticket was closed by the later
    one: the same unexecutable `skip`, offered in a chat instead of on a card."""
    rows, _items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, MERGED)
    closed = [{**r, "ticket_state": "closed", "board": "Done"} for r in rows]

    snap = conversation.state_snapshot(closed)

    assert "ORPHANED" not in snap and "skip" not in snap, snap


async def test_but_a_LIVE_park_on_a_closed_ticket_is_still_orphaned(
        _an_engine_with_two_runs_of_one_ticket):
    """The case the line exists for: the ticket was closed by hand while the run sat parked,
    holding the floor. `skip` is the answer that frees it, and the engine accepts it."""
    rows, _items = await _read(_an_engine_with_two_runs_of_one_ticket, STOPPED, PARKED)
    live, stopped = (conversation.state_snapshot([{**r, "ticket_state": "closed"}])
                     for r in rows)

    assert "ORPHANED" in live, live
    assert "ORPHANED" not in stopped, stopped

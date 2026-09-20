"""A review verdict nobody answers is said so inside the read deadline (found 2026-09-19).

A WORKFLOW QUERY IS ANSWERED BY A WORKER, NOT BY THE ENGINE. #161 bounded every engine read somebody
waits for at `OPENFACTORY_ENGINE_DEADLINE`, and the verdict query was left outside that seam in
both of its readers, made raw. Measured on a throwaway dev server (`temporalio` 1.32.0) with no
worker polling: one raw query gives up at the SDK's own 30.0 s; `conversation._verdicts` took
29.0 s for four jobs (it asked them together); and `/api/inbox` took **116.0 s** to answer `[]`
for four completed jobs that need nobody, because it asked EVERY listed job, one after another.

WHAT IS DOUBLED, AND ONLY THAT. The engine: a client whose handles answer the `verdict` query as
each case says — at once, late, never, or with a refusal. "Never" is a real
`asyncio.Event().wait()`, not a long sleep, so what is measured is this code's bound and nothing
the double does. The clock is real and the deadline is declared short. Everything else is the real
thing: the real `view.review_verdicts`, the real `conversation._verdicts` and `gather_jobs` on the
real standing loop, the real `conversation.answer` with its real semaphore, the real `app.inbox`.

EVERY CASE THAT WAITS HAS ITS OWN HARD BOUND (`_HANGS_AFTER`), so the code this guards against —
which waits for ever on this double — fails the case and does not hang the run.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from openfactory.runtime.temporal import connection, standing
from openfactory.runtime.temporal import view as tv
from openfactory.techlead import conversation

#: The declared deadline, what "inside it" is allowed to cost on eight cores shared with other
#: suites, and when a case stops waiting and calls it a hang.
_DEADLINE = 0.3
_INSIDE = 2.0
_HANGS_AFTER = 4.0

NEVER = object()
APPROVED = {"decision": "approved", "score": 9, "findings": [], "gates": [], "suppressions": []}
REJECTED = {"decision": "rejected", "score": 3, "findings": [], "gates": [], "suppressions": []}


class _Handle:
    def __init__(self, engine: _Engine, wf_id: str) -> None:
        self.engine, self.id = engine, wf_id

    async def query(self, _query, *_a, **_k):
        self.engine.asked.append(self.id)
        how = self.engine.answers.get(self.id, APPROVED)
        try:
            if how is NEVER:
                await asyncio.Event().wait()
            if isinstance(how, float):
                await asyncio.sleep(how)
                return APPROVED
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.engine.stopped.append(self.id)
            raise
        if isinstance(how, Exception):
            raise how
        return how


class _Engine:
    """A client whose workflows answer `verdict` as `answers` says; `asked` and `stopped` record
    which were queried and which queries were cancelled under it."""

    def __init__(self, **answers) -> None:
        self.answers = {_wf(k): v for k, v in answers.items()}
        self.asked: list[str] = []
        self.stopped: list[str] = []

    def get_workflow_handle(self, wf_id, run_id=None):
        return _Handle(self, wf_id)


def _wf(issue: str) -> str:
    return f"openfactory-demo-{issue.lstrip('n')}"


def _job(issue: str, state: str, **more) -> dict:
    return {"workflow_id": _wf(issue), "run_id": f"run-{issue}", "project": "demo",
            "issue": issue, "title": f"ticket {issue}", "state": state, "status": "running",
            "action": None, "wedged": False, "start_time": "2026-09-19T10:00:00+00:00", **more}


def _at_the_gate(issue: str) -> dict:
    return _job(issue, "awaiting_your_merge",
                action={"kind": "merge_wait", "auto": False, "pr_url": f"https://x/pr/{issue}"})


@pytest.fixture(autouse=True)
def _a_short_deadline_and_an_engine_nobody_remembers(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", str(_DEADLINE))
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    tv._answered()
    tv.reset_clients()
    yield
    standing._forget_the_standing_loop()
    tv._answered()
    tv.reset_clients()


def _timed(coro):
    """`(answer, seconds)` — and a hang is a failure of the case, not of the run."""
    async def run():
        started = time.monotonic()
        got = await asyncio.wait_for(coro, _HANGS_AFTER)
        return got, time.monotonic() - started

    try:
        return asyncio.run(run())
    except TimeoutError:
        pytest.fail(f"still waiting after {_HANGS_AFTER}s, with a declared deadline of "
                    f"{_DEADLINE}s — a verdict nobody answers holds whoever asked")


# ── 1. the read itself ──────────────────────────────────────────────────────────────────────────

def test_one_job_that_never_answers_costs_the_deadline_and_ONLY_ITS_OWN_verdict():
    engine = _Engine(n1=REJECTED, n2=NEVER, n3=APPROVED)
    jobs = [_job("1", "pr_open"), _job("2", "pr_open"), _job("3", "pr_open")]

    got, took = _timed(tv.review_verdicts(engine, jobs))

    assert took < _INSIDE, f"three verdicts took {took:.1f}s against a deadline of {_DEADLINE}s"
    assert got == {_wf("1"): REJECTED, _wf("2"): None, _wf("3"): APPROVED}, (
        "the job that did not answer took the others' verdicts with it, or was given one")


def test_the_bound_is_on_the_WHOLE_read_not_on_each_job():
    """Eight silent jobs at one deadline apiece, one after another, is its own page that never
    loads — and so is eight at one deadline apiece that merely overlap badly."""
    engine = _Engine(**{f"n{i}": NEVER for i in range(1, 9)})
    jobs = [_job(str(i), "pr_open") for i in range(1, 9)]

    got, took = _timed(tv.review_verdicts(engine, jobs))

    assert took < _INSIDE, f"eight silent jobs took {took:.1f}s"
    assert took < 3 * _DEADLINE + 1.0, f"{took:.1f}s is the deadline paid more than once"
    assert list(got.values()) == [None] * 8
    assert sorted(engine.asked) == sorted(_wf(str(i)) for i in range(1, 9)), "not all were asked"


def test_they_are_asked_TOGETHER_so_slow_answers_do_not_queue_behind_each_other():
    """Three answers of 0.2 s each fit a 0.3 s deadline only when they are asked at once."""
    engine = _Engine(n1=0.2, n2=0.2, n3=0.2)
    jobs = [_job(str(i), "pr_open") for i in (1, 2, 3)]

    got, _took = _timed(tv.review_verdicts(engine, jobs))

    assert got == {_wf("1"): APPROVED, _wf("2"): APPROVED, _wf("3"): APPROVED}, (
        "the later jobs ran out of a deadline the earlier ones had spent")


def test_a_query_left_behind_is_STOPPED_not_abandoned_on_the_loop():
    """The tech-lead's reads run on a loop that outlives the question (#147). A query still
    asking after the deadline is a task that loop carries, per silent job, per question."""
    engine = _Engine(n1=NEVER, n2=NEVER, n3=APPROVED)

    async def read_then_look():
        await tv.review_verdicts(engine, [_job(str(i), "pr_open") for i in (1, 2, 3)])
        await asyncio.sleep(0.05)   # a cancellation lands on the loop's next turn
        return sorted(engine.stopped)

    stopped, _took = _timed(read_then_look())
    assert stopped == [_wf("1"), _wf("2")], f"queries still asking after the read ended: {stopped}"


def test_a_caller_that_went_away_takes_its_queries_with_it():
    engine = _Engine(n1=NEVER)

    async def ask_and_leave():
        asking = asyncio.ensure_future(tv.review_verdicts(engine, [_job("1", "pr_open")]))
        await asyncio.sleep(0.05)
        asking.cancel()
        await asyncio.gather(asking, return_exceptions=True)
        await asyncio.sleep(0.05)
        return list(engine.stopped)

    stopped, _took = _timed(ask_and_leave())
    assert stopped == [_wf("1")], "the browser left and its query is still asking"


def test_a_refusal_is_UNREADABLE_at_once_and_nobody_waits_the_deadline_for_it(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_ENGINE_DEADLINE", "3")
    engine = _Engine(n1=RuntimeError("query not registered: verdict"), n2=APPROVED)

    got, took = _timed(tv.review_verdicts(engine, [_job("1", "pr_open"), _job("2", "pr_open")]))

    assert got == {_wf("1"): None, _wf("2"): APPROVED}
    assert took < 1.0, f"a refusal that arrived at once was waited on for {took:.1f}s"


def test_a_worker_that_is_gone_is_not_remembered_as_an_ENGINE_that_is_silent():
    """`_within` remembers a timeout and refuses every read for a window. A query nobody answered
    says a WORKER is missing; remembering it as the engine's would refuse the floor and the job
    list each time the inbox met one such job."""
    engine = _Engine(n1=NEVER)

    async def read_then_read_something_else():
        await tv.review_verdicts(engine, [_job("1", "pr_open")])

        async def the_job_list():
            return ["a row"]

        return await tv._within("the job list", the_job_list())

    got, _took = _timed(read_then_read_something_else())
    assert got == ["a row"]
    assert tv.unreachable_for() == 0.0


def test_an_engine_that_IS_remembered_as_silent_is_not_asked():
    engine = _Engine(n1=APPROVED)
    tv._did_not_answer()

    got, took = _timed(tv.review_verdicts(engine, [_job("1", "pr_open")]))

    assert got == {_wf("1"): None}, "unasked must read as could-not-ask, never as no review"
    assert engine.asked == [], "the engine was asked inside the window it is left alone for"
    assert took < 0.2


# ── 2. the tech-lead ────────────────────────────────────────────────────────────────────────────

def test_the_tech_leads_reader_says_UNREADABLE_for_the_silent_job_and_keeps_the_rest():
    engine = _Engine(n1=REJECTED, n2=NEVER)
    jobs = [_at_the_gate("1"), _at_the_gate("2"), _job("3", "running")]

    got, took = _timed(conversation._verdicts(engine, jobs))

    assert took < _INSIDE, f"{took:.1f}s"
    assert got == {"1": REJECTED, "2": {"__unread__": True}}, (
        "`3` is not worth a verdict and must stay ABSENT; `2` was asked and could not be read")
    assert _wf("3") not in engine.asked


@pytest.fixture
def floor(monkeypatch):
    """The real pool and the real standing loop under `gather_jobs`: only `connection.connect`
    (the call that would open a socket) and the job list are stated."""
    engine = _Engine(n1=REJECTED, n2=NEVER)
    rows = [_at_the_gate("1"), _at_the_gate("2")]

    async def _connect():
        await asyncio.sleep(0)
        return engine

    async def _list_jobs(_client, _ns, *, limit=50):
        return [dict(r) for r in rows]

    def _no_tracker(_project):
        raise RuntimeError("this case reads no tracker")

    monkeypatch.setattr(connection, "connect", _connect)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(conversation, "tracker_for", _no_tracker)
    return engine


def _from_threads(n: int, fn) -> tuple[list, float]:
    got: list = [None] * n

    def run(i: int) -> None:
        got[i] = fn()

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(n)]
    started = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, _HANGS_AFTER - (time.monotonic() - started)))
    return got, time.monotonic() - started


def test_the_gatherer_comes_back_from_the_standing_loop_and_the_job_says_UNREADABLE(floor):
    project = SimpleNamespace(name="demo")

    (jobs,), took = _from_threads(1, lambda: conversation.gather_jobs(project))

    assert jobs is not None, (
        f"the asking thread is still waiting after {_HANGS_AFTER}s — the standing loop has no "
        f"deadline of its own, so a read nothing bounds holds it for as long as the read takes")
    assert took < _INSIDE, f"{took:.1f}s"
    by_issue = {j["issue"]: j for j in jobs}
    assert by_issue["1"].get("verdict") == REJECTED
    assert by_issue["2"].get("verdict_unread") is True and "verdict" not in by_issue["2"]
    assert "UNREADABLE" in conversation.state_snapshot(jobs)


def test_THREE_questions_get_through_TWO_slots(floor, monkeypatch, tmp_path):
    """`_ANSWER_SEM` has two slots and a `with` always gives one back — once the answer returns.
    Two questions held on a verdict nobody answers are both slots, and the third question waits
    behind them for as long as they do."""
    from openfactory.adapters import agent as agent_module

    def _no_agent(_project):
        raise RuntimeError("no agent in this case")

    monkeypatch.setattr(conversation, "clone_repo", lambda _p: (tmp_path / "checkout", False))
    monkeypatch.setattr(agent_module, "build_techlead", _no_agent)
    project = SimpleNamespace(name="demo")

    answers, took = _from_threads(3, lambda: conversation.answer(project, "what is on the floor?"))

    assert all(a is not None for a in answers), (
        f"{sum(a is None for a in answers)} of 3 questions had no answer after {_HANGS_AFTER}s")
    assert took < 2 * _INSIDE, f"{took:.1f}s"


# ── 3. the inbox ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def panel(monkeypatch):
    from openfactory.api import app

    def serve(engine: _Engine, rows: list[dict]):
        async def _connect():
            return engine

        async def _list_jobs(_client, _ns, **_k):
            return [dict(r) for r in rows]

        monkeypatch.setattr(tv, "connect", _connect)
        monkeypatch.setattr(tv, "list_jobs", _list_jobs)
        return app.inbox()

    return serve


def test_the_inbox_asks_ONLY_the_jobs_it_is_about_to_show(panel):
    """It asked every listed job before deciding whether the job was an item: four completed jobs
    that need nobody were four queries — each replayed on a worker — for an inbox of `[]`."""
    engine = _Engine()
    rows = [_at_the_gate("1"), _job("2", "on_hold", action={"kind": "impediment", "note": "x"}),
            *[_job(str(i), "merged", status="closed") for i in range(3, 9)]]

    items, _took = _timed(panel(engine, rows))

    assert [i["issue"] for i in items] == ["1", "2"]
    assert sorted(engine.asked) == [_wf("1"), _wf("2")], (
        f"{len(engine.asked)} jobs were asked what their review found, for 2 items")


def test_the_inbox_goes_out_inside_the_deadline_with_the_silent_job_marked_UNREADABLE(panel):
    engine = _Engine(n1=REJECTED, n2=NEVER, n3=NEVER, n4=NEVER)
    rows = [_at_the_gate(str(i)) for i in (1, 2, 3, 4)]

    items, took = _timed(panel(engine, rows))

    assert took < _INSIDE, f"/api/inbox took {took:.1f}s against a deadline of {_DEADLINE}s"
    review = {i["issue"]: i["review"] for i in items}
    assert review["1"]["word"] != "Review unreadable" and review["1"]["level"] == "warn", review["1"]
    for silent in ("2", "3", "4"):
        assert review[silent]["word"] == "Review unreadable", review[silent]
    assert all(set(i["review"]) >= {"level", "word", "clause", "points"} for i in items), (
        "an item went out with a review nobody filled in")


def test_the_inboxs_jobs_are_asked_TOGETHER(panel):
    engine = _Engine(n1=0.2, n2=0.2, n3=0.2)
    rows = [_at_the_gate(str(i)) for i in (1, 2, 3)]

    items, _took = _timed(panel(engine, rows))

    assert [i["review"]["word"] for i in items].count("Review unreadable") == 0, (
        "one after another, the third job ran out of a deadline the first two had spent")


def test_an_inbox_with_nothing_in_it_asks_nobody(panel):
    engine = _Engine()

    items, _took = _timed(panel(engine, [_job("1", "merged", status="closed")]))

    assert items == [] and engine.asked == []

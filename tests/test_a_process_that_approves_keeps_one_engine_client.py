"""A process that delivers N production approvals does not hold N engine clients (GitHub issue #201).

THE SAME SHAPE AS #134 AND #147, ON THE WRITE SIDE. `product/release.py::release` is synchronous —
both of its callers reach it from a thread — so to talk to the engine it opened an event loop and a
client of its own, `asyncio.run(_run())` around `connection.connect()`, once per APPROVAL. Measured
on a throwaway dev server, 2026-09-19, six real jobs parked at the gate, counting this process's
established connections to the engine's port after each delivered approval:

    before:  1, 2, 3, 4, 5, 6      (and 12 after the same six were approved again and REFUSED —
                                    an approval that lands on nothing opened a client too)
    after:   1, 1, 1, 1, 1, 1

THE CLIENT IS THE RELEASE PATH'S OWN, KEPT — NOT THE POOL'S, and section 3 is why. `view.connect()`
holds ONE entry, keyed by the running loop. `release()` runs on the process's standing loop; the
panel reads on its own. Taking the pool's client from the standing loop makes the two take turns
emptying it — measured on the same dev server, a process whose own loop re-reads the job list after
each of six approvals: 13 clients opened, against 7 before any fix and 2 with this one.

EVERY CASE GOES THROUGH THE REAL `release()`, THE REAL STANDING LOOP AND THE REAL `approve_job`.
What is doubled is `connection.connect` — the one call that would open a socket, and the one
`tests/conftest.py::_no_live_durable_engine` forbids — by a counter that hands back an engine
recording every query and signal it is sent, so the cases assert on the ACT and on its order.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
import warnings
from types import SimpleNamespace

import pytest

from openfactory.product import release as rel
from openfactory.runtime.temporal import connection, standing
from openfactory.runtime.temporal import view as tv

FAILED = "OPENFACTORY_RELEASE_SIGNAL_FAILED"


class _Handle:
    def __init__(self, engine: _Engine, wf_id: str) -> None:
        self.engine, self.wf_id = engine, wf_id

    async def query(self, _what):
        await asyncio.sleep(0)
        self.engine.sent.append(("query", self.wf_id))
        return self.wf_id not in self.engine.not_parked

    async def signal(self, _what, *, args):
        await asyncio.sleep(0)
        self.engine.sent.append(("signal", self.wf_id))
        self.engine.signals.append((self.wf_id, list(args)))


class _Engine:
    """What `connection.connect` hands back: ONE client, and everything it was asked to carry."""

    def __init__(self, n: int, log: list, signals: list, not_parked: set) -> None:
        self.n, self.sent, self.signals, self.not_parked = n, log, signals, not_parked

    def get_workflow_handle(self, wf_id: str) -> _Handle:
        self.sent.append(("on client", self.n))
        return _Handle(self, wf_id)


class _Counter:
    """`connection.connect`, counted. It SUSPENDS before it answers, as opening a client does — a
    fake that never yields cannot show two first callers inside the connect at the same moment."""

    def __init__(self) -> None:
        self.calls = 0
        self.sent: list = []
        self.signals: list = []
        self.not_parked: set = set()
        self.refuse_the_next = 0

    async def __call__(self) -> _Engine:
        self.calls += 1
        n = self.calls
        await asyncio.sleep(0.02)
        if self.refuse_the_next:
            self.refuse_the_next -= 1
            raise ConnectionError("the engine refused")
        return _Engine(n, self.sent, self.signals, self.not_parked)

    def clients_used(self) -> set:
        return {n for what, n in self.sent if what == "on client"}


@pytest.fixture
def engine(monkeypatch) -> _Counter:
    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    counter = _Counter()
    monkeypatch.setattr(connection, "connect", counter)
    tv.reset_clients()
    return counter


@pytest.fixture(autouse=True)
def _each_case_is_a_cold_process():
    """The standing loop forgotten before, so every case IS the first approval of its process; and
    stopped after, so no case leaves a thread for the next one to find."""
    standing._forget_the_standing_loop()
    yield
    standing._forget_the_standing_loop()


def _project(name: str = "acme"):
    return SimpleNamespace(name=name, language="pt-BR")


def _approve(issue, **kw) -> tuple[bool, str]:
    return rel.release(_project(), issue, approver="UADM", **kw)


# ── 1. the property from the issue, in both processes that approve ──────────────────────────────

def test_SIX_approvals_open_ONE_engine_client(engine):
    said = [_approve(n) for n in range(1, 7)]

    assert said == [(True, "")] * 6, said
    assert engine.calls == 1, (
        f"six approvals opened {engine.calls} engine clients. Nothing closes one, so a process "
        f"that delivers approvals holds one per approval it ever delivered (#201)")
    assert [wf for wf, _ in engine.signals] == [f"openfactory-acme-{n}" for n in range(1, 7)]
    assert engine.clients_used() == {1}, "the approvals did not all travel on the one client"


def test_an_approval_that_lands_on_NOTHING_opens_no_client_either(engine):
    """Measured with the defect in: six approvals REFUSED at the gate took the process from 6
    connections to 12. A refusal is the commoner answer on a stale thread, not the rarer one."""
    engine.not_parked.update(f"openfactory-acme-{n}" for n in range(1, 7))

    said = [_approve(n) for n in range(1, 7)]

    assert all(ok is False and "não está mais esperando" in why for ok, why in said), said
    assert engine.calls == 1, f"six refused approvals opened {engine.calls} clients"
    assert engine.signals == []


async def test_the_CHAT_path_from_the_threads_the_worker_really_approves_from(engine, monkeypatch):
    """`product/engine.py::_maybe_release`, reached as the worker reaches it: a conversation's turn
    is `asyncio.to_thread(_conversation_turn, …)` — a running loop on the main thread, the
    client's "funcionou" on a pool thread. Four at once first, because a cold worker races itself
    for the first client exactly as a cold panel does."""
    from openfactory.product import engine as turn_engine
    from openfactory.product import followup

    monkeypatch.setattr("openfactory.product.module.may_act", lambda *_a, **_k: True)

    def _funcionou(issue: int) -> str:
        loop = followup.release_of(issue, channel="C1", ts="2026-09-19T10:00:00+00:00",
                                   requirement="0006", where="https://staging.x")
        return turn_engine._maybe_release(_project(), None, loop, "worked", "UADM", "Nina",
                                          "pt-BR", ambiguous=False)

    said = await asyncio.gather(*(asyncio.to_thread(_funcionou, n) for n in range(1, 5)))
    for n in range(5, 8):
        said.append(await asyncio.to_thread(_funcionou, n))

    assert all("subindo para produção" in s for s in said), said
    assert len(engine.signals) == 7
    assert engine.calls == 1, f"seven approvals on the chat path opened {engine.calls} clients"


async def test_the_ACTION_path_the_panel_approves_on(engine, monkeypatch):
    """`actions/catalog.py::_product_release`, the row a click performs — the real one, on a
    running loop, which is what the panel is."""
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    monkeypatch.setattr(catalog, "_product_module", lambda _n, **_kw: (None, _project(), None))
    monkeypatch.setattr("openfactory.product.module.may_act", lambda *_a, **_k: True)
    by = Actor(id="UADM", display="Ana", admin=True)

    outcomes = [await catalog._product_release(project="acme", issue=str(n), by=by, yes=True)
                for n in range(1, 7)]

    assert all(o.ok for o in outcomes), [o.message for o in outcomes]
    assert len(engine.signals) == 6
    assert engine.calls == 1, f"six approvals on the action path opened {engine.calls} clients"


# ── 2. the safety of the call survives, on the kept client ──────────────────────────────────────

def test_the_gate_is_RE_ASKED_before_every_signal_not_only_the_first(engine):
    """The whole safety of `release()`. A kept client must not become a kept ANSWER: the question
    is put to the engine again for each approval, and the signal follows it, never precedes it."""
    _approve(1)
    _approve(2)

    acts = [(what, wf) for what, wf in engine.sent if what != "on client"]
    for n in (1, 2):
        wf = f"openfactory-acme-{n}"
        mine = [what for what, which in acts if which == wf]
        assert mine == ["query", "query", "signal"], (
            f"#{n}: the gate is asked here and again by `approve_job`, then signalled — got {mine}")


def test_a_job_released_by_SOMEBODY_ELSE_in_between_is_not_signalled(engine):
    assert _approve(1) == (True, "")
    engine.not_parked.add("openfactory-acme-2")

    ok, why = _approve(2)

    assert ok is False and "não está mais esperando" in why, (ok, why)
    assert [wf for wf, _ in engine.signals] == ["openfactory-acme-1"], (
        "a stale yes was signalled to a job that was no longer waiting for it")


def test_a_connect_that_FAILED_is_said_honestly_and_is_not_kept(engine, caplog):
    """NEVER raises, and never remembers a refusal: the engine that was down for one approval must
    not make every later one fail for the life of the process."""
    engine.refuse_the_next = 1
    with caplog.at_level(logging.ERROR, logger="openfactory.product"):
        ok, why = _approve(1)

    assert ok is False and "Nada subiu" in why, (ok, why)
    assert any(FAILED in r.getMessage() for r in caplog.records), (
        "a client approved a production release, it did not happen, and no log says so")

    assert _approve(1) == (True, ""), "the approval after a failed connect was not delivered"
    assert engine.calls == 2 and len(engine.signals) == 1


async def test_a_caller_that_IS_running_a_loop_gets_the_honest_sentence_not_a_traceback(
        engine, caplog):
    """Both callers reach `release()` from a thread. One that ever called it from a running loop
    would block that loop on the standing one — so `from_a_thread` refuses it by name, and what
    the person reads is `release()`'s own sentence, with the reason in the log. And NOTHING WAS
    STARTED for the caller that was refused: `asyncio.run(_run())` made the coroutine first and
    left it for the collector to complain about."""
    with warnings.catch_warnings(record=True) as seen, \
            caplog.at_level(logging.ERROR, logger="openfactory.product"):
        warnings.simplefilter("always")
        ok, why = _approve(1)
        gc.collect()

    assert ok is False and "Nada subiu" in why, (ok, why)
    said = [r.getMessage() for r in caplog.records if FAILED in r.getMessage()]
    assert said and "event loop" in said[0], said
    assert engine.calls == 0 and engine.signals == []
    never_awaited = [str(w.message) for w in seen if "never awaited" in str(w.message)]
    assert not never_awaited, never_awaited


# ── 3. why the client is the release path's own, and not the pool's ─────────────────────────────

async def test_a_process_that_READS_on_its_own_loop_keeps_its_client_through_every_approval(
        engine):
    """The panel. Its loop reads through `view.connect()`'s pool — ONE entry, keyed by the running
    loop — and an approval arrives on a thread, so it runs on the standing loop. Taken from the
    pool there, the approval's client evicts the panel's and the panel's next read evicts the
    approval's: 13 clients for six approvals on a real dev server, where this holds two."""
    reads = [await tv.connect()]
    for n in range(1, 7):
        assert await asyncio.to_thread(_approve, n) == (True, "")
        reads.append(await tv.connect())        # the floor re-read that follows every frame

    assert len({id(c) for c in reads}) == 1, "an approval evicted the client the panel reads with"
    assert engine.calls == 2, (
        f"{engine.calls} clients for a panel that read and approved six times — one to read with "
        f"and one to approve with is what it should hold")
    assert reads[0].n not in engine.clients_used(), "an approval travelled on the pool's client"


def test_an_approval_is_still_ATTEMPTED_when_a_read_ran_out_of_time_a_moment_ago(engine):
    """`view.connect()` refuses at once while the engine is remembered as silent (#159) — right
    for a read the page asks again in two seconds, and wrong for a person's yes: it would be
    answered "nothing went up" without the engine having been asked at all."""
    tv._did_not_answer()
    try:
        assert tv.unreachable_for() > 0
        assert _approve(1) == (True, "")
    finally:
        tv._answered()


# ── 4. a kept client is kept only while it is still the right one ───────────────────────────────

def test_a_ROTATED_credential_is_not_approved_with_the_old_client(engine, monkeypatch):
    """A client holds the credential it was opened with. `fingerprint()` is how this tree says
    "the same engine, as the same caller" — the pool's own key, asked of the same function."""
    _approve(1)
    monkeypatch.setenv("TEMPORAL_API_KEY", "rotated-in-place")
    _approve(2)
    _approve(3)

    assert engine.calls == 2, f"{engine.calls} clients across one rotation — expected the old, " \
                              f"then ONE new"
    assert [n for what, n in engine.sent if what == "on client"][-1] == 2


def test_a_standing_loop_that_was_REPLACED_is_not_handed_the_dead_loops_client(engine):
    """`standing.py` replaces a loop that ended. A client made on the loop that died, handed to
    its replacement, is the broken call the pool's loop key exists to prevent."""
    _approve(1)
    first = standing._STANDING.thread
    standing._STANDING.loop.call_soon_threadsafe(standing._STANDING.loop.stop)
    first.join(timeout=5)
    assert not first.is_alive()

    assert _approve(2) == (True, "")
    assert engine.calls == 2 and engine.clients_used() == {1, 2}


def test_TWO_first_approvals_at_once_open_ONE_client(engine):
    start = threading.Barrier(2)
    said = []

    def _yes(n: int) -> None:
        start.wait(timeout=5)
        said.append(_approve(n))

    people = [threading.Thread(target=_yes, args=(n,)) for n in (1, 2)]
    for t in people:
        t.start()
    for t in people:
        t.join(timeout=10)

    assert said == [(True, ""), (True, "")], said
    assert engine.calls == 1, f"two first approvals opened {engine.calls} clients"


def test_the_kept_client_does_not_OUTLIVE_its_test(engine):
    """The seam `tests/conftest.py` clears before every test, as it clears the pool: a module
    global holding one test's fake engine is the next test's engine under `pytest-randomly`."""
    import conftest

    _approve(1)
    # THE FIXTURE'S OWN FUNCTION, run — not its source, read: what matters is that running it
    # leaves no client behind, whatever it calls to do that.
    conftest._an_engine_client_does_not_outlive_its_test.__wrapped__()
    _approve(2)

    assert engine.calls == 2, "the fixture ran and the next test would still hold this one's engine"

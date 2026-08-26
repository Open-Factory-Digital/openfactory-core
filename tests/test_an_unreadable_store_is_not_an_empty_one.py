"""A store that will not answer is never read as a store with nothing in it (#126).

Sweep B3, 2026-08-16. `messages.read` caught its own failures and returned `[]`, with a comment
saying precisely why that was wrong — *"a panel with no messages and a panel that cannot read them
look identical to an operator"*. The guard was DEAD CODE: `observability/query.records_of_kind` and
`sqlite_metrics._query` had both already swallowed to `[]`, one and two layers below, so nothing
could ever reach that `except`.

WHAT IT COST WAS BOTH HALVES OF EVERY HUMAN GATE ON THE PANEL, from one exception nobody saw:

    the ask half     `pending()` folded an empty history, so questions waiting on a person simply
                     were not in the inbox. A factory with nothing to say.
    the answer half  a click on a question the operator could still see came back
                     **409 "that question is not open — it was answered already"**. The platform
                     inventing a decision, in a sentence that blames the person for it.

This is the family the codebase keeps paying into: `_waiting_on_a_human` returning an empty floor
that was really a TypeError (and swallowing the pilot's merge), the ticket and board reads in
`techlead/conversation.py`, `board_index`'s `None` vs `{}`. On any path that gates a human
decision, "nothing" and "could not look" must never be the same value.

THE ASYMMETRY IS DELIBERATE. Reads raise; WRITES keep the never-raise rule. A factory that cannot
record what it said must still say it — a lost write costs a row, and a read that lies costs a
decision.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.memory import messages as ch
from openfactory.observability.query import StoreUnreadable

PROJECT = "podbeam"


def _blind(monkeypatch):
    """Every path `messages.read` can take, refusing to answer."""
    def boom(*_a, **_kw):
        raise StoreUnreadable("the store did not answer")

    monkeypatch.setattr("openfactory.observability.query.records_of_kind", boom)


# ── 1. the layers that used to swallow ──────────────────────────────────────────────────────────

def test_the_sqlite_reader_says_it_could_not_read(tmp_path):
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    path = tmp_path / "m.db"
    path.write_bytes(b"definitely not a database" * 20)
    with pytest.raises(StoreUnreadable):
        SqliteMetricsSink(path).records_of_kind(PROJECT, ch.MESSAGE_KIND)


def test_the_kind_reader_propagates_rather_than_returning_empty(monkeypatch, tmp_path):
    from openfactory.observability import query

    class Broken:
        def records_of_kind(self, *_a, **_kw):
            raise OSError("disk gone")

    monkeypatch.setattr("openfactory.api.metrics_view._configured_sink", lambda: Broken())
    with pytest.raises(OSError):
        query.records_of_kind(PROJECT, ch.MESSAGE_KIND)


# The DynamoDB reader's own raise-on-failure and its scan fallback are pinned beside the sink,
# in `tests/test_dynamo_metrics_sink.py` — the reads are METHODS of that sink now, so the guard
# moved with the code rather than dying.


def test_NO_store_configured_is_still_empty_and_not_a_failure(monkeypatch):
    """The one `[]` that must survive: a deployment that never provisioned telemetry has nothing
    to read, not something it cannot read. Conflating those would turn a supported shape into an
    outage on every panel load."""
    from openfactory.observability import query

    monkeypatch.setattr("openfactory.api.metrics_view._configured_sink", lambda: None)
    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE", raising=False)
    assert query.records_of_kind(PROJECT, ch.MESSAGE_KIND) == []


def test_the_message_store_no_longer_has_a_guard_it_can_never_reach():
    """The defect in one assertion. `read` catching `Exception` was correct-looking code that could
    not run, because nothing below it ever raised — so the sentence in its docstring described a
    behaviour the program did not have."""
    src = inspect.getsource(ch.read)
    assert "except Exception" not in src, (
        "`messages.read` is swallowing again — and if the layers below it also swallow, this "
        "`except` is unreachable and the operator gets an empty inbox during an outage")


def test_the_message_store_propagates(monkeypatch):
    _blind(monkeypatch)
    with pytest.raises(StoreUnreadable):
        ch.read(PROJECT)
    with pytest.raises(StoreUnreadable):
        ch.pending(PROJECT)
    with pytest.raises(StoreUnreadable):
        ch.staged(PROJECT)


def test_a_row_of_an_UNKNOWN_KIND_is_dropped_without_taking_the_thread():
    """`_message` gates on `KINDS` — a row of a kind this module cannot write is skipped."""
    import openfactory.observability.query as q

    original = q.records_of_kind
    try:
        q.records_of_kind = lambda *a, **k: [
            {"extra": {"msg_kind": "not-a-kind", "text": "x"}},
            {"extra": {"msg_kind": "said", "text": "picked up #91"}}]
        assert [m.text for m in ch.read(PROJECT)] == ["picked up #91"]
    finally:
        q.records_of_kind = original


def test_a_row_that_RAISES_still_costs_only_itself(monkeypatch):
    """A different failure with a different answer, and the distinction has to survive the fix: one
    unreadable row must not take down the thread the way an unreadable STORE must not be hidden.

    THE ROW HAS TO ACTUALLY RAISE. The first version of this fed a row of an unknown KIND, which
    `_message` rejects on a plain `if` before anything can throw — so the `except` it was written
    to prove was never entered, and narrowing that except to `ZeroDivisionError` left it green. A
    row whose `extra` is not a mapping at all is the shape that reaches it."""
    monkeypatch.setattr(
        "openfactory.observability.query.records_of_kind",
        lambda *a, **k: [{"extra": "this is a string, not a mapping"},
                         {"extra": {"msg_kind": "said", "text": "picked up #91"}}])
    assert [m.text for m in ch.read(PROJECT)] == ["picked up #91"]


# ── 2. what the operator is told ────────────────────────────────────────────────────────────────

@pytest.fixture
def live(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from openfactory.api.app import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKENS", "mine:alice:Alice Ferreira")
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    return TestClient(app, raise_server_exceptions=False)


AUTH = {"Authorization": "Bearer mine"}


def test_the_inbox_says_it_could_not_look_rather_than_showing_an_empty_factory(live, monkeypatch):
    _blind(monkeypatch)
    r = live.get(f"/api/messages/{PROJECT}", headers=AUTH)
    assert r.status_code == 503, r.text
    assert "did not answer" in r.json()["detail"]


def test_answering_a_question_during_an_outage_never_blames_the_person(live, monkeypatch):
    """THE WORST ONE. The operator is looking at a question on their screen, clicks it, and is told
    it was already answered — by nobody, because the pending list came back empty from a store that
    was simply down. A 409 here is the platform inventing a decision and attributing it."""
    _blind(monkeypatch)
    r = live.post(f"/api/messages/{PROJECT}/answer",
                  json={"token": "req-7", "answer": "approve"}, headers=AUTH)

    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert "answered already" not in detail and "not open" not in detail, (
        f"an outage is still reported as somebody else's decision: {detail}")
    assert "nothing was decided" in detail


def test_approving_a_SUGGESTION_during_an_outage_says_so_too(live, monkeypatch):
    """The same gate, one door along (#123). An unreadable store must not read as "the tech-lead is
    not proposing that" — which would refuse a decision the person is looking at."""
    _blind(monkeypatch)
    r = live.post(f"/api/messages/{PROJECT}/suggestion",
                  json={"token": "tl:resume:87:x"}, headers=AUTH)
    assert r.status_code == 503, r.text


def test_a_HEALTHY_empty_store_is_still_an_empty_page_and_not_an_error(live, monkeypatch):
    """The positive twin, and the one that decides whether this is safe to ship: a brand-new
    project has no messages, and turning that into a 503 would break every first load."""
    monkeypatch.setattr("openfactory.observability.query.records_of_kind", lambda *a, **k: [])
    r = live.get(f"/api/messages/{PROJECT}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["messages"] == [] and r.json()["pending"] == []


def test_every_route_that_reads_the_thread_is_covered():
    """Derived from the app itself, so a fourth route added over this store fails here rather than
    shipping the defect this card is about for a third time."""
    import ast

    from openfactory.api import app as api

    tree = ast.parse(inspect.getsource(api))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = ast.unparse(node)
        reads = any(f"channel.{fn}(" in body for fn in ("read", "pending", "staged"))
        if reads and "_readable_store" not in body:
            offenders.append(node.name)
    assert not offenders, (
        f"these routes read the message store and turn an outage into something else: {offenders}")


# ── 3. what must NOT change ─────────────────────────────────────────────────────────────────────

def test_a_WRITE_still_never_raises(monkeypatch):
    """The asymmetry, asserted. A factory that cannot record what it said must still say it: a lost
    write costs a row, a read that lies costs a decision."""
    class Broken:
        def record(self, _rec):
            raise OSError("disk full")

    monkeypatch.setattr("openfactory.runtime.temporal.activities._metrics_sink", lambda: Broken())
    assert ch.say(PROJECT, "picked up #91") is False
    assert ch.told(PROJECT, "oi", by="u1") is False
    assert ch.answer(PROJECT, token="t", answer="approve") is False


def test_the_dashboard_still_degrades_to_no_data(monkeypatch):
    """Nobody decides anything from a cost dashboard in the next thirty seconds, so it keeps the
    old behaviour — but now by CATCHING at its own edge, one line, rather than by never being told
    anything went wrong."""
    from openfactory.api.metrics_view import scan_records

    class Broken:
        def scan(self):
            raise StoreUnreadable("nope")

    monkeypatch.setattr("openfactory.api.metrics_view._configured_sink", lambda: Broken())
    assert scan_records() == []


@pytest.mark.parametrize("module,fn", [("openfactory.memory.store", "read"),
                                       ("openfactory.memory.transcript", "recent")])
def test_the_agents_memory_still_degrades_but_now_ACTUALLY_logs(module, fn, monkeypatch, caplog):
    """Both of these already had a guard and a log line explaining the amnesia. Neither could ever
    run, for the same reason `messages.read`'s could not. Degrading is right here — an agent pass
    that stops because the memory is down is worse than one that proceeds without it — and the log
    it promised is now genuinely written."""
    import importlib

    mod = importlib.import_module(module)
    _blind(monkeypatch)
    with caplog.at_level("WARNING"):
        got = mod.read(PROJECT) if fn == "read" else mod.recent(PROJECT, thread="t")
    assert got == []
    assert caplog.records, (
        f"{module}.{fn} degraded in total silence — the amnesia its own docstring warns about is "
        f"invisible again")

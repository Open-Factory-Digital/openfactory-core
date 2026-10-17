"""Every read a front end makes declares the shape it answers in (#678, slice a).

The front-end contract (`docs/reference/the-front-end-api.md`) names the routes; until this card
each of them answered `-> dict`, so the description FastAPI serves said "an object" and nothing
else, and a screen of one's own had to read `panel.html` to learn what a floor or a board is.

WHAT IS PROVEN HERE:

  · every read route the card lists declares a `response_model` that is a Pydantic model — never
    `dict`, never `Any`;
  · each route, called with a populated bench, answers a body its declared model accepts;
  · AND THE MODEL ADDS NOTHING AND DROPS NOTHING: the body read back through the model is the same
    body. The default front end keeps working because what it is sent did not change.
"""

from __future__ import annotations

import json
from typing import get_args

import pytest
import yaml
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, RootModel

#: The read routes #678 lists: the floor, the jobs, a job's detail, the board, attention, the inbox,
#: the budget, the decisions, the loops, the messages, the product room, its documents, the
#: metrics, whoami and the action catalogue.
LISTED = (
    "/api/floor", "/api/floor/{project}",
    "/api/jobs", "/api/temporal/jobs", "/api/jobs/{project}/{issue}/detail",
    "/api/board/{project}", "/api/attention", "/api/inbox", "/api/budget", "/api/decisions",
    "/api/loops/{project}", "/api/messages/{project}",
    "/api/product/projects", "/api/product/{project}/attachments",
    "/api/product/{project}/documents",
    "/api/metrics", "/api/whoami", "/api/actions",
)


def _route(path: str) -> APIRoute:
    from openfactory.api.app import app

    found = [r for r in app.routes
             if isinstance(r, APIRoute) and r.path == path and "GET" in (r.methods or set())]
    assert len(found) == 1, f"no single GET route at {path}"
    return found[0]


def _model(path: str) -> type[BaseModel]:
    return _route(path).response_model


@pytest.mark.parametrize("path", LISTED)
def test_every_listed_read_declares_a_pydantic_model(path):
    model = _model(path)
    assert isinstance(model, type) and issubclass(model, BaseModel), (
        f"{path} declares {model!r} — a read a front end makes says its shape as a model")


# ── the bench ───────────────────────────────────────────────────────────────────────────────────

DECISION = {"question": "Which database?", "context": "the card names two",
            "options": [{"key": "a", "label": "Postgres", "consequence": "one more service",
                         "recommended": True},
                        {"key": "b", "label": "SQLite", "consequence": "one file"}]}
JOBS = [
    {"project": "acme", "issue": "7", "title": "Pick a database", "status": "running",
     "state": "on_hold", "attention": True, "workflow_id": "openfactory-acme-7",
     "action": {"decision": DECISION, "note": "parked on a decision",
                "parked_at": "2026-10-12T08:00:00Z", "wakes_at": None}},
    {"project": "acme", "issue": "8", "title": "Render the board", "status": "running",
     "state": "awaiting_your_merge", "attention": True, "workflow_id": "openfactory-acme-8",
     "action": {"pr_url": "https://example.test/pr/3", "note": "ready", "can_review": True,
                "adjusts_left": 2}},
    {"project": "acme", "issue": "9", "title": "Quiet", "status": "completed",
     "state": "merged", "attention": False, "cost_usd": 1.5},
]


@pytest.fixture
def bench(monkeypatch, tmp_path):
    """One registered local project with a product role, a board, a journal and an engine double.
    Every read below the routes is the real one where it is local, and a double where it would
    reach an engine, a store or a vendor."""
    from openfactory.floor import reading
    from openfactory.runtime.temporal import view as tv

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    reg = tmp_path / "registry.yaml"
    reg.write_text(yaml.safe_dump({"projects": {"acme": {
        "name": "acme", "repo_path": str(tmp_path), "enabled": True,
        "tracker": {"kind": "local", "repo": "acme"}, "forge": {"kind": "local", "repo": "acme"},
        "ci": {"kind": "none", "repo": "acme"}, "product": {"docs_repo": "acme/docs"}}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))
    for var in ("OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_IDENTITY",
                "OPENFACTORY_PRODUCT_TOKEN", "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(var, raising=False)

    async def _connect(*_a, **_k):
        return object()

    async def _list_jobs(*_a, **_k):
        return [dict(j) for j in JOBS]

    async def _intake(_client=None):
        return {"known": True, "on": True, "note": "", "watchers": {}}

    async def _verdicts(_client, jobs):
        return {str(j.get("workflow_id")): {"verdict": "approved", "findings": []} for j in jobs}

    async def _detail(_client, project, issue, _ns):
        return {"project": project, "issue": issue, "state": "pr_open", "runtime_s": 61.5,
                "cost_usd": 0.42, "pr_url": "https://example.test/pr/3", "why": "a PR is open",
                "review": {"verdict": "approved"}, "gates": [{"name": "pytest", "ok": True}]}

    monkeypatch.setattr(tv, "connect", _connect)
    monkeypatch.setattr(tv, "list_jobs", _list_jobs)
    monkeypatch.setattr(tv, "intake", _intake)
    monkeypatch.setattr(tv, "review_verdicts", _verdicts)
    monkeypatch.setattr(tv, "job_detail", _detail)
    monkeypatch.setattr(tv, "temporal_config", lambda: ("localhost:7233", "default"))
    monkeypatch.setattr(tv, "ui_base", lambda: "")
    monkeypatch.setattr("openfactory.box_prove.health",
                        lambda _p: {"state": "proven", "gate": "", "detail": ""})
    monkeypatch.setattr("openfactory.product.accept.at_the_gates", lambda jobs: [None] * len(jobs))

    # the local board, with one card on it
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.registry import ProjectRegistry

    project = ProjectRegistry().get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    ref = build_tracker(project).create_ticket(title="Render the board", body="## Objective\nX\n")
    build_board(project).set_column(issue=ref, issue_url="", name="TO-DO")

    # a journal, for the local job list and attention
    from openfactory.paths import events_file

    journal = events_file(project, "12")
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        '{"ts": "2026-10-12T08:00:00Z", "kind": "state", "message": "on_hold"}\n'
        '{"ts": "2026-10-12T08:01:00Z", "kind": "pr", "message": "", '
        '"data": {"url": "https://example.test/pr/12", "cost_usd": 0.5}}\n', encoding="utf-8")

    # what the agents wait on, and what the factory said
    from openfactory.memory import ledger, messages

    loop = ledger.Loop(kind="review_finding", subject="acme#12", owner="techlead",
                       about="a finding", ts="2026-10-12T08:00:00Z",
                       context={"pr": "https://example.test/pr/12"})
    monkeypatch.setattr(ledger, "waiting", lambda _loops: [loop])
    said = messages.Message(kind="said", text="#12 is parked", ts="2026-10-12T08:00:00Z",
                            channel="panel")
    asked = messages.Message(kind="ask", text="register it?", ts="2026-10-12T08:02:00Z",
                             token="req-7", approve="Yes", reject="No")
    monkeypatch.setattr(messages, "read", lambda _p, *a, **k: [said, asked])
    monkeypatch.setattr(messages, "pending", lambda _p, *a, **k: [asked])
    monkeypatch.setattr(messages, "staged", lambda _p, *a, **k: (asked, ""))
    monkeypatch.setattr(messages, "read_suggestion",
                        lambda _m: ("adjust", "12", {"instruction": "rename it"}))

    # the product's documents and a room's files
    from openfactory.product import attachments
    from openfactory.product.documents.store import Store

    monkeypatch.setattr(Store, "index", lambda _self: {
        "checked_at": "2026-10-12T08:00:00Z",
        "paths": {"spec.md": {"readable": True, "title": "Spec", "type": "markdown"},
                  "scan.pdf": {"readable": False, "type": "pdf", "reason": "protected"},
                  "notes.md": {"readable": True, "title": "Notes", "type": "markdown",
                               "audience": "internal"}}})
    monkeypatch.setattr("openfactory.api.product_chat.conversation_for",
                        lambda *_a, **_k: ("room:acme", ""))
    monkeypatch.setattr(attachments, "listed_in", lambda *_a, **_k: [
        {"id": "f1", "name": "brief.pdf", "type": "pdf", "size": 1024, "filed": True}])

    # the trackers' budgets and the metrics store. TWO TRAPS FOR A MODEL THAT CHANGES A BODY: a key
    # no model names (`used`), which a model that ignored extras would drop, and integral numbers
    # in `int | float` fields (`remaining`, `limit`), which a `float` field would send as `4900.0`
    monkeypatch.setattr(reading, "budgets", lambda projects=None: [
        {"kind": "github", "projects": ["acme"], "state": "ok", "vendor": "github",
         "resource": "graphql", "remaining": 4900, "limit": 5000, "reset_epoch": 1760256000,
         "floor": 200, "reset_at": "08:00", "used": 100}])
    monkeypatch.setattr("openfactory.api.metrics_view.scan_all_or_raise", lambda *_a: [
        {"pk": "acme", "kind": "agent_run", "ticket": "12", "ts": "2026-10-12T08:00:00Z",
         "role": "executor", "model": "opus", "harness": "claude", "cost_usd": 0.5,
         "num_turns": 9, "input_tokens": 1000, "output_tokens": 200, "tool_calls": 12},
        {"pk": "acme", "kind": "job", "ticket": "12", "ts": "2026-10-12T08:05:00Z",
         "state": "merged", "title": "Render the board", "wall_s": 300}])

    reading.forget_intake()
    yield TestClient(__import__("openfactory.api.app", fromlist=["app"]).app)
    reading.forget_intake()


#: Each listed route, as the bench calls it: (the route, the address it is called at).
CALLED = (
    ("/api/floor", "/api/floor"),
    ("/api/floor/{project}", "/api/floor/acme"),
    ("/api/jobs", "/api/jobs"),
    ("/api/temporal/jobs", "/api/temporal/jobs"),
    ("/api/jobs/{project}/{issue}/detail", "/api/jobs/acme/12/detail"),
    ("/api/board/{project}", "/api/board/acme?card=1&pr=1"),
    ("/api/attention", "/api/attention"),
    ("/api/inbox", "/api/inbox"),
    ("/api/budget", "/api/budget"),
    ("/api/decisions", "/api/decisions"),
    ("/api/loops/{project}", "/api/loops/acme"),
    ("/api/messages/{project}", "/api/messages/acme"),
    ("/api/product/projects", "/api/product/projects"),
    ("/api/product/{project}/attachments", "/api/product/acme/attachments?room=1"),
    ("/api/product/{project}/documents", "/api/product/acme/documents"),
    ("/api/metrics", "/api/metrics?project=acme"),
    ("/api/whoami", "/api/whoami"),
    ("/api/actions", "/api/actions"),
)


def test_the_bench_calls_every_listed_route():
    assert {route for route, _at in CALLED} == set(LISTED)


def _as_sent(text: str) -> object:
    """A body as its bytes say it, where `3` and `3.0` differ — `json.loads` alone makes them equal
    in Python, and a model that turned one into the other would pass unseen."""
    return json.loads(text, parse_float=lambda s: ("float", s))


def _undeclared(monkeypatch, route: str, at: str, client: TestClient) -> object:
    """What `at` answers with its route's declaration taken away — the body it sent before #678.
    FastAPI builds a route's handler once, from its `response_field`, so the handler is rebuilt
    without it; `monkeypatch` puts all three back when the read is done."""
    from fastapi.routing import request_response

    found = _route(route)
    with monkeypatch.context() as m:
        m.setattr(found, "response_model", None)
        m.setattr(found, "response_field", None)
        m.setattr(found, "app", request_response(found.get_route_handler()))
        got = client.get(at)
    assert got.status_code == 200, f"{at}, undeclared, answered {got.status_code}: {got.text[:400]}"
    return _as_sent(got.text)


@pytest.mark.parametrize(("route", "at"), CALLED, ids=[at for _r, at in CALLED])
def test_each_listed_read_answers_in_its_declared_model_and_unchanged(bench, monkeypatch, route,
                                                                      at):
    got = bench.get(at)
    assert got.status_code == 200, f"{at} answered {got.status_code}: {got.text[:400]}"
    body = got.json()
    assert body, f"{at} answered an empty body — the bench did not populate it"
    _model(route).model_validate(body)

    assert _as_sent(got.text) == _undeclared(monkeypatch, route, at, bench), (
        f"{at}: declaring its model changed the body it sends")


def _versioned(path: str) -> str:
    return "/api/v1" + path.removeprefix("/api")


@pytest.mark.parametrize(("route", "at"), CALLED, ids=[at for _r, at in CALLED])
def test_each_listed_read_answers_the_same_body_under_api_v1(bench, route, at):
    """#678 slice b: the read is served under `/api/v1/…`, and the unversioned path the default
    front end calls is an alias of it — the same handler, the same model, the same body."""
    assert _model(_versioned(route)) is _model(route), f"{route}: the two forms declare apart"
    old, new = bench.get(at), bench.get(_versioned(at))
    assert old.status_code == new.status_code == 200, (at, old.status_code, new.status_code)

    assert _as_sent(new.text) == _as_sent(old.text), f"{at}: /api/v1 answers another body"


def test_a_degraded_engine_frame_is_still_its_declared_model(bench, monkeypatch):
    """The two shapes a durable-engine read degrades into — no engine to ask — are the same model."""
    from openfactory.api import app as api

    def _absent():
        raise RuntimeError("the runtime extra is not installed")

    monkeypatch.setattr(api, "_temporal", _absent)
    for route, at in (("/api/temporal/jobs", "/api/temporal/jobs"),
                      ("/api/jobs/{project}/{issue}/detail", "/api/jobs/acme/12/detail")):
        body = bench.get(at).json()
        assert body["connected"] is False, body
        assert _model(route).model_validate(body).model_dump(
            mode="json", exclude_unset=True) == body


def test_a_board_that_is_not_there_is_still_its_declared_model(bench, monkeypatch):
    monkeypatch.setattr("openfactory.adapters.board.build_board", lambda *a, **kw: None)
    body = bench.get("/api/board/acme").json()
    assert body["board"] is False and "pr" not in body, body
    assert _model("/api/board/{project}").model_validate(body).model_dump(
        mode="json", exclude_unset=True) == body


def test_the_declared_models_are_typed_and_not_free_form():
    """A model whose every field is `Any` is `dict` under another name. Each declares its fields."""
    for path in LISTED:
        model = _model(path)
        if isinstance(model, type) and issubclass(model, RootModel):
            # a list of rows: the row is the model that declares the fields
            (model,) = get_args(model.model_fields["root"].annotation)
        assert issubclass(model, BaseModel) and model.model_fields, (
            f"{path}: {model.__name__} declares no field")


# ── a legacy or malformed row is passed through, never refused ──────────────────────────────────
#
# A READ MUST NOT FAIL BECAUSE A PRODUCER ROW LACKS A FIELD OR CARRIES A NULL. Every row below is
# one a store, a journal or the engine can hold today — written before a field existed, or by a
# producer that sets it to `None` — and the route answers it as it did before it declared a model.

def _passes_through(bench, route: str, at: str) -> object:
    got = bench.get(at)
    assert got.status_code == 200, f"{at} answered {got.status_code}: {got.text[:400]}"
    body = got.json()
    assert _model(route).model_validate(body).model_dump(
        mode="json", exclude_unset=True) == body, f"{at}: the row did not pass through as sent"
    return body


def test_a_floor_with_null_and_missing_words_still_answers(bench, monkeypatch):
    from openfactory import floor

    class _Thin:
        def as_dict(self):
            return {"scope": None, "word": None, "short": None, "level": None, "rung": None,
                    "cause": None, "line": None, "census": None, "ok": None}

    monkeypatch.setattr(floor, "state", lambda *_a, **_k: _Thin())
    body = _passes_through(bench, "/api/floor/{project}", "/api/floor/acme")
    assert body["word"] is None and "detail" not in body, body


def test_a_journal_event_with_no_stamp_and_a_null_state_still_lists(bench):
    from openfactory.paths import events_file
    from openfactory.registry import ProjectRegistry

    journal = events_file(ProjectRegistry().get("acme"), "13")
    journal.write_text('{"kind": "state", "message": null}\n', encoding="utf-8")
    body = _passes_through(bench, "/api/jobs", "/api/jobs")
    row = next(j for j in body if j["issue"] == "13")
    assert row["updated"] == "" and row["state"] is None, row


def _engine_lists(monkeypatch, jobs):
    from openfactory.runtime.temporal import view as tv

    async def _list_jobs(*_a, **_k):
        return [dict(j) for j in jobs]

    monkeypatch.setattr(tv, "list_jobs", _list_jobs)


def test_an_engine_row_with_nothing_but_its_park_still_reaches_the_inbox(bench, monkeypatch):
    # a run listed before it carried a project, an issue or a title, parked with a null note
    _engine_lists(monkeypatch, [
        {"status": "running", "state": "on_hold", "attention": True, "workflow_id": "w-1",
         "action": {"decision": {"question": "Which?", "options": [{"key": "a", "label": None}]},
                    "note": None}}])
    body = _passes_through(bench, "/api/inbox", "/api/inbox")
    assert len(body) == 1 and body[0]["project"] is None, body
    assert body[0]["decision"]["options"] == [{"key": "a", "label": None}], body


def test_an_inbox_item_without_a_review_or_an_answer_is_its_model():
    """`review` and `answer` are written by the route today; a row from before either existed, or
    one a channel relays with them null, is still an inbox item."""
    from openfactory.api.read_models import InboxRead

    rows = [{"kind": "decision", "project": "acme"},
            {"kind": "paused", "review": None, "answer": None, "note": None}]
    assert InboxRead.model_validate(rows).model_dump(mode="json", exclude_unset=True) == rows


def test_a_decision_row_with_missing_fields_still_lists(bench, monkeypatch):
    _engine_lists(monkeypatch, [{"action": {"decision": {"question": "Which?"}}}])
    body = _passes_through(bench, "/api/decisions", "/api/decisions")
    assert body == [{"project": None, "issue": None, "title": None, "state": None,
                     "decision": {"question": "Which?"}}], body


def test_a_budget_row_with_no_state_still_answers(bench, monkeypatch):
    from openfactory.floor import reading

    monkeypatch.setattr(reading, "budgets", lambda projects=None: [
        {"kind": "github", "state": None, "vendor": None}])
    _passes_through(bench, "/api/budget", "/api/budget")


def test_a_loop_with_a_null_context_and_unchased_still_lists(bench, monkeypatch):
    from openfactory.memory import ledger

    loop = ledger.Loop(kind="review_finding", subject="acme#12", owner="techlead",
                       about="a finding", ts="2026-10-12T08:00:00Z", chased_ts=None,
                       context=None)
    monkeypatch.setattr(ledger, "waiting", lambda _loops: [loop])
    body = _passes_through(bench, "/api/loops/{project}", "/api/loops/acme")
    assert body["waiting"][0]["context"] is None and body["waiting"][0]["chased"] is None, body


def test_a_message_and_a_suggestion_with_null_fields_still_answer(bench, monkeypatch):
    from openfactory.memory import messages

    said = messages.Message(kind="said", text=None, ts=None, channel=None, token=None,
                            answer=None, by=None)
    asked = messages.Message(kind="ask", text="register it?", ts="2026-10-12T08:02:00Z",
                             token="req-7", approve=None, reject=None)
    monkeypatch.setattr(messages, "read", lambda _p, *a, **k: [said])
    monkeypatch.setattr(messages, "pending", lambda _p, *a, **k: [asked])
    monkeypatch.setattr(messages, "staged", lambda _p, *a, **k: (asked, None))
    monkeypatch.setattr(messages, "read_suggestion", lambda _m: ("not-a-catalogued-action", None,
                                                                 None))
    body = _passes_through(bench, "/api/messages/{project}", "/api/messages/acme")
    assert body["messages"][0]["text"] is None, body
    assert body["pending"][0]["options"][0]["label"] is None, body
    suggestion = body["suggestion"]
    assert suggestion["params"] is None and suggestion["reason"] is None, suggestion


def test_a_card_with_no_title_or_stamp_is_still_on_the_board(bench, monkeypatch):
    from openfactory.adapters.tracker import local as local_tracker
    from openfactory.adapters.tracker.base import TicketSummary

    monkeypatch.setattr(local_tracker.LocalTracker, "list_tickets", lambda *_a, **_k: [
        TicketSummary.model_construct(ref="1", title=None, labels=None, updated_at=None)])
    body = _passes_through(bench, "/api/board/{project}", "/api/board/acme")
    assert body["cards"][0]["title"] is None, body

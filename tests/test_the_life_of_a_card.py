"""The life of a card, on real parts — what every consumer says at each step (ADR-0055 D9).

WHY ON REAL PARTS. Every defect of #411's table was a defect BETWEEN components that each passed
their own tests: the local board that writes no comment is a property of the real row, the
promise that stays open for ever is the real ledger's, the requester who hears nothing is the real
event path's. A suite on doubles passed all five. So these drive a card through a whole life on
the real local tracker and board, the real ledger and card record (the SQLite store a deployment
runs), the real event path up to the conversation's enqueue (`taken_at_the_door`), and the product
role's real read of the board — each step read back by a SECOND process's worth of state: a fresh
module, a fresh port, nothing remembered from the write. Doubles stand in only for what leaves the
machine: the engine's enqueue, and the preview runtime (none is declared, so there is no preview to
take down and the door says so).

    filed → promoted → pull request → discarded → promoted again
    filed → removed
    pull request → closed → reopened
"""

from __future__ import annotations

import asyncio

import pytest
from the_room_heard import taken_at_the_door

#: The person who asked, where they asked, and the product's admin.
ASKER, ADMIN = "ana-asked-77", "po-admin-12"
CONVERSATION = "dm:ana-asked-77"


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a product role, a board `project init` made, and the SQLite
    store a deployment runs — the ledger and the card's record live in it."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product.board import forget_board
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="acme", repo_path=str(tmp_path), language="en",
                         tracker=ProviderRef(kind="local", repo="acme", options={}),
                         product=ProductConfig(docs_repo="acme/docs", admins=[ADMIN])))
    project = registry.get("acme")
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    forget_board()
    yield project
    forget_board()


@pytest.fixture
def heard(monkeypatch) -> list:
    return taken_at_the_door(monkeypatch)


# ── the parts, as a second process reads them ─────────────────────────────────────────────────

def _tracker(project):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(project)


def _board(project):
    from openfactory.adapters.board import build_board

    return build_board(project)


def _column(project, ref: str) -> str:
    from openfactory.adapters.board.base import stage_key
    from openfactory.contracts.refs import canonical_ref

    board = _board(project)
    return stage_key(board, (board.columns() or {}).get(canonical_ref(ref), ""))


def _said_on_the_card(project, ref: str) -> list[str]:
    return [c.body for c in _tracker(project).comments(ref) or []]


def _loops(project, kind: str):
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import fold

    return [x for x in fold(loop_store.read(project.name)) if x.kind == kind]


def _told(heard, *, about: str) -> list[str]:
    return [m.text for m in heard if m.conversation == CONVERSATION and f"#{about}" in m.text]


def _on_the_role_s_board(project, ref: str) -> bool:
    from openfactory.contracts.refs import canonical_ref
    from openfactory.product.board import forget_board
    from openfactory.product.module import ProductModule

    forget_board()                       # a second process remembers nothing of the first
    tickets, error = ProductModule(project)._read_board()
    assert not error, error
    return canonical_ref(ref) in {canonical_ref(t.number) for t in tickets if t.state == "open"}


def _history(project, ref: str):
    from openfactory.contracts.refs import canonical_ref
    from openfactory.lifecycle import record

    return record.read(record.keyed_sink(), project.name, canonical_ref(ref)).rows


def _act(name: str, *, who: str, product: bool = False, **params):
    from openfactory import actions
    from openfactory.policy.authz import PRODUCT

    if product:
        by = actions.Actor(id=who, display=who, via="panel", admin=False,
                           scopes=frozenset({PRODUCT}))
    else:
        by = actions.Actor(id=who, display="Rob", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=by, **params))


# ── the steps the door does not own yet (slices 2 and 3), as their writers do them ────────────

def _filed(project, *, by_the_product_role: bool = True) -> str:
    """A card the product role filed for ASKER from what they asked in CONVERSATION, and the
    delivery it promised them — as `module._open_delivery` records it."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, open_loop
    from openfactory.product.authoring import ticket_body
    from openfactory.product.followup import delivered_to

    tracker = _tracker(project)
    body = (ticket_body(described="a monthly report", reported_by=ASKER, source="chat")
            if by_the_product_role else "## Objective\n\nA monthly report\n")
    ref = tracker.create_ticket(title="A monthly report", body=body, requester=ASKER)
    _board(project).set_column(issue=ref, issue_url="", name="Backlog")
    loop_store.write(project.name, [open_loop(
        DELIVERY, "7", owner="product", ts=now_iso(),
        context={"issues": ref.lstrip("#"), **delivered_to(CONVERSATION, ASKER)})])
    return ref


def _promoted(project, ref: str) -> None:
    _board(project).set_column(issue=ref, issue_url="", name="TO-DO")


def _at_the_merge_gate(project, ref: str) -> None:
    """The box opened the pull request and a person decides the merge (`needs_person`)."""
    from openfactory.contracts import JobState

    _tracker(project).set_state(ref, JobState.PR_OPEN, needs_person=True)


def _a_question_on_the_card(project, ref: str) -> None:
    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CARD_QUESTION, open_loop

    loop_store.write(project.name, [open_loop(
        CARD_QUESTION, ref.lstrip("#"), owner="techlead", about="h1", ts=now_iso(),
        context={"requester": ASKER})])


# ── filed → promoted → pull request → discarded → promoted again ──────────────────────────────

def test_a_discarded_pull_request_sends_the_card_back_and_every_consumer_says_so(deployment,
                                                                                 heard):
    from openfactory.lifecycle import CardEvent, transition
    from openfactory.memory.ledger import DELIVERY

    ref = _filed(deployment)
    _promoted(deployment, ref)
    _at_the_merge_gate(deployment, ref)
    assert _column(deployment, ref) == "needs_action"

    moved = transition(deployment, ref, CardEvent.DISCARDED, by="Rob", why="not this quarter")

    assert moved.ok and moved.recorded, moved
    assert not moved.failed, moved.failed
    # the column (#409): back in the backlog
    assert _column(deployment, ref) == "backlog"
    # the comment, on the LOCAL board too, saying who and why — the row that dropped `reason`
    [said] = _said_on_the_card(deployment, ref)
    assert "Rob" in said and "not this quarter" in said and "backlog" in said
    # the promise: still owed, and the card's own line says where the card is (D10, D11)
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.waiting
    card = _act("product_board", who=ASKER, product=True, project="acme",
                card=ref).data["card"]
    assert "backlog" in card["owed"] and "delivered" in card["owed"], card["owed"]
    # the requester, once, in the conversation they asked in (#401)
    [told] = _told(heard, about=ref.lstrip("#"))
    assert "back in the backlog" in told
    # the role's own read of the board (#393), as another process makes it
    assert _on_the_role_s_board(deployment, ref)
    # the record: one transition, every effect applied
    [row] = _history(deployment, ref)
    assert row.event == "discarded" and row.before == "waiting_on_a_person"
    assert row.after == "backlog"

    # the sweep finds nothing to do, and says nothing twice
    from openfactory.lifecycle import converge

    assert converge(deployment) == []
    assert len(_told(heard, about=ref.lstrip("#"))) == 1

    _promoted(deployment, ref)
    card = _act("product_board", who=ASKER, product=True, project="acme",
                card=ref).data["card"]
    assert card["owed"] and "backlog" not in card["owed"], card["owed"]


# ── filed → removed ─────────────────────────────────────────────────────────────────────────────

def test_a_removed_card_cancels_what_was_promised_about_it_and_its_requester_is_told(deployment,
                                                                                     heard):
    from openfactory.memory.ledger import CANCELLED, CARD_QUESTION, DELIVERY

    ref = _filed(deployment)
    _a_question_on_the_card(deployment, ref)

    out = _act("product_withdraw_card", who=ASKER, product=True, project="acme",
               number=ref, reason="asked twice", remove=True)

    assert out.ok, out.message
    # the card is gone, from the board and from the role's own read of it (#393)
    with pytest.raises(KeyError):
        _tracker(deployment).get_ticket(ref)
    assert not _on_the_role_s_board(deployment, ref)
    # the promise is cancelled, never left open for ever, and so is the question on it
    [delivery] = _loops(deployment, DELIVERY)
    assert not delivery.waiting and delivery.outcome == CANCELLED
    [question] = _loops(deployment, CARD_QUESTION)
    assert not question.waiting and question.outcome == CANCELLED
    # the requester, once
    [told] = _told(heard, about=ref.lstrip("#"))
    assert "will not be built" in told
    # nothing waits on anybody about it any more
    assert _act("product_agenda", who=ADMIN, project="acme").data["items"] == []
    [row] = _history(deployment, ref)
    assert row.event == "removed" and not [o for o in row.outcomes.values()
                                           if o[0].startswith("failed")]


# ── pull request → closed → reopened ──────────────────────────────────────────────────────────

def test_a_card_closed_and_reopened_takes_its_promise_with_it_both_ways(deployment, heard):
    from openfactory.memory.ledger import CANCELLED, DELIVERY

    ref = _filed(deployment, by_the_product_role=False)
    _promoted(deployment, ref)
    _at_the_merge_gate(deployment, ref)

    out = _act("card_close", who="rob", project="acme", issue=ref, reason="out of scope")

    assert out.ok, out.message
    assert out.data["delivered"] is False
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == CANCELLED
    assert "will not be built" in _told(heard, about=ref.lstrip("#"))[0]

    out = _act("card_reopen", who="rob", project="acme", issue=ref)

    assert out.ok, out.message
    assert _tracker(deployment).get_ticket(ref).state == "open"
    assert _column(deployment, ref) == "backlog"
    # the promise waits on the card again — a new one: the ledger never revives a closed loop
    waiting = [x for x in _loops(deployment, DELIVERY) if x.waiting]
    assert [x.context["issues"] for x in waiting] == [ref.lstrip("#")]
    told = _told(heard, about=ref.lstrip("#"))
    assert len(told) == 2 and "reopened" in told[1]
    assert [r.event for r in _history(deployment, ref)] == ["closed", "reopened"]
    said = _said_on_the_card(deployment, ref)
    assert any("Reopened by" in s for s in said), said

    # and a reopen of an OPEN card is refused, with nothing changed (the defect the table ends)
    again = _act("card_reopen", who="rob", project="acme", issue=ref)
    assert not again.ok and again.code == "conflict", again.message
    assert [r.event for r in _history(deployment, ref)] == ["closed", "reopened"]


# ── what the person sees: Pending, and what is owed on the card (D11) ────────────────────────

def test_pending_is_what_waits_on_the_person_and_what_is_owed_is_on_the_card(deployment):
    """The agenda listed what the role OWES beside what it WAITS FOR — "I will tell you when it is
    fixed" for a card nobody would fix, on a list the person could do nothing with. Pending is what
    waits on them, each item opening where it is answered; a promise is one line on its card."""
    import pathlib

    from openfactory.adapters.board_db import now_iso
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import ACCEPTANCE, open_loop
    from openfactory.product.followup import delivered_to

    ref = _filed(deployment)
    loop_store.write(deployment.name, [open_loop(
        ACCEPTANCE, "6", owner="product", ts=now_iso(),
        context={"issues": "41", **delivered_to("", ASKER)})])

    out = _act("product_agenda", who=ADMIN, project="acme")

    assert out.ok, out.message
    [item] = out.data["items"]
    assert item["kind"] == ACCEPTANCE and item["direction"] == "awaited"
    assert (item["card"], item["opens"]) == ("41", "conversation")
    assert "waiting for" in out.data["about"] and "owes" not in out.data["about"]
    owed = _act("product_board", who=ASKER, product=True, project="acme",
                card=ref).data["card"]["owed"]
    assert "will tell you in the conversation when this is delivered" in owed
    # NEW TO THE BACKLOG IS NOT BACK IN IT: a card just filed lands there, and nobody's work on it
    # stopped — found on the first live run, where a defect reported a minute earlier was said to
    # have had its work stopped
    assert "stopped" not in owed and "backlog" not in owed, owed

    page = (pathlib.Path(__file__).resolve().parent.parent / "openfactory" / "api"
            / "panel.html").read_text(encoding="utf-8")
    assert 'tab("agenda","Pending"' in page
    assert 'data-act="pvPendingCard"' in page and "pvPendingCard: d=>{pvTab(\"board\")" in page
    assert "c.owed?" in page, "the card does not draw what the role owes about it"


# ── a card nobody asked for, and a promise shared by two cards ────────────────────────────────

def test_a_card_nobody_asked_for_tells_nobody_when_it_goes(deployment, heard):
    """An operator's own card, written on the board, with no conversation behind it: the product's
    room is not told what the operator did on the board."""
    tracker = _tracker(deployment)
    ref = tracker.create_ticket(title="Tidy the logs", body="## Objective\n\nTidy them\n")
    _board(deployment).set_column(issue=ref, issue_url="", name="Backlog")

    out = _act("card_remove", who="rob", project="acme", issue=ref, reason="not needed")

    assert out.ok and out.data["told"].startswith("nobody to tell"), out.data
    assert heard == [], [m.text for m in heard]


def test_a_delivery_of_two_cards_waits_on_the_one_that_remains_and_is_announced_when_it_is_done(
        deployment, heard):
    """D10: a delivery spanning several cards closes only when what REMAINS is delivered. One card
    removed leaves the promise open for the other; that other already delivered, the hourly round
    announces the delivery — nothing else would before the weekly catch-all."""
    from openfactory.adapters.board_db import now_iso
    from openfactory.adapters.tracker.base import close_ticket
    from openfactory.lifecycle import converge
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import DELIVERY, open_loop
    from openfactory.product import followup
    from openfactory.product.authoring import ticket_body

    tracker, board = _tracker(deployment), _board(deployment)
    body = ticket_body(described="a monthly report", reported_by=ASKER, source="chat")
    first = tracker.create_ticket(title="The report", body=body, requester=ASKER)
    second = tracker.create_ticket(title="Its export", body=body, requester=ASKER)
    for ref in (first, second):
        board.set_column(issue=ref, issue_url="", name="Backlog")
    loop_store.write(deployment.name, [open_loop(
        DELIVERY, "7", owner="product", ts=now_iso(),
        context={"issues": f"{first.lstrip('#')},{second.lstrip('#')}",
                 **followup.delivered_to(CONVERSATION, ASKER)})])
    close_ticket(tracker, second, "shipped", delivered=True)   # the factory delivered the export

    out = _act("product_withdraw_card", who=ASKER, product=True, project="acme",
               number=first, reason="not needed after all", remove=True)

    assert out.ok, out.message
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.waiting, "a delivery shared with a card still to deliver was cancelled"
    assert followup.cancelled_cards(delivery) == {first.lstrip("#")}
    assert followup.delivered([delivery], {second.lstrip("#")}), (
        "what remains is delivered, and the delivery still waits on the card that went")

    converge(deployment)

    [delivery] = _loops(deployment, DELIVERY)
    assert not delivery.waiting and delivery.outcome == "delivered", delivery
    assert any("ready" in m.text.lower() or "pronto" in m.text.lower()
               for m in heard if m.conversation == CONVERSATION), [m.text for m in heard]


def test_a_caller_that_hands_the_door_only_its_tracker_still_has_the_card_placed(deployment):
    """The product module hands the door a tracker and no board. The board was built only alongside
    a missing tracker, so for it every open card read as one no board places — where the table is
    permissive — instead of the card's own column (found building #413)."""
    from openfactory.lifecycle.ports import Ports
    from openfactory.lifecycle.table import State

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)

    seen = Ports(deployment, tracker=_tracker(deployment)).seen(ref.lstrip("#"))

    assert seen.state is State.WAITING_ON_A_PERSON, seen


# ── the sweeps ask before they act (#413) ────────────────────────────────────────────────────

@pytest.mark.parametrize("delivered,where", [(True, "DONE"), (False, "SKIPPED")])
def test_the_stale_pickup_healer_files_a_closed_card_where_its_close_put_it(deployment, delivered,
                                                                           where):
    """A closed card left in TO-DO was moved to Done whatever it was closed as, so a card withdrawn
    as not planned was filed as delivered work (#411's inventory). Finished work goes to Done, and
    anything else back to Backlog."""
    from openfactory.adapters.tracker.base import close_ticket
    from openfactory.contracts import JobState
    from openfactory.runtime.temporal.activities import _where_a_closed_card_goes

    tracker, board = _tracker(deployment), _board(deployment)
    ref = tracker.create_ticket(title="Export", body="## Objective\n\nExport\n")
    close_ticket(tracker, ref, "done with it", delivered=delivered)
    board.set_column(issue=ref, issue_url="", name="TO-DO")     # the stale card the poller finds

    assert _where_a_closed_card_goes(deployment, tracker, board, ref) is getattr(JobState, where)


# ── the job's own endings go through the door (#413, part 2) ─────────────────────────────────

def _settle(project, ref: str, state: str, note: str = "") -> str:
    """The workflow's `settle_ticket`, called as the worker calls it — and, for a job that ended,
    its one exit after it (`record_outcome`), which journals the outcome and announces what the
    card delivered."""
    from openfactory.runtime.temporal.activities import record_outcome, settle_ticket
    from openfactory.runtime.temporal.io import HoldSyncInput

    inp = HoldSyncInput(project=project.name, issue=ref.lstrip("#"), state=state, note=note)
    settled = asyncio.run(settle_ticket(inp))
    asyncio.run(record_outcome(inp))
    return settled


def test_a_job_that_delivers_on_the_local_board_tells_its_requester_it_is_ready(deployment,
                                                                                heard):
    """#411's inventory marked it "to verify": on the local row a delivered card stayed OPEN in
    Done, and `Ticket.delivered` asks for a closed card — so the requester was never told "it is
    ready" until a person closed the card by hand. Measured true on #413. A job settled DONE is
    `delivered`: the card closes as delivered, and the delivery it completes is announced."""
    from openfactory.memory.ledger import ACCEPTANCE, DELIVERY

    ref = _filed(deployment)
    _promoted(deployment, ref)
    _at_the_merge_gate(deployment, ref)

    assert _settle(deployment, ref, "done", note="Merged, and nothing follows the merge.") == "done"

    ticket = _tracker(deployment).get_ticket(ref)
    assert (ticket.state, ticket.state_reason) == ("closed", "completed")
    [delivery] = _loops(deployment, DELIVERY)
    assert not delivery.waiting and delivery.outcome == "delivered", delivery
    assert [x for x in _loops(deployment, ACCEPTANCE) if x.waiting], "nobody was asked if it works"
    told = [m.text for m in heard if m.conversation == CONVERSATION]
    assert any("is ready" in t for t in told), told
    [row] = _history(deployment, ref)
    assert row.event == "delivered" and row.before == "waiting_on_a_person"
    assert any("nothing follows the merge" in s for s in _said_on_the_card(deployment, ref))


def test_a_parked_job_moves_its_card_and_says_why_on_every_row(deployment):
    from openfactory.contracts import JobState
    from openfactory.runtime.temporal.activities import mark_needs_action
    from openfactory.runtime.temporal.io import HoldSyncInput

    ref = _filed(deployment, by_the_product_role=False)
    _tracker(deployment).set_state(ref, JobState.IMPLEMENTING)

    asyncio.run(mark_needs_action(HoldSyncInput(project="acme", issue=ref.lstrip("#"),
                                                state="on_hold", note="the CI is red twice")))

    assert _column(deployment, ref) == "needs_action"
    assert any("the CI is red twice" in s for s in _said_on_the_card(deployment, ref)), (
        "the local board dropped the park's reason, as `set_state(reason=…)` did")
    [row] = _history(deployment, ref)
    assert row.event == "parked" and row.after == "waiting_on_a_person"


def test_the_jobs_settle_after_a_persons_discard_writes_nothing_twice(deployment, heard):
    """A person's discard goes through the door from the row; the job's own settle arrives after
    it and finds the card where the discard left it — one comment, one transition."""
    from openfactory.lifecycle import CardEvent, transition

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    transition(deployment, ref, CardEvent.DISCARDED, by="Rob", why="not now")

    assert _settle(deployment, ref, "skipped", note="PR closed without merging by Rob") == \
        "already-settled"
    assert len(_said_on_the_card(deployment, ref)) == 1
    assert [r.event for r in _history(deployment, ref)] == ["discarded"]


# ── every pass ends the way the first did (#413 part 3, #448 slice 2) ─────────────────────────

def test_every_adjust_pass_is_told_to_its_requester_numbered_and_none_is_folded_away(deployment,
                                                                                     heard):
    """Measured on a live run (#448): the second pass's "it is ready" was deduplicated away —
    `ready_for_you` is keyed on the card and the pull request, which a pass does not change. Each
    pass is `adjusted` through the door, keyed by its number: told, commented, recorded."""
    from openfactory.runtime.temporal.activities import card_adjusted
    from openfactory.runtime.temporal.io import AdjustedInput

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)

    for n, asked in ((1, "the button on the right"), (2, "and bigger")):
        out = asyncio.run(card_adjusted(AdjustedInput(project="acme", issue=ref.lstrip("#"),
                                                      pr_url="https://x/pr/1", pass_number=n,
                                                      by="ana", instruction=asked)))
        assert "tell:pass_ready=told" in out, out

    told = _told(heard, about=ref.lstrip("#"))
    assert [("Pass 1" in t, "Pass 2" in t) for t in told] == [(True, False), (False, True)], told
    assert all("/p/acme/card/" in t or "/p/acme/preview/" in t for t in told), (
        "the requester was not told where to try it")
    said = _said_on_the_card(deployment, ref)
    assert sum("One more pass, asked for by ana" in s for s in said) == 2, said
    assert [r.event for r in _history(deployment, ref)] == ["adjusted", "adjusted"]


def test_a_pass_with_a_live_preview_tells_its_requester_where_to_try_it(deployment, heard):
    """The preview's own link, not the card's, while the preview is up: `link_for` reads the
    project's NAME, and the callers that handed it the project got "" for every card — so this
    asks for the link the way `link_for` reads it, and holds that it arrives."""
    import time

    from openfactory import preview
    from openfactory.runtime.temporal.activities import card_adjusted
    from openfactory.runtime.temporal.io import AdjustedInput

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    bare = ref.lstrip("#")
    assert preview.record(preview.Preview(project="acme", unit=bare, cards=(bare,),
                                          state=preview.LIVE,
                                          expires_at=int(time.time()) + 3600))

    asyncio.run(card_adjusted(AdjustedInput(project="acme", issue=bare, pr_url="https://x/pr/1",
                                            pass_number=1, by="ana", instruction="bigger")))

    [told] = _told(heard, about=bare)
    assert f"/p/acme/preview/{bare}" in told, told

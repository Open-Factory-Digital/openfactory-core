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
    opened → queued → back to the backlog → corrected, on the board's own rows (#414)
    closed on the vendor's own screen → observed: its promise cancelled, its requester told (#414)
    split → its children filed in the queue → its parent closed, its promise kept → each child
        delivered → the requirement announced once, when the last one is (#414, B1)
    asked a question before the plan → parked → asked again by a retry, said once (#414, B1)
    pull request → ready to try, from the watch and the round, said once (#414, B1)
    the factory's own card closed when its trouble is gone, kept apart from the product's (B1)
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


# ── a card as every card on a board stood before its door owned these steps ─────────────────
#
# Filed and queued by direct writes, with NO RECORD of its own — the shape every card on a live
# board has the day #414 lands, and the one the board sweep must still read (`observe` holds a card
# by its promise when nothing recorded it). Filing and moves through the door are driven below by
# their real rows (`card_create`, `card_move`, `card_edit`).

def _filed(project, *, by_the_product_role: bool = True, promised: str = "7") -> str:
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
        DELIVERY, promised, owner="product", ts=now_iso(),
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


# ── filing, the moves between the operator's columns, and edits through the door (#414) ──────

_A_CARD = ("## Objective\n\nExport the monthly report\n\n## Acceptance criteria\n\n"
           "- the export is a CSV\n")


def test_a_card_opened_queued_and_corrected_on_the_board_goes_through_its_door_every_time(
        deployment):
    """The board's own three verbs (ADR-0049 D6) on the real local board: each is a transition,
    recorded, and the role's read of the board is the board as it now is (#393)."""
    opened = _act("card_create", who="rob", project="acme", title="Export", body=_A_CARD)
    assert opened.ok, opened.message
    ref = opened.data["issue"]
    assert _column(deployment, ref) == "backlog"
    assert _on_the_role_s_board(deployment, ref)

    queued = _act("card_move", who="rob", project="acme", issue=ref, column="TO-DO")
    assert queued.ok and queued.data["event"] == "promoted", queued.message
    assert _column(deployment, ref) == "todo"

    back = _act("card_move", who="rob", project="acme", issue=ref, column="Backlog")
    assert back.ok and back.data["event"] == "reordered", back.message
    assert _column(deployment, ref) == "backlog"

    edited = _act("card_edit", who="rob", project="acme", issue=ref, title="Export it")
    assert edited.ok and edited.data["event"] == "edited", edited.message
    # THE NOTE IS THE DOOR'S COMMENT, once, on the local board too
    [said] = _said_on_the_card(deployment, ref)
    assert "edited the title" in said, said

    assert [(r.event, r.by) for r in _history(deployment, ref)] == [
        (event, "Rob (via panel)") for event in ("filed", "promoted", "reordered", "edited")]


def test_a_person_moves_a_card_only_between_the_backlog_and_the_queue(deployment):
    """The factory's four columns are written by its jobs: a drag that says a card no job holds is
    in progress — or that takes a card a job holds out from under it — is refused, and nothing
    moves or is recorded."""
    from openfactory.contracts import JobState

    ref = _act("card_create", who="rob", project="acme", title="Export", body=_A_CARD
               ).data["issue"]

    into = _act("card_move", who="rob", project="acme", issue=ref, column="In progress")
    assert not into.ok and into.code == "conflict" and "factory's column" in into.message
    assert _column(deployment, ref) == "backlog"

    _tracker(deployment).set_state(ref, JobState.IMPLEMENTING)     # a job took it up
    out = _act("card_move", who="rob", project="acme", issue=ref, column="Backlog")
    assert not out.ok and out.code == "conflict", out.message
    assert _column(deployment, ref) == "in_progress"
    assert [r.event for r in _history(deployment, ref)] == ["filed"]


# ── a change made in the vendor's own interface (D8, #414) ────────────────────────────────────

def _a_hosted_row(project):
    """A DOUBLE OF A HOSTED ROW: the real local store underneath, the capabilities of a hosted
    tracker (no deletion it can tell from a failed read), and a close made on the vendor's own
    screen — `vendor_close` writes the card and runs nothing of ours, the column staying where it
    was, as an issue's project column does on GitHub."""
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.contracts import JobState

    class _Hosted(LocalTracker):
        observes = GitHubIssuesTracker.observes

        def vendor_close(self, ref: str, *, delivered: bool, stays_in: JobState | None = None):
            LocalTracker.close_ticket(self, ref, "closed on the vendor's screen",
                                      delivered=delivered)
            if stays_in is not None:
                LocalTracker.set_state(self, ref, stays_in)

    return _Hosted(project.name)


def test_a_card_closed_on_the_vendors_screen_cancels_its_promise_as_a_close_through_the_platform(
        deployment, heard):
    """#414's scenario. Two cards a requester asked for: one closed through the platform, one
    closed on the vendor's own screen, where no code of ours runs. The board sweep hands the second
    to the door as an observed close, and every consumer says what it said of the first."""
    from openfactory.lifecycle import observe
    from openfactory.lifecycle.ports import Ports
    from openfactory.memory.ledger import CANCELLED, DELIVERY

    hosted = _a_hosted_row(deployment)
    by_us = _filed(deployment, promised="7")
    outside = _filed(deployment, promised="8")

    assert _act("card_close", who="rob", project="acme", issue=by_us, reason="out of scope").ok
    hosted.vendor_close(outside, delivered=False)

    said = observe(deployment, ports=Ports(deployment, tracker=hosted))

    assert [line.split(" ", 1)[0] for line in said] == [f"#{outside.lstrip('#')}"], said
    for ref in (by_us, outside):
        [delivery] = [x for x in _loops(deployment, DELIVERY)
                      if x.context["issues"] == ref.lstrip("#")]
        assert not delivery.waiting and delivery.outcome == CANCELLED, (ref, delivery)
    [told_by_us] = _told(heard, about=by_us.lstrip("#"))
    [told_outside] = _told(heard, about=outside.lstrip("#"))
    assert told_outside.replace(outside.lstrip("#"), "N") == \
        told_by_us.replace(by_us.lstrip("#"), "N"), (told_by_us, told_outside)
    [row] = _history(deployment, outside)
    assert (row.event, row.by, row.facts.get("observed")) == ("closed", "observed", True)
    # NOTHING WRITTEN TO THE CARD: the vendor's own close is the only thing said on it
    assert _said_on_the_card(deployment, outside) == ["closed on the vendor's screen"]

    # the next round finds the record holding it, and says nothing twice
    assert observe(deployment, ports=Ports(deployment, tracker=hosted)) == []
    assert len(_told(heard, about=outside.lstrip("#"))) == 1


def test_a_card_moved_into_the_queue_on_the_vendors_screen_is_promoted_and_one_that_was_split_is_not_withdrawn(  # noqa: E501
        deployment, heard):
    """A move between the operator's columns is a person's too; the close of a card some other card
    was split from is the splitter's — its work lives in its children, and its promise stands."""
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.contracts import JobState
    from openfactory.lifecycle import observe
    from openfactory.lifecycle.ports import Ports
    from openfactory.memory.ledger import DELIVERY

    hosted = _a_hosted_row(deployment)
    queued = _act("card_create", who="rob", project="acme", title="Export", body=_A_CARD
                  ).data["issue"]
    LocalTracker.set_state(hosted, queued, JobState.TODO)          # dragged on the vendor's screen
    split = _filed(deployment, promised="9")
    hosted.create_ticket(title=f"Its first half [auto-split of {split}]", body=_A_CARD)
    hosted.vendor_close(split, delivered=False)

    said = observe(deployment, ports=Ports(deployment, tracker=hosted))

    assert said == [f"#{queued.lstrip('#')} promoted, observed: forget=forgotten"], said
    assert [r.event for r in _history(deployment, queued)] == ["filed", "promoted"]
    [delivery] = [x for x in _loops(deployment, DELIVERY) if x.subject == "9"]
    assert delivery.waiting, "the split card's promise was cancelled"
    assert _told(heard, about=split.lstrip("#")) == []


def test_a_card_closed_outside_while_it_sat_in_the_queue_is_healed_through_its_door(deployment,
                                                                                   heard):
    """The stale-pickup healer (#413) now hands the door what it finds: the card goes where its
    close puts it, and — withdrawn — its promise is cancelled and its requester told, which the
    healer's own move never did."""
    from openfactory.contracts import JobState
    from openfactory.memory.ledger import CANCELLED, DELIVERY
    from openfactory.runtime.temporal.activities import _a_closed_card_in_the_queue

    hosted = _a_hosted_row(deployment)
    ref = _filed(deployment)
    hosted.vendor_close(ref, delivered=False, stays_in=JobState.TODO)

    said = _a_closed_card_in_the_queue(deployment, hosted, _board(deployment), ref)

    assert "Backlog" in said and "moved" in said, said
    ticket = _tracker(deployment).get_ticket(ref)
    assert (ticket.state, ticket.state_reason) == ("closed", "not_planned")
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == CANCELLED
    assert "will not be built" in _told(heard, about=ref.lstrip("#"))[0]
    assert [(r.event, r.by) for r in _history(deployment, ref)] == [("closed", "observed")]


def test_the_healer_leaves_a_split_cards_close_and_its_promise_alone(deployment, heard):
    """The splitter closes the card it split as not delivered; its children carry the work, so its
    promise stands (`triage.delivered_numbers`) — the healer's close is not a person's."""
    from openfactory.contracts import JobState
    from openfactory.memory.ledger import DELIVERY
    from openfactory.runtime.temporal.activities import _a_closed_card_in_the_queue

    hosted = _a_hosted_row(deployment)
    parent = _filed(deployment)
    child = hosted.create_ticket(title=f"Its half [auto-split of {parent}]", body=_A_CARD)
    hosted.link_child(parent, child)
    hosted.vendor_close(parent, delivered=False, stays_in=JobState.TODO)

    said = _a_closed_card_in_the_queue(deployment, hosted, _board(deployment), parent)

    assert "split" in said, said
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.waiting, "the split card's promise was cancelled"
    assert _told(heard, about=parent.lstrip("#")) == [] and not _history(deployment, parent)


def test_the_hourly_round_observes_a_card_closed_outside_the_platform(deployment, heard):
    """On the real local row, through the hourly round's own hook (`techlead_watch`): what the
    record does not hold is observed before what failed is converged."""
    from openfactory.adapters.tracker.base import close_ticket
    from openfactory.memory.ledger import CANCELLED, DELIVERY
    from openfactory.runtime.temporal.activities import _converge_card_transitions

    ref = _filed(deployment)
    close_ticket(_tracker(deployment), ref, "closed by hand, outside", delivered=False)

    _converge_card_transitions(deployment)

    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == CANCELLED
    assert [(r.event, r.by) for r in _history(deployment, ref)] == [("closed", "observed")]


def test_a_row_reports_only_the_changes_it_declares(deployment, heard):
    """A deletion on a hosted row reads as a failed read, so no hosted row declares it, and the
    sweep does not take a card it cannot find for one that was removed. The local row reads its
    own store, and does."""
    from openfactory.adapters.tracker.base import observes
    from openfactory.lifecycle import observe
    from openfactory.lifecycle.ports import Ports
    from openfactory.memory.ledger import CANCELLED, DELIVERY

    class _Silent:
        """A row from before the capability — and a double is not a declaration."""

    assert observes(_Silent()) == frozenset()
    hosted = _a_hosted_row(deployment)
    assert "removed" not in observes(hosted) and "removed" in observes(_tracker(deployment))

    ref = _filed(deployment)
    _tracker(deployment).remove_ticket(ref, "deleted on the vendor's screen", by="someone")

    assert observe(deployment, ports=Ports(deployment, tracker=hosted)) == []
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.waiting, "a row that cannot tell a deletion read one"

    [said] = observe(deployment, ports=Ports(deployment, tracker=_tracker(deployment)))
    assert "removed, observed" in said, said
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == CANCELLED


def test_a_parked_card_is_queued_by_hand_only_when_no_job_waits_on_it(deployment, monkeypatch):
    """A card left in Needs Action with no job on it goes back to the queue by hand; one a job
    still waits on is answered instead, or it would be queued under a job still holding it."""
    from openfactory.actions import catalog
    from openfactory.contracts import JobState

    ref = _act("card_create", who="rob", project="acme", title="Export", body=_A_CARD
               ).data["issue"]
    _tracker(deployment).set_state(ref, JobState.ON_HOLD)
    assert _column(deployment, ref) == "needs_action"

    async def a_job_waits(project, issue):
        return catalog._JobOnTheCard(running=True, waiting_on="a decision", answer_it="resume")

    monkeypatch.setattr(catalog, "_job_on_the_card", a_job_waits)
    held = _act("card_move", who="rob", project="acme", issue=ref, column="TO-DO")
    assert not held.ok and "`resume`" in held.message, held.message
    assert _column(deployment, ref) == "needs_action"

    async def no_job(project, issue):
        return catalog._JobOnTheCard()

    monkeypatch.setattr(catalog, "_job_on_the_card", no_job)
    queued = _act("card_move", who="rob", project="acme", issue=ref, column="TO-DO")
    assert queued.ok, queued.message
    assert _column(deployment, ref) == "todo"


# ── the job's tellings, splits, questions and deliveries through the door (#414, B1) ─────────
#
# A RETRIED ACTIVITY IS THE SAME ACTIVITY: Temporal hands it the same run and activity ids, and the
# door keys what it applies by them (`activities._this_activitys_event`) — so these drive the
# writers inside one `ActivityEnvironment`, whose ids hold still between runs as a retry's do.

_PR = "https://forge.example/acme/pull/12"
_CHILDREN = [{"title": "the report", "objective": "o", "criteria": ["c1"]},
             {"title": "its export", "objective": "o2", "criteria": ["c2"]}]


def _split_into_the_queue(project, ref: str, monkeypatch) -> list[str]:
    """The pre-flight split of `ref`, as the worker runs it, its children sent to the queue."""
    from types import SimpleNamespace

    from temporalio.testing import ActivityEnvironment

    import openfactory.loader
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import SplitInput

    monkeypatch.setattr(openfactory.loader, "load_manifest",
                        lambda project: SimpleNamespace(split_to_todo=True))
    said = ActivityEnvironment().run(acts._do_split, SplitInput(
        project=project.name, issue=ref.lstrip("#"), children=_CHILDREN, reasons="two features"))
    assert said.startswith("split into"), said
    return [c.strip() for c in said.removeprefix("split into").split(",")]


def test_a_split_files_its_children_in_the_queue_and_closes_its_parent_keeping_its_promise(
        deployment, heard, monkeypatch):
    """The children go through their door as `filed`, into TO-DO; the parent as `closed` — split,
    so NOT gone: its work lives in its children, its promise stands, and nobody is told it will
    not be built. One comment on the parent, saying what it was split into."""
    from temporalio.testing import ActivityEnvironment

    from openfactory.memory.ledger import DELIVERY
    from openfactory.runtime.temporal import activities as acts

    parent = _filed(deployment)
    _promoted(deployment, parent)

    children = _split_into_the_queue(deployment, parent, monkeypatch)

    for child in children:
        assert _column(deployment, child) == "todo", child
        assert [(r.event, r.after) for r in _history(deployment, child)] == [("filed", "todo")]
    ticket = _tracker(deployment).get_ticket(parent)
    assert (ticket.state, ticket.state_reason) == ("closed", "not_planned")
    [said] = _said_on_the_card(deployment, parent)
    assert said.startswith("✂️ Split into"), said
    [row] = _history(deployment, parent)
    assert (row.event, row.after) == ("closed", "closed") and row.facts["split_into"]
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.waiting, "the split cancelled the promise its children carry"
    assert _told(heard, about=parent.lstrip("#")) == []

    # A RETRIED FILING IS ANSWERED FROM ITS RECORD: a person took the first child back to the
    # backlog meanwhile, and the retry does not put it in the queue again
    _board(deployment).set_column(issue=children[0], issue_url="", name="Backlog")
    tracker, board = _tracker(deployment), _board(deployment)
    assert ActivityEnvironment().run(acts._file_the_child, deployment, tracker, board,
                                     children[0], column="todo")
    assert _column(deployment, children[0]) == "backlog"
    assert len(_history(deployment, children[0])) == 1


def test_a_closed_card_is_never_filed_into_the_queue(deployment):
    from openfactory.adapters.tracker.base import close_ticket
    from openfactory.runtime.temporal import activities as acts

    tracker = _tracker(deployment)
    ref = tracker.create_ticket(title="Its export", body="## Objective\n\nexport\n")
    close_ticket(tracker, ref, "not needed", delivered=False)

    assert acts._file_the_child(deployment, tracker, _board(deployment), ref,
                                column="todo") is False
    assert _history(deployment, ref) == ()


def test_a_split_cards_promise_is_announced_once_when_its_last_child_is_delivered(
        deployment, heard, monkeypatch):
    """The requirement holds the parent, and the parent's work is in its children: the door that
    delivers a child follows its title to the card it was split from (`loops.deliver`), so the
    requester hears it when — and only when — the last child is delivered."""
    from openfactory.contracts import JobState
    from openfactory.memory.ledger import ACCEPTANCE, DELIVERY

    parent = _filed(deployment)
    first, second = _split_into_the_queue(deployment, parent, monkeypatch)
    for child in (first, second):
        _tracker(deployment).set_state(child, JobState.PR_OPEN, needs_person=True)

    assert _settle(deployment, first, "done") == "done"
    filed, row = _history(deployment, first)
    assert (filed.event, row.event) == ("filed", "delivered")
    assert row.outcome(row.effects.index("loops:deliver")) == "nothing it completes is due yet"
    assert [m.text for m in heard if m.conversation == CONVERSATION] == []

    assert _settle(deployment, second, "done") == "done"
    [delivery] = _loops(deployment, DELIVERY)
    assert not delivery.waiting and delivery.outcome == "delivered", delivery
    assert [x for x in _loops(deployment, ACCEPTANCE) if x.waiting]
    told = [m.text for m in heard if m.conversation == CONVERSATION]
    assert len(told) == 1 and "is ready" in told[0], told


def test_the_card_door_announces_what_a_delivered_card_completes_once_and_a_retry_says_nothing(
        deployment, heard):
    """`delivered` announces the delivery itself now — the job's exit after it, and the same
    settle retried, find it said."""
    from temporalio.testing import ActivityEnvironment

    from openfactory.memory.ledger import DELIVERY
    from openfactory.runtime.temporal.activities import record_outcome, settle_ticket
    from openfactory.runtime.temporal.io import HoldSyncInput

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    inp = HoldSyncInput(project="acme", issue=ref.lstrip("#"), state="done", note="merged")
    env = ActivityEnvironment()

    assert asyncio.run(env.run(settle_ticket, inp)) == "done"

    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == "delivered"
    [row] = _history(deployment, ref)
    assert row.outcome(row.effects.index("loops:deliver")) == "1 announced"
    asyncio.run(env.run(settle_ticket, inp))                 # the same activity, retried
    asyncio.run(record_outcome(inp))                         # the job's one exit, after it
    told = [m.text for m in heard if m.conversation == CONVERSATION]
    assert len(told) == 1 and "is ready" in told[0], told
    assert len(_history(deployment, ref)) == 1


@pytest.mark.parametrize("what_failed", ["the board", "the conversation"])
def test_a_delivery_the_door_could_not_announce_is_announced_by_the_hourly_round(
        deployment, heard, monkeypatch, what_failed):
    """An unread board and a conversation that did not take it are a FAILED effect of a recorded
    transition — applied again by the hourly round, where the weekly catch-all was the only
    second chance."""
    from openfactory.lifecycle import converge
    from openfactory.memory.ledger import DELIVERY
    from openfactory.product import events

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    with monkeypatch.context() as broken:
        if what_failed == "the board":
            broken.setattr(events, "_delivered_now", lambda project: None)
        else:
            broken.setattr(events, "_tell", lambda project, **kw: False)
        assert _settle(deployment, ref, "done", note="merged") == "done"
        [delivery] = _loops(deployment, DELIVERY)
        assert delivery.waiting
        [row] = _history(deployment, ref)
        assert row.outcome(row.effects.index("loops:deliver")).startswith("failed")

    said = converge(deployment)

    assert any("loops:deliver: 1 announced" in line for line in said), said
    [delivery] = _loops(deployment, DELIVERY)
    assert delivery.outcome == "delivered"
    assert len([m for m in heard if m.conversation == CONVERSATION]) == 1


def test_a_question_before_the_plan_parks_the_card_and_a_retry_asks_nothing_twice(deployment):
    """`question_asked`: the question on the card, the park, then the loop its answer closes — and
    the same activity retried is answered from the record: one comment, one loop."""
    from openfactory.lifecycle import CardEvent, transition
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import CARD_QUESTION

    ref = _filed(deployment)
    _promoted(deployment, ref)
    asked = {"requester": ASKER, "poster": "openfactory-bot", "asked_at": "2026-10-04T10:00:00+00:00",
             "paths": "billing/fees.py", "question": "what is the late fee?", "gap_keys": "",
             "repo": "acme", "language": "en"}

    for _ in range(2):
        moved = transition(deployment, ref, CardEvent.QUESTION_ASKED, by="the workflow",
                           facts={"note": f"@{ASKER} — what is the late fee?", "about": "h1",
                                  "asked": asked},
                           event_id="question_asked-run-1")
        assert moved.ok, moved.refused

    assert _column(deployment, ref) == "needs_action"
    assert _said_on_the_card(deployment, ref) == [f"@{ASKER} — what is the late fee?"]
    raw = [x for x in loop_store.read(deployment.name) if x.kind == CARD_QUESTION]
    assert len(raw) == 1 and raw[0].subject == ref.lstrip("#") and raw[0].about == "h1"
    assert raw[0].context["requester"] == ASKER and raw[0].ts == asked["asked_at"]
    assert [r.event for r in _history(deployment, ref)] == ["question_asked"]

    # THE LOOP IS OPENED ONCE however often it is applied — the sweep converging a pending one
    from openfactory.lifecycle import loops

    assert loops.ask(deployment, ref, about="h1", context=asked) == "already waiting on an answer"
    assert len([x for x in loop_store.read(deployment.name) if x.kind == CARD_QUESTION]) == 1


def test_a_question_on_a_card_that_is_gone_asks_nobody(deployment):
    from openfactory.adapters.tracker.base import close_ticket
    from openfactory.lifecycle import CardEvent, transition
    from openfactory.memory.ledger import CARD_QUESTION

    ref = _filed(deployment)
    close_ticket(_tracker(deployment), ref, "not needed", delivered=False)

    moved = transition(deployment, ref, CardEvent.QUESTION_ASKED, by="the workflow",
                       facts={"note": "what is the late fee?", "about": "h1", "asked": {}})

    assert not moved.ok and moved.refused
    assert _said_on_the_card(deployment, ref) == ["not needed"]
    assert _loops(deployment, CARD_QUESTION) == []


def test_a_pull_request_a_person_decides_is_told_once_whichever_of_the_watch_and_the_round_comes_first(  # noqa: E501
        deployment, heard):
    """`pr_opened`, keyed by the pull request: the watch tells the requester it is theirs to try,
    and the round that sees the same gate is answered from the card's record. A second pull
    request is a new thing to try."""
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import ReadyForYouInput

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    bare = ref.lstrip("#")

    assert asyncio.run(acts.tell_the_requester(ReadyForYouInput(project="acme", issue=bare,
                                                                pr_url=_PR)))
    assert acts._pull_requests_waiting(deployment, [(bare, _PR)]) == []
    assert acts._pull_requests_waiting(deployment, [(bare, _PR)]) == []

    [told] = _told(heard, about=bare)
    assert "is ready for you to check" in told, told
    assert [r.event for r in _history(deployment, ref)] == ["pr_opened"]

    assert acts._pull_requests_waiting(deployment, [(bare, _PR + "-2")]) == [bare]
    assert len(_told(heard, about=bare)) == 2


def test_a_card_nobody_is_working_on_has_no_pull_request_to_try(deployment, heard):
    from openfactory.runtime.temporal import activities as acts

    ref = _filed(deployment)                                   # in the backlog

    assert acts._pull_requests_waiting(deployment, [(ref.lstrip("#"), _PR)]) == []
    assert _told(heard, about=ref.lstrip("#")) == [] and _history(deployment, ref) == ()


def test_a_ready_to_try_the_conversation_did_not_take_is_told_by_the_hourly_round(
        deployment, heard, monkeypatch):
    from openfactory.lifecycle import converge
    from openfactory.product import events
    from openfactory.runtime.temporal import activities as acts

    ref = _filed(deployment)
    _at_the_merge_gate(deployment, ref)
    bare = ref.lstrip("#")
    with monkeypatch.context() as broken:
        broken.setattr(events, "_tell", lambda project, **kw: False)
        assert acts._pull_requests_waiting(deployment, [(bare, _PR)]) == []
    [row] = _history(deployment, ref)
    assert row.outcome(row.effects.index("tell:ready_for_you")).startswith("failed")

    converge(deployment)

    assert len(_told(heard, about=bare)) == 1
    assert acts._pull_requests_waiting(deployment, [(bare, _PR)]) == []
    assert len(_told(heard, about=bare)) == 1


def test_the_factorys_own_card_is_closed_through_its_door_with_its_evidence_once(deployment):
    """The factory closes its impediment when the capability works again: `closed`, delivered —
    its work done — and the evidence is the close's one comment, where it was a comment and the
    bare word "completed" beside it."""
    from openfactory.ops import impediment

    cause = impediment.PRODUCT_MOUNT_EMPTY
    impediment._LAST.pop(f"acme|{cause}", None)
    ref = impediment.report(deployment, cause, "entries=0")
    assert ref

    assert impediment.resolved(deployment, cause, "entries=37") is True

    ticket = _tracker(deployment).get_ticket(ref)
    assert (ticket.state, ticket.state_reason) == ("closed", "completed")
    [said] = _said_on_the_card(deployment, ref)
    assert "entries=37" in said, said
    assert [(r.event, r.by) for r in _history(deployment, ref)] == [("closed", "the factory")]
    impediment._LAST.pop(f"acme|{cause}", None)


def test_a_factory_board_of_its_own_keeps_its_cards_record_apart_from_the_products(
        deployment, heard, tmp_path):
    """A declared factory board on another tracker numbers its cards apart: the impediment's close
    is recorded under the factory's own name, and the product's card with the same number is not
    taken by the board sweep for one reopened."""
    from openfactory.contracts.project import FactoryBoard, ProviderRef
    from openfactory.lifecycle import observe, record
    from openfactory.ops import impediment

    product_card = _filed(deployment)
    project = deployment.model_copy(update={"factory_board": FactoryBoard(tracker=ProviderRef(
        kind="local", repo="acme", options={"board_db": str(tmp_path / "factory.db")}))})
    cause = impediment.PRODUCT_NO_CODE
    impediment._LAST.pop(f"acme|{cause}", None)
    ref = impediment.report(project, cause, "no checkout")
    assert ref == product_card, "the two boards were meant to number their cards alike"

    assert impediment.resolved(project, cause, "the checkout is back") is True

    assert _history(deployment, product_card) == ()
    held = record.read(record.keyed_sink(), "acme:factory", ref.lstrip("#")).rows
    assert [r.event for r in held] == ["closed"]
    assert observe(deployment) == []
    assert _told(heard, about=product_card.lstrip("#")) == []
    impediment._LAST.pop(f"acme|{cause}", None)

"""A card nobody has started can be closed — and removed — from the card itself (#384).

WHAT WAS WRONG: a card in Backlog, filed wrong or twice or no longer wanted, could not be dropped
by the person who asked for it. The product view had no card to act on; the floor board's close
refused every card the product role opened ("only the product owner closes it … ask for it in the
conversation"), and nothing anywhere deleted. The cheapest moment to drop work was the one moment a
person could not.

WHAT IS PROVEN HERE:

  · the product view lists the cards and opens one, and a person who asked for a product-opened
    card CLOSES it from the card: it leaves the open columns, and the conversation is told;
  · the same person REMOVES it: the row is gone, the audit line keeps who, when and why, the
    conversation is told, and the next card does not reuse the number;
  · the floor board's close and removal of such a card go THROUGH the product role, not around it;
  · a card the factory has taken up is refused, with the close's own sentence; a person who may not
    act is refused; #150's rule for EDITS is untouched;
  · what "remove" means is the ROW's: a tracker with no removal closes, and says so before and after.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

PANEL = (pathlib.Path(__file__).resolve().parent.parent
         / "openfactory" / "api" / "panel.html").read_text(encoding="utf-8")

#: The person who asked for the card, the product admin, and somebody who is neither.
ASKER, ADMIN, STRANGER = "ana-asked-77", "po-admin-12", "somebody-else-42"


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A registered local project with a product role, whose board `project init` created."""
    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
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
def tracker(deployment):
    from openfactory.adapters.tracker.registry import build_tracker

    return build_tracker(deployment)


@pytest.fixture
def told(monkeypatch) -> list[dict]:
    """What the conversation was told — the door itself is the events suite's."""
    from openfactory.product import events

    said: list[dict] = []
    monkeypatch.setattr(events, "_tell", lambda project, **kw: said.append(kw) or True)
    return said


def _opened_by_product(tracker, board, *, column: str = "Backlog") -> str:
    """A card the product role opened from a request, asked for by ASKER, in `column`."""
    from openfactory.product.authoring import ticket_body

    ref = tracker.create_ticket(title="A monthly report",
                                body=ticket_body(described="um relatório mensal",
                                                 reported_by=ASKER, source="chat"),
                                requester=ASKER)
    board.set_column(issue=ref, issue_url="", name=column)
    return ref


def _on_the_board(tracker, board, *, column: str = "Backlog") -> str:
    ref = tracker.create_ticket(title="Lock the statement", body="## Objective\n\nLock it\n")
    board.set_column(issue=ref, issue_url="", name=column)
    return ref


@pytest.fixture
def board(deployment):
    from openfactory.adapters.board import build_board

    return build_board(deployment)


def _act(name: str, *, who: str = "me", product: bool = False, **params):
    """One action row, driven the way the page drives it — the floor's operator, or a person on
    the product view (a product-scoped credential that is NOT an admin of anything)."""
    from openfactory import actions
    from openfactory.policy.authz import PRODUCT

    if product:
        by = actions.Actor(id=who, display=who, via="panel", admin=False,
                           scopes=frozenset({PRODUCT}))
    else:
        by = actions.Actor(id=who, display="Me", via="panel", admin=True)
    return asyncio.run(actions.perform(name, by=by, **params))


def _open_refs(tracker) -> set[str]:
    return {s.ref for s in tracker.list_tickets(state="open")}


def _audit(ref: str) -> dict | None:
    from openfactory.adapters.board_db import connect
    from openfactory.contracts.refs import canonical_ref

    with connect() as conn:
        row = conn.execute("SELECT * FROM removed_cards WHERE project = 'acme' AND ref = ?",
                           (int(canonical_ref(ref)),)).fetchone()
    return dict(row) if row else None


# ── the product view: the person who asked drops their own card, from the card ─────────────────

def test_the_product_view_lists_the_cards_and_opens_one_with_what_its_controls_do(
        deployment, tracker, board):
    ref = _opened_by_product(tracker, board)

    listed = _act("product_board", who=ASKER, product=True, project="acme")
    assert listed.ok, listed.message
    [card] = [c for c in listed.data["cards"] if c["ref"] == ref.lstrip("#")]
    assert card["opened_by_product"] == "request" and card["started"] is False

    opened = _act("product_board", who=ASKER, product=True, project="acme", card=ref)
    view = opened.data["card"]
    assert view["readable"] and view["removes"] and not view["started"], view
    assert view["words"]["close"] == "Close card"
    assert view["words"]["remove"] == "Remove from the board"
    assert "ask for it in the conversation" not in view["words"]["note"], (
        "the sentence under the card still sends the person away instead of saying what the "
        "control does")
    assert "Close or remove asks it to, from here" in view["words"]["note"], view["words"]


def test_a_product_opened_backlog_card_is_CLOSED_from_the_product_view_by_the_person_who_asked(
        deployment, tracker, board, told):
    """The issue's own acceptance test: the person opens their Backlog card, closes it with a reason
    from the card itself, and the card leaves the open columns — and the conversation hears it."""
    ref = _opened_by_product(tracker, board)

    out = _act("product_withdraw_card", who=ASKER, product=True, project="acme",
               number=ref, reason="filed twice")

    assert out.ok, out.message
    assert out.message.startswith(f"closed #{ref.lstrip('#')}"), out.message
    assert out.data["through"] == "product", "the close did not go through the product role"
    assert ref.lstrip("#") not in _open_refs(tracker), "the card is still in the open columns"
    assert tracker.get_ticket(ref).state == "closed"
    thread = " ".join(c.body for c in (tracker.comments(ref) or []))
    assert "filed twice" in thread and ASKER in thread, (
        f"the closing note does not say who asked for the close, or why: {thread}")
    assert len(told) == 1 and "was closed and left the list of work" in told[0]["text"], told


def test_a_product_opened_backlog_card_is_REMOVED_by_the_person_who_asked(
        deployment, tracker, board, told):
    """Gone from the board, the audit line kept, the conversation told — and the number is never
    handed to the next card."""
    ref = _opened_by_product(tracker, board)

    out = _act("product_withdraw_card", who=ASKER, product=True, project="acme",
               number=ref, reason="changed my mind", remove=True)

    assert out.ok, out.message
    assert out.message.startswith(f"removed #{ref.lstrip('#')}"), out.message
    with pytest.raises(KeyError):
        tracker.get_ticket(ref)
    assert ref.lstrip("#") not in {s.ref for s in tracker.list_tickets(state="all")}
    audit = _audit(ref)
    assert audit and audit["removed_by"] == ASKER and audit["reason"] == "changed my mind", audit
    assert audit["title"] == "A monthly report" and audit["removed_at"], audit
    assert len(told) == 1 and "was removed before anybody started" in told[0]["text"], told
    assert "A monthly report" in told[0]["text"], "the conversation cannot tell which card went"


def test_the_same_card_in_a_STARTED_column_is_refused_with_the_existing_sentence(
        deployment, tracker, board, told):
    from openfactory.contracts import JobState

    ref = _opened_by_product(tracker, board)
    tracker.set_state(ref, JobState.IMPLEMENTING)      # the factory took it up

    for out in (_act("product_withdraw_card", who=ASKER, product=True, project="acme",
                     number=ref, reason="not needed", remove=True),
                _act("card_remove", project="acme", issue=ref, reason="not needed")):
        assert not out.ok
        assert "the factory has taken it up" in out.message, out.message
        assert "Stop the job first" in out.message, out.message
    assert tracker.get_ticket(ref).state == "open" and _audit(ref) is None
    assert not told, "a refused removal told the conversation something happened"


def test_a_card_the_factory_FINISHED_with_is_not_removed_it_is_closed(deployment, tracker, board):
    """Done is past pickup: what shipped is history, which a close keeps and a removal erases."""
    ref = _on_the_board(tracker, board, column="Done")

    out = _act("card_remove", project="acme", issue=ref, reason="tidying")

    assert not out.ok and "can no longer be removed" in out.message, out.message
    assert "Close it instead" in out.message
    assert tracker.get_ticket(ref).state == "open"


def test_a_person_who_may_NOT_act_is_refused(deployment, tracker, board, told):
    ref = _opened_by_product(tracker, board)

    for remove in (False, True):
        out = _act("product_withdraw_card", who=STRANGER, product=True, project="acme",
                   number=ref, reason="not mine but still", remove=remove)
        assert not out.ok, out.message
        assert "only the person who asked for" in out.message, out.message
    assert tracker.get_ticket(ref).state == "open" and _audit(ref) is None
    assert not told


def test_an_OPERATOR_may_drop_a_card_from_the_product_view_too(deployment, tracker, board, told):
    """Decided on #384: no bureaucracy in the first cut. An admin whose credential may enter the
    floor is an operator, and closes or removes from the product view as from the board — while a
    product-scoped credential that is not a product admin still may not."""
    from openfactory import actions

    closing = _opened_by_product(tracker, board)
    removing = _opened_by_product(tracker, board)
    operator = actions.Actor(id="op-1", display="Op", via="panel", admin=True)   # unscoped

    for ref, remove in ((closing, False), (removing, True)):
        out = asyncio.run(actions.perform("product_withdraw_card", by=operator, project="acme",
                                          number=ref, reason="not needed", remove=remove))
        assert out.ok, out.message
    assert tracker.get_ticket(closing).state == "closed"
    assert _audit(removing)["removed_by"] == "op-1"

    scoped = actions.Actor(id="op-2", display="BA", via="panel", admin=True,
                           scopes=frozenset({"product"}))
    other = _opened_by_product(tracker, board)
    out = asyncio.run(actions.perform("product_withdraw_card", by=scoped, project="acme",
                                      number=other, reason="x"))
    assert not out.ok and "only the person who asked for" in out.message, out.message


def test_a_product_admin_may_drop_a_card_somebody_else_asked_for(deployment, tracker, board,
                                                                 told):
    ref = _opened_by_product(tracker, board)

    out = _act("product_withdraw_card", who=ADMIN, product=True, project="acme",
               number=ref, reason="duplicate of another")

    assert out.ok, out.message
    assert tracker.get_ticket(ref).state == "closed"


# ── the floor board: the close no longer refuses, it asks the product role ──────────────────────

def test_the_boards_close_of_a_product_opened_card_goes_THROUGH_the_product_role(
        deployment, tracker, board, told):
    """#150's refusal is gone for a close: the board asks the role, the role writes, the
    conversation is told. The operator is the one the floor row vouches for."""
    ref = _opened_by_product(tracker, board)

    out = _act("card_close", project="acme", issue=ref, reason="not needed")

    assert out.ok, out.message
    assert "only the product owner" not in out.message
    assert out.data["through"] == "product" and out.data["delivered"] is False
    assert tracker.get_ticket(ref).state == "closed"
    assert len(told) == 1, "the conversation the card was asked in was not told"


def test_the_boards_removal_of_a_product_opened_card_goes_through_the_product_role(
        deployment, tracker, board, told):
    ref = _opened_by_product(tracker, board)

    out = _act("card_remove", project="acme", issue=ref, reason="filed wrong")

    assert out.ok, out.message
    assert out.data["through"] == "product" and out.data["removed"] is True
    assert _audit(ref)["removed_by"] == "me"
    assert len(told) == 1


def test_a_board_card_is_removed_from_the_board_with_its_audit_line(deployment, tracker, board,
                                                                    told):
    ref = _on_the_board(tracker, board, column="TO-DO")   # queued, not yet picked up

    out = _act("card_remove", project="acme", issue=ref, reason="asked for by mistake")

    assert out.ok, out.message
    assert "gone from the board" in out.message and out.data["removed"] is True, out.message
    with pytest.raises(KeyError):
        tracker.get_ticket(ref)
    assert _audit(ref)["reason"] == "asked for by mistake"
    assert not told, "a card nobody asked for through the product role told a conversation"


def test_removing_without_a_REASON_is_refused(deployment, tracker, board):
    ref = _on_the_board(tracker, board)

    for out in (_act("card_remove", project="acme", issue=ref, reason="   "),
                _act("product_withdraw_card", who=ADMIN, product=True, project="acme",
                     number=ref, reason="   ", remove=True)):
        assert not out.ok and "why" in out.message, out.message
    assert tracker.get_ticket(ref).state == "open"


def test_an_EDIT_of_a_product_opened_card_is_still_refused(deployment, tracker, board):
    """#150's rule for what a card SAYS is untouched: only removal and close changed."""
    ref = _opened_by_product(tracker, board)

    out = _act("card_edit", project="acme", issue=ref, title="renamed")

    assert not out.ok and "only the product owner changes it" in out.message, out.message


# ── what "remove" means is the row's ────────────────────────────────────────────────────────────

def test_the_local_row_deletes_and_the_next_card_does_NOT_reuse_the_number(deployment, tracker):
    first = tracker.create_ticket(title="one", body="")
    top = tracker.create_ticket(title="two", body="")
    tracker.comment(top, "a thread that goes with it")

    tracker.remove_ticket(top, "filed twice", by=ADMIN)
    after = tracker.create_ticket(title="three", body="")

    assert int(after.lstrip("#")) == int(top.lstrip("#")) + 1, (
        f"{after} reused the number of the removed {top} — every mention of {top} now points at "
        f"somebody else's card")
    assert tracker.comments(top) is None, "the removed card's thread is still answered"
    assert tracker.get_ticket(first).title == "one", "the removal touched another card"


def test_removing_a_card_the_row_does_not_hold_RAISES(deployment, tracker):
    with pytest.raises(KeyError):
        tracker.remove_ticket("#999", "nothing there", by=ADMIN)


def test_a_tracker_that_can_only_CLOSE_says_so_before_and_after(deployment, tracker, board,
                                                               monkeypatch):
    """No `if kind ==`: a row without `remove_ticket` IS a row that can only close. The
    confirmation says the card stays in the history, and so does the answer."""
    from openfactory.adapters.tracker.local import LocalTracker

    monkeypatch.delattr(LocalTracker, "remove_ticket")
    ref = _on_the_board(tracker, board)

    view = _act("product_board", who=ADMIN, product=True, project="acme", card=ref).data["card"]
    assert view["removes"] is False
    assert "can only be closed" in view["words"]["ask_remove"], view["words"]

    out = _act("card_remove", project="acme", issue=ref, reason="filed wrong")
    assert out.ok, out.message
    assert out.data["removed"] is False and "can only close" in out.message, out.message
    again = tracker.get_ticket(ref)
    assert again.state == "closed", "the fallback did not close it"
    assert _closed_reason(ref) == "not_planned", "a removed card was recorded as delivered work"


def _closed_reason(ref: str) -> str:
    from openfactory.adapters.board_db import connect
    from openfactory.contracts.refs import canonical_ref

    with connect() as conn:
        row = conn.execute("SELECT closed_reason FROM cards WHERE project = 'acme' AND ref = ?",
                           (int(canonical_ref(ref)),)).fetchone()
    return (row["closed_reason"] if row else "") or ""


def test_the_seam_decides_by_the_ROW_and_names_no_kind():
    import inspect

    from openfactory.adapters.tracker import base

    source = inspect.getsource(base.remove_ticket) + inspect.getsource(base.removes)
    assert "kind" not in source.replace("what kind", ""), "the seam compares a provider's kind"


def test_the_words_under_the_card_are_in_the_projects_language():
    from openfactory.product.voice import card_controls

    pt = card_controls(opened_by_product=True, started=False, removes=True, language="pt-BR")
    assert pt["close"] == "Fechar cartão" and pt["remove"] == "Remover do quadro"
    assert "daqui mesmo" in pt["note"]
    closes = card_controls(opened_by_product=False, started=False, removes=False, language="pt-BR")
    assert "só podem ser fechados" in closes["ask_remove"]


# ── the page: the controls are drawn on both surfaces ───────────────────────────────────────────

def test_the_drawer_draws_close_and_remove_for_EVERY_open_card_and_edit_only_for_the_boards():
    controls = PANEL.split("function _bcontrols(c, where){")[1].split("\nfunction ")[0]
    assert "${on.ask}('close')" in controls and "${on.ask}('remove')" in controls
    assert "c.started ?" in controls, "Remove is offered on a card the factory has taken up"
    assert "w.note" in controls and "w.ask_remove" in controls and "w.ask_close" in controls, (
        "the words are the page's own instead of the card's, in the project's language")
    close_at = controls.index("${on.ask}('close')")
    assert "c.opened_by_product" not in controls[controls.index("const edit"):close_at].split(
        "\n")[-1], "Close is hidden behind who opened the card again"


def test_the_board_drawer_writes_through_the_two_floor_rows():
    board = PANEL.split("async function boardCardClose(){")[1].split("\n}")[0]
    assert 'act("card_remove"' in board and 'act("card_close"' in board
    assert "prompt(" not in board, "the confirmation went back to a browser prompt"


def test_the_product_view_opens_a_card_and_writes_through_ITS_row():
    view = PANEL.split("async function pvBoardLoad(){")[1].split("function pvDocSearch(")[0]
    assert 'act("product_board"' in view and 'act("product_withdraw_card"' in view
    assert '_bcontrols(c,"product")' in view, "the product view draws a second set of controls"
    assert "cards===null" in view and "!cards.length" in view, (
        "an unreadable board and an empty one are drawn as the same thing")


# ── the product view, EXECUTED: a person opens their card and closes it from the card ──────────

def test_the_product_view_is_DRIVEN_open_the_card_close_it_from_the_card_see_the_answer_there():
    """The issue's acceptance test, on the page's own functions under node: the list is drawn, the
    card opens with both controls and the sentence saying what they do, the reason is typed in the
    card, the row is `product_withdraw_card` with that reason, and the product role's answer stays
    on the card — which, closed now, offers no control. The rows themselves are proven above."""
    import json

    from tests.test_a_refusal_is_not_an_answer import run

    words = {"close": "Close card", "remove": "Remove from the board", "confirm": "Confirm",
             "cancel": "Cancel", "reason": "Why? (one line)", "ask_close": "Closing keeps it.",
             "ask_remove": "Removing deletes it.", "note": "Close or remove asks it to, from here"}
    card = {"ref": "7", "readable": True, "title": "A monthly report", "body": "asked",
            "state": "open", "column": "Backlog", "opened_by_product": "request",
            "started": False, "removes": True, "words": words}
    stubs = ("let _prod={project:'acme'},_bd={};"
             "let _pv={board:undefined,boardMsg:'',card:null,ask:null,said:null};"
             f"const CARD={json.dumps(card)};const acts=[];"
             "async function act(name,params){acts.push([name,params]);"
             "if(name==='product_withdraw_card'){CARD.state='closed';"
             "return {ok:true,message:'closed #7 — it leaves the list of work.',data:{}}}"
             "const cards=CARD.state==='open'?[{ref:'7',title:CARD.title,column:'Backlog'}]:[];"
             "return {ok:true,message:'',data:{cards,card:params.card?CARD:null}}}")
    got = run("nodes['#pvBoard']=node();await pvBoardLoad();"
              "const listed=nodes['#pvBoard'].innerHTML;"
              "await pvCardOpen('7');const opened=nodes['#pvBoard'].innerHTML;"
              "pvCardAsk('close');const asking=nodes['#pvBoard'].innerHTML;"
              "_pv.ask.reason='filed twice';await pvCardClose();"
              "return {listed,opened,asking,after:nodes['#pvBoard'].innerHTML,acts}",
              "pvBoardLoad", "pvCardOpen", "pvCardRead", "pvCardAsk", "pvCardClose",
              "paintPvBoard", "_bcontrols", "pvAdjustBlock", "pvAcceptBlock", stubs=stubs)

    assert 'data-r="7"' in got["listed"] and "A monthly report" in got["listed"], got["listed"]
    assert "Close card" in got["opened"] and "Remove from the board" in got["opened"]
    assert "Close or remove asks it to, from here" in got["opened"], "no sentence under the card"
    assert "Closing keeps it." in got["asking"] and 'id="pv_reason"' in got["asking"], (
        "the confirmation is not drawn in place, with the reason typed in the card")
    assert ["product_withdraw_card", {"project": "acme", "number": "7", "reason": "filed twice",
                                      "remove": False}] in got["acts"], got["acts"]
    assert "closed #7 — it leaves the list of work." in got["after"], (
        "the product role's answer did not stay on the card")
    assert "Close card" not in got["after"], "a closed card still offers to be closed"


# ── the product role SEES the removal: its board is another process's snapshot ──────────────────

def _a_row_dear_to_read_whole(tracker):
    """The same local board, as a row that says its WHOLE read is NOT cheap — the only kind of row
    the refresh below still serves (#384, review of #389).

    WHY NOT THE LOCAL ROW ITSELF: #393 makes `LocalTracker` declare `whole_read_is_cheap = True`,
    and `product/board.py` then reads it whole on every call and never runs `_refresh`. Measured
    with #393 merged on top: both removal rows of plan 384 went GREEN — the subtraction these tests
    guard had no row left that reached it, and the guard read as green by accident of the sweep.
    The combination this mechanism exists for is a row that removes AND is dear to read whole (a
    hosted tracker the day it gains `remove_ticket`); none ships today, so the test builds it: the
    local row's removal and its `removed_refs`, declared dear. `False` is also what a row that
    declares nothing answers, so on a base without #393 this is the same row as before."""
    from openfactory.adapters.tracker.local import LocalTracker

    class DearLocalTracker(LocalTracker):
        whole_read_is_cheap = False

    return DearLocalTracker(tracker.project, db_path=tracker._db)


def test_a_card_removed_ELSEWHERE_leaves_the_product_roles_board_on_the_next_read(
        deployment, tracker, board):
    """Measured live on #384: the card was removed from the board, and the product role went on
    triaging and describing it. Its board is swept once and then refreshed with only what was
    UPDATED — and a removed card is updated never. `forget_board` in the process that removed it
    does not reach the worker's snapshot, so this removes WITHOUT forgetting, as the other process
    sees it. Read through a row dear to read whole — see `_a_row_dear_to_read_whole`."""
    from openfactory.product.board import read_board

    tracker = _a_row_dear_to_read_whole(tracker)
    kept = _on_the_board(tracker, board)
    removed = _opened_by_product(tracker, board)
    before, error = read_board(deployment, tracker=tracker)
    assert not error and removed.lstrip("#") in {t.number for t in before}

    tracker.remove_ticket(removed, "filed twice", by=ASKER)       # the panel's process, not ours
    after, error = read_board(deployment, tracker=tracker)        # an incremental refresh

    assert not error, error
    numbers = {t.number for t in after}
    assert removed.lstrip("#") not in numbers, (
        "the product role still sees a card that was removed from the board")
    assert kept.lstrip("#") in numbers, "the refresh dropped a card nobody removed"


def test_a_row_that_removes_but_cannot_SAY_what_sends_the_refresh_to_a_full_sweep(
        deployment, tracker, board, monkeypatch):
    """Never a blind refresh: a row that cannot say what it removed is swept whole instead. Read
    through a row dear to read whole, the only one the refresh serves (`_a_row_dear_to_read_whole`)."""
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.product.board import read_board

    tracker = _a_row_dear_to_read_whole(tracker)
    removed = _on_the_board(tracker, board)
    read_board(deployment, tracker=tracker)
    monkeypatch.delattr(LocalTracker, "removed_refs")
    tracker.remove_ticket(removed, "gone", by=ADMIN)

    after, error = read_board(deployment, tracker=tracker)

    assert not error and removed.lstrip("#") not in {t.number for t in after}


def test_the_local_row_says_what_it_removed_since_a_stamp(deployment, tracker):
    from openfactory.adapters.board_db import now_iso

    first = tracker.create_ticket(title="one", body="")
    tracker.remove_ticket(first, "old", by=ADMIN)
    stamp = now_iso()
    second = tracker.create_ticket(title="two", body="")
    tracker.remove_ticket(second, "new", by=ADMIN)

    assert tracker.removed_refs(since=stamp) == [second.lstrip("#")]
    assert tracker.removed_refs(since="") == [first.lstrip("#"), second.lstrip("#")]


def test_the_audit_table_is_PRUNED_and_the_highest_removed_number_survives_it(deployment, tracker):
    """`removed_cards` is bounded (review of #389): a removal's audit line older than a year goes
    at the next removal — except the project's HIGHEST removed ref, which `next_ref` reads so the
    number is never handed out again. Card 3 is removed from the top of the board two years ago,
    card 1 as long ago, card 2 today: 1 goes, 3 stays, and the next card is 4, never 3."""
    from openfactory.adapters.board_db import connect, next_ref

    one, two, three = (tracker.create_ticket(title=t, body="") for t in ("one", "two", "three"))
    for ref in (three, one):
        tracker.remove_ticket(ref, "old", by=ADMIN)
    with connect(write=True) as conn:
        conn.execute("UPDATE removed_cards SET removed_at = '2024-01-01T00:00:00+00:00' "
                     "WHERE project = 'acme'")
    tracker.remove_ticket(two, "today", by=ADMIN)

    assert _audit(one) is None, "a removal's audit line older than the retention was kept"
    assert _audit(two) is not None, "today's removal lost its audit line"
    assert _audit(three) is not None, (
        "the prune dropped the HIGHEST removed number, which is what keeps it from being reused")
    with connect() as conn:
        assert next_ref(conn, "acme") == int(three.lstrip("#")) + 1, (
            "a removed card's number was handed out again after its audit line aged")


# ── what a close records and what it says agree (#534) ─────────────────────────────────────────

@pytest.mark.parametrize("column", ["Backlog", "Done"])
@pytest.mark.parametrize("opened", [_opened_by_product, _on_the_board],
                         ids=["the product role's path", "the door's path"])
def test_a_close_says_the_word_it_recorded_on_either_path_from_either_column(
        deployment, tracker, board, told, opened, column):
    """THE RECORD AND THE SENTENCE FROM ONE `delivered` (#534). A finished card's close records
    `completed`, #162's word for delivered; the product role's path answered "stays in the history
    as not done" over that record, while the door's path said "as delivered". Each path, each
    column: what is said agrees with what was written."""
    ref = opened(tracker, board, column=column)

    out = _act("card_close", project="acme", issue=ref, reason="tidying the board")

    assert out.ok, out.message
    recorded = _closed_reason(ref)
    assert recorded == ("completed" if column == "Done" else "not_planned"), recorded
    said_delivered = "as delivered" in out.message
    assert said_delivered == (recorded == "completed"), (recorded, out.message)
    assert ("not done" in out.message) == (opened is _opened_by_product and column == "Backlog")


@pytest.mark.parametrize(("column", "word"), [("Backlog", "as not done"),
                                              ("Done", "as delivered")])
def test_the_close_control_says_the_word_its_close_will_record(deployment, tracker, board,
                                                                column, word):
    """`ask_close`, what the panel shows before a close, said "recorded as not done" whatever the
    card's column — the same claim, made before the close instead of after."""
    from openfactory.actions.catalog import card_view

    ref = _opened_by_product(tracker, board, column=column)

    view = card_view(deployment, tracker, board, ref, opened_by="request")

    assert word in view["words"]["ask_close"].replace("recorded as not done", "as not done"), (
        view["words"]["ask_close"])


def test_the_delivered_sentences_speak_both_languages():
    from openfactory.product.voice import card_controls, card_withdrawn_result

    assert card_withdrawn_result(ref="#7", how="delivered", language="pt-BR").startswith(
        "fechei o #7 como entregue")
    assert card_withdrawn_result(ref="#7", how="delivered", language="en").startswith(
        "closed #7 as delivered")
    for lang, word in (("pt-BR", "como entregue"), ("en", "as delivered")):
        words = card_controls(opened_by_product=True, started=True, removes=True, finished=True,
                              language=lang)
        assert word in words["ask_close"] and "ask_close_finished" not in words

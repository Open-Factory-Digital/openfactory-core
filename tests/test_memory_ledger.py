"""The open-loop ledger (ADR-0021).

The defect it exists for: both judging roles could act and neither could follow through. A remedy
was tried and nothing recorded whether it worked; a question was asked and nothing noticed nobody
answered; work shipped with a critical review finding and no person was told.
"""

from __future__ import annotations

import pytest

from openfactory.memory.ledger import (
    CHASED,
    CLOSED,
    OPEN,
    QUESTION,
    REMEDY,
    chase_due,
    close_by_observation,
    fold,
    open_loop,
    waiting,
)

# ── opening ─────────────────────────────────────────────────────────────────────────────────────

def test_a_loop_always_opens_WAITING():
    """An agent may never open a loop already claiming an outcome — that would be self-reporting
    with extra steps."""
    loop = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    assert loop.state == OPEN and loop.outcome == "" and loop.waiting


def test_an_unknown_kind_is_refused_loudly():
    """A kind nobody knows how to CLOSE is a row that stays open for ever and teaches everyone to
    ignore the list."""
    with pytest.raises(ValueError, match="closing observation"):
        open_loop("vibes", "478", owner="techlead", ts="T1")


# ── append-only ─────────────────────────────────────────────────────────────────────────────────

def test_closing_appends_rather_than_editing():
    rows = [open_loop(REMEDY, "478", owner="techlead", ts="T1")]
    new = close_by_observation(rows, {(REMEDY, "478", ""): "worked"})
    assert len(new) == 1 and new[0].state == CLOSED and new[0].outcome == "worked"
    assert rows[0].state == OPEN, "the original row was mutated"


def test_folding_takes_the_latest_state_per_loop():
    opened = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    closed = close_by_observation([opened], {(REMEDY, "478", ""): "worked"})[0]
    folded = fold([opened, closed])
    assert len(folded) == 1 and folded[0].state == CLOSED


def test_a_stale_open_row_can_NEVER_resurrect_a_closed_loop():
    """Rows come back from a scan in no guaranteed order. An out-of-order `open` overwriting a
    settled outcome would quietly reopen something already answered."""
    opened = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    closed = close_by_observation([opened], {(REMEDY, "478", ""): "did-not-work"})[0]
    assert fold([closed, opened])[0].state == CLOSED


def test_a_settled_loop_is_never_re_closed():
    """History that can be revised on a later pass is not history."""
    opened = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    closed = close_by_observation([opened], {(REMEDY, "478", ""): "worked"})[0]
    assert close_by_observation([opened, closed], {(REMEDY, "478", ""): "did-not-work"}) == []


def test_two_loops_on_the_same_subject_at_different_times_are_different_loops():
    """A second remedy attempt on the same ticket is a new attempt, not a duplicate of the first —
    otherwise a retry history collapses to one row and nothing can be learned from it."""
    a = open_loop(REMEDY, "478", owner="techlead", ts="T1")
    b = open_loop(REMEDY, "478", owner="techlead", ts="T2")
    assert len(fold([a, b])) == 2


# ── observation, never self-report ──────────────────────────────────────────────────────────────

def test_an_UNOBSERVED_loop_stays_open():
    """The safe reading. Assuming it closed would silently drop the follow-through this whole
    ledger exists to provide."""
    rows = [open_loop(QUESTION, "thread-1", owner="product", ts="T1")]
    assert close_by_observation(rows, {}) == []
    assert len(waiting(rows)) == 1


def test_nothing_in_this_module_lets_an_actor_declare_its_own_success():
    """`close_by_observation` is the ONLY way to reach CLOSED, and it takes the world as another
    pass found it. A remedy that grades its own homework is the thing this ledger exists to stop
    believing."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("openfactory/memory/ledger.py").read_text())
    producers = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        # who actually BUILDS a closed loop — `state=CLOSED` as a keyword, not the word in a comment
        for node in ast.walk(fn):
            if isinstance(node, ast.keyword) and node.arg == "state" \
                    and getattr(node.value, "id", "") == "CLOSED":
                producers.append(fn.name)
                break
    assert producers == ["close_by_observation"], (
        f"a new path to CLOSED appeared: {producers} — every one must take OBSERVED state, or an "
        f"agent can declare its own success again"
    )


# ── chasing is bounded ──────────────────────────────────────────────────────────────────────────

def test_an_unanswered_question_is_chased_once():
    rows = [open_loop(QUESTION, "thread-1", owner="product", ts="T1")]
    chased = chase_due(rows, hours_open={(QUESTION, "thread-1", ""): 30.0},
                       after_hours=24.0, ts="T2")
    assert len(chased) == 1 and chased[0].state == CHASED


def test_a_chased_loop_is_NEVER_chased_again():
    """The other failure mode: an agent that asks the same thing every hour until somebody mutes
    the channel. Continued silence is answered by a person looking at the list, not a louder agent."""
    rows = [open_loop(QUESTION, "thread-1", owner="product", ts="T1")]
    rows += chase_due(rows, hours_open={(QUESTION, "thread-1", ""): 30.0}, after_hours=24.0, ts="T2")
    again = chase_due(rows, hours_open={(QUESTION, "thread-1", ""): 300.0}, after_hours=24.0, ts="T3")
    assert again == [], "it would nag"


def test_a_fresh_question_is_left_alone():
    """A person deserves a chance to answer before an agent starts reminding them."""
    rows = [open_loop(QUESTION, "thread-1", owner="product", ts="T1")]
    assert chase_due(rows, hours_open={(QUESTION, "thread-1", ""): 2.0},
                     after_hours=24.0, ts="T2") == []


def test_a_closed_loop_is_never_chased():
    opened = open_loop(QUESTION, "t", owner="product", ts="T1")
    closed = close_by_observation([opened], {(QUESTION, "t", ""): "answered"})[0]
    assert chase_due([opened, closed], hours_open={(QUESTION, "t", ""): 999.0},
                     after_hours=1.0, ts="T9") == []


# ── reading it back ─────────────────────────────────────────────────────────────────────────────

def test_waiting_narrows_by_owner_so_one_agent_never_chases_anothers_loop():
    rows = [open_loop(REMEDY, "478", owner="techlead", ts="T1"),
            open_loop(QUESTION, "t", owner="product", ts="T1")]
    assert [x.kind for x in waiting(rows, owner="product")] == [QUESTION]


def test_a_loop_carries_enough_context_to_write_the_message():
    """A reminder that cannot name what it is about is a reminder nobody can act on."""
    loop = open_loop(QUESTION, "t", owner="product", ts="T1",
                     context={"person": "alice", "asked": "qual formato de export?"})
    assert loop.context["person"] == "alice"
    assert "formato" in loop.context["asked"]

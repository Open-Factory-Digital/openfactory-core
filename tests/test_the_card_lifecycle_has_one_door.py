"""A card changes state through its door, or is named on a list that may only shrink (ADR-0055 D9).

THE DEFECT THIS GUARDS. Five defects in one day had one shape: a card changed state at some call
site, and one of the things that depend on that state was not told (#411). Each was fixed where it
was found, and the next one was already in the tree, at a call site nobody had exercised. The door
(`openfactory/lifecycle/`) is the one place that knows every consumer; this walk fails on a write
anywhere else:

    a card's state          `set_state`, `set_column`, `set_status`, `close_ticket`,
                            `remove_ticket`, `reopen_ticket`
    a promise about a card  `open_loop` / `close_by_observation` in a function that names the
                            loops keyed to a card (DELIVERY, CARD_QUESTION)
    a card's notice         `events.card_finished`, `deliver`, `ready_for_you`,
                            `ready_to_try`, `ready_at_the_gate`, `card_moved`

`events.ci_went_red`, `preview_up` and `pull_requests_at_the_gate` are not card notices in this
sense: a red check, a live preview and a reminder of a waiting gate say how far a job is, and no
card changes state with them.

THE BOX'S PROGRESS MARKS ARE ADMITTED BY RULE, not named on the list (D7, #414): the box's one
writer of each runner (`BOX_WRITERS`) may call `set_state` only inside `if <state> in
PROGRESS_MARKS:`, writing that same state — and `PROGRESS_MARKS` is held here to exactly its
members. Every other state the box reaches is an outcome, handed back in its result and applied
by the worker through the door; one written from the box fails this walk like any other write.

THE WRITERS NOT MOVED YET are in `card_writers_outside_the_door.py`, each with why and the slice
that moves it, under a ceiling and a baseline held HERE — so a new exemption is a visible change of
this file, never a quiet line in that one.
"""

from __future__ import annotations

import ast
import pathlib

from card_writers_outside_the_door import OUTSIDE_THE_DOOR

ROOT = pathlib.Path(__file__).resolve().parent.parent

WRITES = frozenset({"set_state", "set_column", "set_status", "close_ticket", "remove_ticket",
                    "reopen_ticket"})
LOOP_WRITES = frozenset({"open_loop", "close_by_observation"})
CARD_LOOPS = frozenset({"DELIVERY", "CARD_QUESTION"})
NOTICES = frozenset({"card_finished", "deliver", "ready_for_you", "ready_to_try",
                     "ready_at_the_gate", "card_moved"})

#: Where a write is not a caller's, BY RULE — each a directory or one file, with why.
NOT_CALLERS = {
    "openfactory/lifecycle/": "the door itself",
    "openfactory/adapters/": "the ports the door writes through — a row implementing a close as "
                             "a status change is the port, not somebody calling it",
    "openfactory/conformance/": "the conformance probe writes a marker into a port to prove it "
                                "can write at all, on a card it made for that",
    "openfactory/testing/": "the in-memory harness a contributor's adapter is run against — no "
                            "deployment's card",
    # one file, not a directory: forgetting a project (#453) removes its closed cards as DATA,
    # with the door's record of them (`forget.RECORD_KINDS`), because an operator asked for the
    # project to be forgotten. No card's lifecycle goes on, and nobody is left to be told.
    "openfactory/product/forget.py": "forgetting a project erases its closed cards and their "
                                     "record together — data removal, not a card's transition",
}

#: THE BOX'S ONE WRITER OF EACH RUNNER, whose `set_state` is admitted by rule for a progress mark.
BOX_WRITERS = frozenset({("openfactory/orchestrator/machine.py", "_set_state"),
                         ("openfactory/orchestrator/promotion.py", "_state")})

#: THE CEILING AND THE BASELINE, committed. Slice 1 ended at 27: the writers slices 2 and 3 own;
#: 25 since #413's first part moved the card-question sweep through the door; 23 since its
#: second moved the job's park and settle; 16 since #414's first part moved filing, the moves
#: between the operator's columns and the stale-pickup healer (an observed change, D8); 4 since
#: #414's B1 and B2, merged: B1 moved a split's children and parent, the gather's question, the
#: ready-for-you tellings, the delivery's loop and the factory's own impediment card; B2 the box's
#: outcomes, which it hands back for the worker to apply (D7) — its progress marks stay, by rule
#: (`BOX_WRITERS`) — and the promise one card's filing opens (`Loops("open")`).
#: Each slice lowers the ceiling and drops what it moved in from both; slice 3 ends at zero, and
#: the four left are its own (`card_writers_outside_the_door.py`).
CEILING = 4
BASELINE = frozenset({
    ("openfactory/runtime/temporal/activities.py", "_a_card_was_finished", "card_finished"),
    ("openfactory/runtime/temporal/activities.py", "_product_followup", "deliver"),
    ("openfactory/runtime/temporal/activities.py", "_product_followup", "close_by_observation"),
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"),
})


def _named(node: ast.AST) -> set[str]:
    return ({x.id for x in ast.walk(node) if isinstance(x, ast.Name)}
            | {x.attr for x in ast.walk(node) if isinstance(x, ast.Attribute)})


def _name_of(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(
        node, ast.Attribute) else ""


def _a_progress_mark(fn: ast.AST, call: ast.Call) -> bool:
    """Whether `call` — a `set_state` inside `fn` — sits in the body of an `if <state> in
    PROGRESS_MARKS:` of `fn`, and writes that same `<state>`. The else branch is not the body: an
    outcome handed back there writes nothing, and one written there is a write like any other."""
    for node in ast.walk(fn):
        test = getattr(node, "test", None) if isinstance(node, ast.If) else None
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1
                and isinstance(test.ops[0], ast.In) and isinstance(test.left, ast.Name)
                and len(test.comparators) == 1
                and _name_of(test.comparators[0]) == "PROGRESS_MARKS"):
            continue
        inside = any(sub is call for stmt in node.body for sub in ast.walk(stmt))
        state = call.args[1] if len(call.args) > 1 else None
        if inside and isinstance(state, ast.Name) and state.id == test.left.id:
            return True
    return False


def card_writes(root: pathlib.Path, *, rel_to: pathlib.Path) -> tuple[set[tuple], int]:
    """Every `(file, function, call)` under `root` that changes a card outside its door, and how
    many files the walk read. Parsed, never grepped: a comment explaining a write is not one."""
    found: set[tuple[str, str, str]] = set()
    read = 0
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(rel_to).as_posix()
        if any(rel.startswith(where) for where in NOT_CALLERS):
            continue
        read += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]

        def where(line: int, functions=functions):
            inside = [f for f in functions if f.lineno <= line <= (f.end_lineno or f.lineno)]
            return max(inside, key=lambda f: f.lineno) if inside else None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            fn = where(node.lineno)
            here = fn.name if fn is not None else "<module>"
            if name in WRITES:
                if (name == "set_state" and (rel, here) in BOX_WRITERS
                        and _a_progress_mark(fn, node)):
                    continue      # the box's progress mark, by rule (D7)
                found.add((rel, here, name))
            elif name in LOOP_WRITES and fn is not None and _named(fn) & CARD_LOOPS:
                found.add((rel, here, name))
            elif (name in NOTICES and isinstance(func, ast.Attribute)
                  and isinstance(func.value, ast.Name) and func.value.id == "events"):
                found.add((rel, here, name))
    return found, read


def test_nothing_outside_the_door_changes_a_card_unless_it_is_named():
    found, _ = card_writes(ROOT / "openfactory", rel_to=ROOT)
    strays = sorted(found - set(OUTSIDE_THE_DOOR))
    assert not strays, (
        "a card's state, a promise about a card or a card's notice is written outside its door "
        "(`openfactory/lifecycle/`) — call `lifecycle.transition` with the event that happened, "
        "so every consumer hears it:\n  " + "\n  ".join(map(str, strays)))


def test_the_list_names_only_writers_that_are_still_there():
    """An entry whose call moved through the door is gone from the list the same day — a list
    that claims a writer the tree no longer has would let a new one hide under its name."""
    found, _ = card_writes(ROOT / "openfactory", rel_to=ROOT)
    dead = sorted(set(OUTSIDE_THE_DOOR) - found)
    assert not dead, "named on the list and no longer outside the door — remove them:\n  " + \
        "\n  ".join(map(str, dead))


def test_the_list_may_only_shrink():
    """"May only shrink" is enforced, not intended (D9): longer than the ceiling, or naming an entry
    the baseline does not hold, fails — so an exemption is never swapped for another one under the
    same count."""
    assert len(OUTSIDE_THE_DOOR) <= CEILING, (
        f"{len(OUTSIDE_THE_DOOR)} writers outside the door, and the ceiling is {CEILING}")
    added = sorted(set(OUTSIDE_THE_DOOR) - BASELINE)
    assert not added, f"named outside the door and not in the baseline: {added}"
    assert len(BASELINE) == CEILING, "the baseline and the ceiling were moved apart"


def test_every_writer_on_the_list_says_why_and_which_slice_moves_it():
    for key, (why, slice_) in OUTSIDE_THE_DOOR.items():
        assert len(why) > 20, f"{key}: no reason worth the name"
        # slices 1 and 2 have landed: what they did not move is slice 3's to finish, and the list
        # says so rather than naming a slice that is over (review of #482)
        assert slice_ == "3", f"{key}: slices 1 and 2 have landed, so their writers are not here"


def test_the_walk_reads_the_package_and_sees_a_writer_planted_in_it(tmp_path):
    """The walk would pass over an empty tree: it reads what it says it reads, and a write planted
    in a file it reads is found — in each of the three forms."""
    _, read = card_writes(ROOT / "openfactory", rel_to=ROOT)
    assert read > 240, f"the walk read {read} files"
    for where in NOT_CALLERS:
        assert (ROOT / where).exists(), f"{where} is excused by rule and does not exist"

    rogue = tmp_path / "openfactory" / "product" / "rogue.py"
    rogue.parent.mkdir(parents=True)
    rogue.write_text(
        "from openfactory.memory.ledger import DELIVERY, open_loop\n"
        "from openfactory.product import events\n"
        "def drop(tracker, card):\n"
        "    tracker.close_ticket(card, 'gone', delivered=False)\n"
        "def promise(card):\n"
        "    return open_loop(DELIVERY, card, owner='product', ts='now')\n"
        "def say(project, card):\n"
        "    events.card_moved(project, card=card, notice='back', event_id='x')\n"
        "# tracker.reopen_ticket(card) — a comment about a write is not a write\n",
        encoding="utf-8")
    found, _ = card_writes(tmp_path / "openfactory", rel_to=tmp_path)
    assert found == {("openfactory/product/rogue.py", "drop", "close_ticket"),
                     ("openfactory/product/rogue.py", "promise", "open_loop"),
                     ("openfactory/product/rogue.py", "say", "card_moved")}, found


# ── the box writes its progress marks, and hands every outcome back (D7, #414) ────────────────

def test_the_progress_marks_are_exactly_the_box_s_own(tmp_path):
    """The rule admits the box's `set_state` for the states in `PROGRESS_MARKS` — so the set IS the
    rule, and widening it is a change of this test. Each member says how far a job is and has no
    consequence; an outcome (a pull request, a merge, a delivery, a refusal, a park) is not one."""
    from openfactory.contracts.state import PROGRESS_MARKS, JobState

    assert PROGRESS_MARKS == frozenset({
        JobState.SPEC_VALIDATION, JobState.PREPARING, JobState.PLANNING, JobState.IMPLEMENTING,
        JobState.VALIDATING, JobState.REPAIRING, JobState.REVIEWING, JobState.PAUSED,
        JobState.STAGING_VERIFYING, JobState.PROD_RELEASING, JobState.PROD_VERIFYING,
        JobState.ROLLING_BACK})
    for outcome in (JobState.PR_OPEN, JobState.MERGED, JobState.DONE, JobState.ON_HOLD,
                    JobState.NEEDS_REFINEMENT, JobState.BLOCKED, JobState.FAILED,
                    JobState.AWAITING_PROD_APPROVAL):
        assert outcome not in PROGRESS_MARKS, f"{outcome} is an outcome, and handed back"


def _a_box(tmp_path, body: str, *, function: str = "_set_state") -> set:
    box = tmp_path / "openfactory" / "orchestrator" / "machine.py"
    box.parent.mkdir(parents=True, exist_ok=True)
    box.write_text("from openfactory.contracts.state import PROGRESS_MARKS\n"
                   f"def {function}(self, ticket, state, reason=None):\n{body}", encoding="utf-8")
    found, _ = card_writes(tmp_path / "openfactory", rel_to=tmp_path)
    return found


def test_a_progress_mark_from_the_box_is_admitted_and_an_outcome_from_it_fails(tmp_path):
    """The rule, both ways, on a box planted in a tree the walk reads: the box's writer admitted
    under `if state in PROGRESS_MARKS:` writing that state, and every other shape of it found."""
    written = {("openfactory/orchestrator/machine.py", "_set_state", "set_state")}
    assert _a_box(tmp_path, "    if state in PROGRESS_MARKS:\n"
                            "        try:\n"
                            "            self.tracker.set_state(ticket.id, state)\n"
                            "        except Exception:\n"
                            "            pass\n"
                            "    else:\n"
                            "        self._handed_back.append(state)\n") == set()
    # an outcome written from the box — the write the hand-back replaced
    assert _a_box(tmp_path, "    self.tracker.set_state(ticket.id, state, reason=reason)\n") \
        == written
    # written from the else branch: the outcome side of the rule
    assert _a_box(tmp_path, "    if state in PROGRESS_MARKS:\n"
                            "        pass\n"
                            "    else:\n"
                            "        self.tracker.set_state(ticket.id, state)\n") == written
    # a set that is not the closed one
    assert _a_box(tmp_path, "    if state in WORKING:\n"
                            "        self.tracker.set_state(ticket.id, state)\n") == written
    # a state other than the one the test admitted
    assert _a_box(tmp_path, "    if state in PROGRESS_MARKS:\n"
                            "        self.tracker.set_state(ticket.id, 'done')\n") == written
    # the shape, from a function that is not the box's writer
    assert _a_box(tmp_path, "    if state in PROGRESS_MARKS:\n"
                            "        self.tracker.set_state(ticket.id, state)\n",
                  function="_finish") == {("openfactory/orchestrator/machine.py", "_finish",
                                           "set_state")}

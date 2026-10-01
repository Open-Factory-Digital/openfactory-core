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
                            `ready_at_the_gate`, `card_moved`

`events.ci_went_red`, `preview_up` and `pull_requests_at_the_gate` are not card notices in this
sense: a red check, a live preview and a reminder of a waiting gate say how far a job is, and no
card changes state with them.

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
NOTICES = frozenset({"card_finished", "deliver", "ready_for_you", "ready_at_the_gate",
                     "card_moved"})

#: Where a write is not a caller's, BY RULE — each a directory, with why.
NOT_CALLERS = {
    "openfactory/lifecycle/": "the door itself",
    "openfactory/adapters/": "the ports the door writes through — a row implementing a close as "
                             "a status change is the port, not somebody calling it",
    "openfactory/conformance/": "the conformance probe writes a marker into a port to prove it "
                                "can write at all, on a card it made for that",
    "openfactory/testing/": "the in-memory harness a contributor's adapter is run against — no "
                            "deployment's card",
}

#: THE CEILING AND THE BASELINE, committed. Slice 1 ends at 27: the writers slices 2 and 3 own.
#: Each slice lowers the ceiling and drops what it moved in from both; slice 3 ends at zero.
CEILING = 27
BASELINE = frozenset({
    ("openfactory/runtime/temporal/activities.py", "settle_ticket", "set_state"),
    ("openfactory/runtime/temporal/activities.py", "_apply", "set_state"),
    ("openfactory/runtime/temporal/activities.py", "_child_to_todo", "set_state"),
    ("openfactory/runtime/temporal/activities.py", "_child_to_todo", "set_status"),
    ("openfactory/runtime/temporal/activities.py", "_do_split", "close_ticket"),
    ("openfactory/runtime/temporal/activities.py", "_do_gather", "set_state"),
    ("openfactory/runtime/temporal/activities.py", "_do_gather", "open_loop"),
    ("openfactory/runtime/temporal/activities.py", "_do_card_question_sweep", "set_state"),
    ("openfactory/runtime/temporal/activities.py", "_do_card_question_sweep",
     "close_by_observation"),
    ("openfactory/runtime/temporal/activities.py", "scan_todo", "set_status"),
    ("openfactory/runtime/temporal/activities.py", "_a_card_was_finished", "card_finished"),
    ("openfactory/runtime/temporal/activities.py", "_product_followup", "deliver"),
    ("openfactory/runtime/temporal/activities.py", "_product_followup", "close_by_observation"),
    ("openfactory/runtime/temporal/activities.py", "_tell", "ready_for_you"),
    ("openfactory/runtime/temporal/activities.py", "_pull_requests_waiting", "ready_at_the_gate"),
    ("openfactory/product/events.py", "deliver", "close_by_observation"),
    ("openfactory/ops/impediment.py", "resolved", "close_ticket"),
    ("openfactory/orchestrator/machine.py", "_set_state", "set_state"),
    ("openfactory/orchestrator/promotion.py", "_state", "set_state"),
    ("openfactory/actions/catalog.py", "_open", "set_column"),
    ("openfactory/actions/catalog.py", "_card_move", "set_column"),
    ("openfactory/product/module.py", "file_ticket", "set_column"),
    ("openfactory/product/module.py", "file_defect", "set_column"),
    ("openfactory/product/module.py", "_file_one", "set_column"),
    ("openfactory/product/module.py", "promote", "set_column"),
    ("openfactory/product/module.py", "_track_defect", "open_loop"),
    ("openfactory/product/followup.py", "deliveries_to_open", "open_loop"),
})


def _named(node: ast.AST) -> set[str]:
    return ({x.id for x in ast.walk(node) if isinstance(x, ast.Name)}
            | {x.attr for x in ast.walk(node) if isinstance(x, ast.Attribute)})


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
        assert slice_ in ("2", "3"), f"{key}: slice 1 has landed, so its writers are not here"


def test_the_walk_reads_the_package_and_sees_a_writer_planted_in_it(tmp_path):
    """The walk would pass over an empty tree: it reads what it says it reads, and a write planted
    in a file it reads is found — in each of the three forms."""
    _, read = card_writes(ROOT / "openfactory", rel_to=ROOT)
    assert read > 240, f"the walk read {read} files"
    for where in NOT_CALLERS:
        assert (ROOT / where).is_dir(), f"{where} is excused by rule and does not exist"

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

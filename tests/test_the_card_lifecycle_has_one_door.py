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
                            `ready_to_try`, `ready_at_the_gate`, `card_moved` — and the requester's
                            loop past the pull request (#448 slice 6): `merged_for_you`,
                            `staged_for_you`, `tried_and_right` and their door-side forms
                            (`went_in`, `to_try_at_the_stage`, `tried_it_right`), on `events` or
                            imported from it by name
    the door's promise half any call into `lifecycle/loops.py` — `announce`, `deliver`, `owe`,
                            `ask`, … — whose callers are the door's effects (#414): a delivery
                            announced from there by anybody else is a second announcer
    a card's text beside    `update_body` / `update_title` in a function that goes through the
    its door                door (`transition`, `_through_the_door`), anywhere but inside a
                            function that is a transition's `act=` (#448 slice 6): the bar moved
                            at a gate is the engine's half of the decision, never a write beside it
    a release question      `open_loop` / `close_by_observation` in a function that names a release
                            (`is_release`, `release_of`), and any `followup.release_of` — asked
                            and answered by the round's `staged` and the verdicts' transitions
                            (#448 slice 6)
    the requester's yes     `accept.record`, anywhere but inside a transition's `act=` (#448
                            slice 6): the acceptance is the engine's half of `accepted`

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
this file, never a quiet line in that one. THERE ARE NONE since #414 (ADR-0055 D9): a requirement's
delivery, the last, goes through each of its cards' doors as `promised`, and the ceiling is zero.
#448 slice 6 widened the walk to the requester's loop past the pull request and moved every writer
it found through the door in the same change, so the ceiling stayed where it was.
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
                     "ready_at_the_gate", "card_moved",
                     # #448 slice 6: the requester's loop past the pull request
                     "merged_for_you", "staged_for_you", "tried_and_right",
                     "went_in", "to_try_at_the_stage", "tried_it_right"})
#: Where the notices live, the module a file reaches them by — or imports them from by name.
EVENTS = "openfactory.product.events"
#: A card's TEXT (#448 slice 6), admitted only inside a transition's `act=` in a function that
#: goes through the door — the door's own names, as the files call it.
TEXT_WRITES = frozenset({"update_body", "update_title"})
THE_DOOR = frozenset({"transition", "_through_the_door"})
#: A release question (#448 slice 6): the names that make a function one about a release, and the
#: one constructor of its loop, whose every caller asks or answers a release beside the door.
RELEASES = frozenset({"is_release", "release_of"})
FOLLOWUP = "openfactory.product.followup"
#: The requester's yes (#448 slice 6): its record, admitted only inside a transition's `act=`.
ACCEPT = "openfactory.product.accept"

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
#: (`BOX_WRITERS`) — and the promise one card's filing opens (`Loops("open")`); 1 since the job's
#: exit and the weekly sweep stopped announcing beside the door, and the sweep's own questions were
#: closed apart from any card's promise; 0 since ADR-0055 gained `promised` (amended 2026-10-04)
#: and a requirement's delivery went through each of its cards' doors.
#: Each slice lowered the ceiling and dropped what it moved in from both. SLICE 3 ENDS AT ZERO, as
#: D9 says it must (#414): raising it again is a change of this line, in review.
CEILING = 0
BASELINE: frozenset[tuple[str, str, str]] = frozenset()

#: THE DOOR'S PROMISE HALF (#414): `lifecycle/loops.py`, whose callers are the door's effects. A
#: call into it from anywhere the walk reads is a promise about a card kept beside the door — the
#: delivery announced by the job's exit and the weekly sweep, under another name.
DOOR_LOOPS = "openfactory.lifecycle.loops"


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
        # the names this file reaches the door's promise half by: the module, or what it exports
        promise_module, promise_functions = _the_door_s_loops(tree)
        # and the notices, a release's loop and the requester's yes, likewise (#448 slice 6)
        events_module, events_functions = _bound_to(tree, EVENTS, package="openfactory.product")
        events_module |= {"events"}
        followup_module, followup_functions = _bound_to(tree, FOLLOWUP,
                                                        package="openfactory.product")
        accept_module, accept_functions = _bound_to(tree, ACCEPT, package="openfactory.product")
        acts, in_lambda_acts = _acts(tree)

        def where(line: int, functions=functions):
            inside = [f for f in functions if f.lineno <= line <= (f.end_lineno or f.lineno)]
            return max(inside, key=lambda f: f.lineno) if inside else None

        def around(line: int, functions=functions):
            return [f for f in functions if f.lineno <= line <= (f.end_lineno or f.lineno)]

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute | ast.Name) and _a_notice_handed_on(
                    node, events_module, events_functions):
                # A NOTICE HANDED ON, NOT CALLED (#448 slice 6): `asyncio.to_thread(events.
                # staged_for_you, …)` tells as surely as a call, and the round told that way
                fn = where(node.lineno)
                found.add((rel, fn.name if fn is not None else "<module>",
                           node.attr if isinstance(node, ast.Attribute)
                           else events_functions[node.id]))
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name) else "")
            on = func.value.id if (isinstance(func, ast.Attribute)
                                   and isinstance(func.value, ast.Name)) else ""
            fn = where(node.lineno)
            here = fn.name if fn is not None else "<module>"
            if name in WRITES:
                if (name == "set_state" and (rel, here) in BOX_WRITERS
                        and _a_progress_mark(fn, node)):
                    continue      # the box's progress mark, by rule (D7)
                found.add((rel, here, name))
            elif name in TEXT_WRITES:
                enclosing = around(node.lineno)
                beside_the_door = any(_named(f) & THE_DOOR for f in enclosing)
                in_an_act = id(node) in in_lambda_acts or any(f.name in acts for f in enclosing)
                if beside_the_door and not in_an_act:
                    found.add((rel, here, name))
            elif name in LOOP_WRITES and fn is not None and _named(fn) & (CARD_LOOPS | RELEASES):
                found.add((rel, here, name))
            elif (name in NOTICES and on in events_module) or (
                    isinstance(func, ast.Name) and events_functions.get(name) in NOTICES):
                found.add((rel, here, events_functions.get(name) or name))
            elif (name == "release_of" and on in followup_module) or (
                    isinstance(func, ast.Name) and followup_functions.get(name) == "release_of"):
                found.add((rel, here, "followup.release_of"))
            elif (name == "record" and on in accept_module) or (
                    isinstance(func, ast.Name) and accept_functions.get(name) == "record"):
                if not (id(node) in in_lambda_acts
                        or any(f.name in acts for f in around(node.lineno))):
                    found.add((rel, here, "accept.record"))
            elif (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                  and func.value.id in promise_module):
                found.add((rel, here, f"loops.{name}"))
            elif isinstance(func, ast.Name) and name in promise_functions:
                found.add((rel, here, f"loops.{name}"))
    return found, read


def _a_notice_handed_on(node: ast.AST, events_module: set[str],
                        events_functions: dict[str, str]) -> bool:
    """Whether `node` names a card's notice as a VALUE — `events.staged_for_you`, or a notice
    imported by name — in a load that is not itself the call (`card_writes` reads those)."""
    if not isinstance(getattr(node, "ctx", None), ast.Load):
        return False
    if isinstance(node, ast.Attribute):
        return (node.attr in NOTICES and isinstance(node.value, ast.Name)
                and node.value.id in events_module)
    return events_functions.get(node.id) in NOTICES


def _bound_to(tree: ast.AST, module: str, *, package: str) -> tuple[set[str], dict[str, str]]:
    """`(module aliases, {bound name: its name in the module})` a file binds to `module` — `from
    <package> import x`, `import <module> as y`, or `from <module> import f as g` — at any depth:
    the house imports inside functions."""
    leaf = module.rsplit(".", 1)[-1]
    aliases: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == package:
            aliases |= {a.asname or a.name for a in node.names if a.name == leaf}
        elif isinstance(node, ast.ImportFrom) and node.module == module:
            functions.update({a.asname or a.name: a.name for a in node.names})
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.name == module and a.asname}
    return aliases, functions


def _acts(tree: ast.AST) -> tuple[set[str], set[int]]:
    """What a file hands a transition as its `act=`: the functions, by name, and every call that
    lies in a `lambda` handed so (by `id`) — read once per file."""
    named: set[str] = set()
    in_lambdas: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "act":
                continue
            if isinstance(kw.value, ast.Name):
                named.add(kw.value.id)
            elif isinstance(kw.value, ast.Lambda):
                in_lambdas |= {id(sub) for sub in ast.walk(kw.value) if isinstance(sub, ast.Call)}
    return named, in_lambdas


def _the_door_s_loops(tree: ast.AST) -> tuple[set[str], set[str]]:
    """`(module aliases, function names)` a file binds to `lifecycle/loops.py` — imported as a
    module (`from openfactory.lifecycle import loops`, `import openfactory.lifecycle.loops as x`)
    or by name (`from openfactory.lifecycle.loops import announce`), at any depth: the house
    imports inside functions."""
    module: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "openfactory.lifecycle":
            module |= {a.asname or a.name for a in node.names if a.name == "loops"}
        elif isinstance(node, ast.ImportFrom) and node.module == DOOR_LOOPS:
            functions |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            module |= {a.asname for a in node.names if a.name == DOOR_LOOPS and a.asname}
    return module, functions


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


def test_slice_3_ends_with_the_list_empty():
    """D9's done-when for #414: nothing but the box's progress marks, allowed by rule, changes a
    card outside its door — the list, its ceiling and its baseline are all empty."""
    assert OUTSIDE_THE_DOOR == {} and BASELINE == frozenset() and CEILING == 0


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


def test_the_walk_sees_a_delivery_announced_beside_the_door_under_the_door_s_own_name(tmp_path):
    """The job's exit and the weekly sweep announced a delivery beside the door (#414); the one
    announcer is `lifecycle/loops.py` now, and a caller reaching it by name — as a module or a
    function, imported anywhere in the file — is a second announcer the walk finds."""
    rogue = tmp_path / "openfactory" / "runtime" / "rogue.py"
    rogue.parent.mkdir(parents=True)
    rogue.write_text(
        "def job_ended(project, card):\n"
        "    from openfactory.lifecycle import loops\n"
        "    loops.announce_what_it_completes(project, card)\n"
        "def weekly(project, delivered):\n"
        "    from openfactory.lifecycle.loops import announce\n"
        "    announce(project, delivered=delivered)\n"
        "def aliased(project, card):\n"
        "    import openfactory.lifecycle.loops as promises\n"
        "    promises.owe(project, card, {})\n"
        "def converged(project):\n"
        "    from openfactory.lifecycle import converge\n"
        "    return converge(project)\n",
        encoding="utf-8")
    found, _ = card_writes(tmp_path / "openfactory", rel_to=tmp_path)
    assert found == {("openfactory/runtime/rogue.py", "job_ended",
                      "loops.announce_what_it_completes"),
                     ("openfactory/runtime/rogue.py", "weekly", "loops.announce"),
                     ("openfactory/runtime/rogue.py", "aliased", "loops.owe")}, found


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


# ── the requester's loop past the pull request (#448 slice 6, ADR-0055 D9 amended 2026-10-05) ──

def _planted(tmp_path, source: str, *, where: str = "openfactory/product/rogue.py") -> set:
    rogue = tmp_path / where
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text(source, encoding="utf-8")
    found, _ = card_writes(tmp_path / "openfactory", rel_to=tmp_path)
    return found


def test_the_walk_sees_the_loops_notices_on_events_and_imported_by_name(tmp_path):
    """The requester hears the change went in, is theirs to try at a stage, and — the room — that
    they say it is right, only from the card's door (`lifecycle/ports.py::tell`). Said from anywhere
    else, on `events` or imported from it by name, under its old name or its door-side one, called
    or handed on to a thread (as the round told it until #448 slice 6), it is a second teller the
    walk finds."""
    found = _planted(tmp_path,
                     "from openfactory.product import events\n"
                     "from openfactory.product import events as ev\n"
                     "def merged(project):\n"
                     "    events.merged_for_you(project, card='1', pr_url='p')\n"
                     "def staged(project):\n"
                     "    ev.staged_for_you(project, card='1', run='r')\n"
                     "def tried(project):\n"
                     "    from openfactory.product.events import tried_and_right\n"
                     "    tried_and_right(project, card='1', run='r')\n"
                     "def went(project):\n"
                     "    from openfactory.product.events import went_in as said\n"
                     "    said(project, card='1', pr_url='p')\n"
                     "def stage(project):\n"
                     "    events.to_try_at_the_stage(project, card='1')\n"
                     "def right(project):\n"
                     "    events.tried_it_right(project, card='1', run='r')\n"
                     "async def handed_on(project):\n"
                     "    import asyncio\n"
                     "    await asyncio.to_thread(events.staged_for_you, project, card='1')\n"
                     "def harmless(project):\n"
                     "    events.room_of(project)\n")
    rel = "openfactory/product/rogue.py"
    assert found == {(rel, "merged", "merged_for_you"), (rel, "staged", "staged_for_you"),
                     (rel, "tried", "tried_and_right"), (rel, "went", "went_in"),
                     (rel, "stage", "to_try_at_the_stage"), (rel, "right", "tried_it_right"),
                     (rel, "handed_on", "staged_for_you")}, found


def test_the_walk_sees_a_cards_text_written_beside_its_door_and_not_inside_its_act(tmp_path):
    """The bar moved at a gate is the engine's half of the decision (`resumed`'s act), and a
    correction before the factory takes the card up is `edited`'s: in a function that goes through
    the door, the text is written only inside a function — or a lambda — handed to it as `act=`."""
    found = _planted(tmp_path,
                     "from openfactory.lifecycle import transition\n"
                     "def beside(project, tracker):\n"
                     "    tracker.update_body('#1', 'new')\n"
                     "    return transition(project, '1', 'edited', by='ana')\n"
                     "def renamed_beside(project, tracker):\n"
                     "    tracker.update_title('#1', 'new')\n"
                     "    return _through_the_door(project, '1', 'edited', by='ana')\n"
                     "def inside(project, tracker):\n"
                     "    def write():\n"
                     "        tracker.update_body('#1', 'new')\n"
                     "    return transition(project, '1', 'edited', by='ana', act=write)\n"
                     "def in_a_lambda(project, tracker):\n"
                     "    return transition(project, '1', 'edited', by='ana',\n"
                     "                      act=lambda: tracker.update_title('#1', 'new'))\n"
                     "def nowhere_near_a_door(tracker):\n"
                     "    tracker.update_body('#1', 'criteria')\n")
    rel = "openfactory/product/rogue.py"
    assert found == {(rel, "beside", "update_body"),
                     (rel, "renamed_beside", "update_title")}, found


def test_the_walk_sees_a_release_question_asked_or_answered_beside_the_door(tmp_path):
    """The release question is asked by the round's `staged` and answered by the verdicts'
    transitions (`lifecycle/loops.py`); a loop written in a function about a release, or any
    `followup.release_of`, is a second asker or answerer the walk finds."""
    found = _planted(tmp_path,
                     "from openfactory.memory.ledger import ACCEPTANCE, close_by_observation\n"
                     "from openfactory.product import followup\n"
                     "def answered(ledger, loop):\n"
                     "    if followup.is_release(loop):\n"
                     "        return close_by_observation(ledger, {})\n"
                     "def asked(issue):\n"
                     "    return followup.release_of(issue, channel='room', ts='t')\n"
                     "def asked_by_name(issue):\n"
                     "    from openfactory.product.followup import release_of\n"
                     "    return release_of(issue, channel='room', ts='t')\n"
                     "def read_only(loops):\n"
                     "    return [followup.is_release(x) for x in loops]\n")
    rel = "openfactory/product/rogue.py"
    assert found == {(rel, "answered", "close_by_observation"),
                     (rel, "asked", "followup.release_of"),
                     (rel, "asked_by_name", "followup.release_of")}, found


def test_the_walk_sees_the_requesters_yes_recorded_outside_a_transitions_act(tmp_path):
    """`accepted`'s act is the acceptance's record: written anywhere else — beside the door, or
    with no door at all — it is a yes no card's record holds."""
    found = _planted(tmp_path,
                     "from openfactory.product import accept\n"
                     "def beside(project, acc):\n"
                     "    accept.record(project.name, acc)\n"
                     "def by_name(project, acc):\n"
                     "    from openfactory.product.accept import record\n"
                     "    record(project.name, acc)\n"
                     "def inside(project, acc):\n"
                     "    def write():\n"
                     "        return None if accept.record(project.name, acc) else 'no'\n"
                     "    return transition(project, '1', 'accepted', by='ana', act=write)\n"
                     "def read_only(project):\n"
                     "    return accept.standing(project.name, '1')\n")
    rel = "openfactory/product/rogue.py"
    assert found == {(rel, "beside", "accept.record"), (rel, "by_name", "accept.record")}, found

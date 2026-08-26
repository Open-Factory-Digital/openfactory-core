"""Every loop in ADR-0021 must be opened, closed and chased by PRODUCTION code.

The ADR commits to this explicitly, and it is not ceremony: ten capabilities in this codebase have
been designed, implemented, unit-tested and called by nothing. A memory that nothing reads is the
most convincing form of that defect — every test green, every round silent, and no way to tell it
apart from a factory with nothing to remember.

`people.mention` is the case in point. It shipped with the product role, is covered by its own test
file, and until ADR-0021 was called by NOTHING — so every question the product role asked was
addressed to the room rather than to the person who could answer it, which is the exact behaviour
the product owner asked for when the role was designed.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROD = [p for p in Path("openfactory").rglob("*.py")]


def _calls_anywhere(name: str) -> list[str]:
    """Production files that CALL this name — AST, not text, so a docstring cannot satisfy it."""
    out = []
    for path in PROD:
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if (getattr(fn, "id", None) == name) or (getattr(fn, "attr", None) == name):
                    out.append(str(path))
                    break
    return out


def _mentions(name: str) -> list[str]:
    return [str(p) for p in PROD if name in p.read_text()]


def _store_calls(method: str) -> list[str]:
    """Production files that call sdlc.memory.store's `method` THROUGH an alias of that module.

    The first version of this guard matched any `.write(`/`.read()` by attribute name — which a
    file handle's `f.write` and an S3 body's `.read()` satisfied with the ledger fully unplugged.
    A guard a coincidence can satisfy guards nothing."""
    hits = []
    for path in PROD:
        if "openfactory/memory" in str(path):
            continue
        src = path.read_text()
        aliases = set()
        for line in src.splitlines():
            line = line.strip()
            if line.startswith("from openfactory.memory import store as "):
                aliases.add(line.rsplit(" as ", 1)[1].strip())
            elif line == "from openfactory.memory import store":
                aliases.add("store")
        if not aliases:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == method
                    and getattr(node.func.value, "id", None) in aliases):
                hits.append(str(path))
                break
    return hits


def test_the_ledger_is_both_WRITTEN_and_READ_by_production_code():
    """A ledger only written is a log nobody reads; a ledger only read is always empty. Either one
    alone looks exactly like an agent with nothing to remember."""
    assert _store_calls("write"), "nothing writes a loop through the store — memory always empty"
    assert _store_calls("read"), "nothing reads the ledger through the store — memory never used"


def _called_names(node) -> set[str]:
    """Every name `node` calls — and every function it HANDS TO A THREAD.

    `asyncio.to_thread(fn, …)` is a call of `fn` that a graph reading `ast.Call.func` alone cannot
    see: the callee is an ARGUMENT. Measured 2026-08-25: the panel's product turn is
    `await asyncio.to_thread(_product_conversation, project, inp)` (activities.py), so the whole
    conversation — the decision loop's opener with it — was reachable from its activity seed only
    through the Slack bot's direct call, and deleting the Slack package turned this file red with
    "decision: its only openers ['record_decisions'] are themselves unreachable". A guard reporting
    a defect in ITSELF: the loop was reached; the graph could not follow the reaching."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            out.add(getattr(n.func, "id", None) or getattr(n.func, "attr", ""))
            if ((getattr(n.func, "id", None) or getattr(n.func, "attr", None)) == "to_thread"
                    and n.args and isinstance(n.args[0], ast.Name)):
                out.add(n.args[0].id)
    return out - {""}


def _call_graph(*, without: tuple[str, ...] = ()) -> tuple[dict[str, set[str]], set[str]]:
    """(edges: function name → names it calls, seeds: names reachable by construction).

    Name-based on purpose. Two functions sharing a name merge into one node, which errs PERMISSIVE
    — a false "reachable", never a false alarm. For a guard, that is the right direction: what it
    still catches is the thing that has now happened twelve times, a function no name anywhere
    reaches.

    Seeds are the places execution genuinely starts: Temporal activities and workflow entry points
    (decorated), FastAPI routes, `main`s, and module-level calls (code that runs on import — the
    worker's boot lives there).

    `without` leaves whole packages OUT of the graph — path prefixes — so a caller can ask what is
    reachable on a deployment that does not ship them (a channel add-on, ADR-0038 D3)."""
    edges: dict[str, set[str]] = {}
    seeds: set[str] = set()

    for path in PROD:
        if any(str(path).startswith(prefix) for prefix in without):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        # module level: runs on import
        module_body = [n for n in tree.body
                       if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef
                                         | ast.ClassDef)]
        seeds |= set().union(*(_called_names(n) for n in module_body)) if module_body else set()
        # A DISPATCH TABLE IS AN ENTRY POINT. The action catalog (C-23) binds each implementation as
        # `run=<name>` inside an `ActionSpec(...)` literal and `perform` calls it through the row —
        # so a name-based graph sees the function referenced by nobody and called by nothing, which
        # is indistinguishable from dead code. It is the same shape as a FastAPI route or a Temporal
        # activity, both already seeded above: something outside this graph looks the name up.
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "run" and isinstance(
                    node.value, ast.Name):
                seeds.add(node.value.id)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            edges.setdefault(node.name, set()).update(_called_names(node))
            decorations = " ".join(ast.unparse(d) for d in node.decorator_list)
            if ("activity" in decorations or "workflow" in decorations
                    or "app." in decorations or "router." in decorations
                    or node.name == "main"):
                seeds.add(node.name)
    return edges, seeds


def _reachable_from(edges: dict[str, set[str]], seeds: set[str]) -> set[str]:
    """Transitive closure over `edges` from exactly these seeds — a caller that wants to know what
    ONE entry point reaches, rather than what the whole tree does."""
    seen, frontier = set(seeds), list(seeds)
    while frontier:
        for name in edges.get(frontier.pop(), ()):  # noqa: B909 — worklist algorithm
            if name not in seen:
                seen.add(name)
                frontier.append(name)
    return seen


def _reachable() -> set[str]:
    edges, seeds = _call_graph()
    return _reachable_from(edges, seeds)


def test_the_graph_follows_a_function_HANDED_TO_A_THREAD():
    """The positive twin of the `to_thread` reading: a callee passed as an argument is seen as
    called, and an ordinary call is still seen as one. Without this, a guard that walks every
    entry point and reports "unreachable" for a function the worker runs on every turn is a guard
    that can only be satisfied by a SECOND caller — which is how the Slack bot became the only
    proof the decision loop was ever opened."""
    tree = ast.parse("async def turn(project, inp):\n"
                     "    await asyncio.to_thread(_conversation, project, inp)\n"
                     "    return render(inp)\n")
    assert {"to_thread", "_conversation", "render"} <= _called_names(tree)


def _open_loop_sites() -> dict[str, list[tuple[str, str]]]:
    """kind → [(file, enclosing function)] for every `open_loop(KIND, ...)` call in production.
    AST, not substring: the FINDING opener spans two lines and a substring scan missed it."""
    sites: dict[str, list[tuple[str, str]]] = {}
    for path in PROD:
        if "openfactory/memory" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and (getattr(node.func, "id", None) == "open_loop"
                             or getattr(node.func, "attr", None) == "open_loop")
                        and node.args and isinstance(node.args[0], ast.Name)):
                    sites.setdefault(node.args[0].id.lower(), []).append((str(path), fn.name))
    return sites


def test_every_loop_kind_is_opened_from_a_REAL_entry_point():
    """A kind nobody opens is a row that never exists; the feature is inert and the tests pass.

    Three versions of this guard, each killed by its own sabotage test. V1 counted any mention
    outside openfactory/memory — `delivery` passed on a library function called by nothing (twelfth
    instance of the repo's signature defect). V2 searched by substring — missed the `finding`
    opener because the call spans two lines. V3 checked ONE step of reachability — a dead caller
    satisfied it, since it could not tell that the caller was itself unreached. This one walks the
    call graph transitively from genuine entry points, which is what "reached" actually means."""
    from openfactory.memory.ledger import KINDS

    sites = _open_loop_sites()
    alive = _reachable()
    problems = []
    for kind in KINDS:
        where = sites.get(kind, [])
        if not where:
            problems.append(f"{kind}: opened by nothing at all")
        elif not any(fn in alive for _, fn in where):
            problems.append(
                f"{kind}: its only openers {sorted({fn for _, fn in where})} are themselves "
                f"unreachable from any entry point")
    assert not problems, "; ".join(problems)


def test_loops_are_CLOSED_by_production_code_not_only_by_tests():
    """Opened and never closed is worse than not tracking at all: the list grows for ever and
    everyone learns to ignore it."""
    closers = [f for f in _calls_anywhere("close_by_observation") if "openfactory/memory" not in f]
    assert closers, "nothing closes a loop — every list would grow without bound"


def _functions_referencing(kind_const: str):
    """(file, function) pairs whose BODY references the kind constant as a NAME node — an
    identifier the code evaluates, which a docstring or comment can never satisfy. The first
    version substring-matched `ast.unparse` output, which includes docstrings: deleting the only
    real delivery-closer kept it green because a docstring elsewhere said the word."""
    for path in PROD:
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            if kind_const in names:
                yield str(path), fn.name


_CLOSERS = ("close_by_observation", "answered", "delivered")


def test_EVERY_kind_has_a_reachable_closer():
    """Opened and never closed is worse than not tracking: the list grows for ever and everyone
    learns to ignore it. Per kind: some REACHABLE production function must reference the kind (as
    a Name the code evaluates) and call one of the closing helpers — or, for `finding`, the human
    `ack` path must be live (asserted separately below)."""
    from openfactory.memory.ledger import KINDS

    alive = _reachable()
    unclosed = []
    for kind in KINDS:
        ok = False
        for file, fn_name in _functions_referencing(kind.upper()):
            if "openfactory/memory" in file or fn_name not in alive:
                continue
            tree = ast.parse(Path(file).read_text())
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                      and n.name == fn_name)
            called = {getattr(c.func, "id", None) or getattr(c.func, "attr", "")
                      for c in ast.walk(fn) if isinstance(c, ast.Call)}
            # either the kind-referencing function INVOKES closing, or it IS the closing helper
            # itself (followup.delivered names DELIVERY and builds the observations; its caller
            # names no kind at all — both shapes are a real closer)
            if called & set(_CLOSERS) or fn_name in _CLOSERS:
                ok = True
                break
        if not ok:
            unclosed.append(kind)
    assert not unclosed, (
        f"these loops open and no REACHABLE function ever closes them: {unclosed}"
    )


def test_a_loop_kind_with_no_observable_close_is_closed_by_a_PERSON():
    """The `finding` case, stated as a rule.

    A review finding on a merged ticket has nothing left to observe — no reply to read, no state
    change to watch. Rather than invent an observation (which would be a memory that lies), it asks
    for the one thing that genuinely means somebody has it: a person typing `ack #N`."""
    from openfactory.contracts.commands import ACK_VERBS, parse_command

    assert "ack" in ACK_VERBS
    assert parse_command("ack #478") == ("ack", "478")
    # and it must NOT fire on ordinary conversation, or it closes loops nobody meant to close
    assert parse_command("ok, o #412 está pronto") is None
    assert parse_command("ok") is None


def test_something_actually_CHASES():
    chasers = [f for f in _calls_anywhere("chase_due") if "openfactory/memory" not in f]
    assert chasers, "nothing chases — a question that goes quiet stays quiet for ever"


def test_the_product_role_NAMES_the_person_it_needs_an_answer_from():
    """`people.mention` existed and was tested from the day the product role shipped, and was
    called by nothing. "Somebody should clarify #412" is a message everybody reads and nobody owns —
    which is precisely what was asked not to happen."""
    callers = [f for f in _calls_anywhere("mention") if "slack/people.py" not in f]
    assert callers, "mention() is still reached by nothing; every question goes to the room"


def test_a_review_that_rejected_something_reaches_a_person():
    """#478 merged with a rejected review and a critical finding, and it reached no channel, no
    comment and no person. Advisory review is the design; silence was not."""
    callers = _calls_anywhere("_flag_review_findings")
    assert callers, "nothing flags a rejected review — a critical finding evaporates again"


def test_the_activity_that_records_it_is_registered_on_the_worker():
    """An imported-but-unregistered activity raises NotFoundError only when it is finally invoked,
    in production, on the day it matters. Checked by MEMBERSHIP in the real list: the previous
    substring assert was satisfied by the import line alone, so deleting the registration while
    keeping the import stayed green across the whole suite — the exact NotFoundError shape the
    worker's own comment warns about."""
    from openfactory.runtime.temporal.activities import open_review_loop
    from openfactory.runtime.temporal.worker import WORKER_ACTIVITIES

    assert open_review_loop in WORKER_ACTIVITIES

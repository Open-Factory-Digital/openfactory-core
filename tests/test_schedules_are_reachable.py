"""Every schedule this codebase can create must actually be created by something.

THE DEFECT THIS EXISTS FOR, STATED PLAINLY. `ensure_techlead_watch` and `ensure_product_sweeps`
were designed, written, unit-tested and their workflows registered on the worker — and called by
nothing. The tech-lead's hourly rounds and the product role's weekly sweep would never have fired,
in any deployment, ever. Nothing was red. The whole suite passed.

That is the eighth instance of one failure mode in this repo: a capability that is built, tested,
and reached by no entry point. It is worse than a missing feature, because a missing feature is
obvious and this one has green tests and a docs page.

So the guard is reachability, not correctness: for each `ensure_*` in schedule.py, somebody outside
that module must call it. `test_worker_registration` does the same job for activities, for the same
reason and after the same kind of incident.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCHEDULE = Path("openfactory/runtime/temporal/schedule.py")


def _ensure_functions() -> set[str]:
    """Derived from the source, never a hand-kept list — a list somebody must remember to update is
    the same class of bug one level up."""
    tree = ast.parse(SCHEDULE.read_text())
    return {
        n.name
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
        and n.name.startswith("ensure_")
        and n.name != "ensure_all"  # the aggregator; its own reachability is asserted below
    }


#: Entry points inside schedule.py that are themselves proven reachable — `ensure_all` by the
#: worker-boot assertion below, `main` by the module being runnable. Reachability is transitive, so
#: a call from one of these is a real call; a call from another `ensure_*` would not be.
_REACHABLE_ENTRY_POINTS = ("ensure_all", "main")


def _calls_in(node: ast.AST) -> set[str]:
    """The names this code actually CALLS.

    AST rather than a substring search, and the difference is not pedantry: the first version of
    this file searched text, and `ensure_all`'s own docstring names the very functions it must call
    — so deleting the calls left the guard green. A guard that a docstring can satisfy is a guard
    that proves nothing."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return out


def _callers_of(name: str) -> list[str]:
    """Where this function is actually invoked from, following the chain one honest step."""
    hits = []
    for path in list(Path("openfactory").rglob("*.py")) + list(Path("tests").rglob("*.py")):
        try:
            source = path.read_text()
        except FileNotFoundError:
            # A SIBLING TEST WRITES AND DELETES A REAL FILE UNDER `tests/`
            # (`test__live_engine_probe__.py`, in the guard that proves the live-engine barrier is
            # applied to an actual pytest run). Under `-n auto` this walk can list it and then
            # find it gone — a random-order-only failure, which is a race and never a flake.
            #
            # Tolerated rather than filtered by name: `rglob` cannot list a file that does not
            # exist, so the only way to reach this branch is a file that vanished BETWEEN the
            # listing and the read. A missing caller is still a missing caller.
            continue
        tree = ast.parse(source)
        if path == SCHEDULE:
            # inside its own module, only a call from a proven entry point counts
            for node in tree.body:
                if (
                    isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
                    and node.name in _REACHABLE_ENTRY_POINTS
                    and name in _calls_in(node)
                ):
                    hits.append(f"{path}::{node.name}")
        elif name in _calls_in(tree):
            hits.append(str(path))
    return hits


def test_every_ensure_is_called_from_production_code():
    """A test calling it does not count. Tests prove it works; only production code makes it run."""
    unreachable = []
    for fn in sorted(_ensure_functions()):
        prod = [c for c in _callers_of(fn) if not c.startswith("tests/")]
        if not prod:
            unreachable.append(fn)
    assert not unreachable, (
        f"schedule functions nothing in sdlc/ ever calls: {unreachable}. They will never run in "
        f"any deployment. Call them from ensure_all() (which the worker runs at boot)."
    )


def test_ensure_all_covers_every_ensure():
    """The aggregator must not drift behind a newly added schedule — the drift would be silent, and
    the symptom would be a watcher that simply never watches."""
    tree = ast.parse(SCHEDULE.read_text())
    agg = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == "ensure_all"
    )
    called = _calls_in(agg)
    missing = [fn for fn in sorted(_ensure_functions()) if fn not in called]
    assert not missing, f"ensure_all() does not call: {missing}"


def test_the_worker_reconciles_schedules_at_boot():
    """Boot is the reconciliation point because a deploy is the one event guaranteed to happen. If
    this moves somewhere else, this assertion should move with it — deliberately, not by accident."""
    worker = Path("openfactory/runtime/temporal/worker.py").read_text()
    assert "ensure_all" in worker, "the worker no longer reconciles schedules at boot"


def test_reconciliation_failure_is_loud():
    """Best-effort must never mean silent. A worker that came up without the tech-lead's rounds
    looks exactly like a factory with nothing to report — which is the failure #478 was made of."""
    worker = Path("openfactory/runtime/temporal/worker.py").read_text()
    tree = ast.parse(worker)
    handlers = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Try) and "ensure_all" in ast.unparse(n.body)
    ]
    assert handlers, "ensure_all() is not wrapped — a Temporal hiccup would stop the worker booting"
    for h in handlers:
        for eh in h.handlers:
            spoken = ast.unparse(ast.Module(body=eh.body, type_ignores=[]))
            assert "log." in spoken or "raise" in spoken, (
                "schedule reconciliation can fail without saying so"
            )


def test_the_poller_is_created_but_never_silently_retimed():
    """The poller's interval is a live dial somebody may turn during an incident. Boot provisioning
    a missing one is helpful; boot resetting a running one to the source default undoes a decision
    nobody remembers making."""
    source = SCHEDULE.read_text()
    body = source[source.index("async def ensure_poller"):]
    body = body[: body.index("\nasync def ensure_all")]
    assert "create_schedule" in body
    assert ".update(" not in body, "ensure_poller would overwrite a live interval at every deploy"

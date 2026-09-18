"""Nothing outside the engine's own directory imports the engine's client by accident (#178).

THE SWEEP OF #178 ASKED THE ROUTES AND THE COMMANDS, and found a hole neither could show: six
sites of the attended half — the transcript, the messages, the people store, the chat's spend, the
product role's — reached across the runtime for `activities._metrics_sink`, a one-line wrapper over
the deployment's one sink door, and `activities.py` imports `temporalio`. Four of them sat in an
`except Exception` and recorded nothing, silently. `identity/people.py` did not, so on an install
made without the `runtime` extra `openfactory people invite` — the panel's own login on a
local-identity deployment — answered `could not people_invite: No module named 'temporalio'`.

A GET sweep cannot see that class: the import is inside a function, behind a POST, behind a request
body. So this reads the SOURCE instead. It walks the package with `ast`, works out which modules
cost `temporalio` to import (a fixpoint over module-level imports, so a module that imports a
module that imports it counts), and then finds every import of one of those — top-level AND inside
a function — made from outside `openfactory/runtime/temporal/`. Each is either:

  * inside a `try` whose handler catches an `ImportError`;
  * behind the question `up` asks (`host.the_client()` / `cli._refuse_without_the_client`), on an
    earlier line of the same function;
  * in a nested function whose every call is inside such a `try`;
  * the body of an action row — `actions.perform`'s catch-all is the one guard they all share, and
    it names the install;
  * or on the NAMED list below, with the reason it is legitimately the engine's.

Anything else fails, naming the file, the function and the module it reached for. The list is held
EXACTLY — an entry whose import is gone fails too — so it cannot rot into a list of permissions.

PARSED, NEVER GREPPED: this codebase's comments quote the lines they replaced, and a text search
would be satisfied, or alarmed, by prose. And the sweep is proven able to fail on a planted tree.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LIBRARY = "temporalio"
ENGINE_DIR = "openfactory/runtime/temporal/"
#: Where an action row's body lives. `actions.perform` runs every row inside one catch-all.
ACTION_ROWS = "openfactory/actions/catalog.py"
#: A handler that names any of these catches a module that cannot be found.
_CATCHES_IMPORT = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
#: The question `up` asks before it plans a worker, and the CLI's way of asking it.
_ASKS_FIRST = {"the_client", "_refuse_without_the_client"}

#: UNGUARDED ON PURPOSE — `(file, function, module reached)`, and why each is the engine's own.
NAMED: dict[tuple[str, str, str], str] = {
    ("openfactory/floor/reading.py", "intake_cached", "openfactory.runtime.temporal.view"):
        "takes a CONNECTED engine client, and raises by contract: its callers each own an `except` "
        "that answers `connected: False`, and `_intake` is the wrapper that degrades it",
    ("openfactory/product/release.py", "parked_for_release", "openfactory.runtime.temporal.view"):
        "takes a CONNECTED engine client and lists its workflows — there is no client to pass on "
        "an install without the library",
    ("openfactory/techlead/conversation.py", "_verdicts",
     "openfactory.runtime.temporal.workflow"):
        "takes a CONNECTED engine client; its one caller (`gather_jobs._run`) wraps it in a `try` "
        "and is itself only called under one",
    ("openfactory/testing/local_flow.py", "run_flow",
     "openfactory.runtime.temporal.activities"):
        "the offline harness for the WORKER's own pre-flight and split activities — it is the "
        "engine's code under test, not a front end",
}


# ── the sweep ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reach:
    """One import of a module that costs the library, made from outside the engine's directory."""

    file: str
    function: str          # dotted through nesting; "<module>" at the top level
    target: str
    line: int
    guard: str             # "" = unguarded

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.file, self.function, self.target)


def _modules(root: Path) -> dict[str, Path]:
    found = {}
    for path in (root / "openfactory").rglob("*.py"):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    return found


def _loads(node: ast.Import | ast.ImportFrom, here: str, modules: dict[str, Path]) -> set[str]:
    """Every module this statement imports — the named one, a `from pkg import submodule`, and
    each parent package, since importing `a.b.c` runs `a` and `a.b` first."""
    named = []
    if isinstance(node, ast.Import):
        named = [alias.name for alias in node.names]
    else:
        base = node.module or ""
        if node.level:
            package = here.split(".")
            if modules[here].name != "__init__.py":
                package = package[:-1]
            package = package[: len(package) - (node.level - 1)]
            base = ".".join([*package, base] if base else package)
        named = [base, *(f"{base}.{a.name}" for a in node.names if f"{base}.{a.name}" in modules)]
    loaded = set()
    for name in named:
        bits = name.split(".")
        loaded |= {".".join(bits[:i]) for i in range(1, len(bits) + 1)}
    return loaded


def _catches_import(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        kind = handler.type
        if kind is None:
            return True
        kinds = kind.elts if isinstance(kind, ast.Tuple) else [kind]
        if _CATCHES_IMPORT & {getattr(k, "id", getattr(k, "attr", "")) for k in kinds}:
            return True
    return False


def _is_type_checking(test: ast.expr) -> bool:
    return getattr(test, "id", getattr(test, "attr", "")) == "TYPE_CHECKING"


def _walk(tree: ast.Module):
    """Yield `(statement, enclosing function nodes, inside a try that catches the import)` for
    every import and every call — calls, because a nested function is judged by where it is
    CALLED, not where it is written."""

    def visit(body: list[ast.AST], stack: tuple, tried: bool):
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                yield node, stack, tried
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from visit(node.body, (*stack, node), False)
            elif isinstance(node, ast.If) and _is_type_checking(node.test):
                yield from visit(node.orelse, stack, tried)   # never executed: costs nothing
            elif isinstance(node, ast.Try):
                yield from visit(node.body, stack, tried or _catches_import(node.handlers))
                for handler in node.handlers:
                    yield from visit(handler.body, stack, tried)
                yield from visit([*node.orelse, *node.finalbody], stack, tried)
            else:
                if isinstance(node, ast.Call):
                    yield node, stack, tried
                yield from visit(list(ast.iter_child_nodes(node)), stack, tried)

    yield from visit(tree.body, (), False)


def costly_modules(root: Path) -> set[str]:
    """The package's modules whose IMPORT costs the library: those that import it at module level,
    and — to a fixpoint — those that import one of those at module level."""
    modules = _modules(root)
    top_level: dict[str, set[str]] = {}
    for name, path in modules.items():
        loaded: set[str] = set()
        for node, stack, _ in _walk(ast.parse(path.read_text())):
            if not stack and isinstance(node, ast.Import | ast.ImportFrom):
                loaded |= _loads(node, name, modules)
        top_level[name] = loaded
    costly: set[str] = set()
    while True:
        more = {name for name, loaded in top_level.items() if name not in costly
                and (any(m.split(".")[0] == LIBRARY for m in loaded) or loaded & costly)}
        if not more:
            return costly
        costly |= more


def sweep(root: Path) -> list[Reach]:
    modules = _modules(root)
    costly = costly_modules(root)
    found: list[Reach] = []
    for name, path in modules.items():
        file = path.relative_to(root).as_posix()
        if file.startswith(ENGINE_DIR):
            continue
        rows = list(_walk(ast.parse(path.read_text())))
        calls = [(node, stack, tried) for node, stack, tried in rows if isinstance(node, ast.Call)]

        def called_only_under_a_try(function, stack, calls=calls) -> bool:
            sites = [tried for node, where, tried in calls
                     if getattr(node.func, "id", None) == function.name
                     and where[:len(stack) - 1] == stack[:-1] and len(where) >= len(stack) - 1
                     and function not in where]
            return bool(sites) and all(sites)

        def asks_first(function, line, calls=calls) -> bool:
            return any(getattr(node.func, "id", getattr(node.func, "attr", "")) in _ASKS_FIRST
                       and node.lineno < line and function in where
                       for node, where, _ in calls)

        for node, stack, tried in rows:
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            reached = sorted(m for m in _loads(node, name, modules)
                             if m in costly or m.split(".")[0] == LIBRARY)
            if not reached:
                continue
            guard = ""
            if tried:
                guard = "try"
            elif stack and asks_first(stack[-1], node.lineno):
                guard = "asks first"
            elif len(stack) > 1 and called_only_under_a_try(stack[-1], stack):
                guard = "nested, called only under a try"
            elif stack and file == ACTION_ROWS:
                guard = "an action row's body"
            found.append(Reach(file, ".".join(f.name for f in stack) or "<module>", reached[-1],
                               node.lineno, guard))
    return sorted(found, key=lambda r: (r.file, r.line))


@cache
def _this_tree() -> tuple[Reach, ...]:
    return tuple(sweep(ROOT))


# ── the guard ────────────────────────────────────────────────────────────────────────────────────

def test_the_sweep_knows_which_modules_cost_the_library():
    """A sweep that finds nothing because it recognises nothing is the failure to rule out first."""
    costly = costly_modules(ROOT)
    engine = "openfactory.runtime.temporal."

    assert {engine + m for m in ("view", "workflow", "activities", "connection", "schedule",
                                 "poller", "worker")} <= costly, sorted(costly)
    assert not {engine + "vocabulary", engine + "io", engine.rstrip("."),
                "openfactory.runtime.host"} & costly, (
        "a module the panel imports on every page is reported as costing the engine's client")
    outside = sorted(m for m in costly
                     if not _modules(ROOT)[m].relative_to(ROOT).as_posix().startswith(ENGINE_DIR))
    assert not outside, (
        f"importing these costs `{LIBRARY}` although they live outside {ENGINE_DIR}: {outside}")


def test_every_reach_for_the_engine_from_outside_it_is_guarded_or_named():
    reaches = _this_tree()
    assert len(reaches) >= 20, f"the sweep found only {len(reaches)} — it is not reading the tree"

    unguarded = {r.key: r for r in reaches if not r.guard}
    strangers = [f"{r.file}:{r.line}  {r.function}  imports {r.target}"
                 for key, r in sorted(unguarded.items()) if key not in NAMED]
    assert not strangers, (
        f"these import a module that costs `{LIBRARY}` from outside {ENGINE_DIR}, outside any "
        f"`try` that catches the import, and without asking `host.the_client()` first — so on an "
        f"install made without the `runtime` extra they end in a raw ModuleNotFoundError. Move "
        f"the word to `runtime/temporal/vocabulary.py`, call the public seam, put the import "
        f"inside the `try`, or name it in NAMED with why it is the engine's own:\n  "
        + "\n  ".join(strangers))


def test_the_named_list_names_only_what_is_there():
    """Held exactly, so it cannot become a list of permissions nobody re-reads."""
    unguarded = {r.key for r in _this_tree() if not r.guard}
    gone = sorted(set(NAMED) - unguarded)
    assert not gone, f"NAMED lists imports that are no longer there, or are guarded now: {gone}"


def test_the_action_rows_are_only_reached_through_the_layer_that_guards_them():
    """"An action row's body" is a guard only while nothing outside the layer calls into the
    catalog's engine-reaching functions directly. Whatever the rest of the package imports from
    the catalog must therefore be a function that reaches for nothing of the engine."""
    modules = _modules(ROOT)
    catalog = "openfactory.actions.catalog"
    reaching = {r.function.split(".")[0] for r in _this_tree() if r.file == ACTION_ROWS}

    borrowed: dict[str, str] = {}
    for name, path in modules.items():
        if name.startswith("openfactory.actions"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == catalog:
                borrowed.update({alias.name: name for alias in node.names})
    direct = {fn: by for fn, by in borrowed.items() if fn in reaching}
    assert not direct, (
        f"called from outside the action layer, so `perform`'s catch-all is not around them: "
        f"{direct}")


def test_the_sweep_CAN_FAIL(tmp_path):
    """Planted: a module that costs the library at one remove, and the same import written eight
    ways. The bare one, the one whose `try` catches something else, the one that asks too late and
    the nested one called bare must come back unguarded — and nothing else may."""
    pkg = tmp_path / "openfactory"
    (pkg / "runtime" / "temporal").mkdir(parents=True)
    (pkg / "actions").mkdir()
    for init in (pkg, pkg / "runtime", pkg / "runtime" / "temporal", pkg / "actions"):
        (init / "__init__.py").write_text("")
    (pkg / "runtime" / "temporal" / "client.py").write_text("import temporalio\n")
    (pkg / "runtime" / "temporal" / "reader.py").write_text(
        "from openfactory.runtime.temporal import client\n")          # costs it at one remove
    (pkg / "runtime" / "temporal" / "words.py").write_text("WORD = 'w'\n")
    (pkg / "actions" / "catalog.py").write_text(
        "def row():\n    from openfactory.runtime.temporal import reader\n")
    (pkg / "panel.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from openfactory.runtime.temporal import reader\n"
        "from openfactory.runtime.temporal.words import WORD\n"
        "def bare():\n"
        "    from openfactory.runtime.temporal.reader import x\n"
        "def tried():\n"
        "    try:\n"
        "        from openfactory.runtime.temporal import reader\n"
        "    except ImportError:\n"
        "        return None\n"
        "def tried_for_something_else():\n"
        "    try:\n"
        "        from openfactory.runtime.temporal import reader\n"
        "    except ValueError:\n"
        "        return None\n"
        "def asks(host):\n"
        "    if not host.the_client():\n"
        "        return None\n"
        "    from openfactory.runtime.temporal import reader\n"
        "def asks_too_late(host):\n"
        "    from openfactory.runtime.temporal import reader\n"
        "    if not host.the_client():\n"
        "        return None\n"
        "def outer():\n"
        "    def inner():\n"
        "        from openfactory.runtime.temporal import reader\n"
        "    try:\n"
        "        return inner()\n"
        "    except Exception:\n"
        "        return None\n"
        "def outer_bare():\n"
        "    def inner():\n"
        "        from openfactory.runtime.temporal import reader\n"
        "    return inner()\n")

    assert costly_modules(tmp_path) == {"openfactory.runtime.temporal.client",
                                        "openfactory.runtime.temporal.reader"}
    got = {r.function: r.guard for r in sweep(tmp_path)}
    assert got == {
        "bare": "",
        "tried": "try",
        "tried_for_something_else": "",
        "asks": "asks first",
        "asks_too_late": "",
        "outer.inner": "nested, called only under a try",
        "outer_bare.inner": "",
        "row": "an action row's body",
    }, got


# ── what the sweep was written for, driven ───────────────────────────────────────────────────────

_CHILD = r'''
import importlib.abc, json, logging, os, sys


class _Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "temporalio":
            raise ModuleNotFoundError(f"No module named {name!r}", name="temporalio")
        return None


sys.meta_path.insert(0, _Refuse())
logging.disable(logging.CRITICAL)

from typer.testing import CliRunner

from openfactory import cli
from openfactory.adapters.board_setup.local import LocalBoardSetup
from openfactory.contracts.project import Project, ProviderRef
from openfactory.registry import ProjectRegistry

registry = ProjectRegistry()
registry.add(Project(name="acme", repo_path=os.environ["HOME"],
                     tracker=ProviderRef(kind="local", repo="acme", options={})))
LocalBoardSetup().create(project=registry.get("acme"), owner="", title="acme", token=None)

said = {}
for argv in (["people", "invite", "ana@example.com"], ["people", "list"], ["poller", "status"],
             ["act", "stop", "-p", "acme", "-i", "1"], ["act", "scan", "-p", "acme"]):
    result = CliRunner().invoke(cli.app, argv)
    said[" ".join(argv)] = {"exit": result.exit_code, "said": " ".join(result.output.split())}

# The five sites that record, each through its own front door, then read back from the store.
from openfactory.memory import messages, transcript
from openfactory.techlead import conversation

landed = {
    "messages.say": messages.say("acme", "picked up #1"),
    "transcript.record": bool(transcript.record("acme", thread="T1", role="user", text="oi")),
}
conversation._record_chat_spend(registry.get("acme"), {"cost_usd": 0.1, "num_turns": 1})
from openfactory.observability.registry import deployment_metrics_sink

rows = deployment_metrics_sink().scan()
print("\n@@RESULT@@" + json.dumps({
    "said": said, "landed": landed,
    "kinds": sorted({(r.get("kind") or "") + ":" + (r.get("role") or "") for r in rows}),
    "engine_loaded": sorted(m for m in sys.modules if m.split(".")[0] == "temporalio")[:3]}))
'''


@cache
def _without_the_library() -> dict:
    import tempfile

    home = tempfile.mkdtemp(prefix="of-no-engine-client-")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("OPENFACTORY_", "TEMPORAL_"))}
    env.update(HOME=home, PYTHONPATH=str(ROOT),
               OPENFACTORY_REGISTRY=str(Path(home) / "registry.yaml"),
               OPENFACTORY_BOARD_DB=str(Path(home) / "board.db"),
               OPENFACTORY_METRICS_SINK="sqlite",
               OPENFACTORY_METRICS_DB=str(Path(home) / "metrics.db"))
    done = subprocess.run([sys.executable, "-c", _CHILD], cwd=home, env=env, capture_output=True,
                          text=True, timeout=300)
    assert "@@RESULT@@" in done.stdout, (
        f"the child interpreter never reported:\n{done.stdout[-1500:]}\n{done.stderr[-3000:]}")
    return json.loads(done.stdout.rsplit("@@RESULT@@", 1)[1])


def _names_the_install(text: str) -> bool:
    return "pip install -e '.[runtime]'" in text and "temporalio" in text


def test_a_person_is_invited_on_an_install_without_the_engines_client():
    """The defect itself: registration by invitation is the panel's own login on a local-identity
    deployment, and it answered `could not people_invite: No module named 'temporalio'`."""
    got = _without_the_library()
    invited, listed = got["said"]["people invite ana@example.com"], got["said"]["people list"]

    assert invited["exit"] == 0 and "/auth/register?invite=" in invited["said"], invited
    assert "ana@example.com" in listed["said"], f"the invitation was said and not recorded: {listed}"
    assert got["engine_loaded"] == []


def test_the_attended_half_RECORDS_without_the_engines_client():
    """Four of the six sites sat in an `except Exception`, so without the library they did not
    fail — they recorded nothing, and said nothing. Read back from the store, not from a return."""
    got = _without_the_library()

    assert got["landed"] == {"messages.say": True, "transcript.record": True}, got["landed"]
    assert {"agent_run:chat", "channel_message:_factory_", "message:user",
            "person:invited"} <= set(got["kinds"]), got["kinds"]


def test_one_patch_on_the_door_reaches_the_workers_name_for_it_too(monkeypatch):
    """`activities._metrics_sink` asks the door AT CALL TIME. Bound to it at import instead, a
    fake handed to the door (`tests/the_sink_door.py`) would reach the attended half and miss the
    worker — two patch points again, which is how nine test files came to patch the wrong one."""
    pytest.importorskip("temporalio")
    from openfactory.runtime.temporal import activities
    from tests.the_sink_door import SINK_DOOR

    fake = object()
    monkeypatch.setattr(SINK_DOOR, lambda: fake)

    assert activities._metrics_sink() is fake


def test_poller_status_names_the_install_instead_of_asking_about_the_engine():
    status = _without_the_library()["said"]["poller status"]

    assert status["exit"] == 2 and _names_the_install(status["said"]), status
    assert "is the engine reachable" not in status["said"], status


@pytest.mark.parametrize("row", ["stop", "scan"])
def test_an_action_that_IS_the_engines_names_the_install(row):
    """`perform`'s catch-all is what makes "an action row's body" a guard — so it is driven, through
    the real rows, rather than trusted."""
    argv = "act stop -p acme -i 1" if row == "stop" else "act scan -p acme"
    said = _without_the_library()["said"][argv]

    assert said["exit"] != 0 and _names_the_install(said["said"]), said
    assert "No module named" not in said["said"], said


def test_any_OTHER_failure_of_an_action_keeps_its_own_words():
    from openfactory import actions

    assert actions._why(RuntimeError("the forge said no")) == "the forge said no"
    assert not _names_the_install(actions._why(ModuleNotFoundError("No module named 'boto3'",
                                                                  name="boto3")))
    wrapped = RuntimeError("could not reach the floor")
    wrapped.__cause__ = ModuleNotFoundError("No module named 'temporalio'", name="temporalio")
    assert _names_the_install(actions._why(wrapped)), "the import is what it died of"

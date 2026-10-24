"""The installation is changed through its rows, and only by its administrator (#741).

Every verb that changes what a deployment IS — the people it names, whether it picks work up, what
its product role is called and where its requirements live — was the command line's own code.
`poller pause` held the engine's schedule itself, `product name` and `product declare` wrote the
registry themselves, and nothing at all took a person back. So the panel, a script holding its
token and any front end of one's own (`POST /api/act/{name}`) could do none of it.

THE RULES HELD HERE, each over cases read from the code rather than named:

  1. a catalogue row that writes the installation — a registry writer, a people-store writer, the
     poller's hold, each read off its own module — is declared `installation`, and a row declared
     one writes it;
  2. an installation row is the administrator's: a credential scoped to either area is refused it
     before its runner runs, by `perform` and at the panel's door, and an unscoped one reaches it;
  3. no installation row is something the tech-lead may propose;
  4. the contract a front end is written against lists exactly the installation's rows;
  5. the doctor's document is one document, whichever door asked for it;
  6. a person revoked is gone — account, sessions and links — and the last one registered is not
     revoked while nothing else closes the panel's door;
  7. a project's own settings are set by its rows, and the command line writes none of them;
  8. a project is registered by one row, whichever door asked, and a registered one is never
     written over;
  9. a row of several steps says what each step came to — a step that raises is a failed step,
     said, never a traceback, and never with the credential a git call was handed — and running
     it again does only what is missing;
 10. no command of the CLI writes the installation but through a row, as far as the walk reads a
     command (`_reaches` says which shapes it reads and which it does not), and every
     installation row is the mapping of a command.
"""

from __future__ import annotations

import ast
import asyncio
import collections
import dataclasses
import functools
import importlib
import inspect
import json
import re
import typing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openfactory import actions
from openfactory.actions import catalog
from openfactory.identity import people
from openfactory.identity.local import (
    BOARD_PEOPLE_ENV,
    CLOSING_ENVS,
    PRODUCT_PEOPLE_ENV,
    SHARED_ENV,
)
from tests.test_a_person_is_invited_not_signed_up import (
    GOOD,
    invite_and_register,
    local,  # noqa: F401 — the fixture
)
from tests.the_tree_read_once import parsed

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PY = ROOT / "openfactory" / "actions" / "catalog.py"
SCHEDULE_PY = ROOT / "openfactory" / "runtime" / "temporal" / "schedule.py"
CONTRACT = ROOT / "docs" / "reference" / "the-front-end-api.md"

#: The rows that write the installation's registry and are NOT the administrator's, each with why.
#: Held EXACTLY by rule 1 — an entry that stopped writing fails too — so it cannot grow into a
#: list of permissions.
OPERATORS_LEVERS = {
    "enable": "one project's pickup, on or off: the operator's lever on the floor (ADR-0057's "
              "D3, proposed in #740, gives `enable` to `operator`), where the poller's pause is "
              "the deployment's",
}


# ── what writes the installation, read off the modules that do it ──────────────────────────────

def _writers(path: str, owner: str, through: str) -> frozenset[str]:
    """The methods of class `owner` in `path` that call `self.<through>` — its writers. Read from
    the source, so a writer added to the registry or the store is one rule 1 asks about."""
    tree = parsed(ROOT / path)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    return frozenset(
        fn.name for fn in cls.body if isinstance(fn, ast.FunctionDef) and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == through and getattr(n.func.value, "id", "") == "self"
            for n in ast.walk(fn)))


@functools.cache
def _poller_holds() -> frozenset[str]:
    """The schedule module's functions that pause or unpause a schedule."""
    tree = parsed(SCHEDULE_PY)
    return frozenset(
        fn.name for fn in tree.body if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef)
        and any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("pause", "unpause")
                for n in ast.walk(fn)))


#: `class whose instance is written through → (its module, what each of its writers calls on itself)`.
_WRITTEN_THROUGH = {"ProjectRegistry": ("openfactory/registry.py", "_save_raw"),
                    "PeopleStore": ("openfactory/identity/people.py", "_record")}

#: `class whose instance is written through → its writers`.
WRITERS = {cls: _writers(path, cls, through) for cls, (path, through) in _WRITTEN_THROUGH.items()}

#: The same classes by where they are defined, so an instance is known by its class.
_WRITER_HOMES = {(ROOT / path, cls): cls for cls, (path, _) in _WRITTEN_THROUGH.items()}

#: Builtin types whose methods a writer's name may share: `set.add`, `list.remove`.
_BUILTINS = (dict, list, set, frozenset, str, bytes, tuple)


@functools.cache
def _named_only_by_their_writer() -> dict[str, str]:
    """`writer → its class`, for the writers whose name no other function or method of the package
    defines and no builtin type has. Such a call writes the installation whatever it is called on
    (`local.people().invite(...)`, `self.registry.set_docs_repo(...)`), so the reading needs no idea
    of the receiver. The others are seen only on a value the reading knows is a registry or a
    store: on 2026-10-24 those were `add` (a set's, and six other modules'), `remove` (a list's and
    a set's, and `lifecycle/ports.py`'s), `set_enabled` (a route of the panel's) and `register` (a
    function inside the panel's app)."""
    defined = collections.Counter(
        n.name for path in sorted((ROOT / "openfactory").rglob("*.py"))
        for n in ast.walk(parsed(path)) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef))
    return {method: cls for cls, methods in WRITERS.items() for method in methods
            if defined[method] == 1 and not any(hasattr(t, method) for t in _BUILTINS)}


def _module_file(dotted: str) -> Path | None:
    """The file of a module of the package, or `None` for a name that is not one."""
    for candidate in (ROOT / (dotted.replace(".", "/") + ".py"),
                      ROOT / dotted.replace(".", "/") / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _from_the_package(node: ast.AST) -> dict[str, str]:
    """What `node` imports from the package: local name → dotted path, a module's (`from
    openfactory.product import before_code`, `import openfactory.product.onboard as onboard`,
    `import openfactory.product.onboard`, which binds `openfactory`) or a function's or a class's
    (`from openfactory.product.onboard import create_context_repository`). A relative import is
    not read: the package had none on 2026-10-24."""
    out: dict[str, str] = {}
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").startswith(
                "openfactory"):
            out.update({alias.asname or alias.name: f"{n.module}.{alias.name}" for alias in n.names})
        elif isinstance(n, ast.Import):
            out.update({alias.asname or "openfactory": alias.name if alias.asname else "openfactory"
                        for alias in n.names if alias.name.partition(".")[0] == "openfactory"})
    return out


class _Read(typing.NamedTuple):
    """A module of the package, as the walk reads it."""

    dotted: str                    # `openfactory.product.onboard`
    functions: dict[str, ast.AST]  # its functions by name, its classes' methods as `Class.method`
    classes: frozenset[str]
    values: frozenset[str]         # the other names it binds at the top: `CATALOG`, `app`
    imports: dict[str, str]        # what it imports from the package, anywhere in it


@functools.cache
def _module(path: Path) -> _Read:
    tree = parsed(path)
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    functions.update({f"{c.name}.{m.name}": m for c in classes for m in c.body
                      if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)})
    values = {t.id for n in tree.body if isinstance(n, ast.Assign | ast.AnnAssign)
              for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
              if isinstance(t, ast.Name)}
    dotted = ".".join(path.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
    return _Read(dotted, functions, frozenset(c.name for c in classes), frozenset(values),
                 _from_the_package(tree))


@functools.cache
def _target(dotted: str) -> tuple[str, Path, str] | None:
    """What a dotted name of the package is, as `(kind, its module's file, its name there)`: a
    `function` (a method as `Class.method`), a `class`, or another `value` the module binds at its
    top — read in the longest prefix that is a module, and through a name that module imports."""
    followed: set[str] = set()
    while dotted not in followed:
        followed.add(dotted)
        parts = dotted.split(".")
        cut = next((cut for cut in range(len(parts) - 1, 0, -1)
                    if _module_file(".".join(parts[:cut])) is not None), None)
        if cut is None:
            return None
        file = _module_file(".".join(parts[:cut]))
        mod, rest = _module(file), parts[cut:]
        key = ".".join(rest)
        if key in mod.functions:
            return "function", file, key
        if len(rest) == 1 and key in mod.classes:
            return "class", file, key
        if len(rest) == 1 and key in mod.values:
            return "value", file, key
        if rest[0] not in mod.imports:
            return None
        dotted = ".".join([mod.imports[rest[0]], *rest[1:]])
    return None


@dataclasses.dataclass(frozen=True)
class _Is:
    """What the reading knows a value is: an instance of the class `cls` of the module at `home`,
    and, for a row taken from the catalogue by its name, which row."""

    home: Path
    cls: str
    row: str | None = None


def _home(fn) -> tuple[Path, str]:
    """Where a function (or a class) of the package is read from: its module's file in this tree,
    and its name. By the module's name rather than the file the interpreter loaded, so an editable
    install of another checkout cannot send the walk to read a different tree."""
    return _module_file(fn.__module__), fn.__name__


#: A row of the catalogue: what `CATALOG[...]` holds. Its `.run`, called, is the row's runner.
_ROW = _Is(*_home(actions.ActionSpec))

#: Where the catalogue is held: the table, and the lazy view of it `openfactory.actions` exports.
THE_CATALOGUE = frozenset((_module_file(m.__name__), "CATALOG") for m in (catalog, actions))


class _Scope(typing.NamedTuple):
    """One function, as the walk reads it."""

    path: Path
    names: dict[str, str]  # what it and its module import from the package
    typed: dict[str, _Is]  # what its names are known to hold


_SCOPES: dict[tuple, _Scope] = {}
_RETURNS: dict[tuple[Path, str], _Is | None] = {}


def _static(fn: ast.AST) -> bool:
    return any(getattr(d, "id", "") == "staticmethod" for d in fn.decorator_list)


def _named(scope: _Scope, node: ast.AST) -> tuple[str, Path, str] | None:
    """What a name, or a chain of attributes off one, names in the package (`_target`)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id in scope.typed:
        return None
    head = scope.names.get(node.id) or f"{_module(scope.path).dotted}.{node.id}"
    return _target(".".join([head, *reversed(parts)]))


def _annotated(scope: _Scope, node: ast.AST | None) -> _Is | None:
    """The class of the package an annotation names: `ProjectRegistry`, `X | None`, `Optional[X]`,
    `"X"`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.BinOp):
        return _annotated(scope, node.left) or _annotated(scope, node.right)
    if isinstance(node, ast.Subscript) and "Optional" in (getattr(node.value, "id", ""),
                                                          getattr(node.value, "attr", "")):
        return _annotated(scope, node.slice)
    found = _named(scope, node) if node is not None else None
    return _Is(found[1], found[2]) if found and found[0] == "class" else None


def _is_the_catalogue(scope: _Scope, node: ast.AST) -> bool:
    found = _named(scope, node)
    return found is not None and found[0] == "value" and (found[1], found[2]) in THE_CATALOGUE


def _row(key: ast.AST | None) -> _Is:
    """A row taken from the catalogue: which one, when its name is written there."""
    named = isinstance(key, ast.Constant) and key.value in catalog.CATALOG
    return dataclasses.replace(_ROW, row=key.value) if named else _ROW


def _type(scope: _Scope, node: ast.AST) -> _Is | None:
    """What the expression `node` is known to hold, or `None`."""
    if isinstance(node, ast.Await):
        return _type(scope, node.value)
    if isinstance(node, ast.Name):
        return scope.typed.get(node.id)
    if isinstance(node, ast.BoolOp):  # `registry or ProjectRegistry()`, as `product/forget.py` has it
        return next((found for v in node.values if (found := _type(scope, v)) is not None), None)
    if isinstance(node, ast.IfExp):
        return _type(scope, node.body) or _type(scope, node.orelse)
    if isinstance(node, ast.Subscript):
        return _row(node.slice) if _is_the_catalogue(scope, node.value) else None
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get" and _is_the_catalogue(scope,
                                                                                     func.value):
        return _row(node.args[0] if node.args else None)
    if (named := _named(scope, func)) is not None and named[0] == "class":
        return _Is(named[1], named[2])
    if (callee := _callee(scope, func)) is not None:
        return _returns(callee[0], callee[1])
    # A BUILD THE IMPORTS DO NOT NAME, by its class's name, as the reading always read one
    said = getattr(func, "id", "") or getattr(func, "attr", "")
    return next((_Is(*home) for home, cls in _WRITER_HOMES.items() if cls == said), None)


def _returns(path: Path, key: str) -> _Is | None:
    """What a function of the package returns, when the reading knows: by its annotation, or by a
    `return` of a value it knows."""
    if (path, key) not in _RETURNS:
        _RETURNS[(path, key)] = None  # a cycle returns nothing known
        fn, scope = _module(path).functions[key], _scope(path, key)
        _RETURNS[(path, key)] = _annotated(scope, fn.returns) or next(
            (found for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None
             and (found := _type(scope, n.value)) is not None), None)
    return _RETURNS[(path, key)]


def _bound(node: ast.AST):
    """`(name, the expression it is bound to, whether to each item of it)` for what `node` binds."""
    if isinstance(node, ast.Assign):
        yield from ((t.id, node.value, False) for t in node.targets if isinstance(t, ast.Name))
    elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and isinstance(node.target, ast.Name) \
            and node.value is not None:
        yield node.target.id, node.value, False
    elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
        yield node.optional_vars.id, node.context_expr, False
    elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
        target = node.target
        if isinstance(target, ast.Tuple) and len(target.elts) == 2:
            target = target.elts[1]  # `for name, spec in CATALOG.items()`
        if isinstance(target, ast.Name):
            yield target.id, node.iter, True


def _scope(path: Path, key: str, given: frozenset = frozenset()) -> _Scope:
    """The function `key` of the module at `path`, with its parameters holding what `given` says
    its caller handed them."""
    if (path, key, given) not in _SCOPES:
        fn = _module(path).functions[key]
        scope = _SCOPES[(path, key, given)] = _Scope(
            path, {**_module(path).imports, **_from_the_package(fn)}, dict(given))
        params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        if "." in key and params and not _static(fn):
            scope.typed.setdefault(params[0].arg, _Is(path, key.partition(".")[0]))
        for p in params:
            if (found := _annotated(scope, p.annotation)) is not None:
                scope.typed.setdefault(p.arg, found)
        for _ in range(3):  # a name bound to a name bound to a build
            for n in ast.walk(fn):
                for name, value, each in _bound(n):
                    if each:  # an item of the catalogue's `values()` or `items()` is a row
                        held = (_ROW if isinstance(value, ast.Call)
                                and getattr(value.func, "attr", "") in ("values", "items")
                                and _is_the_catalogue(scope, value.func.value) else None)
                    else:
                        held = _type(scope, value)
                    if held is not None:
                        scope.typed.setdefault(name, held)
    return _SCOPES[(path, key, given)]


def _callee(scope: _Scope, node: ast.AST) -> tuple[Path, str, int] | None:
    """The function of the package `node` names, as `(its module's file, its key there, how many
    of its first parameters are not handed in a call's arguments)`: one of the module's own, one
    imported, a module's attribute, a method of a value the reading knows (`self` included) or of
    a class, or a class's `__init__` — `None` for anything else."""
    if isinstance(node, ast.Attribute) and (held := _type(scope, node.value)) is not None:
        key = f"{held.cls}.{node.attr}"
        fn = _module(held.home).functions.get(key)
        return (held.home, key, 0 if _static(fn) else 1) if fn is not None else None
    named = _named(scope, node)
    if named is None:
        return None
    kind, home, key = named
    if kind == "class":
        init = f"{key}.__init__"
        return (home, init, 1) if init in _module(home).functions else None
    if kind != "function":
        return None
    fn = _module(home).functions[key]
    classmethod_ = any(getattr(d, "id", "") == "classmethod" for d in fn.decorator_list)
    return home, key, 1 if classmethod_ else 0


def _handed(scope: _Scope, callee: tuple[Path, str, int], args, keywords) -> frozenset:
    """What a call hands `callee`'s parameters that the reading knows, by position or by name."""
    fn = _module(callee[0]).functions[callee[1]]
    params = [p.arg for p in (*fn.args.posonlyargs, *fn.args.args)][callee[2]:]
    given = {}
    for param, arg in zip(params, args, strict=False):  # a call may leave defaults out
        if isinstance(arg, ast.Starred):
            break
        if (held := _type(scope, arg)) is not None:
            given[param] = held
    for kw in keywords:
        if kw.arg and (held := _type(scope, kw.value)) is not None:
            given[kw.arg] = held
    return frozenset(given.items())


def _written(scope: _Scope, node: ast.AST) -> set[str]:
    """What the one node `node` writes of the installation, called or handed on."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") in _poller_holds():
        return {f"schedule.{node.func.id}"}
    if not isinstance(node, ast.Attribute):
        return set()
    if (cls := _named_only_by_their_writer().get(node.attr)) is not None:
        return {f"{cls}.{node.attr}"}
    held = _type(scope, node.value)
    cls = _WRITER_HOMES.get((held.home, held.cls)) if held is not None else None
    return {f"{cls}.{node.attr}"} if cls and node.attr in WRITERS[cls] else set()


def _entered(scope: _Scope, node: ast.AST) -> list[tuple[Path, str, frozenset]]:
    """The functions of the package the one node `node` enters, each with what its parameters are
    handed that the reading knows."""
    out = []
    if isinstance(node, ast.Name | ast.Attribute) and (callee := _callee(scope, node)):
        out.append((callee[0], callee[1], frozenset()))
    if not isinstance(node, ast.Call):
        return out
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "run" and (
            held := _type(scope, func.value)) is not None and dataclasses.replace(
            held, row=None) == _ROW:  # a row's runner, called without the door
        specs = [catalog.CATALOG[held.row]] if held.row else list(catalog.CATALOG.values())
        out += [(*_home(spec.run), frozenset()) for spec in specs]
    if (callee := _callee(scope, func)) is not None:
        out.append((callee[0], callee[1], _handed(scope, callee, node.args, node.keywords)))
    for i, arg in enumerate(node.args):  # a function handed on gets the arguments after it
        if (callee := _callee(scope, arg)) is not None:
            out.append((callee[0], callee[1], _handed(scope, callee, node.args[i + 1:], [])))
    return out


def _reaches(path: Path, name: str, *, door: tuple[Path, str] | None = None,
             seen: set[tuple[Path, str]] | None = None) -> dict[str, tuple[str, ...]]:
    """What the function `name` of the module at `path` writes of the installation, followed into
    the package: `writer → the functions it was reached through`, so a failure can say how. The
    walk does not enter `door`; `seen` is left holding every function it entered.

    WHAT IS READ AS A WRITE, called or handed on:
      - a writer of the registry or the people store on a value the reading knows is one: built
        there (`ProjectRegistry()`), a name bound to one (`registry = registry or
        ProjectRegistry()` included), what a function of the package returns when it returns one
        (by its annotation, or a `return` of one), a parameter annotated as one, or a parameter a
        caller handed one to, by position or by name, or as an argument after a function it hands
        on (`asyncio.to_thread(helper, registry)`);
      - a writer whose name nothing else defines (`_named_only_by_their_writer`), on anything;
      - the poller's hold called by its name, and any of the schedule's pausing functions entered.

    WHAT IS FOLLOWED: every function of the package a function names, called or handed on — its
    module's own, one imported by name, a module's attribute through any chain of modules
    (`from openfactory.x import y`, `import openfactory.x as y`, `import openfactory.x`), a class's
    `__init__` where the class is named, a method of a value the reading knows (`self` in a method
    included) or of the class itself — and a row's runner, where `.run(...)` is called on a row
    taken from the catalogue (`CATALOG[...]`, `CATALOG.get(...)`, a name bound to either, an item
    of `CATALOG.values()` or `.items()`, a value annotated `ActionSpec`): that row's runner when
    its name is written there, every row's when it is not.

    WHAT IS NOT: a name looked up by a string (`getattr`, `importlib`); a function the module
    holds in a table at its top (`HANDLERS[name]()`); a registry or a store the reading cannot
    type — held in a container or on another object's attribute, or handed back by a function
    from its own parameter — written by a name something else defines too (`add`, `remove`,
    `set_enabled`, `register`); a method a class inherits; a row's runner handed on uncalled; a
    relative import (the package had none on 2026-10-24); and what a module runs when it is
    imported. Six of those were put in a command of `cli.py` on 2026-10-24 and each passed rule
    10: `getattr(ProjectRegistry(), "set_enabled")`, a module-level table, an inherited method,
    `set_enabled` on another object's attribute, a registry handed back from a parameter, and a
    runner bound to a name before it was called. A function a call returns IS read: the function
    that returns it names it, and the walk enters what a function names.

    THE CATALOGUE'S EDGE WAS WHERE THIS READING STOPPED, and two rows wrote past it: main's
    `product_start` and `product_first_source` (#992) register a project and give it its code
    through `product/before_code.py`, and they read as rows that write nothing, so neither was
    declared the installation's and a board credential ran both (slice 3). AND A HOLD WAS SEEN ONLY
    BY ITS NAME: the schedule's pause, reached as the module's attribute, was a function that
    calls `.pause` on a handle and nothing else — so entering one is reaching it (slice 4). AND A
    WRITE WAS SEEN ONLY ON AN INSTANCE BUILT IN THE SAME FUNCTION: an independent review of slice
    4 put five commands in `cli.py` — a registry handed to a helper, one a helper returned, a
    class's method, `catalog.CATALOG["enable"].run(...)` and `import openfactory.product.onboard
    as pob` — and each passed this walk; each is a cut of plan 741d now."""
    return _walk(path, name, frozenset(), door, set() if seen is None else seen, set())


def _walk(path: Path, key: str, given: frozenset, door, seen: set,
          entered: set) -> dict[str, tuple[str, ...]]:
    if (path, key) == door or key not in _module(path).functions or (path, key, given) in entered:
        return {}
    entered.add((path, key, given))
    seen.add((path, key))
    scope, here = _scope(path, key, given), f"{path.relative_to(ROOT)}::{key}"
    out = {f"schedule.{key}": (here,)} if path == SCHEDULE_PY and key in _poller_holds() else {}
    for node in ast.walk(_module(path).functions[key]):
        for writer in _written(scope, node):
            out.setdefault(writer, (here,))
        for callee in _entered(scope, node):
            for writer, trail in _walk(*callee, door, seen, entered).items():
                out.setdefault(writer, (here, *trail))
    return out


@functools.cache
def _catalog_writes() -> dict[str, set[str]]:
    """`row → what it writes`, following what its runner names into the package (`_reaches`)."""
    return {name: set(_reaches(*_home(spec.run))) for name, spec in catalog.CATALOG.items()}


def test_what_writes_the_installation_is_read_off_the_modules_that_write_it():
    """The rule below is only as good as this reading, so it is checked to see something: the
    registry's adding and removing, a person's invitation and withdrawal, the poller's hold."""
    assert {"add", "remove", "set_docs_repo", "set_agent_name", "set_enabled"} <= \
        WRITERS["ProjectRegistry"], WRITERS["ProjectRegistry"]
    assert {"invite", "withdraw"} <= WRITERS["PeopleStore"], WRITERS["PeopleStore"]
    assert "hold_poller" in _poller_holds()
    assert {"get", "list"}.isdisjoint(WRITERS["ProjectRegistry"]), "a read counted as a write"
    # PAST THE CATALOGUE'S EDGE: a row whose write is a function of another module of the package
    # — handed to a thread as a module's attribute — is read as writing it
    assert "ProjectRegistry.add" in _catalog_writes()["product_start"], (
        "the reading stops at the catalogue's edge again")
    # A WRITER IS READ ON ANY RECEIVER ONLY BY A NAME NOTHING ELSE HAS: `add` is a set's too
    named = _named_only_by_their_writer()
    assert named.get("set_docs_repo") == "ProjectRegistry" and named.get("withdraw") == \
        "PeopleStore", named
    assert {"add", "remove"}.isdisjoint(named), named
    # THE CATALOGUE IS READ WHERE `perform` READS IT: each place it is held gives the table's rows
    held = [getattr(importlib.import_module(_module(path).dotted), name)
            for path, name in sorted(THE_CATALOGUE)]
    assert len(held) == 2 and all(h["enable"] is catalog.CATALOG["enable"] for h in held), held


# ── 1. a row that writes the installation says so, and only such a row ─────────────────────────

def test_a_row_that_writes_the_installation_is_declared_an_installation_row():
    writes = {name: what for name, what in _catalog_writes().items() if what}
    declared = {name for name, spec in catalog.CATALOG.items() if spec.installation}

    undeclared = {name: sorted(what) for name, what in writes.items()
                  if name not in declared and name not in OPERATORS_LEVERS}
    assert not undeclared, (
        f"these rows change the installation and are not `installation=True`, so a board or a "
        f"product credential reaches them: {undeclared}")
    idle = sorted(declared - set(writes))
    assert not idle, f"declared installation rows that write nothing of it: {idle}"
    assert set(OPERATORS_LEVERS) <= set(writes) - declared, (
        "OPERATORS_LEVERS names a row that no longer writes the installation, or is declared one")


# ── 2. the administrator's, by every door ──────────────────────────────────────────────────────

INSTALLATION = sorted(name for name, spec in catalog.CATALOG.items() if spec.installation)


def _params(spec) -> dict[str, object]:
    return {p: "acme" if p == "project" else "x" for p in spec.required}


@pytest.fixture
def reached(monkeypatch):
    """Every row's runner replaced by a recorder, through the table `perform` reads."""
    seen: list[str] = []

    def recorder(name: str):
        async def run(by=None, **_params):
            seen.append(name)
            return actions.done(f"recorded {name}")
        return run

    monkeypatch.setattr(catalog, "CATALOG", {
        name: dataclasses.replace(spec, run=recorder(name))
        for name, spec in catalog.CATALOG.items()})
    return seen


def test_there_are_installation_rows_to_hold_the_rule_over():
    assert {"people_invite", "people_revoke", "poller_pause", "poller_resume",
            "product_name", "product_declare"} <= set(INSTALLATION), INSTALLATION


@pytest.mark.parametrize("area", sorted(actions.SCOPES))
@pytest.mark.parametrize("name", INSTALLATION)
def test_a_scoped_credential_is_refused_every_installation_row(name, area, reached):
    """`admin=True` on purpose: a board or a product credential IS admin on its own surface, and
    what refuses it here is the installation, not the authority."""
    scoped = actions.Actor(id="leo", via="panel", admin=True, scopes=frozenset({area}))

    out = asyncio.run(actions.perform(name, by=scoped, **_params(catalog.CATALOG[name])))

    assert out.code == actions.DENIED and reached == [], (name, area, out)


@pytest.mark.parametrize("name", INSTALLATION)
def test_the_administrator_reaches_every_installation_row(name, reached):
    """The positive twin: a rule that refused everybody would pass the test above."""
    admin = actions.Actor(id="rob", via="panel", admin=True)

    out = asyncio.run(actions.perform(name, by=admin, **_params(catalog.CATALOG[name])))

    assert out.ok and reached == [name], (name, out)


@pytest.mark.parametrize("name", INSTALLATION)
def test_an_unscoped_caller_who_is_not_an_admin_is_refused_every_installation_row(name, reached):
    """The installation's rule is asked beside `needs_admin`, not instead of it: an unscoped
    caller who is nobody's admin — a chat user outside `project.admins` — is refused too."""
    nobody = actions.Actor(id="u1", via="slack", admin=False)

    out = asyncio.run(actions.perform(name, by=nobody, **_params(catalog.CATALOG[name])))

    assert out.code == actions.DENIED and reached == [], (name, out)


def test_the_doctor_answers_a_caller_who_is_not_an_admin(reached):
    """The doctor changes nothing, so it answers whoever may enter the floor — admin or not."""
    viewer = actions.Actor(id="u1", via="slack", admin=False)

    out = asyncio.run(actions.perform("doctor", by=viewer, project="acme"))

    assert out.ok and reached == ["doctor"], out


@pytest.fixture
def three_credentials(tmp_path, monkeypatch):
    """The panel's own token, a person's board token and a person's product token."""
    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(SHARED_ENV, "the-admin")
    monkeypatch.setenv(BOARD_PEOPLE_ENV, "the-board:leo:Leo")
    monkeypatch.setenv(PRODUCT_PEOPLE_ENV, "the-analyst:bia:Bia")
    from openfactory.api.app import app

    return TestClient(app)


@pytest.mark.parametrize("name", INSTALLATION)
def test_at_the_panels_door_only_the_administrators_credential_changes_the_installation(
        name, three_credentials, reached):
    """`POST /api/act/{name}` is how a front end of one's own reaches every row, so it is where
    the rule must hold for one: whichever area the path is read as, a scoped credential is
    refused and the row never runs."""
    body = {"params": _params(catalog.CATALOG[name])}
    for credential in ("the-board", "the-analyst"):
        refused = three_credentials.post(f"/api/act/{name}", json=body,
                                         headers={"Authorization": f"Bearer {credential}"})
        assert refused.status_code == 403, (name, credential, refused.text)
    assert reached == [], f"{name} ran for a scoped credential"

    admitted = three_credentials.post(f"/api/act/{name}", json=body,
                                      headers={"Authorization": "Bearer the-admin"})
    assert admitted.status_code == 200 and reached == [name], (name, admitted.text)


# ── 3. never proposed ───────────────────────────────────────────────────────────────────────────

def test_no_installation_row_is_something_the_tech_lead_may_propose():
    """`proposable` asks `perform`'s scope and admin checks and not the installation's, because
    no installation row is in the grammar a person types — held here, so the day one is, the
    third check is added there rather than a proposal to add a project reaching a chat."""
    from openfactory.actions.floor_intents import FLOOR_ROWS
    from openfactory.contracts.commands import ACTION_OF

    typeable = set(ACTION_OF.values()) | set(FLOOR_ROWS.values())
    assert typeable.isdisjoint(INSTALLATION), sorted(typeable & set(INSTALLATION))


# ── 4. the contract a front end is written against ─────────────────────────────────────────────

def _contract_rows() -> dict[str, str]:
    table = CONTRACT.read_text(encoding="utf-8").split("<!-- installation:start -->")[1]
    table = table.split("<!-- installation:end -->")[0]
    rows = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`") and cells[0] != "`name`":
            rows[cells[0].strip("`")] = cells[1]
    return rows


def test_the_front_end_contract_lists_exactly_the_installation_rows_and_what_they_take():
    rows = _contract_rows()

    assert set(rows) == set(INSTALLATION), (
        f"the contract lists {sorted(rows)}; the catalogue's installation rows are {INSTALLATION}")
    for name, takes in rows.items():
        spec = catalog.CATALOG[name]
        said = [p.strip(" `[]") for p in takes.split(",") if p.strip(" `[]-")]
        assert said == list(spec.parameters), (name, said, spec.parameters)


def test_the_catalogue_a_front_end_reads_marks_exactly_the_installation_rows():
    """`GET /api/v1/actions` says which rows are the installation's, so a screen of one's own that
    holds a scoped credential can leave them out rather than offer a button that answers 403."""
    from openfactory.api.app import app

    listed = TestClient(app).get("/api/v1/actions").json()

    assert sorted(row["name"] for row in listed if row["installation"]) == INSTALLATION, listed


# ── 5. one doctor, whichever door asked ─────────────────────────────────────────────────────────

def test_the_doctor_row_answers_the_document_the_command_prints(tmp_path, monkeypatch):
    """`doctor --json` is a public contract (#356). The row is what the command maps onto now, so
    a front end of one's own reads the very document a script reads — not a second rendering."""
    from openfactory import doctor, namespace
    from openfactory.cli import app
    from tests.pinned_probes import a_fully_pinned_probe_set

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(doctor, "probes_for", lambda _p: a_fully_pinned_probe_set(
        docker_running=lambda: (False, "the daemon did not answer")))
    monkeypatch.setattr(namespace, "build_stamp", lambda: ("abc123", "2026-10-05T10:00"))
    from openfactory.api.app import app as panel

    printed = CliRunner().invoke(app, ["doctor", "demo", "--json"])
    answered = TestClient(panel).post("/api/act/doctor", json={"params": {"project": "demo"}})

    assert answered.status_code == 200, answered.text
    assert answered.json()["data"] == json.loads(printed.stdout)
    assert answered.json()["ok"] is True, "the doctor ran — `ok` is about the platform"
    assert answered.json()["data"]["ok"] is False and "docker" in answered.json()["message"]


def test_the_doctor_and_a_declaration_probe_off_the_loop_the_panel_serves_from(tmp_path,
                                                                             monkeypatch):
    """The doctor's probes (`docker info`, the forge's API, the box gate) and a declaration's read
    (`git ls-remote` with each credential) block for seconds. Through the panel these rows run on
    the one loop that serves every other request, stream and approval: measured on 2026-10-19, a
    request sent 0.3 s into a 3 s probe waited 2.75 s behind the doctor and 3.95 s behind a
    declaration. So each runs on a thread of its own, and the loop keeps serving."""
    import threading

    from openfactory import doctor
    from openfactory.cli import app
    from openfactory.product import onboard
    from tests.pinned_probes import a_fully_pinned_probe_set

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0
    ran_on: dict[str, int] = {}

    def docker_running():
        ran_on["doctor"] = threading.get_ident()
        return True, ""

    def reachable(_project, _repo):
        ran_on["product_declare"] = threading.get_ident()
        return True, ""

    monkeypatch.setattr(doctor, "probes_for",
                        lambda _p: a_fully_pinned_probe_set(docker_running=docker_running))
    monkeypatch.setattr(onboard, "context_reachability", reachable)
    admin = actions.Actor(id="rob", via="panel", admin=True)

    async def on_the_loop() -> int:
        for name, params in (("doctor", {"project": "demo"}),
                             ("product_declare", {"project": "demo",
                                                  "docs_repo": "acme/demo-docs"})):
            out = await actions.perform(name, by=admin, **params)
            assert out.ok, (name, out)
        return threading.get_ident()

    loop = asyncio.run(on_the_loop())

    assert set(ran_on) == {"doctor", "product_declare"}, f"a probe was not reached: {ran_on}"
    assert loop not in ran_on.values(), f"a probe ran on the loop's own thread: {ran_on}"


def test_the_command_names_its_remedy_for_an_empty_repository(tmp_path, monkeypatch):
    """`perform` refuses `""` as a missing parameter before the row is reached, and that sentence
    names a parameter; the person typed a command, so the command says which one to type."""
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0

    out = CliRunner().invoke(app, ["product", "declare", "demo", ""])

    assert out.exit_code == 2, out.output
    assert "openfactory product declare <project> <owner/repo>" in out.output, out.output


#: A pause's `in_flight` is the RUNNING jobs the floor read, never the finished ones beside them,
#: because the row filters the list and a front end renders exactly what it is handed. Each case
#: carries a closed job the answer must drop, so `data.in_flight` can never list a finished job as
#: still running.
@pytest.mark.parametrize("jobs,flight,said", [
    ([{"project": "routing", "issue": "210", "status": "running"}, {"project": "routing", "issue": "209", "status": "closed"}], [{"project": "routing", "issue": "210", "status": "running"}], "wait for them"),
    (None, None, "do not roll the deployment"),
    ([{"project": "routing", "issue": "209", "status": "closed"}], [], "Nothing is in flight"),
], ids=["running", "unread", "drained"])
def test_a_pause_from_the_panel_says_what_is_still_running(monkeypatch, jobs, flight, said):
    """The sentence `poller pause` exists to print travels with the row, so a screen of one's own
    is told it too: a pause holds NEW pickups, and a pause that read as "drained" is how a job is
    interrupted by somebody who paused to protect it. An unread list is not a drained floor, and a
    FINISHED job beside a running one is not in flight."""
    from openfactory.api.app import app
    from tests.test_the_poller_has_a_lever import _engine, _Handle, _reading

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    _engine(_Handle(paused=False), monkeypatch)
    _reading(monkeypatch, on=False, jobs=jobs)
    if jobs is None:
        from openfactory.floor import reading as floor
        from openfactory.floor.ladder import FloorInputs

        async def unread(client=None, *, want=(), **_kw):
            return FloorInputs(jobs=None)

        monkeypatch.setattr(floor, "gather", unread)

    r = TestClient(app).post("/api/act/poller_pause", json={"params": {"note": "rolling"}})

    assert r.status_code == 200, r.text
    assert said in r.json()["message"], r.json()["message"]
    assert r.json()["data"]["in_flight"] == flight, "a finished job was counted as in flight"


# ── 6. a person revoked ─────────────────────────────────────────────────────────────────────────

def _revoke(person: str, *, by: str = "rob"):
    return asyncio.run(actions.perform("people_revoke", by=actions.Actor(id=by, via="panel",
                                                                         admin=True),
                                       person=person))


@pytest.fixture
def a_closed_door(monkeypatch):
    """A deployment whose environment closes the panel's door — so the last person may go."""
    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(SHARED_ENV, "the-admin")


def test_a_person_revoked_cannot_sign_in_and_their_sessions_end(local, a_closed_door):  # noqa: F811
    s, ana = invite_and_register(local)
    session = s.open_session(ana)

    out = _revoke("ana@acme.example")

    assert out.ok and out.data["registered"] is True and out.data["sessions"] == 1, out
    fresh = people.PeopleStore()
    assert fresh.login("ana@acme.example", GOOD) == ""
    assert fresh.session_of(session) is None
    assert fresh.people() == []
    assert local.rows[-1]["extra"]["by"] == "rob", "who revoked them is not recorded"


def test_invited_again_they_come_back_like_anybody_new_and_their_old_session_does_not(
        local, a_closed_door):  # noqa: F811
    """The store is append-only and folded in order: the withdrawal ends what came before it, and
    an invitation after it is a new person's. A session from before must stay dead — `session_of`
    would otherwise revive it the moment the same id registered again."""
    s, ana = invite_and_register(local)
    old = s.open_session(ana)
    assert _revoke("ana@acme.example").ok

    invite_and_register(local)

    back = people.PeopleStore()
    assert [p.id for p in back.people()] == ["ana@acme.example"]
    assert back.login("ana@acme.example", GOOD), "registered again, they sign in again"
    assert back.session_of(old) is None, "a session from before the revocation came back"


def test_an_open_invitation_revoked_no_longer_registers_anybody(local):  # noqa: F811
    token, _ = people.PeopleStore().invite("typo@acme.example", by="rob")

    out = _revoke("typo@acme.example")

    assert out.ok and out.data == {"person": "typo@acme.example", "registered": False,
                                   "invitations": 1, "sessions": 0, "by": "rob"}, out
    assert isinstance(people.PeopleStore().register(token=token, display="T", password=GOOD), str)


def test_nobody_by_that_name_is_not_found_and_nothing_is_written(local):  # noqa: F811
    invite_and_register(local)
    before = list(local.rows)

    out = _revoke("ghost@acme.example")

    assert out.code == actions.NOT_FOUND and local.rows == before, out


def test_the_last_person_is_not_revoked_while_nothing_else_closes_the_door(
        local, monkeypatch):  # noqa: F811
    """With nobody registered and no credential configured, the panel is open to whoever arrives —
    the new install's door, and the opposite of what revoking an account is for."""
    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    invite_and_register(local)
    before = list(local.rows)

    out = _revoke("ana@acme.example")

    assert out.code == actions.CONFLICT and local.rows == before, out
    from openfactory.identity.local import LocalIdentity

    assert not LocalIdentity().open_to_everyone(), "the door this refusal exists for opened"


@pytest.mark.parametrize("var", CLOSING_ENVS)
def test_any_credential_that_closes_the_door_lets_the_last_person_go(local, monkeypatch, var):  # noqa: F811,E501
    """Every variable that closes the door, read from the identity row itself: the refusal is about
    the door opening, so any one of them that keeps it shut is enough."""
    for other in CLOSING_ENVS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(var, "t:someone" if var.endswith("TOKENS") else "t")
    invite_and_register(local)

    assert _revoke("ana@acme.example").ok


def test_the_shell_revokes_through_the_row(local, a_closed_door):  # noqa: F811
    from openfactory.cli import app

    invite_and_register(local)

    gone = CliRunner().invoke(app, ["people", "revoke", "ana@acme.example"])
    again = CliRunner().invoke(app, ["people", "revoke", "ana@acme.example"])

    assert gone.exit_code == 0 and "ana@acme.example is revoked" in gone.output, gone.output
    assert again.exit_code == 1 and "nobody called" in again.output, again.output


def test_the_shared_panel_token_cannot_revoke_anybody(local, monkeypatch):  # noqa: F811
    """The voucher rule of #759, on the other end: the shared token is only CALLED "panel", so a
    revocation from it is signed by nobody, and it is refused before the store is read."""
    from openfactory.api.app import app

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(SHARED_ENV, "shared-secret")
    invite_and_register(local)
    before = list(local.rows)

    r = TestClient(app).post("/api/act/people_revoke",
                             headers={"authorization": "Bearer shared-secret"},
                             json={"params": {"person": "ana@acme.example"}})

    assert r.status_code == 400 and r.json()["message"] == people.UNSIGNED_WITHDRAWAL, r.text
    assert local.rows == before and [p.id for p in people.PeopleStore().people()] == [
        "ana@acme.example"]


def test_a_revocation_nobody_signed_is_refused_before_the_store_is_read(local):  # noqa: F811
    """The panel's gate reads the store to admit a caller; the row must not read it again for an
    act it will refuse whatever the store says."""
    invite_and_register(local)
    reads = local.reads

    out = asyncio.run(actions.perform("people_revoke", by=actions.Actor(id="", via="panel",
                                                                        admin=True),
                                      person="ana@acme.example"))

    assert out.code == actions.INVALID and out.message == people.UNSIGNED_WITHDRAWAL, out
    assert local.reads == reads, "the store was read for a revocation nobody signed"


# ── the review's minors (#741, hcristia's independent review) ───────────────────────────────────

@pytest.mark.parametrize("name", ["product_name", "product_declare"])
def test_a_scoped_credential_refused_a_product_row_is_sent_to_the_administrator(name):
    """`product_name` and `product_declare` are the installation's, named `product_` only because
    they configure the product role. A product credential is refused them by the area check — but
    every floor credential is refused them too, so "ask somebody whose credential covers the
    floor" would be the wrong remedy. The sentence names the administrator instead."""
    product = actions.Actor(id="bia", via="panel", admin=True, scopes=frozenset({actions.PRODUCT}))

    out = asyncio.run(actions.perform(name, by=product, **_params(catalog.CATALOG[name])))

    assert out.code == actions.DENIED, out
    assert "administers this deployment" in out.message, out.message
    assert "covers the floor" not in out.message, out.message


def test_a_revocation_is_refused_when_the_sink_keeps_nothing(monkeypatch):
    """`people_revoke` reads the people store, which lives in the metrics sink. A sink that keeps
    nothing cannot say who is registered, so the row refuses — UNAVAILABLE, naming the sink —
    rather than answer "nobody called X" about a store it could not read."""
    from openfactory.identity import people

    monkeypatch.setattr(people, "sink_is_durable",
                        lambda: "the metrics sink is `null`, which keeps nothing")

    out = asyncio.run(actions.perform("people_revoke", by=actions.Actor(id="rob", via="panel",
                                                                        admin=True),
                                      person="ana@acme.example"))

    assert out.code == actions.UNAVAILABLE and "keeps nothing" in out.message, out
# ── 7. a project's own settings (slice 2) ───────────────────────────────────────────────────────

#: Something plausible for each parameter a project row requires besides the project itself.
_PLAUSIBLE = {"model": "a-model", "language": "en", "docs_repo": "acme/docs", "person": "x"}

#: The rows that register a project, read off what they write.
REGISTERS = sorted(name for name, what in _catalog_writes().items()
                   if "ProjectRegistry.add" in what)

#: Of those, the ones that need more than its name — where the new project lives. They take a
#: project that is NOT registered yet, so the rule below is not theirs; theirs is that what is
#: registered already is never written over (slice 3, below).
REGISTERS_A_NEW_ONE = sorted(name for name in REGISTERS
                             if set(catalog.CATALOG[name].required) - {"project"})

TAKES_A_PROJECT = sorted(name for name in INSTALLATION
                         if "project" in catalog.CATALOG[name].required
                         and name not in REGISTERS_A_NEW_ONE)


@pytest.fixture
def one_project(tmp_path, monkeypatch):
    """A registry holding `acme`, and nothing else."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(path))
    ProjectRegistry().add(Project(name="acme", repo_path=str(tmp_path / "acme"),
                                  tracker=ProviderRef(kind="local", repo="acme", options={}),
                                  forge=ProviderRef(kind="local", repo="acme", options={})))
    return path


@pytest.mark.parametrize("name", TAKES_A_PROJECT)
def test_every_installation_row_that_takes_a_project_refuses_one_nobody_registered(
        name, one_project):
    """By name, with the roster — the commonest cause is a typo, and the right name is on it —
    and with the registry exactly as it was: a write to a ghost is how a project that does not
    exist comes to have settings."""
    before = one_project.read_bytes()
    params = {p: _PLAUSIBLE.get(p, "x") for p in catalog.CATALOG[name].required}
    params["project"] = "acmee"

    out = asyncio.run(actions.perform(name, by=actions.Actor(id="rob", via="cli", admin=True),
                                      **params))

    assert out.code == actions.NOT_FOUND, (name, out)
    assert re.search(r"knows: acme\.", out.message, re.IGNORECASE), (
        f"{name} refused the ghost without the roster the right name is on: {out.message}")
    assert one_project.read_bytes() == before, f"{name} wrote the registry for a ghost"


def test_the_shell_and_a_front_end_set_the_same_preview_policy(one_project, tmp_path,
                                                               monkeypatch):
    """The flags a terminal gives and the words a JSON body carries are one request: a front end
    of one's own writes `"true"`, `"6"` and `"web=DB_URL"` where the shell passes booleans, an
    int and a list, and the policy saved must be the same."""
    from openfactory.api.app import app as panel
    from openfactory.cli import app
    from openfactory.registry import ProjectRegistry

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    shell = CliRunner().invoke(app, ["project", "set-preview", "acme", "--required", "--hours",
                                     "6", "--env", "web=DB_URL", "--env",
                                     "api=OPENFACTORY_BOT_TOKEN", "--no-auto-start"])
    assert shell.exit_code == 0, shell.output
    by_the_shell = ProjectRegistry().get("acme").preview.model_dump()

    ProjectRegistry().set_preview("acme", {})
    answered = TestClient(panel).post("/api/act/project_set_preview", json={"params": {
        "project": "acme", "required": "true", "hours": "6",
        "env": "web=DB_URL,api=OPENFACTORY_BOT_TOKEN", "auto_start": "false"}})

    assert answered.status_code == 200, answered.text
    assert ProjectRegistry().get("acme").preview.model_dump() == by_the_shell
    assert answered.json()["data"]["preview"]["required"] is True
    # AND WHAT WAS REFUSED IS SAID to the screen too: the factory's own credential is never
    # written, and a front end that shows only the sentence must not read that as accepted
    assert answered.json()["data"]["dropped"] == ["api=OPENFACTORY_BOT_TOKEN"]
    assert "OPENFACTORY_BOT_TOKEN" in answered.json()["message"], answered.json()["message"]


@pytest.mark.parametrize("field", ["required", "auto_start", "clear_env"])
def test_a_yes_or_no_that_is_neither_is_refused_and_nothing_is_written(field, one_project):
    """`"maybe"` is not a no: read as one, a form field carrying anything but yes would lift a
    look a person must take before a merge."""
    before = one_project.read_bytes()

    out = asyncio.run(actions.perform("project_set_preview",
                                      by=actions.Actor(id="rob", via="cli", admin=True),
                                      project="acme", **{field: "maybe"}))

    assert out.code == actions.INVALID and "maybe" in out.message, out
    assert one_project.read_bytes() == before


ADMIN = actions.Actor(id="rob", via="panel", admin=True)


@pytest.mark.parametrize("argv,row", [
    (["project", "set-model", "acme", "m"], "project_set_model"),
    (["project", "set-language", "acme", "en"], "project_set_language"),
    (["project", "set-preview", "acme", "--hours", "3"], "project_set_preview"),
    (["project", "remove", "acme"], "project_remove"),
])
def test_each_project_verb_runs_its_row_and_writes_nothing_itself(argv, row, one_project,
                                                                  monkeypatch):
    """The command is a mapping: with the row's own code replaced by a recorder, the verb still
    answers, the recorder ran once, and the registry is byte for byte as it was. A verb that wrote
    the registry itself beside its row would pass every test that reads the registry back."""
    from openfactory import cli

    before, seen = one_project.read_bytes(), []

    async def recorder(by=None, **params):
        seen.append(params)
        return actions.done("recorded", preview={"required": False, "auto_start": True,
                                                 "hours": 3, "network": "", "env": {},
                                                 "build_args": {}}, dropped=[])

    monkeypatch.setattr(catalog, "CATALOG", {**catalog.CATALOG, row: dataclasses.replace(
        catalog.CATALOG[row], run=recorder)})
    monkeypatch.setattr(cli, "_model_recognition_note", lambda p, m: "")

    out = CliRunner().invoke(cli.app, argv)

    assert out.exit_code == 0, out.output
    assert len(seen) == 1, f"{argv} did not run {row}"
    assert one_project.read_bytes() == before, f"{argv} wrote the registry itself"


@pytest.mark.parametrize("model", [
    "arn:aws:bedrock:us-east-1:123:inference-profile/ACM.Fictitious.Model-" + "X" * 80,
    " padded ", "a-model-with-dashes-inside"])
def test_the_model_is_saved_verbatim(model, one_project):
    """The harness names its models its own way, so the row passes the string on as it came: no
    case folded, nothing stripped, nothing cut. The one shape refused is a leading '-' (below)."""
    from openfactory.registry import ProjectRegistry

    out = asyncio.run(actions.perform("project_set_model", by=ADMIN, project="acme", model=model))

    assert out.ok and ProjectRegistry().get("acme").model == model, out


@pytest.mark.parametrize("model", ["--looks-like-a-flag", "  -x"])
def test_a_model_that_begins_like_a_flag_is_refused_and_nothing_is_written(model, one_project):
    """A model value is handed to the harness as one `--model=<value>` token; a value that begins
    with '-' is refused, with a sentence, and the registry is byte for byte as it was."""
    from openfactory.registry import ProjectRegistry

    before = one_project.read_bytes()
    out = asyncio.run(actions.perform("project_set_model", by=ADMIN, project="acme", model=model))

    assert out.code == actions.INVALID and "begin with '-'" in out.message, out
    assert one_project.read_bytes() == before
    assert ProjectRegistry().get("acme").model is None, "a refused model was written"


def test_the_refusal_holds_the_per_role_shape_and_the_add_door(one_project):
    """Every writer passes through the one check (`model_refused`): the per-role form of
    `set_model`, and `project add`'s own model."""
    import pytest as _pytest

    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    with _pytest.raises(ValueError, match="begin with '-'"):
        ProjectRegistry().set_model("acme", "--flag", role="executor")
    with _pytest.raises(ValueError, match="begin with '-'"):
        ProjectRegistry().add(Project(name="beta", repo_path=str(one_project.parent / "beta"),
                                      tracker=ProviderRef(kind="local", repo="beta", options={}),
                                      model="--flag"))


def test_a_model_set_through_a_front_end_says_it_was_not_checked(one_project):
    """Only the shell asks the harness whether it runs the name, on the machine that will run it.
    A front end is told the row did not, so silence never reads as a confirmation."""
    out = asyncio.run(actions.perform("project_set_model", by=ADMIN, project="acme",
                                      model="gtp-5-typo"))

    assert out.ok and "not checked" in out.message.lower() and out.data.get("checked") is False, out


def test_clear_env_drops_what_was_held(one_project):
    from openfactory.registry import ProjectRegistry

    asyncio.run(actions.perform("project_set_preview", by=ADMIN, project="acme", env="web=A"))
    asyncio.run(actions.perform("project_set_preview", by=ADMIN, project="acme",
                                clear_env="true", env="api=B"))

    assert ProjectRegistry().get("acme").preview.env == {"api": {"B": "B"}}


@pytest.mark.parametrize("hours", ["6h", "abc"])
def test_hours_that_are_not_a_number_are_refused(hours, one_project):
    """The shell types `--hours` as a number; a front end's body may carry anything, and the
    policy reads what is not a number as its default — saved and reported as a success."""
    before = one_project.read_bytes()

    out = asyncio.run(actions.perform("project_set_preview", by=ADMIN, project="acme",
                                      hours=hours))

    assert out.code == actions.INVALID and hours in out.message, out
    assert one_project.read_bytes() == before


def test_a_network_a_preview_may_not_join_is_said_and_not_saved(one_project):
    from openfactory.registry import ProjectRegistry

    out = asyncio.run(actions.perform("project_set_preview", by=ADMIN, project="acme",
                                      network="host"))

    assert out.ok and "network 'host' refused" in out.message, out
    assert ProjectRegistry().get("acme").preview.network == ""


# ── 8. registering a project (slice 3) ──────────────────────────────────────────────────────────

def _kinds_the_axes_branch_on() -> set[str]:
    """The kinds `doors.axes_for` writes differently, read off its comparisons — so a kind it
    learns to write is a kind the cases below must carry an address for."""
    fn = next(n for n in parsed(ROOT / "openfactory" / "doors.py").body
              if isinstance(n, ast.FunctionDef) and n.name == "axes_for")
    return {c.value for n in ast.walk(fn) if isinstance(n, ast.Compare)
            for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)}


#: One address for each kind `doors.axes_for` writes differently: a path on this machine (every axis
#: local), a clone URL whose kind writes the tracker, and one whose kind writes two axes from the
#: coordinates the URL carries. The panel's door wrote the tracker alone for both URLs.
ADDRESSES = ("{tmp}/acme", "https://github.com/acme-corp/acme.git",
             "https://dev.azure.com/acme-org/Payments/_git/acme")


def test_the_addresses_cover_every_kind_the_row_writes_differently(tmp_path):
    from openfactory import doors

    covered = {doors.kind_for(a.format(tmp=tmp_path)) for a in ADDRESSES}

    assert covered == _kinds_the_axes_branch_on(), (covered, _kinds_the_axes_branch_on())


@pytest.mark.parametrize("address", ADDRESSES)
def test_the_command_and_the_panels_door_register_one_row(address, tmp_path, monkeypatch):
    """`project add` and `POST /api/projects` are mappings onto one row, so the same address
    registers the same project through either — every axis, not the tracker alone."""
    from openfactory.api.app import app as panel
    from openfactory.cli import app
    from openfactory.registry import ProjectRegistry

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    where = address.format(tmp=tmp_path)
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "by-the-shell.yaml"))
    shell = CliRunner().invoke(app, ["project", "add", "acme", where])
    assert shell.exit_code == 0, shell.output
    by_the_shell = ProjectRegistry().get("acme").model_dump(mode="json")

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "by-the-panel.yaml"))
    answered = TestClient(panel).post("/api/projects", json={"name": "acme", "repo_path": where})

    assert answered.status_code == 200, answered.text
    assert ProjectRegistry().get("acme").model_dump(mode="json") == by_the_shell


@pytest.mark.parametrize("argv,body", [
    (["project", "add", "acme", "/srv/acme"], None),
    (None, {"name": "acme", "repo_path": "/srv/acme"}),
], ids=["project add", "POST /api/projects"])
def test_each_registering_door_runs_the_row_and_writes_nothing_itself(argv, body, tmp_path,
                                                                      monkeypatch):
    """With the row's own code replaced by a recorder, the door still answers, the recorder ran
    once, and no registry was written: a door that also wrote the project itself would pass every
    test that reads the registry back."""
    from openfactory.api.app import app as panel
    from openfactory.cli import app

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    registry = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))
    seen = []

    async def recorder(by=None, **params):
        seen.append(params)
        return actions.done("recorded", project="acme", changed=True, registered={})

    monkeypatch.setattr(catalog, "CATALOG", {**catalog.CATALOG, "project_add": dataclasses.replace(
        catalog.CATALOG["project_add"], run=recorder)})

    if argv:
        out = CliRunner().invoke(app, argv)
        assert out.exit_code == 0, out.output
    else:
        answered = TestClient(panel).post("/api/projects", json=body)
        assert answered.status_code == 200, answered.text

    assert [p["project"] for p in seen] == ["acme"], "the door did not run project_add"
    assert not registry.exists(), "the door wrote the registry itself"


def test_registering_through_the_panels_door_is_the_administrators(three_credentials, tmp_path,
                                                                   monkeypatch):
    """`POST /api/projects` is held to the row's scoping: a board credential passes the floor's
    door and is refused by the row, a product credential is refused at the door, and nothing is
    written for either."""
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    body = {"name": "acme", "repo_path": str(tmp_path / "acme")}
    for credential in ("the-board", "the-analyst"):
        refused = three_credentials.post("/api/projects", json=body,
                                         headers={"Authorization": f"Bearer {credential}"})
        assert refused.status_code == 403, (credential, refused.text)
    assert ProjectRegistry().list() == [], "a scoped credential registered a project"

    admitted = three_credentials.post("/api/projects", json=body,
                                      headers={"Authorization": "Bearer the-admin"})

    assert admitted.status_code == 200, admitted.text
    assert [p.name for p in ProjectRegistry().list()] == ["acme"]


#: Requests no door may register as written, each with the data a door renders its refusal from.
#: Each is refused before the registry is read for writing, so the file is never touched.
UNREGISTRABLE = {
    "a host nobody here implements": ({"repo_path": "https://gitlab.com/o/acme.git"}, "foreign"),
    "an address missing the coordinates its kind needs": (
        {"repo_path": "https://dev.azure.com/acme-org/Payments"}, "missing"),
    "a model that begins like a flag": ({"repo_path": "/srv/acme", "model": "--flag"}, None),
}


@pytest.mark.parametrize("case", sorted(UNREGISTRABLE))
def test_an_address_that_cannot_be_registered_as_written_is_refused_and_nothing_is_written(
        case, tmp_path, monkeypatch):
    from openfactory.api.app import app as panel

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    registry = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))
    params, rendered_from = UNREGISTRABLE[case]

    out = asyncio.run(actions.perform("project_add", by=ADMIN, project="acme", **params))

    assert out.code == actions.INVALID, out
    if rendered_from:
        assert out.data.get(rendered_from), f"the refusal carries no {rendered_from!r}: {out.data}"
    assert not registry.exists(), f"{case} wrote the registry"
    if "model" not in params:
        # THE PANEL'S DOOR ANSWERS AS IT ALWAYS DID, 422 and the row's sentence
        answered = TestClient(panel).post("/api/projects", json={"name": "acme", **params})
        assert answered.status_code == 422 and answered.json()["detail"] == out.message, (
            answered.text)
        assert not registry.exists()


def test_adding_what_is_registered_changes_nothing_and_adding_it_differently_is_refused(
        tmp_path, monkeypatch):
    """Safe to run again, and never over what is there: the same request is an answer, even after
    a board was attached and a model set since — those are not what was asked — and a request
    for a different address is refused, naming what differs, with the registry byte for byte as
    it was."""
    from openfactory.registry import ProjectRegistry

    registry = tmp_path / "registry.yaml"
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry))
    asked = {"project": "acme", "repo_path": "https://github.com/acme-corp/acme.git",
             "language": "pt-BR"}
    assert asyncio.run(actions.perform("project_add", by=ADMIN, **asked)).data["changed"] is True
    ProjectRegistry().attach_board("acme", board_owner="acme-corp", board_number="7")
    ProjectRegistry().set_model("acme", "a-model")
    before = registry.read_bytes()

    again = asyncio.run(actions.perform("project_add", by=ADMIN, **asked))
    elsewhere = asyncio.run(actions.perform("project_add", by=ADMIN,
                                            **{**asked, "repo_path": str(tmp_path / "acme")}))

    assert again.ok and again.data["changed"] is False, again
    assert elsewhere.code == actions.CONFLICT and "repo_path" in elsewhere.data["differs"], (
        elsewhere)
    assert registry.read_bytes() == before, "registering again wrote over what was registered"


# ── 9. a row of several steps says what each came to, and is safe to run again (slice 3) ──────

def _rows_reaching(helper: str) -> set[str]:
    """The rows whose runner reaches `helper` in the catalogue, by a call or by handing a function
    on — the same walk as rule 1's."""
    tree = parsed(CATALOG_PY)
    functions = {n.name: n for n in tree.body
                 if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}

    def reaches(name: str, seen: set[str]) -> bool:
        if name in seen or name not in functions:
            return False
        seen.add(name)
        return name == helper or any(isinstance(n, ast.Name) and reaches(n.id, seen)
                                     for n in ast.walk(functions[name]))

    return {name for name, spec in catalog.CATALOG.items() if reaches(spec.run.__name__, set())}


#: The rows of several steps: those that answer through `_the_steps_came_to`.
STEPPED = sorted(_rows_reaching("_the_steps_came_to"))


def _a_fresh_machine(root: Path, monkeypatch) -> Path:
    """A one-machine deployment at `root` with a repository of the person's own — nothing of this
    machine reached, nothing remote."""
    from tests.one_machine import a_deployment, a_repository

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(root))
    a_deployment(root, monkeypatch=monkeypatch)
    return a_repository(root)


@pytest.fixture
def a_machine(tmp_path, monkeypatch):
    return _a_fresh_machine(tmp_path, monkeypatch)


def _a_push_that_fails_once(monkeypatch) -> None:
    """The first `git push` of the run fails, as a full disk or a dropped connection makes it."""
    import subprocess

    real, state = subprocess.run, {"failed": False}

    def once(args, *a, **kw):
        if isinstance(args, list) and "push" in args and not state["failed"]:
            state["failed"] = True
            raise subprocess.CalledProcessError(1, args, stderr="no room on the disk")
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", once)


def _init_a_path(repo, monkeypatch):
    """`project_init` on a path, with the context repository's push failing the first time."""
    _a_push_that_fails_once(monkeypatch)
    return {"project": "myapp", "repo_path": str(repo)}, "context"


class _ContextForge:
    """A forge that creates the context repository by naming one that exists, clones it from a
    bare repository on this machine, and remembers the review it opened — so a second run can be
    told one is open."""

    def __init__(self, bare: str):
        self.bare, self.opened = bare, []

    def create_repository(self, *, name, private=True, description=""):
        return f"acme-corp/{name}", True

    def clone_url(self, repo, *, token=None):
        return self.bare

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append(head)
        return "https://forge.invalid/acme-corp/acme-context/pull/1"

    def pr_for_head(self, branch, *, repo=""):
        return "https://forge.invalid/acme-corp/acme-context/pull/1" if branch in self.opened else ""

    def pr_status(self, *, pr, repo=""):
        return "open"


def _a_product(repo, monkeypatch):
    """`product_init` creating a hosted project's context repository and proposing its
    declaration — `(params, forge)`. The forge is a double over a bare repository on this
    machine; the registry and everything between them is real."""
    import subprocess

    from openfactory.adapters.forge import registry as forges
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.product import onboard
    from openfactory.registry import ProjectRegistry

    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    bare, seed = repo.parent / "acme-context.git", repo.parent / "acme-context-seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("the client's context repository\n", encoding="utf-8")
    for args in (["add", "README.md"], ["commit", "-q", "-m", "seed"],
                 ["push", "-q", str(bare), "main"]):
        subprocess.run(["git", *ident, "-C", str(seed), *args], check=True)
    forge = _ContextForge(str(bare))
    monkeypatch.setattr(forges, "build_forge", lambda *a, **kw: forge)
    monkeypatch.setattr(onboard, "_context_token", lambda p: None)
    ProjectRegistry().add(Project(name="acme", repo_path=str(repo),
                                  tracker=ProviderRef(kind="github", repo="acme-corp/acme"),
                                  forge=ProviderRef(kind="github", repo="acme-corp/acme")))
    return {"project": "acme", "create_context": "true", "write": "true"}, forge


def _init_a_product(repo, monkeypatch):
    """`_a_product`, with the declaration's push failing the first time."""
    params, _ = _a_product(repo, monkeypatch)
    _a_push_that_fails_once(monkeypatch)
    return params, "declaration"


#: How each row of several steps is driven to fail halfway: `(params, the step that fails)`, the
#: cause failing once and then passing.
HALFWAY = {"project_init": _init_a_path, "product_init": _init_a_product}


def test_every_row_of_several_steps_is_driven_halfway():
    assert STEPPED, "no row answers through `_the_steps_came_to` — the reading sees nothing"
    assert sorted(HALFWAY) == STEPPED, (
        f"rows of several steps {STEPPED}, driven halfway {sorted(HALFWAY)}: a row that takes "
        f"several steps must show what it says when one fails, and that running it again finishes")


@pytest.mark.parametrize("name", STEPPED)
def test_a_row_of_several_steps_says_what_was_done_when_a_step_fails_and_finishes_when_run_again(
        name, a_machine, monkeypatch):
    """A failure halfway is a list of what is done and what is not, not one sentence about the last
    thing that broke; running the row again does what is missing and nothing twice; and a third
    run finds everything there."""
    from openfactory.registry import ProjectRegistry

    params, failing = HALFWAY[name](a_machine, monkeypatch)

    first = asyncio.run(actions.perform(name, by=ADMIN, **params))
    states = {s["step"]: s["state"] for s in first.data["steps"]}
    assert first.code == actions.FAILED and states[failing] == actions.STEP_FAILED, first
    before_it = [s["step"] for s in first.data["steps"]][:list(states).index(failing)]
    assert before_it and all(states[s] == actions.STEP_DONE for s in before_it), (
        f"the steps before {failing!r} are not said to be done: {first.data['steps']}")
    for s in first.data["steps"]:
        assert s["said"] in first.message, f"{s['step']} is not said in the sentence: {first}"

    second = asyncio.run(actions.perform(name, by=ADMIN, **params))
    again = {s["step"]: s["state"] for s in second.data["steps"]}
    assert second.ok and again[failing] == actions.STEP_DONE, second
    assert all(again[s] in (actions.STEP_ALREADY, actions.STEP_SKIPPED) for s in before_it), (
        f"running it again did again what was done: {second.data['steps']}")
    registered = Path(ProjectRegistry().path).read_bytes()

    third = asyncio.run(actions.perform(name, by=ADMIN, **params))
    assert third.ok and all(s["state"] in (actions.STEP_ALREADY, actions.STEP_SKIPPED)
                            for s in third.data["steps"]), third
    assert Path(ProjectRegistry().path).read_bytes() == registered


def test_a_front_end_is_told_which_steps_were_done_when_a_later_one_failed(a_machine,
                                                                          monkeypatch):
    """Through `POST /api/act/{name}` a failed step is the outcome's code, and the steps ride with
    it — so a screen of one's own can show that the project is registered and its board made,
    and offer the same button again."""
    from openfactory.api.app import app as panel

    _a_push_that_fails_once(monkeypatch)

    r = TestClient(panel).post("/api/act/project_init", json={"params": {
        "project": "myapp", "repo_path": str(a_machine)}})

    assert r.status_code == 500, r.text
    said = {s["step"]: s["state"] for s in r.json()["data"]["steps"]}
    assert said["register"] == "done" and said["context"] == "failed", said
    assert "running it again does only what is missing" in r.json()["message"]


@pytest.mark.parametrize("argv,row", [
    (["project", "init", "acme"], "project_init"),
    (["product", "init", "acme", "--write"], "product_init"),
])
def test_each_verb_of_several_steps_runs_its_row_and_writes_nothing_itself(argv, row, one_project,
                                                                          monkeypatch):
    """The command is a mapping: with the row's own code replaced by a recorder, the verb answers,
    the recorder ran once, and the registry is byte for byte as it was."""
    from openfactory import cli

    before, seen = one_project.read_bytes(), []

    async def recorder(by=None, **params):
        seen.append(params)
        return actions.done("recorded", steps=[{"step": "declaration", "state": "already",
                                                 "said": "already declared"}],
                            local=True, base_branch="main", already_correct=True)

    monkeypatch.setattr(catalog, "CATALOG", {**catalog.CATALOG, row: dataclasses.replace(
        catalog.CATALOG[row], run=recorder)})

    out = CliRunner().invoke(cli.app, argv)

    assert out.exit_code == 0, out.output
    assert len(seen) == 1, f"{argv} did not run {row}"
    assert one_project.read_bytes() == before, f"{argv} wrote the registry itself"


def test_onboard_creates_a_context_repository_through_its_row_and_writes_nothing_itself(
        one_project, monkeypatch):
    """`onboard` on a project with no context repository asks `product_init` to create one, once,
    and records nothing itself: with the row's own code replaced by a recorder, the verb answers
    and the registry is byte for byte as it was (slice 4). Before, the onboarding module created
    the repository and wrote it into the registry from the command line's own code."""
    from types import SimpleNamespace

    from openfactory import cli
    from openfactory.onboarding import onboard

    before, seen = one_project.read_bytes(), []

    async def recorder(by=None, **params):
        seen.append(params)
        return actions.done("recorded", steps=[{"step": "context", "state": "done",
                                                 "said": "created acme-corp/acme-context"}])

    monkeypatch.setattr(catalog, "CATALOG", {**catalog.CATALOG, "product_init": dataclasses.replace(
        catalog.CATALOG["product_init"], run=recorder)})
    proven = SimpleNamespace(ok=True, detail="nothing to propose", pr="", proof="proven",
                             questions=[], manifest_already_there=True, repo="acme")
    monkeypatch.setattr(onboard, "onboard_source_repo", lambda *a, **kw: proven)
    monkeypatch.setattr(onboard, "onboard_product_context", lambda project, **kw: (
        onboard.ContextOutcome(ok=True, docs_repo="acme-corp/acme-context", detail="proposed")))

    out = CliRunner().invoke(cli.app, ["onboard", "acme", "--yes"])

    assert out.exit_code == 0, out.output
    assert [p.get("create_context") for p in seen] == [True], (
        f"onboard did not ask product_init to create the context repository: {seen}")
    assert one_project.read_bytes() == before, "onboard wrote the registry itself"
    assert "(created)" in out.output, out.output


# ── 8, again: what is registered is never written over (slice 3) ────────────────────────────

def _add_elsewhere(repo):
    return {"project": "myapp", "repo_path": str(repo.parent / "elsewhere")}


def _init_elsewhere(repo):
    return {"project": "myapp", "repo_path": str(repo.parent / "elsewhere"), "language": "pt-BR"}


def _start_before_its_code(repo):
    return {"project": "myapp", "docs_repo": "myapp-context"}


#: For each row that registers: a request naming a project already registered, differently.
OVER_IT = {"project_add": _add_elsewhere, "project_init": _init_elsewhere,
           "product_start": _start_before_its_code}


def test_every_row_that_registers_is_asked_to_write_over_a_project():
    assert sorted(OVER_IT) == REGISTERS, (REGISTERS, sorted(OVER_IT))


@pytest.mark.parametrize("name", REGISTERS)
def test_a_row_that_registers_never_writes_over_what_is_registered(name, a_machine):
    """Whatever the request says, a project that is registered keeps its address, its axes and its
    language: `project_add` refuses and names what differs, `project_init` initialises the project
    as it is registered, and `product_start` will not start one that already has its code."""
    from openfactory.registry import ProjectRegistry

    assert asyncio.run(actions.perform("project_add", by=ADMIN, project="myapp",
                                       repo_path=str(a_machine))).ok
    before = Path(ProjectRegistry().path).read_bytes()

    out = asyncio.run(actions.perform(name, by=ADMIN, **OVER_IT[name](a_machine)))

    assert out.ok or out.code == actions.CONFLICT, out
    assert Path(ProjectRegistry().path).read_bytes() == before, f"{name} wrote over myapp"


# ── 9, before the code: a product's declaration names no source it cannot vouch for (slice 3) ──

#: The two shapes a product before its code is registered in (`before_code.context_axes`): on a
#: hosted forge its axes name no repository, and on this machine they carry the project's own
#: name — which is no repository yet, and must not be listed as one.
BEFORE_ITS_CODE = {"hosted": ("github", None), "this machine": ("local", "acme")}


@pytest.fixture(params=sorted(BEFORE_ITS_CODE))
def a_product_before_its_code(request, a_machine, monkeypatch):
    """`acme`, registered with its context repository and no code repository (#992), its context
    doubled over a bare repository that does not declare the product yet."""
    import subprocess

    from openfactory.adapters.forge import registry as forges
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef, before_its_code
    from openfactory.product import onboard
    from openfactory.registry import ProjectRegistry

    ident = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    bare, seed = a_machine.parent / "acme-context.git", a_machine.parent / "acme-context-seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("the client's context repository\n", encoding="utf-8")
    for args in (["add", "README.md"], ["commit", "-q", "-m", "seed"],
                 ["push", "-q", str(bare), "main"]):
        subprocess.run(["git", *ident, "-C", str(seed), *args], check=True)
    forge = _ContextForge(str(bare))
    monkeypatch.setattr(forges, "build_forge", lambda *a, **kw: forge)
    monkeypatch.setattr(onboard, "_context_token", lambda p: None)
    kind, own = BEFORE_ITS_CODE[request.param]
    axes = {"tracker": ProviderRef(kind=kind, repo=own)}
    if kind == "local":
        axes |= {"forge": ProviderRef(kind=kind, repo=own),
                 "ci": ProviderRef(kind="none", repo=own)}
    ProjectRegistry().add(Project(name="acme", repo_path="", **axes,
                                  product=ProductConfig(docs_repo="acme-corp/acme-context")))
    assert before_its_code(ProjectRegistry().get("acme"))
    return bare, forge


def _declared_on(bare: Path, tmp: Path):
    """What the proposal branch of the context declares, read back with the loader's own reader."""
    import subprocess

    from openfactory.product.loader import _read_docs_manifest
    from openfactory.product.onboard import proposal_branch

    branch = proposal_branch("acme")
    if subprocess.run(["git", "-C", str(bare), "rev-parse", "--verify", "-q",
                       f"refs/heads/{branch}"], capture_output=True).returncode != 0:
        return None
    checkout = tmp / "read-back"
    subprocess.run(["git", "clone", "-q", "-b", branch, str(bare), str(checkout)], check=True,
                   capture_output=True)
    docs, error = _read_docs_manifest(checkout)
    assert docs is not None, error
    return docs


def test_a_product_before_its_code_is_declared_with_no_source_and_its_link_admits_it(
        a_product_before_its_code, tmp_path):
    """`product start` sends a product whose context does not declare it here, so the row runs
    before the code (`needs_code=False`) — and writes `sources: []`, the one list a project with
    no code may be declared with: the axes of a product before its code name no repository of
    its own to list."""
    from openfactory.product.config import resolve_product_link
    from openfactory.registry import ProjectRegistry

    bare, forge = a_product_before_its_code

    out = asyncio.run(actions.perform("product_init", by=ADMIN, project="acme", write="true"))

    assert out.ok, out
    docs = _declared_on(bare, tmp_path)
    assert docs is not None and docs.product == "acme" and list(docs.sources) == [], docs
    link = resolve_product_link(project=ProjectRegistry().get("acme"), manifest_docs_repo="",
                                docs=docs)
    assert link.active, f"the declaration the row proposed is refused by the link: {link}"


def test_a_source_for_a_product_before_its_code_is_refused_and_nothing_is_pushed(
        a_product_before_its_code, tmp_path):
    """Listing a repository is the first source's act, which records it too: here it would make a
    member of a product that can vouch for nobody (#992's one declaration per act)."""
    bare, forge = a_product_before_its_code

    out = asyncio.run(actions.perform("product_init", by=ADMIN, project="acme",
                                      source="acme-corp/acme", write="true"))

    assert out.code == actions.INVALID and "product_first_source" in out.message, out
    assert _declared_on(bare, tmp_path) is None and forge.opened == [], "something was proposed"


# ── 9, again: a step that raises is a failed step, whichever step it is (review of #1085) ──────

def _steps_of(row: str) -> list[str]:
    """The steps `row` can say: the first argument of every `actions.base.step(...)` call its
    runner reaches in the catalogue, by a call or by handing a function on — `_rows_reaching`'s
    walk. Read off the code, so a step added to a row is a case below."""
    from openfactory.actions import base

    tree = parsed(CATALOG_PY)
    functions = {n.name: n for n in tree.body
                 if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    # THE NAME THE CATALOGUE CALLS IT BY, read off the module rather than spelled here
    called = {name for name, value in vars(catalog).items() if value is base.step}
    seen, said, todo = set(), set(), [catalog.CATALOG[row].run.__name__]
    while todo:
        name = todo.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Name):
                todo.append(node.id)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in called and node.args
                  and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                said.add(node.args[0].value)
    return sorted(said)


#: Every step of every row of several steps: `(row, step)`.
RAISABLE = [(row, step) for row in STEPPED for step in _steps_of(row)]


def _a_path(repo, monkeypatch):
    """`project_init` on a path of the person's own — `(params, None)`: no forge to double."""
    return {"project": "myapp", "repo_path": str(repo)}, None


#: Each row of several steps on a fresh machine, where every one of its steps has something to do:
#: `(params, the forge's double or None)`.
FRESH = {"project_init": _a_path, "product_init": _a_product}


def _the_registry_cannot_be_written(repo, monkeypatch, forge):
    """The registry's directory is a file, so its lock cannot be taken — what a read-only
    directory does, for whoever runs the suite."""
    (repo.parent / "not-a-directory").write_text("", encoding="utf-8")
    monkeypatch.setenv("OPENFACTORY_REGISTRY",
                       str(repo.parent / "not-a-directory" / "registry.yaml"))


def _the_tracker_raises(repo, monkeypatch, forge):
    """The board's creation raises something nobody expected."""
    from openfactory.adapters.board_setup import registry as setups

    class _Raises:
        def attached(self, project):
            return ""

        def create(self, **_kw):
            raise RuntimeError("the tracker answered 502")

    monkeypatch.setattr(setups, "board_creator", lambda kind: _Raises())


def _the_installations_directory_cannot_be_written(repo, monkeypatch, forge):
    """Where this installation keeps its context repositories is a file, so none is made there."""
    from openfactory import namespace

    where = namespace.operator_path("context")
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text("", encoding="utf-8")


def _the_checkout_cannot_be_written(repo, monkeypatch, forge):
    """The manifest's directory is a file in the checkout — the review's read-only checkout, for
    whoever runs the suite."""
    from openfactory import namespace

    (repo / namespace.DIR).write_text("", encoding="utf-8")


def _the_forge_drops_the_connection(repo, monkeypatch, forge):
    """The forge drops the connection that creates the context repository."""
    def drops(**_kw):
        raise ConnectionResetError("[Errno 54] Connection reset by peer")

    monkeypatch.setattr(forge, "create_repository", drops)


def _the_credential_cannot_be_resolved(repo, monkeypatch, forge):
    """The clone's address, which carries the context repository's credential, cannot be made."""
    def unresolved(repo, *, token=None):
        raise LookupError("no credential for acme-corp/acme-context")

    monkeypatch.setattr(forge, "clone_url", unresolved)


#: How each step of each row is made to raise, from inside the step: `(repo, monkeypatch, forge)`.
RAISING = {
    ("project_init", "register"): _the_registry_cannot_be_written,
    ("project_init", "board"): _the_tracker_raises,
    ("project_init", "context"): _the_installations_directory_cannot_be_written,
    ("project_init", "manifest"): _the_checkout_cannot_be_written,
    ("product_init", "context"): _the_forge_drops_the_connection,
    ("product_init", "declaration"): _the_credential_cannot_be_resolved,
}


def test_every_step_of_every_row_of_several_steps_is_made_to_raise():
    assert RAISABLE, "no step is read off the rows of several steps — the reading sees nothing"
    assert sorted(RAISING) == sorted(RAISABLE), (
        f"steps {sorted(RAISABLE)}, made to raise {sorted(RAISING)}: every step a row can say "
        f"must be shown failing when it raises")
    assert sorted(FRESH) == STEPPED, (STEPPED, sorted(FRESH))


@pytest.mark.parametrize("row,step", RAISABLE)
def test_a_step_that_raises_is_a_failed_step_and_the_steps_around_it_stand(row, step, tmp_path,
                                                                           monkeypatch, caplog):
    """Whichever step raises, and whatever it raises, it is a failed step: the row answers
    `failed`, with every step it took in `data.steps` and in its sentence. The steps before it
    stand as a run where nothing raised says them, and the steps after it still run — except
    after the first, which the others are done on (the project registered, the context
    repository there), where nothing is tried. Before, only the board step said so: any other
    raised out of the row, and the registration and the board were said nowhere (review of
    #1085). And nothing is logged that a terminal prints as a traceback — a failure speaks by
    name."""
    import logging

    params, _ = FRESH[row](_a_fresh_machine(tmp_path / "clean", monkeypatch), monkeypatch)
    clean = asyncio.run(actions.perform(row, by=ADMIN, **params))
    took = [(s["step"], s["state"]) for s in clean.data.get("steps", [])]
    assert clean.ok and sorted(name for name, _ in took) == _steps_of(row), (
        f"a run of {row} where nothing raises did not take every step it can say: {clean}")
    at = [name for name, _ in took].index(step)

    repo = _a_fresh_machine(tmp_path / "raising", monkeypatch)
    params, forge = FRESH[row](repo, monkeypatch)
    RAISING[row, step](repo, monkeypatch, forge)
    with caplog.at_level(logging.WARNING):
        out = asyncio.run(actions.perform(row, by=ADMIN, **params))

    said = [(s["step"], s["state"]) for s in out.data.get("steps", [])]
    assert out.code == actions.FAILED and said, f"the {step} step raised out of {row}: {out}"
    assert said[:at] == took[:at], f"the steps before {step} do not stand: {said}"
    assert said[at] == (step, actions.STEP_FAILED), said
    assert said[at + 1:] == ([] if at == 0 else took[at + 1:]), (
        f"the steps after {step} did not run as they would have: {said}")
    for s in out.data["steps"]:
        assert s["said"] in out.message, f"{s['step']} is not said in the sentence: {out}"
    traced = [r.getMessage() for r in caplog.records if r.exc_info]
    assert not traced, f"a traceback reaches the terminal: {traced}"


# ── and at the terminal, on a read-only directory, as the review drove it ─────────────────────

def _git_init(where: Path) -> Path:
    import subprocess

    where.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(where)], check=True)
    return where


def _a_read_only_checkout(root, monkeypatch):
    """`project init` on a `git init`'d directory made read-only — the review's reproduction."""
    checkout = _git_init(root / "ro")
    return ["project", "init", "roapp", str(checkout)], checkout


def _a_read_only_registry(root, monkeypatch):
    """`project init` with the registry's directory read-only."""
    registry = root / "registry-ro"
    registry.mkdir()
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(registry / "registry.yaml"))
    return ["project", "init", "rwapp", str(_git_init(root / "rw"))], registry


def _a_read_only_installation(root, monkeypatch):
    """`product init --create-context` for a project on this machine, with the directory this
    installation keeps its context repositories under read-only."""
    from openfactory import namespace

    added = asyncio.run(actions.perform("project_add", by=ADMIN, project="rwapp",
                                        repo_path=str(_git_init(root / "rw"))))
    assert added.ok, added
    installation = namespace.operator_path("context").parent
    installation.mkdir(parents=True, exist_ok=True)
    return ["product", "init", "rwapp", "--create-context", "--write"], installation


#: Each row's command, run where a directory one of its steps writes is read-only:
#: `(argv, the directory)`.
READ_ONLY = {
    ("project_init", "register"): _a_read_only_registry,
    ("project_init", "manifest"): _a_read_only_checkout,
    ("product_init", "context"): _a_read_only_installation,
}


def test_every_row_of_several_steps_is_run_at_the_terminal_on_a_read_only_directory():
    assert sorted({row for row, _ in READ_ONLY}) == STEPPED, (STEPPED, sorted(READ_ONLY))
    assert set(READ_ONLY) <= set(RAISABLE), sorted(set(READ_ONLY) - set(RAISABLE))


@pytest.mark.parametrize("row,step", sorted(READ_ONLY))
def test_a_step_a_read_only_directory_stops_is_said_at_the_terminal_never_a_traceback(
        row, step, tmp_path, monkeypatch):
    """The command a person types, in a process of its own, on a directory it cannot write: the
    step that could not write is a line naming the directory, the command exits 1, and nothing
    is printed as a traceback. `project init` on a read-only checkout printed one, and no line
    for the registration and the board it had done (review of #1085)."""
    import os
    import subprocess
    import sys

    from tests.one_machine import a_deployment

    for var in CLOSING_ENVS:
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    a_deployment(tmp_path, monkeypatch=monkeypatch)
    argv, locked = READ_ONLY[row, step](tmp_path, monkeypatch)
    locked.chmod(0o555)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip(f"a read-only directory does not stop this user ({os.geteuid()=})")
        # THIS TREE'S CODE, whichever install the interpreter has: the working directory holds
        # no package, so the import comes from PYTHONPATH.
        ran = subprocess.run([sys.executable, "-m", "openfactory.cli", *argv], cwd=tmp_path,
                             env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True,
                             text=True, timeout=180)
    finally:
        locked.chmod(0o755)

    shown = ran.stdout + ran.stderr
    assert "Traceback" not in shown, shown
    failed = [line for line in ran.stdout.splitlines() if line.startswith("✗")]
    assert ran.returncode == 1 and failed and str(locked) in failed[0], shown


# ── 9, and what a step says carries no credential (review of #1085) ───────────────────────────

#: A forge credential, spelled as a GitHub App installation token is.
CREDENTIAL = "ghs_" + "Q7xR2mK9pL4vN8wT3yH6jB1cF5dZ0sAeUuIo"


def _times_out(args, address, timeout):
    import subprocess

    raise subprocess.TimeoutExpired(args, timeout)


def _exits_naming_its_remote(args, address, timeout):
    """As git says an address it could not reach: the address as it was given, credential and
    all."""
    import subprocess

    return subprocess.CompletedProcess(args, 128, "", f"fatal: unable to access '{address}/': "
                                                      f"Could not resolve host: github.com\n")


def _raises_with_its_command(args, address, timeout):
    """What any of them raises once it is run with `check=True`: its argv, in the exception."""
    import subprocess

    raise subprocess.CalledProcessError(128, args)


#: The ways a git call of a row can fail: `(argv, the address, its timeout) -> what run answers`.
FAILURES = {"times out": _times_out, "exits naming its remote": _exits_naming_its_remote,
            "raises with its command": _raises_with_its_command}


def _a_product_whose_remote_carries_a_credential(root: Path, monkeypatch, *,
                                                 failing: int | None = None, how: str = ""):
    """`_a_product` on a fresh machine at `root`, its context repository's address carrying
    `CREDENTIAL` as the GitHub adapter's does, and every git call recorded: `(params, the calls,
    the address)`. The `failing`-th call fails `how`; every other runs, with the bare repository
    in the address's place — so everything before the failure really happens."""
    import subprocess

    params, forge = _a_product(_a_fresh_machine(root, monkeypatch), monkeypatch)
    address = f"https://x-access-token:{CREDENTIAL}@github.com/acme-corp/acme-context.git"
    monkeypatch.setattr(forge, "clone_url", lambda repo, *, token=None: address)
    real, calls = getattr(subprocess.run, "real", subprocess.run), []

    def run(args, *a, **kw):
        if not (isinstance(args, list) and args[:1] == ["git"]):
            return real(args, *a, **kw)
        calls.append(list(args))
        if len(calls) - 1 == failing:
            return FAILURES[how](args, address, kw.get("timeout"))
        return real([forge.bare if part == address else part for part in args], *a, **kw)

    run.real = real
    monkeypatch.setattr(subprocess, "run", run)
    return params, calls, address


def _the_git_calls_of_a_clean_run(root: Path, monkeypatch) -> list[list[str]]:
    """Every git call `product_init` makes when none fails — read off a run, so a call added to
    the row is a case."""
    params, calls, address = _a_product_whose_remote_carries_a_credential(root, monkeypatch)
    clean = asyncio.run(actions.perform("product_init", by=ADMIN, **params))
    assert clean.ok, clean
    assert any(address in call for call in calls), (
        f"no git call was handed the address that carries the credential: {calls}")
    return list(calls)


@pytest.mark.parametrize("how", sorted(FAILURES))
def test_whichever_git_call_fails_and_however_the_answer_carries_no_credential(how, tmp_path,
                                                                                monkeypatch):
    """The context repository's address carries the forge's credential (`https://x-access-token:
    <token>@…`), and git says it: a call that runs out of time raises with its argv, one that
    cannot reach the address names it, and one run to check raises with its argv. A clone that
    ran out of time put the token into `message` and `data.steps` — what the panel shows, the
    API answers and the terminal prints (review of #1085, 2026-10-24). So every git call of a
    clean run is made to fail each way, and the whole answer is read."""
    calls = _the_git_calls_of_a_clean_run(tmp_path / "clean", monkeypatch)

    for at, call in enumerate(calls):
        params, _, _ = _a_product_whose_remote_carries_a_credential(
            tmp_path / f"failing-{at}", monkeypatch, failing=at, how=how)
        out = asyncio.run(actions.perform("product_init", by=ADMIN, **params))

        answer = json.dumps({"message": out.message, "data": dict(out.data)}, default=str)
        assert CREDENTIAL not in answer, (
            f"`{' '.join(call[:3])} …` that {how} put the credential into the answer: {answer}")


def test_a_git_call_that_carries_the_credential_and_runs_out_of_time_is_said_as_one(tmp_path,
                                                                                    monkeypatch):
    """Said in a sentence naming the repository and the time it was given — `could not clone
    acme-corp/acme-context: timed out after 180 s` — never as the command `subprocess` puts in
    the exception (`Command '[…]' timed out after 180 seconds`): the command is the address, and
    a sentence is what a person can act on."""
    calls = _the_git_calls_of_a_clean_run(tmp_path / "clean", monkeypatch)
    carrying = [at for at, call in enumerate(calls)
                if any(CREDENTIAL in part for part in call)]
    assert carrying, calls

    for at in carrying:
        params, _, _ = _a_product_whose_remote_carries_a_credential(
            tmp_path / f"failing-{at}", monkeypatch, failing=at, how="times out")
        out = asyncio.run(actions.perform("product_init", by=ADMIN, **params))

        said = {s["step"]: s for s in out.data.get("steps", [])}
        declaration = said.get("declaration") or {}
        assert out.code == actions.FAILED and declaration.get("state") == actions.STEP_FAILED, out
        assert ("acme-corp/acme-context" in declaration["said"]
                and f"timed out after {catalog._A_CONTEXT_GIT_S} s" in declaration["said"]
                and "Command '" not in declaration["said"]), declaration


# ── 10. the command line changes the installation through its rows, and only so (slice 4) ──────
#
# THE GUARD #741 ASKED FOR, AND THE DIRECTION NOTHING CHECKED. `test_the_action_layer.py` proves
# every row is reached from the shell (`openfactory act`); nothing proved that a verb which changes
# the installation goes through a row. Three slices moved the verbs one by one, and the last one
# still writing past them, `onboard`'s context repository, was found by this walk, not by a list.

def _the_door() -> tuple[Path, str]:
    """`perform`: where every front end hands a row its parameters. The walk does not enter it —
    what a row writes is the row's, held to the row's declaration by rule 1 — and nothing else is
    a door."""
    return _home(actions.perform)


@functools.cache
def _commands() -> dict[str, object]:
    """Every command a person can type, read off the Typer app itself: the tree click builds from
    it, which is what runs, as `words → the function that runs`."""
    import typer.main

    from openfactory.cli import app

    def walk(command, words: tuple[str, ...]):
        subs = getattr(command, "commands", None)
        if subs:
            for name, sub in sorted(subs.items()):
                yield from walk(sub, (*words, name))
        else:
            yield " ".join(words), inspect.unwrap(command.callback)

    return dict(walk(typer.main.get_command(app), ()))


def _registered() -> dict[str, object]:
    """The same commands, read off what the app registered: the second reading the walk is held
    to, so a walk that loses a group is seen."""
    from openfactory.cli import app

    def names(typer_app, words: tuple[str, ...]):
        for c in typer_app.registered_commands:
            said = c.name or c.callback.__name__.lower().replace("_", "-")
            yield " ".join((*words, said)), inspect.unwrap(c.callback)
        for group in typer_app.registered_groups:
            yield from names(group.typer_instance, (*words, group.name))

    return dict(names(app, ()))


def _read_as_written(fn) -> bool:
    """Whether the walk reads `fn`'s own body: a module-level function of the package, the one of
    its name that starts on the line the interpreter says it does."""
    path, name = _home(fn)
    node = _module(path).functions.get(name) if path is not None else None
    if node is None:
        return False
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return first == fn.__code__.co_firstlineno


_HANDS_ON: dict[tuple[Path, str], bool] = {}


def _hands_on(home: tuple[Path, str]) -> bool:
    """Whether calling this function hands a row's name to the door: it is `perform`, or it passes
    its own first parameter on to a function that does — the shell's `_perform`."""
    if home == _the_door():
        return True
    if home not in _HANDS_ON:
        _HANDS_ON[home] = False  # a cycle hands nothing on
        path, name = home
        fn = _module(path).functions.get(name)
        first = fn.args.args[0].arg if fn is not None and fn.args.args else None
        scope = _scope(path, name) if first else None
        _HANDS_ON[home] = bool(first) and any(
            isinstance(c, ast.Call) and c.args and isinstance(c.args[0], ast.Name)
            and c.args[0].id == first and (callee := _callee(scope, c.func)) is not None
            and _hands_on(callee[:2]) for c in ast.walk(fn))
    return _HANDS_ON[home]


@functools.cache
def _walked(words: str) -> tuple[dict[str, tuple[str, ...]], frozenset[str]]:
    """What the command `words` writes of the installation without going through the door, and
    the rows it hands to the door by name — the first argument of a call, in a function the walk
    entered, to a function that hands it on."""
    seen: set[tuple[Path, str]] = set()
    writes = _reaches(*_home(_commands()[words]), door=_the_door(), seen=seen)
    rows = set()
    for path, name in seen:
        scope = _scope(path, name)
        rows |= {c.args[0].value for c in ast.walk(_module(path).functions[name])
                 if isinstance(c, ast.Call) and c.args and isinstance(c.args[0], ast.Constant)
                 and c.args[0].value in catalog.CATALOG
                 and (callee := _callee(scope, c.func)) is not None and _hands_on(callee[:2])}
    return writes, frozenset(rows)


def test_the_walk_reaches_every_command_the_app_registers_and_reads_each_body():
    """The guard below is only as good as its list of commands, so the list is read twice off the
    app — the tree that runs and what was registered — and the two must be the same commands
    running the same functions; and the walk must read each one's own body."""
    walked, registered = _commands(), _registered()

    assert walked == registered, (
        f"the walk and the app's registrations disagree: "
        f"{sorted(set(walked) ^ set(registered)) or 'the same words run different functions'}")
    assert any(" " in words for words in walked), "the walk never left the root"
    unread = sorted(words for words, fn in walked.items() if not _read_as_written(fn))
    assert not unread, f"commands whose body the walk cannot read: {unread}"


def test_no_command_writes_the_installation_but_through_a_row():
    """A command that changes the installation is a mapping onto a row: what it writes, it writes
    through `perform`, which asks who is acting and logs it. Every command is walked into the
    package as rule 1 walks a row, and none may reach a writer of the registry, the people store
    or the poller's schedule on its own — directly, through a helper or a class's method, or by
    calling a row's runner without the door. Each failure names the command, the writer and the
    rows that write it.

    WHAT THE WALK DOES NOT READ is written on `_reaches`: a name looked up by a string, a function
    held in a module's table, a registry it cannot type written by a name something else defines
    too, an inherited method, a runner handed on uncalled, a relative import, and import-time
    code. A command that writes through one of those passes this test."""
    said = []
    for words in sorted(_commands()):
        for writer, trail in sorted(_walked(words)[0].items()):
            rows = sorted(r for r, what in _catalog_writes().items() if writer in what)
            onto = (f"map it onto {' or '.join(rows)} through `perform`" if rows else
                    "no row writes it yet: add one, declared `installation=True`, and map the "
                    "command onto it")
            said.append(f"`openfactory {words}` writes {writer} outside a row "
                        f"({' → '.join(trail)}) — {onto}")

    assert not said, "\n".join(said)


def test_every_installation_row_is_the_mapping_of_a_command():
    """THE POSITIVE TWIN, and #741's other half: the shell's verbs are mappings over the
    installation's rows. Each installation row is handed to `perform`, by name, from a command the
    walk reaches — so the walk reads the commands down to the door, and a walk that lost a group,
    or a door the shell's verbs stopped going through, loses the rows they map.

    A NEW INSTALLATION ROW COMES WITH ITS VERB, in the same pull request: #741 asks that the shell
    can do what a front end can, and #1041, the next rows for the registry, asks for a typed verb
    for each option. So the failure says what to add rather than naming an exemption: there is
    none, and a row that should have no verb of its own is a decision for the review that adds
    it."""
    mapped = {row for words in _commands() for row in _walked(words)[1]}

    missing = sorted(set(INSTALLATION) - mapped)
    assert not missing, (
        f"installation rows no command maps onto: {missing} — add the verb that changes this part "
        f"of the installation, calling the row through `perform` as the other verbs do, in the "
        f"pull request that adds the row. `openfactory act` reaches every row, but it is not "
        f"that verb")

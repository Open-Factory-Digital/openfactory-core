"""A name bound to a MODULE can never be called (pilot, 2026-08-16).

`actions/catalog.py` imports `from openfactory import namespace` at module scope — the paths
module. Inside `_waiting_on_a_human` it then wrote:

    await tv.list_jobs(client, namespace())

meaning the *Temporal* namespace, which is a different `namespace` living in
`runtime/temporal/connection.py`. The line reads correctly, `_diagnose` twenty lines up runs the
identical expression and works — because that one carries a local `from …connection import
namespace` that re-binds the name inside the function — and this one raised `TypeError: 'module'
object is not callable` on every single call.

WHAT IT COST is why this file exists rather than a one-line fix. The function's own `except
Exception` turned the `TypeError` into `[]`, `[]` meant "no job is waiting on a human", and the
chat therefore handed the operator's *"pode fazer o merge"* to the tech-lead, which answered — with
complete accuracy, for the floor it was shown — that it had nothing to merge. The pull request was
open, at the gate, with a Merge button beside the chat. Twenty-seven tests covered the feature and
passed; every one of them monkeypatched the function that contained the defect.

THE RULE IS ABSOLUTE, which is what makes it worth a guard: a module object has no `__call__`, so
a call of one is not a style question or a probable mistake — it is a `TypeError` that has not
happened yet. Nothing in ruff or the type checker looks for it, and the failure is invisible in any
code path that catches broadly.

Shadowing is respected: a function that imports its own `namespace` is calling that one.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PKG = pathlib.Path(__file__).resolve().parents[1] / "openfactory"


def _is_module(dotted: str) -> bool:
    """Does `openfactory.x.y` name a MODULE or package on disk?

    CASE-EXACT, LISTED RATHER THAN STAT-ED. `Path.is_file()` answers on the filesystem's terms, and
    this repository is developed on a case-insensitive one — so `openfactory/contracts/Ticket.py`
    "exists" because `ticket.py` does, and the first run of this guard accused three re-exported
    CLASSES (`Ticket`, `Manifest`) of being modules. The mistake matters beyond the false alarm: a
    guard whose failures are noise is a guard somebody deletes."""
    if not dotted.startswith("openfactory"):
        return False  # third-party: we cannot see its shape from here, and we did not write it
    parts = dotted.split(".")[1:]
    if not parts:
        return False
    parent = PKG.joinpath(*parts[:-1])
    if not parent.is_dir():
        return False
    here = {p.name for p in parent.iterdir()}
    return f"{parts[-1]}.py" in here or (parts[-1] in here and (parent / parts[-1]).is_dir()
                                         and "__init__.py" in {
                                             p.name for p in (parent / parts[-1]).iterdir()})


def _module_names_bound(node: ast.AST, *, package: str) -> set[str]:
    """Names this node's own import statements bind to a MODULE object.

    Both spellings that produce one: `import a.b as c` binds `c`, and `from pkg import mod` binds
    `mod` whenever `pkg.mod` is itself a module — the shape that caused this. `from pkg import
    thing` where `thing` is a function or a class binds no module and is ignored."""
    bound: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Import):
            for alias in n.names:
                # `import a.b` binds `a`; `import a.b as c` binds `c`.
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:  # relative: resolve against the file's own package
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - n.level + 1] + ([base] if base else []))
            for alias in n.names:
                if alias.name != "*" and _is_module(f"{base}.{alias.name}"):
                    bound.add(alias.asname or alias.name)
    return bound


#: Nodes that open a scope of their own. A binding inside one of these does NOT shadow the name
#: for its siblings, and a call inside one is judged against its own chain of enclosing scopes.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
           ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _within_scope(node: ast.AST):
    """Every node belonging to THIS scope, stopping at nested ones."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            continue
        yield child
        yield from _within_scope(child)


def _nested_scopes(node: ast.AST):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            yield child
        else:
            yield from _nested_scopes(child)


def _bindings(scope: ast.AST) -> set[str]:
    """Names bound in this scope ITSELF — an import, an assignment, a parameter, a `with … as`,
    an `except … as`, the name of a function or class defined here.

    SCOPE-EXACT, and the first version was not. It used `ast.walk`, which descends into nested
    functions — so an import inside a closure was credited to the enclosing function, and a
    mutation that moved the shadowing import one level in went undetected. A guard that is blind
    in the direction of "everything is fine" is the shape this whole file exists to warn about."""
    names: set[str] = set()
    for arg in ast.walk(scope.args) if hasattr(scope, "args") and scope.args else ():
        if isinstance(arg, ast.arg):
            names.add(arg.arg)
    for n in _within_scope(scope):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        elif isinstance(n, ast.withitem) and isinstance(n.optional_vars, ast.Name):
            names.add(n.optional_vars.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
    # A nested def/class binds its NAME here, even though its body is another scope.
    for child in _nested_scopes(scope):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
    return names


def _label(scope: ast.AST) -> str:
    return getattr(scope, "name", None) or type(scope).__name__


def _calls_in(scope: ast.AST, visible: set[str], path: pathlib.Path, where: str,
              out: list[str]) -> None:
    for n in _within_scope(scope):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in visible:
            out.append(f"{path.name}:{n.lineno} — {n.func.id}() in {where} "
                       f"calls the MODULE {n.func.id}")


def _offenders(path: pathlib.Path) -> list[str]:
    package = "openfactory." + ".".join(path.relative_to(PKG).with_suffix("").parts[:-1])
    tree = ast.parse(path.read_text())

    # Module-scope imports only: a name bound at the top of the file is what every scope in it
    # sees unless that scope says otherwise.
    top = ast.Module(body=[n for n in tree.body
                           if isinstance(n, (ast.Import, ast.ImportFrom))], type_ignores=[])
    module_names = _module_names_bound(top, package=package)
    if not module_names:
        return []

    out: list[str] = []

    def _descend(scope: ast.AST, shadowed: frozenset[str], where: str) -> None:
        # At module level the module-object imports ARE the binding, so they are not shadowing;
        # anything else bound up there (a later reassignment) means the name may no longer be a
        # module, and this errs towards saying nothing.
        own = _bindings(scope) - (module_names if scope is tree else set())
        visible = module_names - shadowed - own
        if visible:
            _calls_in(scope, visible, path, where, out)
        for child in _nested_scopes(scope):
            _descend(child, frozenset(shadowed | own), f"{where} › {_label(child)}()"
                     if where else f"{_label(child)}()")

    _descend(tree, frozenset(), path.stem)
    return out


def test_no_function_calls_a_name_that_is_a_module():
    offenders: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        offenders += _offenders(path)
    assert not offenders, (
        "these calls raise TypeError every time they run — a module object is not callable, and "
        "a broad `except` nearby turns that into a plausible negative answer:\n  "
        + "\n  ".join(offenders))


def _scan(source: str) -> list[str]:
    """Run the guard over `source` as if it were a module of this package.

    Written to a real path under `openfactory/` because `_is_module` resolves imports against the
    tree on disk — the probe has to live where a module would."""
    target = PKG / "_guard_mutation_probe.py"
    try:
        target.write_text(source)
        return _offenders(target)
    finally:
        target.unlink(missing_ok=True)


def test_the_guard_sees_the_defect_it_was_written_for():
    """THE GUARD IS MUTATED, not trusted. The exact shape that shipped: a module-level
    `from openfactory import namespace`, and a function calling `namespace()` with no local
    import — plus the sibling that IS correct because it shadows, which must stay silent."""
    found = _scan(
        "from openfactory import namespace\n"
        "\n"
        "def broken(client):\n"
        "    return list_jobs(client, namespace())\n"
        "\n"
        "def fine(client):\n"
        "    from openfactory.runtime.temporal.connection import namespace\n"
        "    return list_jobs(client, namespace())\n"
    )
    assert any("broken" in f for f in found), (
        "the guard did not see the defect that cost the pilot a merge — it is decoration")
    assert not any("fine" in f for f in found), (
        "the guard flags a function whose own import shadows the module — it would be turned off")


@pytest.mark.parametrize("name,source", [
    # THE MASK. An import inside a CLOSURE is not a binding in the enclosing function, and the
    # first version of this guard used `ast.walk` — which descends — so moving the shadowing
    # import one level in silenced it completely.
    ("a nested function's import does not excuse its parent",
     "from openfactory import namespace\n"
     "def outer(client):\n"
     "    def inner():\n"
     "        from openfactory.runtime.temporal.connection import namespace\n"
     "        return namespace()\n"
     "    return list_jobs(client, namespace())\n"),
    # A call at module scope was not examined at all: the walk only ever entered functions.
    ("a call at module scope",
     "from openfactory import namespace\n"
     "NS = namespace()\n"),
    # Nor was a class body.
    ("a call in a class body",
     "from openfactory import namespace\n"
     "class C:\n"
     "    NS = namespace()\n"),
    # A decorator, a default argument and a comprehension are all outside a function's body but
    # inside the module's — the same blind spot wearing different clothes.
    ("a call in a default argument",
     "from openfactory import namespace\n"
     "def f(ns=namespace()):\n"
     "    return ns\n"),
    ("a call inside a comprehension",
     "from openfactory import namespace\n"
     "def f(rows):\n"
     "    return [r for r in rows if r == namespace()]\n"),
])
def test_the_guard_survives_the_mutations_of_its_own_defect_class(name, source):
    """FIVE SHAPES THAT ALL RAISE THE SAME TypeError, and the first version of this guard missed
    every one of them — reported by an adversarial verifier the same night it was written, which
    is the only reason they are here rather than in production.

    Nothing else in the toolchain looks: ruff does not, and the type checker does not run on this
    repository's tests."""
    assert _scan(source), f"the guard is blind to {name} — it raises TypeError every time it runs"


@pytest.mark.parametrize("name,source", [
    ("a parameter shadowing the module",
     "from openfactory import namespace\n"
     "def f(namespace):\n"
     "    return namespace()\n"),
    ("an assignment shadowing the module",
     "from openfactory import namespace\n"
     "def f(get):\n"
     "    namespace = get\n"
     "    return namespace()\n"),
    ("a nested function with its own import",
     "from openfactory import namespace\n"
     "def outer():\n"
     "    def inner():\n"
     "        from openfactory.runtime.temporal.connection import namespace\n"
     "        return namespace()\n"
     "    return inner\n"),
    ("a name that is a class, not a module",
     "from openfactory.contracts import Ticket\n"
     "def f():\n"
     "    return Ticket()\n"),
])
def test_the_guard_stays_silent_where_the_code_is_right(name, source):
    """The other direction, and it matters as much: a guard that cries about correct code is a
    guard somebody deletes. `Ticket` is the case that failed on the first run — this repository is
    developed on a case-insensitive filesystem, so `contracts/Ticket.py` "exists"."""
    assert not _scan(source), f"the guard wrongly flags {name}"

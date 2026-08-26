"""Every `from openfactory.… import name` must name something that exists.

THE DEFECT THIS GENERALISES. `openfactory/doctor.py` did `from openfactory.product.loader import
load_product_docs`. There is no such function and there never was — the real entry point is
`load_product_context`, three lines further down the same file. The import sat inside a probe
body, the probe body was reached only by `probes_for()`, and `probes_for()` was built by no test.
So the statement was written once, ran for the first time months later against a real client's
first project, and produced "could not check product_link" — a broken check that reads as a
failing one.

WHY A TYPE CHECKER IS NOT THIS. mypy would catch it, and mypy is not in this repository's gate.
More to the point, the property is worth pinning independently of the tool that happens to check
it: an internal import that names nothing is a rename somebody did not finish, and the cost of
noticing it in CI versus in a client's terminal is the entire difference.

WHY IT IS AST AND NOT `importlib`. Importing every module to ask what it defines would drag in
every vendor library, defeat the lazy ports C-21 shipped, and execute module-level code in a test.
Reading the target file answers the same question for free. The price is the two special cases
below — PEP 562 `_LAZY` tables and submodule imports — and both are explicit rather than a
wildcard exemption.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module_file(dotted: str) -> pathlib.Path | None:
    """The file a dotted `sdlc.…` path resolves to, module or package."""
    as_module = ROOT / (dotted.replace(".", "/") + ".py")
    if as_module.is_file():
        return as_module
    as_package = ROOT / dotted.replace(".", "/") / "__init__.py"
    return as_package if as_package.is_file() else None


def _collect(body, into: set[str]) -> None:
    """Names bound at module scope, descending into `if`/`try` — which is where `TYPE_CHECKING`
    blocks and optional-dependency fallbacks put their definitions."""
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            into.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                elements = target.elts if isinstance(target, ast.Tuple) else [target]
                into.update(e.id for e in elements if isinstance(e, ast.Name))
            # PEP 562: a lazy package's `_LAZY` keys resolve through `__getattr__`, so they are
            # every bit as real as a plain import — just not until first use (C-21).
            if any(isinstance(t, ast.Name) and t.id == "_LAZY" for t in node.targets) and \
                    isinstance(node.value, ast.Dict):
                into.update(k.value for k in node.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            into.add(node.target.id)
        elif isinstance(node, ast.Import):
            into.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            into.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.If | ast.Try):
            _collect(node.body, into)
            _collect(node.orelse, into)
            for handler in getattr(node, "handlers", []):
                _collect(handler.body, into)


def unresolved_imports(path: pathlib.Path, source: str,
                       read=lambda p: p.read_text()) -> list[str]:
    """Every `from openfactory.X import Y` in `source` where `Y` is not defined by `sdlc.X`.

    Split out from the sweep so the sabotage below can feed it a module that is wrong on purpose —
    a guard that has never failed is a guard nobody has checked."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        if not (node.module == "openfactory" or node.module.startswith("openfactory.")):
            continue
        target = _module_file(node.module)
        if target is None:
            problems.append(f"{path.name}:{node.lineno} — no module {node.module!r}")
            continue
        exported: set[str] = set()
        _collect(ast.parse(read(target)).body, exported)
        for alias in node.names:
            if alias.name == "*" or alias.name in exported:
                continue
            # `from openfactory.pkg import submodule` imports a FILE, not a name in `__init__.py`.
            if _module_file(f"{node.module}.{alias.name}") is not None:
                continue
            problems.append(
                f"{path.name}:{node.lineno} — {node.module} has no {alias.name!r}"
            )
    return problems


SOURCES = sorted(p for p in (ROOT / "openfactory").rglob("*.py") if "__pycache__" not in str(p))


def test_the_sweep_walks_something():
    assert len(SOURCES) >= 100


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_internal_import_names_something_that_exists(path):
    problems = unresolved_imports(path, path.read_text())
    assert not problems, (
        "an internal import names something that does not exist. It will raise the first time "
        "that line runs, which for an import inside a function body can be months later and in "
        "somebody else's terminal:\n  " + "\n  ".join(problems)
    )


# ── the guard, sabotaged ────────────────────────────────────────────────────────────────────────

def test_the_guard_catches_a_name_that_does_not_exist():
    """The exact shape of the bug it was written for."""
    problems = unresolved_imports(
        pathlib.Path("fake.py"),
        "from openfactory.product.loader import load_product_docs",
    )
    assert problems and "load_product_docs" in problems[0]


def test_the_guard_accepts_a_name_that_does(tmp_path):
    assert not unresolved_imports(
        pathlib.Path("fake.py"),
        "from openfactory.product.loader import load_product_context",
    )


def test_the_guard_accepts_a_lazily_exported_name():
    """`GitHubIssuesTracker` is not in `tracker/__init__.py` as an import — it is a `_LAZY` key
    resolved by `__getattr__`. A guard that flagged it would have made C-21 impossible to keep.
    (The example was `SlackNotifier` until the chat notifier left `notify/__init__.py` with its
    package, 2026-08-26 — a lazy export of a name the distribution does not contain is a promise
    that raises on first use.)"""
    assert not unresolved_imports(
        pathlib.Path("fake.py"),
        "from openfactory.adapters.tracker import GitHubIssuesTracker",
    )


def test_the_guard_accepts_a_submodule():
    assert not unresolved_imports(
        pathlib.Path("fake.py"),
        "from openfactory.product import loader",
    )


def test_the_guard_ignores_third_party_and_relative_imports():
    assert not unresolved_imports(
        pathlib.Path("fake.py"),
        "from pydantic import BaseModel\nfrom . import sibling\nimport os",
    )

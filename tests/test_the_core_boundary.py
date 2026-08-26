"""The Core is named, and it does not import the shell (C-21).

The boundary is **named and enforced inside this repository**, and it has to be, because the guard
is what stops the seams decaying back into direct construction — ADR-0022's own recorded risk:
*"a registry can rot into a lookup nobody uses."* `docs/core/02` §1 is the definition this file
executes; a boundary stated only in a document is a boundary nobody measures.

WHAT IS SHIPPED HERE IS THE GUARD, NOT THE MOVE. Physically relocating ~2,600 lines into a
`openfactory_core/` directory rewrites several hundred import statements and changes no behaviour
whatsoever. The property that matters — **the Core does not depend on the shell** — is true or
false today regardless of which directory the files sit in, and asserting it is what makes the
later move mechanical and boring instead of an opportunity to break something. Directory first,
guard later would have been the wrong order.

THE DEFINITION IS THE INTERESTING PART. `docs/core/02` §1 gives three questions, and a module is
Core only if all three answer yes: would it be identical for a client on Jira + GitLab + Teams +
Codex; can it run with no I/O, no clock and no network; would deleting it change what the factory
MEANS rather than how it runs. The list below is that test applied, and every entry earns its place
by the answer rather than by where it happens to live.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The Core, by the test in `docs/core/02` §1.
#:
#: `adapters/*/base.py` is here and the adapters themselves are not: a PORT is a statement about
#: what the Core calls, and an adapter is a vendor. That distinction is the whole of ADR-0022.
CORE = [
    "openfactory/contracts",                    # the domain model and the vocabulary
    # `policy/` is NOT homogeneous, and saying so is the finding. `floor.py` and `test_work.py`
    # are pure policy. `presets.py` reads a table shipped inside the package (allowed, bounded
    # below) and `conformance.py` globs the CLIENT's repository to check that declared doc paths
    # exist — that is genuine I/O on external state, so it is a checker that needs a checkout,
    # not Core. Splitting its pure half out is the purer move and a refactor, not a discovery.
    "openfactory/policy/floor.py",
    "openfactory/policy/test_work.py",
    "openfactory/policy/presets.py",
    "openfactory/orchestrator/merge_policy.py",  # pure decisions over domain types
    "openfactory/orchestrator/validation.py",   # ditto
    "openfactory/adapters/agent/base.py",       # the ports — what the Core calls
    "openfactory/adapters/board/base.py",
    "openfactory/adapters/channel/base.py",
    "openfactory/adapters/environment/base.py",
    "openfactory/adapters/forge/base.py",
    "openfactory/adapters/notify/base.py",
    "openfactory/adapters/reviewer/base.py",
    "openfactory/adapters/sandbox/base.py",
    "openfactory/adapters/tracker/base.py",
]

#: What the Core may never reach for. Each is a layer BELOW or BESIDE it in `docs/core/00` §5, and
#: an import of any one inverts the dependency the whole programme exists to establish.
FORBIDDEN = (
    "openfactory.runtime",       # the engine — it CALLS the Core, never the reverse (ADR-0033)
    "openfactory.product",       # an application
    "openfactory.api",           # an application
    "openfactory.techlead",      # an application
    "openfactory.knowledge",     # an application
    "openfactory.factory",       # the composition root: it wires the Core, so it is not part of it
    "openfactory.registry",      # deployment state
    "openfactory.credentials",   # the environment
    "openfactory.loader",        # reads the filesystem
    "openfactory.paths",         # ditto
    "openfactory.observability",  # telemetry: the Core decides, it does not report
)

#: Third-party packages the Core may not import. A Core that needs boto3 is not installable
#: without AWS, and a Core that needs temporalio is not workflow-engine-agnostic — the claim
#: `docs/core/02` E1 says a `workflow.patched()` in the Core would falsify.
#:
#: `yaml` IS ALLOWED, and the reason is a real deviation worth stating rather than hiding.
#: `policy/presets.py` reads framework-owned stack presets from a directory shipped inside the
#: package, and `conformance.py` and `validation.py` both consult them while deciding. By the
#: letter of `docs/core/02` §1 that is I/O in the Core. By its intent it is not: there is no
#: network, no clock, no external state and no vendor — it is a constant table that happens to be
#: written in YAML rather than in Python. Handing the presets IN would be purer and is a
#: refactor, not a discovery. What matters is that the access stays bounded, which the next test
#: asserts.
FORBIDDEN_THIRD_PARTY = ("boto3", "botocore", "temporalio", "slack_sdk", "fastapi", "uvicorn",
                         "typer", "httpx", "requests")


def _files():
    for entry in CORE:
        path = ROOT / entry
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*.py") if "__pycache__" not in str(p))
        else:
            yield path


def _imports(path: pathlib.Path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield node.lineno, a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


FILES = list(_files())


def test_every_declared_core_file_exists():
    """A list that names a file which was moved or deleted silently stops guarding it."""
    missing = [e for e in CORE if not (ROOT / e).exists()]
    assert not missing, missing


def test_the_guard_walks_something():
    assert len(FILES) >= 15


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_core_does_not_import_the_shell(path):
    offenders = [
        f"{path.relative_to(ROOT)}:{line} — {mod}"
        for line, mod in _imports(path)
        if any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN)
    ]
    assert not offenders, (
        "the Core reached into a layer that is supposed to depend on IT. The engine calls the "
        "Core, never the reverse (docs/core/00 §5, ADR-0033):\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_core_needs_no_vendor_library(path):
    offenders = [
        f"{path.relative_to(ROOT)}:{line} — {mod}"
        for line, mod in _imports(path)
        if mod.split(".")[0] in FORBIDDEN_THIRD_PARTY
    ]
    assert not offenders, (
        "the Core would not install without this dependency. A Core that needs boto3 cannot run "
        "without AWS; one that needs temporalio is not engine-agnostic:\n  " + "\n  ".join(offenders)
    )


def test_the_core_imports_cleanly_with_nothing_but_pydantic():
    """The installability claim, asserted rather than assumed: a subprocess that blocks every
    forbidden third-party package must still import the whole Core."""
    import subprocess
    import sys
    import textwrap

    mods = [str(p.relative_to(ROOT)).replace("/", ".")[:-3].removesuffix(".__init__")
            for p in FILES]
    code = textwrap.dedent(f"""
        import sys, importlib

        BANNED = {FORBIDDEN_THIRD_PARTY!r}

        class _Block:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BANNED:
                    raise ImportError(f"{{name}} is not available to the Core")
                return None

        sys.meta_path.insert(0, _Block())
        for m in {mods!r}:
            importlib.import_module(m)
        print("OK")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_only_thing_the_core_reads_is_its_own_presets():
    """The bound on the deviation above. `yaml` is allowed because the Core reads a table shipped
    inside its own package — so the guard is that it reads NOTHING ELSE. Without this, allowing
    the parser quietly allows reading a client repository, a config file or a cache."""
    reads: list[str] = []
    for path in FILES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                "read_text", "read_bytes", "open", "glob", "rglob", "iterdir", "listdir"
            ):
                reads.append(f"{path.relative_to(ROOT)}:{node.lineno} — .{node.attr}()")
    allowed = "openfactory/policy/presets.py"
    unexpected = [r for r in reads if not r.startswith(allowed)]
    assert not unexpected, (
        "the Core reached the filesystem somewhere other than its own shipped presets:\n  "
        + "\n  ".join(unexpected)
    )


def test_the_presets_directory_is_inside_the_package():
    """If the presets ever moved outside the package, `yaml` would stop being a table reader and
    start being a config loader — the same import, a different thing entirely."""
    from openfactory.policy import presets

    assert presets._PRESETS_DIR.is_relative_to(ROOT / "openfactory")


# ── the shell may depend on the Core, and does ──────────────────────────────────────────────────

def test_the_dependency_actually_points_the_right_way():
    """A boundary nothing crosses in EITHER direction is not a boundary, it is dead code. The
    shell must genuinely consume the Core, or this whole guard is protecting nothing."""
    consumers = 0
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        if "__pycache__" in str(path) or any(str(path).endswith(e) for e in CORE):
            continue
        if any(m.startswith("openfactory.contracts") for _l, m in _imports(path)):
            consumers += 1
    assert consumers >= 20, f"only {consumers} modules consume the Core"

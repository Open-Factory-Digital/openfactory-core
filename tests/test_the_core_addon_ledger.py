"""The core/add-on ledger is DERIVED, not promised — #106 item 3.

`docs/core/07-extensibility.md` §10 states the list: what is vendor-owned, and which core modules
still reach a vendor. A list in a document decays the day after it is written — unless the tree is
what writes it. So this file derives the core→vendor edges from the AST, two ways:

  * a VENDOR SDK import (`boto3`/`botocore`/`slack_sdk`/`telegram`), module scope or function
    body — the shape the ledger was first written for;
  * an import BY PATH of a vendor-owned module — `from openfactory.adapters.github_app import …`
    inside a core module is a core→vendor edge whether or not that file imports an SDK. It was
    the blind half: 18 of the 21 `vendor_modules` import no SDK at all (they reach GitHub, Azure
    DevOps and Jira through `gh`, `requests` and `httpx`), so `cli.py`, `floor/reading.py` and
    `api/app.py` importing them passed a scan that keyed on SDK names (175 passed, 2026-08-24).

and fails when the ledger and the tree disagree in EITHER direction:

    a new vendor edge in core            → not in the ledger → red (the boundary moved, silently)
    a mixed entry whose edge is gone     → still in the ledger → red (paid debt must leave)
    a vendor entry whose file is gone    → still in the ledger → red (a stale line is not a ledger)

That third line was MISSING until 2026-08-25: two phantom entries added to `vendor_modules` passed
every test, and deleting all 22 listed vendor files across three removal experiments left the
guard green each time, while §10 promised "both directions". Ownership is BY PATH, so the
direction that exists for it is existence — `vendor_modules`/`vendor_packages` are not ratcheted
on an SDK import they mostly do not have.

WHO MAY IMPORT A VENDOR PATH WITHOUT BEING LISTED, each by name and with its reason: the registry
rows (`adapters/<axis>/registry.py`, `observability/registry.py`, and the board axis's registry,
which is called `factory.py`) — `kind → builder` is exactly the place that knows the concrete
modules; the composition root `factory.py`; and the per-axis seam `adapters/agent/session_store.py`,
the free store dispatching to its S3 twin by name. Anything else is debt, and debt is listed in
`mixed_modules` with what it reaches — visibly, in a review, never by drift.

THE HARNESS AXIS IS NOT DECIDED HERE. ADR-0040 says the harness, its model and its credential are
configuration and therefore core; `adapters/agent/claude_code.py` is not on the vendor side and
`codex.py`/`kimi.py`/`opencode.py` are, as §10 lists them. This file derives from the list; it does
not tag files by name.
"""

from __future__ import annotations

import ast
import pathlib
import re

import add_ons
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "core" / "07-extensibility.md"

#: The SDKs whose import makes a module vendor-dependent. `requests` is deliberately NOT here —
#: it is a generic HTTP client, and the Jira/ADO adapters using it are already on the vendor side.
VENDOR_SDKS = ("boto3", "botocore", "slack_sdk", "telegram")

#: Core modules that may import a vendor path without being listed as debt, each with the reason
#: the exemption is architecture rather than a hole. A registry is matched by shape below; these
#: are the ones a shape would not find.
ALLOWED_IMPORTERS: dict[str, str] = {
    "openfactory/factory.py":
        "the composition root — the one place allowed to know every concrete adapter",
    "openfactory/adapters/board/factory.py":
        "the board axis's registry, which is called factory.py",
    # `observability/registry.py` and `adapters/agent/session_store.py` were here as importers of
    # their vendor twins by name; the AWS cut of 2026-08-26 turned both into registry rows the
    # vendor package fills, so neither imports a vendor path any more and the ratchet below
    # (an exemption nobody uses is an exemption that will be used later) removed them.
}
_REGISTRY = re.compile(r"openfactory/adapters/[^/]+/registry\.py")


def _ledger(doc: pathlib.Path = DOC) -> tuple[set[str], set[str], set[str]]:
    """The three lists, parsed out of the doc's fenced yaml — the doc IS the source of truth."""
    text = doc.read_text()
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    joined = "\n".join(blocks)

    def section(name: str) -> set[str]:
        m = re.search(rf"{name}:\n((?:  - .*\n?)*)", joined)
        assert m, f"the ledger in {doc.name} has no `{name}:` list"
        return {line.strip()[2:].split("#")[0].strip()
                for line in m.group(1).splitlines() if line.strip().startswith("- ")}

    return section("vendor_modules"), section("vendor_packages"), section("mixed_modules")


def _module_name(rel: str) -> str:
    """`openfactory/a/b.py` → `openfactory.a.b`; a package directory or `__init__.py` → the
    package; used on both sides of the comparison so the two spellings cannot disagree."""
    rel = rel.rstrip("/")
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def _imported_modules(path: pathlib.Path, rel: str) -> set[str]:
    """Every absolute module name this file imports, at any depth. A relative import is resolved
    against the file's own package, and `from a.b import c` contributes both `a.b` and `a.b.c`
    — `c` may be the vendor module itself."""
    package = _module_name(rel)
    if not rel.endswith("/__init__.py"):
        package = package.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join([*parts, base] if base else parts)
            found.add(base)
            found |= {f"{base}.{a.name}" for a in node.names}
    return found


def _vendor_sdk_imports(path: pathlib.Path) -> set[str]:
    """Every vendor SDK this module imports, at any depth — module scope or lazy."""
    hits: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            hits |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            hits.add(node.module.split(".")[0])
    return {h for h in hits if h in VENDOR_SDKS}


def _on_the_vendor_side(rel: str, vendor_modules: set[str], vendor_packages: set[str]) -> bool:
    return rel in vendor_modules or any(rel.startswith(pkg) for pkg in vendor_packages)


def _vendor_path_imports(path: pathlib.Path, rel: str, vendor_modules: set[str],
                         vendor_packages: set[str]) -> set[str]:
    """Every vendor-owned module this file imports by name, as `path:<module>` — a vendor module
    by its own name, anything inside a vendor package by the package's."""
    modules = {_module_name(m) for m in vendor_modules}
    packages = {_module_name(p) for p in vendor_packages}
    hits = set()
    for name in _imported_modules(path, rel):
        if name in modules:
            hits.add(f"path:{name}")
        for pkg in packages:
            if name == pkg or name.startswith(pkg + "."):
                hits.add(f"path:{pkg}")
    return hits


def _tree_map(root: pathlib.Path = ROOT,
              ledger: tuple[set[str], set[str], set[str]] | None = None) -> dict[str, set[str]]:
    """Every CORE module that reaches a vendor, with what it reaches — an SDK name, or
    `path:<vendor module>`. Files on the vendor side are not core and are not mapped."""
    vendor_modules, vendor_packages, _ = ledger or _ledger()
    out: dict[str, set[str]] = {}
    for path in sorted(root.joinpath("openfactory").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if _on_the_vendor_side(rel, vendor_modules, vendor_packages):
            continue
        found = _vendor_sdk_imports(path) | _vendor_path_imports(path, rel, vendor_modules,
                                                                 vendor_packages)
        if found:
            out[rel] = found
    return out


def _may_import_a_vendor_path(rel: str) -> bool:
    return rel in ALLOWED_IMPORTERS or _REGISTRY.fullmatch(rel) is not None


def _unlisted(root: pathlib.Path = ROOT,
              ledger: tuple[set[str], set[str], set[str]] | None = None) -> dict[str, list[str]]:
    """Every core module that reaches a vendor and is neither listed as mixed nor allowed to —
    what direction one reports. One function for the real tree and the planted one, so the
    exemption's shape is judged where a widening is observable."""
    vendor_modules, vendor_packages, mixed = ledger or _ledger()
    return {rel: sorted(found)
            for rel, found in _tree_map(root, (vendor_modules, vendor_packages, mixed)).items()
            if rel not in mixed and not _may_import_a_vendor_path(rel)}


# ── the scans can see what they hunt ────────────────────────────────────────────────────────────

def test_the_scan_can_SEE_a_lazy_vendor_import(tmp_path):
    """The positive twin: a function-level import — the exact shape this hunts — must be seen."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def sink():\n    import boto3\n    return boto3\n"
        "def chat():\n    from slack_sdk import WebClient\n    return WebClient\n"
        "import json  # a stdlib import must not count\n")
    assert _vendor_sdk_imports(planted) == {"boto3", "slack_sdk"}


def _planted_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """A miniature package: one vendor module, one vendor package, and four importers in the
    shapes the real tree uses — absolute, relative, lazy, and from inside a registry."""
    pkg = tmp_path / "openfactory"
    (pkg / "adapters" / "tracker").mkdir(parents=True)
    (pkg / "api").mkdir()
    (pkg / "runtime" / "fargate").mkdir(parents=True)
    (pkg / "adapters" / "github_app.py").write_text("def mint():\n    return 'ghs_x'\n")
    (pkg / "runtime" / "fargate" / "launcher.py").write_text("class FargateLauncher: ...\n")
    (pkg / "core_a.py").write_text(
        "def token():\n    from openfactory.adapters.github_app import mint\n    return mint()\n")
    (pkg / "api" / "core_b.py").write_text(
        "from ..adapters import github_app\n"
        "def run():\n    from ..runtime.fargate.launcher import FargateLauncher\n"
        "    return github_app, FargateLauncher\n")
    (pkg / "adapters" / "tracker" / "registry.py").write_text(
        "def _github():\n    from openfactory.adapters import github_app\n    return github_app\n")
    # a CORE file that merely lives under adapters/ — not a registry, so not exempt by shape
    (pkg / "adapters" / "tracker" / "helper.py").write_text(
        "from openfactory.adapters.github_app import mint\n")
    (pkg / "clean.py").write_text("import json\nfrom openfactory.api import core_b\n")
    return tmp_path


_PLANTED_LEDGER = ({"openfactory/adapters/github_app.py"}, {"openfactory/runtime/fargate/"}, set())


def test_the_scan_can_SEE_an_import_of_a_vendor_module_BY_PATH(tmp_path):
    """The twin for the half that was blind: absolute and relative, module scope and lazy, the
    module itself and a name from inside a vendor package — every shape the eleven real
    importers use, on a tree of its own."""
    root = _planted_tree(tmp_path)
    found = _tree_map(root, _PLANTED_LEDGER)
    assert found == {
        "openfactory/core_a.py": {"path:openfactory.adapters.github_app"},
        "openfactory/api/core_b.py": {"path:openfactory.adapters.github_app",
                                      "path:openfactory.runtime.fargate"},
        "openfactory/adapters/tracker/registry.py": {"path:openfactory.adapters.github_app"},
        "openfactory/adapters/tracker/helper.py": {"path:openfactory.adapters.github_app"},
    }, found
    assert "openfactory/clean.py" not in found, "a core→core import was counted as a vendor edge"
    assert _may_import_a_vendor_path("openfactory/adapters/tracker/registry.py")
    assert not _may_import_a_vendor_path("openfactory/api/core_b.py")


def test_the_exemption_by_shape_is_a_REGISTRY_and_not_every_file_under_adapters(tmp_path):
    """The twin of `_REGISTRY`. No core file under `adapters/` imports a vendor path on the real
    tree today, so the exemption could widen to `adapters/.*\\.py` and nothing would notice
    (reviewer's cut, 2026-08-26). On the planted tree the widening is observable: a helper beside
    the registry, importing the same vendor module, must be REPORTED by direction one while the
    registry beside it is not."""
    unlisted = _unlisted(_planted_tree(tmp_path), _PLANTED_LEDGER)

    assert "openfactory/adapters/tracker/helper.py" in unlisted, (
        f"a core file under adapters/ that is not a registry walked past direction one: "
        f"{unlisted}")
    assert "openfactory/adapters/tracker/registry.py" not in unlisted, (
        "the registry row itself is reported as debt — the exemption by shape is gone")
    assert set(unlisted) == {"openfactory/core_a.py", "openfactory/api/core_b.py",
                             "openfactory/adapters/tracker/helper.py"}, unlisted


# ── direction one: the tree may not grow an edge the ledger does not name ───────────────────────

def test_every_vendor_import_is_on_the_ledger():
    """Direction one: the tree may not grow a vendor dependency — an SDK import or a by-path
    import of a vendor-owned module — that the ledger does not name."""
    offenders = _unlisted()
    assert not offenders, (
        f"these core modules reach a vendor and the ledger in {DOC.name} §10 does not name them: "
        f"{offenders}. Either the code belongs on the vendor side (an adapter file, "
        f"runtime/slack/, runtime/fargate/), behind a registry, or the entry belongs in "
        f"`mixed_modules` with what it reaches — visibly, in a review, never by drift")


# ── direction two: the ratchet ──────────────────────────────────────────────────────────────────

def test_every_mixed_entry_is_still_EARNED():
    """Direction two, the ratchet: paid debt must leave the list. An entry for a module that no
    longer reaches any vendor reads as open debt that somebody already closed — delete it, and
    the count goes down by one."""
    _, _, mixed = _ledger()
    tree = _tree_map()
    stale = sorted(rel for rel in mixed if rel not in tree)
    assert not stale, (
        f"{stale} are listed as mixed in {DOC.name} §10 but no longer import a vendor SDK or a "
        f"vendor-owned module — the debt was paid; delete the entries so the ratchet records it")


def test_mixed_modules_are_core_shaped_not_vendor_shaped():
    """A file inside a vendor package listed as `mixed` would double-count the same debt — the
    two lists partition the world, and a partition that overlaps stops meaning either thing."""
    vendor_modules, vendor_packages, mixed = _ledger()
    misfiled = sorted(rel for rel in mixed if _on_the_vendor_side(rel, vendor_modules,
                                                                    vendor_packages))
    assert not misfiled, f"{misfiled} are on both sides of the ledger"


# ── direction three: a vendor entry is a file ───────────────────────────────────────────────────

def test_every_vendor_entry_EXISTS():
    """Ownership is by path, so the direction that exists for it is existence. A NAMED set, not
    `all()`: the failure has to say which line is stale. An empty ledger is not what this
    catches — direction one already fails on a tree whose vendor imports name nobody."""
    vendor_modules, vendor_packages, _ = _ledger()
    assert len(vendor_modules) >= 15 and vendor_packages, "the ledger has lost its vendor side"
    # IN THE PUBLIC TREE the entries marked `leaves` are absent by construction — the export
    # removed them — and the ledger is the private tree's list. An entry `docs/STATUS.md` excludes
    # may be absent only there (no `addons/`); in the private tree every entry must exist.
    public = add_ons.is_public_tree()
    missing = sorted(p for p in vendor_modules | vendor_packages
                     if not (ROOT / p).exists() and not (public and add_ons.package_for(p)))
    assert not missing, (
        f"the ledger in {DOC.name} §10 names vendor files that do not exist — moved, renamed or "
        f"deleted without the line following: {missing}")


def test_every_allowed_importer_is_still_an_importer():
    """The twin of the exemption list: an allowed importer that no longer imports a vendor path,
    or no longer exists, is an exemption nobody needs — and an exemption list that can only grow
    is indistinguishable from no guard at all."""
    tree = _tree_map()
    idle = sorted(rel for rel in ALLOWED_IMPORTERS if rel not in tree)
    assert not idle, (
        f"{idle} are allowed to import a vendor path and do not — drop the exemption, its "
        f"reason no longer applies")


# ── the dev extra is this tree's suite, not a vendor's ──────────────────────────────────────────

def _dev_extra_names() -> set[str]:
    import re
    import tomllib

    dev = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]["dev"]
    return {re.split(r"[<>=!\[ ;]", d, maxsplit=1)[0].strip().replace("-", "_") for d in dev}


def test_the_dev_extra_carries_no_sdk_the_suite_does_not_import():
    """Until 2026-08-26 `dev` carried `slack_sdk` and `boto3` so a bare `.[dev]` on the private
    tree could collect the add-on packages' tests before `make install` — and every stranger's
    dev install of the public core downloaded two SDKs the public tree uses nowhere, under a
    comment about a directory that tree does not have. Derived: a vendor SDK may sit in `dev`
    only if some module under `tests/` imports it (module scope or lazy, by AST — a name inside
    a subprocess script string is not an import); the package that ships a vendor's rows
    declares that vendor's SDK, and its tests are collected only where it imports."""
    imported: set[str] = set()
    for path in (ROOT / "tests").glob("*.py"):
        imported |= _vendor_sdk_imports(path)
    carried = _dev_extra_names() & set(VENDOR_SDKS)
    assert carried <= imported, (
        f"the core's dev extra carries {sorted(carried - imported)}, which no module under tests/ "
        f"imports — a vendor SDK is the dependency of the package that ships the vendor's rows "
        f"(addons/<package>/pyproject.toml), and its tests are collected only where it imports")


def test_each_add_on_package_declares_its_own_sdk():
    """The positive twin: the SDKs left `dev` because the packages declare them — measured on
    each package's own metadata, where the private tree holds them."""
    import tomllib

    if add_ons.is_public_tree():
        pytest.skip("the public tree carries no add-on package to read")
    packages = sorted((ROOT / "addons").glob("*/pyproject.toml"))
    assert packages, "no add-on package under addons/ — the twin has no subject"
    for pyproject in packages:
        deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
        names = {d.split(">")[0].split("=")[0].split("[")[0].strip().replace("-", "_") for d in deps}
        assert names & set(VENDOR_SDKS), f"{pyproject.parent.name} declares no vendor SDK: {sorted(names)}"

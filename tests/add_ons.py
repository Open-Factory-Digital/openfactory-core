"""Reach a module that leaves the public tree — or skip, by name, naming the package that ships it.

Some tests in this directory exercise the CORE through the chat listener or the cloud launcher:
the action layer's front-end scan walks `runtime/slack/bot.py`, the confirmation tests drive the
bot's click handler, the workflow test reads the launcher's source for the agent wall. They are
not tests of the vendor code — they stay here — but they cannot run where that code is absent,
which is the public export (`docs/STATUS.md` lists the paths). Each such site asks this module
for the module or the file it needs and SKIPS AT RUN TIME, with the skip naming the package to
install, when it is not there. Never at collection: a suite that cannot be collected reports
nothing (`tests/test_ci_runs_what_we_run.py` is about that).

The package name comes from `docs/STATUS.md`'s table — the one place the excluded paths and the
packages that carry them are written down — so this file keeps no copy of that map.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATUS = ROOT / "docs" / "STATUS.md"
HEADING = "## What the public repository contains"


def public_tree_signal() -> str:
    """The ONE path whose presence tells a guard which tree it measures: present, this is the
    private repository, which carries the add-on packages; absent, the public export. Spelled
    here once and read by every guard that needs the distinction (`is_public_tree`), and held
    to a row of STATUS's table by `tests/test_the_public_cut_is_written_down.py` — a signal
    path the export does not exclude would read the public tree as the private one, and an
    export that shipped it would register rows naming modules the tree does not hold."""
    return "addons/"


def is_public_tree() -> bool:
    """True in the export: the signal path is absent."""
    return not (ROOT / public_tree_signal()).is_dir()


def excluded_paths() -> dict[str, str]:
    """path → the package that ships it (`""` when the table names none), from STATUS's table."""
    text = STATUS.read_text()
    if HEADING not in text:
        return {}
    body = text[text.index(HEADING) + len(HEADING):]
    nxt = body.find("\n## ")
    body = body if nxt < 0 else body[:nxt]
    rows = re.findall(r"^\| `([^`]+)` \| (.+?) \|$", body, re.M)
    return {path: (re.search(r"`?(openfactory-[a-z]+)`?", where) or [None, ""])[1]
            for path, where in rows}


def package_for(rel: str) -> str:
    """The package `docs/STATUS.md` says ships `rel` (a path, `openfactory/runtime/slack/bot.py`),
    or `""` when the path does not leave the public tree."""
    for path, package in excluded_paths().items():
        if rel == path or (path.endswith("/") and rel.startswith(path)):
            return package
    return ""


def _as_path(module_name: str) -> str:
    return module_name.replace(".", "/") + ".py"


def module(name: str):
    """Import `name`, or skip naming the package that ships it."""
    package = package_for(_as_path(name)) or package_for(name.replace(".", "/") + "/")
    reason = (f"{name} leaves the public tree with {package or 'an add-on package'}"
              + (f" — install {package} to run this" if package else ""))
    return pytest.importorskip(name, reason=reason)


def source(rel: str) -> pathlib.Path:
    """The path of a file that leaves the public tree, or skip naming its package."""
    path = ROOT / rel
    if not path.exists():
        package = package_for(rel)
        pytest.skip(f"{rel} leaves the public tree with {package or 'an add-on package'}"
                    + (f" — install {package} to run this" if package else ""))
    return path


def sdk(name: str, carried_by: str):
    """Import a vendor SDK a test needs, or skip naming the package that brings it — `carried_by`
    is the tree path of the module that leaves with that package (`docs/STATUS.md`'s table maps
    it), so the reason names the package and this file keeps no SDK → package copy. Since
    2026-08-26 the core's `dev` extra carries no vendor SDK; a test under `tests/` that reaches
    one reaches it through here, at run time, never as a bare import."""
    package = package_for(carried_by)
    return pytest.importorskip(
        name, reason=(f"{name} is the SDK of {package or 'an add-on package'}, which is not "
                      f"installed here" + (f" — install {package} to run this" if package else "")))

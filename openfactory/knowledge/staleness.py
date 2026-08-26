"""Staleness & orphan detection (§12) — what makes the layer SAFE to serve.

A wrong or stale map misleads agents — worse than no map at all. So the bundle is only
trusted when we can PROVE it still describes reality:

- `is_stale`     — the canonical file SET changed (a source was added/removed), OR any tracked
                   file's checksum differs → stale → regenerate before use (or fall back to
                   searching the code). Sources only — never `source_commit` vs HEAD; see the
                   function docstring for why that comparison is structurally always false.
- `orphan_links` — every `source:` link (and key file) must still resolve: the file exists
                   and, when the link is symbol-scoped, the symbol is still a top-level
                   def/class. A link that no longer resolves is an orphan (the code moved,
                   the map didn't).
- `is_trustworthy` — the fail-safe gate the injector uses: fresh AND no orphans. If we
                   cannot CONFIRM freshness (e.g. the bundle won't parse), treat it as
                   untrustworthy — degrade, never mislead.

Every function is best-effort: it answers a boolean/list, it never raises at the caller.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path

from openfactory.knowledge.contracts import KnowledgeBundle
from openfactory.knowledge.generator import canonical_source_files

_log = logging.getLogger("openfactory.knowledge.staleness")


def is_stale(bundle: KnowledgeBundle, repo_path: Path) -> bool:
    """True if the bundle no longer matches the working tree. Checksum-driven and git-free.
    On ANY uncertainty (an unreadable file, an exception) we return True — a fail-safe would
    rather regenerate a fresh bundle than serve a possibly-stale one.

    Freshness is decided by the SOURCES ONLY, never by comparing `source_commit` to HEAD. In
    the persist-per-commit model (§22 D-1/D-2) the bundle is generated from commit X and then
    committed, which creates commit Y — so its stamp is one commit behind HEAD *by
    construction*, permanently. A HEAD comparison would therefore report every correctly
    persisted bundle as stale and the map would never be served once. `source_commit` is
    provenance ("which commit was this derived from"), not the freshness test; the checksums
    are the freshness test, and they are exact."""
    repo = Path(repo_path).expanduser().resolve()
    try:
        tracked = {c.file: c.sha256 for c in bundle.manifest.checksums}
        current = {p.as_posix() for p in canonical_source_files(repo)}
        # a source added or removed since generation → the map's coverage is wrong
        if current != set(tracked):
            return True
        # a tracked file whose bytes changed → its module/imports may have changed
        for rel, expected in tracked.items():
            data = (repo / rel).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                return True
        return False
    except OSError as exc:  # a file vanished/unreadable mid-check → assume stale
        _log.warning("knowledge: staleness check hit %s — treating bundle as stale", exc)
        return True


def _toplevel_symbols(py_source: str) -> set[str]:
    """Top-level def/class names in a Python file (for verifying a symbol-scoped link)."""
    try:
        tree = ast.parse(py_source)
    except (SyntaxError, ValueError):
        return set()
    return {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def orphan_links(bundle: KnowledgeBundle, repo_path: Path) -> list[str]:
    """Every `source:` link (and key file) that no longer resolves, as sorted strings
    ('path' or 'path::symbol'). An empty list means every fact still points at real code."""
    repo = Path(repo_path).expanduser().resolve()
    orphans: set[str] = set()
    for module in bundle.module_map.modules:
        link = module.source
        target = repo / link.file
        if not target.is_file():
            orphans.add(link.file)
        elif link.symbol:
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                orphans.add(f"{link.file}::{link.symbol}")
                continue
            if link.file.endswith(".py") and link.symbol not in _toplevel_symbols(text):
                orphans.add(f"{link.file}::{link.symbol}")
        for kf in module.key_files:
            if not (repo / kf).is_file():
                orphans.add(kf)
    return sorted(orphans)


def is_trustworthy(bundle: KnowledgeBundle | None, repo_path: Path) -> bool:
    """The gate the injector uses (§12 fail-safe): serve the map ONLY when it is present,
    fresh, and free of orphan links. Anything else → False, and the consumer searches the
    code directly instead of trusting knowingly-stale knowledge."""
    if bundle is None:
        return False
    try:
        if is_stale(bundle, repo_path):
            return False
        return not orphan_links(bundle, repo_path)
    except Exception as exc:  # noqa: BLE001 — never let a verification hiccup crash the job
        _log.warning("knowledge: trust check failed (%s) — treating bundle as untrusted", exc)
        return False

"""The system layer, refreshed for a registered product and published in its context repository.

WHERE THE SOURCES COME FROM. The product's own list — `sources:` in the context repository's
`.openfactory/product.yaml` — read only once the product link holds (`load_product_context`: the
registry authorises the context repository, and the context repository names its members). Each
source is checked out through the worker's repository cache, under a key of this layer's own, at
the repository's own default branch; one that cannot be is named in the map, never dropped.

HOW IT IS WRITTEN. Through `pipeline.publish_dir`, the one way derived knowledge reaches the
context repository: onto its default branch, beside `.okf/repos/`, never `--force`, retried once on
a moved tip — the module map's convention (`knowledge-layer.md` D-6, ADR-0045 §6), because the
system layer is derived knowledge like the map and not a proposal anybody reviews.

UNDER THE PRODUCT'S SEMAPHORE (ADR-0051 D7, #266). The push lands on the same branch a person's
save lands on — a decision, a fact, a requirement — and those writes push once and do not retry: a
refresh that pushed between a person's clone and their push made their save fail. So the clone,
the commit and the push happen with the product's semaphore held, which is seconds and never a
model call. The WRITE SEQUENCE is not bumped: the system map is not work, and a turn that checked
for duplicates has nothing to re-check because the map moved. A semaphore that cannot be had in
time costs this refresh (`busy`) and never the person's write; the next refresh publishes.

CONVERGENT. The derivation's `derived_key` blanks every commit and the clock; when it equals the
published one, nothing is cloned, committed or pushed (`unchanged`).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from openfactory.knowledge.system.derive import derive
from openfactory.knowledge.system.render import (
    SYSTEM_DIRNAME,
    SYSTEM_FILE,
    derived_key,
    read_derived_key,
    write_system,
)
from openfactory.knowledge.system.tree import SourceTree

log = logging.getLogger("openfactory.knowledge.system")

#: Outcome words, for the log line the caller writes.
NO_PRODUCT = "no-product"
NO_SOURCES = "no-sources"
UNCHANGED = "unchanged"
PUBLISHED = "published"
BUSY = "busy"
FAILED = "failed"


def system_subpath() -> Path:
    """`.okf/system` — where the layer lives in the context repository, beside `.okf/repos/`."""
    from openfactory.knowledge.okf import OKF_DIRNAME

    return Path(OKF_DIRNAME) / SYSTEM_DIRNAME


def cache_key(project_name: str, repo: str) -> str:
    """This layer's own repository-cache key for one source — never the product role's, the
    refresh's or a job's, so no two consumers reset one checkout under each other."""
    flat = (repo or "unknown").strip().strip("/").replace("/", "--")
    return f"{project_name}-system--{flat}"


def _head(path: Path) -> str:
    """The commit a checkout is on — asked of git by the caller, never inside the derivation."""
    try:
        p = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                           text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("system layer: could not read the commit of %s (%s) — its entries will cite "
                    "no commit", path, exc)
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def gather(project, sources: list[str], *, token: str | None, cache
           ) -> tuple[list[SourceTree], dict[str, str]]:
    """Every source checked out — `(trees, missing)`, where `missing` says why each one that could
    not be was not."""
    from openfactory.adapters.forge.registry import clone_url_for

    trees: list[SourceTree] = []
    missing: dict[str, str] = {}
    for repo in sorted(dict.fromkeys(s for s in sources if s)):
        try:
            url = clone_url_for(project, repo, token=token)
        except Exception as exc:  # noqa: BLE001 — an unknown forge names this source, not the map
            # the reason is PUBLISHED in the context repository: no user part of a URL rides it
            said = re.sub(r"://[^@/\s]+@", "://", str(exc))[:120]
            missing[repo] = f"the forge could not name its address ({said})"
            continue
        path = cache.sync(cache_key(project.name, repo), url, "")
        if path is None:
            missing[repo] = "it could not be checked out"
            continue
        trees.append(SourceTree(repo=repo, root=Path(path), commit=_head(Path(path))))
    return trees, missing


def refresh_system(project, *, token: str | None = None, cache=None, generated_at: str = "",
                   timeout: float | None = None) -> str:
    """Derive the product's system layer and publish it if it changed. Returns an outcome word.

    Never raises for a source, a clone or a push: each is an outcome. It may raise for a defect of
    its own, and its caller (the knowledge refresh) keeps that from reaching a job."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import bot_identity
    from openfactory.knowledge.pipeline import PUBLISHED as DIR_PUBLISHED
    from openfactory.knowledge.pipeline import UNCHANGED as DIR_UNCHANGED
    from openfactory.knowledge.pipeline import publish_dir
    from openfactory.product import semaphore
    from openfactory.product.loader import _read_docs_manifest, load_product_context
    from openfactory.runtime.repo_cache import RepoCache

    cache = cache or RepoCache()
    ctx = load_product_context(project, token=token, cache=cache)
    if not ctx.available:
        return NO_PRODUCT
    docs, error = _read_docs_manifest(Path(ctx.docs_path))
    if docs is None or not docs.sources:
        log.info("system layer: %s declares no sources (%s) — nothing to derive",
                 getattr(project, "name", "?"), error or "an empty `sources:`")
        return NO_SOURCES
    trees, missing = gather(project, list(docs.sources), token=token, cache=cache)
    system = derive(trees, missing=missing,
                    generated_at=generated_at or datetime.now(UTC).isoformat())
    key = derived_key(system)
    if read_derived_key(ctx.docs_path, f"{system_subpath().as_posix()}/{SYSTEM_FILE}") == key:
        return UNCHANGED
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-system-"))
    try:
        write_system(system, tmp / SYSTEM_DIRNAME)
        context_url = clone_url_for(project, project.product.docs_repo, token=token)
        bot = bot_identity()
        try:
            with semaphore.held(project, timeout=timeout):
                done = publish_dir(tmp / SYSTEM_DIRNAME, context_url, subpath=system_subpath(),
                                   message=f"chore(okf): refresh the system layer @ {key}",
                                   what=f"system layer @ {key}",
                                   author=(bot.name or "openfactory-bot",
                                           bot.email or "openfactory-bot@local"))
        except semaphore.Busy as exc:
            log.warning("system layer: %s — not published this round, the next refresh will",
                        exc)
            return BUSY
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if done == DIR_PUBLISHED:
        return PUBLISHED
    return UNCHANGED if done == DIR_UNCHANGED else FAILED


__all__ = ["BUSY", "FAILED", "NO_PRODUCT", "NO_SOURCES", "PUBLISHED", "UNCHANGED", "cache_key",
           "gather", "refresh_system", "system_subpath"]

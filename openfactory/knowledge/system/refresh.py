"""The system layer, refreshed for a registered product and published in its context repository.

WHERE THE SOURCES COME FROM: THE ONE RULE THE PRODUCT ROLE MOUNTS BY (`product/sources.py`, #268
slice 1). The product's own list — `sources:` in the context repository's
`.openfactory/product.yaml` — read only once the product link holds (`load_product_context`: the
registry authorises the context repository, and the context repository names its members); each
entry read for the repository it names (`sources.declared`), addressed by THIS project's forge so
an entry cannot choose the host, brought up side by side (`sources.check_out`), and one that cannot
be is named with the same sentence the role's prompt gives it (`sources.why_not`). An entry that
names no repository is named and never fetched. So the map and the role's mount never disagree
about which repositories are the product's.

HOW EACH IS CHECKED OUT: `SparseRepoCache`, the role's own cache — a partial clone checked out
through a cone that leaves out directories holding nothing but pictures, fonts, archives and
binaries. The credential reaches git in memory and is never written to a `.git/config`. Under keys
of this layer's own (`cache_key`), so a turn's mount and this refresh never reset one checkout
under each other. The cone never leaves out a file this layer reads — every declaration is text
(`tests/test_the_system_layer_is_published.py` holds it) — and what it did leave out is written on
each source in the map.

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

AND THE FLOWS ACROSS THE SOURCES (#268 slice 3, ADR-0052 D19). With the map derived, the flows a
requirement carries across several repositories are observed from the map, the requirements and
the published per-source bundles (`knowledge/flows.py`) and published beside it at `.okf/flows/`,
by the same publisher under the same semaphore, converging on a key of their own. Observations, as
every derived file here is: a capability becomes the product's only when a person confirms it.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from openfactory.knowledge.flows import FLOWS_DIRNAME, observe, read_flows, write_flows
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
    """This layer's own repository-cache key for one source — never the product role's
    (`<project>--source--<repo>`), the refresh's or a job's, so no two consumers reset one checkout
    under each other."""
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


def gather(project, found, *, token: str | None, root: Path | None = None
           ) -> tuple[list[SourceTree], dict[str, str]]:
    """Every source `found` (a `sources.Declared`) names, brought up — `(trees, missing)`, where
    `missing` says, in the role's own sentences, why each one that could not be was not.

    The registry project's own repository is addressed and read as the role reads it: the
    registry's spelling, on the registry's declared base. The rest are addressed as `sources:`
    names them, on their own default branch. `root` is the cache's directory (the deployment's by
    default); one `SparseRepoCache` per source, because a cache keeps its last failure and what
    its cone left out, and the sources are brought up side by side."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.loader import load_manifest_base_branch
    from openfactory.product.config import _source_repo
    from openfactory.product.sources import (
        NOT_ADDRESSABLE,
        NOT_DECLARED,
        Checkout,
        check_out,
        why_not,
    )
    from openfactory.runtime.repo_cache import SparseRepoCache

    own_repo = _source_repo(project)

    def one(coordinate: str, spelling: str, own: bool) -> Checkout:
        try:
            url = clone_url_for(project, (own_repo if own else "") or spelling or coordinate,
                                token=token)
        except Exception as exc:  # noqa: BLE001 — a forge that cannot address this source
            log.warning("system layer: the forge of %s cannot address the source %s (%s)",
                        getattr(project, "name", "?"), coordinate, type(exc).__name__)
            return Checkout(why=NOT_ADDRESSABLE)
        cache = SparseRepoCache(root)
        path = cache.sync(cache_key(project.name, coordinate), url,
                          load_manifest_base_branch(project, default="") if own else "")
        if path is None:
            return Checkout(why=why_not(cache.failure))
        return Checkout(path=path, left_out=tuple(cache.left_out))

    got = check_out(own_repo, found, one)
    # the registry project's repository NOT being among `sources:` is a fact about the ROLE's
    # boundary, which `check_out` holds for it; the product's map is of what the product declares
    missing = {repo: why for repo, why in got.missing.items() if why != NOT_DECLARED}
    trees = [SourceTree(repo=repo, root=Path(path), commit=_head(Path(path)),
                        left_out=got.left_out.get(repo, ()))
             for repo, path in got.placed.items()]
    return trees, missing


def refresh_system(project, *, token: str | None = None, root: Path | None = None,
                   generated_at: str = "", timeout: float | None = None) -> str:
    """Derive the product's system layer and publish it if it changed. Returns an outcome word.

    `root` is where the repository caches live — the deployment's by default; a test hands its
    own. Never raises for a source, a clone or a push: each is an outcome. It may raise for a
    defect of its own, and its caller (the knowledge refresh) keeps that from reaching a job."""
    from openfactory.adapters.forge.registry import clone_url_for
    from openfactory.credentials import bot_identity
    from openfactory.knowledge.pipeline import PUBLISHED as DIR_PUBLISHED
    from openfactory.knowledge.pipeline import UNCHANGED as DIR_UNCHANGED
    from openfactory.knowledge.pipeline import publish_dir
    from openfactory.product import semaphore
    from openfactory.product.loader import load_product_context
    from openfactory.product.sources import declared
    from openfactory.runtime.repo_cache import RepoCache

    ctx = load_product_context(project, token=token, cache=RepoCache(root))
    if not ctx.available:
        return NO_PRODUCT
    found = declared(ctx.docs_path)
    if found.error or not (found.sources or found.refused):
        log.info("system layer: %s declares no sources (%s) — nothing to derive",
                 getattr(project, "name", "?"), found.error or "an empty `sources:`")
        return NO_SOURCES
    trees, missing = gather(project, found, token=token, root=root)
    now = generated_at or datetime.now(UTC).isoformat()
    system = derive(trees, missing=missing, generated_at=now)
    key = derived_key(system)
    moved = read_derived_key(ctx.docs_path, f"{system_subpath().as_posix()}/{SYSTEM_FILE}") != key
    # THE FLOWS ACROSS THE SOURCES (#268 slice 3, ADR-0052 D19), observed from what this map, the
    # requirements and the published bundles say — the same refresh one step on, converging on a
    # key of their own, so a round where neither moved publishes nothing.
    flows, concepts = _observe_flows(ctx, found.repos, system, generated_at=now)
    flowed = _published_flows_key(ctx.docs_path) != flows.derived_key
    if not moved and not flowed:
        return UNCHANGED
    tmp = Path(tempfile.mkdtemp(prefix="openfactory-system-"))
    try:
        if moved:
            write_system(system, tmp / SYSTEM_DIRNAME)
        if flowed:
            write_flows(flows, concepts, tmp / FLOWS_DIRNAME)
        context_url = clone_url_for(project, project.product.docs_repo, token=token)
        bot = bot_identity()
        author = (bot.name or "openfactory-bot", bot.email or "openfactory-bot@local")
        try:
            with semaphore.held(project, timeout=timeout):
                outcomes = []
                if moved:
                    outcomes.append(publish_dir(
                        tmp / SYSTEM_DIRNAME, context_url, subpath=system_subpath(),
                        message=f"chore(okf): refresh the system layer @ {key}",
                        what=f"system layer @ {key}", author=author))
                if flowed:
                    outcomes.append(publish_dir(
                        tmp / FLOWS_DIRNAME, context_url, subpath=flows_subpath(),
                        message=f"chore(okf): refresh the flows across sources @ "
                                f"{flows.derived_key}",
                        what=f"flows @ {flows.derived_key}", author=author))
        except semaphore.Busy as exc:
            log.warning("system layer: %s — not published this round, the next refresh will",
                        exc)
            return BUSY
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if DIR_PUBLISHED in outcomes and all(o in (DIR_PUBLISHED, DIR_UNCHANGED) for o in outcomes):
        return PUBLISHED
    return UNCHANGED if all(o == DIR_UNCHANGED for o in outcomes) else FAILED


def flows_subpath() -> Path:
    """`.okf/flows` — the observed flows across the sources, beside `.okf/system/`."""
    from openfactory.knowledge.okf import OKF_DIRNAME

    return Path(OKF_DIRNAME) / FLOWS_DIRNAME


def _published_flows_key(docs: Path) -> str:
    published = read_flows(Path(docs) / flows_subpath())
    return published.derived_key if published is not None else ""


def _observe_flows(ctx, repos: list[str], system, *, generated_at: str):
    """The flows the requirements, `system` and the published bundles of `repos` show — read from
    the context repository the refresh just loaded, so the flows follow the bundles the knowledge
    refresh published a moment before."""
    from openfactory.knowledge.okf import OKF_INDEX_FILE
    from openfactory.product.sources import bundle_home

    bundles = {}
    for repo in repos:
        home = bundle_home(ctx.docs_path, repo)
        bundles[repo] = home if home is not None and (home / OKF_INDEX_FILE).is_file() else None
    corpus = getattr(ctx, "corpus", None)
    return observe(getattr(corpus, "requirements", None) or [], sources=list(repos),
                   bundles=bundles, system=system, generated_at=generated_at)


__all__ = ["BUSY", "FAILED", "NO_PRODUCT", "NO_SOURCES", "PUBLISHED", "UNCHANGED", "cache_key",
           "flows_subpath", "gather", "refresh_system", "system_subpath"]

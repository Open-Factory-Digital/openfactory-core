"""What mounting every source of a product costs the product role — time and disk, for the first
turn and for the next one (#268 slice 1, ADR-0052 D16: "measured, not assumed").

Two mechanisms side by side, through the real module, workspace and git:

  sparse   what the role mounts now — a partial clone per source, checked out through a cone that
           leaves out directories of pictures, fonts and archives (`SparseRepoCache`)
  whole    a whole clone of every source (`RepoCache`), placed the same way — what mounting N
           sources would cost without it

On the multi-repository fixture by default. On a real product with `--source name=url`, repeated,
the first one being the registry project's own: the context repository is made up to declare them,
and each is cloned from its URL (a private one needs the URL to carry its credential).

    .venv/bin/python tools/measure_the_mount.py
    .venv/bin/python tools/measure_the_mount.py --source front-end=https://github.com/o/front-end \\
        --source carts=https://github.com/o/carts

Disk is what the turn left under the repository cache — the clones, the placed worktrees and the
turn's own view — counted once per inode, in allocated blocks, the way `du` counts it. The
documentation checkout is made before the first turn and is not counted.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "evaluation" / "harbourline"
FIXTURE_REPOS = {"harbourline": "source",
                 "harbourline-pricing": "sources/harbourline-pricing",
                 "harbourline-tracking": "sources/harbourline-tracking",
                 "harbourline-web": "sources/harbourline-web"}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repository(src: Path | None, dest: Path) -> Path:
    """`src` (or nothing) as a git repository at `dest` that serves partial clones."""
    if src is not None:
        shutil.copytree(src, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q", "-b", "main")
    for key, value in (("user.name", "measure"), ("user.email", "measure@example.invalid"),
                       ("commit.gpgsign", "false"), ("uploadpack.allowFilter", "true"),
                       ("uploadpack.allowAnySHA1InWant", "true")):
        _git(dest, "config", key, value)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-qm", "measure", "--allow-empty")
    return dest


def disk(root: Path) -> int:
    """Allocated bytes under `root`, one count per inode — what `du` says."""
    seen: set[tuple[int, int]] = set()
    total = 0
    for where, _dirs, files in os.walk(root):
        for name in files:
            try:
                st = os.lstat(os.path.join(where, name))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            total += st.st_blocks * 512
    return total


def _product(work: Path, sources: list[tuple[str, str]] | None):
    """`(project, context repository, urls)` for the fixture or for the named sources."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    made = work / "repositories"
    if sources is None:
        repos = {n: _repository(FIXTURE / rel, made / n) for n, rel in FIXTURE_REPOS.items()}
        context = _repository(FIXTURE / "context", made / "context")
        urls = {n: f"file://{p}" for n, p in repos.items()}
        name, own = "harbourline", repos["harbourline"]
    else:
        urls = dict(sources)
        name = sources[0][0]
        context = made / "context"
        (context / ".openfactory").mkdir(parents=True)
        (context / ".openfactory" / "product.yaml").write_text(
            f"product: {name}\nsources:\n" + "".join(f"  - {n}\n" for n in urls))
        (context / "requirements").mkdir()
        _repository(None, context)
        own = _repository(None, made / "own")
    local = {"kind": "local", "repo": name, "options": {}}
    project = Project(name=name, repo_path=str(own), tracker=ProviderRef(**local),
                      forge=ProviderRef(**local), ci=ProviderRef(kind="none", repo=name,
                                                                 options={}),
                      product=ProductConfig(docs_repo=f"{name}-context"))
    return project, context, urls


class _Checkouts:
    """The loader's cache, answering the context repository's key with the made-up one."""

    def __init__(self, context: Path) -> None:
        from openfactory.runtime.repo_cache import RepoCache

        self._cache, self._context = RepoCache(), context

    def sync(self, key: str, clone_url: str, base_branch: str = ""):
        from openfactory.product.loader import DOCS_CACHE_SUFFIX

        return self._cache.sync(key, str(self._context) if key.endswith(DOCS_CACHE_SUFFIX)
                                else clone_url, base_branch)


def measure(mode: str, sources: list[tuple[str, str]] | None, turns: int) -> list[dict]:
    """Each turn's seconds and bytes, for one mechanism, in a directory of its own."""
    from openfactory.product import module as product_module
    from openfactory.product.loader import load_product_context
    from openfactory.product.sources import Checkout
    from openfactory.runtime.repo_cache import RepoCache

    work = Path(tempfile.mkdtemp(prefix=f"measure-{mode}-"))
    cache = work / "cache"
    os.environ.update({"OPENFACTORY_REPO_CACHE": str(cache), "OPENFACTORY_METRICS_SINK": "null",
                       "OPENFACTORY_BOARD_DB": str(work / "board.db"),
                       "OPENFACTORY_REGISTRY": str(work / "registry.yaml"),
                       "OPENFACTORY_LOG_DIR": str(work / "logs")})
    project, context, urls = _product(work, sources)
    module_type = product_module.ProductModule
    module_type._clone_url = lambda self, repo: urls[repo]
    product_module._the_read_model = lambda module, root: {}   # the read model is not the mount
    if mode == "whole":
        def whole(self, repo, spelling="", *, own=False):
            path = RepoCache().sync(self._source_key(repo), urls[repo], "")
            return Checkout(path=path) if path else Checkout(why="could not be cloned")
        module_type._source_checkout = whole
    ctx = load_product_context(project, cache=_Checkouts(context))
    rows = []
    try:
        for turn in range(1, turns + 1):
            before = disk(cache)
            module = module_type(project, context=ctx)
            began = time.monotonic()
            module._workspace()
            mounted = time.monotonic()
            held = module.mounts() or []
            checked = time.monotonic()
            rows.append({"turn": turn, "mount_s": mounted - began, "map_check_s": checked - mounted,
                         "added": disk(cache) - before, "cache": disk(cache),
                         "sources": sum(1 for m in held if m.path),
                         "missing": {m.repo: m.why for m in held if not m.path},
                         "left_out": {m.repo: m.left_out for m in held if m.left_out}})
            module.release()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return rows


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.2f} MB"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", action="append", default=[], metavar="NAME=URL")
    parser.add_argument("--turns", type=int, default=2)
    args = parser.parse_args(argv)
    sources = [tuple(s.split("=", 1)) for s in args.source] or None
    what = "the fixture `harbourline`" if sources is None else f"{len(sources)} repositories"
    print(f"# Mounting every source of {what}\n")
    print("| mechanism | turn | mount (s) | map check (s) | disk added | cache total | mounted |")
    print("|---|---|---|---|---|---|---|")
    for mode in ("sparse", "whole"):
        for row in measure(mode, sources, args.turns):
            print(f"| {mode} | {row['turn']} | {row['mount_s']:.2f} | {row['map_check_s']:.2f} | "
                  f"{_mb(row['added'])} | {_mb(row['cache'])} | {row['sources']} |")
            if row["missing"]:
                print(f"|  |  | missing: {row['missing']} | | | | |")
            if row["left_out"] and row["turn"] == 1:
                print(f"|  |  | left out: {row['left_out']} | | | | |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

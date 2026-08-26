"""One working directory holding the documentation repo AND every source repo of a product.

The product role reads two kinds of thing — what the product promises, and what the code does — and
for a brownfield project reading the code IS the work. But an agent runs in a single working
directory, and whether it may read a path outside that directory depends on the harness: Codex's
`-s read-only` is a sandbox POLICY that confines it, while Claude's tool allowlist does not. Handing
over an absolute path and hoping would produce a role that works on one engine and silently reads
nothing on another — the worst possible failure, because the answers keep arriving.

So both repositories are placed INSIDE one workspace:

    <workspace>/docs/          the documentation repo
    <workspace>/src/<name>/    one directory per source repo

Real files, not symlinks: a confined sandbox will not follow a link that leaves its root, so a
symlinked layout would reproduce exactly the failure this exists to avoid.

Built with `git worktree` from the checkouts `RepoCache` already keeps, so the object stores are
reused and adding a source costs a checkout rather than a clone. A worktree that cannot be created
is REPORTED, never fatal: a product question about requirements is still answerable when one source
repo is unreachable, and losing the whole answer over it would be a poor trade.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("openfactory.product")

_GIT_TIMEOUT = 300


@dataclass
class ProductWorkspace:
    """A composed working directory, and an honest account of what is in it."""

    path: Path
    docs: Path
    sources: dict[str, Path] = field(default_factory=dict)
    #: repos that could not be placed, with why — the agent is TOLD, so it can say "I could not
    #: read the front end" instead of concluding the front end does not do the thing
    missing: dict[str, str] = field(default_factory=dict)
    #: where each source worktree was created FROM. Kept because `git worktree remove` only works
    #: from inside the owning repository — running it from the workspace silently does nothing, and
    #: the cached repo then accumulates a stale entry per use until `prune` is the only way back.
    origins: dict[str, Path] = field(default_factory=dict)
    _owned: bool = True

    def release(self) -> None:
        if not self._owned:
            return
        for repo, dest in self.sources.items():
            origin = self.origins.get(repo)
            if origin is not None:
                _run(["git", "worktree", "remove", "--force", str(dest)], cwd=origin)
                _run(["git", "worktree", "prune"], cwd=origin)
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> ProductWorkspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    def layout(self) -> str:
        """What the agent is told about its own workspace. Written as prose because it goes into a
        prompt, and because the MISSING list matters as much as the present one."""
        lines = ["You are working in a directory that contains both the product's documentation "
                 "and its source code:", "", "- `docs/` — the requirements repository"]
        for name, path in sorted(self.sources.items()):
            lines.append(f"- `src/{path.name}/` — the source repository `{name}`")
        if self.missing:
            lines += ["", "NOT available in this workspace (say so rather than concluding anything "
                          "about them):"]
            lines += [f"- `{name}` — {why}" for name, why in sorted(self.missing.items())]
        return "\n".join(lines)


def _run(args: list[str], cwd: Path | None = None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=_GIT_TIMEOUT, check=False)


def _safe_name(repo: str) -> str:
    return repo.strip("/").split("/")[-1] or "repo"


def _already_at(dest: Path, want: str) -> bool:
    """Whether `dest` is already a usable worktree sitting on `want`.

    ASKED OF THE TREE, not remembered: this process is not the only thing that touches these paths
    (a deploy replaces the worker mid-conversation, another message rebuilt it a second ago), so
    anything held in memory about them is a belief and this is an observation. A `rev-parse` that
    fails for ANY reason answers False, which rebuilds — the expensive-but-correct direction, and
    the cheap one would serve an agent a tree it cannot vouch for.
    """
    if not dest.is_dir() or not (dest / ".git").exists():
        return False
    at = _run(["git", "rev-parse", "HEAD"], cwd=dest)
    return at.returncode == 0 and at.stdout.strip() == want


def compose(
    *,
    docs_checkout: str | Path,
    sources: dict[str, str | Path],
    root: str | Path | None = None,
) -> ProductWorkspace:
    """Build the composed workspace from checkouts that already exist.

    `sources` maps `owner/name` to the cached checkout of that repo. A source with no usable
    checkout is recorded in `missing` rather than omitted silently — an agent that is not told a
    repository is absent will happily conclude things about code it never saw.

    IDEMPOTENT AT A STABLE `root`, which is what makes it affordable on the conversational path.
    That path runs on EVERY client message, and a fresh worktree per message would be a checkout
    per message; reused, it is a `rev-parse` and nothing else on the overwhelmingly common turn
    where the cache has not moved. A worktree whose HEAD no longer matches the cache is rebuilt
    rather than served stale — an agent reading last week's code and citing the file is worse than
    one told it cannot read it at all.
    """
    base = Path(root) if root else Path(tempfile.mkdtemp(prefix="openfactory-product-"))
    base.mkdir(parents=True, exist_ok=True)
    (base / "src").mkdir(exist_ok=True)

    docs_src = Path(docs_checkout)
    docs_dest = base / "docs"
    missing: dict[str, str] = {}

    # The documentation repo is COPIED rather than worktree'd: it is small (markdown), and a copy
    # cannot be disturbed by the cache resetting underneath a long agent run — which is exactly what
    # `RepoCache` does to every checkout on its next use.
    if docs_src.is_dir():
        shutil.copytree(docs_src, docs_dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git"))
    else:
        docs_dest.mkdir(exist_ok=True)
        missing["documentation"] = f"the checkout at {docs_src} does not exist"

    placed: dict[str, Path] = {}
    origins: dict[str, Path] = {}
    for repo, checkout in sources.items():
        src = Path(checkout) if checkout else None
        dest = base / "src" / _safe_name(repo)
        if src is None or not (src / ".git").exists():
            missing[repo] = "no checkout was available"
            continue
        # a detached worktree at whatever the cache currently holds: the objects are already local,
        # so this costs a file write rather than a fetch
        head = _run(["git", "rev-parse", "HEAD"], cwd=src)
        if head.returncode != 0:
            missing[repo] = "the cached checkout has no HEAD (it is being rebuilt)"
            continue
        want = head.stdout.strip()
        if _already_at(dest, want):
            placed[repo] = dest
            origins[repo] = src
            continue        # the ordinary turn: nothing moved, so nothing is checked out again
        if dest.exists():
            # a worktree behind the cache, or a directory left by something else. Removed through
            # git where possible so the OWNING repo stops listing it — an rmtree alone leaves a
            # stale entry per rebuild until `prune` is the only way back.
            _run(["git", "worktree", "remove", "--force", str(dest)], cwd=src)
            shutil.rmtree(dest, ignore_errors=True)
            _run(["git", "worktree", "prune"], cwd=src)
        added = _run(["git", "worktree", "add", "--detach", str(dest), want], cwd=src)
        if added.returncode != 0:
            _run(["git", "worktree", "prune"], cwd=src)
            added = _run(["git", "worktree", "add", "--detach", str(dest), want], cwd=src)
        if added.returncode != 0:
            missing[repo] = f"could not be checked out ({added.stderr.strip()[:120]})"
            continue
        placed[repo] = dest
        origins[repo] = src

    return ProductWorkspace(path=base, docs=docs_dest, sources=placed, missing=missing,
                            origins=origins)

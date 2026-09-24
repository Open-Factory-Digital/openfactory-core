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

EVERY SOURCE THE PRODUCT DECLARES, READ-ONLY, AND NOTHING LEADING OUT (#268). A sparse cache is
worktree'd through its own cone; each placed source's files are made unwritable; and no symbolic
link that climbs out of its tree reaches the view — a repository can hold a link to anywhere.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
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


#: Git may not stop to ask anybody anything, and may not reach the network from inside the view's
#: lock: every object a worktree here needs is already in the cache it is made from, and a lazy
#: fetch under the lock would hold every other turn of the project behind one forge's latency.
_QUIET = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}


def _run(args: list[str], cwd: Path | None = None, stdin: str | None = None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, input=stdin,
                          timeout=_GIT_TIMEOUT, check=False, env={**os.environ, **_QUIET})


def _safe_name(repo: str) -> str:
    return repo.strip("/").split("/")[-1] or "repo"


def _placements(repos) -> dict[str, str]:
    """The directory each source gets under `src/`: its bare name, unless two sources of the
    product share one — `acme/web` and `partner/web` — and then each gets its whole coordinate,
    flattened (`acme--web`). A product of many repositories must never have one placed over
    another."""
    repos = list(repos)
    bare = [_safe_name(r) for r in repos]
    return {r: (b if bare.count(b) == 1 else r.strip("/").replace("/", "--") or "repo")
            for r, b in zip(repos, bare, strict=True)}


def escaping_links(root: str | Path) -> Callable[[str, list[str]], set[str]]:
    """A `copytree` `ignore` that leaves out every symbolic link a reader could follow OUT of
    `root`: an absolute one, wherever it points, and a relative one that climbs above it.

    A REPOSITORY CAN HOLD A LINK TO ANYWHERE. `link -> /etc/passwd` or `-> ../../../other-client`
    is one commit away for anybody who can write to a source or to the context repository, and the
    role opens what its view holds. So the view holds only links that stay inside the tree they
    came from; an absolute one never does once the tree is copied, even when it pointed inside."""
    base = os.path.realpath(root)

    def ignore(where: str, names: list[str]) -> set[str]:
        out: set[str] = set()
        for name in names:
            path = os.path.join(where, name)
            if not os.path.islink(path):
                continue
            target = os.readlink(path)
            landed = os.path.realpath(os.path.join(where, target))
            if os.path.isabs(target) or os.path.commonpath([base, landed]) != base:
                out.add(name)
        return out

    return ignore


def _without_escaping_links(tree: Path) -> None:
    """Every link in `tree` that `escaping_links` would leave out, removed from it."""
    ignore = escaping_links(tree)
    for where, dirs, files in os.walk(tree):
        for name in ignore(where, [*dirs, *files]):
            os.unlink(os.path.join(where, name))
        dirs[:] = [d for d in dirs if d != ".git" and not os.path.islink(os.path.join(where, d))]


def _read_only(tree: Path) -> None:
    """Every file of a placed source made unwritable — the mount is read-only by the file's mode,
    not only by what the harness allows (#268: a source is mounted read-only).

    ON THE WORKTREE, ONCE PER CHECKOUT, and every turn's view inherits it: a view's file is a hard
    link to this one, and a mode belongs to the file, not to the name. A write through one turn's
    view would otherwise change the cached worktree and every other turn's view with it."""
    for where, dirs, files in os.walk(tree):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = os.path.join(where, name)
            if os.path.islink(path) or name == ".git":
                continue
            try:
                mode = os.stat(path).st_mode
                os.chmod(path, mode & ~0o222)
            except OSError:
                continue


def _cone_of(src: Path) -> list[str] | None:
    """The cone `src` is checked out through, or None when it is not sparse — so a worktree made
    from it is checked out through the same one, whatever git version made it."""
    on = _run(["git", "config", "--bool", "core.sparseCheckout"], cwd=src)
    if on.returncode != 0 or on.stdout.strip() != "true":
        return None
    listed = _run(["git", "sparse-checkout", "list"], cwd=src)
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def _add_worktree(src: Path, dest: Path, want: str):
    """`dest` as a worktree of `src` at `want` — through `src`'s cone when `src` is sparse, so a
    directory the cache left out is not materialised here either (and not fetched for)."""
    cone = _cone_of(src)
    if cone is None:
        return _run(["git", "worktree", "add", "--detach", str(dest), want], cwd=src)
    added = _run(["git", "worktree", "add", "--no-checkout", "--detach", str(dest), want],
                 cwd=src)
    if added.returncode != 0:
        return added
    for args, stdin in ((["git", "sparse-checkout", "set", "--cone", "--stdin"],
                         "".join(f"{d}\n" for d in cone)),
                        (["git", "reset", "-q", "--hard", want], None)):
        done = _run(args, cwd=dest, stdin=stdin)
        if done.returncode != 0:
            return done
    return added


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
    #
    # ITS LINKS STAY LINKS, AND ONLY THE ONES THAT STAY INSIDE IT. `copytree` follows a link by
    # default and copies what it points at, so `docs/x -> /` in the context repository copied the
    # machine into the view; now a link is copied as a link, and one leaving the tree is not.
    #
    # AND THE COPY IS MADE BESIDE AND SWAPPED IN, not poured over the last one: a link cannot be
    # written over an existing name, and a pour never removes what the repository deleted — a
    # requirement file removed upstream stayed in the view for ever.
    for leftover in base.glob(".docs-*"):     # a copy a crash left half made
        shutil.rmtree(leftover, ignore_errors=True)
    if docs_src.is_dir():
        fresh = base / f".docs-{uuid.uuid4().hex[:8]}"
        shutil.copytree(docs_src, fresh, symlinks=True, ignore=_inside(docs_src))
        if docs_dest.exists():
            old = base / f".docs-old-{uuid.uuid4().hex[:8]}"
            os.rename(docs_dest, old)
            os.rename(fresh, docs_dest)
            shutil.rmtree(old, ignore_errors=True)
        else:
            os.rename(fresh, docs_dest)
    else:
        docs_dest.mkdir(exist_ok=True)
        missing["documentation"] = f"the checkout at {docs_src} does not exist"

    placed: dict[str, Path] = {}
    origins: dict[str, Path] = {}
    names = _placements(sources)
    # A SOURCE THE PRODUCT NO LONGER DECLARES LEAVES THE VIEW. Its worktree would otherwise stay
    # under `src/` for ever, and a turn that falls back to reading this shared root would read a
    # repository outside the product's `sources:` (#268).
    for stale in sorted((base / "src").iterdir()):
        if stale.name in names.values():
            continue
        if stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)
    for repo, checkout in sources.items():
        src = Path(checkout) if checkout else None
        dest = base / "src" / names[repo]
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
        added = _add_worktree(src, dest, want)
        if added.returncode != 0:
            _run(["git", "worktree", "remove", "--force", str(dest)], cwd=src)
            shutil.rmtree(dest, ignore_errors=True)
            _run(["git", "worktree", "prune"], cwd=src)
            added = _add_worktree(src, dest, want)
        if added.returncode != 0:
            missing[repo] = f"could not be checked out ({added.stderr.strip()[:120]})"
            continue
        # once per checkout, never per turn: what a view links from holds no way out of its tree
        # and no file a reader may write
        _without_escaping_links(dest)
        _read_only(dest)
        placed[repo] = dest
        origins[repo] = src

    return ProductWorkspace(path=base, docs=docs_dest, sources=placed, missing=missing,
                            origins=origins)


# ── one turn's own view (#266 slice 2, ADR-0051 D11) ────────────────────────────────────────────

#: What names a turn's view, and the parent it lives under — the IDENTITY a later removal checks
#: before it deletes anything (`util/scratch.py`'s rule: a directory we may delete says so in its
#: name, and nothing else is deletable here).
TURN_PREFIX = "turn-"
TURNS_SUFFIX = "-turns"

#: How long a turn's view may outlive its turn before anything may remove it — the backstop for a
#: caller that never released one (a sweep, an activity that is not a turn). Twelve times the
#: longest bound a product activity runs under (ten minutes), so no view is ever removed from under
#: a turn still reading it.
TURN_VIEW_TTL_SECONDS = 2 * 60 * 60


def turn_view(into: str | Path, *, docs: str | Path,
              sources: dict[str, Path] | None = None) -> Path:
    """A directory of THIS TURN'S OWN, holding what the role may read — removed by
    `release_turn_view` when the turn ends.

    WHY A TURN NEEDS ONE. The composed view is rebuilt IN PLACE at a stable root, which is what
    makes it affordable on every message — and that was safe only while one turn ran at a time.
    With conversations in parallel (ADR-0051 D3) one turn's compose copied the documentation over
    the files another turn's agent was reading, replaced a source worktree the cache had moved past
    under it, and cleared its facts pack (`facts.write_facts` removes the previous one first). So
    the stable root stays the CACHE and no agent reads it; each turn reads a view of its own.

    AND IT COSTS NO CHECKOUT, which is the property the stable root was built for: the
    documentation is copied (it is small, and `compose` overwrites its copy in place, so a link
    would change under the turn), while every source file is a HARD LINK to the cached worktree's.
    A checkout replaces a file by unlinking it and writing a new one — never by rewriting it in
    place — so a rebuild of the cache leaves every link this view holds exactly as it was. Where a
    link cannot be made (another filesystem) the file is copied instead.

    `sources` maps each repository to its cached worktree; with none, the view is the
    documentation alone, laid at the view's root — the degraded shape `ProductModule.mounted`
    already describes as `docs: "."`. Stale views of earlier turns are swept on the way in.

    NOTHING IN IT LEADS OUT OF IT (#268). A source's `.git` is a file naming the cache's own git
    directory — a pointer out of the view, and the way a read would reach the cache's objects — so
    it stays behind: the role reads files, not history. And no symbolic link that climbs out of the
    tree it came from is copied (`escaping_links`)."""
    base = Path(into)
    base.mkdir(parents=True, exist_ok=True)
    _sweep_turn_views(base)
    dest = base / f"{TURN_PREFIX}{uuid.uuid4().hex[:16]}"
    try:
        if sources is None:
            shutil.copytree(docs, dest, symlinks=True, ignore=_inside(docs))
            return dest
        dest.mkdir()
        shutil.copytree(docs, dest / "docs", symlinks=True, ignore=_inside(docs))
        (dest / "src").mkdir()
        for checkout in sources.values():
            src = Path(checkout)
            shutil.copytree(src, dest / "src" / src.name, symlinks=True, ignore=_inside(src),
                            copy_function=_link_or_copy)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


def _inside(tree) -> Callable[[str, list[str]], set[str]]:
    """The `ignore` of a view's copy: `.git`, and every link out of `tree`."""
    outside = escaping_links(tree)
    return lambda where, names: outside(where, names) | ({".git"} & set(names))


def _link_or_copy(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def is_turn_view(path: str | Path) -> bool:
    """Whether `path` is a view `turn_view` made — by its name and its parent's, never by where it
    happens to be."""
    p = Path(path)
    return p.name.startswith(TURN_PREFIX) and p.parent.name.endswith(TURNS_SUFFIX)


def release_turn_view(path: str | Path | None) -> bool:
    """Remove one turn's view. REFUSES anything `turn_view` did not make, loudly and without
    raising — this runs in a `finally`, where an exception would replace an answer."""
    if path is None:
        return False
    if not is_turn_view(path):
        log.error("refusing to remove %s — not a turn's view of the product", path)
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def _sweep_turn_views(base: Path) -> None:
    """Views older than `TURN_VIEW_TTL_SECONDS`, removed — what bounds the directory when a caller
    never released its view. Best-effort: a view that cannot be removed costs disk, not a turn."""
    cutoff = time.time() - TURN_VIEW_TTL_SECONDS
    try:
        stale = [p for p in base.iterdir()
                 if p.name.startswith(TURN_PREFIX) and p.stat().st_mtime < cutoff]
    except OSError:
        return
    for view in stale:
        shutil.rmtree(view, ignore_errors=True)

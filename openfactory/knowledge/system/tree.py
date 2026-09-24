"""A source's files, read the only way the system layer reads anything: inside the tree, as text.

THE LAYER RUNS NOTHING FROM A REPOSITORY. It opens files and parses their text — YAML through the
safe loader, JSON, Python through `ast.parse` (which builds a tree and executes nothing), and the
rest through patterns. No build, no `docker compose config`, no `helm template`, no `terraform
plan`, no import of a migration: each of those runs the client's code or the client's tool, and
a repository is not a thing this platform executes to describe it. (The preview reader,
`preview/read.py` on #265, runs the pinned compose CLI because a preview must run the stack; the
map must not, so it reads the text and says what the text alone cannot tell.) This module does not
import `subprocess`, and a test holds that nothing it reaches starts a process.

NO READ LEAVES THE TREE. The walk never follows a link — a link to a file or a directory out of the
tree is NAMED, as not followed, and never opened; a link inside the tree is skipped, because what
it points at is walked at its own path. Every read checks the real path against the real root and
opens with `O_NOFOLLOW`, so a path handed in from elsewhere (a `$ref`, an `import`) cannot escape
through a link either. A FIFO or a device is not a file and is never opened: opening a FIFO blocks.

BOUNDED. A file past `READ_CEILING` is not read and is said to be too large; a walk past
`MAX_FILES` stops and says so. A repository is somebody else's input, and the one reading it
decides how much it will read.
"""

from __future__ import annotations

import os
import posixpath
import stat
from dataclasses import dataclass, field
from pathlib import Path

#: Bytes of one file the layer reads. A declaration is small; a megabyte of OpenAPI is already a
#: generated artefact, and the same ceiling the inventory reads to (`inventory.READ_CEILING`).
READ_CEILING = 1_000_000
#: Files one walk lists before it stops and says so.
MAX_FILES = 100_000

#: Directories never walked. What someone else wrote (dependencies, vendored code), what a build
#: wrote (its output), what a tool keeps for itself — and tests and examples, whose OpenAPI files
#: and compose files describe a fixture, not the product. Said once in the map's scope statement
#: rather than once per directory (`render.SCOPE_LIMIT`).
PRUNED = frozenset({
    ".git", ".hg", ".svn", ".okf",
    "node_modules", "vendor", "vendors", "third_party", "third-party", "bower_components",
    "jspm_packages", ".venv", "venv", "__pycache__", ".terraform", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".gradle", ".idea", ".vscode",
    "dist", "build", "target",
    "test", "tests", "__tests__", "testdata", "test-data", "fixtures", "__fixtures__", "e2e",
    "examples", "example", "samples", "sample",
})


@dataclass(frozen=True)
class SourceTree:
    """One declared source, as the caller checked it out: its name, its root, its commit.

    The COMMIT is handed in, never asked of git here: asking would run a process in the
    repository, and the derivation is a pure function of the files."""

    repo: str
    root: Path
    commit: str = ""

    @property
    def leaf(self) -> str:
        """The repository's own name, without its owner: `acme/orders` → `orders`."""
        return self.repo.strip("/").rsplit("/", 1)[-1]


@dataclass
class Walked:
    """What one walk found — the files, and what it did not open, with where."""

    files: list[str] = field(default_factory=list)
    #: links, to a file or a directory, that resolve outside the tree — never opened
    links_out: list[str] = field(default_factory=list)
    #: directories the walk could not open
    unreadable: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class Read:
    """A file's text, or why there is none. `why` is a clause: "is a link, …"."""

    text: str | None
    why: str = ""
    #: `too-large` when that is the reason; the caller files everything else by what it asked
    too_large: bool = False


def inside(real_root: str, real: str) -> bool:
    """Whether a REAL path is the root or under it."""
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def walk(root: str | Path) -> Walked:
    """Every regular file under `root`, repository-relative with `/`, sorted — never through a link.

    `os.walk(followlinks=False)` lists a linked directory without descending into it; this goes
    one step further and never lists a linked FILE either, and names every link whose target is
    out of the tree."""
    real_root = os.path.realpath(str(root))
    out = Walked()

    def rel(path: str) -> str:
        return os.path.relpath(path, real_root).replace(os.sep, "/")

    def on_error(error: OSError) -> None:
        out.unreadable.append(rel(getattr(error, "filename", "") or real_root))

    for dirpath, dirnames, filenames in os.walk(real_root, onerror=on_error, followlinks=False):
        keep = []
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                if not inside(real_root, os.path.realpath(full)):
                    out.links_out.append(rel(full))
                continue
            if name.lower() in PRUNED:
                continue
            keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            try:
                mode = os.lstat(full).st_mode
            except OSError:
                out.unreadable.append(rel(full))
                continue
            if stat.S_ISLNK(mode):
                if not inside(real_root, os.path.realpath(full)):
                    out.links_out.append(rel(full))
                continue
            if not stat.S_ISREG(mode):
                continue
            if len(out.files) >= MAX_FILES:
                out.truncated = True
                break
            out.files.append(rel(full))
        if out.truncated:
            break
    out.files.sort()
    out.links_out.sort()
    out.unreadable.sort()
    return out


def read_text(root: str | Path, rel: str) -> Read:
    """The UTF-8 text of `rel` under `root`, or why it is not read.

    Refused: a path that is absolute or climbs out, a link, anything whose real path leaves the
    root, anything that is not a regular file, a file past `READ_CEILING`, bytes that are not
    UTF-8. Opened with `O_NOFOLLOW | O_NONBLOCK`, so a file swapped for a link or a FIFO after the
    check is refused by the kernel rather than followed or waited on."""
    if "\x00" in rel:
        return Read(None, "is not a path (it holds a NUL byte)")
    real_root = os.path.realpath(str(root))
    norm = posixpath.normpath(rel)
    if norm.startswith("/") or norm == ".." or norm.startswith("../"):
        return Read(None, "is outside the repository's tree")
    full = os.path.join(real_root, *norm.split("/"))
    try:
        st = os.lstat(full)
    except OSError as exc:
        return Read(None, f"could not be opened ({exc.strerror or exc})")
    if stat.S_ISLNK(st.st_mode):
        return Read(None, "is a link, and a link is never followed")
    if not inside(real_root, os.path.realpath(full)):
        return Read(None, "is outside the repository's tree")
    if not stat.S_ISREG(st.st_mode):
        return Read(None, "is not a regular file")
    if st.st_size > READ_CEILING:
        return Read(None, f"is {st.st_size} bytes, over the {READ_CEILING}-byte ceiling this "
                          f"layer reads", too_large=True)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(full, flags)
    except OSError as exc:
        return Read(None, f"could not be opened ({exc.strerror or exc})")
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return Read(None, "is not a regular file")
        data = fh.read(READ_CEILING + 1)
    if len(data) > READ_CEILING:
        return Read(None, f"is over the {READ_CEILING}-byte ceiling this layer reads",
                    too_large=True)
    try:
        return Read(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return Read(None, "is not UTF-8 text")


def resolve(from_rel: str, target: str) -> str | None:
    """`target`, named inside the file at `from_rel`, as a repository-relative path — or None when
    it cannot be one: absolute, home-rooted, a URL, or climbing out of the tree. Whether it EXISTS,
    and whether a link takes it out, is `read_text`'s question."""
    t = (target or "").strip()
    if not t or t.startswith(("/", "~", "\\")) or "://" in t or "$" in t or "\x00" in t:
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), t))
    if joined == ".." or joined.startswith("../") or joined.startswith("/"):
        return None
    return joined


__all__ = ["MAX_FILES", "PRUNED", "READ_CEILING", "Read", "SourceTree", "Walked", "inside",
           "read_text", "resolve", "walk"]

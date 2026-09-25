"""The DEPLOYMENT's own guidelines — one home for an organisation's central standards (#318).

WHY THIS EXISTS. An organisation whose engineering standards are owned centrally used to reach
them by listing ABSOLUTE paths in every project's `docs.guidelines`. That worked only because
`build_context` did `repo_path / g` and pathlib discards the left operand when `g` is absolute —
the very escape `_inside()`'s docstring names and contains for profile paths. The day that hole is
closed, every such job runs without the organisation's standards and NOTHING fails: the agent
simply knows less. This gives those standards a first-class, deployment-level home instead.

WHO MAY SET IT. `OPENFACTORY_GUIDELINES_DIR` is an OPERATOR setting, read from the process
environment and nowhere else — never from a target repository's manifest and never from an add-on
package. That is the supply-chain reason `plugins.py` gives for built-ins winning a collision: a
value a project or a stranger's wheel could set would let untrusted content decide what every job
on the deployment reads. The environment belongs to whoever runs the stack.

THE THREE TIERS THIS FEEDS, and where each lands relative to the rest of the cascade:

    openfactory/org_defaults/*.md          the FRAMEWORK baseline            first
    $OPENFACTORY_GUIDELINES_DIR/*.md       the OPERATOR's own guidelines     after the baseline
    <checkout> docs.guidelines             the PROJECT's own house rules     last (keeps the word)

`reference/*.md` under the directory is a fourth thing: it does not inline, it INDEXES — a
table-of-contents entry that feeds `doc_index` on the same terms as `docs.architecture`, so a long
central document is read on demand instead of shipped in full on every job.

CONTAINMENT IS THE SAME CHECK `_inside()` APPLIES. Every path is resolved and must stay under the
configured directory; a symlink that leads out of it is ignored with a warning naming the file.
The reason is identical: these files are read into the agent's prompt, so a link to
`/etc/passwd` under the directory would put whatever it found in front of the model.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openfactory.policy.profiles import ResolvedProfile

_log = logging.getLogger("openfactory.orchestrator.operator_guidelines")

#: The one OPERATOR setting that names the directory. Read from the environment ONLY — see the
#: module docstring for why a project or an add-on may not set it.
ENV_VAR = "OPENFACTORY_GUIDELINES_DIR"

#: The subdirectory whose documents are INDEXED (read on demand) rather than inlined on every job.
REFERENCE_SUBDIR = "reference"


def configured_dir(env: dict[str, str] | None = None) -> Path | None:
    """The directory the operator named, or None when the setting is unset or blank.

    `env` is injectable so a test can exercise the branch without touching the process
    environment; production reads `os.environ`."""
    raw = ((env if env is not None else os.environ).get(ENV_VAR) or "").strip()
    return Path(raw).expanduser() if raw else None


def _contained(root: Path, path: Path) -> Path | None:
    """`path`, resolved, when it stays under `root` — else None with a warning naming the file.

    The same containment `orchestrator/context.py::_inside` applies to profile paths, rooted at the
    operator directory instead of the checkout: these files are read into the agent's prompt, so a
    symlink leading out of the directory would put whatever it points at in front of the model."""
    try:
        root_r = root.resolve()
        cand = path.resolve()
    except OSError:
        _log.warning("operator guideline %s could not be resolved — ignored.", path)
        return None
    if cand == root_r or not cand.is_relative_to(root_r):
        _log.warning(
            "operator guideline %s resolves outside %s — ignored. These files are read into the "
            "agent's prompt, so they stay inside the configured directory.", path, root)
        return None
    return cand


def _contained_md(root: Path, files: list[Path]) -> list[Path]:
    """The `.md` files among `files` that resolve inside `root`, sorted, containment applied."""
    kept = []
    for p in sorted(files):
        if p.is_file() and p.suffix == ".md" and _contained(root, p) is not None:
            kept.append(p)
    return kept


def _reference_md(root: Path, ref_root: Path) -> list[Path]:
    """The `.md` under `reference/`, contained, walked WITHOUT trusting a symlink to keep the walk
    inside `root`.

    `os.walk(followlinks=False)` never descends a link, so the walk cannot be steered out of the
    directory (or into a cycle) by a subdirectory symlink — and it does not depend on `rglob`'s
    symlink-following, which changed across Python versions (`**` followed links before 3.13 and
    does not after). A linked subdirectory whose target escapes is named in a warning ONCE, the
    same containment posture `_contained` gives a linked file, so the AC's "a symlink leading out
    of it is ignored with a warning naming the file" holds for a whole subtree too."""
    kept: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ref_root, followlinks=False):
        here = Path(dirpath)
        for name in dirnames:
            sub = here / name
            if sub.is_symlink():
                _contained(root, sub)  # warns and names it when the target escapes
        kept.extend(_contained_md(root, [here / f for f in filenames if f.endswith(".md")]))
    return sorted(kept)


@dataclass
class OperatorTier:
    """What the operator directory contributes to a job, already contained.

    `configured` is the setting being present at all; `dir_exists` is that directory being on
    disk. The two are separate because a MISSING directory and an EMPTY one warn differently, and
    both differ from the setting simply being unset (the ordinary case, which contributes nothing
    and says nothing)."""

    configured: bool = False
    dir: Path | None = None
    dir_exists: bool = False
    #: `*.md` directly in the directory — inlined into `guidelines` after the framework baseline.
    guideline_docs: list[Path] = field(default_factory=list)
    #: `*.md` under `reference/` — INDEXED into `doc_index`, read on demand, never inlined.
    reference_docs: list[Path] = field(default_factory=list)
    #: a short git marker when the directory is a checkout, else None — so a reader of the change
    #: can see WHICH revision of the central standards applied.
    version: str | None = None

    @property
    def empty(self) -> bool:
        """Configured, present on disk, and yielding no usable `.md` in either tier — the shape
        that WARNS the way `docs.constraints` does when its glob matches nothing."""
        return (self.configured and self.dir_exists
                and not self.guideline_docs and not self.reference_docs)

    @property
    def missing(self) -> bool:
        """Configured, and the named directory is not on disk."""
        return self.configured and not self.dir_exists


def gather(env: dict[str, str] | None = None) -> OperatorTier:
    """Read the operator directory into an `OperatorTier`, containment applied, nothing warned.

    Deliberately SILENT about missing/empty: this is called from more than one place per job
    (`build_context` on every pass, plus the journal note), and the warning belongs where
    `docs.constraints`' equivalent lives — once, at the caller that assembles the context — not
    doubled by every reader. The tier carries `missing`/`empty` so the caller decides."""
    root = configured_dir(env)
    if root is None:
        return OperatorTier(configured=False)
    if not root.is_dir():
        return OperatorTier(configured=True, dir=root, dir_exists=False)

    guideline_docs = _contained_md(root, list(root.glob("*.md")))
    ref_root = root / REFERENCE_SUBDIR
    reference_docs = _reference_md(root, ref_root) if ref_root.is_dir() else []
    return OperatorTier(
        configured=True, dir=root, dir_exists=True,
        guideline_docs=guideline_docs, reference_docs=reference_docs,
        version=_git_version(root))


#: How many characters of the commit sha name the revision — git's own default `--short` length
#: for a small repository, so the marker reads like the `git rev-parse --short HEAD` a person types.
_SHORT_SHA = 7


def _git_version(root: Path) -> str | None:
    """A short commit marker when `root` is a git checkout, else None.

    A STAMP, NEVER A GATE — the same posture `knowledge/pipeline.py::_head_commit` takes: a
    directory that is not a checkout (a plain mount, an unpacked tarball) still contributes its
    guidelines; it just has no revision to name.

    READ FROM `.git`, NEVER SHELLED OUT. `root` is an OPERATOR-configured directory, and running
    `git` inside a directory named from outside would execute whatever that repository's
    `.git/config` chose to — aliases, `core.fsmonitor`, `core.pager` — an external-execution
    surface a stamp does not need. `onboarding/infer.py` already reads `.git/HEAD` as text for the
    same reason; this resolves the one ref the same way. Any surprise in the layout (a missing
    file, an unreadable one, an unexpected shape) yields None — the guidelines still apply."""
    try:
        return _resolve_head(root)
    except OSError as exc:
        _log.info("operator guidelines: could not read the revision of %s (%s) — the guidelines "
                  "still apply, they just carry no version marker.", root, exc)
        return None


def _git_dir(root: Path) -> Path | None:
    """`root/.git`, following the one-line `gitdir:` pointer a worktree leaves behind — this
    platform runs jobs in worktrees, so `.git` being a FILE is not exotic here."""
    dot = root / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        for line in dot.read_text().splitlines():
            if line.startswith("gitdir:"):
                target = Path(line.split(":", 1)[1].strip())
                return target if target.is_absolute() else (root / target)
    return None


def _common_dir(git_dir: Path) -> Path:
    """A worktree's own gitdir holds its HEAD but shares refs through a `commondir` pointer; loose
    refs and `packed-refs` live there, not in the worktree's gitdir."""
    commondir = git_dir / "commondir"
    if commondir.is_file():
        target = Path(commondir.read_text().strip())
        return target if target.is_absolute() else (git_dir / target)
    return git_dir


def _resolve_head(root: Path) -> str | None:
    git_dir = _git_dir(root)
    if git_dir is None or not git_dir.is_dir():
        return None
    head = (git_dir / "HEAD").read_text().strip()
    if not head.startswith("ref:"):
        # Detached HEAD — the file holds the sha itself.
        return head[:_SHORT_SHA] or None
    ref = head.split(":", 1)[1].strip()
    common = _common_dir(git_dir)
    sha = _read_ref(common, ref) or _read_ref(git_dir, ref)
    return sha[:_SHORT_SHA] if sha else None


def _read_ref(git_dir: Path, ref: str) -> str | None:
    """The sha a ref points at — the loose ref file, or its `packed-refs` line when a checkout that
    has run `git gc` keeps its refs packed rather than as loose files."""
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text().strip() or None
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "^")):
                continue
            sha, _, name = line.partition(" ")
            if name == ref:
                return sha or None
    return None


def reference_label(root: Path, doc: Path) -> str:
    """How a reference document is named in `doc_index` — its path relative to the operator
    directory, so the entry reads the way `docs.architecture`'s repo-relative entries do."""
    try:
        return str(doc.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return doc.name


def applied_note(profile: ResolvedProfile | None = None,
                 env: dict[str, str] | None = None) -> str | None:
    """A one-line summary of the operator guideline set that APPLIED, for the journal (#318).

    NAMED WHERE A READER OF THE CHANGE CAN SEE IT, with a version marker when the directory is a
    git checkout — so which revision of the central standards shaped a job is a fact a reader is
    told, not one they infer. `None` when nothing is configured, or when the directory is
    missing/empty (the warning and the doctor line already speak to that, and nothing applied)."""
    tier = gather(env)
    if not tier.configured or tier.missing or tier.empty or tier.dir is None:
        return None
    waived = set(profile.waived_guidelines()) if profile is not None else set()
    applied = [p.name for p in tier.guideline_docs if p.name not in waived]
    dropped = sorted(p.name for p in tier.guideline_docs if p.name in waived)
    refs = [reference_label(tier.dir, p) for p in tier.reference_docs]
    ver = f" @ {tier.version}" if tier.version else ""
    line = (f"operator guidelines ({tier.dir}{ver}): "
            f"{', '.join(applied) if applied else 'none'}")
    if dropped:
        line += f"; waived by profile: {', '.join(dropped)}"
    if refs:
        line += f"; reference (read on demand): {', '.join(refs)}"
    return line

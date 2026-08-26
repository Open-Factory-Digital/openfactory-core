"""RepoCache — the worker's per-project read-only checkout (ADR-0013 D6).

The long-lived worker keeps ONE cached clone per project for cheap read-only work (the
pre-flight sizing gate's code layer). Clone on first touch; per use `fetch` + `reset --hard
origin/<base>` + `clean -fdx` — reset, never pull: a cache must be IDENTICAL to base, not
merged into. A corrupt cache is deleted and recloned; a reclone failure returns None so the
caller degrades (text-only gate) instead of blocking. The executor's fresh isolated clone in
Fargate is untouched — this cache is only ever read.

THE SERVED TREE IS NEVER MUTATED IN PLACE. The per-key lock covers sync-vs-sync, but a READER
(the baseline survey, a conversational agent behind the view symlink) holds the returned path for
minutes, and callers have no way to say "still reading". Resetting or recloning the served path
under such a reader handed it a torn half-old/half-new tree — a survey describing code that never
existed in any commit — or vanishing files mid-`rmtree`. So all git mutation happens on a hidden
MASTER checkout, and the path callers receive is a hardlink snapshot of it, republished by atomic
rename only when the master's commit moved (or the snapshot was dirtied/corrupted). A displaced
snapshot is parked for a grace period before deletion, so a reader that anchored itself (open fd,
cwd) keeps a complete, self-consistent tree for the whole window; a reader resolving by name flips
between complete trees, never through a mid-mutation state.

THE CREDENTIAL NEVER RESTS IN THE CHECKOUT. `git clone <url-with-token>` persists that URL in
`.git/config`, and agents DO run over this cache — the pre-flight sizer explores it. A sizer reads
ticket text, which anyone able to file an issue can write, so a ticket instructing it to read
`.git/config` and repeat what it finds would exfiltrate a live App token into a public comment. So
`origin` is rewritten to the tokenless URL immediately after cloning, and every later fetch passes
the credentialed URL as an argument instead — which git does not persist. (The Slack bot already
scrubbed for exactly this reason; the cache had not.) Snapshots hardlink the master's config, so
they inherit the scrubbed remote.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

#: WARNINGS, NOT `print`. These two lines are the cache degrading, and they used to go to
#: stdout — so they landed ABOVE `openfactory doctor`'s table, in the middle of a command
#: whose whole contract is one line per check with its remedy, and no logger setting could
#: quiet them (pilot, 2026-08-14). Through logging they stay visible in the worker (an
#: unconfigured logger still prints WARNING to stderr) and obey the diagnostic that owns
#: the screen.
log = logging.getLogger("openfactory.repo_cache")

#: Where checkouts live. `/tmp` was the original and it is the wrong default for a container: the
#: tree is lost on every restart, so a deploy costs a full re-clone of every client repository.
#: `OPENFACTORY_REPO_CACHE` lets a deployment put it on the volume that survives, beside the
#: registry.
#: Where checkouts live when a caller does not say. READ AT CALL TIME, never frozen at import
#: (#185) — this module-level `Path(os.environ.get(...))` was evaluated once, when the module was
#: first imported, so a deployment that sets `OPENFACTORY_REPO_CACHE` after that point silently
#: got the default. It is the shape `box_prove.PROOF_DIR` is filed under in #163's notes, and
#: this codebase names it a defect in its own words.
#:
#: MEASURED COST, and it is not hypothetical config hygiene. Every caller that constructs
#: `RepoCache()` without a root shares ONE directory, so a parallel test run has several workers
#: syncing different repositories into the same tree, swapping it under each other. The failure
#: surfaces as `pre-flight did not size (clone: could not reach the repo…) — proceeding UNSIZED`
#: in whichever test lost the race, which is indistinguishable from the live #37 bug the offline
#: harness exists to catch. It cost most of a day of intermittency wearing two different masks.
_FALLBACK_ROOT = "/tmp/openfactory-repo-cache"


def default_root() -> Path:
    """The cache root this process should use, asked now rather than at import."""
    return Path(os.environ.get("OPENFACTORY_REPO_CACHE") or _FALLBACK_ROOT)
_GIT_TIMEOUT = 300

#: How long a displaced snapshot stays on disk after being swapped out. This is the window a
#: reader has to finish with a tree it was handed before a newer sync replaced it. Longer than
#: any survey the product role runs; short enough that the parked trees (hardlinks — metadata,
#: not content) never pile up. Bounded by upstream commit rate times this window.
_TRASH_GRACE_SECONDS = 30 * 60

_MASTERS_DIRNAME = ".masters"
_STAGING_DIRNAME = ".staging"
_TRASH_DIRNAME = ".trash"

# One lock per project: the poller may overlap ticks; two concurrent fetch/reset runs on the
# same checkout corrupt it. Process-local is enough — one worker process owns the cache dir.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def _scrub(text: str) -> str:
    """A token must never reach a log line — the whole point of an error string is to be pasted
    somewhere."""
    return re.sub(r"(https://)[^@/\s]+@", r"\1***@", text or "")


def _scrub_remote(path: Path, clone_url: str) -> None:
    """Rewrite `origin` to the tokenless URL. Idempotent and best-effort: failing to scrub leaves a
    short-lived repo-scoped token on the worker's disk, which is bad, but failing the sync over it
    would take the sizing gate down, which is worse."""
    public = re.sub(r"(https://)[^@/\s]+@", r"\1", clone_url or "")
    if public and public != clone_url:
        _git(["remote", "set-url", "origin", public], cwd=path)


def _git(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       timeout=_GIT_TIMEOUT)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _head(path: Path) -> str:
    rc, out = _git(["rev-parse", "HEAD"], cwd=path)
    return out.strip() if rc == 0 else ""


def _worktree_dirty(path: Path) -> bool:
    rc, out = _git(["status", "--porcelain"], cwd=path)
    return rc != 0 or bool(out.strip())


def remote_default_branch(clone_url: str) -> str:
    """Which branch the REMOTE points HEAD at, or `""` — asked without cloning anything.

    `git ls-remote --symref <url> HEAD` transfers no objects: it is a ref advertisement, so this
    costs a round trip and nothing else. That matters because it runs on the hot path — the
    preflight asks per ticket.

    IT EXISTS BECAUSE THE CACHE IS NOT THE REPOSITORY. `sync("")` used to resolve "nobody said"
    against the EXISTING checkout, so the promise its callers were written against — "let the
    clone land where the repository points" — held only on the very first clone. Afterwards a
    long-lived worker pinned whatever it had happened to land on, and a client who moved their
    default from `main` to `develop` was served the abandoned branch for ever, silently, with the
    tree looking perfectly healthy. Found by adversarial review, 2026-08-20.

    `""` ON ANY TROUBLE, and the caller falls back to what it already has: an unreachable remote
    must not be the reason a working checkout is thrown away.
    """
    rc, out = _git(["ls-remote", "--symref", clone_url, "HEAD"])
    if rc != 0:
        return ""
    for line in (out or "").splitlines():
        # `ref: refs/heads/develop\tHEAD`
        if line.startswith("ref:") and "refs/heads/" in line:
            return line.split("refs/heads/", 1)[1].split()[0].strip()
    return ""


def current_branch(checkout) -> str:
    """The branch a checkout is on, or `""` — never a guess.

    `""` for an absent tree, a corrupt one, and for a detached HEAD, which git reports as the
    literal string `HEAD`. Returning that would build the refspec `refs/heads/HEAD`, which fetches
    nothing and resets to nothing.
    """
    at = Path(checkout)          # a caller may hold a str — this is asked of paths from four
    if not (at / ".git").exists():   # modules and one of them stores them as text
        return ""
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=at)
    named = (out or "").strip().splitlines()[0].strip() if out else ""
    return named if (rc == 0 and named and named != "HEAD") else ""


class RepoCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_root()

    def sync(self, project: str, clone_url: str, base_branch: str = "") -> Path | None:
        """Return a checkout of `project` reset hard to origin/<base>, or None when the repo
        can't be made available (caller degrades to text-only). Never raises.

        `base_branch=""` MEANS "WHATEVER THIS REPOSITORY'S DEFAULT IS" — which is what a caller
        that does not know should ask for, and what neither of this method's callers could ask
        before. Both passed the literal `main`: a client on `master`, `develop` or `trunk` got a
        `--branch main` that names nothing, the clone failed, and the caller degraded with a
        message about reachability. `clone_for_proposal` already had this parameter and says the
        same thing; the cache did not, so the two answers to one question disagreed.

        The returned path is STABLE across syncs, and its content is only ever replaced by an
        atomic swap — a caller still reading the tree a previous sync returned is never reset,
        cleaned, or deleted underneath.

        `project` is only a cache key, so one project may keep several checkouts under distinct
        keys (its code, its documentation repo) without them colliding."""
        try:
            with _lock_for(project):
                served = self.root / project
                master = self.root / _MASTERS_DIRNAME / project
                # UNNAMED IS ASKED OF THE REMOTE, not of the checkout. `_reset` needs a name for
                # its refspec, and taking that name from the existing tree made "the repository's
                # own default" mean "whatever this cache landed on once" — so a client who moved
                # their default branch was served the abandoned one for ever. The remote is the
                # only thing that knows; the tree is the fallback for when it cannot be reached,
                # because an unreachable remote must not throw away a working checkout.
                wanted = base_branch or remote_default_branch(clone_url) or current_branch(master)
                if not (wanted and (master / ".git").exists()
                        and self._reset(master, wanted, clone_url)):
                    # missing or corrupt → drop and reclone (the degrade ladder's middle rung).
                    # Only the hidden master is dropped; the served tree stays whole throughout.
                    shutil.rmtree(master, ignore_errors=True)
                    master.parent.mkdir(parents=True, exist_ok=True)
                    # THE CALLER'S OWN ANSWER DECIDES HERE, not `wanted`: `wanted` may have been
                    # inferred from the checkout this line has just deleted, and cloning
                    # `--branch <name-from-a-tree-we-judged-unusable>` fails on a name nobody
                    # asked for. An empty ask lets git pick, which is what it means.
                    rc, out = _git(["clone", *(["--branch", base_branch] if base_branch else []),
                                    clone_url, str(master)])
                    if rc != 0:
                        log.warning("OPENFACTORY_CACHE: clone failed for %s (%s)",
                                    project, _scrub(out)[-160:])
                        return None
                    _scrub_remote(master, clone_url)
                if self._needs_publish(served, master):
                    self._publish(project, served, master)
                self._purge_displaced()
                return served
        except Exception as exc:  # noqa: BLE001 — cache trouble must never block the pipeline
            log.warning("OPENFACTORY_CACHE: sync failed for %s (%s)",
                        project, _scrub(str(exc))[:160])
            return None

    @staticmethod
    def _needs_publish(served: Path, master: Path) -> bool:
        """Whether the served snapshot must be replaced: absent, corrupt, behind the master's
        commit, or dirtied by a scribbler (a cache must be IDENTICAL to base, never merged into).
        When none of that holds the snapshot is left completely untouched, so the routine
        no-change sync costs a fetch and two reads — and churns nothing under a reader."""
        if not (served / ".git").exists():
            return True
        head = _head(served)
        return not head or head != _head(master) or _worktree_dirty(served)

    def _publish(self, project: str, served: Path, master: Path) -> None:
        """Swap a fresh snapshot of the master into the served path.

        Hardlinks, not copies: git never modifies a working-tree or object file in place (it
        unlinks and recreates), so a snapshot stays frozen while the master moves on, at the cost
        of directory metadata only. The displaced tree is parked under the grace window rather
        than deleted, because a reader may still hold it. The swap itself is two renames — a
        name-based reader can catch a sub-millisecond gap between them and degrade exactly as it
        already must for any sync that returns None."""
        staging_root = self.root / _STAGING_DIRNAME
        staging_root.mkdir(parents=True, exist_ok=True)
        stage = staging_root / f"{project}-{uuid.uuid4().hex[:8]}"
        try:
            shutil.copytree(master, stage, symlinks=True, copy_function=os.link)
        except OSError:  # a filesystem without hardlinks still gets a correct (slower) snapshot
            shutil.rmtree(stage, ignore_errors=True)
            shutil.copytree(master, stage, symlinks=True)
        if os.path.lexists(served):
            trash_root = self.root / _TRASH_DIRNAME
            trash_root.mkdir(parents=True, exist_ok=True)
            slot = trash_root / f"{project}-{uuid.uuid4().hex[:8]}"
            os.rename(served, slot)
            os.utime(slot)  # rename keeps the dir's old mtime; purge ages by arrival, not creation
        os.rename(stage, served)

    def _purge_displaced(self) -> None:
        """Delete parked trees whose grace expired. Best-effort and per-entry: two keys syncing
        concurrently may purge at once, and losing a purge race must never fail a sync."""
        trash_root = self.root / _TRASH_DIRNAME
        if not trash_root.is_dir():
            return
        now = time.time()
        for entry in trash_root.iterdir():
            try:
                if now - entry.stat().st_mtime >= _TRASH_GRACE_SECONDS:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                continue

    @staticmethod
    def _reset(path: Path, base_branch: str, clone_url: str = "") -> bool:
        """fetch + reset --hard origin/<base> + clean, on the MASTER only. False → caller recloned.

        Fetches from the URL passed as an ARGUMENT rather than from the stored remote, because the
        stored remote deliberately carries no credential (see the module docstring). The explicit
        refspec keeps `origin/<base>` meaning what it always did — without it the fetch would only
        move FETCH_HEAD and the reset below would silently use a stale ref."""
        spec = f"+refs/heads/{base_branch}:refs/remotes/origin/{base_branch}"
        fetch = ["fetch", clone_url, spec] if clone_url else ["fetch", "origin", base_branch]
        for args in (fetch,
                     ["checkout", "-f", base_branch],
                     ["reset", "--hard", f"origin/{base_branch}"],
                     ["clean", "-fdx"]):
            rc, _ = _git(args, cwd=path)
            if rc != 0:
                return False
        # a checkout cloned before this was fixed still holds a token in .git/config
        _scrub_remote(path, clone_url)
        return True

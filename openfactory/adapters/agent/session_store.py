"""Where a paused agent session waits between two boxes — free by default (#118).

A rate-limit pause is a pause, not a redo (ADR-0012): the harness's session is kept and the next
run continues it with `--resume` instead of replanning and re-implementing. Until this module the
keeping was an S3 `put_object`, so the capability existed only for a deployment that had bought an
object store — and the free, open-source deployment, the one least able to absorb a second agent
pass, was the one that paid for the pause twice.

THE AXIS SHAPE IS THE METRICS AXIS'S, deliberately. `observability/registry.py` already solved
this exact problem for telemetry: a table keyed by kind, a free row and a vendor row as PEERS, a
selection function that prefers what the deployment SAYS over what it can be guessed to have, and
an unknown kind that raises naming what is supported rather than degrading to a no-op nobody can
tell from "the job never started".

WHAT A STORE HOLDS is one opaque blob per key — a gzipped tar of the harness's own session
directory, produced and consumed by the adapter that knows what is in it. The key is the same
string for both stores (`resume/<project>/<issue>/<session>.tar.gz`), so a deployment that later
adds a cloud does not have to rewrite handles that are already parked, and the cloud's IAM policy
and lifecycle rule keep matching the prefix they were written for.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger("openfactory.agent.session_store")

#: How long a snapshot is worth keeping. It is the pause backoff's horizon, not a guess: the
#: workflow retries a rate-limited job on a 30→120-minute ladder and an impediment can hold one for
#: days, so a week covers every resumable pause this platform can produce, and the cloud twin's own
#: bucket lifecycle has been 7 days since it was written (`infra/terraform/resume_store.tf`). Past
#: it the session is stale anyway: the branch has moved and the ticket may not exist.
RETENTION_SECONDS = 7 * 24 * 60 * 60

#: How long a `.part` may exist before it is read as abandoned rather than in flight. Generous
#: because the cost of being wrong in one direction is a lost snapshot (one cold run) and in the
#: other a file that never leaves — and because a write this size finishes in seconds.
_STAGING_GRACE_SECONDS = 60 * 60


def session_key(project: str, issue: str, session: str) -> str:
    """The address of one session's snapshot. Callers pass values already made path-safe."""
    return f"resume/{project}/{issue}/{session}.tar.gz"


@runtime_checkable
class SessionStore(Protocol):
    """Two methods, both best-effort: losing a session costs a cold run, never a failed job."""

    def put(self, *, key: str, blob: bytes) -> bool:
        """Keep `blob` under `key`, replacing any previous one. False = not kept."""
        ...

    def get(self, *, key: str) -> bytes | None:
        """The blob, or None when there is none here / it could not be read."""
        ...


#: The compose worker's state volume — already how proofs, the registry and the metrics database
#: survive a restart, so a deployment there gets durability with no new mount to explain.
_SYSTEM_DIR = Path("/var/lib/openfactory/resume")


def session_dir() -> Path:
    """Where the free store keeps its snapshots.

    Read at CALL time, never captured into a module constant: a constant read at import makes
    `monkeypatch.setenv` inert, the test passes, and the code under test writes to the real
    `/var/lib` path — the trap `box_prove.PROOF_DIR` is still living with.

    THE FALLBACK IS NOT DECORATION. `/var/lib/openfactory` belongs to the compose worker and to
    nobody else: an operator who `pip install`ed this and runs it as themselves cannot create it,
    and the free capability would disappear behind one WARNING line. So the operator's own
    directory is the second answer — the same place the registry falls back to."""
    explicit = (os.environ.get("OPENFACTORY_RESUME_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    try:
        _SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        return _SYSTEM_DIR
    except OSError:
        from openfactory import namespace

        return Path(namespace.operator_path("resume"))


class FileSessionStore:
    """The free store: one file per snapshot, on the machine that ran the job.

    BOUNDED TWO WAYS, because a store that grows with traffic on the shared state volume surfaces
    as "every job raises" rather than as a storage error. A new snapshot for a job REPLACES that
    job's older ones (only the newest session can be resumed — the older keys are unreachable the
    moment a new handle is minted), and anything past `RETENTION_SECONDS` is swept from the write
    path, which is where `RepoCache._purge_displaced` already does its own sweeping.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else session_dir()

    def _path(self, key: str) -> Path | None:
        """The file for `key`, or None if the key is not the shape this store issues.

        The key reaches here from a handle that has been round-tripped through the durable engine
        and the board, so it is checked rather than trusted: an absolute path or a `..` segment
        would write outside the store."""
        k = (key or "").strip()
        if not k or k.startswith("/") or ".." in Path(k).parts or not k.startswith("resume/"):
            log.warning("refusing %r as a session key — not an address this store issues", key)
            return None
        return self.root / k

    def put(self, *, key: str, blob: bytes) -> bool:
        path = self._path(key)
        if path is None:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Written beside and moved into place: a reader (the next run) must never find a
            # half-written archive, which would restore as a corrupt session and cost the cold run
            # this whole module exists to avoid.
            staging = path.with_suffix(path.suffix + ".part")
            staging.write_bytes(blob)
            staging.replace(path)
        except OSError as exc:
            log.warning("could not keep the session snapshot at %s (%s) — the next run will be "
                        "cold", path, exc)
            return False
        self._sweep(path)
        return True

    def get(self, *, key: str) -> bytes | None:
        path = self._path(key)
        if path is None or not path.is_file():
            return None
        try:
            # THE WINDOW IS ENFORCED ON THE WAY OUT, not only by the sweep. The cloud twin's
            # bucket expires the object, so a stale key there simply misses; a store swept only
            # from its own write path would hand back a month-old session on a deployment that
            # paused once — into a branch that has moved and a ticket that may not exist.
            if time.time() - path.stat().st_mtime > RETENTION_SECONDS:
                log.info("the snapshot at %s is past the %d-day window — running cold",
                         path, RETENTION_SECONDS // 86400)
                path.unlink(missing_ok=True)
                return None
            return path.read_bytes()
        except OSError as exc:
            log.warning("could not read the session snapshot at %s (%s) — running cold", path, exc)
            return None

    def _sweep(self, keep: Path) -> None:
        """Best-effort, from the write path, and never able to fail the put that triggered it."""
        try:
            for sibling in keep.parent.glob("*.tar.gz"):
                if sibling != keep:
                    sibling.unlink(missing_ok=True)
            cutoff = time.time() - RETENTION_SECONDS
            root = self.root
            # `.part` TOO. A worker SIGTERM'd between the write and the rename — which a deploy
            # mid-job does routinely — leaves a full-size staging file that matches neither glob,
            # so the "bounded" store would keep one per interrupted pause for ever.
            abandoned = time.time() - _STAGING_GRACE_SECONDS
            for old in (*root.glob("resume/*/*/*.tar.gz"), *root.glob("resume/*/*/*.part")):
                try:
                    stale = old.stat().st_mtime < (abandoned if old.suffix == ".part" else cutoff)
                    if stale:
                        old.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError as exc:
            log.debug("sweeping old session snapshots raised (%s) — the snapshot itself is "
                      "already stored", exc)


def _file_store(**kw) -> SessionStore:
    return FileSessionStore(root=kw.get("root"))


#: kind → builder. A new store joins as one row — here, or through the `session_store.<kind>`
#: entry point. THE VENDOR ROW IS NOT HERE ANY MORE: `s3` registers through that group (declared
#: by the `openfactory-aws` package), so this module imports nothing from `s3_session_store.py`
#: and the free
#: store is not a fallback for it, it is a peer that happens to ship in the core.
SESSION_STORES = {"file": _file_store}

#: The entry-point axis name: `session_store.<kind>`.
AXIS = "session_store"


def session_store_kind() -> str:
    """Which store this deployment uses.

    An explicit `OPENFACTORY_SESSION_STORE` wins, because the OSS compose file says `file` out
    loud and an inferred default is a decision nobody can find. Absent it, a configured bucket
    means the deployment has an object store and intends to use it; absent that, the free store —
    which needs nothing, and therefore is what a deployment with nothing gets."""
    explicit = (os.environ.get("OPENFACTORY_SESSION_STORE") or "").strip().lower()
    if explicit:
        return explicit
    return "s3" if (os.environ.get("OPENFACTORY_RESUME_BUCKET") or "").strip() else "file"


def build_session_store(kind: str | None = None, **kw) -> SessionStore:
    """Build the configured store. An unknown kind RAISES naming what is known — falling back to
    a store that keeps nothing is indistinguishable from a job that never paused."""
    from openfactory import plugins

    chosen = (kind or session_store_kind()).strip().lower()
    builder = SESSION_STORES.get(chosen) or plugins.builder(AXIS, chosen, builtin=SESSION_STORES)
    if builder is None:
        known = ", ".join(plugins.known(AXIS, SESSION_STORES))
        raise ValueError(f"unknown session store {chosen!r} — known: {known}"
                         f"{plugins.install_hint(AXIS, chosen)}")
    return builder(**kw)

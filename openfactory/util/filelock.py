"""A lock on a file that every thread and every process on one host agrees on, with a timeout —
and the atomic replace that goes with it (#266 slice 3).

THREE STORES NEEDED THE SAME TWO THINGS, and `registry.py` had already paid for both once: the
product's semaphore on what becomes work (`product/semaphore.py`), and the two JSON files a turn
reads and rewrites (`cases.json`, `recall-index.json`). Each did a plain `write_text`, so a crash
between the truncate and the write left an empty file, and two writers left whichever came last.
One implementation here, rather than the registry's lines copied three times — a lesson learned in
one file and not copied is this codebase's most repeated defect.

WHY `flock` AND NOT `fcntl.lockf`. A POSIX record lock belongs to the PROCESS: two threads of one
worker — which runs eight activities at once — would both "hold" it, and the lock would guard
nothing between the two conversations it exists for. `flock` belongs to the open file
description, so each acquisition opens the file afresh and two threads contend exactly as two
processes do. The kernel holds it on the inode, so it also holds across the worker's and the
panel's containers where they share the volume (compose mounts one), and it is released by the
kernel when a holder dies: a process killed mid-write leaves no lock behind for anyone to clear.

WHY A THREAD LOCK IN FRONT OF IT. Threads of one process queue on a `threading.Lock` with a real
timeout instead of polling the file; only the thread at the head polls. It also makes the lock
RE-ENTRANT for its holder, which `flock` alone cannot be: a second open of the same file by the
thread that already holds it would wait for itself until the timeout.

A SIBLING LOCK FILE, NEVER THE FILE BEING WRITTEN. The data file is replaced on every write, and a
lock held on a replaced inode protects nothing (`registry.py::_locked` says the same).

WHAT IT DOES NOT DO: hold across HOSTS. Two workers on two machines that share no filesystem
share no lock; ADR-0051 asks for one host at least, and a deployment of more than one host needs
the lock moved to a store both can reach. Said here so it is found before it is assumed.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import stat
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger("openfactory.util.filelock")

#: How often the thread at the head of the queue asks the file again. Short, because a hold is a
#: comparison and a push — seconds — and the waiter should not add a noticeable fraction to it.
POLL_SECONDS = 0.05


class Waited(TimeoutError):
    """The lock was not had within the timeout. `waited` is how long was spent asking."""

    def __init__(self, path: str, waited: float) -> None:
        super().__init__(f"{path} was held by somebody else for the whole {waited:.1f}s waited")
        self.path = path
        self.waited = waited


class _Guard:
    """One lock file as THIS process holds it: which thread has it, how deeply, on which handle."""

    __slots__ = ("depth", "handle", "mutex", "owner")

    def __init__(self) -> None:
        self.mutex = threading.Lock()
        self.owner: int | None = None
        self.depth = 0
        self.handle = None


#: One guard per lock file this process has taken — bounded by the products and the registry
#: projects this deployment serves (a semaphore and two stores each), never by traffic.
_GUARDS: dict[str, _Guard] = {}
_GUARDS_LOCK = threading.Lock()


def _guard(path: str) -> _Guard:
    with _GUARDS_LOCK:
        return _GUARDS.setdefault(path, _Guard())


class FileLock:
    """An exclusive lock on `path`, for threads and processes alike. `acquire` raises `Waited`."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

    def held_here(self) -> bool:
        """Whether the CALLING thread holds it."""
        return _guard(self.path).owner == threading.get_ident()

    def acquire(self, *, timeout: float) -> None:
        guard = _guard(self.path)
        me = threading.get_ident()
        if guard.owner == me:
            guard.depth += 1
            return
        started = time.monotonic()
        if not guard.mutex.acquire(timeout=max(0.0, timeout)):
            raise Waited(self.path, time.monotonic() - started)
        try:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            # "a": never truncate — the file holds nothing, but a mode that truncates on open is
            # one edit away from somebody using it to hold something
            handle = open(self.path, "a")  # noqa: SIM115 — closed by `release`, not by a block
            try:
                while True:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        spent = time.monotonic() - started
                        if spent >= timeout:
                            raise Waited(self.path, spent) from None
                        time.sleep(POLL_SECONDS)
            except BaseException:
                handle.close()
                raise
        except BaseException:
            guard.mutex.release()
            raise
        guard.owner, guard.depth, guard.handle = me, 1, handle

    def release(self) -> None:
        guard = _guard(self.path)
        if guard.owner != threading.get_ident():
            raise RuntimeError(f"{self.path} released by a thread that does not hold it")
        guard.depth -= 1
        if guard.depth:
            return
        handle, guard.handle, guard.owner = guard.handle, None, None
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()
            guard.mutex.release()

    @contextlib.contextmanager
    def held(self, *, timeout: float):
        self.acquire(timeout=timeout)
        try:
            yield self
        finally:
            self.release()


def lock_beside(path: Path | str) -> FileLock:
    """The sibling lock of a data file — `cases.json` → `cases.json.lock`."""
    return FileLock(f"{path}.lock")


def replace_atomically(path: Path | str, text: str) -> None:
    """Write `text` to `path` so a reader sees the old file or the new one, never half of either.

    A temporary file in the SAME directory, flushed to disk, then `os.replace` — atomic on one
    filesystem. `write_text` truncates first, so a crash, a full disk or a kill in between left an
    empty store, which each of these stores reads as "nothing there" rather than as damage."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = None
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            if mode is not None:
                os.fchmod(fh.fileno(), mode)
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)  # never leave debris beside the store
        raise

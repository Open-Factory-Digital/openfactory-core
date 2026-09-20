"""The factory as three processes on this machine — the host's `docker compose up` (ADR-0049 D9).

Compose is four processes in a file: the durable engine and its database, the worker and the
panel. Unpacked, three of them run here as they are — the engine's dev server is one binary with a
SQLite file behind it, the worker is a module this package ships, and the panel is `openfactory
serve`, the very command compose runs in its container. What Docker adds is the box's isolation,
which the `local` runtime gives up out loud.

IT LIVES HERE AND NOT IN `cli.py` because a front end may not do the work: the action layer's own
guard refuses `Popen` and `terminate` in a command module by name, and it is right to — a surface
that supervises processes itself is a second implementation of something, and the two drift
without either side noticing. `openfactory up` is the front end; this is the thing it drives.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

#: The durable engine's own dev server: one binary, a SQLite file behind it, no database service.
#: NAMED RATHER THAN INSTALLED — a platform that fetches binaries onto somebody's machine is a
#: different product from one that says which command to run.
TEMPORAL_HINT = ("the durable engine is off: `temporal` is not on your PATH. Install it — "
                 "`brew install temporal`, or https://temporal.io/setup/install-temporal-cli — "
                 "and re-run. Everything attended (`run`, `poll`, the panel) works without it; "
                 "what waits for it is the human merge gate, park/resume and every deadline.")


#: The other half of the durable engine: the library the worker runs on. It is the `runtime`
#: extra, so an install that followed the older one-machine page (`pip install -e .`) does not
#: have it — and `TEMPORAL_HINT` told that same reader to put `temporal` on the PATH (#171).
#:
#: IT DOES NOT SAY THE PANEL WORKS WITHOUT IT, because it does not: measured 2026-09-18 on an
#: interpreter with `temporalio` blocked, the panel process serves but its page (`/`) and
#: `/api/floor` answer 500 — both import `runtime.temporal.view`. `run` and `poll` do work.
RUNTIME_HINT = ("the durable engine is off: `temporal` is on your PATH, but this install has no "
                "`temporalio` — the `runtime` extra, which the worker runs on and the panel's own "
                "page needs as well. Install it — `pip install -e '.[runtime]'` in the checkout "
                "you installed from — and re-run. `run` and `poll` work without it; what waits for "
                "it is the human merge gate, park/resume and every deadline.")

#: Said after `TEMPORAL_HINT` when the library is missing as well, so that installing the binary
#: as told is not the step that takes the factory down (#171).
RUNTIME_TOO = ("This install has no `temporalio` either — the `runtime` extra, which the engine's "
               "worker runs on and the panel's own page needs — so install it beside the binary: "
               "`pip install -e '.[runtime]'` in the checkout you installed from.")


def durable_half(asked: bool) -> tuple[str | None, str]:
    """The engine binary to start, or None — and the sentence that says what is missing, or "".

    BOTH HALVES, ONE ANSWER. The binary and the library are two separate installs, and saying only
    the first one sent a reader straight into the crash #171 reported: they put `temporal` on the
    PATH as `TEMPORAL_HINT` told them, and the next `up` died on the missing library."""
    if not asked:
        return None, ""
    binary, client = the_engine(), the_client()
    if binary and client:
        return binary, ""
    if binary:
        return None, RUNTIME_HINT
    return None, TEMPORAL_HINT if client else f"{TEMPORAL_HINT} {RUNTIME_TOO}"


def the_engine() -> str | None:
    """The `temporal` binary, or None — the one thing this runtime cannot ship."""
    return shutil.which("temporal")


def the_client() -> bool:
    """Whether the worker's library is installed in the interpreter the worker would run in.

    ASKED OF THE SPEC, NOT BY IMPORTING IT. The worker is `sys.executable -m …`, this very
    interpreter, so a spec found here is the one the child finds. Importing `temporalio.worker` to
    be sure cost 2.9 s cold, measured 2026-09-18 on a WSL machine (2.2 s even for `find_spec` of
    the submodule, which imports the package); the top-level spec took 7 ms and answers the only
    question an install without the extra raises."""
    import importlib.util

    try:
        return importlib.util.find_spec("temporalio") is not None
    except (ImportError, ValueError):   # a module blocked or half-removed in sys.modules
        return False


def processes(*, panel_port: int, state: Path, engine: str | None) -> list[tuple[str, list[str]]]:
    """What to start, in order, and what each one is called.

    THE WORKER ONLY WHERE THERE IS AN ENGINE TO WORK FOR. It connects at startup and exits when
    nothing answers, and one dying process ends the set — so on a machine with no `temporal`
    binary, starting it would take the panel down with it and deliver NOTHING from a command whose
    whole promise is that the attended half still works.

    AND ONLY WHERE IT CAN START AT ALL (#171). `temporalio` is the `runtime` extra, the one-machine
    page installed without it, and `up` told that reader to put `temporal` on the PATH. Doing
    exactly that ended the whole set: `✓ engine, worker, panel`, then `ModuleNotFoundError:
    No module named 'temporalio'`, `✗ worker exited (1) — stopping the rest`, and the panel went
    down with it. The ENGINE stays out too, not only the worker: an engine with no worker is the
    half-state the doctor cannot see — its `processes` check reads the engine's port as the durable
    half answering, and the worker holds no port to be missed by. So the durable half is off, as it
    is without the binary, and `durable_half` says which of the two is missing.
    """
    plan: list[tuple[str, list[str]]] = []
    if engine and the_client():
        plan.append(("engine", [engine, "server", "start-dev", "--db-filename",
                                str(state / "temporal.db"), "--port", "7233", "--ui-port", "8080"]))
        plan.append(("worker", [sys.executable, "-m", "openfactory.runtime.temporal.worker"]))
    plan.append(("panel", [sys.executable, "-m", "openfactory.cli", "serve",
                           "--port", str(panel_port)]))
    return plan


#: How long a child is given to stop after it is asked, before it is made to.
GRACE_S = 10.0


def run(plan: list[tuple[str, list[str]]], *, say, grace: float = GRACE_S) -> int:
    """Start them, wait, and stop them together. Returns the exit code for the caller.

    IN THE FOREGROUND, ON PURPOSE. A person starting their own factory wants one window they can
    read and one Ctrl-C that ends it — not three terminals and a stale pid file. Each child keeps
    its own stdout, which is why nothing here captures it.

    "TOGETHER" HELD ONLY FOR CTRL-C (#136). Measured on this machine: a SIGTERM to the supervisor
    (`kill`, a service manager, a closed terminal's SIGHUP) ended it on the spot and left the
    engine, the worker and the panel running as orphans; a SIGKILL did the same; and a child that
    did not exit within the wait was simply left there. The panel then held its port with nothing
    behind it, and a fresh `up` could not bind. So SIGTERM and SIGHUP stop the set exactly as
    Ctrl-C does, a child that outlives its grace is killed, and a small reaper outlives a
    supervisor that was killed outright, for exactly as long as it takes to stop what that
    supervisor started.
    """
    started: list[tuple[str, subprocess.Popen]] = []
    reaper: subprocess.Popen | None = None
    previous = _stop_on_signals()
    try:
        for name, argv in plan:
            try:
                started.append((name, subprocess.Popen(argv)))
            except OSError as exc:
                say(f"✗ {name} could not start: {exc}")
        if not started:
            return 1
        reaper = _start_reaper(started, grace=grace, say=say)
        # CHECKED AFTER IT IS BOUND, NEVER INSIDE THE START. A signal arriving while this waits
        # raises here, and `reaper` is already the name the `finally` kills. Done inside
        # `_start_reaper` it was not: a SIGTERM during the wait left the watcher running after an
        # orderly stop — measured, on a widened window, and it is the very thing the reaper's own
        # docstring says must not happen, since it then signals pids the set no longer owns.
        if reaper is not None and not _reaper_is_there(reaper, say=say):
            reaper = None   # it is gone; there is nothing for the stop path to kill
        say(f"✓ {', '.join(name for name, _ in started)} — Ctrl-C stops them together.")
        while True:
            for name, child in started:
                if child.poll() is not None:
                    # ONE DYING ENDS THE SET. A worker that exited while the panel keeps serving
                    # is a factory that looks up and takes no cards — the silent half-state this
                    # platform exists to refuse.
                    say(f"✗ {name} exited ({child.returncode}) — stopping the rest")
                    raise KeyboardInterrupt
            time.sleep(0.4)
    except KeyboardInterrupt:
        say("stopping…")
    finally:
        # THE REAPER FIRST: it exists for a supervisor that died without getting here, and a reaper
        # left running after an orderly stop would be a process acting on pids that are not ours.
        if reaper is not None:
            with contextlib.suppress(Exception):
                reaper.kill()
                reaper.wait(timeout=grace)
        _stop(started, grace=grace)
        _restore(previous)
    return 0


def _stop_on_signals() -> dict:
    """SIGTERM and SIGHUP end the set the way Ctrl-C does. The handlers it replaced, to restore."""

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    previous: dict = {}
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is None:
            continue
        with contextlib.suppress(ValueError, OSError):   # not the main thread: nothing to install
            previous[sig] = signal.signal(sig, interrupt)
    return previous


def _restore(previous: dict) -> None:
    for sig, handler in previous.items():
        with contextlib.suppress(ValueError, OSError, TypeError):
            signal.signal(sig, handler)


def _stop(started: list[tuple[str, subprocess.Popen]], *, grace: float) -> None:
    """Ask every child to stop, give them `grace` together, then make the rest.

    A CHILD THAT DID NOT STOP WAS LEFT RUNNING. `wait(timeout=10)` inside a suppressed block gave up
    and moved on, so a panel whose shutdown was held by an open stream outlived the set that
    started it — holding the port a fresh `up` needs."""
    for _, child in started:
        with contextlib.suppress(Exception):
            child.terminate()
    deadline = time.monotonic() + grace
    for _, child in started:
        with contextlib.suppress(Exception):
            child.wait(timeout=max(0.0, deadline - time.monotonic()))
    for _, child in started:
        if child.poll() is None:
            with contextlib.suppress(Exception):
                child.kill()
                child.wait(timeout=grace)


#: How long to wait before asking whether the reaper is still there. An import error, a `sys.path`
#: this process has and the child does not, a missing interpreter — all of them happen at once.
_REAPER_STARTS_IN_S = 0.3


def _start_reaper(started: list[tuple[str, subprocess.Popen]], *, grace: float, say):
    """The process that stops the children if this one is killed before it can.

    AND IT SAYS SO IF IT DID NOT START. `Popen` raising was the only failure this reported, so a
    reaper that started and exited at once — the module failing to import on a deployment whose
    `sys.path` differs from this process's — left the operator believing a SIGKILL was covered,
    and finding out when a port was held (review of #160)."""
    argv = [sys.executable, "-m", "openfactory.runtime.host", "--reap", str(os.getpid()),
            str(grace), *(str(child.pid) for _, child in started)]
    try:
        return subprocess.Popen(argv)
    except OSError as exc:
        say(f"! the reaper could not start ({exc}) — if this supervisor is killed outright, its "
            f"children will outlive it")
        return None


def _reaper_is_there(watcher: subprocess.Popen, *, say) -> bool:
    """Whether the reaper is still running a beat after it was started.

    SEPARATE FROM STARTING IT, so the caller holds the process while this waits: an interrupt here
    must leave the watcher in a name the stop path can kill, and inside `_start_reaper` it did
    not."""
    time.sleep(_REAPER_STARTS_IN_S)
    if watcher.poll() is None:
        return True
    say(f"! the reaper exited at once ({watcher.returncode}) — if this supervisor is killed "
        f"outright, its children will outlive it")
    return False


def reap(supervisor: int, pids: list[int], *, grace: float, every: float = 0.5) -> None:
    """Wait for `supervisor` to die, then stop `pids` — SIGTERM, `grace`, SIGKILL.

    A SUPERVISOR KILLED OUTRIGHT RUNS NO `finally`, and nothing else on a Mac would stop what it
    started: there is no parent-death signal to ask for. This process is its child, so the moment
    it is reparented the supervisor is gone. It ignores the terminal's Ctrl-C and hang-up — those
    reach the supervisor, which stops the set itself and then kills this.

    IT ACTS ON RAW PIDS, AND THAT IS THE ONE WAY IT CAN REACH OUTSIDE THE SET IT OWNS (review of
    #160). A child that had already exited leaves a pid the system may reuse, and a signal sent
    here would then reach a stranger's process. The window is narrow — these children are
    long-lived, and a child that dies normally ends the set through the supervisor, which kills
    this first — so nothing is restructured for it, but it is why this list is never widened
    beyond the children of one supervisor and never re-read from anywhere."""
    while os.getppid() == supervisor:
        time.sleep(every)
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.2)
    for pid in pids:
        if _alive(pid):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


if __name__ == "__main__" and len(sys.argv) >= 4 and sys.argv[1] == "--reap":
    for _ignored in (signal.SIGINT, getattr(signal, "SIGHUP", None)):
        if _ignored is not None:
            signal.signal(_ignored, signal.SIG_IGN)
    reap(int(sys.argv[2]), [int(pid) for pid in sys.argv[4:]], grace=float(sys.argv[3]))

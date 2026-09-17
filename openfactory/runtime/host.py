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


def the_engine() -> str | None:
    """The `temporal` binary, or None — the one thing this runtime cannot ship."""
    return shutil.which("temporal")


def processes(*, panel_port: int, state: Path, engine: str | None) -> list[tuple[str, list[str]]]:
    """What to start, in order, and what each one is called.

    THE WORKER ONLY WHERE THERE IS AN ENGINE TO WORK FOR. It connects at startup and exits when
    nothing answers, and one dying process ends the set — so on a machine with no `temporal`
    binary, starting it would take the panel down with it and deliver NOTHING from a command whose
    whole promise is that the attended half still works.
    """
    plan: list[tuple[str, list[str]]] = []
    if engine:
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
        watcher = subprocess.Popen(argv)
    except OSError as exc:
        say(f"! the reaper could not start ({exc}) — if this supervisor is killed outright, its "
            f"children will outlive it")
        return None
    time.sleep(_REAPER_STARTS_IN_S)
    if watcher.poll() is not None:
        say(f"! the reaper exited at once ({watcher.returncode}) — if this supervisor is killed "
            f"outright, its children will outlive it")
        return None
    return watcher


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

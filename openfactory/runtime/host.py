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
import shutil
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


def run(plan: list[tuple[str, list[str]]], *, say) -> int:
    """Start them, wait, and stop them together. Returns the exit code for the caller.

    IN THE FOREGROUND, ON PURPOSE. A person starting their own factory wants one window they can
    read and one Ctrl-C that ends it — not three terminals and a stale pid file. Each child keeps
    its own stdout, which is why nothing here captures it.
    """
    started: list[tuple[str, subprocess.Popen]] = []
    for name, argv in plan:
        try:
            started.append((name, subprocess.Popen(argv)))
        except OSError as exc:
            say(f"✗ {name} could not start: {exc}")
    if not started:
        return 1
    say(f"✓ {', '.join(name for name, _ in started)} — Ctrl-C stops them together.")
    try:
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
        for _, child in started:
            with contextlib.suppress(Exception):
                child.terminate()
        for _, child in started:
            with contextlib.suppress(Exception):
                child.wait(timeout=10)
    return 0

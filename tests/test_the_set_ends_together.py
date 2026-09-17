"""#136: the processes `openfactory up` starts end together, however the supervisor ends.

MEASURED ON THIS MACHINE before the change, with the real engine, worker and panel:

    SIGKILL to the supervisor   -> engine, worker and panel all still alive, the panel on its port
    SIGTERM to the supervisor   -> the same: the supervisor gone at once, all three orphaned
    engine gone under the panel -> /api/floor 38.8 s, /api/inbox 8.9 s (500), /api/temporal/jobs 6.3 s

Only Ctrl-C ran the `finally` that stops the set, and a child still running after its wait was left
there. The orphaned panel then held its port with nothing behind it, and a fresh `up` could not bind.

These drive `host.run` in a real process with real children — sleepers that write their pid — and
signal it the way a terminal, a service manager and `kill -9` do.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def _sleeper(pidfile: Path, *, ignores_term: bool = False, exits_after: float = 0) -> list[str]:
    body = textwrap.dedent(f"""
        import os, signal, sys, time
        open({str(pidfile)!r}, "w").write(str(os.getpid()))
        {"signal.signal(signal.SIGTERM, signal.SIG_IGN)" if ignores_term else ""}
        time.sleep({exits_after or 120})
        sys.exit(3)
    """)
    return [sys.executable, "-c", body]


def _supervise(tmp_path: Path, plan: list[tuple[str, list[str]]], *, grace: float = 1.0):
    script = textwrap.dedent(f"""
        import sys
        from openfactory.runtime import host
        sys.exit(host.run({plan!r}, say=lambda line: print(line, flush=True), grace={grace}))
    """)
    return subprocess.Popen([sys.executable, "-c", script], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, start_new_session=True)


def _pids(*files: Path, within: float = 15.0) -> list[int]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if all(f.exists() and f.read_text().strip() for f in files):
            return [int(f.read_text()) for f in files]
        time.sleep(0.1)
    raise AssertionError(f"the children never started: {[str(f) for f in files]}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # a zombie answers kill(0); it has stopped, which is what these tests ask
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(state.stdout.strip()) and not state.stdout.strip().startswith("Z")


def _gone(pids: list[int], *, within: float) -> list[int]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        left = [pid for pid in pids if _alive(pid)]
        if not left:
            return []
        time.sleep(0.2)
    return [pid for pid in pids if _alive(pid)]


@pytest.fixture
def cleanup():
    pids: list[int] = []
    yield pids
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _two(tmp_path: Path, **kw) -> tuple[list[tuple[str, list[str]]], list[Path]]:
    files = [tmp_path / "a.pid", tmp_path / "b.pid"]
    return [("a", _sleeper(files[0], **kw)), ("b", _sleeper(files[1]))], files


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_supervisor_asked_to_stop_by_a_signal_stops_the_set(tmp_path, cleanup, sig):
    """`kill`, a service manager and a closed terminal send these, not Ctrl-C."""
    plan, files = _two(tmp_path)
    supervisor = _supervise(tmp_path, plan)
    children = _pids(*files)
    cleanup.extend(children)

    supervisor.send_signal(sig)

    assert _gone(children, within=10) == [], "the children outlived a supervisor that was stopped"
    assert supervisor.wait(timeout=10) == 0
    assert "stopping…" in supervisor.stdout.read()


def test_a_supervisor_KILLED_outright_still_takes_its_children_with_it(tmp_path, cleanup):
    plan, files = _two(tmp_path)
    supervisor = _supervise(tmp_path, plan)
    children = _pids(*files)
    cleanup.extend(children)
    time.sleep(1)   # the reaper is started after the children

    supervisor.kill()

    assert _gone(children, within=15) == [], (
        "a supervisor killed with SIGKILL left its children running — the orphaned panel of #136")


def test_a_child_that_ignores_the_request_to_stop_is_made_to(tmp_path, cleanup):
    """`wait(timeout=10)` gave up and moved on, leaving the child — a panel whose shutdown an open
    stream was holding — running after the set that started it had ended."""
    plan, files = _two(tmp_path, ignores_term=True)
    supervisor = _supervise(tmp_path, plan, grace=1.0)
    children = _pids(*files)
    cleanup.extend(children)

    supervisor.send_signal(signal.SIGTERM)
    supervisor.wait(timeout=10)

    # AT THE MOMENT THE SUPERVISOR RETURNS, not "within ten seconds": the reaper would also stop
    # them a beat later, and a guard that waits cannot see whether the supervisor did its own job.
    # Measured with the kill cut out: the child is still there when `run` returns, and for seconds
    # after it.
    still = [pid for pid in children if _alive(pid)]
    assert still == [], "a child that ignored SIGTERM was left running by the supervisor"


def test_one_child_dying_still_ends_the_set(tmp_path, cleanup):
    files = [tmp_path / "a.pid", tmp_path / "b.pid"]
    plan = [("short", _sleeper(files[0], exits_after=1)), ("long", _sleeper(files[1]))]
    supervisor = _supervise(tmp_path, plan)
    children = _pids(*files)
    cleanup.extend(children)

    assert supervisor.wait(timeout=20) == 0
    assert _gone(children, within=10) == []
    assert "short exited (3)" in supervisor.stdout.read()


def test_an_orderly_stop_leaves_no_reaper_behind(tmp_path, cleanup):
    """The reaper exists for a supervisor that died without stopping the set. Left running after an
    orderly stop, it would one day signal pids that are no longer ours."""
    plan, files = _two(tmp_path)
    supervisor = _supervise(tmp_path, plan)
    cleanup.extend(_pids(*files))
    time.sleep(1)
    reapers = subprocess.run(["pgrep", "-f", f"openfactory.runtime.host --reap {supervisor.pid}"],
                             capture_output=True, text=True).stdout.split()
    assert reapers, "no reaper was started, so a SIGKILL would orphan the children"
    cleanup.extend(int(pid) for pid in reapers)

    supervisor.send_signal(signal.SIGTERM)
    supervisor.wait(timeout=10)

    # GONE WHEN THE SUPERVISOR RETURNS, not a moment later: a reaper that is only noticing its
    # parent died would then signal the pids it was given, which an orderly stop has already freed
    still = [pid for pid in (int(p) for p in reapers) if _alive(pid)]
    assert still == [], "the reaper outlived an orderly stop"


def test_the_panel_does_not_wait_forever_for_an_open_stream_to_close(monkeypatch):
    """uvicorn waits for every open response before it exits, and the engine stream is open for as
    long as a tab is."""
    import uvicorn
    from typer.testing import CliRunner

    from openfactory.cli import app

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: seen.update(kw))
    monkeypatch.setattr("openfactory.namespace.announce_build", lambda role: "")

    CliRunner().invoke(app, ["serve", "--port", "8899"])

    assert 0 < (seen.get("timeout_graceful_shutdown") or 0) <= 10, seen


def test_a_reaper_that_exits_at_once_is_reported(monkeypatch, capsys):
    """`Popen` raising was the only failure this reported, so a reaper that started and died —
    the module failing to import where `sys.path` differs — left the operator believing a SIGKILL
    was covered (review of #160)."""
    from openfactory.runtime import host

    class Stillborn:
        returncode = 1
        pid = 424242

        def poll(self):
            return 1

    monkeypatch.setattr(host.subprocess, "Popen", lambda *a, **kw: Stillborn())
    monkeypatch.setattr(host, "_REAPER_STARTS_IN_S", 0.01)
    said: list[str] = []

    assert host._reaper_is_there(Stillborn(), say=said.append) is False
    assert any("reaper exited at once" in line and "outlive" in line for line in said), said


def test_a_reaper_that_is_there_is_returned(monkeypatch):
    from openfactory.runtime import host

    class Running:
        pid = 424243

        def poll(self):
            return None

    monkeypatch.setattr(host.subprocess, "Popen", lambda *a, **kw: Running())
    monkeypatch.setattr(host, "_REAPER_STARTS_IN_S", 0.01)
    said: list[str] = []

    watcher = host._start_reaper([("panel", Running())], grace=1.0, say=said.append)

    assert isinstance(watcher, Running)
    assert host._reaper_is_there(watcher, say=said.append) is True
    assert said == []


def test_a_signal_WHILE_THE_REAPER_IS_CHECKED_still_stops_it(monkeypatch):
    """Measured on a widened window: a SIGTERM arriving while the check waited left the watcher
    running after an orderly stop — the one thing `reap`'s docstring says must not happen, because
    it then signals pids the set no longer owns.

    THE REAPER HAS ITS OWN DOUBLE, and that is the whole case. The first version used one fake for
    both and asserted that SOMETHING had been killed — which the child satisfies on every path, so
    it passed against the very shape it was written to catch (review of #164). What is asserted is
    that the REAPER was killed."""
    from openfactory.runtime import host

    stopped: list[str] = []

    class Process:
        pid, returncode = 4242, 0

        def __init__(self, what: str) -> None:
            self.what = what

        def poll(self):
            return None

        def terminate(self):
            stopped.append(f"terminate {self.what}")

        def kill(self):
            stopped.append(f"kill {self.what}")

        def wait(self, timeout=None):
            return 0

    def popen(argv, *_a, **_kw):
        return Process("reaper" if "--reap" in argv else "child")

    monkeypatch.setattr(host.subprocess, "Popen", popen)

    def interrupted(_seconds):
        raise KeyboardInterrupt        # the signal lands inside the check

    monkeypatch.setattr(host.time, "sleep", interrupted)

    assert host.run([("panel", ["/bin/true"])], say=lambda _l: None, grace=0.01) == 0

    assert "kill reaper" in stopped, (
        f"the reaper was left running by an interrupt during its check: {stopped}")
    assert "terminate child" in stopped, "the children were not stopped either"

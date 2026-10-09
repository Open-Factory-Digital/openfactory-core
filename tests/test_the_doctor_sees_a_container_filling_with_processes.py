"""`openfactory doctor` sees a container of the stack filling up with processes (#532).

A panel whose PID 1 reaped no orphan held 17,420 zombies after 39 hours, against a `pids.max` of
17,435. It could start no thread, the floor read the engine as unreachable, and the doctor passed
the whole time: nothing in the stack read the count. The containers now start an init (the other
half of #532); `pid_headroom` is what sees the next leak, whatever its source, before the ceiling.

It asks the container the doctor runs in, and the panel through `docker exec` on the socket the
worker holds, ONE script in each one's own `sh`. It FAILS at half the ceiling, at a hundred zombies
whatever the ceiling, or when a container that was asked did not answer; a container that could not
be asked — not there, no daemon — is a note rather than a failure of the stack.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import subprocess
import time
from types import SimpleNamespace

import pytest

from openfactory import doctor
from openfactory.doctor import PidCount
from tests.pinned_probes import a_fully_pinned_probe_set

LIMIT = 17435


def _line(*counts):
    """The `pid_headroom` finding over these counts, every other probe pinned green."""
    report = doctor.diagnose(a_fully_pinned_probe_set(pid_counts=lambda: list(counts)))
    lines = [f for f in report.findings if f.check == "pid_headroom"]
    return (lines[0] if lines else None), report


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────

def test_a_stack_with_room_passes_and_says_what_it_read():
    line, report = _line(PidCount("worker", 41, LIMIT, 0), PidCount("panel", 12, LIMIT, 1))

    assert line.ok and report.ok
    assert line.message == ("the worker holds 41 processes of its 17,435, none of them a zombie; "
                            "the panel holds 12 processes of its 17,435, 1 of them a zombie")


def test_half_the_ceiling_fails_with_the_repair():
    """Live processes count as much as zombies: a leak of either stops the container."""
    line, report = _line(PidCount("worker", 41, LIMIT, 0),
                         PidCount("panel", LIMIT // 2 + 1, LIMIT, 0))

    assert not line.ok and not report.ok
    assert line.message.startswith("the panel holds 8,718 processes of its 17,435, none of them a "
                                   "zombie — at its ceiling a container can start no thread"), (
        line.message)
    assert "the worker" not in line.message, "a container with room is not the failure"
    assert "`init: true`" in line.remedy and "`tini`" in line.remedy
    assert "docker inspect -f '{{.HostConfig.Init}}' <container>" in line.remedy


def test_just_under_half_the_ceiling_passes():
    line, _report = _line(PidCount("worker", LIMIT // 2 - 1 , LIMIT, 0))
    assert line.ok, line.message


@pytest.mark.parametrize(("zombies", "ok"), [(doctor.ZOMBIES_THAT_FAIL - 1, True),
                                             (doctor.ZOMBIES_THAT_FAIL, False)])
def test_a_hundred_zombies_fail_whatever_the_ceiling(zombies, ok):
    """An unlimited container (`pids.max` reads `max`) has no half to reach: the zombies are what
    a PID 1 that reaps nothing leaves, and they are counted on their own."""
    line, _report = _line(PidCount("worker", 300, None, zombies))
    assert line.ok is ok, line.message


def test_an_unread_container_is_a_note_on_a_pass_never_a_failure():
    line, report = _line(PidCount("worker", 41, LIMIT, 0),
                         PidCount("panel", unread="No such container: openfactory-panel"))

    assert line.ok and report.ok
    assert line.message == "the worker holds 41 processes of its 17,435, none of them a zombie"
    assert line.note == ("the panel's processes could not be read "
                         "(No such container: openfactory-panel)")


def test_nothing_to_read_says_nothing():
    """One machine with no container: its processes are its own, and there is no stack to ask."""
    assert _line()[0] is None
    report = doctor.diagnose(dataclasses.replace(a_fully_pinned_probe_set(), pid_counts=None))
    assert not [f for f in report.findings if f.check == "pid_headroom"], "an older Probes asks"


def test_a_probe_that_raised_is_a_finding_not_a_crash():
    def broken():
        raise OSError("permission denied")

    report = doctor.diagnose(a_fully_pinned_probe_set(pid_counts=broken))
    [line] = [f for f in report.findings if f.check == "pid_headroom"]
    assert not line.ok and "permission denied" in line.message and line.remedy


def test_a_container_that_was_asked_and_did_not_answer_FAILS():
    """REVIEW OF #572: at its ceiling a container cannot start the shell that would count, and
    the check passed in exactly that state, with a note. Asked and silent is the failure; not
    there is the note."""
    line, report = _line(PidCount("worker", 41, LIMIT, 0),
                         PidCount("panel", silent="it did not answer in 20s"))

    assert not line.ok and not report.ok
    assert "the panel was asked how many processes it holds and did not answer" in line.message
    assert "restart the container" in line.remedy


# ── the one reader, run ─────────────────────────────────────────────────────────────────────────

def _script(cgroup: pathlib.Path, proc: pathlib.Path) -> PidCount:
    """`PIDS_SCRIPT` as a container runs it, in this machine's `sh`, over a cgroup and a `/proc`
    of the test's own."""
    done = subprocess.run(["sh", "-c", doctor.PIDS_SCRIPT, "sh", str(cgroup), str(proc)],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return doctor.parse_pid_script("here", done.stdout)


def _proc(tmp_path: pathlib.Path, stats: dict[str, str]) -> pathlib.Path:
    proc = tmp_path / "proc"
    for pid, stat in stats.items():
        (proc / pid).mkdir(parents=True)
        (proc / pid / "stat").write_text(stat + "\n")
    return proc


def test_the_cgroup_is_read_on_v2_and_on_v1_and_max_is_unlimited(tmp_path: pathlib.Path):
    proc = _proc(tmp_path, {"1": "1 (python) S 0 1 1"})
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "pids.current").write_text("41\n")
    (v2 / "pids.max").write_text("17435\n")
    assert _script(v2, proc) == PidCount("here", 41, 17435, 0)

    (v2 / "pids.max").write_text("max\n")
    assert _script(v2, proc) == PidCount("here", 41, None, 0)

    v1 = tmp_path / "v1"
    (v1 / "pids").mkdir(parents=True)
    (v1 / "pids" / "pids.current").write_text("7\n")
    (v1 / "pids" / "pids.max").write_text("4096\n")
    assert _script(v1, proc) == PidCount("here", 7, 4096, 0)

    assert _script(tmp_path / "none", proc) == PidCount("here", zombies=0), "no pids controller"


def test_a_zombie_is_read_after_the_commands_last_parenthesis(tmp_path: pathlib.Path):
    """`pid (comm) state …` — and a command may carry `) Z ` in its own name: `60 (a) Z (b) S` is
    a sleeping process, which the panel's reader counted as a zombie (review of #572)."""
    proc = _proc(tmp_path, {"1": "1 (python) S 0 1 1", "57": "57 (git) Z 1 57 1",
                            "58": "58 (git) Z 1 58 1", "60": "60 (a) Z (b) S 1 60 1",
                            "61": "61 (a) S (b) Z 1 61 1", "62": "62 (c) Z (d) R 1 62 1",
                            "self": "99 (x) Z 1"})

    assert _script(tmp_path / "none", proc).zombies == 3


def test_the_count_forks_nothing_per_process(tmp_path: pathlib.Path):
    """REVIEW OF #572: it forked a `cat` per `/proc` entry, 0.6 ms a process — eleven seconds at
    the 17,420 the panel held, against a twenty-second timeout. Read by the shell's own `read`, the
    count holds no command per process."""
    proc = _proc(tmp_path, {str(n): f"{n} (git) Z 1 {n} 1" for n in range(2, 3002)})

    started = time.monotonic()
    assert _script(tmp_path / "none", proc).zombies == 3000
    assert time.monotonic() - started < 5, "the count costs a process per process again"
    assert not re.search(r"\$\((?!\()|`|\bcat\b", doctor.PIDS_SCRIPT), "a command per process"


def test_the_script_runs_in_a_posix_shell_on_this_machine():
    """RUN, NOT READ: against this machine's own cgroup and `/proc`, what it prints must parse."""
    done = subprocess.run(["sh", "-c", doctor.PIDS_SCRIPT], capture_output=True, text=True,
                          timeout=30)

    assert done.returncode == 0, done.stderr
    read = doctor.parse_pid_script("here", done.stdout)
    assert not read.unread and read.zombies is not None and read.zombies >= 0, done.stdout


def test_a_container_with_no_pids_controller_still_counts_its_zombies():
    assert doctor.parse_pid_script("panel", "4\n") == PidCount("panel", zombies=4)
    assert doctor.parse_pid_script("panel", "9\nmax\n0\n") == PidCount("panel", 9, None, 0)


# ── which containers it asks, and how ───────────────────────────────────────────────────────────

class _Docker:
    """Answers `sh -c` here and `docker inspect` / `docker exec` on the panel, as set per test."""

    def __init__(self, *, here="41\n17435\n0\n", running="true", panel="12\n17435\n3\n"):
        self.asked: list[list[str]] = []
        self.here, self.running, self.panel = here, running, panel

    def __call__(self, argv):
        self.asked.append(argv)
        if argv[0] == "sh":
            return self._done(self.here)
        if argv[:2] == ["docker", "inspect"]:
            return self._done(self.running)
        return self._done(self.panel)

    @staticmethod
    def _done(answer):
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, SimpleNamespace):
            return answer
        return SimpleNamespace(returncode=0, stdout=answer, stderr="")


def test_the_container_it_runs_in_is_read_only_inside_a_pids_cgroup(tmp_path: pathlib.Path):
    """`/.dockerenv` is Docker's file; a pids cgroup is the container, whatever started it."""
    assert doctor.pid_counts(in_container=False, panel="", run=_Docker()) == []
    assert not doctor.in_a_pids_cgroup(tmp_path)
    (tmp_path / "pids.current").write_text("1\n")
    assert doctor.in_a_pids_cgroup(tmp_path)


@pytest.mark.parametrize(("role", "label"), [("worker", "worker"), ("panel", "panel"),
                                             ("", "container box-7")])
def test_the_container_it_runs_in_is_named_as_its_service_declares(monkeypatch, role, label):
    """REVIEW OF #572: it was "the worker" wherever the doctor ran — run in the panel, the line
    named the worker for the panel's own processes. The role the service declares, else the
    hostname."""
    import socket

    monkeypatch.setenv("OPENFACTORY_ROLE", role)
    monkeypatch.setattr(socket, "gethostname", lambda: "box-7")

    [here] = doctor.pid_counts(in_container=True, panel="", run=_Docker())

    assert here == PidCount(label, 41, LIMIT, 0)


def test_run_in_the_panel_the_panel_is_not_asked_twice(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_ROLE", "panel")
    docker = _Docker()

    counts = doctor.pid_counts(in_container=True, panel="openfactory-panel", run=docker)

    assert counts == [PidCount("panel", 41, LIMIT, 0)]
    assert not [a for a in docker.asked if a[0] == "docker"]


def test_the_panel_is_asked_through_docker_exec_and_read_back():
    docker = _Docker()

    [panel] = doctor.pid_counts(in_container=False, panel="openfactory-panel", run=docker)

    assert panel == PidCount("panel", 12, LIMIT, 3)
    assert docker.asked[-1][:4] == ["docker", "exec", "openfactory-panel", "sh"]


@pytest.mark.parametrize(("docker", "expected"), [
    (_Docker(running=SimpleNamespace(returncode=1, stdout="",
                                     stderr="Error: No such object: openfactory-panel\n")),
     PidCount("panel", unread="Error: No such object: openfactory-panel")),
    (_Docker(running="false"), PidCount("panel", unread="it is not running")),
    (_Docker(running=FileNotFoundError("docker")), PidCount("panel", unread="docker")),
    (_Docker(panel="garbage\n"), PidCount("panel", unread="it answered 'garbage'")),
], ids=["not-there", "stopped", "no-docker", "garbled"])
def test_a_panel_that_could_not_be_asked_is_unread(docker, expected):
    [panel] = doctor.pid_counts(in_container=False, panel="openfactory-panel", run=docker)
    assert panel == expected


@pytest.mark.parametrize(("docker", "silent"), [
    (_Docker(panel=subprocess.TimeoutExpired(["docker"], 20)), "it did not answer in 20s"),
    (_Docker(panel=SimpleNamespace(returncode=126, stdout="", stderr=(
        "OCI runtime exec failed: exec failed: unable to start container process: "
        "fork/exec /bin/sh: resource temporarily unavailable"))),
     "OCI runtime exec failed: exec failed: unable to start container process: fork/exec "
     "/bin/sh: resource temporarily unavail"),
], ids=["timed-out", "could-not-start-the-shell"])
def test_a_running_panel_that_did_not_answer_is_silent(docker, silent):
    """The state the check exists for: the panel is there, running, and too full to answer."""
    [panel] = doctor.pid_counts(in_container=False, panel="openfactory-panel", run=docker)
    assert panel == PidCount("panel", silent=silent)


def test_the_container_it_runs_in_that_could_not_run_the_count_is_silent(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_ROLE", "worker")
    docker = _Docker(here=BlockingIOError(11, "Resource temporarily unavailable"))

    [here] = doctor.pid_counts(in_container=True, panel="", run=docker)

    assert here.container == "worker" and "Resource temporarily unavailable" in here.silent


def test_the_doctor_a_deployment_runs_asks_it(tmp_path: pathlib.Path):
    """The real probe set, not only the pinned one: a check no deployment's doctor asks is a test
    of a function, and the 17,420 zombies stayed invisible exactly that way."""
    from openfactory.contracts.project import Project

    probes = doctor.probes_for(Project(name="acme", repo_path=str(tmp_path)))

    assert probes.pid_counts is doctor.pid_counts

"""`openfactory doctor` sees a container of the stack filling up with processes (#532).

A panel whose PID 1 reaped no orphan held 17,420 zombies after 39 hours, against a `pids.max` of
17,435. It could start no thread, the floor read the engine as unreachable, and the doctor passed
the whole time: nothing in the stack read the count. The containers now start an init (the other
half of #532); `pid_headroom` is what sees the next leak, whatever its source, before the ceiling.

It reads the container the doctor runs in — the worker, as `docker compose exec worker openfactory
doctor` runs it — from its own cgroup and `/proc`, and the panel through `docker exec` on the
socket the worker holds. It FAILS at half the ceiling, or at a hundred zombies whatever the
ceiling, and says an unread container in a note rather than as a failure of the stack.
"""

from __future__ import annotations

import dataclasses
import pathlib
import subprocess
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


# ── what it reads in the container it runs in ───────────────────────────────────────────────────

def test_the_cgroup_is_read_on_v2_and_on_v1_and_max_is_unlimited(tmp_path: pathlib.Path):
    v2 = tmp_path / "v2"
    v2.mkdir()
    (v2 / "pids.current").write_text("41\n")
    (v2 / "pids.max").write_text("17435\n")
    assert doctor.cgroup_pids(v2) == (41, 17435)

    (v2 / "pids.max").write_text("max\n")
    assert doctor.cgroup_pids(v2) == (41, None)

    v1 = tmp_path / "v1"
    (v1 / "pids").mkdir(parents=True)
    (v1 / "pids" / "pids.current").write_text("7\n")
    (v1 / "pids" / "pids.max").write_text("4096\n")
    assert doctor.cgroup_pids(v1) == (7, 4096)

    assert doctor.cgroup_pids(tmp_path / "none") == (None, None)


def test_a_zombie_is_read_after_the_commands_last_parenthesis(tmp_path: pathlib.Path):
    """`pid (comm) state …` — and a command may carry `) Z ` in its own name."""
    for pid, stat in {"1": "1 (python) S 0 1 1", "57": "57 (git) Z 1 57 1",
                      "58": "58 (git) Z 1 58 1", "60": "60 (a) Z (b) S 1 60 1",
                      "self": "99 (x) Z 1"}.items():
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "stat").write_text(stat + "\n")

    assert doctor.zombie_count(tmp_path) == 2


def test_the_worker_is_read_only_inside_a_container(monkeypatch):
    monkeypatch.setattr(doctor, "cgroup_pids", lambda: (41, LIMIT))
    monkeypatch.setattr(doctor, "zombie_count", lambda: 0)

    assert doctor.pid_counts(in_container=False, panel="") == []
    assert doctor.pid_counts(in_container=True, panel="") == [PidCount("worker", 41, LIMIT, 0)]


# ── what it asks the panel ──────────────────────────────────────────────────────────────────────

def test_the_panel_is_asked_through_docker_exec_and_read_back():
    asked = []

    def run(argv):
        asked.append(argv)
        return SimpleNamespace(returncode=0, stdout="12\n17435\n3\n", stderr="")

    [panel] = doctor.pid_counts(in_container=False, panel="openfactory-panel", run=run)

    assert panel == PidCount("panel", 12, LIMIT, 3)
    assert asked[0][:4] == ["docker", "exec", "openfactory-panel", "sh"]


@pytest.mark.parametrize(("done", "unread"), [
    (SimpleNamespace(returncode=1, stdout="", stderr="Error: No such container: openfactory-panel\n"),
     "Error: No such container: openfactory-panel"),
    (SimpleNamespace(returncode=0, stdout="garbage\n", stderr=""), "it answered 'garbage'"),
])
def test_a_panel_that_could_not_say_is_unread(done, unread):
    [panel] = doctor.pid_counts(in_container=False, panel="openfactory-panel",
                                run=lambda argv: done)
    assert panel == PidCount("panel", unread=unread)


def test_a_panel_with_no_pids_controller_still_counts_its_zombies():
    assert doctor.parse_pid_script("panel", "4\n") == PidCount("panel", zombies=4)
    assert doctor.parse_pid_script("panel", "9\nmax\n0\n") == PidCount("panel", 9, None, 0)


def test_the_script_the_panel_is_asked_runs_in_a_posix_shell():
    """RUN, NOT READ: the script is a string a container's `sh` executes, so it is executed here,
    against this machine's own cgroup and `/proc`, and what it prints must parse."""
    done = subprocess.run(["sh", "-c", doctor._PIDS_SCRIPT], capture_output=True, text=True,
                          timeout=30)

    assert done.returncode == 0, done.stderr
    read = doctor.parse_pid_script("here", done.stdout)
    assert not read.unread and read.zombies is not None and read.zombies >= 0, done.stdout


def test_the_doctor_a_deployment_runs_asks_it(tmp_path: pathlib.Path):
    """The real probe set, not only the pinned one: a check no deployment's doctor asks is a test
    of a function, and the 17,420 zombies stayed invisible exactly that way."""
    from openfactory.contracts.project import Project

    probes = doctor.probes_for(Project(name="acme", repo_path=str(tmp_path)))

    assert probes.pid_counts is doctor.pid_counts

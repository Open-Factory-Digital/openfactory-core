"""Where the FACTORY runs is one question, and `local` needs nothing but this machine (D9).

`init` asked which vendors a deployment uses and never asked the question underneath them: where
does the factory itself run? There was one answer in the code — a compose stack — and every path
led to it: the file was named for it, the closing line told you to bring it up, and the credential
it asked for existed because a CLI has to authenticate inside a container with no human at a
browser.

WHAT IS PROVEN HERE:

  · the runtime is the FIRST question, and its vocabulary is read live — `local`, `compose`, and
    whatever box an add-on installed;
  · `local` renders the four switches and asks for **no credential at all**: no token row, no PAT
    row, no vendor line, and a to-do that is a check rather than a paste;
  · the declaration `OPENFACTORY_OWN_WORK` is written on `local` and **never** on `compose`, and
    it is what lets the durable path run in a box that bounds only the code state — a deployment
    that has not said it is still refused, by name;
  · `openfactory up` starts the worker only where there is an engine for it to work for, and the
    panel either way;
  · the doctor names which processes answer, and asks only where they are this operator's to
    start.
"""

from __future__ import annotations

import os
import re

import pytest

from openfactory import doctor, own_work
from openfactory.adapters.sandbox.registry import durable_refusal
from openfactory.onboarding.deployment import QUESTIONS, Answers, Probes, render
from tests.pinned_probes import a_fully_pinned_probe_set

_ROW = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.M)


def _rows(text: str) -> list[str]:
    """The variable NAMES the file actually carries — never the prose around them."""
    return _ROW.findall(text)


@pytest.fixture
def local(tmp_path) -> str:
    return render(Answers(), Probes(home=lambda: str(tmp_path))).text


# ── the question ────────────────────────────────────────────────────────────────────────────────

def test_where_the_factory_runs_is_asked_FIRST():
    """It decides which of the others are worth asking: on `local` there is no vendor to
    authenticate to and no container runtime to install."""
    first = QUESTIONS[0]

    assert first.flag == "runtime"
    assert first.default == "local"
    assert "local" in first.options and "compose" in first.options


def test_the_vocabulary_is_READ_not_written_here():
    """A hand-written list is a copy that stops being true the day somebody installs an add-on —
    the defect this generator's own help text already paid for once."""
    from openfactory import plugins
    from openfactory.adapters.sandbox.registry import AXIS, BOXES

    offered = set(QUESTIONS[0].options)
    installed = {k for k in plugins.known(AXIS, BOXES) if k not in ("worktree", "container")}

    assert installed <= offered, f"a box an add-on installed is not offered: {installed - offered}"


def test_an_answer_outside_the_vocabulary_is_refused_by_name():
    from openfactory.onboarding.deployment import UnknownAnswer

    with pytest.raises(UnknownAnswer, match="runtime"):
        Answers(runtime="on-my-fridge").validate()


# ── what `local` renders ────────────────────────────────────────────────────────────────────────

def test_the_local_runtime_asks_for_NO_CREDENTIAL(local):
    """Not one row a person has to fill. The harness signs in with the login on this machine, and
    a file that asked for a token nothing reads would make a working install look unfinished."""
    vendor_rows = [name for name in _rows(local)
                   if any(word in name for word in ("TOKEN", "KEY", "PAT", "SECRET"))
                   and name != "OPENFACTORY_PANEL_TOKEN"]

    assert vendor_rows == [], f"{vendor_rows} are credentials on a runtime that needs none"
    assert "github" not in local.lower()
    # THE PANEL'S OWN SECRET IS NOT A VENDOR'S, and it is the one row that may carry the word:
    # empty means the panel is open, which is the documented default on a laptop and is generated
    # rather than fetched when the person says it is exposed. Nothing to go and get either way.
    assert "OPENFACTORY_PANEL_TOKEN=\n" in local


def test_the_local_runtime_switches_the_four_things_on(local, tmp_path):
    rows = dict(line.split("=", 1) for line in local.splitlines() if _ROW.match(line))

    assert rows["OPENFACTORY_SANDBOX"] == "worktree"
    assert rows[own_work.VARIABLE] == "1"
    assert rows["TEMPORAL_ADDRESS"] == "localhost:7233"
    assert rows["OPENFACTORY_PANEL_URL"].startswith("http://localhost")
    # ABSOLUTE, NOT `~`: this file is read by processes, not by a shell.
    assert rows["OPENFACTORY_REGISTRY"] == f"{tmp_path}/.openfactory/registry.yaml"
    assert rows["OPENFACTORY_BOARD_DB"] == f"{tmp_path}/.openfactory/board.db"


def test_the_to_do_on_this_runtime_is_a_CHECK_not_a_paste(local):
    """An EMPTY list would read as "nothing is needed", and a harness nobody signed in fails at
    the first card with the money already spent getting there."""
    todo = render(Answers()).remaining

    assert len(todo) == 1
    assert "signed in" in todo[0] and "paste" not in todo[0]


def test_what_this_runtime_gives_up_is_IN_THE_FILE(local):
    """A person who chose this runtime should be able to read what they chose, in the thing they
    chose it with — not in a release note."""
    assert "with YOUR rights" in local
    assert "worktree" in local


def test_compose_NEVER_declares_that_the_work_is_its_own():
    """The declaration is about somebody's own machine. A compose stack that had it written by
    the generator would hand the durable path a box that bounds nothing, on a deployment where
    the worker is shared infrastructure."""
    hosted = render(Answers(runtime="compose", forge="github", tracker="github",
                            harness="claude_code"))

    assert own_work.VARIABLE not in hosted.text
    assert "CLAUDE_CODE_OAUTH_TOKEN" in _rows(hosted.text), "the hosted door lost its credential"


# ── the declaration, and the one predicate that reads it ────────────────────────────────────────

def test_a_durable_job_in_a_box_that_bounds_nothing_is_refused_by_name(monkeypatch):
    monkeypatch.delenv(own_work.VARIABLE, raising=False)

    why = durable_refusal("worktree")

    assert "worktree" in why and own_work.VARIABLE in why, why


def test_the_declaration_is_what_lets_it_through(monkeypatch):
    monkeypatch.setenv(own_work.VARIABLE, "1")

    assert durable_refusal("worktree") == ""
    assert durable_refusal("container") == "", "the isolating box never needed the declaration"


def test_the_declaration_does_not_invent_a_box_that_does_not_exist(monkeypatch):
    """The registry's own answer stands: a typo is still a typo on somebody's own machine."""
    monkeypatch.setenv(own_work.VARIABLE, "1")

    assert "nosuchbox" in durable_refusal("nosuchbox")


@pytest.mark.parametrize("value,heard", [("1", True), ("true", True), ("YES", True),
                                         ("0", False), ("", False), ("maybe", False)])
def test_the_declaration_is_read_the_same_way_everywhere(monkeypatch, value, heard):
    monkeypatch.setenv(own_work.VARIABLE, value)

    assert own_work.declared() is heard


# ── the three processes ─────────────────────────────────────────────────────────────────────────

def test_up_starts_the_worker_only_where_there_is_an_ENGINE_to_work_for(monkeypatch, tmp_path):
    """A worker with nothing to connect to exits within seconds, and one dying process ends the
    set — so on a machine with no `temporal` binary this command would have delivered NOTHING,
    which is the opposite of what it promises."""
    from openfactory.runtime import host

    without = [name for name, _ in host.processes(panel_port=8788, state=tmp_path, engine=None)]
    with_engine = [name for name, _ in
                   host.processes(panel_port=8788, state=tmp_path, engine="/usr/bin/temporal")]

    assert without == ["panel"], f"the worker was planned with no engine to connect to: {without}"
    assert with_engine == ["engine", "worker", "panel"], with_engine


def test_the_doctor_says_which_processes_answer():
    up = doctor.diagnose(a_fully_pinned_probe_set())
    finding = next(f for f in up.findings if f.check == "processes")

    assert finding.ok and "durable engine answers" in finding.message
    assert "WORKER" in finding.note, "the one that holds no port must be named as unmeasured"


def test_a_stopped_engine_is_a_FINDING_not_a_silence():
    """Without an engine the attended commands still work and the panel still serves: the
    deployment looks healthy from every surface a person checks."""
    report = doctor.diagnose(a_fully_pinned_probe_set(
        processes=lambda: {"engine": (False, "localhost:7233"),
                           "panel": (True, "http://localhost:8787")}))
    finding = next(f for f in report.findings if f.check == "processes")

    assert not finding.ok
    assert "merge gate" in finding.message and "openfactory up" in finding.remedy


def test_the_doctor_asks_about_processes_only_where_they_are_THIS_operators(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="mine", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="mine")))
    project = registry.get("mine")

    monkeypatch.delenv(own_work.VARIABLE, raising=False)
    assert doctor.probes_for(project).processes is None, (
        "a hosted deployment would be told its stack is down by somebody else's doctor")

    monkeypatch.setenv(own_work.VARIABLE, "1")
    assert doctor.probes_for(project).processes is not None


def test_the_deployments_own_file_is_the_FLOOR_not_the_ceiling(tmp_path, monkeypatch):
    """`.env` in this shell wins; `~/.openfactory/env` fills in the rest. A person debugging with
    one exported variable must not have to edit a file to be heard."""
    from openfactory import cli

    home = tmp_path / "home"
    (home / ".openfactory").mkdir(parents=True)
    (home / ".openfactory" / "env").write_text(
        "OPENFACTORY_SANDBOX=worktree\nOPENFACTORY_PANEL_URL=http://localhost:8787\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")   # what this shell exported
    monkeypatch.delenv("OPENFACTORY_PANEL_URL", raising=False)

    cli._load_environment()

    assert os.environ["OPENFACTORY_SANDBOX"] == "container", "the file overrode a live value"
    assert os.environ["OPENFACTORY_PANEL_URL"] == "http://localhost:8787"

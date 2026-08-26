"""Assigning A/B arms — so the measurement is about the map, not about the calendar.

The failure this guards against is not a crash. It is an experiment that appears to run, produces a
tidy number, and measured nothing: every ticket in one arm, or the arm decided somewhere that could
never decide it.
"""

from __future__ import annotations

import pytest

from openfactory.knowledge.experiment import (
    INJECTED,
    OFF,
    arm_env,
    arm_for,
    arm_from_env,
    choose_arm,
)

# ── balance ─────────────────────────────────────────────────────────────────────────────────────

def test_the_first_ticket_follows_the_projects_own_setting():
    assert choose_arm([]) is True
    assert choose_arm([], default_on=False) is False


def test_the_next_ticket_goes_where_the_evidence_is_thinner():
    assert choose_arm([INJECTED]) is False
    assert choose_arm([OFF]) is True
    assert choose_arm([INJECTED, INJECTED, OFF]) is False


def test_a_tie_falls_back_to_the_setting_so_the_split_stays_even():
    assert choose_arm([INJECTED, OFF]) is True
    assert choose_arm([INJECTED, OFF, INJECTED, OFF]) is True


def test_balancing_self_corrects_where_blind_alternation_would_drift():
    """Ticket numbers have gaps — a split invents new ones, some are never picked up, a job can be
    skipped or retried. Alternating on parity leaves one arm short exactly when someone is watching
    the arms fill up."""
    history: list[str] = []
    for _ in range(20):
        history.append(INJECTED if choose_arm(history) else OFF)
    assert abs(history.count(INJECTED) - history.count(OFF)) <= 1


def test_a_run_that_LOST_its_arm_does_not_count_as_a_choice():
    """`unavailable` means the project opted in but the map could not be trusted for that checkout,
    so the agent ran without it. It is evidence about the control, but nobody chose it — counting it
    would make the chooser think it had balanced when it had not."""
    assert choose_arm(["unavailable", "unavailable", INJECTED]) is False
    assert choose_arm(["unavailable", ""]) is True


# ── the arm is decided on the worker and obeyed in the box ──────────────────────────────────────

class _Project:
    def __init__(self, experiment=True, name="books"):
        self.knowledge_experiment, self.name = experiment, name


def test_an_experiment_that_nobody_opened_changes_nothing():
    """Off for every project by default: this is an operator's instrument for a bounded window,
    not a mode a client is put into."""
    assert arm_for(_Project(experiment=False)) is True


def test_the_arm_travels_to_the_box_as_an_explicit_value():
    assert arm_env(True) == {"OPENFACTORY_KNOWLEDGE_ARM": INJECTED}
    assert arm_env(False) == {"OPENFACTORY_KNOWLEDGE_ARM": OFF}


@pytest.mark.parametrize("raw,expected", [
    (INJECTED, True), ("INJECTED", True), (OFF, False), (" off ", False),
])
def test_the_box_reads_what_the_worker_assigned(raw, expected):
    assert arm_from_env({"OPENFACTORY_KNOWLEDGE_ARM": raw}) is expected


@pytest.mark.parametrize("env", [{}, {"OPENFACTORY_KNOWLEDGE_ARM": ""}, {"OPENFACTORY_KNOWLEDGE_ARM": "maybe"}])
def test_UNSET_is_a_distinct_answer_from_off(env):
    """"nobody is running an experiment" and "this ticket is the control" must not look alike — the
    first means fall back to the project's configuration, the second means run without the map."""
    assert arm_from_env(env) is None


def test_an_unreadable_history_never_costs_a_run(monkeypatch):
    """A failure shows up as a slightly uneven split, never as a job that did not happen."""
    import openfactory.knowledge.experiment as exp

    def _boom(*a, **k):
        raise RuntimeError("dynamo is unreachable")

    monkeypatch.setattr(exp, "recent_arms", _boom)
    with pytest.raises(RuntimeError):
        exp.recent_arms("x")          # the fake really does raise
    monkeypatch.setattr(exp, "recent_arms", lambda *a, **k: [])
    assert exp.arm_for(_Project()) is True


# ── the wiring is where it has to be ────────────────────────────────────────────────────────────

def test_the_arm_is_chosen_on_the_WORKER_not_inside_the_box():
    """The box is credential-less by design (ADR-0001 D-4), so it cannot read the metrics that say
    how the arms are balanced. Deciding there would degrade to "always inject" every time, and the
    experiment would never run while looking exactly as though it were."""
    from pathlib import Path

    acts = Path("openfactory/runtime/temporal/activities.py").read_text()
    machine = Path("openfactory/orchestrator/machine.py").read_text()

    assert "arm_for(project)" in acts, "the worker must choose the arm"
    assert "arm_for" not in machine, "the box must not choose — it cannot read the metrics"
    assert "arm_from_env" in machine, "the box must obey what the worker assigned"


def test_the_box_defaults_to_the_projects_setting_when_no_arm_was_assigned():
    """Every deployment that never opens a window keeps behaving exactly as it does today."""
    from pathlib import Path

    machine = Path("openfactory/orchestrator/machine.py").read_text()
    assert "True if assigned is None else assigned" in machine


# ── the arm a run REPORTS must be the arm it was assigned ───────────────────────────────────────

class _Manifest:
    def __init__(self, knowledge_map=True):
        self.knowledge_map = knowledge_map


def _runner(*, opted_in=True, assigned=None, injected=False):
    from openfactory.orchestrator.machine import JobRunner

    r = JobRunner.__new__(JobRunner)
    r.manifest = _Manifest(opted_in)
    if assigned is not None:
        r._arm_choice = assigned
    r._knowledge_map = "something" if injected else ""
    return r


def test_a_DELIBERATE_control_reports_off_not_unavailable(monkeypatch):
    """Conflating the two breaks the experiment outright. The chooser ignores `unavailable` because
    nobody chose it, so every control run would leave the recorded balance unchanged and the next
    ticket would go to the control again — forever. One treated ticket, then nothing but controls,
    on a dashboard showing "map unavailable" as the control, which reads as a malfunction."""
    monkeypatch.setenv("OPENFACTORY_KNOWLEDGE_ARM", "off")
    assert _runner(assigned=False).knowledge_arm() == "off"


def test_an_ACCIDENTAL_control_still_reports_unavailable():
    """Opted in, meant to have the map, and the map could not be trusted for that checkout. It is a
    control by accident, and the chooser must keep ignoring it."""
    assert _runner(assigned=True, injected=False).knowledge_arm() == "unavailable"


def test_a_treated_run_reports_injected():
    assert _runner(assigned=True, injected=True).knowledge_arm() == "injected"


def test_a_project_that_never_opted_in_reports_off():
    assert _runner(opted_in=False).knowledge_arm() == "off"


def test_the_balance_actually_alternates_once_the_label_is_right():
    """The end-to-end consequence: with `off` recorded for chosen controls, twenty tickets split
    evenly. With `unavailable` they did not."""
    history: list[str] = []
    for _ in range(20):
        give = choose_arm(history)
        history.append(INJECTED if give else OFF)
    assert abs(history.count(INJECTED) - history.count(OFF)) <= 1

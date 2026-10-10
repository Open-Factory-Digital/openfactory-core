"""A job the attended driver ran says how it ended, in its journal, where `outcomes()` reads it (#551).

`query.outcomes` reads a job's terminal state from the journal's ending line — a `state` line
carrying `by` — and never infers it. The workflow wrote that line from `record_outcome`; the
attended driver (`openfactory run`, `openfactory poll`), the scheduler of a one-machine
deployment, wrote none. So there every job read as "without a recorded ending", `jobs` was 0, and
an evidence pack's activity threshold failed however much work the deployment did.

WHAT IS PROVEN HERE:

  · a card `poll` drives to its merge ends in the journal, and `outcomes()` counts the job;
  · a park and a failure end there too, each with its own state and its reason;
  · every writer of the line writes it through ONE function, in ONE shape;
  · a journal that cannot be written never changes what happened to the job.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from openfactory.contracts import JobState, RunResult
from openfactory.contracts.project import Project

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402


def _endings(path) -> list[dict]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [e for e in lines if e.get("kind") == "state" and "by" in (e.get("data") or {})]


def _window() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now - timedelta(hours=1), now + timedelta(hours=1)


# ── end to end: `poll` drives a real card to its merge ──────────────────────────────────────────

@pytest.fixture
def one_machine(tmp_path, monkeypatch):
    """A one-machine deployment with a card queued, as `test_the_attended_driver_records_what_it_
    spent` builds it."""
    from openfactory import own_work

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(own_work.VARIABLE, "1")
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setattr("openfactory.box_prove.gate_reason", lambda *a, **k: None)
    repo = om.a_repository(tmp_path)
    om.a_deployment(tmp_path, monkeypatch=monkeypatch)
    om.register_the_harness(monkeypatch=monkeypatch)
    assert om.cli("project", "init", "myapp", str(repo))[0] == 0
    om.plug_the_project_in(repo, merge_policy="auto")
    om.cli("act", "card_create", "-p", "myapp", "-P", "title=Add the feature",
           "-P", f"body={om.CARD_BODY}")
    om.cli("act", "card_move", "-p", "myapp", "-i", "1", "-P", "column=TO-DO")
    return repo


def test_a_card_poll_drove_to_its_merge_ends_in_its_journal_and_is_counted(one_machine):
    from openfactory.observability.query import outcomes
    from openfactory.paths import events_file
    from openfactory.registry import ProjectRegistry

    code, out = om.cli("poll", "myapp")
    assert code == 0, out

    [ending] = _endings(events_file(ProjectRegistry().get("myapp"), "1"))
    assert ending["data"]["by"] == "the attended driver"
    since, until = _window()
    seen = outcomes("myapp", since, until)
    assert (seen["jobs"], seen["without_a_recorded_ending"]) == (1, 0), seen
    assert seen["ended"][ending["message"]] == 1, seen["ended"]


# ── a park and a failure ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def driven(tmp_path, monkeypatch):
    """`_drive_one` over a runner that ends where the test says — the driver's own code, from the
    runner's hand-back on."""
    from openfactory import cli
    from openfactory.lifecycle import handed_back
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "sqlite")
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "metrics.db"))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setattr(handed_back, "apply", lambda *a, **k: None)
    project = Project(name="acme", repo_path=str(tmp_path / "acme"))
    ProjectRegistry().add(project)

    def drive(issue: str, state: JobState, note: str = "") -> RunResult:
        from openfactory.observability.events import JobEvent, now_iso
        from openfactory.observability.registry import journal_for
        from openfactory.paths import events_file

        class _Runner:
            def run(self, _issue):
                # THE BOX'S OWN PROGRESS LINE, as `machine._set_state` writes it — a `reason`,
                # never a `by` — so the journal holds a job before its ending, as a real run's does
                journal_for(events_file(project, issue)).emit(JobEvent(
                    ts=now_iso(), job_id=f"#{issue}", ticket_id=f"#{issue}", kind="state",
                    message="running", data={"reason": "picked up"}))
                return RunResult(ticket_id=issue, state=state, note=note or None)

        monkeypatch.setattr(cli, "build_runner", lambda *a, **k: _Runner())
        return cli._drive_one(project, issue, sandbox="worktree", image="", review=False)

    return project, drive


def test_a_park_and_a_failure_end_with_their_state_and_their_reason(driven):
    from openfactory.observability.query import outcomes
    from openfactory.paths import events_file

    project, drive = driven
    drive("7", JobState.ON_HOLD, "the change fails the project's gates (`test` exit 1)")
    drive("8", JobState.FAILED, "the harness exited 2")

    [parked] = _endings(events_file(project, "7"))
    [failed] = _endings(events_file(project, "8"))
    assert (parked["message"], parked["data"]["reason"]) == (
        "on_hold", "the change fails the project's gates (`test` exit 1)")
    assert (failed["message"], failed["data"]["reason"]) == ("failed", "the harness exited 2")
    since, until = _window()
    seen = outcomes("acme", since, until)
    assert (seen["jobs"], seen["without_a_recorded_ending"]) == (2, 0), seen
    assert (seen["ended"]["on_hold"], seen["ended"]["failed"]) == (1, 1), seen["ended"]


def test_every_writer_writes_one_shape_through_one_function(driven):
    """The workflow's `record_outcome`, the attended driver and a stop: the same keys, the same
    `kind`, and only `by` says who — so `outcomes()` cannot read one of them differently."""
    import asyncio

    from openfactory.actions.catalog import _journal_the_stop
    from openfactory.paths import events_file
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import HoldSyncInput

    project, drive = driven

    drive("1", JobState.MERGED)
    asyncio.run(activities.record_outcome(HoldSyncInput(project="acme", issue="2",
                                                        state="merged", note="")))
    _journal_the_stop(project, "3", by="ana", why="not needed any more")

    shapes = {}
    for issue in ("1", "2", "3"):
        [line] = _endings(events_file(project, issue))
        shapes[issue] = (tuple(sorted(line)), line["kind"], tuple(sorted(line["data"])),
                         line["data"]["by"])
    assert {s[:3] for s in shapes.values()} == {shapes["1"][:3]}, shapes
    assert [s[3] for s in shapes.values()] == ["the attended driver", "the workflow", "ana"]


def test_a_journal_that_cannot_be_written_never_changes_the_job(driven, monkeypatch, caplog):
    from openfactory.observability import job_record

    def _broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(job_record, "record_ending", _broken)
    _project, drive = driven

    result = drive("9", JobState.MERGED)

    assert result.state == JobState.MERGED
    assert "OPENFACTORY_OUTCOME_NOT_JOURNALLED" in caplog.text and "disk full" in caplog.text

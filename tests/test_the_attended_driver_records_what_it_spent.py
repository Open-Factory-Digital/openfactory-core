"""A job run from the terminal is measured like one the engine ran (found by walking, 2026-09-11).

A real card went all the way through on the one-machine runtime — agent, gates, review, pull
request, merge, Done — and afterwards the deployment's metrics database held ONE row, a channel
message. No `job` row, no `agent_run` row, nothing for the panel's cost view, `metrics_view` or
any yield measurement to read.

The rows were the durable path's alone: the workflow calls a `record_job_metrics` activity when a
ticket finishes. `openfactory run` and `openfactory poll` called nothing — and `poll` is the only
scheduler a one-machine deployment has, on the runtime where the durable engine is optional. The
door with no operations team was the door that measured nothing.

WHAT IS PROVEN HERE:

  · a card driven to Done by `poll` leaves a `job` row and one `agent_run` row per pass;
  · the attempt's own facts are on it — state, wall clock, the pull request;
  · both drivers write through ONE function, so a second spender cannot grow a second answer;
  · telemetry that cannot be written never touches the job.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")
import one_machine as om  # noqa: E402


@pytest.fixture
def measured(tmp_path, monkeypatch):
    """A one-machine deployment whose metrics sink is a file this test can read back."""
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


def _rows(kind: str) -> list[dict]:
    from openfactory.observability.registry import deployment_metrics_sink

    return deployment_metrics_sink().records_of_kind("myapp", kind)


def test_a_card_the_TERMINAL_drove_leaves_a_job_row(measured):
    code, out = om.cli("poll", "myapp")

    assert "→ #1" in out and code == 0, out
    jobs = _rows("job")
    assert len(jobs) == 1, f"the attended driver recorded {len(jobs)} job rows: {jobs}"
    assert jobs[0]["ticket"] == "1"


def test_the_row_carries_what_the_ATTEMPT_did(measured):
    om.cli("poll", "myapp")

    (job,) = _rows("job")
    assert job["state"], "the row does not say how the attempt ended"
    assert job["wall_s"] is not None and job["wall_s"] >= 0, "nothing was timed"
    assert job["pr_url"], "the pull request this job opened is not on its row"


def test_every_agent_PASS_is_its_own_row(measured):
    """The dashboard slices by model and harness, which only a per-invocation row can answer."""
    om.cli("poll", "myapp")

    runs = _rows("agent_run")
    assert runs, "the passes that spent the money were not recorded"
    assert {r["role"] for r in runs} >= {"executor"}, {r["role"] for r in runs}


def test_the_two_drivers_write_through_ONE_function():
    """`deployment_metrics_sink` exists so a second spender could not build a second sink; this is
    the same sentence one caller further in — a second driver must not grow a second answer to
    what a job cost."""
    import inspect

    from openfactory import cli
    from openfactory.runtime.temporal import activities

    assert "record_job(" in inspect.getsource(cli._drive_one)
    assert "record_job(" in inspect.getsource(activities.record_job_metrics)


def test_BOTH_attended_commands_go_through_it():
    """`run` and `poll` are two doors onto the same job, and a guard on one of them would leave
    the other free to forget."""
    import inspect

    from openfactory import cli

    for command in (cli.run, cli.poll):
        # CODE ONLY. Both commands carry a comment quoting the call they used to make, and a
        # scan that reads prose would report the history instead of the behaviour.
        source = "\n".join(line for line in inspect.getsource(command).splitlines()
                           if not line.lstrip().startswith("#"))
        assert "_drive_one(" in source, f"`{command.__name__}` drives a job past the record"
        assert "build_runner(" not in source, (
            f"`{command.__name__}` still builds its own runner, which is how it forgot")


def test_telemetry_that_cannot_be_written_does_not_touch_the_job(measured, monkeypatch):
    """Additive, always: the measurement is worth less than the work it measures. The sink here
    cannot even be BUILT, which is the shape a misconfigured deployment really has."""
    monkeypatch.setattr("openfactory.observability.registry.deployment_metrics_sink",
                        lambda: (_ for _ in ()).throw(RuntimeError("no sink")))

    code, out = om.cli("poll", "myapp")

    assert code == 0 and "done" in out, out
    assert (measured / om.FEATURE).read_text().strip() == om.VALUE

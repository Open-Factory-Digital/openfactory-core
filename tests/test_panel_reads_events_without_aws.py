"""The panel reads a job's events with no AWS configured (C-11c).

The local journal was already tried first and the remote fallback already degraded, so this is
narrower than the card implies — but the remaining behaviour is wrong in a way that matters for a
downloadable product: **the fallback is attempted whenever the journal is merely absent**, which on
a machine with no AWS means an import, a failed credential lookup and an `INFO` line on every
request for a job that has not written its first event yet.

A distribution whose logs are full of "remote events unavailable" teaches its operator that log
lines are noise. That is the same cost as a false alarm anywhere else in this platform: it trains
people to stop reading.

So the fallback is now attempted only when the deployment actually launches boxes remotely — the
one situation in which the journal legitimately lives on a machine the panel cannot see. And
"remotely" is the BOX'S answer (`installed_box_traits(kind).remote`), not a vendor's cluster
variable: the panel used to know one connector by heart, and was blind to any other remote box.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def project(tmp_path, monkeypatch):
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    (tmp_path / "repo").mkdir()
    p = Project(name="demo", repo_path=str(tmp_path / "repo"))
    ProjectRegistry().add(p)
    return p


class _Tail:
    def __init__(self, answer):
        self._answer = answer

    def fetch_new(self):
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def test_a_local_journal_is_read_without_touching_the_remote_box(project, monkeypatch):
    from openfactory.api import app as api
    from openfactory.paths import events_file

    path = events_file(project, "1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"ts":"t","job_id":"1","ticket_id":"1","kind":"state","message":"done"}\n')

    def _never(*_a, **_kw):
        raise AssertionError("the remote box must not be consulted when the journal is right here")

    monkeypatch.setattr(api, "_remote_tail", _never)
    assert api._events("demo", "1")[0]["message"] == "done"


def test_no_journal_and_no_remote_box_does_not_reach_for_the_remote_tail(project, monkeypatch):
    """The card's point. A local deployment has no remote box, so an absent journal means the job
    has not written yet — not that the events are somewhere else."""
    from openfactory.api import app as api

    def _never(*_a, **_kw):
        raise AssertionError("the remote tail was consulted on a deployment that has no remote boxes")

    monkeypatch.setattr(api, "_remote_tail", _never)
    monkeypatch.setattr(api, "_boxes_are_remote", lambda: False)
    assert api._events("demo", "1") == []


def test_no_journal_WITH_a_remote_box_still_reaches_for_the_remote_tail(project, monkeypatch):
    """The behaviour that must not regress: a remote job's journal is on the worker's disk, not
    the panel host's, and the box's own tail is the only place the panel can see it."""
    from openfactory.api import app as api

    monkeypatch.setattr(api, "_boxes_are_remote", lambda: True)
    monkeypatch.setattr(api, "_remote_tail", lambda *_a, **_kw: _Tail([{"message": "from the box"}]))
    assert api._events("demo", "1")[0]["message"] == "from the box"


def test_a_broken_remote_tail_still_degrades_rather_than_500s(project, monkeypatch):
    from openfactory.api import app as api

    monkeypatch.setattr(api, "_boxes_are_remote", lambda: True)
    monkeypatch.setattr(api, "_remote_tail", lambda *_a, **_kw: _Tail(OSError("no credentials")))
    assert api._events("demo", "1") == []


@pytest.mark.parametrize("env,expected", [
    ({}, False),
    ({"OPENFACTORY_FARGATE_CLUSTER": "sdlc"}, False),
    ({"OPENFACTORY_SANDBOX": "fargate"}, True),
    ({"OPENFACTORY_SANDBOX": "container"}, False),
    ({"OPENFACTORY_SANDBOX": "worktree", "OPENFACTORY_FARGATE_CLUSTER": "sdlc"}, False),
])
def test_remote_boxes_are_detected_from_the_deployments_declared_box(monkeypatch, env, expected):
    """The box the deployment DECLARES answers, through its traits. A cluster variable alone used
    to read as "remote" — a vendor's variable deciding what the panel believes about every job."""
    from openfactory.api import app as api

    for k in ("OPENFACTORY_FARGATE_CLUSTER", "OPENFACTORY_SANDBOX"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert api._boxes_are_remote() is expected

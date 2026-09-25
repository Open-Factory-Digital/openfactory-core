"""A preview ends when it should, through the deployment's runtime row, with its logs kept first
(#265 slice 2; ADR-0050 D10; the design's §5.2 "The reaper").

The reaper asks the RUNTIME what is on the daemon — exited stacks included — and ends a unit when
its time is up, when every pull request of it merged or closed (an unreadable one keeps it), when
an exposed service has been down past `keep_failed_minutes`, or when a `starting` record outlived
`start_timeout_minutes`. It sweeps work directories nothing runs behind any more, and prunes where
the runtime keeps caches. A runtime faked in Python; nothing here needs Docker.
"""

from __future__ import annotations

import os
import time

import pytest

from openfactory import preview
from openfactory.contracts.project import PreviewPolicy
from openfactory.preview.plan import RunningPreview
from openfactory.preview.reap import MAX_TTL_HOURS, latest_by_unit, reap

NOW = 1_900_000_000.0
PR = "https://forge.example/acme/shop/pull/12"


class Runtime:
    """The port, faked: what `running()` answers, and every call in the order it was made."""

    def __init__(self, running=(), prunes=False):
        self._running = list(running)
        self.calls: list[tuple] = []
        if prunes:
            self.prune = lambda: (self.calls.append(("prune",)) or ["the build cache"])

    def prerequisites(self):
        return []

    def up(self, plan):
        raise AssertionError("the reaper brought something up")

    def prove(self, plan):
        raise AssertionError("the reaper proved something")

    def watch(self, compose_project):
        return None

    def running(self):
        return list(self._running)

    def logs(self, compose_project, log_dir):
        self.calls.append(("logs", compose_project, log_dir))
        return []

    def down(self, compose_project, workdir):
        self.calls.append(("down", compose_project, workdir))
        return [f"the work directory {workdir}"]


def unit(token="12", *, state="running", expires=NOW + 3600, project="acme"):
    return RunningPreview(compose_project=preview.compose_project(project, token), unit=token,
                          project=project, state=state, expires_at=int(expires),
                          started_at=int(NOW - 600))


def rec(token="12", state=preview.LIVE, **kw):
    return preview.Preview(project="acme", unit=token, state=state, cards=("12",),
                           pr_urls=(PR,), **kw)


@pytest.fixture
def world(tmp_path):
    written: list[preview.Preview] = []

    def run(runtime, *, records=None, status=lambda p, u: "open", policy=None, now=NOW):
        return reap(runtime, policies={"acme": policy or PreviewPolicy()},
                    latest_of=lambda project: records or {}, pr_status=status,
                    record=written.append, now=now, work_root=str(tmp_path),
                    log_dir=lambda project, token: f"/logs/preview--{project}--{token}")

    run.written = written
    run.root = tmp_path
    return run


def _ended(runtime) -> list[str]:
    return [c[1] for c in runtime.calls if c[0] == "down"]


# ── the rules ────────────────────────────────────────────────────────────────────────────────────


def test_a_preview_whose_time_is_up_is_ended_with_its_logs_kept_first(world):
    rt = Runtime([unit(expires=NOW - 1)])

    ended = world(rt, records={"12": rec()})

    assert ended == ["acme 12: its time was up"]
    assert [c[0] for c in rt.calls] == ["logs", "down"], "the stack went down before its logs"
    assert rt.calls[0][2] == "/logs/preview--acme--12"
    assert rt.calls[1][2] == os.path.join(str(world.root), "openfactory-pv-acme-12")
    assert world.written[-1].state == preview.ENDED
    assert world.written[-1].why == "its time was up" and world.written[-1].cards == ("12",)


def test_a_preview_without_an_expiry_is_ended(world):
    rt = Runtime([unit(expires=0)])
    assert world(rt) == ["acme 12: its time was up"]


def test_a_live_preview_whose_pull_request_is_open_is_left(world):
    rt = Runtime([unit()])
    assert world(rt, records={"12": rec()}) == [] and rt.calls == []


@pytest.mark.parametrize("status", ["merged", "closed"])
def test_every_pull_request_merged_or_closed_ends_it(world, status):
    rt = Runtime([unit()])
    ended = world(rt, records={"12": rec()}, status=lambda p, u: status)
    assert ended == ["acme 12: its pull request was merged or closed"]


def test_one_open_pull_request_of_the_unit_keeps_it(world):
    other = "https://forge.example/acme/web/pull/4"
    record = rec().model_copy(update={"pr_urls": (PR, other)})
    rt = Runtime([unit()])

    assert world(rt, records={"12": record},
                 status=lambda p, u: "merged" if u == PR else "open") == []


def test_a_pull_request_that_cannot_be_read_keeps_the_preview(world):
    def unreadable(project, url):
        raise RuntimeError("the forge is down")

    rt = Runtime([unit()])

    assert world(rt, records={"12": rec()}, status=unreadable) == []
    assert rt.calls == []


def test_an_exposed_service_that_stopped_is_recorded_failed_first_and_ended_later(world):
    rt = Runtime([unit(state="failed")])

    assert world(rt, records={"12": rec()}) == []
    assert world.written[-1].state == preview.FAILED and world.written[-1].ended_at == int(NOW)
    assert rt.calls == [], "a stack was taken down the tick it was first seen failing"

    kept = rec(state=preview.FAILED, ended_at=int(NOW) - 60)
    assert world(rt, records={"12": kept}) == [], "taken down before a person could read why"

    old = rec(state=preview.FAILED, ended_at=int(NOW) - 31 * 60)
    ended = world(rt, records={"12": old})
    assert ended == ["acme 12: it failed and was kept 30 minutes for a person to read why"]
    assert [c[0] for c in rt.calls] == ["logs", "down"]


def test_a_unit_still_starting_is_not_judged_by_its_services(world):
    rt = Runtime([unit(state="exited")])
    starting = rec(state=preview.STARTING, started_at=int(NOW) - 60)

    assert world(rt, records={"12": starting}) == [] and rt.calls == []
    assert world.written == []


def test_a_start_that_outlived_its_timeout_is_ended_by_name(world):
    rt = Runtime([])
    stuck = rec(token="13", state=preview.STARTING, started_at=int(NOW) - 31 * 60)
    fresh = rec(token="14", state=preview.STARTING, started_at=int(NOW) - 60)

    ended = world(rt, records={"13": stuck, "14": fresh})

    assert ended == ["acme 13: the worker restarted during the build — it was starting for more "
                     "than 30 minutes"]
    assert [c[:2] for c in rt.calls] == [("logs", "openfactory-pv-acme-13"),
                                         ("down", "openfactory-pv-acme-13")]


def test_a_unit_that_ended_but_is_still_on_the_daemon_is_taken_down(world):
    rt = Runtime([unit(state="exited")])
    assert world(rt, records={"12": rec(state=preview.ENDED)}) == [
        "acme 12: it had ended and was still on the daemon"]


def test_an_unreadable_store_ends_nothing_by_itself(world):
    def broken(project):
        raise RuntimeError("the store is locked")

    rt = Runtime([unit()])
    ended = reap(rt, policies={"acme": PreviewPolicy()}, latest_of=broken,
                 pr_status=lambda p, u: "open", record=world.written.append, now=NOW,
                 work_root=str(world.root), log_dir=lambda p, t: "/logs")
    assert ended == [] and rt.calls == []


# ── what nothing runs behind any more ────────────────────────────────────────────────────────────


def _aged(path, hours):
    stamp = NOW - hours * 3600
    os.utime(path, (stamp, stamp))


def test_an_orphaned_work_directory_is_swept_only_when_old_and_nothing_runs_behind_it(world):
    root = world.root
    old = root / "openfactory-pv-acme-9"
    young = root / "openfactory-pv-acme-10"
    busy = root / "openfactory-pv-acme-12"
    foreign = root / "somebody-else"
    for d in (old, young, busy, foreign):
        d.mkdir()
    link = root / "openfactory-pv-acme-11"
    link.symlink_to(foreign)
    _aged(old, MAX_TTL_HOURS + 1)
    _aged(young, 1)
    _aged(busy, MAX_TTL_HOURS + 1)
    _aged(foreign, MAX_TTL_HOURS + 1)
    rt = Runtime([unit("12")])

    ended = world(rt, records={"12": rec()})

    assert ended == ["openfactory-pv-acme-9: its work directory outlived every preview"]
    assert _ended(rt) == ["openfactory-pv-acme-9"]


def test_a_runtime_that_keeps_caches_is_pruned_every_tick(world):
    rt = Runtime([], prunes=True)
    assert world(rt) == ["the build cache"] and rt.calls == [("prune",)]


# ── the records ──────────────────────────────────────────────────────────────────────────────────


def test_the_newest_row_of_each_unit_is_its_record():
    rows = [
        {"ts": "2026-09-24T01:00:00", "extra": rec(state=preview.STARTING).model_dump()},
        {"ts": "2026-09-24T01:05:00", "extra": rec(state=preview.LIVE).model_dump()},
        {"ts": "2026-09-24T01:02:00", "extra": rec(state=preview.FAILED).model_dump()},
        {"ts": "2026-09-24T01:03:00", "extra": rec(token="13").model_dump()},
        {"ts": "2026-09-24T01:04:00", "extra": {"unit": "14", "state": 3}},
    ]

    latest = latest_by_unit(rows)

    assert set(latest) == {"12", "13"}
    assert latest["12"].state == preview.LIVE


def test_the_reaper_activity_runs_the_rules_through_the_deployments_runtime(monkeypatch,
                                                                             tmp_path):
    """The scheduled tick composes the real world: the row the deployment names, the registry's
    policies, the records, the forge — on a deployment that runs none, nothing is on a daemon and
    a `starting` record a dead worker left is still ended."""
    pytest.importorskip("temporalio")
    import asyncio

    from temporalio.testing import ActivityEnvironment

    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal import activities

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_WORK_DIR", str(tmp_path))
    monkeypatch.delenv("OPENFACTORY_PREVIEW_RUNTIME", raising=False)
    ProjectRegistry().add(Project(name="acme", repo_path=str(tmp_path)))
    stuck = rec(state=preview.STARTING, started_at=int(time.time()) - 3 * 3600)
    monkeypatch.setattr("openfactory.observability.query.records_of_kind",
                        lambda project, kind, **kw: [{"ts": "1", "extra": stuck.model_dump()}])
    written = []
    monkeypatch.setattr(preview, "record", written.append)

    ended = asyncio.run(ActivityEnvironment().run(activities.reap_previews))

    assert ended == ["acme 12: the worker restarted during the build — it was starting for more "
                     "than 30 minutes"]
    assert written[-1].state == preview.ENDED

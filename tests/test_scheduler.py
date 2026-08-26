"""Resume scheduler: when may a rate-limit-paused job come back?"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from openfactory.contracts.project import Project
from openfactory.scheduler import _iso_epoch, ready_to_resume, resume_epoch

_PAUSED = "2026-07-12T10:00:00+00:00"


def test_the_vendors_retry_at_DECIDES_NOTHING():
    """It used to win whenever it parsed and was in the future — and `workflow._pause_backoff`
    refuses it in as many words, because "formats vary, clocks skew" and over-trusting it resumes
    into a still-closed window. The park comment beside it warns that a surface promoting a job
    off `retry_at` "would fire up to 100 minutes before this workflow intended to resume by
    itself". This sweep WAS that surface, and it is the platform's own (#164)."""
    future = "2026-07-12T10:30:00+00:00"

    assert resume_epoch(_PAUSED, future) == resume_epoch(_PAUSED, None)
    assert resume_epoch(_PAUSED, future) != _iso_epoch(future)


def test_and_the_backoff_is_what_decides():
    assert resume_epoch(_PAUSED, "2026-07-12T10:30:00+00:00", backoff_s=600) == (
        _iso_epoch(_PAUSED) + 600)


def test_the_parameter_is_still_ACCEPTED():
    """Deleting it would send the next reader — who has just read the vendor's claim in the park
    payload — looking for another way to hand it over. It is shown on the panel; it decides
    nothing, and that is the whole statement."""
    import inspect

    from openfactory.scheduler import resume_epoch as fn

    assert "retry_at" in inspect.signature(fn).parameters


def test_resume_falls_back_to_backoff_without_retry():
    assert resume_epoch(_PAUSED, None, backoff_s=600) == _iso_epoch(_PAUSED) + 600


def test_resume_ignores_past_retry_and_uses_backoff():
    past = "2026-07-12T09:00:00+00:00"  # before the pause
    assert resume_epoch(_PAUSED, past, backoff_s=600) == _iso_epoch(_PAUSED) + 600


def _write_journal(tmp_path: Path, issue: str, events: list[dict]) -> Project:
    project = Project(name="demo", repo_path=str(tmp_path / "repo"))
    log = tmp_path / ".openfactory-logs" / "demo"
    log.mkdir(parents=True, exist_ok=True)
    (log / f"{issue}-events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    return project


def _paused_events(retry_at: str | None):
    return [
        {"ts": _PAUSED, "kind": "warning", "message": "rate limited",
         "data": {"retry_at": retry_at}},
        {"ts": _PAUSED, "kind": "state", "message": "paused", "data": {}},
    ]


def test_ready_when_reset_passed(tmp_path: Path):
    retry = "2026-07-12T10:30:00+00:00"
    project = _write_journal(tmp_path, "5", _paused_events(retry))
    now = _iso_epoch("2026-07-12T11:00:00+00:00")  # after reset
    assert ready_to_resume(project, now) == ["5"]


def test_not_ready_before_reset(tmp_path: Path):
    retry = "2026-07-12T10:30:00+00:00"
    project = _write_journal(tmp_path, "5", _paused_events(retry))
    now = _iso_epoch("2026-07-12T10:15:00+00:00")  # before reset
    assert ready_to_resume(project, now) == []


def test_non_paused_job_is_not_resumed(tmp_path: Path):
    events = [{"ts": _PAUSED, "kind": "state", "message": "pr_open", "data": {}}]
    project = _write_journal(tmp_path, "6", events)
    assert ready_to_resume(project, datetime.now().timestamp()) == []

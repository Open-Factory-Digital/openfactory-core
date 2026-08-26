"""Resume scheduler — bring PAUSED (rate-limited) jobs back after their reset.

A usage-limit pause is temporary: the job halted with a reset time. The scheduler
finds PAUSED jobs whose resume time has passed (from the journal) so the poller can
re-run them. Reset info from the agent is best-effort, so a default backoff is the
reliable floor; a clean ISO `retry_at` refines it. Pure functions over the journal —
no polling loop here (the poller/cron drives cadence).
"""

from __future__ import annotations

import json
from datetime import datetime

from openfactory.contracts.project import Project
from openfactory.paths import project_log_dir

_DEFAULT_BACKOFF_S = 3600.0  # if the agent gave no usable reset time


def _iso_epoch(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def resume_epoch(
    paused_ts: str, retry_at: str | None = None, backoff_s: float = _DEFAULT_BACKOFF_S
) -> float:
    """When a job paused at `paused_ts` may resume: `paused_ts` plus the backoff.

    `retry_at` IS ACCEPTED AND DELIBERATELY NOT OBEYED (#164), which is the engine's own decision
    stated one file over. `workflow._pause_backoff` refuses to parse it in as many words — "the
    string is adapter/vendor telemetry (formats vary, clocks skew) and over-trusting it risks
    resuming too early into a still-closed window" — and the park comment above it warns that any
    surface promoting a job off `retry_at` "would fire up to 100 minutes before this workflow
    intended to resume by itself".

    This function did exactly that: it preferred `retry_at` whenever it parsed and was in the
    future, so the CLI's resume sweep and the engine disagreed about when the same job was ready.
    Two answers to one question, and the losing one was the platform's own.

    THE PARAMETER STAYS rather than being deleted, and the caller keeps passing it: it is what a
    reader who has just read the vendor's claim expects to hand over, and a signature that refuses
    it would send them looking for another way in. It is shown on the panel; it decides nothing.
    """
    return (_iso_epoch(paused_ts) or 0.0) + backoff_s


def _latest_pause(events: list[dict]) -> tuple[str | None, str | None, str | None]:
    """(current_state, pause_event_ts, retry_at) from a job's journal."""
    state = next((e["message"] for e in reversed(events) if e["kind"] == "state"), None)
    for e in reversed(events):
        if e["kind"] == "warning":
            return state, e["ts"], (e.get("data") or {}).get("retry_at")
    return state, None, None


def ready_to_resume(project: Project, now_epoch: float) -> list[str]:
    """Issue numbers of this project's PAUSED jobs whose resume time has passed."""
    d = project_log_dir(project)
    if not d.exists():
        return []
    ready: list[str] = []
    for f in d.glob("*-events.jsonl"):
        events = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
        if not events:
            continue
        state, paused_ts, retry = _latest_pause(events)
        if state == "paused" and paused_ts and now_epoch >= resume_epoch(paused_ts, retry):
            ready.append(f.name.replace("-events.jsonl", ""))
    return ready

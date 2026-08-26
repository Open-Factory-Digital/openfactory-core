"""A wait the factory imposes on ITSELF is still a wait (pilot, 2026-08-14).

The poller measures the API budget and skips a tick when it is low — right, and invisible: it
said so to a workflow log, so the floor went quiet for up to an hour while the board looked
idle. The operator met the wall from the other side, through an unrelated command, and asked
the question that names the defect: *"what limit? I never got any warning."*

ADR-0038 D2: a wait is a QUESTION, never a state. These hold the three sentences the platform
now owes about a budget:

  1. the poller ANNOUNCES the pause, once per reset window (not once per three-minute tick);
  2. `doctor` prints the budget, and says whose it is when it is nearly gone;
  3. a write that failed on a budget says "waiting", not "open it by hand" — the first clears
     by itself at a known time, the second is work somebody has to do.
"""

from __future__ import annotations

import time

import pytest


def test_the_pause_is_announced_once_per_reset_window(tmp_path, monkeypatch):
    import asyncio

    from openfactory import box_prove
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import RatePauseInput

    monkeypatch.setattr(box_prove, "PROOF_DIR", tmp_path)
    said: list[str] = []

    class _Notifier:
        def notify(self, *, message, level=""):
            said.append(message)

    monkeypatch.setattr(acts.ProjectRegistry, "list",
                        lambda self: [type("_P", (), {"name": "demo"})()])
    monkeypatch.setattr("openfactory.factory.notifier_for_project", lambda p: _Notifier())

    reset = int(time.time()) + 1800
    inp = RatePauseInput(resource="graphql", remaining=12, reset_epoch=reset)

    assert asyncio.run(acts.announce_rate_pause(inp)) is True
    assert asyncio.run(acts.announce_rate_pause(inp)) is False, (
        "the poller ticks every three minutes — an alarm on every tick is one people filter")

    assert len(said) == 1
    assert "not taking cards" in said[0]
    assert "graphql" in said[0] and "12" in said[0]
    assert time.strftime("%H:%M", time.localtime(reset)) in said[0], (
        "the operator is told it will pass, but not WHEN")
    assert "resumes on its own" in said[0], "a wait that sounds permanent gets somebody debugging"


def test_the_NEXT_window_speaks_again(tmp_path, monkeypatch):
    """Once per window, not once ever: an hour later it is a new fact."""
    import asyncio

    from openfactory import box_prove
    from openfactory.runtime.temporal import activities as acts
    from openfactory.runtime.temporal.io import RatePauseInput

    monkeypatch.setattr(box_prove, "PROOF_DIR", tmp_path)
    monkeypatch.setattr(acts.ProjectRegistry, "list",
                        lambda self: [type("_P", (), {"name": "demo"})()])
    monkeypatch.setattr("openfactory.factory.notifier_for_project",
                        lambda p: type("_N", (), {"notify": lambda self, **kw: None})())

    first = RatePauseInput(resource="graphql", remaining=5, reset_epoch=1000)
    later = RatePauseInput(resource="graphql", remaining=5, reset_epoch=4600)

    assert asyncio.run(acts.announce_rate_pause(first)) is True
    assert asyncio.run(acts.announce_rate_pause(later)) is True


def test_the_poller_calls_it_before_it_returns():
    """Reachability: the activity exists and the workflow reaches it — the class this
    repository has paid for sixteen times."""
    import inspect

    from openfactory.runtime.temporal import poller, worker

    # the LIVE arm of the tick — `run` dispatches to it behind `patched("tracker-budgets")`, and
    # the pre-seam arm beside it is replay-only (tests/test_temporal_workflow.py drives both)
    body = inspect.getsource(poller.PollWorkflow._tick_around_each_vendors_budget)
    skip = body[body.index('!= "low"'):body.index('"budget_low"')]
    assert "announce_rate_pause" in skip, (
        "the poller still skips the tick in silence — the log line is not a person")
    assert worker.announce_rate_pause in worker.WORKER_ACTIVITIES, (
        "an activity the workflow calls and the worker does not know about fails at the moment "
        "it is finally needed")


@pytest.mark.parametrize("text, is_wait", [
    ("API rate limit already exceeded for user ID 2326783", True),
    ("You have exceeded a secondary rate limit", True),
    ("HTTP 429: Too Many Requests", True),
    ("GraphQL: Resource not accessible by integration", False),
    ("fatal: repository not found", False),
])
def test_a_budget_wait_is_told_apart_from_a_failure(text, is_wait):
    from openfactory.onboarding.propose_manifest import rate_limited

    assert rate_limited(text) is is_wait


def test_doctor_prints_the_budget_and_whose_it_is():
    from openfactory.adapters.tracker.base import Budget
    from openfactory.doctor import diagnose
    from tests.test_doctor import _probes  # the healthy baseline this suite already keeps

    # `floor` is the ADAPTER's threshold: 11 is low because the vendor said 200 is the line.
    low = diagnose(_probes(api_budget=lambda: Budget(
        resource="graphql", remaining=11, limit=5000, reset_epoch=int(time.time()) + 600,
        floor=200)))
    finding = {f.check: f for f in low.findings}["api_budget"]

    assert not finding.ok
    assert "11/5000" in finding.message
    assert "pauses on its own" in finding.message, "a pause that sounds like a fault"
    assert "YOUR token" in finding.remedy, (
        "on a personal account the board spends the OPERATOR's quota — the remedy must say so")

    healthy = diagnose(_probes(api_budget=lambda: Budget(resource="graphql", remaining=4800,
                                                         limit=5000, floor=200)))
    assert {f.check: f for f in healthy.findings}["api_budget"].ok

"""The screen a person DECIDES on had the poorest answer of the three (#174).

At one instant, three readers of one job — podbeam #107, parked at a human merge gate whose
review had REJECTED the change:

    /api/temporal/jobs            awaiting_your_merge   action merge_wait
    /api/inbox                    awaiting_your_merge   kind merge · "Review rejected it"
    /api/jobs/podbeam/107/detail running               "Still running."

The card-click briefing read the workflow's TEMPORAL STATUS and returned early. A job parked at a
gate is still RUNNING as a workflow — that is the design, single-line strict holds the floor until
the merge lands — so `running` was true about the engine and false about everything a person needs:
no gate, no pull request, no verdict, on the one surface where the decision is taken.

THE QUERIES WERE ALWAYS THERE. `list_jobs` asks them through `_domain_state`, and `verdict` was
published for exactly this (#149: a rejected pull request must not look like an approved one). The
same one-question-two-answers class as the floor and the inbox in #164 — and again the poorer
answer was the one on the deciding surface.
"""

from __future__ import annotations

import types

import pytest

from openfactory.runtime.temporal import view as tv

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _Handle:
    """A workflow parked at a human merge gate, with a rejected review, still RUNNING."""

    def __init__(self, *, action=None, merge=None, approval=False, verdict=None, raises=()):
        self.id, self.run_id = "openfactory-podbeam-107", "run-1"
        self._action, self._merge, self._approval = action, merge, approval
        self._verdict, self._raises = verdict, raises
        self.asked: list[str] = []

    async def describe(self):
        return types.SimpleNamespace(
            status=tv.WorkflowExecutionStatus.RUNNING, id=self.id, run_id=self.run_id,
            start_time=None, close_time=None, memo=None)

    async def query(self, which, *a, **k):
        name = getattr(which, "__name__", str(which))
        self.asked.append(name)
        if name in self._raises:
            raise RuntimeError("the worker is gone")
        return {"awaiting_action": self._action, "awaiting_merge": self._merge,
                "awaiting_approval": self._approval, "verdict": self._verdict}[name]

    async def result(self):  # pragma: no cover — a RUNNING job must never be asked for one
        raise AssertionError("job_detail asked a running workflow for its result")


class _Client:
    def __init__(self, handle):
        self._handle = handle

    def get_workflow_handle(self, wf_id, run_id=None):
        return self._handle


REJECTED = {"decision": "rejected", "score": 42, "summary": "the migration has no rollback"}
GATE = {"auto": False, "pr_url": "https://forge.example/pr/117", "working": False}


async def _detail(handle, monkeypatch):
    monkeypatch.setattr(tv, "_memo_title", lambda desc: _async("t"))
    monkeypatch.setattr(tv, "_true_status", lambda c, wf: _async(tv.WorkflowExecutionStatus.RUNNING))
    monkeypatch.setattr(tv, "_pr_checks", lambda project, url: _async([{"name": "ci", "ok": True}]))
    monkeypatch.setattr(tv, "_ci_provider", lambda project: "GitHub")
    return await tv.job_detail(_Client(handle), "podbeam", "107", "default")


def _async(value):
    async def run():
        return value
    return run()


async def test_the_card_reports_the_GATE_not_the_engines_status(monkeypatch):
    handle = _Handle(merge=GATE, verdict=REJECTED)

    got = await _detail(handle, monkeypatch)

    assert got["state"] == "awaiting_your_merge", (
        f"the deciding screen says {got['state']!r} about a job parked on the person reading it")
    assert got["why"] != "Still running."
    assert got["action"] and got["action"]["kind"] == tv.MERGE_WAIT


async def test_and_it_carries_the_verdict_that_REJECTED_the_change(monkeypatch):
    """#149's whole point, on the surface it was missing from: an approved pull request and a
    rejected one must not produce the same card."""
    handle = _Handle(merge=GATE, verdict=REJECTED)

    got = await _detail(handle, monkeypatch)

    assert (got["review"] or {}).get("decision") == "rejected"
    assert "42" in got["why"] and "REJECTED" in got["why"], got["why"]


async def test_and_the_PULL_REQUEST_it_is_about(monkeypatch):
    """A gate with no address is a decision nobody can take."""
    handle = _Handle(merge=GATE, verdict=REJECTED)

    got = await _detail(handle, monkeypatch)

    assert got["pr_url"] == GATE["pr_url"]
    assert got["ci_checks"], "the checks on the open pull request are not shown"


@pytest.mark.parametrize("kwargs,expected", [
    ({"action": {"state": "on_hold", "kind": "impediment", "note": "no acceptance criteria"}},
     "on_hold"),
    ({"action": {"state": "paused", "kind": "rate_limit", "note": "GitHub rate limit"}}, "paused"),
    ({"approval": True}, "awaiting_prod_approval"),
    ({"merge": {"auto": True, "pr_url": "u", "working": False}}, "merging"),
    ({"merge": {"auto": False, "pr_url": "u", "working": True}}, "repairing"),
])
async def test_every_shape_a_running_job_can_be_PARKED_in(monkeypatch, kwargs, expected):
    """Not only the merge gate. The early return covered every one of these with one word, so a
    production approval and an impediment read exactly like an agent mid-pass."""
    got = await _detail(_Handle(**kwargs), monkeypatch)

    assert got["state"] == expected


async def test_a_job_that_is_GENUINELY_running_still_says_so(monkeypatch):
    """The positive twin. A fix that reported every running job as parked would be the same defect
    facing the other way — and this branch is the common case, not the exception."""
    got = await _detail(_Handle(), monkeypatch)

    assert got["state"] == "running"
    assert got["why"] == "running" or "Still running" in got["why"]


async def test_a_workflow_that_cannot_be_QUERIED_degrades_instead_of_500ing(monkeypatch):
    """Usually a job whose worker is gone. The card must still render — the operator looking at it
    is the person who most needs to see that something is wrong."""
    got = await _detail(_Handle(merge=GATE, raises=("verdict",)), monkeypatch)

    assert got["state"] == "awaiting_your_merge"
    assert got["review"] is None


async def test_the_running_branch_never_asks_for_a_RESULT(monkeypatch):
    """A running workflow has none, and `handle.result()` on one BLOCKS until it finishes — on a
    merge gate that is up to fourteen days, inside a request the panel is waiting on."""
    handle = _Handle(merge=GATE, verdict=REJECTED)

    await _detail(handle, monkeypatch)  # `_Handle.result` raises if it is ever reached

    assert "verdict" in handle.asked

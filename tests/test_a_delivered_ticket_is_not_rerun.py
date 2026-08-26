"""The stale-card guard actually reads a state (audit finding, 2026-08-05).

`scan_todo` refuses to re-run a ticket the tracker has already closed — a card left in the pickup
column after delivery costs a full agent pass and parks the single job slot. The guard was written
(6fb8b78), tested, and could never fire. THREE layers hid it:

    activities.py   getattr(ticket, "state", "open")     ← default answers when the field is absent
    contracts       `Ticket` had no `state` field         ← and pydantic drops unknown keys silently
    github.py       --json number,title,body,labels,author  ← `state` was never even requested

So the condition `state == "open"` was always true, the OPENFACTORY_STALE_PICKUP_CARD branch was
unreachable, and the suite was green because every double INVENTED the attribute the real contract
lacked: `type("_Tk", (), {"state": states[r]})`.

THAT IS WHY THIS FILE USES THE REAL `Ticket`. A guard proven against a fake that has a field the
product does not have proves the fake. Every test here builds the contract the code will actually
receive, and one of them asserts the field exists at all — because absence is what the getattr
default silently forgave.
"""

from __future__ import annotations

import pytest

from openfactory.contracts import Ticket


def _ticket(ref: str, state: str | None) -> Ticket:
    return Ticket(id=ref, title="t", objective="o", repo="o/r", state=state)


# ── the contract can hold the answer ─────────────────────────────────────────────────────────────

def test_the_contract_HAS_a_state_field():
    """The whole defect in one assertion. `getattr(t, "state", "open")` cannot tell a missing
    field from an open ticket, so the guard read its own default forever."""
    assert "state" in Ticket.model_fields


def test_an_unset_state_is_None_not_a_guess():
    """None means "the provider was not asked" — distinct from "it is open", which is a claim."""
    assert Ticket(id="#1", title="t", objective="o", repo="o/r").state is None


# ── the providers answer it, each in its own vocabulary ──────────────────────────────────────────

def test_github_ASKS_for_the_state():
    """It was absent from the `--json` list, so no answer could ever arrive."""
    import inspect

    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    src = inspect.getsource(GitHubIssuesTracker.get_ticket)
    assert "state" in src.split("--json")[1].split("]")[0]


def test_github_fills_it_from_the_payload(monkeypatch):
    import json
    import subprocess

    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    payload = {"number": 7, "title": "t", "body": "objective: o", "labels": [],
               "author": {"login": "a"}, "state": "CLOSED"}

    def _fake(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", _fake)
    t = GitHubIssuesTracker(repo="o/r").get_ticket("#7")
    assert t.state == "closed"  # normalised, because the guard compares lowercase


def test_jira_answers_from_the_status_CATEGORY(monkeypatch):
    """Not the status NAME. A client's done column may be called "Donee", "Entregue" or anything
    else they chose — this deployment has literally seen a typo'd one — and the category is the
    vendor's own answer to "is this finished"."""
    from openfactory.adapters.tracker.jira import JiraTracker

    tracker = JiraTracker(site="https://x.atlassian.net", project_key="DAR", email="e@x")
    monkeypatch.setattr(tracker, "_call", lambda *a, **k: {
        "key": "DAR-9",
        "fields": {"summary": "t", "description": "objective: o",
                   "status": {"name": "Donee", "statusCategory": {"key": "done"}}},
    })
    assert tracker.get_ticket("DAR-9").state == "closed"


def test_jira_in_progress_reads_as_open(monkeypatch):
    from openfactory.adapters.tracker.jira import JiraTracker

    tracker = JiraTracker(site="https://x.atlassian.net", project_key="DAR", email="e@x")
    monkeypatch.setattr(tracker, "_call", lambda *a, **k: {
        "key": "DAR-9",
        "fields": {"summary": "t", "description": "objective: o",
                   "status": {"name": "Em curso", "statusCategory": {"key": "indeterminate"}}},
    })
    assert tracker.get_ticket("DAR-9").state == "open"


# ── and the guard fires on the REAL contract ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_CLOSED_card_is_not_picked_up(monkeypatch):
    """The end of the chain, with no invented attribute anywhere."""
    from openfactory.runtime.temporal import activities

    states = {"1": "open", "2": "closed"}

    class _Tracker:
        def get_ticket(self, ref):
            return _ticket(ref, states[str(ref).lstrip("#")])

    picked = await activities._open_refs(_Tracker(), ["1", "2"])
    assert picked == ["1"], picked


@pytest.mark.asyncio
async def test_an_UNREADABLE_ticket_is_still_picked_up(monkeypatch):
    """The positive twin: refusing on a read failure would let one flaky API call stop intake,
    which is the opposite failure and the worse one."""
    from openfactory.runtime.temporal import activities

    class _Tracker:
        def get_ticket(self, ref):
            raise RuntimeError("boom")

    assert await activities._open_refs(_Tracker(), ["1"]) == ["1"]


@pytest.mark.asyncio
async def test_a_provider_that_does_not_answer_does_not_block_intake():
    """`state=None` means the provider was not asked — that must read as "carry on", never as
    "closed", or a tracker without the field would silently stop every pickup."""
    from openfactory.runtime.temporal import activities

    class _Tracker:
        def get_ticket(self, ref):
            return _ticket(ref, None)

    assert await activities._open_refs(_Tracker(), ["1"]) == ["1"]

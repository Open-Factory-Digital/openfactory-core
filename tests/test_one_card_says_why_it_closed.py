"""#480 — asked for one card, Jira and Azure DevOps say why it closed, as their summaries do.

THE DEFECT. Both rows filled `state_reason` only in their bulk summaries (`_summary`); `get_ticket`
built the `Ticket` without it. Every reader that asks for ONE card — the stale-pickup healer
(#413), the card's door (ADR-0055) — therefore read every closed card on these rows as "this
tracker does not say", and a card withdrawn on the vendor's own screen was filed as finished work.
GitHub's `get_ticket` learned it in #414 part A; the local row fills it since #413.

WHAT IS PROVEN HERE: the real row classes, with only their transport faked, answer the SAME reason
from `get_ticket` and from `_summary` for one card, closed as not delivered, closed as done, and
open.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsClient
from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker
from openfactory.adapters.tracker.jira import JiraTracker

WONT_DO = "Won't Do"


# ── Jira ─────────────────────────────────────────────────────────────────────────────────────────

def _jira_issue(category: str, resolution: str | None) -> dict:
    return {"key": "CONT-7", "fields": {
        "summary": "Mostrar o total", "description": None,
        "status": {"name": "Done" if category == "done" else "Em andamento",
                   "statusCategory": {"key": category}},
        "resolution": {"id": "1", "name": resolution} if resolution else None,
        "labels": [], "assignee": None, "updated": "2026-10-02T00:00:00.000+0000"}}


def _jira(issue: dict) -> JiraTracker:
    tracker = JiraTracker(site="https://acme.atlassian.net", project_key="CONT", email="a@b.c",
                          status_map={"todo": "To Do", "done": "Done"},
                          not_delivered_resolution=WONT_DO)

    def call(method, path, payload=None):
        assert (method, path) == ("GET", "issue/CONT-7"), (method, path)
        return issue

    tracker._call = call  # noqa: SLF001 — the transport, and only the transport
    return tracker


@pytest.mark.parametrize("category, resolution, reason", [
    ("done", WONT_DO, "not_planned"),
    ("done", "Done", ""),
    ("indeterminate", None, ""),
    # REOPENED, its old resolution still on it — Jira does not always clear the field, and an open
    # card is open work whatever it once was closed as
    ("indeterminate", WONT_DO, ""),
], ids=["withdrawn", "done", "open", "reopened"])
def test_jira_says_for_one_card_what_its_summary_says(category, resolution, reason):
    issue = _jira_issue(category, resolution)
    tracker = _jira(issue)

    card = tracker.get_ticket("CONT-7")

    assert card.state_reason == reason
    assert card.state_reason == tracker._summary(issue).state_reason  # noqa: SLF001


# ── Azure DevOps ─────────────────────────────────────────────────────────────────────────────────

_STATES = {"value": [{"name": "To Do", "category": "Proposed"},
                     {"name": "Doing", "category": "InProgress"},
                     {"name": "Done", "category": "Completed"},
                     {"name": "Removed", "category": "Removed"}]}


def _work_item(state: str) -> dict:
    return {"id": 7, "fields": {"System.Title": "Mostrar o total", "System.Description": "",
                                "System.WorkItemType": "Issue", "System.State": state,
                                "System.Tags": "", "System.ChangedDate": "2026-10-02"}}


def _azure(row: dict) -> AzureBoardsTracker:
    class _Client(AzureDevOpsClient):
        def call(self, method, path, *, body=None, params=None, project_scoped=True,
                 content_type="application/json", api_version=None):
            if method.upper() == "GET" and path.endswith("/states"):
                return _STATES
            assert (method.upper(), path) == ("GET", "wit/workitems/7"), (method, path)
            return row

    return AzureBoardsTracker(organization="acme-ai", project="factory",
                              client=_Client(organization="acme-ai", project="factory",
                                             token="pat"),
                              state_map={"todo": "To Do", "done": "Done"})


@pytest.mark.parametrize("state, reason", [
    ("Removed", "not_planned"),
    ("Done", "completed"),
    ("Doing", ""),
], ids=["removed", "done", "open"])
def test_azure_devops_says_for_one_card_what_its_summary_says(state, reason):
    row = _work_item(state)
    tracker = _azure(row)

    card = tracker.get_ticket("7")

    assert card.state_reason == reason
    assert card.state_reason == tracker._summary(row).state_reason  # noqa: SLF001


# ── what the readers then conclude ───────────────────────────────────────────────────────────────

def test_the_door_and_the_healer_now_read_a_withdrawn_card_as_withdrawn_on_both_rows():
    """`lifecycle.ports.withdrawn` is what the stale-pickup healer and the card's door ask of one
    card. On these rows it answered False for every card, a withdrawn one included."""
    from openfactory.lifecycle.ports import withdrawn

    assert withdrawn(_jira(_jira_issue("done", WONT_DO)).get_ticket("CONT-7"))
    assert withdrawn(_azure(_work_item("Removed")).get_ticket("7"))
    assert not withdrawn(_jira(_jira_issue("done", "Done")).get_ticket("CONT-7"))
    assert not withdrawn(_azure(_work_item("Done")).get_ticket("7"))

"""The tracker reads what a person wrote on a card — a fence typed by hand, who asked, the whole
thread.

THREE READS THE SLICE-2 DESIGN CRITIQUE (2026-09-06) FOUND BROKEN BY TRYING THEM IN-TREE, each on
the single door every vendor shares:

  * `parse_ticket_body` called `yaml.safe_load` unguarded on the front-matter fence. `requester:
    @octocat` — a line a person would type — is a `ScannerError` (`@` cannot start a token), and
    that door is `get_ticket` on GitHub, Jira and Azure Boards: ONE hand-edited card took down
    every read of it, from `scan_todo` to the breakdown.
  * `JiraTracker.get_ticket` never set `Ticket.author`, so on one vendor in three a card could
    never be routed back to whoever asked for it (the park escalation, the requester lookup).
  * `AzureBoardsTracker.comments(limit=0)` read ONE page and its docstring said paging was
    unnecessary. A thread longer than the service's page came back as its first page, silently —
    and a caller looking for its own question after the requester's answer would not find it.

The rule these guards keep is the read-side rule of `tests/test_the_tracker_has_a_read_side.py`
applied one layer further in: what a person typed is data the port must READ, never a reason the
port dies; and a read that comes back short SAYS so.
"""

from __future__ import annotations

import logging

import pytest
import yaml

from openfactory.adapters.tracker.parse import parse_ticket_body
from tests.test_the_tracker_has_a_read_side import (
    _ALICE,
    ADO_COMMENTS_DESC,
    _ado_tracker,
    _Gh,
    _Jira,
    ado_comments_paged,
    ado_comments_service,
)

#: What a person types when they want a card to say who asked for it. Not YAML.
HAND_TYPED = ("---\nrequester: @octocat\n---\n## Objective\nLer o que a pessoa escreveu\n"
              "## Acceptance criteria\n- o cartão abre\n- ninguém morre\n")

#: The same card with a fence the parser CAN read — the positive twin.
WELL_FORMED = ("---\ndepends_on: [\"#3\"]\nbase_branch: release/2\n---\n## Objective\n"
               "Ler o que a pessoa escreveu\n## Acceptance criteria\n- o cartão abre\n")


def _jira_issue_with(body: str, **who) -> dict:
    """A `GET issue/<key>` answer whose description is `body`, one ADF paragraph per line — the
    shape `_text` walks back into the same lines — plus whatever identity blobs the test hands in."""
    fields = {"summary": "quem pediu", "labels": [], "assignee": None,
              "status": {"name": "To Do", "statusCategory": {"key": "new"}},
              "description": {"type": "doc", "version": 1, "content": [
                  {"type": "paragraph", "content": [{"type": "text", "text": line}]}
                  for line in body.splitlines()]}}
    fields.update(who)
    return {"id": "10071", "key": "DAR-7", "fields": fields}


def _ado_work_item(body: str) -> dict:
    return {"id": 12, "fields": {"System.Id": 12, "System.WorkItemType": "Issue",
                                 "System.State": "To Do", "System.Title": "quem pediu",
                                 "System.CreatedBy": _ALICE, "System.Description": body},
            "multilineFieldsFormat": {"System.Description": "markdown"}}


def _github_issue(body: str) -> dict:
    return {"number": 7, "title": "quem pediu", "body": body, "labels": [],
            "author": {"login": "alicecsp"}, "state": "OPEN"}


_VENDORS = {
    "github": lambda body: _Gh({"issue": _github_issue(body)}).get_ticket("#7"),
    "jira": lambda body: _Jira({("GET", "issue/DAR-7"): _jira_issue_with(body)}
                               ).get_ticket("DAR-7"),
    "azure_devops": lambda body: _ado_tracker({("GET", "wit/workitems/12"): _ado_work_item(body)}
                                              ).get_ticket("12"),
}


# ── the fence ───────────────────────────────────────────────────────────────────────────────────

def test_the_line_a_person_types_is_refused_by_yaml_itself_and_that_used_to_be_the_end():
    """The measurement. `@` cannot start a YAML token, so the very line the requester half of the
    design writes on a card is a `ScannerError` — and until 2026-09-06 that exception left
    `_split_front_matter` untouched, so it left `get_ticket` untouched, on every vendor."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("requester: @octocat")

    ticket = parse_ticket_body(id="#7", title="quem pediu", body=HAND_TYPED, repo="r")

    assert ticket.objective == "Ler o que a pessoa escreveu"


@pytest.mark.parametrize("vendor", sorted(_VENDORS))
def test_a_fence_that_does_not_parse_is_body_text_on_every_vendor(vendor):
    """The card is read whole; the fence's optional keys are simply not set. Through each vendor's
    OWN `get_ticket`, because the door is shared but the three bodies arrive in three shapes
    (`gh` JSON, ADF, sanitised markdown) and any of them could have re-raised on the way in."""
    ticket = _VENDORS[vendor](HAND_TYPED)

    assert ticket.objective == "Ler o que a pessoa escreveu"
    assert [c.text for c in ticket.acceptance_criteria] == ["o cartão abre", "ninguém morre"]
    assert ticket.depends_on == [] and ticket.base_branch is None
    assert ticket.raw.startswith("---"), "the body is kept as written, fence included"


@pytest.mark.parametrize("vendor", sorted(_VENDORS))
def test_a_fence_that_parses_still_sets_its_keys(vendor):
    """The positive twin — the guard must not have turned every fence into body text."""
    ticket = _VENDORS[vendor](WELL_FORMED)

    assert ticket.depends_on == ["#3"] and ticket.base_branch == "release/2"
    assert ticket.objective == "Ler o que a pessoa escreveu"


def test_the_warning_names_the_first_line_of_the_fence_and_nothing_of_the_body(caplog):
    """A log is not the place to copy a client's card. The line that failed is the thirty-second
    fix; the objective and the criteria are theirs."""
    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.parse"):
        parse_ticket_body(id="#7", title="t", body=HAND_TYPED, repo="r")

    (record,) = [r for r in caplog.records if "front matter" in r.getMessage()]
    assert "requester: @octocat" in record.getMessage()
    assert "Ler o que a pessoa escreveu" not in record.getMessage()
    assert "ninguém morre" not in record.getMessage()


# ── who asked, on Jira ──────────────────────────────────────────────────────────────────────────

def test_a_jira_ticket_names_its_reporter_by_display_name():
    """`reporter` is who the card is FOR; `displayName` because this field is read by a person or
    a model and never written back (the same choice `comments` makes against the accountId)."""
    tracker = _Jira({("GET", "issue/DAR-7"): _jira_issue_with(
        "## Objective\nx", reporter={"displayName": "Bruno Sá", "accountId": "712020:aa"},
        creator={"displayName": "Alice Ferreira", "accountId": "712020:bb"})})

    assert tracker.get_ticket("DAR-7").author == "Bruno Sá"


def test_a_jira_ticket_without_a_reporter_falls_back_to_whoever_created_it():
    tracker = _Jira({("GET", "issue/DAR-7"): _jira_issue_with(
        "## Objective\nx", reporter=None,
        creator={"displayName": "Alice Ferreira", "accountId": "712020:bb"})})

    assert tracker.get_ticket("DAR-7").author == "Alice Ferreira"


def test_a_jira_ticket_nobody_is_recorded_on_answers_None_like_the_other_two_vendors():
    """`Ticket.author` is `str | None`, None meaning the provider did not say — GitHub and Azure
    Boards both answer that; an accountId with no display name is not a name either."""
    tracker = _Jira({("GET", "issue/DAR-7"): _jira_issue_with(
        "## Objective\nx", reporter={"accountId": "712020:aa"}, creator=None)})

    assert tracker.get_ticket("DAR-7").author is None


# ── the whole thread, on Azure Boards ───────────────────────────────────────────────────────────

def test_an_un_limited_ado_read_follows_the_continuation_token_to_the_end():
    """The service pages; the port promised the whole thread and read one page. With a page of two
    over the recorded three-comment thread, the second request must carry the token the first
    answer handed back, and the result is the three, oldest first."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments_paged})

    got = tracker.comments("12")

    calls = [c for c in tracker.recorded.calls if c["path"].endswith("/comments")]
    assert len(calls) == 2, "one page was read for a thread of two pages"
    assert calls[0]["params"] == {"order": "asc"}
    assert calls[1]["params"] == {"order": "asc", "continuationToken": "skip2"}
    assert [c.created_at for c in got] == ["2026-08-06T09:11:43.653Z", "2026-08-06T11:21:34.88Z",
                                           "2026-08-06T11:27:50.503Z"]


def test_a_limited_ado_read_is_one_request_whatever_the_service_pages_at():
    """`$top` is the server-side bound; the newest N never needs a second page."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments_paged})

    got = tracker.comments("12", limit=2)

    calls = [c for c in tracker.recorded.calls if c["path"].endswith("/comments")]
    assert len(calls) == 1 and "continuationToken" not in calls[0]["params"]
    assert [c.created_at for c in got] == ["2026-08-06T11:21:34.88Z", "2026-08-06T11:27:50.503Z"]


def test_a_read_that_ends_short_of_totalCount_is_handed_back_and_SAYS_so(caplog):
    """A service that stops sending a token before `totalCount` is reached — the port cannot fetch
    what it was not pointed at, but it must not hand back three comments as if they were five: a
    caller looking for one particular comment would read its absence as a fact."""
    def short(_body, params):
        rows = list(reversed(ADO_COMMENTS_DESC["comments"]))
        return {"totalCount": 5, "count": len(rows), "comments": rows}
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): short})

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.azure_devops"):
        got = tracker.comments("12")

    assert len(got) == 3
    (record,) = [r for r in caplog.records if "SHORT" in r.getMessage()]
    assert "3 of the 5" in record.getMessage()


def test_a_complete_read_does_not_cry_short(caplog):
    """The twin of the warning: three of three is not a short read."""
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): ado_comments_paged})

    with caplog.at_level(logging.WARNING, logger="openfactory.tracker.azure_devops"):
        tracker.comments("12")

    assert not [r for r in caplog.records if "SHORT" in r.getMessage()]


def test_a_second_page_of_an_unrecognised_shape_makes_the_whole_thread_unreadable():
    """The rule of the read side, kept on page two: a 200 this adapter cannot read is None, never
    the first page presented as the thread."""
    service = ado_comments_service(ADO_COMMENTS_DESC["comments"], page=2)

    def flaky(body, params):
        if (params or {}).get("continuationToken"):
            return {"totalCount": 3, "count": 1}
        return service(body, params)
    tracker = _ado_tracker({("GET", "wit/workItems/12/comments"): flaky})

    assert tracker.comments("12") is None

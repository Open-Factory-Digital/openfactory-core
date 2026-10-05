"""The same transition leaves the same comments on every tracker row (ADR-0055 D6, #414).

THE DEFECT. A transition's note travelled as `set_state(reason=…)`, and each row did something of
its own with it: GitHub and Azure DevOps wrote it as a comment (`[on_hold] …`), Jira wrote it for
one state of all of them, and the local board dropped it. Every caller that passed a reason ALSO
commented, so on two rows the same park said itself twice, and on one it said nothing — the
"one comment saying who decided" existed on two rows of four. The door's `Comment` effect is now
the one writer of a transition's comment, and `set_state` writes none on any row.

ON THE REAL ROWS, with only their transport stood in for: the local board on its own SQLite file,
GitHub through a `gh` that answers, Azure DevOps through its client's one request method, Jira
through its one REST call. What is read back is what reached the transport as a comment — so a
row that wrote one by some other path than its own `comment` is caught too.

THE PARAMETRIZATION IS THE SCOPE, AND IT IS ASSERTED: a fifth row shipped in `TRACKERS` fails here
until it is driven too.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import pytest

from openfactory.contracts import JobState
from openfactory.lifecycle.card import transition
from openfactory.lifecycle.ports import Ports, Seen
from openfactory.lifecycle.table import CardEvent, State


@dataclass
class Row:
    """One shipped tracker row, its transport stood in for, and what reached it as a comment —
    `posted` as the transport saw it, or `read` back from a store that IS the transport."""

    tracker: object
    posted: list[str] = field(default_factory=list)
    read: object = None

    @property
    def said(self) -> list[str]:
        return self.read() if self.read is not None else self.posted


def _local(tmp_path, monkeypatch) -> Row:
    from openfactory.adapters.board_setup.local import LocalBoardSetup
    from openfactory.adapters.tracker.local import LocalTracker
    from openfactory.contracts.project import Project, ProviderRef

    monkeypatch.setenv("OPENFACTORY_BOARD_DB", str(tmp_path / "board.db"))
    project = Project(name="acme", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="local", repo="acme", options={}))
    LocalBoardSetup().create(project=project, owner="", title="acme", token=None)
    tracker = LocalTracker("acme")
    for _ in range(12):
        tracker.create_ticket(title="a card", body="## Objective\n\nx\n")
    # THE LOCAL ROW'S STORE IS ITS TRANSPORT: what it holds as comments on the card
    return Row(tracker, read=lambda: [c.body for c in tracker.comments("12") or []])


def _github(tmp_path, monkeypatch) -> Row:
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    tracker = GitHubIssuesTracker("acme/books")
    row = Row(tracker)

    def gh(args, timeout=60):
        if args[:2] == ["issue", "comment"]:
            row.posted.append(args[args.index("--body") + 1])
        if "--comment" in args:
            row.posted.append(args[args.index("--comment") + 1])
        out = ""
        if args[:2] == ["issue", "view"]:
            out = "OPEN" if "--jq" in args else '{"labels": []}'
        return subprocess.CompletedProcess(["gh", *args], 0, stdout=out, stderr="")

    tracker._gh = gh  # noqa: SLF001 — the transport, and only the transport
    return row


def _azure_devops(tmp_path, monkeypatch) -> Row:
    from openfactory.adapters.azure_devops import AzureDevOpsClient
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    states = {"value": [{"name": "To Do", "category": "Proposed"},
                        {"name": "Doing", "category": "InProgress"},
                        {"name": "Needs Action", "category": "InProgress"},
                        {"name": "In review", "category": "Resolved"},
                        {"name": "Done", "category": "Completed"}]}
    holder: dict[str, Row] = {}

    class _Client(AzureDevOpsClient):
        def call(self, method, path, *, body=None, params=None, project_scoped=True,
                 content_type="application/json", api_version=None):
            if method.upper() == "GET" and path.endswith("/states"):
                return states
            if method.upper() == "POST" and path.endswith("/comments"):
                holder["row"].posted.append(body["text"])
            return {}

    tracker = AzureBoardsTracker(
        organization="acme-ai", project="factory",
        client=_Client(organization="acme-ai", project="factory", token="pat"),
        state_map={"backlog": "To Do", "todo": "To Do", "in_progress": "Doing",
                   "in_review": "In review", "needs_action": "Needs Action", "done": "Done"})
    holder["row"] = Row(tracker)
    return holder["row"]


def _jira(tmp_path, monkeypatch) -> Row:
    from openfactory.adapters.tracker.jira import JiraTracker

    names = {"backlog": "Backlog", "todo": "To Do", "in_progress": "In Progress",
             "in_review": "In Review", "needs_action": "Needs Action", "done": "Done"}
    tracker = JiraTracker(site="https://acme.atlassian.net", project_key="CONT", email="a@b.c",
                          status_map=names)
    row = Row(tracker)

    def call(method, path, payload=None):
        if method == "GET" and path.endswith("/transitions"):
            return {"transitions": [{"id": str(i), "name": n, "to": {"name": n}}
                                    for i, n in enumerate(names.values())]}
        if method == "POST" and path.endswith("/comment"):
            row.posted.append(JiraTracker._text(payload["body"]))  # noqa: SLF001
        return {}

    tracker._call = call  # noqa: SLF001 — the transport, and only the transport
    return row


ROWS = {"local": _local, "github": _github, "azure_devops": _azure_devops, "jira": _jira}


class Project:
    name = "acme"
    language = "en"


class _OnTheRow(Ports):
    """The real ports over a real row, with a fixed reading of where the card is (the card's
    legality is the table's, tested elsewhere) and none of the consumers that are not the card."""

    board = None

    def __init__(self, tracker, state: State):
        super().__init__(Project(), tracker=tracker)
        self._state = state

    def sink(self):
        from openfactory.lifecycle.record import Unrecordable

        raise Unrecordable("this test keeps no record")

    def seen(self, card):
        return Seen(state=self._state, title="a card")

    def asked_in(self, card):
        return ""

    def tell(self, card, **kw):
        return "nobody to tell"

    def preview(self, card, *, action, by):
        return "none running"

    def forget(self):
        return "forgotten"


def test_the_rows_driven_here_are_every_row_the_platform_ships():
    from openfactory.adapters.tracker.registry import TRACKERS

    assert set(ROWS) == set(TRACKERS), (
        f"a row is shipped and not driven here, or driven and not shipped: "
        f"{sorted(set(ROWS) ^ set(TRACKERS))}")


#: Transitions whose column travels through `set_state` — where the reason used to.
TRANSITIONS = [
    (CardEvent.PARKED, State.RUNNING, {"job_state": "on_hold", "note": "the CI is red twice"}),
    (CardEvent.DELIVERED, State.WAITING_ON_A_PERSON,
     {"note": "Merged, and nothing follows the merge."}),
    (CardEvent.DISCARDED, State.WAITING_ON_A_PERSON, {}),
    (CardEvent.QUESTION_ANSWERED, State.WAITING_ON_A_PERSON, {}),
    # the box's outcomes, applied by the worker through the door (#414, D7)
    (CardEvent.PR_OPENED, State.RUNNING, {"needs_person": True,
                                          "note": "Ready for review: https://x/pr/3"}),
    (CardEvent.MERGED, State.RUNNING, {"note": "Merged."}),
    (CardEvent.REFUSED, State.RUNNING, {"note": "The card has no acceptance criteria."}),
]


@pytest.mark.parametrize("event,state,facts", TRANSITIONS, ids=lambda x: getattr(x, "value", ""))
@pytest.mark.parametrize("kind", sorted(ROWS))
def test_the_same_transition_leaves_the_same_one_comment_on_every_row(kind, event, state, facts,
                                                                      tmp_path, monkeypatch):
    row = ROWS[kind](tmp_path, monkeypatch)

    moved = transition(Project(), "12", event, by="ana", why="not this quarter", facts=facts,
                       ports=_OnTheRow(row.tracker, state))

    assert moved.ok and not moved.failed, (moved.refused, moved.failed)
    assert row.said == [moved.facts["note"]], (
        f"{kind}: {event.value} left {row.said!r}, and the door's comment is the one")


@pytest.mark.parametrize("kind", sorted(ROWS))
def test_set_state_writes_no_comment_on_any_row(kind, tmp_path, monkeypatch):
    """The parameter stays — no caller and no add-on breaks — and no row writes it."""
    row = ROWS[kind](tmp_path, monkeypatch)

    for state in (JobState.ON_HOLD, JobState.NEEDS_REFINEMENT, JobState.SKIPPED, JobState.DONE):
        row.tracker.set_state("12", state, reason=f"why it is {state.value}")

    assert row.said == [], f"{kind}: set_state wrote {row.said!r}"

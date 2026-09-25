"""A delivered card is closed by the row that owns its state — whatever repository the pull
request opened in (#180).

After #179 the job writes a closing line into a pull request only where the forge OWNS the card.
That is right: `Closes #12` in `acme/api` named issue 12 of `acme/api`, which is not a card routed
from `acme/issues`. But the closing line was the ONLY thing that ever closed a GitHub issue on the
delivery path. `set_state(DONE)` moved the board column (or wrote the `openfactory:done` label) and
left the issue open, so on every pairing the forge does not own — another repository, a local
forge, Azure Repos, an add-on — a delivered issue stayed open in Done: the state triage reports as
`done-but-open`, produced by the factory itself on every card.

THE TRACKER ROW IS THE ONE WRITER OF THE CARD'S STATE. #179 already applies that rule to Azure
Repos, which refuses to transition work items from the forge side. Here the GitHub row's Done path
closes the issue as completed, so the close no longer depends on which forge it is paired with or
on a cross-repository keyword nobody has measured with this deployment's token.

Every case drives the real `GitHubIssuesTracker` over a recorded `gh`, and reads the argv it ran.
"""

from __future__ import annotations

import json
import logging
import subprocess

import pytest

from openfactory.adapters.tracker.github import GitHubIssuesTracker
from openfactory.contracts import JobState

_FIELDS = json.dumps({"fields": [
    {"name": "Status", "id": "FID", "options": [
        {"name": "Backlog", "id": "OPT_BACKLOG"}, {"name": "TO-DO", "id": "OPT_TODO"},
        {"name": "In progress", "id": "OPT_PROG"}, {"name": "In review", "id": "OPT_REVIEW"},
        {"name": "Needs Action", "id": "OPT_NEEDS"}, {"name": "Done", "id": "OPT_DONE"},
    ]},
]})
_ITEMS = json.dumps({"data": {"organization": {"projectV2": {"items": {
    "pageInfo": {"hasNextPage": False, "endCursor": None},
    "nodes": [{"id": "ITEM7", "content": {"number": 7},
               "fieldValueByName": {"name": "In review"}}],
}}}}})
_SCRIPT = [
    ("field-list", _FIELDS),
    ("project view", json.dumps({"id": "PID"})),
    ("repository(owner:", json.dumps({"data": {"repository": {"issue": {"id": "NODE7"}}}})),
    ("addProjectV2ItemById",
     json.dumps({"data": {"addProjectV2ItemById": {"item": {"id": "ITEM7"}}}})),
    ("updateProjectV2ItemFieldValue",
     json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM7"}}}})),
    ("api graphql", _ITEMS),
    ("issue view", json.dumps({"labels": []})),
]


class FakeGH:
    """Answers `subprocess.run(["gh", …])` from a script and records every argv."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail: set[str] = set()
        self.first: list[tuple[str, str]] = []      # answers that win over the script
        self.hangs: set[str] = set()                # calls that never answer

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for marker in self.hangs:
            if marker in joined:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 60)
        for marker in self.fail:
            if marker in joined:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr=f"boom: {marker}")
        for marker, stdout in [*self.first, *_SCRIPT]:
            if marker in joined:
                return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def matching(self, *needles: str) -> list[list[str]]:
        return [argv for argv in self.calls if all(n in " ".join(argv) for n in needles)]


@pytest.fixture
def gh(monkeypatch) -> FakeGH:
    fake = FakeGH()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


# ── the delivery closes the card ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("board", [True, False], ids=["a board", "no board: the label is the state"])
def test_DONE_closes_the_issue_as_completed(gh, board):
    kw = {"board_owner": "org", "board_number": "6"} if board else {}
    tracker = GitHubIssuesTracker("o/r", **kw)

    tracker.set_state("#7", JobState.DONE)

    [closed] = gh.matching("issue", "close")
    assert closed[closed.index("close") + 1] == "7"
    assert _flag(closed, "--repo") == "o/r"
    assert _flag(closed, "--reason") == "completed", "a delivered card was closed as not planned"


def test_a_card_routed_from_ANOTHER_repository_is_closed_in_its_own(gh):
    """The pairing the issue is about: the card is `acme/issues#12`, this adapter's default
    repository is the code's. The close goes where the CARD lives."""
    tracker = GitHubIssuesTracker("acme/api")

    tracker.set_state("acme/issues#12", JobState.DONE)

    [closed] = gh.matching("issue", "close")
    assert closed[closed.index("close") + 1] == "12"
    assert _flag(closed, "--repo") == "acme/issues"


@pytest.mark.parametrize("state", [s for s in JobState if s is not JobState.DONE])
def test_no_other_state_closes_anything(gh, state):
    """MERGED least of all: a merged change is still overseen while it deploys, and the chain
    after it can still roll back."""
    GitHubIssuesTracker("o/r").set_state("#7", state)

    assert not gh.matching("issue", "close"), state


def test_the_column_moves_BEFORE_the_close(gh):
    """If the close is the write that fails, the card is already where the work got to."""
    tracker = GitHubIssuesTracker("o/r", board_owner="org", board_number="6")

    tracker.set_state("#7", JobState.DONE)

    moved = gh.calls.index(gh.matching("updateProjectV2ItemFieldValue")[0])
    closed = gh.calls.index(gh.matching("issue", "close")[0])
    assert moved < closed


# ── a close that fails is said, and the delivery stands ─────────────────────────────────────────

def test_a_refused_close_does_not_fail_the_delivery_and_is_SAID_BY_NAME(gh, caplog):
    """The change is merged and the column moved: nothing about recording it may undo it. But it
    is not swallowed — the log names the card under a marker, the way a refused board move does."""
    gh.fail = {"issue close"}
    tracker = GitHubIssuesTracker("o/r", board_owner="org", board_number="6")

    with caplog.at_level(logging.ERROR):
        landed = tracker.set_state("#7", JobState.DONE)

    assert landed is True, "the move landed; the answer is about the move"
    assert "OPENFACTORY_DELIVERED_CARD_NOT_CLOSED o/r#7" in caplog.text
    assert "boom: issue close" in caplog.text, "the forge's own words are what a person can act on"


def test_the_row_does_not_speak_to_a_person_in_a_language_it_was_never_told(gh):
    """The tracker row has no project language. What a person reads about a card left open comes
    from triage, which does."""
    gh.fail = {"issue close"}

    GitHubIssuesTracker("o/r").set_state("#7", JobState.DONE)

    assert not gh.matching("issue", "comment")


def test_a_state_that_cannot_even_be_read_does_not_raise(gh, caplog):
    """`gh` hanging on the read is a `TimeoutExpired`, not the `RuntimeError` a refusal is."""
    gh.fail = {"issue close"}
    gh.hangs = {"--json state"}

    with caplog.at_level(logging.ERROR):
        GitHubIssuesTracker("o/r").set_state("#7", JobState.DONE)

    assert "OPENFACTORY_DELIVERED_CARD_NOT_CLOSED" in caplog.text


def test_a_close_refused_because_the_issue_is_ALREADY_closed_is_not_a_failure(gh, caplog):
    """The owned pairing: the pull request's `Closes #7` closed the issue at the merge, before Done
    is written. `gh issue close` answers 0 for that today — but if any version of it, or a forge
    behind it, refuses instead, a card that IS closed must not be told it could not be."""
    gh.fail = {"issue close"}
    gh.first = [("--json state", "CLOSED\n")]
    tracker = GitHubIssuesTracker("o/r")

    with caplog.at_level(logging.ERROR):
        tracker.set_state("#7", JobState.DONE)

    assert "OPENFACTORY_DELIVERED_CARD_NOT_CLOSED" not in caplog.text
    assert not gh.matching("issue", "comment")


def test_the_reason_a_caller_gave_is_still_written(gh):
    tracker = GitHubIssuesTracker("o/r")

    tracker.set_state("#7", JobState.DONE, "shipped in v2")

    assert any("shipped in v2" in _flag(argv, "--body") for argv in gh.matching("issue", "comment"))
    assert gh.matching("issue", "close")


# ── the owned pairing keeps what it had ─────────────────────────────────────────────────────────

def test_the_forge_still_declares_its_closing_word():
    """Same repository: the pull request's `Closes #N` is the native link and stays. The issue is
    then already closed when Done is written, and the row reads that and writes nothing
    (`test_a_card_is_closed_only_when_its_work_merges`)."""
    from openfactory.adapters.forge.github import GitHubForge

    assert GitHubForge.closing_keyword == "Closes"

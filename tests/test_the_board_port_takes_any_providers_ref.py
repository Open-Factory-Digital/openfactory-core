"""The board contract holds a ref no GitHub board could produce (C-05, #33).

WHY THIS FILE IS THE POINT OF THE PORT. `BoardAdapter` exists so the platform can be handed a
board without knowing who keeps it — it is the seam the whole "vendor-agnostic" claim rests on.
It was typed `int` throughout, which is precisely the one shape a Jira board cannot produce.

The hole was invisible because THREE OF THE FOUR TRACKERS ARE NUMERIC:

    GitHub          412        fits
    Azure DevOps    1234       fits      (`contracts/refs.py` says so in its own docstring)
    GitLab          27         fits
    Jira            CONT-412   DOES NOT

So a `fx-ado` fixture would have passed and proved nothing. Jira is the outlier, which is why the
backlog's own card is named *the non-numeric-ref fixture*.

AND THE `int` WAS NEVER BUYING ARITHMETIC. Nothing in this codebase adds, averages or subtracts a
ticket ref — a grep for it comes back empty. What it bought was ORDERING, and that now lives in
`refs.ref_sort_key`. Identity and ordering are different questions and only one of them needs a
number.

THE FAKE BELOW IS THE TEST. A `Protocol` exists exactly so a second provider can be written
without an account anywhere, and writing one is the only way to find out whether the contract can
actually hold a second provider — which is a different question from whether the first one still
works.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.board.base import BoardAdapter
from openfactory.contracts import JobState
from openfactory.contracts.refs import ref_sort_key


class FakeJiraBoard:
    """A board whose refs are `PROJ-123`. Implements the port and nothing else — no inheritance,
    so `isinstance` is answering about the SHAPE rather than about a base class."""

    def __init__(self, cards: dict[str, str]) -> None:
        self.cards = dict(cards)
        self.moves: list[tuple[str, str]] = []

    def url(self) -> str:

        """Where a person looks at this board — `""` for a double that has

        nowhere to send anybody. The port asks it of every board (#162)."""

        return ""


    def columns(self) -> dict[str, str] | None:
        return dict(self.cards)

    def column_names(self) -> list[str] | None:
        return sorted(set(self.cards.values()))

    def pickup_column(self) -> str:

        return "TO-DO"


    def items_in_status(self, status: str) -> list[str]:
        return [ref for ref, col in self.cards.items() if col == status]

    def add_item(self, *, issue_url: str) -> None:
        return None

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        if issue not in self.cards:
            return False
        self.cards[issue] = name
        self.moves.append((issue, name))
        return True

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        return self.set_column(issue=issue, issue_url=issue_url, name=state.value)


def test_a_jira_shaped_board_satisfies_the_contract():
    """`BoardAdapter` is `@runtime_checkable`, and `build_board`'s callers rely on that — a
    half-implemented adapter must fail loudly at construction rather than at the first card move."""
    assert isinstance(FakeJiraBoard({}), BoardAdapter)


def test_a_non_numeric_ref_survives_the_whole_round_trip():
    """THE regression. `CONT-412` has to come OUT of the queue and go back IN to move the card —
    a port that reduced it to `412` on the way through could never address the ticket again."""
    board = FakeJiraBoard({"CONT-412": "TO-DO", "CONT-7": "Done"})

    queued = board.items_in_status("TO-DO")
    assert queued == ["CONT-412"]

    assert board.set_column(issue=queued[0], issue_url="https://jira/CONT-412", name="In progress")
    assert board.cards["CONT-412"] == "In progress"


def test_two_projects_sharing_a_number_are_not_one_ticket():
    """THE reason the ref is not reduced to its digits at this seam. A Jira board routinely spans
    projects — that is what a board IS, as opposed to a project — so `CONT-412` and `PROJ-412` sit
    on it together. Keeping only the number would make them EQUAL, and a platform that believes
    two tickets are one moves the wrong card and comments on the wrong ticket, silently. Same
    shape as the `int(...) or 0` collapse that made the tech-lead's memory report every failure as
    a single ticket (#69)."""
    board = FakeJiraBoard({"CONT-412": "TO-DO", "PROJ-412": "Done"})

    board.set_column(issue="CONT-412", issue_url="https://jira/CONT-412", name="In progress")

    assert board.cards["CONT-412"] == "In progress"
    assert board.cards["PROJ-412"] == "Done", "a same-numbered ticket in another project moved too"


# ── ordering: what the int was actually for ─────────────────────────────────────────────────────

def test_plain_string_sorting_is_the_thing_ref_sort_key_exists_to_prevent():
    """Named rather than assumed, because it is the whole justification for the sort key: sorting
    refs as bare strings puts 10 before 2, and board order is what an operator reads."""
    assert sorted(["2", "10"]) == ["10", "2"]


@pytest.mark.parametrize("refs,expect", [
    (["10", "2", "1"], ["1", "2", "10"]),                        # GitHub / ADO / GitLab
    (["CONT-10", "CONT-2"], ["CONT-2", "CONT-10"]),              # Jira, one project
    (["PROJ-1", "CONT-9"], ["CONT-9", "PROJ-1"]),                # grouped by project first
    (["#7", "3"], ["3", "#7"]),                                  # the '#' is decoration only
])
def test_ref_sort_key_orders_the_way_a_person_expects(refs, expect):
    assert sorted(refs, key=ref_sort_key) == expect


def test_a_numeric_and_a_prefixed_ref_never_collide_in_the_ordering():
    """`412` and `CONT-412` are different tickets and must not compare equal, even though the
    numbers match — the sort key has to keep them apart as well as ordered."""
    assert ref_sort_key("412") != ref_sort_key("CONT-412")


def test_an_unparseable_ref_still_sorts_instead_of_raising():
    """This runs mid-render, in front of a client. A ref nobody anticipated must take a stable,
    if arbitrary, place rather than take the message down — the same degrade-never-crash rule
    `ref_number` was written under."""
    assert sorted(["CONT-2", "whatever", "3"], key=ref_sort_key)  # does not raise


# ── the GitHub adapter still converts at its own edge ───────────────────────────────────────────

def test_the_github_adapter_hands_the_port_strings(monkeypatch):
    """The vendor's shape stops at the vendor's boundary. GitHub's item number IS an int and stays
    one inside the adapter; the port sees a string.

    The GraphQL read is stubbed rather than the result cached — this adapter deliberately holds no
    item cache (its docstring explains the read-cost work that shaped it), so there is no attribute
    to prime and stubbing the one method is the honest seam."""
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    board = GitHubProjectBoard(owner="o", number="1", token="t")
    monkeypatch.setattr(GitHubProjectBoard, "_board_items",
                        lambda self: [{"number": 412, "status": "TO-DO", "id": "x"}])

    assert board.items_in_status("TO-DO") == ["412"], "an int escaped through the port"
    assert board.columns() == {"412": "TO-DO"}


def test_the_github_adapter_converts_the_ref_BACK_on_the_way_in(monkeypatch):
    """The other direction, and the one that fails silently. `_item_id` matches the ref against
    GraphQL's `number`, which is an int — and `"412" == 412` is False in Python. Without the
    conversion at the entrance, every card move would find no item and log 'no card for the issue'
    about a card sitting right there."""
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    board = GitHubProjectBoard(owner="o", number="1", token="t")
    monkeypatch.setattr(GitHubProjectBoard, "_board_items",
                        lambda self: [{"number": 412, "status": "TO-DO", "id": "item-1"}])
    monkeypatch.setattr(GitHubProjectBoard, "_ensure_meta", lambda self: None)
    board._option_ids = {"Done": "opt-done"}
    board._status_field_id = "field-1"
    board._project_id = "proj-1"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: type("_P", (), {"returncode": 0})())

    # True is the whole signal: `set_column` returns False with "no card for the issue" when
    # `_item_id` finds nothing, which is exactly what a str-vs-int mismatch produces.
    assert board.set_column(issue="412", issue_url="https://github.com/o/r/issues/412", name="Done")


def test_a_jira_ref_handed_to_a_GITHUB_board_is_refused_not_guessed(monkeypatch, caplog):
    """The other side of the same conversion. A GitHub board cannot address `CONT-412`, and the
    honest answer is False with a logged reason — not a guess at what `412` might mean, which is
    the collapse that would move somebody else's card."""
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    board = GitHubProjectBoard(owner="o", number="1", token="t")
    monkeypatch.setattr(GitHubProjectBoard, "_board_items",
                        lambda self: [{"number": 412, "status": "TO-DO", "id": "item-1"}])
    monkeypatch.setattr(GitHubProjectBoard, "_ensure_meta", lambda self: None)
    board._option_ids = {"Done": "opt-done"}
    board._status_field_id = "field-1"
    board._project_id = "proj-1"

    with caplog.at_level("ERROR"):
        moved = board.set_column(issue="CONT-412", issue_url="https://jira/CONT-412", name="Done")

    assert moved is False
    assert "OPENFACTORY_BOARD_MOVE_FAILED" in caplog.text

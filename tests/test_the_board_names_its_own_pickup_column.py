"""The pickup column is a QUESTION for the provider, never a literal the platform keeps.

The poller resolved its queue as *explicit `pickup_status`* → *the client's `columns.todo`* → the
string `"TO-DO"`, under a comment claiming a Portuguese board therefore needed zero extra config.
That was true for exactly one provider. GitHub's canonical board really is spelled `TO-DO`; Azure
Boards spells it `To Do`. So an Azure deployment that had configured nothing wrong asked for a
column that does not exist and read an empty queue on every tick — the silent stall this platform
exists to end, arriving through the front door of its own default.

Found by running `sdlc doctor` against a live Azure project, not by reading. The adapter was
already honest about it (`OPENFACTORY_BOARD_UNKNOWN_COLUMN … this queue is empty because of the NAME, not
because nothing is waiting`), which is the only reason it took minutes instead of a client's week.

A CONSTANT STANDING IN FOR A QUESTION ONLY THE PROVIDER CAN ANSWER IS THE SAME DEFECT AS A
HARDCODED VENDOR NAME, wearing a different hat. Every adapter already held the answer; there was
simply no way to ask for it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every board implementation, and what it must call its pickup column with no client override.
#: Spelled out per provider rather than derived, because the POINT is that they differ.
IMPLEMENTATIONS = [
    ("openfactory/adapters/board/azure_devops.py", "AzureBoardsBoard", "To Do"),
    ("openfactory/adapters/tracker/github_project.py", "GitHubProjectBoard", "TO-DO"),
]


def test_every_board_implementation_answers_the_question():
    """The positive twin: a Protocol nobody implements is documentation.

    `BoardAdapter` is `@runtime_checkable`, so a missing method is caught by the conformance suite
    — but only for the doubles it knows about. This asserts the real classes, by AST, so an adapter
    that quietly drops the method is caught even if nothing constructs it in a test.
    """
    for path, class_name, _ in IMPLEMENTATIONS:
        tree = ast.parse((ROOT / path).read_text())
        cls = next((n for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef) and n.name == class_name), None)
        assert cls is not None, f"{class_name} vanished from {path}"
        methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        assert "pickup_column" in methods, (
            f"{path}::{class_name} cannot say what it calls its pickup column, so every caller "
            f"falls back to a literal that is right for at most one provider"
        )


@pytest.mark.parametrize(("path", "class_name", "expected"), IMPLEMENTATIONS)
def test_the_providers_disagree_and_that_is_the_whole_point(path, class_name, expected):
    """Two providers, two different correct answers. A test asserting one value for both would be
    asserting the bug."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard
    from openfactory.adapters.tracker.github_project import GitHubProjectBoard

    built = {
        "AzureBoardsBoard": lambda: AzureBoardsBoard(
            organization="o", project="p", token="t"),
        "GitHubProjectBoard": lambda: GitHubProjectBoard("o", "1", token="t"),
    }[class_name]()
    assert built.pickup_column() == expected


def test_a_client_who_renames_the_column_is_obeyed():
    """C-14: the STATES are closed, the LABELS are the client's. The override has to reach here,
    or the mechanism exists and the poller ignores it."""
    from openfactory.adapters.board.azure_devops import AzureBoardsBoard

    board = AzureBoardsBoard(organization="o", project="p", token="t",
                             columns={"todo": "A Fazer"})
    assert board.pickup_column() == "A Fazer"


def test_the_poller_ASKS_rather_than_assuming():
    """Reachability. `pickup_column` being correct is worth nothing if `scan_targets` still
    hardcodes the literal — this codebase's signature defect, ~19 times over.

    AST rather than a string search: the comment right above the code explains the rule and
    therefore contains every token a grep would look for.
    """
    source = (ROOT / "openfactory" / "runtime" / "temporal" / "activities.py").read_text()
    tree = ast.parse(source)
    helper = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_pickup_column"), None)
    assert helper is not None, "the poller no longer has a helper that asks the board"

    calls = {n.func.attr for n in ast.walk(helper)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "pickup_column" in calls, (
        "the poller's helper does not actually ask the board — it is back to guessing"
    )

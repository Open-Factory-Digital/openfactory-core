"""The board must be a CONCEPT, not a GitHub feature.

The product owner, 2026-07-28: *"putting `gh` in their hands strikes me as an architecture error,
because if it were Jira, for example, it would not be `gh` — and that is a premise of
OpenFactory."*

The debt was worse than the phrasing: the board did not exist as an abstraction at all.
`TrackerAdapter` covers tickets and says nothing about columns, and `GitHubProjectBoard` was
constructed directly in SIX places — the CLI, the poller, the panel, the product module, the Slack
bot and the GitHub tracker. Agnosticism was true of tickets and quietly false of columns; a Jira
deployment would not have had a worse board, it would have had none, and the failure would have
surfaced as an import error inside the poller.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.adapters.board import BOARD_KINDS, BoardAdapter, build_board
from openfactory.contracts.project import Project, ProviderRef

#: The only places allowed to name a vendor's board class: the factory (whose job is choosing one)
#: and the GitHub provider's own module (a GitHub tracker building a GitHub board is not coupling).
_MAY_NAME_A_VENDOR = {
    "openfactory/adapters/board/factory.py",
    "openfactory/adapters/tracker/github.py",
    "openfactory/adapters/tracker/github_project.py",
}


def _project(kind="github", **options):
    return Project(name="x", repo_path="/t",
                   tracker=ProviderRef(kind=kind, repo="a/b", options=options),
                   forge=ProviderRef(kind="github", repo="a/b"))


def _files_naming_a_vendor_board() -> set[str]:
    out = set()
    for path in Path("openfactory").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            called = isinstance(node, ast.Call) and getattr(node.func, "id", "") == \
                "GitHubProjectBoard"
            imported = isinstance(node, ast.ImportFrom) and any(
                a.name == "GitHubProjectBoard" for a in node.names)
            if called or imported:
                out.add(str(path))
    return out


def test_nothing_outside_the_provider_constructs_a_vendor_board():
    stray = _files_naming_a_vendor_board() - _MAY_NAME_A_VENDOR
    assert not stray, (
        f"these name a GitHub board directly: {sorted(stray)}. Use build_board(project) — a Jira "
        f"deployment must not need any of them changed."
    )


def test_the_github_board_actually_satisfies_the_contract():
    """A Protocol nobody checks is documentation. This one caught its own implementation: when the
    protocol first landed, `GitHubProjectBoard` had no `columns()` and isinstance said so."""
    board = build_board(_project(board_owner="AcmeCorp", board_number="6"))
    assert isinstance(board, BoardAdapter)


def test_a_project_with_no_board_gets_None_not_a_crash():
    """A board is OPTIONAL — a deployment can run on tickets alone."""
    assert build_board(_project()) is None


def test_an_unknown_tracker_RAISES_rather_than_guessing_a_provider():
    """The one thing worse than an unsupported tracker is a supported-LOOKING one that writes to
    the wrong system. Same rule as the harness registry (ADR-0018).

    The example used to be `jira`, which now HAS a board (F-02) — the rule did not move, its
    illustration did. `linear` stands in for whatever is next: a kind nobody has implemented must
    still stop at the factory rather than resolve to whichever provider happens to be first."""
    with pytest.raises(ValueError, match="no board provider"):
        build_board(_project(kind="linear", board_owner="X", board_number="1"))


def test_a_jira_project_satisfies_the_same_contract_as_the_github_one():
    """The point of the port: the poller, the panel and the product role hold a `BoardAdapter` and
    never learn which vendor keeps it."""
    import json

    board = build_board(_project(kind="jira", site="https://x.atlassian.net", project_key="DAR",
                                 email="a@b.c", status_map=json.dumps({"todo": "TO-DO"})),
                        token="t")

    assert isinstance(board, BoardAdapter)


def test_the_contract_is_derived_from_what_production_actually_calls():
    """A protocol invented ahead of its callers grows methods nobody implements. Every name here
    must be called somewhere in sdlc/."""
    protocol_methods = {n.name for n in ast.walk(
        ast.parse(Path("openfactory/adapters/board/base.py").read_text()))
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    assert protocol_methods, "the protocol scan found nothing"

    called = set()
    for path in Path("openfactory").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    unused = protocol_methods - called
    assert not unused, f"the board contract declares methods nothing calls: {sorted(unused)}"


def test_adding_a_provider_means_adding_a_row_not_editing_callers():
    """The shape of the extension point, asserted: one tuple names the supported kinds."""
    assert "github" in BOARD_KINDS
    assert isinstance(BOARD_KINDS, tuple)

"""Filed work must land where the client is TOLD it lands — ADR-0030.

WHAT THE AUDIT FOUND. `file_issues`, `file_defect` and `break_down` all took `board=None` by
default, every placement sat behind `if board is not None`, and `grep` showed `board=` supplied
ONLY from tests. So `FILING_COLUMN = "Backlog"` — whose comment argues at length about why the
column must be a literal rather than a caller's choice — was reached by nothing.

The consequence is not cosmetic. A card with no column is invisible to `readiness` and
`propose_queue`, which match column names exactly and have no else-branch: it lands in no bucket,
is never a queue candidate, and `promote` is only ever called with numbers from a staged queue
proposal. So the role can never surface that work again. Meanwhile the reply asserts "Estão no
Backlog — começar a trabalhar nelas continua sendo decisão de uma pessoa" and the defect reply
promises "entra na fila de correção quando o time aprovar a próxima leva".

Both sentences are false, and false in the way ADR-0028 is about: an outcome asserted on a code path
that cannot deliver it. An optional argument only tests supply is the definition of unreachable code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.product.module import ProductModule


class _Board:
    def __init__(self):
        self.placed: list[tuple[int, str]] = []

    def add_item(self, *, issue_url):
        return True

    def set_column(self, *, issue, issue_url, name):
        self.placed.append((issue, name))
        return True


def test_the_default_is_the_REAL_board_not_None():
    """The whole defect in one assertion: with nobody passing a board, one must still be built."""
    import inspect

    for fn in (ProductModule.file_issues, ProductModule.file_defect, ProductModule.break_down):
        sig = inspect.signature(fn)
        default = sig.parameters["board"].default
        assert default is not None, f"{fn.__name__} still defaults to None — placement is dead"


def test_UNSET_and_None_mean_different_things():
    """`None` had to express both "nobody passed one" and "deliberately do not place", and conflating
    them is what left every filed card column-less. A sentinel keeps them apart."""

    mod = ProductModule.__new__(ProductModule)
    injected = _Board()

    assert mod._board_or_default(injected) is injected, "an injected board must win"
    assert mod._board_or_default(None) is None, "None must still mean 'do not place'"


class _Tracker:
    def __init__(self):
        self.created: list[str] = []

    def find_ticket(self, *, title):
        return None

    def create_ticket(self, *, title, body):
        self.created.append(title)
        return "88"


def _defect_module(board):
    from types import SimpleNamespace

    mod = ProductModule.__new__(ProductModule)
    mod.context = lambda: SimpleNamespace(                     # type: ignore[method-assign]
        available=True, reason="", link=SimpleNamespace(docs_repo="a/docs"), docs_commit="")
    # THE TRACKER IS AN ARGUMENT NOW: the card's URL is asked of the provider (`ticket_url`)
    # instead of being spelled `https://github.com/{repo}/issues/{n}` here. A stub left on the old
    # one-argument shape raises TypeError inside the placement's own `except`, which reports the
    # card as unplaced — a green-to-red that says nothing about placement at all.
    mod._issue_url = lambda tracker, ref: f"https://x/{ref}"    # type: ignore[method-assign]
    tracked: list[int] = []
    mod._track_defect = tracked.append                         # type: ignore[method-assign]
    mod._board_tracked = tracked
    return mod


def test_a_filed_card_is_placed_in_the_filing_column():
    """Driven through the PRODUCTION `file_defect`, boundary fakes only (tracker + board). The
    first version of this test performed the placement itself — `board.add_item`/`set_column`
    called from the test body — so mutating the production column to "TO-DO" (the poller's
    auto-spend column) or deleting the placement block entirely kept every guard green."""
    board = _Board()
    mod = _defect_module(board)

    result = mod.file_defect(restated="a conciliação duplica lançamentos",
                             reported_by="<@U1>", violates=None,
                             tracker=_Tracker(), board=board)

    assert result.ok, result.detail
    # the literal on purpose: computing the expectation from FILING_COLUMN would bless whatever
    # the constant is changed to — including the column that spends money
    assert board.placed == [("88", "Backlog")]
    assert mod._board_tracked == [88], "the filed defect never opened its delivery follow-up"


def test_a_defect_that_cannot_be_placed_is_still_filed():
    """Placement is cosmetic, the issue is the record: a board outage must not lose the defect."""
    class _BrokenBoard:
        def add_item(self, *, issue_url):
            raise RuntimeError("board unreachable")

        def set_column(self, **kw):
            raise AssertionError("unreached")

    mod = _defect_module(_BrokenBoard())

    result = mod.file_defect(restated="o extrato não fecha", reported_by="<@U1>", violates=None,
                             tracker=_Tracker(), board=_BrokenBoard())

    assert result.ok and result.ref == "88", result.detail


def test_FILING_COLUMN_is_the_column_readiness_can_actually_see():
    """The column has to be one the role's own deterministic readings match, or placing the card
    changes nothing. `readiness` compares names exactly and has no else-branch."""
    from openfactory.product import queue

    src = Path(queue.__file__).read_text()
    assert ProductModule.FILING_COLUMN.lower() in src.lower(), (
        f"{ProductModule.FILING_COLUMN!r} is not a column readiness() recognises — filed work would "
        f"be invisible to propose_queue even when placed")


@pytest.mark.parametrize("fn", ["file_issues", "file_defect", "break_down"])
def test_no_production_caller_has_to_remember_the_board(fn):
    """The structural half. The bug was not a missing argument at one call site — it was an API that
    required every caller to know about placement. A test that only checked one call site would pass
    the day somebody adds a second."""
    src = Path("openfactory/product/channel.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == fn:
            passed = {k.arg for k in node.keywords}
            assert "board" not in passed, (
                f"{fn} is called with an explicit board at line {node.lineno} — the default should "
                f"be doing this, or the next caller forgets again")

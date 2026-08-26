"""A forge that refused us is not a board under a different root (#132).

Measured on the pilot, 2026-08-17, while chasing "something is draining the GitHub budget again".
The worker's log carried this, once, on an afternoon GitHub spent returning 503s:

    board solo-dev/1 could not be read as an organisation OR a user project —
    falling back to the CLI path (100x costlier per read)
    … Completing activity as failed

Both halves are the defect. The cheap GraphQL read had failed for a reason that has nothing to do
with roots — a 503 — and `_board_items_via_graphql` returned `None`, which is also what it returns
for "this board is not under this root". Its own docstring said so out loud: *"None when that root
is not the right one (or the query failed)"*. Two `None`s later, `_board_items` concluded neither
root owned the board and bought `gh project item-list`, which the CLI bills at ONE REQUEST PER
CARD — the 303-point read this codebase already killed once, on 2026-07-28 and again on 08-14.

SO THE PLATFORM ACCELERATED ITS OWN BURN AT THE EXACT MOMENT THE FORGE WAS UNHEALTHY, and the
tick failed anyway: the points bought nothing. On a board of a few hundred cards, a bad GitHub
half-hour is the whole hourly quota.

The rule this file holds: the expensive fallback exists for a board SHAPE this query cannot
address. It must never be reached by a call that simply did not work.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.adapters.tracker.github_project import (
    BoardUnreadable,
    GitHubProjectBoard,
    _is_wrong_root,
)

# ── 1. the two answers, told apart ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    # Real forge wording, with the logins replaced by placeholders: a fixture only needs the
    # SHAPE of the sentence, and this product carries no deployment's name (#137).
    "gh api graphql failed: Could not resolve to an Organization with the login of acme-user.",
    "gh api graphql failed: Could not resolve to a User with the login of AcmeOrg.",
    'gh api graphql failed: {"type":"NOT_FOUND","message":"..."}',
    "gh api graphql failed: TYPE_MISMATCH on field projectV2",
])
def test_the_forges_own_words_for_a_WRONG_ROOT_are_recognised(said):
    assert _is_wrong_root(said), f"a wrong root is being read as a failure: {said}"


@pytest.mark.parametrize("said", [
    "gh api graphql failed: HTTP 503: No server is currently available to service your request.",
    "gh api graphql failed: HTTP 502 Bad Gateway",
    "gh api graphql failed: API rate limit exceeded for installation",
    "gh api graphql failed: HTTP 401: Bad credentials",
    "gh api graphql failed: dial tcp 140.82.113.6:443: i/o timeout",
    "gh api graphql failed: something GitHub started saying last Tuesday",
])
def test_everything_else_is_a_FAILURE_including_words_nobody_has_seen(said):
    """The safe direction. Guessing "wrong root" costs a hundredfold read on the day the quota
    matters most; guessing "failure" costs one skipped tick."""
    assert not _is_wrong_root(said), f"a failed call is being read as a wrong root: {said}"


# ── 2. what each answer makes the board do ──────────────────────────────────────────────────────

class _Board(GitHubProjectBoard):
    """A board whose only I/O is the GraphQL call, scripted per root."""

    def __init__(self, answers):
        super().__init__(owner="o", number="1", token="t")
        self._answers = answers
        self.cli_reads = 0

    def _board_items_via_graphql(self, root):  # type: ignore[override]
        answer = self._answers[root]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _board_items_via_cli(self):  # type: ignore[override]
        self.cli_reads += 1
        return [{"id": "x", "number": 1, "repo": "", "status": "TO-DO"}]


def test_a_board_under_the_OTHER_root_still_finds_it_without_paying():
    board = _Board({"organization": None,
                    "user": [{"id": "a", "number": 7, "repo": "", "status": "TO-DO"}]})

    assert [i["number"] for i in board._board_items()] == [7]
    assert board.cli_reads == 0, "it bought the hundredfold read for a board it could address"


def test_a_FAILED_call_never_reaches_the_hundredfold_read():
    """THE CARD. A 503 under the first root must not be answered by spending 100x more quota on
    the same unhealthy forge."""
    board = _Board({"organization": BoardUnreadable("HTTP 503"), "user": None})

    with pytest.raises(BoardUnreadable):
        board._board_items()
    assert board.cli_reads == 0, "a 503 still buys the per-card read — the whole defect"


def test_a_failure_under_the_SECOND_root_is_not_swallowed_either():
    board = _Board({"organization": None, "user": BoardUnreadable("HTTP 502")})

    with pytest.raises(BoardUnreadable):
        board._board_items()
    assert board.cli_reads == 0


def test_the_fallback_SURVIVES_for_the_shape_it_exists_for():
    """The positive twin, and the one that decides whether this is safe: a board genuinely under
    neither root (a shape this query cannot address) must still be readable, or the fix trades a
    quota bug for an intake outage."""
    board = _Board({"organization": None, "user": None})

    assert board._board_items(), "a board the query cannot address is no longer readable at all"
    assert board.cli_reads == 1


def test_an_unreadable_board_is_never_turned_into_an_EMPTY_one():
    """`[]` would tell the poller the queue is empty, which is the absence-reads-as-an-answer
    defect this repository keeps paying for — here it would silently stop all intake."""
    board = _Board({"organization": BoardUnreadable("HTTP 503"), "user": None})

    with pytest.raises(BoardUnreadable):
        board.items_in_status("TO-DO")


# ── 3. the seam, held ───────────────────────────────────────────────────────────────────────────

def test_the_caller_does_NOT_catch_the_failure_back_into_the_fallback():
    """Wrapping the loop in a `try` would restore the defect in one line while every test above
    still passed — the failure would simply arrive at the fallback by another road."""
    import ast

    # PARSED, NOT GREPPED. The first cut read the source as text and tripped on the COMMENT that
    # explains the rule — the fourth guard today satisfied (or broken) by prose about itself.
    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(GitHubProjectBoard._board_items)))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Try)], (
        "`_board_items` catches again — the expensive fallback is reachable from a failed call")


def test_the_read_itself_still_distinguishes_at_the_ONE_place_it_can():
    src = inspect.getsource(GitHubProjectBoard._board_items_via_graphql)
    assert "_is_wrong_root" in src and "raise BoardUnreadable" in src
    assert "return None" in src, "a wrong root no longer lets the other one be tried"


def test_BoardUnreadable_is_its_own_type_and_not_a_bare_RuntimeError():
    """The caller's answer differs by kind, so the kind has to survive the raise. A bare
    `RuntimeError` would be caught by any `except RuntimeError` on the way up — including the one
    inside the very function that raises it."""
    assert issubclass(BoardUnreadable, RuntimeError)
    assert BoardUnreadable is not RuntimeError

"""Two things the platform owns and used to keep at a vendor's address (ADR-0049 D7, and the
move D1 depends on).

**The columns.** Six names and six neutral keys were written down three times and compared in
four more, and every copy lived under `adapters/tracker/github_*`. A neutral caller that needed
one — the product role's filing column, the triage's three arguments, the poller's fallback —
spelled a literal instead of asking, because asking meant importing a vendor's module to learn
the platform's own word. The names have not changed; their HOME has, and these tests pin both.

**The identity.** *Who is this person on this tracker* and *how do I address them so they are
notified* were answered in the activities by comparing the provider's name to `"github"`. They
are the row's answers, and the port now says so — in the shape `link_child` already had:
declared on the port, called through `getattr` with today's answer as the default. What that
shape does and does not buy was measured here rather than assumed, and the last test says so.
"""

from __future__ import annotations

import inspect

import pytest

from openfactory.adapters.board.columns import (
    BOARD_ORDER,
    CANONICAL_COLUMNS,
    column_names,
    name_for,
)

# ── the columns: one home, and the value did not move with it ───────────────────────────────────

#: What `main` held, spelled out rather than derived. A test that computed this from the module it
#: is checking would bless whatever the module says — which is the whole failure mode of moving a
#: constant. These six strings are the platform's vocabulary as it stood before the move.
BEFORE = ("Backlog", "TO-DO", "In progress", "In review", "Needs Action", "Done")


def test_the_move_changed_no_name() -> None:
    assert column_names() == BEFORE
    assert sorted(CANONICAL_COLUMNS.values()) == sorted(BEFORE)


def test_the_order_covers_the_map_exactly() -> None:
    """The two rotted apart once: the creating act listed six names in order and the runtime map
    five plus a sixth appended after it, so a reader comparing them saw two vocabularies."""
    assert set(BOARD_ORDER) == set(CANONICAL_COLUMNS)
    assert len(BOARD_ORDER) == len(CANONICAL_COLUMNS) == 6


def test_a_key_the_platform_does_not_know_answers_empty() -> None:
    """`""`, never a raise: every caller of this is naming a column to LOOK FOR on somebody's
    board, and a board without it is an ordinary answer the platform already handles."""
    assert name_for("todo") == "TO-DO" and name_for(" TODO ") == "TO-DO"
    assert name_for("sprint") == "" and name_for("") == "" and name_for(None) == ""  # type: ignore[arg-type]


def test_every_neutral_caller_reads_the_home_rather_than_a_literal() -> None:
    """The four places that used to spell a name, each asserted against the home.

    Read through the objects rather than by grepping the source: a grep passes the day somebody
    writes the literal back in a place the grep does not look."""
    from openfactory.product.module import ProductModule
    from openfactory.product.triage import triage

    assert ProductModule.FILING_COLUMN == CANONICAL_COLUMNS["backlog"]
    assert ProductModule.QUEUE_COLUMN == CANONICAL_COLUMNS["todo"]

    defaults = inspect.signature(triage).parameters
    assert defaults["active_columns"].default == (CANONICAL_COLUMNS["in_progress"],)
    assert defaults["waiting_column"].default == CANONICAL_COLUMNS["needs_action"]
    assert defaults["done_column"].default == CANONICAL_COLUMNS["done"]


def test_the_pollers_last_resort_follows_the_home_rather_than_a_literal() -> None:
    """The one caller whose answer is INSIDE a function, so no attribute can be read for it.

    MEASURED, AND IT IS WHY THIS TEST EXISTS. The first run of this slice's mutation plan cut
    `CANONICAL_COLUMNS["todo"]` back to the literal `"TO-DO"` in `_pickup_column` and every test
    stayed green — the two spell the same six characters today, so nothing behavioural could tell
    them apart and every assertion available was about a value that had not changed. A guard that
    cannot see the cut is decoration.

    So the home is moved and the caller is asked again. The import is `from … import
    CANONICAL_COLUMNS`, which binds the same dict OBJECT, so editing the home here is what the
    activities read — and a literal cannot follow."""
    from openfactory.runtime.temporal import activities

    project = type("P", (), {
        "name": "acme",
        "tracker": type("T", (), {"options": {}, "kind": "nothing-buildable"})(),
    })()

    CANONICAL_COLUMNS["todo"] = "Fila"
    try:
        assert activities._pickup_column(project) == "Fila", (
            "the poller's last resort spelled its own literal instead of asking the platform for "
            "the name of the pickup column")
    finally:
        CANONICAL_COLUMNS["todo"] = "TO-DO"

    assert activities._pickup_column(project) == "TO-DO"


def test_the_github_rows_still_answer_what_they_answered() -> None:
    """The two vendor copies now READ the home. Their values are the ones a live board was
    created with, so a change here is a change to somebody's existing board."""
    from openfactory.adapters.tracker.github_board_setup import CANONICAL_COLUMNS as CREATED
    from openfactory.adapters.tracker.github_project import DEFAULT_COLUMNS as RUNTIME

    assert CREATED == BEFORE
    assert RUNTIME == {"todo": "TO-DO", "in_progress": "In progress", "in_review": "In review",
                       "needs_action": "Needs Action", "done": "Done", "backlog": "Backlog"}


def test_the_runtime_map_is_a_copy_nobody_can_reach_the_home_through() -> None:
    """A caller mutating the adapter's dict must not reach the table every other axis reads."""
    from openfactory.adapters.tracker.github_project import DEFAULT_COLUMNS

    DEFAULT_COLUMNS["todo"] = "sabotage"
    try:
        assert CANONICAL_COLUMNS["todo"] == "TO-DO"
    finally:
        DEFAULT_COLUMNS["todo"] = "TO-DO"


def test_the_azure_row_keeps_its_own_names() -> None:
    """A vendor whose board ALREADY EXISTS is entitled to its own defaults — Azure Boards says
    `To Do` and `Doing`, and the move must not have quietly made them the platform's."""
    from openfactory.adapters.board.azure_devops import DEFAULT_COLUMNS as ADO

    assert ADO["todo"] == "To Do" and ADO["in_progress"] == "Doing"
    assert ADO["todo"] != CANONICAL_COLUMNS["todo"]


# ── the identity: the row answers, not the lifecycle ────────────────────────────────────────────

class _Row:
    """A tracker that implements both capabilities — a stranger's, as far as the core knows."""

    def identity_of(self, subject_id: str) -> str:
        return subject_id

    def mention(self, login: str) -> str:
        return f"<{login}>"


class _Silent:
    """A tracker from before the capabilities existed. It must keep working, unchanged."""


class _Angry:
    def identity_of(self, subject_id: str) -> str:
        raise RuntimeError("the vendor is down")

    def mention(self, login: str) -> str:
        raise RuntimeError("the vendor is down")


def test_the_three_vendor_rows_answer_for_themselves() -> None:
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker
    from openfactory.adapters.tracker.github import GitHubIssuesTracker
    from openfactory.adapters.tracker.jira import JiraTracker

    assert GitHubIssuesTracker.mention(None, "mara") == "@mara"
    assert JiraTracker.mention(None, "Mara Silva") == "Mara Silva"
    assert AzureBoardsTracker.mention(None, "mara@acme.com") == "mara@acme.com"

    # None of the three can spell a platform id in its own namespace, and says so.
    for row in (GitHubIssuesTracker, JiraTracker, AzureBoardsTracker):
        assert row.identity_of(None, "panel") == ""


def test_a_mention_degrades_to_the_plain_name_three_ways() -> None:
    """The default, the empty login and the vendor that raised — one answer for all three, and it
    is the one every non-GitHub tracker gave before the port had the question."""
    from openfactory.runtime.temporal.activities import _mention_for

    assert _mention_for(_Row(), "mara") == "<mara>"
    assert _mention_for(_Silent(), "mara") == "mara"
    assert _mention_for(_Angry(), "mara") == "mara"
    assert _mention_for(_Row(), "") == "" and _mention_for(_Row(), "   ") == ""


@pytest.mark.parametrize("tracker", [None, _Silent(), _Row()])
def test_a_declared_map_beats_every_row(tracker) -> None:
    """What somebody declares beats what a machine infers — including a row that would answer."""
    from openfactory.product.requester import forge_identity_for

    project = type("P", (), {"people": {"joao": "U09XYZ"}})()
    assert forge_identity_for(project, "U09XYZ", tracker) == "joao"
    assert forge_identity_for(project, "<@U09XYZ>", tracker) == "joao"


def test_the_row_is_asked_only_when_the_map_held_nobody() -> None:
    from openfactory.product.requester import forge_identity_for

    empty = type("P", (), {"people": {}})()
    assert forge_identity_for(empty, "panel", _Row()) == "panel", "the row's own namespace"
    assert forge_identity_for(empty, "panel", _Silent()) == "", "today's answer, unchanged"
    assert forge_identity_for(empty, "panel") == "", "no tracker passed at all — today's answer"
    assert forge_identity_for(empty, "", _Row()) == "", "nobody asked is still nobody"


def test_an_ambiguous_declaration_is_not_papered_over_by_a_row() -> None:
    """Two logins for one id is a configuration MISTAKE somebody has to fix. A row answering over
    it would hide the mistake behind a plausible name — which is worse than not asking."""
    from openfactory.product.requester import forge_identity_for

    project = type("P", (), {"people": {"ana": "U04ABC", "bea": "U04ABC"}})()
    assert forge_identity_for(project, "U04ABC", _Row()) == ""


def test_a_row_that_raises_leaves_the_factory_not_asking() -> None:
    from openfactory.product.requester import forge_identity_for

    empty = type("P", (), {"people": {}})()
    assert forge_identity_for(empty, "panel", _Angry()) == ""


def test_the_port_declares_both_and_conformance_names_them() -> None:
    """Declared on the port, so a row LEARNS the question exists — and conformance names them.

    MEASURED, NOT ASSUMED, AND THE ISSUE SAID OTHERWISE. `check_tracker` asks
    `isinstance(tracker, TrackerAdapter)` against a runtime-checkable Protocol, which demands
    every public member — so a capability declared here is a capability conformance REQUIRES.
    `link_child` and `children_of` have always been in that position: "optional" in this house
    means the CALLER does not depend on it (getattr, today's answer as the default), never that
    the port stays silent about it.

    The cost is bounded and worth naming: `check_tracker` is a REPORT — the
    `openfactory conformance-adapter` verb and this suite are its only callers, and nothing in
    the build path consults it — so a stranger's add-on shipped against yesterday's core keeps
    RUNNING and its report gains one finding that names exactly what to add."""
    from openfactory.adapters.tracker.base import TrackerAdapter
    from openfactory.conformance.adapters import check_tracker

    assert hasattr(TrackerAdapter, "identity_of") and hasattr(TrackerAdapter, "mention")

    detail = " ".join(f.detail for f in check_tracker(_Silent()))
    assert "identity_of" in detail and "mention" in detail, (
        "a row that implements neither must be TOLD which two methods it is missing")

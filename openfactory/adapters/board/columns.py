"""The platform's own column vocabulary — six names, six neutral keys, one board order.

WHY THIS FILE EXISTS, AND WHY IT IS NOT IN A VENDOR'S MODULE. The six names were written down
three times and compared in four more, and every copy lived at a GitHub address:
`github_board_setup.CANONICAL_COLUMNS` (creation, in board order), `github_project.DEFAULT_COLUMNS`
(the runtime map, unordered), and four literals in neutral code — the product role's `FILING_COLUMN`
and `QUEUE_COLUMN`, the triage's three column arguments and the poller's `"TO-DO"` fallback. Any
reader of those four could only conclude the platform's queue is a GitHub concept, and the next row
on any axis would have had to import a vendor's module to learn the platform's own words.

`STATE_KEYS` (`adapters/tracker/base.py`) already answers *which key does this job state belong to*
for every tracker and every board. This answers the other half — *what does the platform call that
key* — and the two together are the whole vocabulary. A client whose board says `A Fazer` maps the
KEYS in the registry (`columns:`, C-14, ADR-0022 §4); the states stay closed and only the labels
open. This file is what the mapping starts as, never what it must stay.

NOT A PORT AND NOT A REGISTRY. Nothing dispatches here: it is a table two adapters and three
neutral callers read, so it takes no import beyond the standard library and can be read from
anywhere without dragging a vendor, a token or pydantic in behind it.
"""

from __future__ import annotations

#: The platform's own name for each neutral column key. A board CREATED by the platform uses
#: these verbatim, which is why the mapping starts as the identity; a board that already existed
#: keeps its own names and maps them per key in the registry.
#:
#: `backlog` IS A COLUMN, NOT AN ABSENCE. A ticket a person took off the floor belongs with the
#: work nobody is working on — the reasoning is written where the states are bound
#: (`tracker/base.py::_PARKED_BY_A_PERSON`), and the two tables have to agree on the key or a
#: state resolves to a column nothing declares.
CANONICAL_COLUMNS: dict[str, str] = {
    "backlog": "Backlog",
    "todo": "TO-DO",
    "in_progress": "In progress",
    "in_review": "In review",
    # Parked waiting on a HUMAN → a column of its own, never Backlog: a ticket that needs you must
    # not hide among the ones nobody has started.
    "needs_action": "Needs Action",
    "done": "Done",
}

#: The keys in BOARD ORDER — left to right as a person reads the board, which is the order a
#: creating act writes its columns in and is NOT the order a dict literal happens to carry.
#: Kept as its own tuple, and asserted to cover the map exactly, because the two answers rotted
#: apart once already: the creating act listed six names in order and the runtime map five plus a
#: sixth appended after it, so a reader comparing them saw two different vocabularies.
BOARD_ORDER: tuple[str, ...] = (
    "backlog", "todo", "in_progress", "in_review", "needs_action", "done",
)


def column_names() -> tuple[str, ...]:
    """The six names in board order — what a creating act writes onto a new board.

    A FUNCTION RATHER THAN A SECOND CONSTANT, so there is exactly one place the order and the
    names meet and no copy of the answer can drift from the map above."""
    return tuple(CANONICAL_COLUMNS[key] for key in BOARD_ORDER)


def name_for(key: str) -> str:
    """The platform's name for one key, or `""` for a key it does not know.

    `""` RATHER THAN A RAISE, because every caller of this is naming a column to look for on a
    board, and a board that does not have it is an ordinary answer this platform already handles
    (`set_column` returns False, `set_status` no-ops). A traceback here would turn a board's
    missing column into a crashed job."""
    return CANONICAL_COLUMNS.get((key or "").strip().lower(), "")

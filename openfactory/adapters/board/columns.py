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


#: The keys a card sits in BEFORE the factory has taken it up, and the ones that mean it has.
#:
#: THE WRITE SIDE OF THIS HAS ALWAYS EXISTED AND THE READ SIDE DID NOT (#150). A job's state is
#: resolved to a key by `STATE_KEYS` and the row moves the card, so the column IS where a card got
#: to — but nothing answered the question back in the platform's own words. Every caller that
#: wanted it re-derived it from the column NAME, and two gave up and searched the card's body text
#: instead (`product/queue.py`, `product/triage.py`), which is how the queue came to call ready
#: what the spec gate refuses.
#:
#: `todo` AND `backlog` ARE THE OPERATOR'S; the other four are the factory's own writing. A card in
#: `in_progress`, `in_review`, `needs_action` or `done` is there because `set_state` put it there.
BEFORE_THE_FACTORY: tuple[str, ...] = ("backlog", "todo")

#: The keys a card sits in once the factory has FINISHED with it (#162).
#:
#: "TAKEN UP" WAS READ AS "A JOB MAY BE RUNNING", AND FOR ONE COLUMN THAT IS NOT TRUE. The stage
#: gate refused a close in every column `has_started` answers for, with the sentence *"a job may
#: be working on it right now … Stop the job first"* — said of a card in Done, where the job ended
#: and there is nothing to stop. It is also the card triage reports as `done-but-open` and asks a
#: person to close, so the platform asked for a close it then refused.
#:
#: A NAMED SET BESIDE THE OTHER ONE, so the question is asked of the vocabulary and no caller
#: compares a key to `"done"`. It stays a subset of what `has_started` answers for: the factory DID
#: take a finished card up, which is why editing one is still refused.
#:
#: AND IT IS `done` ALONE ON PURPOSE, NOT BY ACCIDENT (review of #191, evidence 2026-09-20). The
#: obvious next candidate is `needs_action` — a card the factory handed back, which can sit there
#: for ever — and it does NOT belong here, because `has_finished` decides one thing only: whether a
#: close is recorded as DELIVERED. A parked card never shipped. Recording one as delivered would be
#: the eleven-duplicates incident in reverse, and `triage.Ticket.delivered` reads that word
#: downstream. Whether such a card may be closed AT ALL is a different question, and the column is
#: the wrong thing to ask: `needs_action` covers both a job parked alive on `wait_condition`
#: (`workflow.py::_wait_operator`) and no job at all — the gather's question parks the card and
#: RETURNS `SKIPPED` (`_lifecycle`), and an elapsed impediment deadline returns the park untouched
#: and completes. So the close asks the ENGINE whether a job is really on the card
#: (`actions/catalog.py::_job_on_the_card`), and this table keeps answering only what it can know.
AFTER_THE_FACTORY: tuple[str, ...] = ("done",)


def key_for(name: str, *, renamed: dict[str, str] | None = None) -> str:
    """The neutral key a board's own column NAME means, or `""` when nothing maps it.

    THE INVERSE OF `name_for`, and it takes the deployment's map because only that can answer: a
    client whose board says `A Fazer` declares `columns: {"todo": "A Fazer"}` in the project's
    tracker options (C-14, ADR-0022 §4), and the hosted rows already merge exactly that map over
    their defaults. Falling back to the canonical names is right for a board the platform created,
    which uses them verbatim.

    `""` RATHER THAN A GUESS, for the same reason `name_for` answers `""`: a column this platform
    does not know is a legitimate thing for a client's board to have, and a caller deciding what
    may be done to a card must be able to tell *I know this column* from *I do not*.
    """
    wanted = (name or "").strip().casefold()
    if not wanted:
        return ""
    for key, spelled in {**CANONICAL_COLUMNS, **(renamed or {})}.items():
        if str(spelled).strip().casefold() == wanted:
            return str(key)
    return ""


def has_started(key: str) -> bool:
    """Whether a card in this column is one the factory has taken up.

    ASKED OF A KEY THE CALLER HAS ALREADY RESOLVED. An unmapped column answers `""` from
    `key_for`, which is *I cannot tell* and not *it has not started* — folding the two here would
    quietly answer the safe-sounding one, and the caller that must refuse cannot see the
    difference."""
    return bool(key) and key not in BEFORE_THE_FACTORY


def has_finished(key: str) -> bool:
    """Whether a card in this column is one the factory has finished with — delivered work.

    `""` ANSWERS FALSE, for the reason `has_started` gives: an unmapped column is *I cannot tell*,
    and a caller about to record a card as delivered must not get there on a guess."""
    return bool(key) and key in AFTER_THE_FACTORY


def may_be_running(key: str) -> bool:
    """Whether a job may be working on a card in this column right now.

    Taken up and not finished. This is the question a CLOSE asks — taking a card off the board
    from under its job is what that gate prevents — and it is narrower than `has_started`, which
    is the question an EDIT asks (#162).

    `MAY` IS THE WHOLE WORD, AND IT IS NOT THE LAST WORD (review of #191). A column is where the
    factory last put the card, never proof that a job is still on it: `in_review` holds a card
    whose merge watch is alive, and `needs_action` holds both a job parked on a signal and a card
    whose workflow ended hours ago. This answers the board's half; `_job_on_the_card` asks the
    engine for the other half before a close is refused."""
    return has_started(key) and not has_finished(key)


def name_for(key: str) -> str:
    """The platform's name for one key, or `""` for a key it does not know.

    `""` RATHER THAN A RAISE, because every caller of this is naming a column to look for on a
    board, and a board that does not have it is an ordinary answer this platform already handles
    (`set_column` returns False, `set_status` no-ops). A traceback here would turn a board's
    missing column into a crashed job."""
    return CANONICAL_COLUMNS.get((key or "").strip().lower(), "")

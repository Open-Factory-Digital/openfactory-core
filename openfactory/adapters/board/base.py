"""What a BOARD is, independently of who provides it.

The product owner, 2026-07-28, on why the board needed a seam of its own: *"handing them `gh`
directly strikes me as an architectural error — if it were Jira, for example, it would not be `gh`,
and that is a premise of OpenFactory."*

That is right, and the debt was worse than the phrasing suggests: the board was not merely reachable
through a vendor command, it **did not exist as a concept**. `TrackerAdapter` covers tickets —
create, comment, label, link — and says nothing about columns; `GitHubProjectBoard` was constructed
directly in six places across the CLI, the poller, the panel, the product module and the Slack bot.
A Jira deployment would not have had a worse board; it would have had none, and the failure would
have surfaced as an import error in the poller.

So this protocol is deliberately SMALL and derived from what the code actually calls, not from what
a board could conceivably do. Every method here has a production caller today:

    columns()          the whole board as {ticket: column} — the read the agents are HANDED
    column_names()     which columns EXIST, whatever is or is not sitting in them
    items_in_status()  the pickup queue, the single hottest read in the system
    add_item()         put a ticket on the board at all
    set_column()       move a card to a named column
    set_status()       move a card to the column mapped from a JobState

TWO RULES THAT ARE NOT NEGOTIABLE FOR ANY IMPLEMENTATION:

**`columns()` returns None when it could not read, `{}` only when the board is genuinely empty.**
Three separate bugs in this codebase came from collapsing those into one value — an unreadable
board became "nothing is queued", "no findings", "the questions resolved themselves". A provider
that cannot tell the difference must return None.

**No vendor vocabulary escapes the implementation.** Callers pass ticket REFS and column NAMES,
never project ids, node ids, field ids or GraphQL. That is what lets the product role be handed a
board it can reason about without knowing who keeps it.

**A ticket ref is the PROVIDER'S OWN STRING, never a number** (C-05). This protocol was typed with
`int` throughout, which is the one shape a Jira board cannot produce: `CONT-412`. Azure DevOps
(`1234`), GitLab and GitHub are all numeric, so the hole was invisible — Jira is the outlier, and
it is why the backlog's own fixture card is named *the non-numeric-ref fixture*.

The `int` was never buying arithmetic; nothing here adds or averages a ticket ref. It was buying
ORDERING, and that is now `contracts.refs.ref_sort_key`, which sorts by prefix and then
numerically. Identity and ordering are different questions, and only one of them needs a number.

Converting at this seam instead — taking the digits out of `CONT-412` — would be worse than the
bug: a Jira board routinely spans projects, so `CONT-412` and `PROJ-412` would both become `412`
and the platform would treat two tickets as one. And the ref has to go BACK to the provider; a
comment on `CONT-412` cannot be addressed with `412`.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from openfactory.contracts import JobState

log = logging.getLogger("openfactory.board")


@runtime_checkable
class Rankable(Protocol):
    """A board whose backlog ORDER can be written — the product owner's second verb (#33).

    A SECOND PROTOCOL, NOT A METHOD ON `BoardAdapter`, and that is the point of it. Every board
    can be read and every card can be moved between columns; not every board has a rank a client
    of this platform is allowed to write, and a capability bolted onto the base protocol would make
    every double, every conformance fake and every client's own adapter claim it or fail
    `isinstance`. The three boards shipped here all rank (Azure Boards by `StackRank`, GitHub
    Projects by item position, Jira by the Agile rank endpoint); a board that does not is told so
    by `ProductModule.reorder` in one sentence, never by an `AttributeError` in a chat.
    """

    def place_after(self, *, issue: str, issue_url: str, after: str | None, column: str) -> bool:
        """Put `issue` immediately after `after` in the backlog's rank order — `after=None` is the
        top. `column` names where the neighbours are looked up on a provider whose rank is read per
        column (Azure Boards); a provider whose rank is global ignores it. False when the provider
        could not, with a reason logged — never a raise, for the same reason `set_column` never
        raises: a False must always leave a why behind it."""
        ...


@runtime_checkable
class Watchable(Protocol):
    """A board a person can WATCH — one whose re-read costs so little that a surface may repeat it
    while somebody is looking (ADR-0049 D6).

    A THIRD PROTOCOL, FOR `Rankable`'S EXACT REASON, and the reason is worth stating because the
    alternative is the one this platform keeps refusing: the panel comparing a provider's name.
    Watching a board means asking it again every few seconds, which is free against a file on the
    same machine and is a rate-limit incident against somebody's hosted API. The panel must not
    decide which is which — a new row would be decided about by a surface that has never met it —
    and putting the question on `BoardAdapter` would make every board, every double and every
    client's own adapter claim an answer or fail `isinstance`.

    So a board that is cheap to re-read says so, and one that is silent is simply not watched. The
    panel reads a NUMBER and never a kind."""

    def poll_seconds(self) -> int:
        """How often a surface may re-read this board while a person is looking at it, in seconds.

        THE ROW CHOOSES, because only the row knows what it costs. A file on this machine can
        answer every few seconds; nothing that crosses a network should claim one at all — it
        should not implement this protocol."""
        ...


@runtime_checkable
class Staged(Protocol):
    """A board that can say which neutral STAGE one of its own columns is (#231).

    A FOURTH PROTOCOL, FOR `Rankable`'S EXACT REASON — and this one was learned rather than
    designed. The stage gate on `card_edit`/`card_close` resolved the key itself, out of one option
    name it hoped every tracker spelled alike:

        key_for(column, renamed=proj.tracker.options.get("columns"))

    `ProviderRef.options` is `dict[str, str]`, so that value is a string or absent, and `key_for`
    wants a mapping. Absent mapped nothing — on Jira, whose columns ARE the site's workflow
    statuses, that refused every edit and every close on every card; present raised `TypeError:
    'str' object is not a mapping` in front of an operator. The deployment had declared its names
    all along, in the Jira row's OWN option (`status_map`), which generic code had no way to know
    about.

    WHICH IS THE WHOLE POINT: *what does this board call `done`* is the row's question, the same
    way `pickup_column()` is. Each row already holds the answer — the hosted two merge the client's
    `columns` over their defaults, Jira reads the tracker's `status_map`, the local board reads the
    key off its own rows — and there was simply no way to ask for it. A constant standing in for a
    question only the provider can answer is the defect `pickup_column` already paid for once.

    OPTIONAL, AND A SILENT ROW STILL WORKS. `stage_key` is reached through the module function
    below, never by `isinstance` (a mock satisfies a `runtime_checkable` protocol by having
    attributes), and a row that does not implement it is read by the platform's own six names —
    which is exactly right for a board this platform created and honestly degraded for one that
    renamed its columns.
    """

    #: The registry option, on this project's tracker row, that declares this board's column
    #: names — `columns` for the rows that take the platform's map, `status_map` on Jira. A plain
    #: class attribute rather than a method because it is a LITERAL each row knows about itself,
    #: and it exists so the refusal for a column nobody maps can name the option a person should
    #: actually go and edit. Telling a Jira operator to set `columns` is a remedy that changes
    #: nothing.
    stage_option: str

    def stage_key(self, column: str) -> str:
        """The neutral key this board's column `column` means, or `""` when nothing maps it.

        `""` IS A REAL ANSWER and must stay one: a column this platform does not know is a
        legitimate thing for a client's board to have, and the gate that decides what may be done
        to a card has to tell *I know this column* from *I do not* (`columns.key_for`). What was
        wrong was meeting that answer on every card."""
        ...


@runtime_checkable
class BoardAdapter(Protocol):
    """A column-based view of tickets. Optional per deployment: a project with no board configured
    has no adapter at all, and every caller already handles that."""

    def url(self) -> str:
        """Where a PERSON goes to look at this board, or `""` when there is nowhere to send them.

        THE PANEL WAS BUILDING THIS BY HAND, from GitHub Projects v2 vocabulary
        (`board_owner`/`board_number`) and a literal `github.com`, on the reference surface of a
        product sold as vendor-agnostic. An Azure or Jira deployment got a link to a github.com
        page that does not exist — and the panel had ALREADY paid for this class once: the same
        line shipped an `/orgs/` URL for a user-owned board and 404ed on somebody's own account.

        A board URL is provider knowledge, exactly like `clone_url` and `ticket_url`: the host, the
        path shape, and the org-vs-user asymmetry GitHub has and the others do not. It belongs to
        the adapter that already holds the coordinates.

        `""` RATHER THAN A GUESS, because the caller's alternative is to show no button — which is
        honest — while a wrong link is a person clicking through to a 404 and concluding the
        platform has lost their board.
        """
        ...

    def columns(self) -> dict[str, str] | None:
        """`{ticket ref: column name}` for the whole board.

        `None` = COULD NOT READ. `{}` = read fine, nothing on it. Callers depend on the
        distinction; see the module docstring."""
        ...

    def column_names(self) -> list[str] | None:
        """Which columns the board HAS, in board order.

        A DIFFERENT QUESTION FROM `columns()`, and conflating the two is what this method exists to
        make impossible. `columns()` answers *where are the cards*; on an empty board that is `{}`,
        and on a busy one its keys are ticket refs. Neither tells you whether a column named
        `TO-DO` exists — which is the only thing `openfactory doctor` wants to know, and the one
        setup
        mistake whose symptom is total silence.

        Same `None` rule as `columns()`: `None` = could not read, `[]` = read fine and the board
        genuinely defines none. A provider that cannot distinguish them must return None, because
        reporting an unreadable board as a column-naming problem sends somebody to rename columns
        they are looking straight at."""
        ...

    def pickup_column(self) -> str:
        """What THIS board calls the column the poller picks work up from.

        THE ONE QUESTION NOBODY COULD ASK, AND THE POLLER GUESSED IT. The queue was resolved as
        *explicit `pickup_status`* → *the client's `columns.todo`* → the literal `"TO-DO"`, with a
        comment claiming a Portuguese board therefore needs zero extra config. It was true for
        exactly one provider: GitHub's canonical board really does say `TO-DO`. Azure Boards says
        `To Do`, so an ADO deployment that configured nothing wrong asked for a column that does
        not exist and read an empty queue — the silent stall this platform exists to end, arriving
        through the front door of its own default.

        Each adapter already HELD the answer (`DEFAULT_COLUMNS` merged with the client's override,
        C-14); there was simply no way to ask for it. So the platform kept a literal instead, which
        is the same defect as a hardcoded vendor name wearing a different hat: a constant standing
        in for a question only the provider can answer.

        Implementations return the client's override when there is one and their own default
        otherwise. Never empty — a caller has to be able to name the column it looked for."""
        ...

    def items_in_status(self, status: str) -> list[str]:
        """Ticket refs sitting in one column, in board order — the pickup queue.

        IN BOARD ORDER, which the provider decides — this does not re-sort. A caller that needs a
        different order uses `refs.ref_sort_key`; a caller that re-sorted these as plain strings
        would put `CONT-10` before `CONT-2`."""
        ...

    def add_item(self, *, issue_url: str) -> None:
        """Put a ticket on the board. Idempotent."""
        ...

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        """Move a card to a column BY NAME. False when the column does not exist.

        `issue` rather than `issue_number`: the parameter carries the provider's ref, and a name
        promising a number is how the type came to be `int` in the first place."""
        ...

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        """Move a card to whichever column this provider maps `state` to."""
        ...


# ── asking an optional capability, the way `tracker/base.py::close_ticket` does ─────────────────
# A module function rather than a call at each site: the degrade for a row that does not answer has
# to be decided ONCE, or the gate and the product role come to read the same board differently.


def stage_key(board, column: str) -> str:
    """Which neutral stage `column` is on `board` — the ONE place generic code asks (#231).

    THROUGH THE ROW, NEVER THROUGH AN OPTION NAME. See `Staged` for what reading one option name
    out of generic code cost. The fallback is the platform's own six names and nothing else: a
    board that says nothing is a board this platform created, or an add-on written before the verb
    existed, and the canonical vocabulary reads both correctly.

    ONLY A REAL ANSWER IS BELIEVED. A `MagicMock` answers every call with another mock, and a
    stage key that is not a string travels into `has_started`/`has_finished` and compares equal to
    nothing — a gate that silently refuses every card, which is this very defect wearing a test
    double's clothes. A row that claims the verb and answers otherwise is named in the log, because
    a silent degrade here stays invisible until somebody's card cannot be closed."""
    from openfactory.adapters.board.columns import CANONICAL_COLUMNS, key_for

    name = (column or "").strip()
    if not name:
        return ""
    # NO BOARD IS NOT "NO ANSWER". A project can run on tickets alone and still have a caller
    # holding a column name (`ProductModule.correct_card` reads one off the card); the platform's
    # own vocabulary is the honest read there, and it is what that caller had before this seam.
    if board is not None and callable(getattr(board, "stage_key", None)):
        try:
            said = board.stage_key(name)
        except Exception as exc:  # noqa: BLE001 — a board that cannot say is not a traceback
            log.warning("OPENFACTORY_BOARD_STAGE_UNANSWERED column=%r: %s raised when asked which "
                        "stage it is (%s) — reading it by the platform's own column names, which "
                        "is right only for a board this platform created",
                        name, type(board).__name__, str(exc)[:200])
        else:
            # A KEY, OR NOTHING. `""` is the row saying *I do not map this one*, which is a real
            # answer the gate needs. Anything else has to be one of the platform's six, because
            # `has_started`/`has_finished` compare against exactly those: a row answering with its
            # own private key (a board may carry columns this platform knows nothing about) would
            # be read as "the factory has taken it up" and refuse a card nobody is working on.
            key = said.strip() if isinstance(said, str) else None
            if key == "" or (key and key in CANONICAL_COLUMNS):
                return key
            log.warning("OPENFACTORY_BOARD_STAGE_UNANSWERED column=%r: %s answered %r, which is "
                        "not one of this platform's stage keys (%s) — the answer is ignored in "
                        "favour of the platform's own column names",
                        name, type(board).__name__, said, ", ".join(CANONICAL_COLUMNS))
    return key_for(name)


def stage_option(board) -> str:
    """The tracker option that declares THIS board's column names, or `""` when it declares none.

    What a refusal offers as the repair, and it has to come from the row: `columns` is right for
    the rows that take the platform's map and wrong for Jira, whose map is `status_map`. A
    non-empty string is the only thing accepted as a declaration — a mock's attribute is not one,
    and a refusal naming an option the deployment does not have is worse than one naming none."""
    named = getattr(board, "stage_option", "")
    return named.strip() if isinstance(named, str) else ""

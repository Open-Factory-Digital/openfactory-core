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

from typing import Protocol, runtime_checkable

from openfactory.contracts import JobState


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

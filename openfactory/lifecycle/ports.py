"""Everything the card's door reads and writes, behind one object (ADR-0055 D3).

THE EXISTING PORTS, NOT NEW ONES: the tracker writes the card, the ledger keeps the promises,
`events.py` tells the conversation, the engine takes the preview down, the board's snapshot is
forgotten, and the metrics store keeps the record. `Ports` holds them for one project, so the
door asks one object — and the test derived from the table hands it a double of every port and
asserts that exactly the table's effects happened.

EACH EFFECT RETURNS WHAT IT CAME TO, as the record's outcome, and RAISES WHEN IT FAILED: the
executor records the failure and the sweep applies the effect again (D5). An effect with nothing
to do — no preview running, nothing promised about the card — is an outcome, not a failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openfactory.lifecycle.table import BY_COLUMN, State

log = logging.getLogger("openfactory.lifecycle.ports")


@dataclass(frozen=True)
class Seen:
    """A card as the door found it: its state, or why nobody can tell; and its title."""

    state: State | None = None
    cannot_tell: str = ""
    title: str = ""
    #: which of the product role's writers opened the card — `""` for a card written on the board
    opened_by: str = ""
    #: whether the tracker says the card is open — a finished card can be either (`delivered`)
    open: bool = True


class Unreadable(RuntimeError):
    """The tracker or the board could not be read — a state, not "the card is not there"."""


class Ports:
    """The real ports of one project. `tracker` and `board` are the caller's when it holds them,
    so a row that read the board for its own gate and the door read the same row; `columns` is the
    board as that row already READ it — one read for the gate and the door, which could otherwise
    disagree about a card that moved between them (#162)."""

    def __init__(self, project, *, tracker=None, board=None,
                 columns: dict[str, str] | None = None) -> None:
        self.project = project
        self.name = getattr(project, "name", "") or ""
        self._tracker = tracker
        self._board = board
        self._built = tracker is not None
        self._columns = columns

    def _where(self) -> dict[str, str] | None:
        if self._columns is None:
            self._columns = self.board.columns() if self.board is not None else {}
        return self._columns

    # ── what the door reads ─────────────────────────────────────────────────────────────────────

    @property
    def tracker(self):
        if self._tracker is None:
            self._build()
        return self._tracker

    @property
    def board(self):
        if not self._built:
            self._build()
        return self._board

    def _build(self) -> None:
        from openfactory.adapters.board import build_board
        from openfactory.adapters.tracker.registry import build_tracker
        from openfactory.credentials import deployment_tracker_token, tracker_token_for

        token = tracker_token_for(self.project) or deployment_tracker_token(self.project)
        if self._tracker is None:
            self._tracker = build_tracker(self.project, token=token)
        if self._board is None:
            self._board = build_board(self.project, token=token)
        self._built = True

    def sink(self):
        from openfactory.lifecycle.record import keyed_sink

        return keyed_sink()

    def seen(self, card: str) -> Seen:
        """Where `card` is. Absent from its tracker: `removed`. Closed: `closed`. Open: what its
        board's column says — `None` when no board places it, and a sentence when a board cannot be
        read or names a column this platform does not map, which refuses rather than guesses."""
        from openfactory.adapters.board.base import stage_key
        from openfactory.contracts.refs import canonical_ref

        try:
            ticket = self.tracker.get_ticket(card)
        except KeyError:
            return Seen(state=State.REMOVED)
        except Exception as exc:  # noqa: BLE001 — an unreadable card is an answer, and it refuses
            log.warning("OPENFACTORY_CARD_UNREAD card=%s: %s", card, exc)
            return Seen(cannot_tell=(f"#{card.lstrip('#')} could not be read ({str(exc)[:120]}), "
                                     f"so there is no way to tell where it is. Nothing was "
                                     f"changed — try again."))
        from openfactory.product.authoring import filed_by_the_product_role

        title = str(getattr(ticket, "title", "") or "")
        opened_by = filed_by_the_product_role(getattr(ticket, "raw", "") or "")
        if (getattr(ticket, "state", "") or "open") != "open":
            return Seen(state=self._closed_as(card, ticket), title=title, opened_by=opened_by,
                        open=False)
        board = self.board
        if board is None:
            return Seen(state=None, title=title, opened_by=opened_by)
        where = self._where()
        if where is None:
            return Seen(title=title, cannot_tell=(
                f"{self.name}'s board could not be read, so there is no way to tell where "
                f"#{card.lstrip('#')} is. Nothing was changed — try again."))
        column = where.get(canonical_ref(card)) or where.get(str(card))
        if not column:
            return Seen(state=None, title=title, opened_by=opened_by)
        state = BY_COLUMN.get(stage_key(board, column))
        if state is None:
            return Seen(title=title, cannot_tell=(
                f"#{card.lstrip('#')} is in {column!r}, which is not a column this platform "
                f"maps, so it cannot tell where the card is in its life. Map it in the "
                f"project's tracker options. Nothing was changed."))
        return Seen(state=state, title=title, opened_by=opened_by)

    def _closed_as(self, card: str, ticket) -> State:
        """A closed card is `delivered` when it was closed as finished work — the tracker's own
        reason says so, or its board still shows it in Done (Jira closes a card BY moving it to a
        status in the done category) — and `closed` otherwise: withdrawn, a duplicate, not
        planned. Unsure is `closed`: a reopen is allowed from both, and only a finished card may
        be closed again as delivered."""
        from openfactory.adapters.board.base import stage_key
        from openfactory.contracts.refs import canonical_ref

        reason = str(getattr(ticket, "state_reason", "") or "").lower()
        if reason in ("not_planned", "not planned", "duplicate"):
            return State.CLOSED
        if reason == "completed":
            return State.DELIVERED
        try:
            where = self._where() or {}
        except Exception:  # noqa: BLE001 — unsure, and unsure is `closed`
            log.info("could not read where closed #%s sits on its board", card, exc_info=True)
            where = {}
        column = where.get(canonical_ref(card)) or where.get(str(card))
        if column and BY_COLUMN.get(stage_key(self.board, column)) is State.DELIVERED:
            return State.DELIVERED
        return State.CLOSED

    def asked_in(self, card: str) -> str:
        """The conversation `card`'s requester asked in — `""` when nobody's is known."""
        from openfactory.memory import store as loop_store
        from openfactory.memory.ledger import DELIVERY, fold
        from openfactory.product import events

        try:
            rows = loop_store.read(self.name)
            found = events.requester_conversation(self.project, card, rows=rows)
            if found:
                return found
            # A CARD COMING BACK: the delivery that waited on it was closed as cancelled when it
            # left, and that closed loop is still where its requester asked
            closed = [x for x in fold(rows) if x.kind == DELIVERY and card in events.issues_of(x)
                      and (x.context or {}).get("conversation")]
            return str(max(closed, key=lambda x: x.ts).context["conversation"]) if closed else ""
        except Exception:  # noqa: BLE001 — unknown is "", and the room is told for a card the
            log.info("could not read where #%s was asked for", card, exc_info=True)  # role opened
            return ""

    # ── the card ────────────────────────────────────────────────────────────────────────────────

    def column(self, card: str, key: str) -> str:
        from openfactory.contracts import JobState

        # THE ONE COLUMN A PERSON'S ENDING WRITES, through the port's one writer of a card's state.
        # No `reason`: the door's comment is its own effect, and `set_state` writing it too is the
        # double comment D6 ends (two rows write `reason`, the local board drops it).
        states = {"backlog": JobState.SKIPPED}
        if self.tracker.set_state(card, states[key]) is False:
            raise RuntimeError(f"the tracker did not move the card to {key}")
        return "moved"

    def close(self, card: str, *, delivered: bool, note: str) -> str:
        from openfactory.adapters.tracker.base import close_ticket

        close_ticket(self.tracker, card, note, delivered=delivered)
        return "closed as delivered" if delivered else "closed as not delivered"

    def remove(self, card: str, *, note: str, by: str, why: str) -> str:
        from openfactory.adapters.tracker.base import remove_ticket

        if remove_ticket(self.tracker, card, why, by=by, note=note):
            return "removed"
        return "closed as not delivered: this tracker cannot remove a card"

    def reopen(self, card: str) -> str:
        self.tracker.reopen_ticket(card)
        return "reopened"

    def comment(self, card: str, text: str) -> str:
        self.tracker.comment(card, text)
        return "said"

    # ── the promise, the conversation, the preview, the snapshot ───────────────────────────────

    def loops(self, card: str, action: str) -> str:
        from openfactory.lifecycle import loops

        if action != "cancel":
            return loops.restore(self.project, card)
        said, _still = loops.cancel(self.project, card)
        return said

    def deliver_what_remains(self) -> None:
        """A delivery whose remaining cards were all delivered before one of its cards was cancelled
        is due — announced through the delivery's own path, which reads the board and the ledger
        again under the telling lock (`events.deliver`). The hourly sweep asks it (`converge`),
        never a person's turn: a turn reaching the delivery path is a second way into it."""
        from openfactory.product import events

        try:
            delivered = events._delivered_now(self.project)
            if delivered:
                events.deliver(self.project, delivered=delivered)
        except Exception:  # noqa: BLE001 — the weekly catch-all announces what this missed
            log.exception("[%s] could not see whether what remains of a delivery is delivered",
                          self.name)

    def tell(self, card: str, *, notice: str, event_id: str, title: str, removed: bool,
             opened_by: str, conversation: str) -> str:
        """Tell the conversation the card was asked in. A card nobody asked for in a conversation —
        written on the board, with no delivery recording where — has no requester to tell, and the
        product's room is not told what an operator did on the board; one the product role opened
        is said to the room when nobody's conversation is known, as #384 said it."""
        from openfactory.product import events

        if not events._speaks(self.project):
            return "nobody to tell: the project has no product role"
        if not opened_by and not conversation:
            return "nobody to tell: nobody asked for it in a conversation"
        return events.card_moved(self.project, card=card, notice=notice, event_id=event_id,
                                 title=title, removed=removed, conversation=conversation)

    def preview(self, card: str, *, action: str, by: str) -> str:
        """Take down the preview of `card`'s unit — unless the unit also shows another card that is
        still open, whose requester may be trying it right now."""
        from openfactory import preview

        bare = card.rsplit("#", 1)[-1]
        if not preview.UNIT_RE.fullmatch(bare):
            return "none: the card is not a unit a preview is addressed by"
        unit = preview.unit_of_card(self.name, bare)
        found = preview.latest(self.name, unit)
        if found is None or not found.live:
            return "none running"
        others = [c for c in (found.cards or ()) if str(c).rsplit("#", 1)[-1] != bare]
        still = [c for c in others if self._open(str(c))]
        if still:
            return f"kept: it also shows #{str(still[0]).lstrip('#')}, which is still open"
        try:
            # THE ENGINE'S OWN MODULES, ASKED FOR INSIDE THE `try`: an install without the
            # `runtime` extra has no engine and no preview workflow to take down
            from openfactory.runtime.temporal import connection
            from openfactory.runtime.temporal import view as tv
        except ImportError:
            return "none: this install runs no engine"
        try:
            connection.address()
        except connection.EngineNotDeclared:
            return "none: this deployment runs no engine"
        from openfactory.product.door import _run

        async def _stop() -> bool:
            client = await connection.connect()
            return await tv.signal_preview(client, self.name, unit, action, by)

        return "stopping" if _run(_stop()) else "none running"

    def _open(self, card: str) -> bool:
        try:
            return (getattr(self.tracker.get_ticket(card), "state", "") or "open") == "open"
        except Exception:  # noqa: BLE001 — a card nobody can read keeps its preview: the safe side
            log.info("could not read #%s to tell whether a preview still shows it", card,
                     exc_info=True)
            return True

    def forget(self) -> str:
        from openfactory.product.board import forget_board

        forget_board(self.name)
        return "forgotten"

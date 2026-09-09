"""`board.local` — the columns of the board the platform itself holds (ADR-0049 D1, D5, D6).

IT WRAPS THE TRACKER, WHICH IS JIRA'S SHAPE AND FOR JIRA'S REASON. A Jira project's workflow status
IS its column, so `JiraProjectBoard` holds no client of its own and reads the tracker's map rather
than keeping a second copy that would drift the day somebody edited one of them. The same is true
here one turn tighter: the columns and the cards are rows in the same file, so a board with its own
connection would be a second reader of one truth. `BOARDS` receives no tracker instance, so the row
builds one — exactly as the Jira row does.

RANKABLE IS NOT IMPLEMENTED, and that is a statement rather than an omission. `Rankable` is a
second protocol precisely so a board without a writable backlog order says so by not claiming it;
`ProductModule.reorder` then answers in one sentence instead of an `AttributeError` in a chat. The
column a card sits in is the only order this file keeps today, and inventing a rank column that
nothing reads would be a promise with no mechanism behind it.
"""

from __future__ import annotations

import logging

from openfactory.adapters.board_db import connect, now_iso
from openfactory.adapters.tracker.base import column_key
from openfactory.contracts import JobState
from openfactory.contracts.refs import canonical_ref

log = logging.getLogger("openfactory.board.local")


class LocalBoard:
    """The six columns and where each card sits, for one project."""

    def __init__(self, tracker) -> None:
        #: The tracker this board is the face of. Held rather than re-derived, for the reason the
        #: Jira row states: a second source for one fact is a board moving cards by rules the
        #: tracker has abandoned.
        self._tracker = tracker

    @property
    def project(self) -> str:
        return getattr(self._tracker, "project", "")

    def _db(self):
        return getattr(self._tracker, "_db", None)

    # ---- reads ---------------------------------------------------------------------------

    def url(self) -> str:
        """The panel's board route. `""` rather than a guess is the port's rule, and there is
        nothing to guess at here — the route exists as soon as the panel is up."""
        from openfactory.adapters.tracker.local import panel_url

        return f"{panel_url()}/p/{self.project}/board" if self.project else ""

    def columns(self) -> dict[str, str] | None:
        """`{ref: column name}` — `None` could not read, `{}` read fine and nothing on it.

        THE DISTINCTION IS THE WHOLE POINT and the module docstring of the port says why: a board
        reported empty when it was unreadable is the factory announcing itself idle while a queue
        of work sits in front of it."""
        try:
            with connect(self._db()) as conn:
                rows = conn.execute(
                    "SELECT c.ref AS ref, col.name AS name FROM cards c "
                    "LEFT JOIN columns col ON col.project = c.project AND col.key = c.column_key "
                    "WHERE c.project = ? AND c.state = 'open'", (self.project,)).fetchall()
        except Exception:  # noqa: BLE001 — unreadable is not empty
            log.warning("could not read %s's board", self.project, exc_info=True)
            return None
        # A card whose column key names no column is left OUT rather than placed somewhere: the
        # caller asks this to find work, and a card reported in a column that does not exist is a
        # card the next `set_column` cannot move.
        return {str(r["ref"]): r["name"] for r in rows if r["name"]}

    def column_names(self) -> list[str] | None:
        """Which columns this board HAS, in board order — a different question from `columns()`.

        `[]` MEANS THE BOARD GENUINELY HAS NONE, which on this row means `project init` has not
        created them yet, and that is the one setup mistake whose symptom is otherwise total
        silence. `None` stays reserved for a read that did not happen."""
        try:
            with connect(self._db()) as conn:
                rows = conn.execute(
                    "SELECT name FROM columns WHERE project = ? ORDER BY position ASC",
                    (self.project,)).fetchall()
        except Exception:  # noqa: BLE001 — see `columns`
            log.warning("could not read %s's columns", self.project, exc_info=True)
            return None
        return [r["name"] for r in rows]

    def pickup_column(self) -> str:
        """What THIS board calls the column the poller picks up from.

        Read from the board's own rows rather than from a table here, so a person who renamed the
        column in `columns:` is answered with the name that is actually on their board. Falls back
        to the platform's own word, which is the honest guess — the caller reports which column it
        looked for, and the doctor turns exactly that into an actionable sentence."""
        from openfactory.adapters.board.columns import CANONICAL_COLUMNS

        try:
            with connect(self._db()) as conn:
                row = conn.execute("SELECT name FROM columns WHERE project = ? AND key = 'todo'",
                                   (self.project,)).fetchone()
        except Exception:  # noqa: BLE001 — never raise inside a poll tick
            log.warning("could not ask %s's board what it calls its pickup column — falling back "
                        "to the platform's own name for it", self.project, exc_info=True)
            row = None
        return (row["name"] if row else "") or CANONICAL_COLUMNS["todo"]

    def items_in_status(self, status: str) -> list[str]:
        """Refs sitting in one column, in board order — the pickup queue.

        BY NAME, because that is what the caller has: the poller resolves the column through
        `pickup_column()` or the deployment's `pickup_status`, both of which are names."""
        wanted = (status or "").strip()
        if not wanted:
            return []
        try:
            with connect(self._db()) as conn:
                rows = conn.execute(
                    "SELECT c.ref AS ref FROM cards c JOIN columns col "
                    "ON col.project = c.project AND col.key = c.column_key "
                    "WHERE c.project = ? AND c.state = 'open' AND col.name = ? "
                    "ORDER BY c.ref ASC", (self.project, wanted)).fetchall()
        except Exception:  # noqa: BLE001 — one bad read must not stop the tick
            log.warning("could not read %s's %r column", self.project, wanted, exc_info=True)
            return []
        return [str(r["ref"]) for r in rows]

    def poll_seconds(self) -> int:
        """Three seconds — `Watchable`, and this board is the reason that protocol exists.

        A person queues a card and watches it move: TO-DO, Doing, In review, Done. Every one of
        those moves is a row in a file on this machine, so re-reading them costs a SQLite query
        while somebody is looking at the page. The panel's own tick is three seconds and there is
        nothing to be gained by being slower than the surface asking."""
        return 3

    # ---- writes --------------------------------------------------------------------------

    def add_item(self, *, issue_url: str) -> None:
        """A no-op, IDEMPOTENT BY CONSTRUCTION. On a vendor's board a card and a board item are two
        objects and one has to be put on the other; here the card IS the row, so it is on the board
        the moment it exists. Declared rather than omitted because the port declares it and a
        caller must not have to know which rows need it."""

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        """Move a card to a column BY NAME. `False` when the board has no such column — never a
        raise, and a `False` always leaves a reason in the log behind it."""
        wanted = (name or "").strip()
        bare = canonical_ref(issue)
        if not wanted or not bare.isdigit():
            return False
        with connect(self._db(), write=True) as conn:
            col = conn.execute("SELECT key FROM columns WHERE project = ? AND name = ?",
                               (self.project, wanted)).fetchone()
            if col is None:
                log.warning("%s's board has no column named %r — the card stays where it is",
                            self.project, wanted)
                return False
            moved = conn.execute(
                "UPDATE cards SET column_key = ?, updated_at = ? WHERE project = ? AND ref = ?",
                (col["key"], now_iso(), self.project, int(bare))).rowcount
        if not moved:
            log.warning("%s has no card %s to move", self.project, bare)
        return bool(moved)

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        """Move a card to whichever column this board maps `state` to.

        THROUGH `column_key`, the platform's ONE resolution for every tracker and every board, so
        the `pr_open` that a person is blocking on lands in Needs Action here exactly as it does on
        a vendor's board (#166)."""
        key = column_key(state, needs_person=needs_person)
        if not key:
            return False
        with connect(self._db(), write=True) as conn:
            col = conn.execute("SELECT name FROM columns WHERE project = ? AND key = ?",
                               (self.project, key)).fetchone()
            if col is None:
                log.warning("%s's board declares no %r column — %s is not moved",
                            self.project, key, canonical_ref(issue))
                return False
            moved = conn.execute(
                "UPDATE cards SET column_key = ?, updated_at = ? WHERE project = ? AND ref = ?",
                (key, now_iso(), self.project, int(canonical_ref(issue) or 0))).rowcount
        return bool(moved)

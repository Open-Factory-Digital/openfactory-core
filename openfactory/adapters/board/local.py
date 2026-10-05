"""`board.local` — the columns of the board the platform itself holds (ADR-0049 D1, D5, D6).

IT WRAPS THE TRACKER, WHICH IS JIRA'S SHAPE AND FOR JIRA'S REASON. A Jira project's workflow status
IS its column, so `JiraProjectBoard` holds no client of its own and reads the tracker's map rather
than keeping a second copy that would drift the day somebody edited one of them. The same is true
here one turn tighter: the columns and the cards are rows in the same file, so a board with its own
connection would be a second reader of one truth. `BOARDS` receives no tracker instance, so the row
builds one — exactly as the Jira row does.

RANKABLE, BY A POSITION IN THE COLUMN (#512). This board kept no order of its own and said so by
not claiming `Rankable`, and the poller was served the queue by card number: a queue a person
confirmed as #9, #3 started on #3, under a reply saying "a fábrica começa pelo primeiro". Not
claiming a rank was honest about the order a person could WRITE; it said nothing about the order
the factory READ, which was the one that spent. Now each card has a `position` in its column
(`board_db`): a card that enters a column joins it at the bottom, whoever moved it there, and
`place_after` rewrites the column in the order a person gave — the confirmed queue (`promote`) or
the backlog order (`reorder`). `items_in_status`, the poller's read, serves that order and no
other.
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

    def __init__(self, tracker, *, queue: str = "") -> None:
        #: The tracker this board is the face of. Held rather than re-derived, for the reason the
        #: Jira row states: a second source for one fact is a board moving cards by rules the
        #: tracker has abandoned.
        self._tracker = tracker
        #: The queue's name when the deployment declared it with `pickup_status`, or `""` (#502).
        #: Folded over this board's own rows wherever they are read as names, so the column the
        #: poller pulls from is the one `pickup_column`, `stage_column` and `stage_key` answer with
        #: — see `board/factory.py::with_the_queue` for the promotion it kept from landing nowhere.
        self._queue = (queue or "").strip()

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
        of work sits in front of it.

        IN THE ORDER `items_in_status` SERVES (#512): each column's cards by `position`, then
        number. The panel draws a column in this order, and a queue drawn in another one — it was
        the tracker's most-recently-updated first — shows a person a first card the factory does
        not pick up."""
        try:
            with connect(self._db()) as conn:
                rows = conn.execute(
                    "SELECT c.ref AS ref, col.name AS name FROM cards c "
                    "LEFT JOIN columns col ON col.project = c.project AND col.key = c.column_key "
                    "WHERE c.project = ? AND c.state = 'open' "
                    "ORDER BY c.position ASC, c.ref ASC", (self.project,)).fetchall()
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

    #: A local deployment renames its columns in `columns:` like the hosted rows do, and
    #: `project init` writes the result onto the board (`board_setup/local.py`) — see
    #: `board/base.py::Staged` for why the row names the option rather than generic code guessing.
    stage_option = "columns"

    def stage_key(self, column: str) -> str:
        """Which neutral stage one of this board's columns is. See `Staged.stage_key`.

        OFF THE BOARD'S OWN ROWS, not off the registry, and that is this row's whole advantage:
        the key and the name sit in the same table, so a column renamed after `project init` is
        mapped without anybody writing a second copy of the map into the registry. `key_for` does
        the matching, once, for the same reason the hosted rows call it — the platform's own six
        names answer under whatever this board renamed.

        ONLY THE PLATFORM'S OWN KEYS ARE ANSWERED WITH. This table can hold a column a deployment
        added for itself — `('parking', 'Parking')` is in the panel's own guard — and its key is
        not a stage: `has_started` reads anything non-empty outside `backlog`/`todo` as *the
        factory has taken it up*, so answering `parking` would refuse an edit on a card nobody is
        working on. A column this platform does not map is `""`, which is what the gate is built
        to hear."""
        from openfactory.adapters.board.columns import key_for

        try:
            with connect(self._db()) as conn:
                rows = conn.execute("SELECT key, name FROM columns WHERE project = ?",
                                    (self.project,)).fetchall()
        except Exception:  # noqa: BLE001 — a board that cannot be read is not a traceback here
            log.warning("could not ask %s's board what its columns are called — reading them by "
                        "the platform's own names, which is right until somebody renames one",
                        self.project, exc_info=True)
            rows = []
        return key_for(column, renamed=self._renamed(rows))

    def stage_column(self, key: str) -> str:
        """What this board calls the stage `key`. See `Staged.stage_column`.

        Off the board's own rows, for the reason `stage_key` gives: a column renamed with
        `columns:` at `project init`, or on the board afterwards, is the name `set_column` matches,
        and the product role asking for the platform's word would find no such column (#496)."""
        from openfactory.adapters.board.columns import name_for

        try:
            with connect(self._db()) as conn:
                rows = conn.execute("SELECT key, name FROM columns WHERE project = ?",
                                    (self.project,)).fetchall()
        except Exception:  # noqa: BLE001 — a board that cannot be read is not a traceback here
            log.warning("could not ask %s's board what its columns are called — naming them by "
                        "the platform's own words, which is right until somebody renames one",
                        self.project, exc_info=True)
            rows = []
        return name_for(key, renamed=self._renamed(rows))

    def _renamed(self, rows) -> dict[str, str]:
        """This board's own names for the platform's keys, read off its rows — and the queue the
        deployment declared over them (#502), so both directions and the poller read one column."""
        from openfactory.adapters.board.columns import CANONICAL_COLUMNS

        named = {r["key"]: r["name"] for r in rows if r["name"] and r["key"] in CANONICAL_COLUMNS}
        if self._queue:
            named["todo"] = self._queue
        return named

    def pickup_column(self) -> str:
        """What THIS board calls the column the poller picks up from.

        Read from the board's own rows rather than from a table here, so a person who renamed the
        column in `columns:` is answered with the name that is actually on their board. Falls back
        to the platform's own word, which is the honest guess — the caller reports which column it
        looked for, and the doctor turns exactly that into an actionable sentence."""
        from openfactory.adapters.board.columns import CANONICAL_COLUMNS

        if self._queue:
            # THE QUEUE THE DEPLOYMENT NAMED (#502) — what the poller pulls from either way
            return self._queue
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
        `pickup_column()` or the deployment's `pickup_status`, both of which are names.

        IN THE ORDER A PERSON SET, NEVER BY NUMBER (#512): each card's `position` in its column —
        where it joined, or where `place_after` put it. The number only breaks a tie, and only
        cards already on a board when the position was added can tie."""
        wanted = (status or "").strip()
        if not wanted:
            return []
        try:
            with connect(self._db()) as conn:
                rows = conn.execute(
                    "SELECT c.ref AS ref FROM cards c JOIN columns col "
                    "ON col.project = c.project AND col.key = c.column_key "
                    "WHERE c.project = ? AND c.state = 'open' AND col.name = ? "
                    "ORDER BY c.position ASC, c.ref ASC", (self.project, wanted)).fetchall()
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
        raise, and a `False` always leaves a reason in the log behind it.

        BY THE TRACKER'S RULE, NOT A SECOND ONE (#500): `tracker/local.py::move_card`, which the
        tracker's `set_state` writes through too. So a card closed as delivered — which the panel
        draws in Done — that a person drags out of Done is open work again in the column they put
        it in, as it is on Jira and Azure DevOps, where the status is the state. A card dragged
        INTO Done stays as open as it was: recording a delivery is the close's, not the drag's."""
        from openfactory.adapters.tracker.local import move_card

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
            moved = move_card(conn, self.project, int(bare), col["key"], closes_at_done=False)
        if not moved:
            log.warning("%s has no card %s to move", self.project, bare)
        return bool(moved)

    def place_after(self, *, issue: str, issue_url: str, after: str | None, column: str) -> bool:
        """Put `issue` right after `after` in `column` — the top when `after` is None (see
        `Rankable`, #512).

        THE WHOLE COLUMN IS NUMBERED AGAIN, in one write transaction: the column is read in its
        order, the card is taken out and put back after its anchor, and every open card in it is
        given its place, 1 to n. A midpoint between two neighbours — what Azure Boards writes,
        because a hosted call per card is what it costs there — halves a gap every time a person
        puts one card first, and a column re-arranged often enough runs out of halves. Here the
        column is a handful of rows in a file on this machine.

        THE CARD AND ITS ANCHOR MUST BE IN `column`, by the name this board gives it, as for
        `set_column`. A place is an order among the cards in one column; a card in another one has
        no place here to be given, and `False` says so in the log rather than writing a position
        nobody reads."""
        wanted = (column or "").strip()
        bare = canonical_ref(issue)
        anchor = canonical_ref(after) if after else ""
        if not wanted or not bare.isdigit() or (after and not anchor.isdigit()):
            log.warning("%s cannot place %r after %r in %r — not a card of this board",
                        self.project, issue, after, column)
            return False
        with connect(self._db(), write=True) as conn:
            col = conn.execute("SELECT key FROM columns WHERE project = ? AND name = ?",
                               (self.project, wanted)).fetchone()
            if col is None:
                log.warning("%s's board has no column named %r — nothing was placed",
                            self.project, wanted)
                return False
            order = [int(r["ref"]) for r in conn.execute(
                "SELECT ref FROM cards WHERE project = ? AND state = 'open' AND column_key = ? "
                "ORDER BY position ASC, ref ASC", (self.project, col["key"]))]
            card = int(bare)
            rest = [ref for ref in order if ref != card]
            if card not in order or (anchor and int(anchor) not in rest):
                log.warning("%s cannot place %s after %r: %s is not in %r", self.project, bare,
                            after, bare if card not in order else anchor, wanted)
                return False
            rest.insert(rest.index(int(anchor)) + 1 if anchor else 0, card)
            conn.executemany("UPDATE cards SET position = ? WHERE project = ? AND ref = ?",
                             [(place, self.project, ref) for place, ref in enumerate(rest, 1)])
        return True

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

"""`tracker.local` — the board the platform itself holds, in `board.db` (ADR-0049 D1, D5, D7).

THE ROW A DEPLOYMENT WHOSE WORLD IS ITS OWN MACHINE HAS ALWAYS NEEDED. Every other row on this
axis reaches a service somebody rents; this one reaches a file beside the registry, so a person
with a repository and a coding agent can put a card in and get a pull request out without opening
an account anywhere.

IT IS NOT A TEST DOUBLE. `openfactory/testing/local_flow.py` holds an in-memory tracker that drives
the real poller offline, and it is a fixture: it lives in `testing/`, it is built by hand, and
nothing persists. This is a registry row — built by kind through `build_tracker`, conformant, and
durable across the three processes that share the file.

WHAT IT DOES NOT INVENT. A budget it cannot report, a person it was not told about, an assignee
nobody set: each answers the port's own word for *I cannot say* rather than a plausible value. The
one place it answers where every hosted vendor cannot is `identity_of` (D7) — its namespace IS the
platform's, so the id it is handed is the id it returns.
"""

from __future__ import annotations

import logging

from openfactory.adapters.board_db import connect, next_ref, now_iso
from openfactory.adapters.tracker.base import (
    NOT_REPORTED,
    STATE_KEYS,
    TicketComment,
    TicketSummary,
    column_key,
    list_state,
)
from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts import JobState, Ticket
from openfactory.contracts.refs import canonical_ref

log = logging.getLogger("openfactory.tracker.local")

#: What the factory signs its own comments with. THE SPELLING IS GITHUB'S, deliberately: it is the
#: convention a reader already knows for "the platform wrote this, not a person", and the ADR-0048
#: sweep's whole job is telling those two apart. Written by the row on `comment()` rather than read
#: from `bot_identity().login`, because setting `OPENFACTORY_BOT_LOGIN` switches on three hosted-row
#: paths in the same process and this row must not need it.
BOT_AUTHOR = "openfactory[bot]"

#: Where a card's page is, when the deployment says where the panel lives. The default is the
#: panel's own compose port, which is the address a person on one machine actually opens.
PANEL_URL_ENV = "OPENFACTORY_PANEL_URL"
DEFAULT_PANEL_URL = "http://localhost:8787"


def panel_url() -> str:
    """The panel's base address, without a trailing slash.

    A ROW ASKS FOR THIS RATHER THAN COMPOSING A VENDOR'S URL, which is the property
    `test_the_board_says_where_it_lives.py` holds for the whole package: `ticket_url` is a port
    question and this row's answer is a route on the surface the person is already looking at."""
    import os

    return (os.environ.get(PANEL_URL_ENV, "").strip() or DEFAULT_PANEL_URL).rstrip("/")


class LocalTracker:
    """Cards, comments and labels in `board.db`, for one project.

    `token` and `token_provider` are accepted and IGNORED, which is the port's shape rather than
    laziness: `activities.py` hands any tracker without a credential of its own the GitHub App
    minter, and a row that refused the argument would fail on a deployment that has one."""

    def __init__(self, project: str, *, db_path=None, token=None, token_provider=None) -> None:
        self.project = (project or "").strip()
        self._db = db_path
        #: Kept so `build_tracker`'s contract holds; see the class docstring.
        self.token = token

    # ---- reads ---------------------------------------------------------------------------

    def get_ticket(self, ref: str) -> Ticket:
        """The parsed card. Raises when there is no such card — the port's own shape for a read
        that could not happen, and what `conformance` probes with a ref that cannot exist."""
        bare = _number(ref)
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT * FROM cards WHERE project = ? AND ref = ?", (self.project, bare)
            ).fetchone()
            if row is None:
                raise KeyError(f"no card {canonical_ref(ref)} on {self.project!r}'s board")
            labels = [r["label"] for r in conn.execute(
                "SELECT label FROM labels WHERE project = ? AND ref = ? ORDER BY label",
                (self.project, bare))]

        # `#N` HERE AND BARE `N` ON THE SUMMARY, because that is what the port says
        # (`contracts/ticket.py` vs `tracker/base.py`) and both spellings reach `canonical_ref`
        # before anything compares them.
        ticket = parse_ticket_body(id=f"#{bare}", title=row["title"], body=row["body"] or "",
                                   repo=self.project)
        ticket.labels = [lbl.lower() for lbl in labels]
        ticket.author = row["author"] or None
        ticket.state = row["state"] or "open"
        # The card's own record wins over anything the body's prose says: the requester is written
        # when the card is opened and a person editing the description must not silently reassign
        # who the factory asks (ADR-0048 §5).
        if row["requester"]:
            ticket.requester = row["requester"]
            ticket.requester_forge = row["requester"]
        return ticket

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        """Oldest-first; `[]` for a card with none; `None` when the read could not happen.

        THE THREE ANSWERS ARE THE POINT AND THE PORT SAYS SO. The consumer is a language model, and
        an un-commented card and an unreadable thread produce the same silence in a prompt — it
        concludes nobody has looked and repeats an answer that already failed. So a card this file
        does not hold answers `None`, never `[]`."""
        bare = _number(ref)
        try:
            with connect(self._db) as conn:
                if conn.execute("SELECT 1 FROM cards WHERE project = ? AND ref = ?",
                                (self.project, bare)).fetchone() is None:
                    return None
                rows = conn.execute(
                    "SELECT author, body, created_at FROM comments "
                    "WHERE project = ? AND ref = ? ORDER BY seq ASC", (self.project, bare)
                ).fetchall()
        except Exception:  # noqa: BLE001 — a file that cannot be opened is "could not look"
            log.warning("could not read the comments on %s — answering 'could not look' rather "
                        "than 'there are none'", canonical_ref(ref), exc_info=True)
            return None
        out = [TicketComment(author=r["author"], body=r["body"], created_at=r["created_at"])
               for r in rows]
        # AFTER the read, and the most recent ones: `limit` on this port means "the tail I can
        # afford to put in a prompt", and the oldest-first order is preserved within it.
        return out[-limit:] if limit and limit > 0 else out

    def list_tickets(self, *, state: str = "all", updated_since: str = "",
                     limit: int = 0) -> list[TicketSummary] | None:
        """Newest-updated first. `state` through the port's own vocabulary, which RAISES on a
        misspelling — that failure is the caller's, and the two quiet alternatives both hide half
        a board from whoever asked."""
        want = list_state(state)
        try:
            with connect(self._db) as conn:
                rows = conn.execute(
                    "SELECT ref, title, body, state, closed_reason, updated_at FROM cards "
                    "WHERE project = ? ORDER BY updated_at DESC", (self.project,)).fetchall()
                held = {r["ref"]: [] for r in rows}
                for lab in conn.execute(
                        "SELECT ref, label FROM labels WHERE project = ? ORDER BY label",
                        (self.project,)):
                    held.setdefault(lab["ref"], []).append(lab["label"])
        except Exception:  # noqa: BLE001 — see `comments`
            log.warning("could not read %s's board", self.project, exc_info=True)
            return None

        kept = [r for r in rows
                if (want == "all" or r["state"] == want)
                and (not updated_since or (r["updated_at"] or "") >= updated_since)]
        # THE FILTER FIRST, THEN THE LIMIT. A limit applied to the read would answer "the newest
        # N cards, of which these few are open", which is a different question from the one asked.
        if limit and limit > 0:
            kept = kept[:limit]
        return [TicketSummary(ref=str(r["ref"]), title=r["title"], body=r["body"] or "",
                              state=r["state"], state_reason=r["closed_reason"] or "",
                              labels=[lbl.lower() for lbl in held.get(r["ref"], [])],
                              updated_at=r["updated_at"] or "")
                for r in kept]

    def find_ticket(self, *, title: str) -> str | None:
        """The newest card with exactly this title, or `None`. Used for split idempotency, where
        a false match would silently reuse somebody else's card."""
        wanted = (title or "").strip()
        if not wanted:
            return None
        with connect(self._db) as conn:
            row = conn.execute(
                "SELECT ref FROM cards WHERE project = ? AND title = ? "
                "ORDER BY ref DESC LIMIT 1", (self.project, wanted)).fetchone()
        return f"#{row['ref']}" if row else None

    def ticket_url(self, ref: str) -> str:
        """The panel's own card route — this deployment's board is a page on the panel."""
        return f"{panel_url()}/p/{self.project}/card/{_number(ref)}"

    def budget(self) -> object:
        """`NOT_REPORTED` — there is no quota on a local file, and the port has a word for a
        provider that has nothing to report rather than a number it made up."""
        return NOT_REPORTED

    def person(self, ref: str) -> dict:
        """A registered panel person, or `{}`. Never raises — its caller is composing a message
        somebody is waiting for."""
        who = (ref or "").strip()
        if not who:
            return {}
        try:
            from openfactory.identity.people import PeopleStore

            for person in PeopleStore().people():
                if getattr(person, "id", "") == who:
                    return {"id": person.id, "name": getattr(person, "display", "") or "",
                            "email": getattr(person, "email", "") or ""}
        except Exception:  # noqa: BLE001 — "I cannot say" beats a wrong name
            log.info("could not read the registered people for %r", who, exc_info=True)
        return {}

    def assignees(self, ref: str) -> list[str]:
        """`[]` — one machine has one person and nobody is assigned to anybody. The method exists
        because the port declares it and a caller must not have to ask which rows have it."""
        return []

    def children_of(self, parent_ref: str) -> list[str]:
        with connect(self._db) as conn:
            rows = conn.execute(
                "SELECT child_ref FROM links WHERE project = ? AND parent_ref = ? "
                "ORDER BY child_ref", (self.project, _number(parent_ref))).fetchall()
        return [f"#{r['child_ref']}" for r in rows]

    # ---- identity, where this row can answer and the hosted ones cannot (D7) ---------------

    def identity_of(self, subject_id: str) -> str:
        """The id itself — THIS ROW'S NAMESPACE IS THE PLATFORM'S.

        Every hosted vendor answers `""` here because a GitHub login is not a platform id and no
        row can invent the bridge. There is no bridge to invent on this one: the person who filed
        the card through the panel or the shell is written on it in the platform's own spelling,
        and that is the spelling a comment's author carries back. So the factory ASKS on a
        deployment where nobody is registered — which, on one machine, is every deployment — and
        `""` still means nobody (`identity/base.py`: the anonymous subject's id is `""`)."""
        return (subject_id or "").strip()

    def mention(self, login: str) -> str:
        """The plain id. There is no `@` this board resolves, and a mention nobody is notified by
        is decoration (ADR-0048 §5) — the panel renders the name beside the comment."""
        return (login or "").strip()

    # ---- writes --------------------------------------------------------------------------

    def create_ticket(self, *, title: str, body: str, author: str = "",
                      requester: str = "", column: str = "") -> str:
        """Open a card and return `#N`. The number is per project and taken under the write lock.

        `author`, `requester` and `column` are this row's own arguments and are absent from the
        port on purpose: every caller of `create_ticket` passes exactly title and body, and a
        keyword with a default is how a row offers more without making the port carry it."""
        when = now_iso()
        key = (column or "").strip() or "backlog"
        with connect(self._db, write=True) as conn:
            ref = next_ref(conn, self.project)
            conn.execute(
                "INSERT INTO cards(project, ref, title, body, state, column_key, author, "
                "requester, created_at, updated_at) VALUES (?,?,?,?,'open',?,?,?,?,?)",
                (self.project, ref, (title or "").strip(), body or "", key,
                 (author or "").strip(), (requester or "").strip(), when, when))
        return f"#{ref}"

    def update_body(self, ref: str, body: str) -> None:
        """Rewrite the description. A SEPARATE METHOD from `comment` because the port made it one:
        a caller here is overwriting what somebody else wrote, and that has to be visible at the
        call site rather than hidden behind an edit."""
        self._touch(ref, "body", body or "")

    def comment(self, ref: str, body: str) -> None:
        """Append. The row signs it, so a reader — and the ADR-0048 sweep — can tell the platform's
        own note from a person's answer without a fourth field on the comment."""
        bare = _number(ref)
        when = now_iso()
        with connect(self._db, write=True) as conn:
            row = conn.execute("SELECT MAX(seq) AS top FROM comments WHERE project = ? AND ref = ?",
                               (self.project, bare)).fetchone()
            conn.execute(
                "INSERT INTO comments(project, ref, seq, author, body, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (self.project, bare, int(row["top"] or 0) + 1, BOT_AUTHOR, body or "", when))
            conn.execute("UPDATE cards SET updated_at = ? WHERE project = ? AND ref = ?",
                         (when, self.project, bare))

    def say(self, ref: str, body: str, *, author: str) -> None:
        """A PERSON's comment, in their own name — what the panel and `openfactory act` write.

        Separate from `comment()` rather than a parameter on it, because the difference is the one
        the answer sweep turns on: an answer counts only when its author is the requester and is
        not the platform's own posting identity, and a single method with an optional author is a
        method somebody will call without one."""
        bare = _number(ref)
        when = now_iso()
        with connect(self._db, write=True) as conn:
            row = conn.execute("SELECT MAX(seq) AS top FROM comments WHERE project = ? AND ref = ?",
                               (self.project, bare)).fetchone()
            conn.execute(
                "INSERT INTO comments(project, ref, seq, author, body, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (self.project, bare, int(row["top"] or 0) + 1, (author or "").strip(),
                 body or "", when))
            conn.execute("UPDATE cards SET updated_at = ? WHERE project = ? AND ref = ?",
                         (when, self.project, bare))

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> bool | None:
        """Move the card to the column this state belongs in. `False` when this board declares no
        such column — never a raise, which is what every other row on this axis promises and what
        the gather's park path reads to decide whether to say the park did not land."""
        key = column_key(state, needs_person=needs_person)
        if not key:
            return False
        bare = _number(ref)
        when = now_iso()
        with connect(self._db, write=True) as conn:
            if conn.execute("SELECT 1 FROM columns WHERE project = ? AND key = ?",
                            (self.project, key)).fetchone() is None:
                return False
            changed = conn.execute(
                "UPDATE cards SET column_key = ?, updated_at = ? WHERE project = ? AND ref = ?",
                (key, when, self.project, bare)).rowcount
        return bool(changed)

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        """A no-op with a record in the log rather than a silent one: a caller that assigned
        somebody and saw nothing happen should be able to find out why."""
        if logins:
            log.info("this board has no assignees; %s stays unassigned", canonical_ref(ref))

    def add_label(self, ref: str, label: str) -> None:
        name = (label or "").strip()
        if not name:
            return
        with connect(self._db, write=True) as conn:
            conn.execute("INSERT OR IGNORE INTO labels(project, ref, label) VALUES (?,?,?)",
                         (self.project, _number(ref), name))
            conn.execute("UPDATE cards SET updated_at = ? WHERE project = ? AND ref = ?",
                         (now_iso(), self.project, _number(ref)))

    def remove_label(self, ref: str, label: str) -> None:
        with connect(self._db, write=True) as conn:
            conn.execute("DELETE FROM labels WHERE project = ? AND ref = ? AND label = ?",
                         (self.project, _number(ref), (label or "").strip()))

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        """CLOSED IS NOT DELIVERED. `delivered=False` records a duplicate or an abandoned plan, and
        the word is what `triage.Ticket.delivered` reads — eleven cards closed as duplicates once
        came back from a tracker looking like completed work."""
        when = now_iso()
        with connect(self._db, write=True) as conn:
            conn.execute(
                "UPDATE cards SET state = 'closed', closed_reason = ?, column_key = ?, "
                "updated_at = ? WHERE project = ? AND ref = ?",
                ("completed" if delivered else "not_planned",
                 STATE_KEYS.get(JobState.DONE, "done") if delivered else "backlog",
                 when, self.project, _number(ref)))
            if reason:
                conn.execute(
                    "INSERT INTO comments(project, ref, seq, author, body, created_at) "
                    "SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ? FROM comments "
                    "WHERE project = ? AND ref = ?",
                    (self.project, _number(ref), BOT_AUTHOR, reason, when,
                     self.project, _number(ref)))

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        with connect(self._db, write=True) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO links(project, parent_ref, child_ref) VALUES (?,?,?)",
                (self.project, _number(parent_ref), _number(child_ref)))

    # ---- internals -----------------------------------------------------------------------

    def _touch(self, ref: str, field: str, value: str) -> None:
        """One column and `updated_at`, together. `field` is never a caller's string — the two
        call sites name it as a literal, and an interpolated column name that came from outside
        would be this file's own injection."""
        assert field in {"body", "title"}, field
        with connect(self._db, write=True) as conn:
            conn.execute(
                f"UPDATE cards SET {field} = ?, updated_at = ? WHERE project = ? AND ref = ?",
                (value, now_iso(), self.project, _number(ref)))


def _number(ref: object) -> int:
    """The card's number from either spelling. `0` for anything that is not one — which matches
    no row, so a malformed ref reads as *no such card* instead of raising inside a poll tick."""
    bare = canonical_ref(ref)
    return int(bare) if bare.isdigit() else 0

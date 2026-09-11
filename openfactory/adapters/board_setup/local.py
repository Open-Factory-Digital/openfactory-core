"""Creating the board the platform itself holds — six rows in `board.db` (ADR-0049 D1, D5).

WHAT "CREATING A BOARD" MEANS HERE. On a vendor's board it is an API call that mints an object and
hands back a coordinate; here it is the six columns appearing in this project's rows, in board
order, with the platform's own names. There is no second object and therefore no coordinate: the
port's `create` answers `""` for the first half of its pair, and `init` writes nothing into the
registry, because there is nothing to point at.

IDEMPOTENT, AND SAYS SO THROUGH `attached`. `openfactory project init` promises whoever re-runs it
that the board step can be repeated, and this row keeps that promise twice over: it reports the
columns it already has, and the write itself only fills in what is missing.
"""

from __future__ import annotations

from openfactory.adapters.board.columns import BOARD_ORDER, CANONICAL_COLUMNS
from openfactory.adapters.board_db import connect


class LocalBoardSetup:
    """The six columns, for one project, in `board.db`."""

    def attached(self, project) -> str:
        """A sentence naming the columns this project already has, or `""`."""
        names = self._existing(project)
        return f"{len(names)} columns ({', '.join(names)})" if names else ""

    def create(self, *, project, owner: str, title: str, token: str | None) -> tuple[str, str]:
        """Write the six columns; answer `("", <the board's page>)`.

        `owner` and `token` ARE ACCEPTED AND UNUSED, which is the port's shape rather than an
        oversight: the caller resolves a credential on the tracker axis for every row and a row
        that refused the argument would fail on a deployment that has one. There is nobody to
        authenticate to — the file is this deployment's own."""
        from openfactory.adapters.tracker.local import panel_url

        name = _name_of(project)
        with connect(_db_of(project), write=True) as conn:
            for position, key in enumerate(BOARD_ORDER):
                # INSERT OR IGNORE, so a re-run adds what is missing and RENAMES NOTHING: a person
                # who renamed a column is entitled to keep the name (C-14), and an idempotent
                # command that quietly restored the platform's word would undo their edit.
                conn.execute(
                    "INSERT OR IGNORE INTO columns(project, key, name, position) VALUES (?,?,?,?)",
                    (name, key, CANONICAL_COLUMNS[key], position))
        return "", f"{panel_url()}/p/{name}/board"

    def _existing(self, project) -> list[str]:
        with connect(_db_of(project)) as conn:
            rows = conn.execute("SELECT name FROM columns WHERE project = ? ORDER BY position ASC",
                                (_name_of(project),)).fetchall()
        return [r["name"] for r in rows]


def _name_of(project) -> str:
    """The project's own name — the key every row in this file is written under."""
    return (getattr(project, "name", "") or "").strip()


def _db_of(project):
    """The project's own `board_db` option, when it names one; otherwise the deployment's."""
    options = (getattr(getattr(project, "tracker", None), "options", None) or {})
    return options.get("board_db") or None

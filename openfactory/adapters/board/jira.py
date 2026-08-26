"""A Jira project AS A BOARD — the pickup queue for a deployment with no GitHub Projects.

WHY THIS HAD TO EXIST BEFORE ANY JIRA CLIENT COULD BE ONBOARDED. `JiraTracker` has covered tickets
for months — create, read, comment, transition — and is unit-tested and, since 2026-08-05, proven
live against a real Jira. None of that gets a ticket PICKED UP. The poller asks
`build_board(project)` for `items_in_status(<pickup column>)`, and `BOARD_KINDS` listed exactly one
provider, so a Jira project resolved to `None` — which `scan_todo` reports as *"no board configured
— the pickup queue is empty by configuration, not because nothing is waiting"*.

Truthful, and total: the factory would sit idle beside a full Jira backlog, saying so once per tick
in a log nobody reads. The client's first day looks like a factory that does not work.

THE COLUMN IS A STATUS, and that is the whole design. GitHub Projects keeps a separate Status field
per card; Jira's workflow status IS the column, which is why this class needs no field ids, no node
ids and no board id — a `Kanban` board in Jira is a saved view over a JQL query, and the query is
what the poller actually wants. So `items_in_status("TO-DO")` is one JQL call, and moving a card is
a workflow transition, which `JiraTracker.set_state` already knows how to do safely (it refuses to
invent a transition the project's workflow does not offer).

`ORDER BY Rank` is not decoration: the protocol says board order, and a Jira backlog IS ranked by
the humans who groomed it. Falling back to key order would hand the factory whatever was created
first, which is the opposite of what a groomed backlog means.
"""

from __future__ import annotations

import logging
import urllib.parse

from openfactory.contracts import JobState

log = logging.getLogger("openfactory.board.jira")

#: One page is plenty for a pickup queue and bounds a runaway read. A backlog longer than this is
#: reported rather than silently truncated — the same rule the GitHub board follows at 2000 cards.
_MAX_ISSUES = 200

#: `/rest/api/3/search` IS GONE — Atlassian removed it, and a live call answers 410 *"A API
#: solicitada foi removida. Migre para a API /rest/api/3/search/jql"*. Found the first time this
#: board was pointed at a real Jira (2026-08-05); no fake would ever have said it, which is the
#: whole argument for `validate-in-the-cloud-not-just-local`.
#:
#: The replacement is token-paginated and carries NO `total`, so completeness is read from
#: `isLast` rather than from a count.
_SEARCH_PATH = "search/jql"


class JiraProjectBoard:
    """Satisfies `BoardAdapter` over a Jira project's workflow statuses."""

    def __init__(self, tracker) -> None:
        #: THE TRACKER, not a second REST client. Auth, the site URL, the ADF encoding, the
        #: status map and the "never invent a transition" rule all live there already, and a
        #: board that re-implemented them would drift from the tracker the day one of them
        #: changed — with the board silently moving cards by rules the tracker had abandoned.
        self._tracker = tracker

    @property
    def project_key(self) -> str:
        return getattr(self._tracker, "project_key", "")

    def url(self) -> str:
        """`<site>/browse/<KEY>` — see `BoardAdapter.url`.

        THE PROJECT'S OWN PAGE, NOT A BOARD ID. A Jira project may have several boards and this
        adapter is not given one: it works from the project key and the status map. `/browse/<KEY>`
        is the page that always exists and lists this project's work — asking a person for one more
        click beats inventing a board id that 404s.

        THE SAME SHAPE `JiraTracker.ticket_url` USES, from the same `site`, so a deployment that
        moves its Jira instance moves both together.
        """
        site = getattr(self._tracker, "site", "")
        key = self.project_key
        return f"{site}/browse/{key}" if site and key else ""

    def pickup_column(self) -> str:
        """The status this Jira project calls TO-DO. See `BoardAdapter.pickup_column`.

        FROM THE TRACKER'S `status_map`, not from a table here, for the same reason this class
        holds no REST client of its own: the map is the tracker's and a second copy would drift
        the day somebody edited one of them — with the board then reading a queue by rules the
        tracker had abandoned.

        Jira is the provider with NO safe default, and that is a property of Jira rather than an
        omission: every project defines its own workflow, so there is no status this adapter could
        name without inventing one (ADR-0022 §4 — transitions are configured, never invented).
        Falling back to the platform's `TO-DO` is therefore a GUESS, and it is returned so the
        caller can say which column it looked for — the doctor turns exactly that into *"the board
        has no 'TO-DO' column (found: …)"*, which is the actionable form of not knowing."""
        status_map = getattr(self._tracker, "status_map", None) or {}
        return str(status_map.get("todo") or "") or "TO-DO"

    def _search(self, jql: str) -> list[dict] | None:
        """Issues matching `jql`, or None when the search could not be made at all.

        `None` versus `[]` is the protocol's hardest rule and this is where it is decided: an
        unreachable Jira and an empty backlog are the same shape to a caller that collapses
        them, and the collapse reads as "nothing is queued"."""
        query = urllib.parse.urlencode({
            "jql": jql, "maxResults": _MAX_ISSUES, "fields": "status",
        })
        try:
            data = self._tracker._call("GET", f"{_SEARCH_PATH}?{query}")
        except Exception as exc:  # noqa: BLE001 — unreadable is never "empty"
            log.warning("could not search %s (%s) — the caller must treat this as UNREADABLE, "
                        "never as an empty board", self.project_key, str(exc)[:200])
            return None
        issues = data.get("issues")
        if issues is None:
            log.warning("jira search for %s returned no `issues` field — treating as unreadable",
                        self.project_key)
            return None
        # NO SILENT TRUNCATION. The new endpoint reports completeness as `isLast`; a missing
        # `isLast` is read as "there may be more" rather than as "that was everything", because
        # a queue quietly missing its tail looks exactly like a queue that is done.
        if not data.get("isLast", False):
            log.warning("%s has more issues matching %r than this read returned (stopped at %s) — "
                        "the queue may be missing items", self.project_key, jql, _MAX_ISSUES)
        return issues

    @staticmethod
    def _status_of(issue: dict) -> str:
        return str(((issue.get("fields") or {}).get("status") or {}).get("name") or "")

    def columns(self) -> dict[str, str] | None:
        issues = self._search(f'project = "{self.project_key}" ORDER BY Rank ASC')
        if issues is None:
            return None
        return {str(i.get("key")): self._status_of(i) for i in issues if i.get("key")}

    def column_names(self) -> list[str] | None:
        """The project's workflow statuses, which ARE its columns.

        Asked of the project rather than derived from `columns()`, deliberately: a status nothing
        currently sits in still exists, and `openfactory doctor` asking "is there a "
                                                                        "TO-DO?" must not be
        answered "no" by an empty backlog."""
        try:
            types = self._tracker._call("GET", f"project/{self.project_key}/statuses")
        except Exception as exc:  # noqa: BLE001 — unreadable is NOT "has no columns"
            log.warning("could not read the statuses of %s (%s) — the caller must treat this as "
                        "UNREADABLE, never as a project without columns",
                        self.project_key, str(exc)[:200])
            return None
        seen: list[str] = []
        for issue_type in types if isinstance(types, list) else []:
            for status in issue_type.get("statuses") or []:
                name = str(status.get("name") or "")
                if name and name not in seen:
                    seen.append(name)
        return seen

    def items_in_status(self, status: str) -> list[str]:
        """The pickup queue, in the backlog's OWN rank order.

        `[]` on an unreadable project rather than a raise: this is the poller's hottest read, and
        `scan_todo` already treats an empty queue as "nothing to do this tick". The warning in
        `_search` is what says which of the two happened."""
        safe = str(status).replace('"', '\\"')
        issues = self._search(
            f'project = "{self.project_key}" AND status = "{safe}" ORDER BY Rank ASC')
        return [str(i.get("key")) for i in (issues or []) if i.get("key")]

    def add_item(self, *, issue_url: str) -> None:
        """A Jira issue is ON its project's board by existing — there is nothing to add.

        Kept as an explicit no-op rather than omitted: `GitHubProjectBoard.add_item` exists
        because a Projects v2 board is a SEPARATE object a card must be attached to, and a caller
        should not have to know which of the two shapes it is holding."""

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        """Transition `issue` to the status called `name`.

        Goes through the tracker's own transition logic, so a workflow that does not offer the
        move is refused rather than forced — and refused the same way for the board and for the
        state machine, which is the point of not writing a second REST client here."""
        target = str(name or "")
        if not target:
            return False
        transitions = self._transitions(issue)
        if transitions is None:
            return False
        match = next((t for t in transitions
                      if str((t.get("to") or {}).get("name", "")).lower() == target.lower()
                      or str(t.get("name", "")).lower() == target.lower()), None)
        if match is None:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s issue=%s -> %r: the project's workflow "
                      "offers no "
                      "such transition from where the issue is now", self.project_key, issue,
                      target)
            return False
        try:
            self._tracker._call("POST", f"issue/{issue}/transitions",
                                {"transition": {"id": match["id"]}})
        except Exception as exc:  # noqa: BLE001 — a False must always leave a why behind it
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s issue=%s -> %r: %s",
                      self.project_key, issue, target, str(exc)[:200])
            return False
        return True

    def _transitions(self, issue: str) -> list[dict] | None:
        try:
            return self._tracker._call("GET", f"issue/{issue}/transitions").get("transitions") or []
        except Exception as exc:  # noqa: BLE001
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s issue=%s: could not read its transitions "
                      "(%s)",
                      self.project_key, issue, str(exc)[:200])
            return None

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        """Move to whichever status THIS deployment mapped `state` to.

        The map is the tracker's (`status_map` in the project's tracker options), so the board and
        the state machine cannot disagree about what "done" is called here. Unmapped is False with
        a reason, never a guess: every Jira project has its own workflow (C-14 — the client's
        vocabulary belongs to the client)."""
        from openfactory.adapters.tracker.base import STATE_KEYS

        key = STATE_KEYS.get(state)
        target = (getattr(self._tracker, "status_map", None) or {}).get(key or "", "")
        if not target:
            log.warning("no jira status mapped for %s (status_map key %r) on %s — the card stays "
                        "where it is; add the mapping in the project's tracker options",
                        state, key, self.project_key)
            return False
        return self.set_column(issue=issue, issue_url=issue_url, name=target)

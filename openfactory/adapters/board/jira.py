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

import json
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

    #: THE MAP IS `status_map`, NOT `columns` (#231, see `board/base.py::Staged`). The stage gate
    #: used to resolve a column's key out of the `columns` option in generic code, which a Jira
    #: deployment has no reason to set and which this row would ignore if it did — so every card
    #: on every Jira board sat in "a column this platform does not map" and could be neither
    #: edited nor closed. Naming the option here is what lets that refusal, when it is real, point
    #: at something a person can actually edit.
    stage_option = "status_map"

    def stage_key(self, column: str) -> str:
        """Which neutral stage one of this project's statuses is. See `Staged.stage_key`.

        FROM THE TRACKER'S `status_map`, for the reason `pickup_column` gives: the map is the
        tracker's, and a second copy would drift the day somebody edited one of them.

        THE PLATFORM'S OWN NAMES STILL ANSWER UNDER IT (`key_for` merges the deployment's map over
        the canonical one), which is what a Jira project that declared only half its workflow
        needs: `In review` is read as `in_review` rather than as a status nobody maps, and a
        status the deployment DID name always wins."""
        from openfactory.adapters.board.columns import key_for

        return key_for(column, renamed=getattr(self._tracker, "status_map", None) or {})

    def stage_column(self, key: str) -> str:
        """The status this project calls the stage `key`. See `Staged.stage_column`.

        THE ROW THE DEFECT WAS MEASURED ON (#496): with `status_map: {"todo": "A Fazer"}` the
        product role asked `set_column` for `TO-DO`, the site's workflow offered `A Fazer`, and the
        match below is by name — so each promotion was refused. Read off the same `status_map` as
        `stage_key` and `set_status`, with the platform's names under it for a status the
        deployment did not declare, which is what this row has always been asked for."""
        from openfactory.adapters.board.columns import name_for

        return name_for(key, renamed=getattr(self._tracker, "status_map", None) or {})

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

    def intake_column(self, state: str = "") -> str | None:
        """The status an issue the tracker creates is in before anybody moves it — `""` for the
        one Jira gives a new issue, its workflow's INITIAL status (#543). See `board.base.intake`.

        THE SAME DEFECT AS AZURE'S (#536), ON THE ROW THAT CANNOT CHOOSE. A Jira project's
        statuses are its columns and a new issue is born in its workflow's first one — `To Do`,
        `A Fazer` on the templates a team starts from — which the deployment maps as its queue
        (`status_map: '{"todo": "A Fazer"}'`, the shape `docs/reference/configuration.md` shows).
        The door's `filed` then asked for a `Backlog` the workflow does not offer, the card stayed,
        and the poller took it; where it does offer one, the card sat in the queue until the move.
        `JiraTracker.intake_state` says why the create cannot carry a status of its own.

        READ FROM THE ISSUE TYPE THE TRACKER CREATES (`issue_type`) ONLY WHERE THE READ CANNOT BE
        A GUESS: its ONE status of the To Do category (`new`), or its one status where the site
        names no category. Atlassian documents no order for `project/{key}/statuses` and no read of
        a workflow's initial status short of administering it, so a type with SEVERAL candidates is
        not answered by the order they happen to be listed in — measured in the review of #552, the
        same statuses listed the other way round made the doctor pass a board whose create lands in
        the queue, and fail the board its own line had repaired. It raises `IntakeUnknown`, naming
        them and the declaration that answers it: `intake_status`, the deployment's word for the
        initial status, which the line `intake_remedy` hands over carries too.

        A DECLARED `state` is its status by name, without case — and one the type does not have
        raises `IntakeUnknown` rather than answering `""`, which would read as "born on no column"
        and file. `None` = the statuses could not be read — never "no such column", for the reason
        `AzureBoardsBoard.intake_column` gives — and a type that lists none has not said either."""
        from openfactory.adapters.board.base import IntakeUnknown

        statuses = self._statuses_of_the_type()
        if not statuses:
            return None
        names = list(dict.fromkeys(n for n, _c in statuses))
        kind = str(getattr(self._tracker, "issue_type", "") or "") or "issue"
        wanted = (state or "").strip().casefold()
        if wanted:
            found = next((n for n in names if n.casefold() == wanted), None)
            if found is None:
                raise IntakeUnknown(
                    f"`intake_status` declares {state.strip()!r}, which is not a status of the "
                    f"{kind} type ({', '.join(repr(n) for n in names)})",
                    remedy=_intake_status_remedy(names, kind))
            return found
        first = list(dict.fromkeys(n for n, c in statuses if c == "new")) or names
        if len(first) == 1:
            return first[0]
        raise IntakeUnknown(
            f"the {kind} type's workflow has {len(first)} statuses a new issue could start in "
            f"({', '.join(repr(n) for n in first)}), and Jira says which one only to the "
            f"workflow's administrator — so none is taken from the order the site lists them in",
            remedy=_intake_status_remedy(first, kind))

    def intake_remedy(self, column: str) -> str:
        """The line that takes a filed card out of the queue `column` on this row — what
        `openfactory doctor` hands the operator (#543), as the registry takes it: QUOTED, a string
        of JSON, the deployment's whole `status_map` with the two keys changed — on Jira that map
        names every stage, and a line naming two would unmap the rest.

        A QUEUE OF ITS OWN, the shape the Azure row's line asks for too: `column` stays where Jira
        files a new issue and becomes the backlog, so a card a PERSON creates on the board waits
        there as well, and the poller reads a status nobody's create lands in.

        AND `intake_status` WITH IT: the repaired workflow has two statuses of the To Do category,
        which `intake_column` refuses to tell apart by listing order — so the line also declares
        the one Jira creates in, and applying it removes the guess instead of creating one (review
        of #552)."""
        named = dict(getattr(self._tracker, "status_map", None) or {})
        line = json.dumps({**named, "backlog": column, "todo": "Ready"}, ensure_ascii=False)
        return ("add a status of the To Do category for the queue — `Ready`, say — to the "
                f"project's workflow, with a transition into it from `{column}`, and declare under "
                f"the tracker's options `status_map: {_yaml_quoted(line)}` and "
                f"`intake_status: {_yaml_quoted(column)}` — a new issue then waits in `{column}` "
                f"until a person queues it")

    def _statuses_of_the_type(self) -> list[tuple[str, str]] | None:
        """`(name, category key)` of each status of the issue type the tracker creates, in the
        site's order — every type's, when that one is not listed — or None when unreadable."""
        try:
            types = self._tracker._call("GET", f"project/{self.project_key}/statuses")
        except Exception as exc:  # noqa: BLE001 — unreadable is NOT "born on no column"
            log.warning("could not read the statuses of %s (%s) — where a new issue is born is "
                        "unknown, and unknown is never read as out of the queue",
                        self.project_key, str(exc)[:200])
            return None
        listed = [t for t in types if isinstance(t, dict)] if isinstance(types, list) else []
        kind = str(getattr(self._tracker, "issue_type", "") or "").strip().casefold()
        mine = [t for t in listed if str(t.get("name") or "").strip().casefold() == kind] or listed
        return [(str(s.get("name")), str((s.get("statusCategory") or {}).get("key") or ""))
                for t in mine for s in (t.get("statuses") or []) if s.get("name")]

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

    def place_after(self, *, issue: str, issue_url: str, after: str | None, column: str) -> bool:
        """Rank `issue` right after `after` — or before the first card of `column` when there is
        no `after` — through the Agile API's rank endpoint (see `Rankable`).

        THE ENDPOINT, NOT THE FIELD. Jira's rank is a LexoRank in a custom field whose id differs
        per site, and writing it by hand is how two cards end up with the same rank. The Agile
        API's `issue/rank` takes a neighbour and computes the value, which is what the board's own
        drag does."""
        payload: dict = {"issues": [issue]}
        if after:
            payload["rankAfterIssue"] = after
        else:
            first = next((k for k in self.items_in_status(column) if k != issue), None)
            if first is None:
                return True  # alone in the column: it is already first
            payload["rankBeforeIssue"] = first
        try:
            self._tracker._call("PUT", "issue/rank", payload, api="agile/1.0")
        except Exception as exc:  # noqa: BLE001 — a False must always leave a why behind it
            log.error("OPENFACTORY_BOARD_RANK_FAILED %s issue=%s after=%r: %s",
                      self.project_key, issue, after, str(exc)[:200])
            return False
        return True

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
        if match is None and self._status_now(issue).lower() == target.lower():
            # ALREADY THERE IS PLACED (#543). A workflow offers no transition into the status an
            # issue is in, so a card born in the backlog — what a Jira project whose queue has a
            # status of its own does with every new issue — had its `filed` refused as a move the
            # workflow does not offer, said to the person, and asked again by the hourly round
            # for ever. Every other row writes a column it is already in as a no-op; this one now
            # answers the same.
            return True
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

    def _status_now(self, issue: str) -> str:
        """The status `issue` is in, `""` when it could not be read — asked only of a move the
        workflow does not offer, so an ordinary move costs no second call."""
        try:
            fields = self._tracker._call("GET", f"issue/{issue}").get("fields") or {}
        except Exception as exc:  # noqa: BLE001 — unread is "not known to be there": the move fails
            log.info("could not read where %s is (%s)", issue, str(exc)[:200])
            return ""
        return self._status_of({"fields": fields})

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


def _yaml_quoted(value: str) -> str:
    """`value` as a YAML single-quoted scalar — the form a line pasted under the tracker's options
    is read back as one string: a quote inside is doubled, YAML's own escape there (`Won't Do`)."""
    return "'" + str(value).replace("'", "''") + "'"


def _intake_status_remedy(statuses: list[str], kind: str) -> str:
    """The declaration that answers where a new issue starts, when the workflow cannot be read for
    it (#543) — `intake_status`, named among the statuses it can be, never guessed among them."""
    them = ", ".join(f"`{s}`" for s in statuses)
    return (f"declare under the tracker's options the status a new {kind} issue starts in — the "
            f"workflow's initial status, one of {them} — as `intake_status: "
            f"{_yaml_quoted(statuses[0] if len(statuses) == 1 else '<that status>')}`")

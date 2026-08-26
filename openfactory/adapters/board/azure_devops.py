"""An Azure Boards board — the pickup queue for a deployment whose work lives in Azure DevOps.

THE COLUMN IS A STATE, the same shape the Jira board solved. A Kanban board in Azure DevOps has
no per-card status field of its own: each column declares `stateMappings`, `{work item type:
state}`, and a card sits in the column its state maps to. So this class needs no field ids and no
card ids — reading the board is a query, and moving a card is a state change.

    "To Do"        stateMappings {"Issue": "To Do"}
    "Doing"        stateMappings {"Issue": "Doing"}
    "Needs Action" stateMappings {"Issue": "Needs Action"}

WHAT ONLY A LIVE CALL WOULD HAVE TOLD US — every one of these was found against a live Azure
DevOps project (`{org}/{project}` below), and every one of them would have been a plausible-looking
bug written from the documentation:

**`System.BoardColumn` is READ-ONLY.** It is the obvious field to write — it is literally named
after the column — and a `PATCH` of it answers `400 TF401326: Invalid field status 'ReadOnly'`.
The move therefore goes through `System.State`, resolved from the column's own `stateMappings`
for THAT CARD'S type. Which is also why the type is read before the write: one board can carry
several work item types, and a column maps a different state for each.

**The board is a TEAM's, the work items are the PROJECT's, and the routes do not overlap.** A
board lives under `{project}/{team}/_apis/work/…`, and so does `wit/wiql` — but every other
`wit/…` route answers `404 The controller for path '…/{project} Team/_apis/wit/workitems/3' was
not found` under a team segment. So the reads here are team-scoped and the writes are
project-scoped, deliberately, and neither is an accident of copy-paste.

**A wrong team is a 404 that reads exactly like a missing board** (`The team with id 'x' does not
exist`). That is why the team is *discovered* — `GET _apis/projects/{project}` carries
`defaultTeam.name` — rather than guessed from a naming convention, and why the one place that
still falls back to the convention says so in its warning.

**`items_in_status` for a column that does not exist answers `[]`, cheerfully.** WIQL has no
opinion about whether `System.BoardColumn = 'Todo'` could ever match. A pickup column misspelled
by one character therefore looks precisely like a factory with nothing to do — which is the
failure this platform exists to not have — so the name is checked against the board's real columns
first, and a miss is loud.

`ORDER BY` IS `Microsoft.VSTS.Common.StackRank`, which is what Jira's `Rank` is: the order the
humans who groomed the backlog put the cards in. `BacklogPriority` follows it as a tie-break
because that is the field the Scrum process templates order by instead, and a board must not fall
back to creation order just because the client picked a different process — the fallback is only
`[System.Id]`, and reaching it is logged as the loss of fidelity that it is.
"""

from __future__ import annotations

import logging
import urllib.parse

from openfactory.adapters.azure_devops import AzureDevOpsClient
from openfactory.contracts import JobState
from openfactory.contracts.refs import canonical_ref, qualify_ref, ref_number, split_repo_ref

log = logging.getLogger("openfactory.board.azure_devops")

#: One page per column bounds a runaway read. Longer than this is REPORTED, never silently cut —
#: the same rule the Jira board follows at 200 and the GitHub one at 2000.
_MAX_ITEMS = 200

_COLUMN_FIELD = "System.BoardColumn"
_STATE_FIELD = "System.State"
_TYPE_FIELD = "System.WorkItemType"

#: The board's own order. `StackRank` is Basic/Agile/CMMI; `BacklogPriority` is Scrum. Both are
#: organisation-level fields, so naming both in one `ORDER BY` sorts either process correctly
#: (the one the process does not use is null on every card and never decides anything).
_ORDER_BY = ("[Microsoft.VSTS.Common.StackRank] ASC, "
             "[Microsoft.VSTS.Common.BacklogPriority] ASC, [System.Id] ASC")

#: Where `_ORDER_BY` retreats to when the organisation defines neither ranking field. Creation
#: order is NOT board order, so reaching this is a warning, not a silent equivalence.
_ORDER_BY_FALLBACK = "[System.Id] ASC"

#: WIQL's "you named a field I do not have" — the only ORDER BY failure worth retrying.
_UNKNOWN_FIELD = "TF51005"

#: The DEFAULT column names — what the platform's own `OpenFactory Basic` process creates. A
#: client whose board says "A Fazer" overrides them per key in the registry's tracker options
#: (`columns:`), exactly as the Jira and GitHub boards already do: the STATES stay closed, only
#: the LABELS open (C-14). There is no `backlog` key because `STATE_KEYS` never asks for one and
#: an Azure Boards board has no such column by default — inventing one here would have
#: `set_status` aiming at a column that is not on the client's board.
DEFAULT_COLUMNS: dict[str, str] = {
    "todo": "To Do",
    "in_progress": "Doing",
    "in_review": "In review",
    "needs_action": "Needs Action",
    "done": "Done",
}


def _wiql_literal(value: str) -> str:
    """A WIQL string literal's inside. WIQL escapes a quote by doubling it, and a column named
    `Client's review` is a syntax error otherwise — not a wrong answer, a 400 mid-tick."""
    return str(value).replace("'", "''")


class AzureBoardsBoard:
    """Satisfies `BoardAdapter` over one Azure Boards board."""

    def __init__(self, *, organization: str, project: str, team: str = "", board: str = "",
                 columns: dict[str, str] | None = None, order_by: str = "",
                 token: str | None = None, token_provider=None,
                 default_repo: str = "", areas: dict[str, str] | None = None,
                 options: dict[str, str] | None = None) -> None:
        if not (organization or "").strip() or not (project or "").strip():
            # Fails HERE, not on the first read inside a job: the shared client makes the same
            # promise for the same reason, and a board that resolves to something unusable is a
            # poller tick that logs a stack trace instead of a queue.
            raise ValueError(
                "an Azure Boards board needs both an organization and a project — its routes nest "
                f"organization/project/team/board. Got organization={organization!r}, "
                f"project={project!r}; declare them under the tracker's `options`."
            )
        self.organization = organization.strip()
        self.project = project.strip()
        self._team = (team or "").strip()
        self._board = (board or "").strip()
        self._names = {**DEFAULT_COLUMNS, **{str(k): str(v) for k, v in (columns or {}).items()}}
        self._order_by = (order_by or "").strip() or _ORDER_BY
        self._static_token = token
        self._token_provider = token_provider
        self._options = dict(options or {})
        # C-18 ON AZURE DEVOPS. A GitHub Projects v2 card IS an issue in a repository, so the repo
        # is INTRINSIC and the board just reads it. An Azure Boards work item lives in a PROJECT
        # that holds N git repositories with no link to any of them — so on ADO the mechanism has
        # nothing to read, and every card on a three-repo product would arrive bare, resolve to
        # the single registry `forge.repo`, and send the agent to edit the wrong tree in silence.
        #
        # AREA PATH IS THE ANSWER, and it is the ADO-native one rather than a convention invented
        # here: it is how real teams partition a project, it is on every Azure Boards screen, it
        # travels ON the work item, and `openfactory init` can create the nodes by API. Probed live
        # on
        # a client's Azure DevOps project (2026-08-06): a child area is creatable
        # (`\{project}\Area\<name>`), `System.AreaPath` comes back on the item, and WIQL
        # filters `UNDER` it.
        #
        # THE DEFAULT IS THE LEAF NAME. A client whose areas are named after their repositories
        # configures nothing; one whose are not declares `areas: '{"Portal": "dsk-ui"}'`. Empty
        # `default_repo` keeps today's behaviour byte for byte: refs stay bare.
        self._default_repo = (default_repo or "").strip()
        self._areas = {str(k).strip().lower(): str(v).strip()
                       for k, v in (areas or {}).items() if str(v).strip()}
        # Resolved once per instance. `build_board` is called per operation across this codebase,
        # so this de-duplicates the calls inside one read and can never serve a stale board across
        # ticks — a column added in the ADO UI is visible on the next one.
        self._team_cache: str = ""
        self._board_cache: str = ""
        self._columns_cache: list[dict] | None = None
        self._area_cache: str | None = None

    @property
    def token(self) -> str | None:
        # Resolved at each USE, never frozen: the `az account get-access-token` credential this is
        # provable with expires in about an hour, and a job outlives one.
        return self._token_provider() if self._token_provider else self._static_token

    # ---- scoping -----------------------------------------------------------------------------

    def _client(self, *, team: bool = False) -> AzureDevOpsClient:
        """A client scoped to the project, or to the team INSIDE the project.

        The shared client takes no `team` argument and does not need one: it quotes the project
        with `urllib.parse.quote`, whose default `safe="/"` keeps the separator and percent-encodes
        the space in `{project} Team`, so a project of `"<project>/<team>"` produces exactly the
        team-scoped URL Azure DevOps documents. Verified live against both scopes. If the shared
        client ever grows a real `team=` parameter, this method is the single call site to move.
        """
        scope = f"{self.project}/{self._resolve_team()}" if team else self.project
        return AzureDevOpsClient(organization=self.organization, project=scope,
                                 token=self.token, options=self._options)

    def _resolve_team(self) -> str:
        """Which team's board this is. Declared, else the project's own default team.

        ASKED, NOT GUESSED. `"<project> Team"` is Azure DevOps's naming convention and it is right
        almost always, which is the problem: the time it is wrong, every board route answers 404
        *"The team with id 'x' does not exist"* and the deployment reads that as a board somebody
        forgot to create."""
        if self._team:
            return self._team
        if self._team_cache:
            return self._team_cache
        convention = f"{self.project} Team"
        try:
            got = self._client().call(
                "GET", f"projects/{urllib.parse.quote(self.project)}", project_scoped=False)
            name = str(((got.get("defaultTeam") or {}).get("name")) or "")
        except Exception as exc:  # noqa: BLE001 — a probe must not take the board down with it
            name = ""
            log.warning("could not read the default team of %s/%s (%s) — falling back to Azure "
                        "DevOps's naming convention %r. If the board now reads as missing, THIS "
                        "guess is why: declare `team` in the project's tracker options.",
                        self.organization, self.project, str(exc)[:200], convention)
        self._team_cache = name or convention
        return self._team_cache

    def _resolve_board(self) -> str | None:
        """Which board. Declared, else the team's first — which is its lowest backlog level.

        A project has one board per backlog level (`Issues` and `Epics` here; `Stories`,
        `Features`, `Epics` on Agile) and Azure DevOps lists them lowest level first. The lowest is
        where day-to-day cards live, so it is the right default — and it is logged when there was
        more than one to choose from, because a default nobody sees is a default nobody corrects.
        """
        if self._board:
            return self._board
        if self._board_cache:
            return self._board_cache
        try:
            boards = self._client(team=True).values("work/boards")
        except Exception as exc:  # noqa: BLE001 — unreadable is never "there is no board"
            log.warning("could not list the boards of team %r in %s/%s (%s) — the caller must "
                        "treat this as UNREADABLE, never as a project without a board",
                        self._resolve_team(), self.organization, self.project, str(exc)[:200])
            return None
        names = [str(b.get("name") or "") for b in boards if b.get("name")]
        if not names:
            log.error("team %r in %s/%s reports no boards at all — a backlog level with no board "
                      "is a project configuration problem, not an empty queue",
                      self._resolve_team(), self.organization, self.project)
            return None
        self._board_cache = names[0]
        if len(names) > 1:
            log.info("no `board` declared for %s/%s — reading %r, the first of %s that team %r "
                     "reports. Declare `board` in the project's tracker options to pin it.",
                     self.organization, self.project, self._board_cache, names,
                     self._resolve_team())
        return self._board_cache

    # ---- the board's own metadata ------------------------------------------------------------

    def url(self) -> str:
        """`https://dev.azure.com/{org}/{project}/_boards/board/t/{team}/{board}` — see
        `BoardAdapter.url`.

        THE TEAM AND THE BOARD ARE OPTIONAL COORDINATES, and the URL degrades WITH them rather than
        guessing: with neither, `…/_boards` is the project's board hub, which is a page that exists
        and is one click from the right board. A fabricated team name is a 404, and a 404 reads to
        an operator as "the platform lost my board".
        """
        import urllib.parse

        if not (self.organization and self.project):
            return ""
        base = (f"https://dev.azure.com/{urllib.parse.quote(self.organization)}"
                f"/{urllib.parse.quote(self.project)}/_boards")
        if not self._team:
            return base
        team = urllib.parse.quote(self._team)
        if not self._board:
            return f"{base}/board/t/{team}"
        return f"{base}/board/t/{team}/{urllib.parse.quote(self._board)}"

    def pickup_column(self) -> str:
        """`To Do` here, or whatever this client renamed it to. See `BoardAdapter.pickup_column`.

        This is the provider that made the gap visible: the platform's literal `"TO-DO"` asked an
        Azure board for a column it does not have, and the honest empty list that came back was
        indistinguishable from an idle queue until the adapter logged why."""
        return self._names.get("todo") or DEFAULT_COLUMNS["todo"]

    def _board_columns(self) -> list[dict] | None:
        """The columns as Azure DevOps reports them, in board order. None = could not read."""
        if self._columns_cache is not None:
            return self._columns_cache
        name = self._resolve_board()
        if name is None:
            return None
        try:
            got = self._client(team=True).values(
                f"work/boards/{urllib.parse.quote(name)}/columns")
        except Exception as exc:  # noqa: BLE001 — unreadable is NOT "a board without columns"
            log.warning("could not read the columns of board %r for team %r in %s/%s (%s) — the "
                        "caller must treat this as UNREADABLE, never as a board without columns. "
                        "A 404 here is usually the TEAM rather than the board: the board hangs off "
                        "the team, and a wrong team name answers exactly like a board that is not "
                        "there.", name, self._resolve_team(), self.organization, self.project,
                        str(exc)[:200])
            return None
        if not got:
            # A KANBAN BOARD ALWAYS HAS COLUMNS — `work/boards/Nope/columns` answers `404
            # TF401501: The board does not exist`, so an empty list is never Azure DevOps saying
            # "this board has none"; it is a 200 whose `value` did not arrive, and `values()` has
            # no way to tell the two apart. Kept as UNREADABLE for the reason `_resolve_board`
            # keeps a team with no boards: letting it through makes `columns()` answer `{}` — an
            # unreadable board reported as one every card has left — and `column_names()` answer
            # `[]`, which sends somebody to create columns they are looking straight at.
            log.error("board %r for team %r in %s/%s reports no columns at all — treating the "
                      "board as UNREADABLE rather than as empty",
                      name, self._resolve_team(), self.organization, self.project)
            return None
        self._columns_cache = got
        return got

    def _board_types(self) -> list[str] | None:
        """The work item types this board carries, taken from the columns' own `stateMappings`.

        Read from the board rather than configured, because getting it wrong is silent in both
        directions: query too broadly and an Epic's `To Do` — a DIFFERENT board's column of the
        same name — joins the pickup queue and the factory starts coding an epic."""
        cols = self._board_columns()
        if cols is None:
            return None
        types: list[str] = []
        for column in cols:
            for kind in (column.get("stateMappings") or {}):
                if str(kind) not in types:
                    types.append(str(kind))
        return types

    def _team_area_clause(self) -> str:
        """`[System.AreaPath] …` restricting a query to the TEAM's own cards, or `""`.

        A board shows the team's area paths, not the project's. Without this the pickup queue on a
        multi-team project is a superset of the board somebody is looking at, and the factory
        picks up another team's card — work nobody asked it for, in the client's name.

        The field is read from the response rather than assumed to be `System.AreaPath`: an older
        project may be partitioned on a custom team field, and the answer names which."""
        if self._area_cache is not None:
            return self._area_cache
        try:
            got = self._client(team=True).call("GET", "work/teamsettings/teamfieldvalues")
        except Exception as exc:  # noqa: BLE001 — a superset queue beats no queue, but say so
            log.warning("could not read the area paths of team %r in %s/%s (%s) — querying the "
                        "whole project instead. On a project with several teams the queue is then "
                        "a SUPERSET of this team's board.", self._resolve_team(),
                        self.organization, self.project, str(exc)[:200])
            self._area_cache = ""
            return ""
        field = str((got.get("field") or {}).get("referenceName") or "System.AreaPath")
        parts = []
        for value in got.get("values") or []:
            path = str(value.get("value") or "")
            if not path:
                continue
            # `includeChildren` is the team's own answer to "and everything under it?" — honoured
            # rather than assumed, because assuming UNDER hands the factory sub-team cards and
            # assuming `=` hides the team's own.
            operator = "UNDER" if value.get("includeChildren") else "="
            parts.append(f"[{field}] {operator} '{_wiql_literal(path)}'")
        self._area_cache = f"({' OR '.join(parts)})" if parts else ""
        return self._area_cache

    # ---- the one query path ------------------------------------------------------------------

    def _ids(self, clause: str = "") -> list[str] | None:
        """Work item ids matching `clause`, in board order. None = could not read.

        `None` versus `[]` is the port's hardest rule and this is where it is decided for every
        read below: an unreachable Azure DevOps and an empty column are the same shape to a caller
        that collapses them, and the collapse reads as "nothing is queued"."""
        types = self._board_types()
        if types is None:
            return None  # the board itself is unreadable; a query would answer for the wrong scope
        where = ["[System.TeamProject] = @project"]
        if types:
            where.append("[System.WorkItemType] IN ("
                         + ", ".join(f"'{_wiql_literal(t)}'" for t in types) + ")")
        area = self._team_area_clause()
        if area:
            where.append(area)
        if clause:
            where.append(clause)
        return self._run(" AND ".join(where))

    def _qualify(self, ids: list[str]) -> list[str]:
        """Ids → refs carrying their repository, when this board knows how to say (C-18).

        A NO-OP UNTIL A DEPLOYMENT ASKS FOR IT. With no `default_repo` the refs come back exactly
        as before, because a single-repo project has nothing to disambiguate and paying a batch
        read per tick to learn that would be a cost with no answer.

        ONE EXTRA CALL, NOT ONE PER CARD. A flat WIQL response carries `{id, url}` and nothing
        else — no fields, whatever the SELECT says — so the area has to be read separately; the
        batch route takes 200 ids at a time, which is this board's own page size.

        UNREADABLE AREAS DEGRADE TO BARE REFS, LOUDLY. Returning nothing would turn a metadata
        hiccup into an empty pickup queue, which is the failure this whole adapter is written
        against. A bare ref still routes to the project's default repository — the behaviour of
        every deployment before this existed — and the warning says the routing is now a guess."""
        if not self._default_repo or not ids:
            return ids
        try:
            rows = self._client().values(
                "wit/workitems",
                params={"ids": ",".join(ids[:_MAX_ITEMS]), "fields": "System.Id,System.AreaPath",
                        "$expand": "none"})
        except Exception as exc:  # noqa: BLE001 — a metadata read must never empty the queue
            log.warning("could not read the area paths of %s/%s (%s) — the pickup queue keeps its "
                        "bare refs, so every card routes to %r. On a product spanning several "
                        "repositories that is the WRONG repository for all but one of them.",
                        self.organization, self.project, str(exc)[:160], self._default_repo)
            return ids
        by_id = {str(r.get("id")): str((r.get("fields") or {}).get("System.AreaPath") or "")
                 for r in rows}
        return [qualify_ref(self._repo_for_area(by_id.get(i, "")), i, self._default_repo)
                for i in ids]

    def _repo_for_area(self, area: str) -> str:
        """Which repository an area path names. `""` when it names none — meaning the default.

        The LEAF is what carries meaning: Azure DevOps reports `{project}\\Portal\\Admin` and the
        root segment is always the project, which every card shares and therefore cannot
        distinguish. An explicit `areas:` entry wins over the convention, matched case-insensitively
        because a client typing `portal` in the registry for an area named `Portal` has not made a
        mistake worth a silent misroute."""
        leaf = (area or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip()
        if not leaf or leaf.lower() == self.project.lower():
            return ""  # the project root: this card is not partitioned, so it is the default's
        repo = self._areas.get(leaf.lower(), leaf)
        # PROJECT-QUALIFIED, and that is not decoration. `split_repo_ref` only splits a ref whose
        # repo segment contains a `/` (`refs.py:86`), so a bare `fx-dsk-ui#3` travels downstream
        # LOOKING qualified and resolves to the default repository anyway — the silent misroute
        # this whole mechanism exists to prevent, reintroduced by the mechanism itself. Measured:
        # `split_repo_ref("fx-dsk-ui#3", "fx-ado")` → `("fx-ado", "fx-dsk-ui#3")`, while
        # `split_repo_ref("{project}/fx-dsk-ui#3", …)` → `("{project}/fx-dsk-ui", "3")`.
        # `AzureReposForge` takes the last segment, so the extra one costs nothing there.
        return f"{self.project}/{repo}"

    def _run(self, where: str, *, order_by: str = "") -> list[str] | None:
        query = (f"SELECT [System.Id] FROM WorkItems WHERE {where} "
                 f"ORDER BY {order_by or self._order_by}")
        try:
            got = self._client(team=True).call(
                "POST", "wit/wiql", body={"query": query},
                # one over the cap, so truncation is DETECTED rather than assumed away
                params={"$top": _MAX_ITEMS + 1})
        except Exception as exc:  # noqa: BLE001 — unreadable is never "empty"
            detail = str(exc)
            if _UNKNOWN_FIELD in detail and not order_by:
                log.warning("%s/%s does not define the ranking fields this board orders by (%s) — "
                            "retrying by id, which is CREATION order, not the order the backlog "
                            "was groomed into. Set `order_by` in the project's tracker options to "
                            "name this organisation's own ranking field.",
                            self.organization, self.project, detail[:200])
                # REMEMBERED, not just retried. `columns()` is one query per column, so a fallback
                # that only applied to the query that discovered it would spend a guaranteed 400
                # on every single one — and log the same warning once per column, every read.
                # The explicit `order_by` below is what keeps this from recursing: the retry can
                # never take this branch again.
                self._order_by = _ORDER_BY_FALLBACK
                return self._run(where, order_by=_ORDER_BY_FALLBACK)
            log.warning("could not query the board of %s/%s (%s) — the caller must treat this as "
                        "UNREADABLE, never as an empty board",
                        self.organization, self.project, detail[:300])
            return None
        items = got.get("workItems")
        if items is None:
            log.warning("the WIQL query on %s/%s returned no `workItems` field — treating as "
                        "unreadable rather than as an empty board",
                        self.organization, self.project)
            return None
        ids = [str(w.get("id")) for w in items if w.get("id")]
        if len(ids) > _MAX_ITEMS:
            log.warning("%s/%s has more cards matching %r than this read returned (stopped at %s) "
                        "— the queue may be missing items",
                        self.organization, self.project, where, _MAX_ITEMS)
            ids = ids[:_MAX_ITEMS]
        return ids

    # ---- the port ----------------------------------------------------------------------------

    def columns(self) -> dict[str, str] | None:
        """`{work item id: column name}` for the whole board, in board order.

        READ COLUMN BY COLUMN rather than as one query plus a field lookup, and the reason is the
        route split at the top of this module: `System.BoardColumn` on a work item read is resolved
        for the project's DEFAULT team, because no `wit/workitems` route accepts a team segment,
        while `wit/wiql` does. Asking each column "who is in you?" through the team-scoped query is
        the only shape that stays truthful on a project with more than one team.

        The dict is built in board order and, within a column, in the backlog's own rank order —
        `dict` preserves insertion, so the caller gets the board as a person reads it.

        ONE UNREADABLE COLUMN MAKES THE WHOLE ANSWER `None`. A partial board is worse than an
        admitted failure: it reports the cards it could not see as not being on the board at all.
        """
        names = self.column_names()
        if names is None:
            return None
        out: dict[str, str] = {}
        for name in names:
            ids = self._ids(f"[{_COLUMN_FIELD}] = '{_wiql_literal(name)}'")
            if ids is None:
                log.warning("could not read column %r of %s/%s — reporting the WHOLE board as "
                            "unreadable rather than as a board those cards have left",
                            name, self.organization, self.project)
                return None
            # QUALIFIED AT THIS EDGE TOO (C-18), exactly as the GitHub board does: two cards
            # numbered the same in different repositories must not collapse into one key, or the
            # board moves the wrong card and says it moved the right one.
            for ref in self._qualify(ids):
                out[ref] = name
        return out

    def column_names(self) -> list[str] | None:
        """The board's columns, in board order — which columns EXIST, cards or no cards.

        A different question from `columns()`: on an empty board that is `{}`, and `openfactory
        doctor`
        asking "is there a To Do?" must not be answered "no" by a board nobody has filed against
        yet."""
        cols = self._board_columns()
        if cols is None:
            return None
        return [str(c.get("name") or "") for c in cols if c.get("name")]

    def items_in_status(self, status: str) -> list[str]:
        """Work item ids sitting in one column, in the backlog's own rank order — the pickup queue.

        `[]` on an unreadable board rather than a raise: this is the poller's hottest read and
        `scan_todo` already treats an empty queue as "nothing to do this tick". The warnings in
        `_run` and below are what say which of the two happened.

        THE NAME IS CHECKED AGAINST THE REAL COLUMNS FIRST. WIQL will happily answer `[]` for
        `System.BoardColumn = 'Todo'` on a board whose column is `To Do` — an entire factory
        standing still because of one space, reported as a quiet day. The check costs the columns
        read this adapter already needs, and its miss is loud."""
        wanted = str(status or "")
        if not wanted:
            log.warning("items_in_status was asked for an unnamed column on %s/%s — returning "
                        "empty; the caller's pickup column is unset",
                        self.organization, self.project)
            return []
        known = self.column_names()
        if known is not None:
            # The board's OWN spelling goes into the query, not the caller's: the comparison here
            # is case-insensitive and Azure DevOps's need not be.
            match = next((n for n in known if n.lower() == wanted.lower()), None)
            if match is None:
                log.error("OPENFACTORY_BOARD_UNKNOWN_COLUMN %s/%s: the board has no column "
                          "named %r "
                          ""
                          "— it "
                          "has %s. This queue is empty because of the NAME, not because nothing "
                          "is waiting.", self.organization, self.project, wanted, known)
                return []
            wanted = match
        # THE PICKUP QUEUE IS WHERE THE REPOSITORY STARTS TRAVELLING WITH THE TICKET (C-18) —
        # everything downstream (the clone, the tracker call, the board move) acts on the ref this
        # returns, so a bare one here is what sends the agent to the wrong repository.
        return self._qualify(self._ids(f"[{_COLUMN_FIELD}] = '{_wiql_literal(wanted)}'") or [])

    def add_item(self, *, issue_url: str) -> None:
        """An Azure DevOps work item is ON its team's board by existing — there is nothing to add.

        Kept as an explicit no-op rather than omitted, exactly as the Jira board keeps its own:
        `GitHubProjectBoard.add_item` exists because a Projects v2 board is a SEPARATE object a
        card must be attached to, and no caller should have to know which of the two shapes it is
        holding.

        The one case that is not automatic is a card filed OUTSIDE the team's area paths, which no
        column can hold it in. That is a decision about where work belongs, taken when the ticket
        is created; a board silently re-parenting somebody's card would be the worse answer."""

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        """Move a card to the column called `name`, by setting the state that column maps to.

        NOT by writing the column. `System.BoardColumn` is read-only — a `PATCH` of it answers
        `400 TF401326: Invalid field status 'ReadOnly'` — so the column is an effect of the state,
        and the board's own `stateMappings` is what says which state. Per work item TYPE, which is
        why the card is read before it is written: one board carries several types and a column
        maps a different state for each of them."""
        target = str(name or "")
        # THE REF THIS BOARD MINTS IS THE REF THIS BOARD MUST ACCEPT (sweep S1, 2026-08-16).
        # `items_in_status` returns `_qualify`'d refs — `owner/repo#1234` — precisely so the
        # repository travels with the ticket on a multi-repo product (C-18), and this method then
        # handed the whole string to `ref_number`, got None, and refused its own output as "not an
        # Azure DevOps work item id". Every card move on such a board failed: the park never
        # showed, the merge never settled, and the three-minute stale-card heal retried the same
        # refusal for ever. The Azure TRACKER learned this at C-18 and left a comment saying the
        # GitHub one had had it since; the BOARD is the third place, found by the sweep rather
        # than by a client.
        #
        # The repository is discarded on purpose, exactly as the tracker discards it: which repo a
        # card belongs to is the forge's question, and all a board move needs is the number.
        _repo, ref = split_repo_ref(canonical_ref(issue), "")
        number = ref_number(ref)
        if number is None:
            # C-05: the ref is the provider's own string, and Azure DevOps's is a positive integer.
            # Refused rather than coerced — reducing `CONT-412` to `412` moves somebody else's card.
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%r -> %r: not an Azure "
                      "DevOps work "
                      ""
                      "item "
                      "id", self.organization, self.project, issue, target)
            return False
        if not target:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s: asked to move to an unnamed "
                      "column",
                      self.organization, self.project, number)
            return False
        cols = self._board_columns()
        if cols is None:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r: the board's columns are "
                      "unreadable, so the state that column maps to is unknown — refusing to "
                      "guess a state", self.organization, self.project, number, target)
            return False
        column = next((c for c in cols
                       if str(c.get("name") or "").lower() == target.lower()), None)
        if column is None:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r: the board has no such "
                      "column "
                      "(it has %s)", self.organization, self.project, number, target,
                      [str(c.get("name") or "") for c in cols])
            return False
        card = self._card(number)
        if card is None:
            return False
        state = str((column.get("stateMappings") or {}).get(card["type"]) or "")
        if not state:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r: that column carries no "
                      "state "
                      "for work item type %r (it maps %s) — the card stays where it is",
                      self.organization, self.project, number, target, card["type"],
                      column.get("stateMappings") or {})
            return False
        if card["state"] == state:
            # Already there. Compared on the STATE and not on `System.BoardColumn`: state is the
            # same answer for every team, and the column a work item read reports is the default
            # team's. Skipping the write also spares the card a revision that says nothing.
            return True
        try:
            self._client().call(
                "PATCH", f"wit/workitems/{number}",
                body=[{"op": "add", "path": f"/fields/{_STATE_FIELD}", "value": state}],
                content_type="application/json-patch+json")
        except Exception as exc:  # noqa: BLE001 — a False must always leave a why behind it
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r (state %r): %s",
                      self.organization, self.project, number, target, state, str(exc)[:300])
            return False
        return True

    def _card(self, number: int) -> dict | None:
        """`{type, state}` for one work item, or None when it could not be read.

        Project-scoped on purpose: `wit/workitems/{id}` answers `404 The controller for path …
        was not found` under a team segment, which is a route error wearing a not-found's clothes.
        """
        try:
            got = self._client().call(
                "GET", f"wit/workitems/{number}",
                params={"fields": f"{_TYPE_FIELD},{_STATE_FIELD}"})
        except Exception as exc:  # noqa: BLE001
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s: could not read the card, so "
                      "its "
                      "work item type — which decides the state its target column maps to — is "
                      "unknown (%s)", self.organization, self.project, number, str(exc)[:300])
            return None
        fields = got.get("fields") or {}
        return {"type": str(fields.get(_TYPE_FIELD) or ""),
                "state": str(fields.get(_STATE_FIELD) or "")}

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        """Move the card to whichever column THIS deployment mapped `state` to.

        Through `STATE_KEYS` and then through the client's own column names (C-14): the lifecycle
        is the platform's and the vocabulary is the client's, so an unmapped state is False with a
        reason rather than a guessed English literal."""
        from openfactory.adapters.tracker.base import column_key

        key = column_key(state, needs_person=needs_person)
        target = self._names.get(key or "", "")
        if not target:
            log.warning("no Azure Boards column mapped for %s (lifecycle key %r) on %s/%s — the "
                        "card stays where it is; add the mapping under the project's tracker "
                        "options (`columns`)", state, key, self.organization, self.project)
            return False
        return self.set_column(issue=issue, issue_url=issue_url, name=target)

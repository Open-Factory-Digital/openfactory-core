"""Azure Boards work items as a tracker — the second vendor for the tracker axis after Jira.

Written against a live client Azure DevOps project (process "OpenFactory Basic", type Issue,
states To Do → Doing → Needs Action → In review → Done). Every route below was called there before
it was written down; the shapes the tests assert against were recorded from those calls.

WHAT AZURE DEVOPS DOES DIFFERENTLY, and what each difference cost:

*Refs are integers.* GitHub says `#412`, Jira says `CONT-412`, Azure DevOps says `1234` — and
`contracts/refs.py` already documents that. A ref that is not a number reaches the API as
`GET wit/workitems/DAR-2` and comes back *"The controller for path … was not found or does not
implement IController"*, which sends the reader looking for a routing bug in the platform. So a ref
is normalised and refused here, with a sentence that says what it should have been.

*Writes are JSON Patch.* A work item changes through
`PATCH wit/workitems/{id}` with `application/json-patch+json` and a list of `{op, path, value}`
against `/fields/…`. The content type is not optional; the shared client takes it as
`content_type=`.

*Labels are tags, and the platform's own marker is illegal.* `System.Tags` is one
semicolon-separated string. Azure DevOps ACCEPTS a space inside a tag — the opposite of Jira, whose
adapter has to close the space up — but REFUSES any character outside the BMP: `🤖 sdlc-working`,
`🤖sdlc-working` and a bare `🤖` all answer *"TF401407: The tag name is invalid. It contains invalid
characters"*, while `✓ done` and `→ next` are fine. Verified live, one character at a time. So the
sanitiser here is the exact inverse of Jira's: keep the space, drop the astral characters.

*Adding a tag is a real `add`.* `{"op": "add", "path": "/fields/System.Tags"}` UNIONS with what is
there (proved: writing `sdlc-working` onto an item tagged `sdlc working` left both). That is why
`add_label` does not read-merge-write: a read-merge-write would be a lost-update race against the
human editing tags in the browser at the same moment, and it would be a race we introduced for
nothing. Removal has no such op, so `remove_label` does read-modify-`replace` and says so.

*Comments are on a different API version.* `POST wit/workItems/{id}/comments` under the pinned `7.1`
answers *"The requested version 7.1 of the resource is under preview. The -preview flag must be
supplied"* — a 400 on every comment the platform would ever post. It needs `7.1-preview.4`, and
`?format=markdown` so a multi-line comment is not rendered as one run-on line.

*Descriptions are HTML unless you say otherwise.* `System.Description` is stored as HTML by default
— a ticket a human writes in the browser arrives as `<div>Some intro</div><h2>Objective</h2>…` —
and `parse_ticket_body` reads markdown headings. Unconverted, every human-authored ticket would
parse as a ticket with no objective and no acceptance criteria, and the sizing gate would tell its
author their ticket says nothing. `multilineFieldsFormat` (returned on every read, settable on
every write) is what tells the two apart, so what the platform WRITES is stored as markdown and
what it READS is converted when the field says html.

*…AND THE SANITISER RUNS ANYWAY, WHICH TRUNCATES BODIES.* Saying `markdown` changes how the field
is RENDERED, not how it is stored: descriptions and comments both go through an HTML sanitiser on
every write, and it is not lossy in a tidy way. Measured live on that project's work item #9:

    wrote  'List<String> items and a <placeholder>'   read  'List items and a '
    wrote  '```\nif (a<b) { x }\n```'                 read  '```\nif (a'
    wrote  'A & B, 5 < 6'                             read  'A &amp; B, 5 &lt; 6'

An unknown tag is deleted, an unterminated one EATS THE REST OF THE FIELD, and a bare `&` comes
back as an entity. A split child's acceptance criteria are LLM prose about code — `Dict<str,int>`,
"the `<div>` renders" — so the second line above is a ticket whose criteria silently vanish, and
the sizing gate then tells its author the ticket says nothing, which is the very failure the
paragraph above exists to prevent, arriving from the other side. On the comment route the same cut
lands in the platform's voice: the `close_ticket` sentence that says the work was NOT delivered is
one `<` away from never being written.

So everything this adapter writes into either field is entity-escaped first and un-escaped on the
way back (`for_storage` / `description_text`). Escaping is the INVERSE of what the sanitiser does
— it rewrites exactly the characters that survive escaping untouched — so the round trip is
lossless (verified: byte-identical after `html.unescape`), and a person still reads `<String>`
because markdown renders entities. Escaping BEFORE and unescaping AFTER also composes: a body read
and rewritten unchanged stays unchanged.

STATE IS THE CATEGORY, NEVER THE NAME. `wit/workitemtypes/{type}/states` returns each state with
the vendor's own `category` — Proposed / InProgress / Resolved / Completed / Removed. `Completed`
and `Removed` mean closed; everything else is open. This is the same rule the Jira adapter follows
for `statusCategory`, and it is what keeps `Ticket.state` right on a board whose done column is
called "Donee" — a typo this deployment has actually seen. Reading the name would cost a full agent
pass on a delivered card every time somebody renames a column.

The forward direction — which state a JobState moves the card to — comes from the same table:
`state_map` in the project's tracker options wins, otherwise the category answers (done → the
Completed state, todo → Proposed, in_progress → InProgress, in_review → Resolved). `needs_action`
is the one bucket Azure DevOps has no category for; see `_state_for_key`.
"""

from __future__ import annotations

import html
import logging
import urllib.parse
from html.parser import HTMLParser

from openfactory.adapters.azure_devops import AzureDevOpsClient, AzureDevOpsError
from openfactory.adapters.tracker.base import (
    NOT_REPORTED,
    BudgetAnswer,
    TicketComment,
    TicketSummary,
    list_state,
)
from openfactory.adapters.tracker.base import column_key as _column_key
from openfactory.contracts import JobState, Ticket
from openfactory.contracts.refs import ref_number, split_repo_ref

log = logging.getLogger("openfactory.tracker.azure_devops")

#: Work item writes are JSON Patch and Azure DevOps rejects anything else with a 400.
JSON_PATCH = "application/json-patch+json"

#: The comments resource is still preview under 7.1 and says so in the 400 it answers otherwise.
COMMENTS_API_VERSION = "7.1-preview.4"

#: The fields one board row is built from. Named explicitly so the batch read does not drag every
#: process field (and every custom one a client added) across the wire for three hundred cards.
_LIST_FIELDS = ("System.Id,System.Title,System.Description,System.State,System.WorkItemType,"
                "System.Tags,System.AssignedTo,System.ChangedDate")

#: What `limit=0` costs at most, in work items. WIQL will happily return a whole project; this
#: bounds one read, and reaching it is logged rather than silently trimmed.
_LIST_CEILING = 1000

#: The vendor's own answer to "is this finished". `Removed` is a cancelled card — closed, and (via
#: `close_ticket(delivered=False)`) closed WITHOUT having been delivered.
CLOSED_CATEGORIES = frozenset({"completed", "removed"})

#: lifecycle key → the state category that means it. `needs_action` is absent on purpose: Azure
#: DevOps classifies work as Proposed/InProgress/Resolved/Completed/Removed and has no category for
#: "a human must look at this", so no category can answer for it.
_CATEGORY_FOR_KEY: dict[str, str] = {
    "todo": "proposed",
    "in_progress": "inprogress",
    "in_review": "resolved",
    "done": "completed",
}

#: Last resort for `needs_action` only, and only when the deployment configured no `state_map`:
#: the names a board gives the column a human watches. Matching a state by NAME is the thing this
#: module refuses to do everywhere else — but the two failures are not comparable. Reading "closed"
#: off a name silently marks live work as delivered; failing to find the parking column leaves a
#: parked card painted as in-progress on the board, which is the one place the park is supposed to
#: be visible. Configured `state_map` always wins, and the choice is logged when it is taken.
_NEEDS_ACTION_ALIASES = (
    "needs action", "needs attention", "blocked", "impediment", "on hold", "waiting",
    "precisa de acao", "precisa de ação", "bloqueado", "aguardando", "impedido",
)

#: Batch reads (`GET wit/workitems?ids=…`) are capped by the service at 200 ids per call.
_BATCH_LIMIT = 200


class AzureBoardsTracker:
    """Azure Boards work items. Satisfies `TrackerAdapter`."""

    def __init__(self, *, organization: str, project: str, token: str | None = None,
                 work_item_type: str = "Issue", state_map: dict[str, str] | None = None,
                 options: dict | None = None, client: AzureDevOpsClient | None = None) -> None:
        self.organization = (organization or "").strip()
        self.project = (project or "").strip()
        #: configurable because the type is the process's vocabulary: Basic calls it "Issue", Agile
        #: "User Story", Scrum "Product Backlog Item". A hardcoded one 400s on every create for
        #: exactly the deployments this is sold to.
        self.work_item_type = (work_item_type or "Issue").strip() or "Issue"
        self.state_map = {str(k): str(v) for k, v in (state_map or {}).items() if v}
        self.ado = client or AzureDevOpsClient(
            organization=organization, project=project, token=token, options=options)
        #: type name → ((state name, category), …) in the process's own workflow order. Populated
        #: on demand and refetched when a state we have never seen shows up, because a process
        #: gains a state while a worker is running and answering "unknown" for it would mean
        #: guessing whether live work is finished.
        self._states_by_type: dict[str, tuple[tuple[str, str], ...]] = {}

    # ---- plumbing -------------------------------------------------------------------------

    @staticmethod
    def work_item_id(ref: object) -> str:
        """The bare integer an Azure DevOps ref carries. Raises when it carries none.

        Refs arrive as strings and sometimes with GitHub's `#`. A ref this cannot read must not be
        passed through: the API answers a 404 about a missing *controller*, which reads as a bug in
        the platform's routing rather than as a bad ref."""
        # SPLIT FIRST (C-18). A ref may carry its own repository — `{project}/fx-dsk-ui#12` —
        # because one Azure Boards board routes cards to several repositories in the same project.
        # Without this line `work_item_id` raised on every qualified ref, so a multi-repo product
        # failed at the FIRST read of the ticket rather than doing anything wrong later. The
        # GitHub tracker has had this line since C-18; the Azure one shipped without it.
        #
        # The default repo is `""` because this is a STATIC method and the answer is discarded
        # anyway: all it needs is the number on the right of the `#`. Which repository the card
        # belongs to is the FORGE's question, and the forge already reads it off the ref itself.
        _repo, bare = split_repo_ref(str(ref), "")
        number = ref_number(bare)
        if number is None:
            raise AzureDevOpsError(
                f"{ref!r} is not an Azure DevOps work item ref — they are integers (`1234`, or "
                f"`#1234`). A `PROJ-12` style ref belongs to a different tracker."
            )
        return str(number)

    def _patch(self, ref: str, ops: list[dict]) -> dict:
        """One JSON Patch against a work item. Raises when the server refused it (contract)."""
        return self.ado.call("PATCH", f"wit/workitems/{self.work_item_id(ref)}", body=ops,
                             content_type=JSON_PATCH)

    def _description_ops(self, body: str) -> list[dict]:
        """The two ops that store a markdown body intact — used by create and by update alike.

        One helper because the pair is a single decision: the format op without the escape is a
        body cut at its first `<`, and the escape without the format op is a card showing literal
        `## Objective` to the person reading it."""
        return [
            {"op": "add", "path": "/fields/System.Description", "value": for_storage(body)},
            {"op": "add", "path": "/multilineFieldsFormat/System.Description",
             "value": "markdown"},
        ]

    def _work_item(self, ref: str, *, expand: str | None = None) -> dict:
        params = {"$expand": expand} if expand else None
        return self.ado.call("GET", f"wit/workitems/{self.work_item_id(ref)}", params=params)

    def _states(self, type_name: str, *, refresh: bool = False) -> tuple[tuple[str, str], ...]:
        """`((name, category), …)` for a work item type, in the process's own workflow order."""
        cached = self._states_by_type.get(type_name)
        if cached is not None and not refresh:
            return cached
        rows = self.ado.values(f"wit/workitemtypes/{urllib.parse.quote(type_name)}/states")
        states = tuple((str(r.get("name") or ""), str(r.get("category") or "").lower())
                       for r in rows if r.get("name"))
        self._states_by_type[type_name] = states
        return states

    def _is_closed(self, type_name: str, state_name: str) -> bool:
        """Whether the vendor considers this state finished — by CATEGORY, never by name."""
        wanted = _fold(state_name)
        was_cached = type_name in self._states_by_type
        for name, category in self._states(type_name):
            if _fold(name) == wanted:
                return category in CLOSED_CATEGORIES
        if was_cached:
            # a state this worker has never seen: the process may have gained one since we looked,
            # and only a cached table can be that stale
            for name, category in self._states(type_name, refresh=True):
                if _fold(name) == wanted:
                    return category in CLOSED_CATEGORIES
        # A state the process does not declare. Answering "closed" would make the platform ignore a
        # live card for ever; answering "open" costs at most one re-read. Neither is silent.
        log.warning("work item type %r does not declare a state named %r — reading the card as "
                    "OPEN. Its lifecycle category is what decides whether work is delivered, so "
                    "this needs looking at before the card is trusted either way",
                    type_name, state_name)
        return False

    def _state_for_key(self, key: str) -> str | None:
        """The board state this deployment means by a lifecycle key, or None when nothing answers.

        Three sources, narrowest first: what the deployment configured, what the vendor's own
        category says, and — for `needs_action` alone — the names a parking column goes by."""
        configured = self.state_map.get(key)
        if configured:
            return configured

        states = self._states(self.work_item_type)
        category = _CATEGORY_FOR_KEY.get(key)
        if category:
            # first match in workflow order: a process that has two InProgress states lists the
            # ordinary one first (Basic: Doing before Needs Action). Ambiguity is what `state_map`
            # is for, and the log below says so.
            for name, cat in states:
                if cat == category:
                    log.debug("azure devops: %r derived from the %s category → %r", key,
                              category, name)
                    return name

        if key == "needs_action":
            for name, _cat in states:
                if _fold(name) in _NEEDS_ACTION_ALIASES:
                    log.info("azure devops: no `state_map` entry for needs_action — using the "
                             "state named %r. Pin it with `state_map` if that is the wrong column",
                             name)
                    return name
        return None

    # ---- the contract ---------------------------------------------------------------------

    def get_ticket(self, ref: str) -> Ticket:
        """Through `parse_ticket_body`, exactly like GitHub and Jira — `Ticket` is the PARSED
        contract (objective, acceptance criteria, budget…), not `{id, title, body}`."""
        from openfactory.adapters.tracker.parse import parse_ticket_body

        data = self._work_item(ref)
        fields = data.get("fields") or {}
        formats = data.get("multilineFieldsFormat") or {}
        ticket = parse_ticket_body(
            id=str(data.get("id") or self.work_item_id(ref)),
            title=str(fields.get("System.Title") or ""),
            body=description_text(fields.get("System.Description"),
                                  str(formats.get("System.Description") or "html")),
            repo=self.project,
        )
        ticket.labels = [t.lower() for t in split_tags(fields.get("System.Tags"))]
        ticket.author = _identity(fields.get("System.CreatedBy"))
        ticket.state = "closed" if self._is_closed(
            str(fields.get("System.WorkItemType") or self.work_item_type),
            str(fields.get("System.State") or "")) else "open"
        return ticket

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> None:
        """Move the work item to the state this deployment means by the job's lifecycle bucket.

        NOTHING MAPPED IS A NO-OP WITH A WARNING, never a guess: an invented state name is a 400
        (`"The field 'State' contains the value 'Nope' that is not in the list"`) at best and a card
        moved somewhere nobody watches at worst. The reason is still posted either way — a caller's
        explanation dropped because the move could not be made is the silent half of a failure."""
        key = _column_key(state, needs_person=needs_person)
        target = self._state_for_key(key or "")
        if not target:
            log.warning("no azure devops state for %s (lifecycle key %r) — work item %s stays "
                        "where it is; add it to the project's tracker option `state_map`",
                        state, key, ref)
        else:
            self._patch(ref, [{"op": "add", "path": "/fields/System.State", "value": target}])
        if reason:
            self.comment(ref, f"[{state.value}] {reason}")

    def comment(self, ref: str, body: str) -> None:
        """A markdown comment. Both the api-version and the format are deliberate — see the module
        docstring: the pinned 7.1 answers 400 here, and the default html format renders a
        multi-line park explanation as one unreadable line.

        Escaped for the same reason a description is, and this route is where it bites hardest,
        because what it carries is the platform's whole voice to a person. Measured live, the
        comment `close_ticket` builds for a card closed as a duplicate of something —

            duplicate: the a<b guard was wrong

            _Closed as NOT delivered. … the card shows **Done** — the work was not done._

        is STORED as `duplicate: the a`. An unterminated `<` in a caller's own reason deletes the
        sentence that says the work did NOT happen, on a card the board now shows as Done. Eleven
        cards closed as duplicates reading downstream as delivered work is the incident behind that
        sentence; here the vendor was quietly reproducing it."""
        self.ado.call("POST", f"wit/workItems/{self.work_item_id(ref)}/comments",
                      body={"text": for_storage(body)}, params={"format": "markdown"},
                      api_version=COMMENTS_API_VERSION)

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        """`GET wit/workItems/{id}/comments` — the read half of the route `comment` already writes.

        NEWEST FIRST IS THIS VENDOR'S DEFAULT, which is the opposite of GitHub's and of Jira's.
        Measured on work item 1 of that live client project: no `order` gives `[4680928, 4680780,
        4680525, 4680457]`, i.e. 09:26 → 09:11 descending, and `order=asc` reverses it. The port
        promises oldest first, so `order` is always sent rather than inherited — a default that
        differs per provider is a default that will be wrong on the day somebody reads the list.

        `$top` bounds the truncated read at the server, and the page carries a `continuationToken`
        when there is more; the full read does not need it because `totalCount` is authoritative.

        AND THE SANITISER RUNS ON COMMENTS TOO, which is why every body goes back through
        `description_text`. A comment stores its own `format` (`html` or `markdown` — both are on
        the live item), and even the markdown ones come back entity-escaped: the platform's own
        `🤖 PR ready for review` reads out of the API as `&#129302; PR ready for review` (verified
        on work item 12). Handed to a model raw, a whole thread arrives spelling its emoji and its
        `<`s as entities, and a comment a person wrote with the toolbar arrives as HTML tags.
        """
        params: dict[str, str | int] = {"order": "asc"}
        if limit > 0:
            # newest N, then reversed here — `order=asc&$top=N` would give the OLDEST N, which is
            # the wrong end of a thread whose last word is what the caller came for
            params = {"order": "desc", "$top": int(limit)}
        try:
            page = self.ado.call("GET", f"wit/workItems/{self.work_item_id(ref)}/comments",
                                 params=params, api_version=COMMENTS_API_VERSION)
        except Exception as exc:  # noqa: BLE001 — an unread thread is None, never []
            log.warning("could not read the comments of work item %s (%s) — the caller is being "
                        "told UNREADABLE, not empty", ref, str(exc)[:200])
            return None
        raw = page.get("comments")
        if not isinstance(raw, list):
            log.warning("azure devops answered no `comments` field for %s (%r) — reading as "
                        "UNREADABLE", ref, sorted(page))
            return None
        rows = list(reversed(raw)) if limit > 0 else raw
        return [
            TicketComment(
                # `uniqueName` — the sign-in address. Same half `_identity` takes everywhere else
                # here, and unlike Jira's accountId it is legible to the person or model reading it.
                author=_identity((c or {}).get("createdBy")) or "",
                body=description_text((c or {}).get("text"),
                                      str((c or {}).get("format") or "html")),
                created_at=str((c or {}).get("createdDate") or ""),
            )
            for c in rows
        ]

    def list_tickets(self, *, state: str = "all", updated_since: str = "",
                     limit: int = 0) -> list[TicketSummary] | None:
        """WIQL for the ids, then one batched field read — the same two-call shape `find_ticket`
        uses, and for the same reason: WIQL answers with ids only, and open-versus-closed is a
        CATEGORY decision no WIQL predicate can express without hardcoding the client's state names.

        `timePrecision=true` GOES ON THE QUERY STRING OR THE WATERMARK IS A 400. A WIQL date literal
        carrying a time is refused by default — *"You cannot supply a time with the date when
        running a query using date precision"* — and the flag that lifts that is a REQUEST
        parameter, not a field of the body. Measured live, same query three ways:

            body {"query": …, "timePrecision": true}   →  400, the message above
            ?$timePrecision=true                       →  400, the message above
            ?timePrecision=true                        →  200, the six items changed since 11:00

        The `$`-prefixed spelling looks right next to `$top` and `$expand` and is wrong. This
        failure is at least LOUD — the Jira adapter's equivalent trap answers 200 with an empty
        page — but a 400 on every incremental board read is still a reader that only ever does the
        expensive thing, if it survives at all.
        """
        wanted = list_state(state)
        # THE CALLER'S LIMIT MAY NOT REACH THE QUERY WHEN A STATE FILTER IS IN PLAY, and that is a
        # correctness rule rather than a tuning one. Open-versus-closed is a CATEGORY decision taken
        # after the field read (`_summaries`), so a WIQL `$top` equal to the limit spends the whole
        # limit on cards the filter then throws away. Measured live on that client project:
        # `list_tickets(state="closed", limit=3)` asked for the three most recently changed work
        # items, all three were open, and the answer was `[]` — on a board holding five closed
        # cards. `[]` is this port's word for *I read, and there is nothing*, so a paging parameter
        # was producing this codebase's signature collapse, and doing it data-dependently: the same
        # call is right whenever the newest cards happen to be closed, which is how it survived a
        # live drive. GitHub spends its limit on the filtered set (`--state` goes to the server) and
        # so does Jira (a `statusCategory` clause inside the JQL); this is the third provider
        # agreeing with them instead of quietly under-answering.
        filtered = wanted != "all"
        ceiling = limit if (limit > 0 and not filtered) else _LIST_CEILING
        clauses = ["[System.TeamProject] = @project"]
        params: dict[str, str | int] = {"$top": ceiling}
        if updated_since:
            # the stamp is one THIS adapter produced (`System.ChangedDate`, e.g.
            # `2026-08-06T11:27:51.75Z`) and goes back in the vendor's own spelling; the quote is
            # doubled for the same reason `find_ticket` doubles one, WIQL being SQL-shaped
            clauses.append(
                f"[System.ChangedDate] >= '{str(updated_since).replace(chr(39), chr(39) * 2)}'")
            params["timePrecision"] = "true"
        query = ("SELECT [System.Id] FROM WorkItems WHERE " + " AND ".join(clauses)
                 + " ORDER BY [System.ChangedDate] DESC")
        try:
            found = self.ado.call("POST", "wit/wiql", body={"query": query}, params=params)
            ids = [str(row.get("id")) for row in (found.get("workItems") or []) if row.get("id")]
            # ONLY WHEN THE CEILING WAS OURS. A caller that asked for three and got three learned
            # nothing; a caller that asked for EVERYTHING and got exactly `_LIST_CEILING` is
            # holding a partial board and has no way to know it, because the ceiling is this
            # module's private number.
            if limit <= 0 and len(ids) >= ceiling:
                log.warning("%s answered with %d work items, which is this adapter's own ceiling — "
                            "the board is larger than what the caller is about to judge",
                            self.project, ceiling)
            out = self._summaries(ids, wanted=wanted, limit=limit)
        except Exception as exc:  # noqa: BLE001 — an unread board is None, never []
            log.warning("could not list the work items of %s (%s) — the caller is being told "
                        "UNREADABLE, not empty", self.project, str(exc)[:200])
            return None

        # A SHORT ANSWER THAT IS OUR OWN FAULT SAYS SO. The filtered walk stops at `_LIST_CEILING`
        # cards scanned, so a caller that asked for twenty closed cards and got four may be holding
        # four because the board has four, or because the ceiling arrived first — and only this
        # module knows which, the ceiling being its own number.
        if filtered and 0 < limit and len(out) < limit and len(ids) >= ceiling:
            log.warning("found only %d of the %d %s work items asked for inside this adapter's own "
                        "ceiling of %d scanned cards — the answer is short because the read was "
                        "bounded, not because the board is", len(out), limit, wanted, ceiling)
        return out

    def _summaries(self, ids: list[str], *, wanted: str, limit: int) -> list[TicketSummary]:
        """The board rows for `ids`, in the QUERY's order, keeping only the wanted lifecycle state.

        Chunked because `GET wit/workitems?ids=…` is capped by the service at 200 ids per call — a
        201st is not truncated, it is a 400 — so a board bigger than that has to arrive in pieces.

        THE FILTER RUNS INSIDE THE WALK AND THE LIMIT COUNTS SURVIVORS. Both halves are the fix to
        the same defect: filtering afterwards let the limit be spent on cards that were then thrown
        away (see `list_tickets`), and stopping early is what keeps the corrected version from
        reading every card up to the ceiling for a caller who asked for three. So a filtered read
        costs one request per 200 cards SCANNED rather than per 200 returned — bounded by
        `_LIST_CEILING`, and it is the price of an answer that is not quietly short.
        """
        out: list[TicketSummary] = []
        for start in range(0, len(ids), _BATCH_LIMIT):
            chunk = ids[start:start + _BATCH_LIMIT]
            rows = self.ado.values("wit/workitems", params={
                "ids": ",".join(chunk), "fields": _LIST_FIELDS})
            by_id = {str(r.get("id")): r for r in rows}
            for number in chunk:  # WIQL's order is what the query asked for; the batch's is not
                row = by_id.get(number)
                if row is None:
                    # A work item WIQL named and the batch read did not return. Skipping it
                    # silently would shrink the board by exactly the cards somebody just lost
                    # access to.
                    log.warning("work item %s was listed by the query and not returned by the "
                                "field read — it is missing from the board this caller sees",
                                number)
                    continue
                card = self._summary(row)
                if wanted != "all" and (card.state == "closed") is not (wanted == "closed"):
                    continue
                out.append(card)
                if 0 < limit <= len(out):
                    return out
        return out

    def _summary(self, row: dict) -> TicketSummary:
        fields = row.get("fields") or {}
        formats = row.get("multilineFieldsFormat") or {}
        type_name = str(fields.get("System.WorkItemType") or self.work_item_type)
        state_name = str(fields.get("System.State") or "")
        closed = self._is_closed(type_name, state_name)
        return TicketSummary(
            ref=str(row.get("id") or fields.get("System.Id") or ""),
            title=str(fields.get("System.Title") or ""),
            body=description_text(fields.get("System.Description"),
                                  str(formats.get("System.Description") or "html")),
            state="closed" if closed else "open",
            # THE SAME CATEGORY THE WRITE SIDE USES. `close_ticket(delivered=False)` looks for a
            # `Removed` state; this reads one back. Deriving delivery from `System.Reason` instead
            # would be reading a sentence the vendor composes ("Moved out of state Needs Action"),
            # and deriving it from the state NAME is what this module refuses everywhere.
            state_reason=self._closed_reason(type_name, state_name) if closed else "",
            labels=[t.lower() for t in split_tags(fields.get("System.Tags"))],
            assignees=[who] if (who := _identity(fields.get("System.AssignedTo"))) else [],
            updated_at=str(fields.get("System.ChangedDate") or ""),
        )

    def _closed_reason(self, type_name: str, state_name: str) -> str:
        """`"not_planned"` for the Removed category, `"completed"` otherwise.

        A process with no Removed state (Basic, for an Issue — verified on the live board) can only
        ever answer `"completed"`, and `close_ticket` already says so in the comment it leaves. The
        two halves have to agree or a card the platform closed as NOT delivered comes back reading
        as delivered work, which is the eleven-duplicates incident with the arrow reversed."""
        wanted = _fold(state_name)
        for name, category in self._states(type_name):
            if _fold(name) == wanted:
                return "not_planned" if category == "removed" else "completed"
        return "completed"

    def ticket_url(self, ref: str) -> str:
        """`https://dev.azure.com/{org}/{project}/_workitems/edit/{id}` — where a human opens it.

        The API's own `_links.html.href` uses the project's GUID; this is the same page addressed by
        the name the person reading the link recognises."""
        try:
            number = self.work_item_id(ref)
        except AzureDevOpsError:
            # the contract allows an empty URL when the provider cannot say, and a caller pasting
            # a broken link into an alert is worse than one printing the bare ref
            log.warning("cannot build an azure devops URL for the ref %r", ref)
            return ""
        org = urllib.parse.quote(self.organization)
        project = urllib.parse.quote(self.project)
        return f"https://dev.azure.com/{org}/{project}/_workitems/edit/{number}"

    def budget(self) -> BudgetAnswer:
        """Azure DevOps meters by TSTU per identity and reports it only in response headers of the
        calls that spent it — there is no endpoint that says what is left before a call is made.
        The declared sentinel, rendered as a state of its own; never a `None` that reads as ok."""
        return NOT_REPORTED

    def person(self, ref: str) -> dict:
        """See `TrackerAdapter.person`. NO CALL IS MADE: on Azure DevOps the ref IS the answer.

        `assignees()` hands out `uniqueName`, the sign-in address — which is an EMAIL, the
        strongest signal a directory match has. Spending an identity API call to rediscover it
        would be a round trip per mention for a fact already in hand.

        THE DISPLAY NAME IS NOT RECOVERABLE FROM THE REF and is left empty rather than guessed at
        from the address: `a.silva@acme.com` is not a name a person recognises, and the caller's
        match treats a single word as a coin toss for precisely this reason.
        """
        who = (ref or "").strip()
        if not who:
            return {}
        return {"id": who, "name": "", "email": who.lower() if "@" in who else ""}

    def assignees(self, ref: str) -> list[str]:
        """Azure DevOps has ONE assignee; the protocol speaks in lists, so this is a list of at most
        one. Callers already treat the first entry as the owner to return a parked ticket to.

        The identity comes back as an object; `uniqueName` (the sign-in address) is the half that
        can be written back."""
        fields = (self._work_item(ref).get("fields") or {})
        who = _identity(fields.get("System.AssignedTo"))
        return [who] if who else []

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        """Replace the assignee. An empty list clears the field, which is how a parked ticket with
        no previous owner is handed back to nobody in particular rather than to the bot."""
        self._patch(ref, [{"op": "add", "path": "/fields/System.AssignedTo",
                           "value": logins[0] if logins else ""}])

    @staticmethod
    def ado_tag(label: str) -> str:
        """The platform's label in the shape THIS provider accepts.

        Azure DevOps refuses any character outside the BMP — the platform's own marker
        `🤖 sdlc-working` is rejected whole, with or without the space (TF401407, seen live on
        every spelling). It keeps the space that Jira rejects, and it treats `;` as the separator
        between tags, so a label containing one would silently become two."""
        kept = "".join(" " if ch == ";" else ch for ch in (label or "") if ord(ch) <= 0xFFFF)
        return " ".join(kept.split()) or "openfactory"

    def add_label(self, ref: str, label: str) -> None:
        """Add a tag. `add` on `System.Tags` unions with what is there (verified live), so this is
        one call and not a read-merge-write — which would be a lost-update race with whoever is
        editing tags in the browser."""
        self._patch(ref, [{"op": "add", "path": "/fields/System.Tags",
                           "value": self.ado_tag(label)}])

    def remove_label(self, ref: str, label: str) -> None:
        """Remove a tag. There is no remove op for `System.Tags`, so the remaining set is written
        back with `replace`; a tag the item does not carry is a no-op with no write at all."""
        wanted = self.ado_tag(label).lower()
        fields = (self._work_item(ref).get("fields") or {})
        current = split_tags(fields.get("System.Tags"))
        remaining = [t for t in current if t.lower() != wanted]
        if len(remaining) == len(current):
            return
        self._patch(ref, [{"op": "replace", "path": "/fields/System.Tags",
                           "value": "; ".join(remaining)}])

    def create_ticket(self, *, title: str, body: str) -> str:
        """Create a work item in the project's intake state and return its ref.

        The description is written AS MARKDOWN (`multilineFieldsFormat`): the bodies this platform
        writes are markdown, and stored as html a person reads `## Objective` as literal text."""
        created = self.ado.call(
            "POST", f"wit/workitems/${urllib.parse.quote(self.work_item_type)}",
            content_type=JSON_PATCH,
            body=[{"op": "add", "path": "/fields/System.Title", "value": title},
                  *self._description_ops(body)])
        number = created.get("id")
        if not number:
            # a create that answered 200 without an id leaves a card nobody can address; the
            # splitter would file another one on the next pass
            raise AzureDevOpsError(
                f"azure devops accepted the work item {title!r} but returned no id: {created!r}")
        return str(number)

    def find_ticket(self, *, title: str) -> str | None:
        """Ref of an OPEN work item with exactly this title, or None (splitter idempotency).

        Two calls on purpose. WIQL answers with ids only and its `=` is case-insensitive, so the
        exact comparison and the open/closed decision both need the fields — and the second is a
        CATEGORY decision, which no WIQL predicate can express without hardcoding the client's
        state names."""
        # WIQL is SQL-shaped: a quote inside a literal is doubled. Unescaped, a title like
        # `an O'Brien "quoted" title` answers 400 ("Expecting closing quote") — verified live — and
        # the splitter's one guard against filing a duplicate would be the thing that failed.
        escaped = (title or "").replace("'", "''")
        query = ("SELECT [System.Id] FROM WorkItems "
                 "WHERE [System.TeamProject] = @project "
                 f"AND [System.Title] = '{escaped}' ORDER BY [System.Id] DESC")
        found = self.ado.call("POST", "wit/wiql", body={"query": query})
        ids = [str(row.get("id")) for row in (found.get("workItems") or []) if row.get("id")]
        if not ids:
            return None
        if len(ids) > _BATCH_LIMIT:
            log.warning("%d work items share the title %r — only the %d most recent are checked",
                        len(ids), title, _BATCH_LIMIT)
            ids = ids[:_BATCH_LIMIT]
        rows = self.ado.values("wit/workitems", params={
            "ids": ",".join(ids),
            "fields": "System.Id,System.Title,System.State,System.WorkItemType"})
        for row in rows:
            fields = row.get("fields") or {}
            if str(fields.get("System.Title") or "").strip() != (title or "").strip():
                continue
            if self._is_closed(str(fields.get("System.WorkItemType") or self.work_item_type),
                               str(fields.get("System.State") or "")):
                continue
            return str(row.get("id"))
        return None

    def update_body(self, ref: str, body: str) -> None:
        """Replace the description — the one destructive write on this port, and it rewrites what
        somebody else wrote. Stored as markdown for the same reason `create_ticket` does."""
        self._patch(ref, self._description_ops(body))

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        """Close the work item with a final comment.

        CLOSED IS NOT DELIVERED. Azure DevOps says the difference with the `Removed` category, and
        `delivered=False` looks for it. The Basic process has no Removed state for an Issue —
        verified on the live board — so on such a process the card can only land in the Completed
        state, and the comment SAYS the work did not happen. Silence there is precisely how eleven
        cards closed as duplicates came back downstream as delivered work."""
        states = self._states(self.work_item_type)
        target = None
        if not delivered:
            target = next((name for name, cat in states if cat == "removed"), None)
        if target is None:
            target = self._state_for_key("done")
        if target is None:
            raise AzureDevOpsError(
                f"work item type {self.work_item_type!r} declares no state this platform can close "
                f"into (states: {[n for n, _ in states] or 'none readable'}). Map one with the "
                f"project's tracker option `state_map`.")

        note = reason or ""
        if not delivered and not any(cat == "removed" for _n, cat in states):
            note = (note + "\n\n" if note else "") + (
                f"_Closed as NOT delivered. This process has no Removed state, so the card shows "
                f"**{target}** — the work was not done._")
        if note:
            self.comment(ref, note)
        self._patch(ref, [{"op": "add", "path": "/fields/System.State", "value": target}])

    # ---- optional linkage (ADR-0013 D3) ---------------------------------------------------

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        """Azure DevOps's native hierarchy link, written from the CHILD (`Hierarchy-Reverse` is
        "my parent"). Best-effort by contract: a process whose types forbid the pairing — Basic
        allows Issue under Issue, which is not true of every process — still splits correctly
        through the deterministic titles."""
        try:
            parent = self._work_item(parent_ref)
            self._patch(child_ref, [{
                "op": "add", "path": "/relations/-",
                "value": {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": parent["url"]},
            }])
        except Exception as exc:  # noqa: BLE001 — the split works without native linkage
            log.info("could not link %s under %s (%s) — the split still holds through titles",
                     child_ref, parent_ref, exc)

    def children_of(self, parent_ref: str) -> list[str]:
        """Refs of the work items linked under this one."""
        try:
            item = self._work_item(parent_ref, expand="relations")
        except Exception as exc:  # noqa: BLE001 — "unknown" must never read as "no children"
            log.warning("could not list the children of %s (%s) — the splitter will fall back to "
                        "matching by title, which is correct but slower", parent_ref, exc)
            return []
        out: list[str] = []
        for rel in item.get("relations") or []:
            if str(rel.get("rel") or "") != "System.LinkTypes.Hierarchy-Forward":
                continue
            child = ref_number(str(rel.get("url") or "").rstrip("/").rsplit("/", 1)[-1])
            if child is not None:
                out.append(str(child))
        return out


# ---- shapes this vendor answers in --------------------------------------------------------

def split_tags(raw: object) -> list[str]:
    """`System.Tags` is ONE semicolon-separated string, not a list; an item with no tags has no
    field at all rather than an empty one."""
    return [part.strip() for part in str(raw or "").split(";") if part.strip()]


def for_storage(text: str) -> str:
    """Text as Azure DevOps's sanitiser will leave it alone — the write half of the round trip.

    `quote=False`: the sanitiser leaves `"` and `'` untouched (verified), so escaping them would
    only put `&quot;` inside code fences, where a markdown renderer shows entities literally. It is
    `&`, `<` and `>` that are rewritten, and `&` has to go first — which `html.escape` does — or the
    escape of a body that already contains `&lt;` would not survive its own round trip."""
    return html.escape(str(text or ""), quote=False)


def _identity(value: object) -> str | None:
    """The writable half of an Azure DevOps identity — `uniqueName` is the sign-in address, and it
    is what `System.AssignedTo` accepts back on a write. `displayName` is not."""
    if isinstance(value, dict):
        return str(value.get("uniqueName") or "") or None
    return str(value or "") or None


def _fold(name: str) -> str:
    """A state name reduced to what it says: lowercase, unpadded, single-spaced."""
    return " ".join(str(name or "").lower().split())


class _HtmlToMarkdown(HTMLParser):
    """Azure DevOps's stored HTML back into the markdown `parse_ticket_body` reads.

    Not a general HTML renderer: it recovers the four things a ticket body carries — headings,
    bullets, line breaks and text. Both authoring styles have to survive. Somebody who types
    `## Objective` into the browser editor gets `<div>## Objective</div>`, and somebody who uses the
    toolbar's Heading 2 gets `<h2>Objective</h2>`; both must come out as a markdown heading, because
    the alternative is the platform telling a ticket's author that their ticket has no objective."""

    _HEADINGS = {f"h{n}": n for n in range(1, 7)}
    _BLOCKS = {"div", "p", "br", "tr", "li", "ul", "ol", "table", "blockquote", "pre", "hr",
               "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def _newline(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ARG002 — attributes carry nothing
        level = self._HEADINGS.get(tag)
        if level:
            self._newline()
            self._parts.append("#" * level + " ")
        elif tag == "li":
            self._newline()
            self._parts.append("- ")
        elif tag in self._BLOCKS:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HEADINGS or tag in self._BLOCKS:
            self._newline()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        # `\xa0` because `&nbsp;` decodes to it, and a heading that starts with one is not a
        # heading any more — the marker survives while the section it names disappears.
        lines = [line.replace("\xa0", " ").rstrip()
                 for line in "".join(self._parts).replace("\r\n", "\n").split("\n")]
        out: list[str] = []
        for line in lines:
            if not line and out and not out[-1]:
                continue  # runs of empty block tags collapse to one blank line
            out.append(line)
        return "\n".join(out).strip()


def description_text(raw: object, stored_format: str = "html") -> str:
    """A work item's description as the markdown the platform's parser expects.

    `multilineFieldsFormat` is the vendor telling us which it stored; anything that is not markdown
    goes through the converter, which is a no-op on plain text.

    Either way the entities come off. The sanitiser escapes what it stores whatever the declared
    format is (`A & B` reads back `A &amp; B`), so a markdown body handed to `parse_ticket_body`
    raw would put `&amp;` and `&lt;` into a criterion, a prompt and a client's screen. The html
    branch already does this — `convert_charrefs` — so this is the two branches agreeing rather
    than a new rule."""
    body = str(raw or "")
    if not body or _fold(stored_format) == "markdown":
        return html.unescape(body)
    parser = _HtmlToMarkdown()
    parser.feed(body)
    parser.close()
    return parser.text()

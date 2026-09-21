"""Jira Cloud as a tracker — the second implementation the seam exists for.

Written against the same `TrackerAdapter` protocol as GitHub, which is the whole point: nothing
outside this file learns that a deployment keeps its tickets in Jira. The pilot runs Python on
GitHub; the product is sold to clients whose tickets live here instead, and that has to be
structurally true before the first of them arrives.

REFS ARE THE PROVIDER'S OWN. GitHub says `#412`, Jira says `CONT-412` — the framework passes refs
around opaquely and never parses them, so both work unchanged. Where a caller must render one for a
human, it prints what the tracker gave it.

STATE MAPPING IS CONFIGURED, NOT GUESSED. Every Jira project has its own workflow, and a transition
this adapter invented would either fail or move a card somewhere nobody expects. `status_map` in the
project's tracker options says which Jira status each JobState means; an unmapped state is a no-op
with a warning, never a wrong transition.

CLOSED IS NOT DELIVERED, AND JIRA SAYS THE DIFFERENCE WITH A RESOLUTION (#203). `Done` against
`Won't Do` / `Duplicate` / `Cannot Reproduce` is a field set on the closing transition — and it is
the SITE's list, named by its administrator and localised with everything else, carried only by a
transition whose screen has the field. So it is configured exactly as the statuses are, and there is
no default that pretends every site has one:

    tracker:
      kind: jira
      options:
        status_map: '{"todo": "A Fazer", "done": "Concluído"}'
        not_delivered_resolution: "Won't Do"      # the site's own name for it; unset = none

`close_ticket(delivered=False)` sends that resolution with the transition and `list_tickets` reads
it back as `not_planned`. Unset, or refused by the site, the card is still closed, a note on it says
the work was withdrawn, a log line names this option — and the card READS AS DELIVERED downstream,
because nothing Jira holds says otherwise. `close_ticket` says why that is not papered over.

…OR WITH A STATUS, AND THE SITE DECIDES WHICH (2026-09-19). A resolution travels only on a
transition whose screen has the field, and Atlassian documents team-managed projects as having no
such screen — for those the paragraph above was the ONLY path, and every withdrawn card read as
delivered. Such a site says it with a status of its own in the Done category (`Cancelled`,
`Won't do`, `Cancelado`), and that is declared the same way, with the same absence of a default:

        not_delivered_status: "Cancelado"         # a status in the Done category; unset = none

The withdrawn close is then the bare transition into that status, and a closed card sitting in it
reads as `not_planned` whoever put it there. It is its own option and not a `status_map` key,
because that map is keyed by the states a JOB can be in, and "not delivered" is a word of the
close, never a state. A deployment may name both; `close_ticket` says which is tried first.

AUTH: Jira Cloud basic auth with an API token (`email` + token). The token arrives the same way
every other credential does — from the deployment, never from the client's repository.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from openfactory.contracts import JobState, Ticket

log = logging.getLogger("openfactory.tracker.jira")


class JiraRefused(RuntimeError):
    """Jira answered a call with an HTTP error. The status code is KEPT, not only printed.

    A `RuntimeError` still, so every caller that parks or diagnoses on one keeps working. The code
    is what lets `close_ticket` tell a site refusing ONE FIELD (400 — the transition's screen does
    not carry `resolution`, or the site has no resolution of that name) from a credential that
    expired or a site that is down, which must keep raising."""

    def __init__(self, message: str, *, code: int) -> None:
        super().__init__(message)
        self.code = code


#: How many issues one `search/jql` page asks for. Jira's own ceiling for this endpoint is 100.
_PAGE = 100

#: How many pages `list_tickets` will walk for a single answer. `search/jql` is token-paginated and
#: reports completeness with `isLast` — it does NOT return a total (verified: the response carries
#: exactly `isLast`, `issues` and, when there is more, `nextPageToken`) — so "how big is this board"
#: is a question that can only be answered by walking it. This bounds the walk; hitting it is
#: logged, because a board read as smaller than it is is the failure this whole port guards.
_MAX_PAGES = 20

# THE lifecycle table lives in the CONTRACT now (C-14): both adapters answer the same four
# questions, and two copies of the bucketing is how they drift. `_column_key` stays as this
# module's name for it — the vendor-neutrality test reads it here on purpose.
from openfactory.adapters.tracker.base import (  # noqa: E402
    NOT_REPORTED,
    BudgetAnswer,
    TicketComment,
    TicketSummary,
    list_state,
)
from openfactory.adapters.tracker.base import column_key as _column_key  # noqa: E402


def _jql_since(stamp: str) -> str:
    """An ISO-8601 timestamp as a JQL date literal — a RELATIVE one, `"-90m"`.

    THE PROVIDER'S OWN TIMESTAMP IS POISON IN ITS OWN QUERY LANGUAGE, and it fails in the worst
    possible way. `list_tickets` is handed back a value this adapter produced — Jira answers
    `updated` as `2026-08-05T15:07:22.794+0100` — and JQL does not accept that shape. It does not
    reject it either. Measured live against a production client's Jira Cloud site, same project,
    same afternoon:

        updated >= "2026-08-05 11:00"        →  200, DAR-3, DAR-2
        updated >= "2026-08-05T11:00:00Z"    →  200, []
        updated >= "2026-08-05T11:00"        →  200, []
        updated >= "-3d"                     →  200, DAR-3, DAR-2, DAR-1

    HTTP 200, no error message, an empty page. A board reader whose watermark went through
    untouched would report "nothing changed" on every refresh for ever, and every caller of
    `product/board.py` treats a clean empty answer as a fact about the board. That is this
    codebase's signature collapse — unreadable presenting as empty — arriving through the syntax of
    a date.

    So the absolute form is never built. `'yyyy-MM-dd HH:mm'` is the shape JQL wants, but bare of a
    zone it is read in the API USER'S timezone, which is a per-account setting nothing here can
    see; converting a UTC instant into it is wrong by that offset, and the direction of the error
    decides between re-reading a few cards twice and never seeing them again. A relative window
    carries no timezone at all, so it cannot be wrong in either direction.

    ROUNDED UP, WITH A MINUTE OF SLACK, because JQL's finest relative unit is the minute and an
    over-wide window costs a few rows the caller was going to merge by ref anyway, while a
    too-narrow one silently drops the ticket somebody just touched.

    A stamp that cannot be parsed DROPS THE CLAUSE — the read becomes a full one, logged. The other
    branch (pass it through and hope) is the silent-empty above; a full read is merely expensive.
    """
    text = str(stamp or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        log.warning("the watermark %r is not a timestamp this adapter can convert into JQL — "
                    "reading the WHOLE board instead of the changes. That is slower and correct; "
                    "passing it through would have matched nothing at all", stamp)
        return ""
    if moment.tzinfo is None:
        # a naive stamp is treated as UTC rather than as local time: the worker's timezone is not
        # the client's, and guessing local is how a window comes out hours short on one deployment
        moment = moment.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - moment).total_seconds()
    if elapsed < 0:
        # a watermark from the future means somebody's clock disagrees; the safe reading is "since
        # right about now", never a negative window, which JQL would read as a date in the future
        log.warning("the watermark %r is in the future — reading the last minute rather than "
                    "trusting it", stamp)
        return "-1m"
    return f"-{int(elapsed // 60) + 1}m"


class JiraTracker:
    """Jira Cloud REST v3. Satisfies `TrackerAdapter`."""

    def __init__(self, *, site: str, project_key: str, email: str, token: str | None = None,
                 status_map: dict[str, str] | None = None, issue_type: str = "Task",
                 not_delivered_resolution: str = "", not_delivered_status: str = "",
                 language: str | None = None, scope_jql: str = "") -> None:
        self.site = site.rstrip("/")
        self.project_key = project_key
        self.email = email
        self.token = token
        self.status_map = status_map or {}
        #: configurable because Jira localises issue types: a pt-BR site calls it "Tarefa", and a
        #: hardcoded "Task" would 400 on every create for exactly the clients this is sold to
        self.issue_type = issue_type or "Task"
        #: THIS SITE's name for the resolution that means "closed, and the work was not done" —
        #: `Won't Do`, `Não será feito`, whatever its administrator called it. `""` is the honest
        #: default and it is not a gap: a literal here would be a name most sites do not have, sent
        #: on every withdrawn close and refused on every one.
        self.not_delivered_resolution = str(not_delivered_resolution or "").strip()
        #: …and its name for the STATUS that means the same, on a site that says it with a column
        #: of its own rather than with a field (a team-managed project has no screen to carry a
        #: resolution). `""` for the same reason: `Cancelled` is a name most sites do not have.
        self.not_delivered_status = str(not_delivered_status or "").strip()
        #: The PROJECT's language, for the one sentence this row writes to a person in its own
        #: name — the note on a card it could not record as not delivered. Everything else it
        #: posts was composed by its caller, already in that language.
        self.language = language
        #: Extra JQL ANDed onto every board read, so a shared Jira project only exposes the
        #: issues meant for the factory (e.g. `labels = openfactory`). Empty means the whole
        #: project.
        self.scope_jql = scope_jql or ""

    # ---- plumbing -------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        raw = f"{self.email}:{self.token or ''}".encode()
        return {
            "Authorization": f"Basic {base64.b64encode(raw).decode()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _call(self, method: str, path: str, payload: dict | None = None, *,
              api: str = "api/3") -> dict:
        """One REST call. Raises on transport failure so the caller's own park/diagnose path sees
        it — a tracker that swallowed its errors would let a job report success having written
        nothing.

        `api` names the REST family under `/rest/` — `api/3` for everything this tracker did until
        the board learned to rank, `agile/1.0` for the rank endpoint, which lives nowhere else."""
        url = f"{self.site}/rest/{api.strip('/')}/{path.lstrip('/')}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:  # noqa: S310 — fixed https site
                body = resp.read().decode() or "{}"
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:300] if hasattr(exc, "read") else ""
            raise JiraRefused(f"jira {method} {path} failed: {exc.code} {detail}",
                              code=int(exc.code)) from exc

    @staticmethod
    def _text(adf: dict | None) -> str:
        """Jira stores rich text as Atlassian Document Format; the framework wants plain text.

        Walks the tree collecting text nodes rather than assuming a shape — a description written
        with tables or panels must not come back empty, because that empty body is what the sizing
        gate would judge."""
        out: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                # Headings and list items keep their markdown shape, because the sizing gate looks
                # for `## Acceptance criteria` and `- ` bullets. Flattened to bare text, a ticket
                # written in Jira's own editor reads as having no sections at all.
                kind = node.get("type")
                if kind in ("heading", "listItem"):
                    inner: list[str] = []

                    def collect(n):
                        if isinstance(n, dict):
                            if n.get("type") == "text":
                                inner.append(str(n.get("text", "")))
                            for c in n.get("content") or []:
                                collect(c)

                    collect(node)
                    level = int((node.get("attrs") or {}).get("level", 2))
                    prefix = "#" * level + " " if kind == "heading" else "- "
                    out.append(prefix + " ".join(inner).strip())
                    return
                if node.get("type") == "text":
                    out.append(str(node.get("text", "")))
                for child in node.get("content") or []:
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(adf or {})
        return "\n".join(out).strip()

    @staticmethod
    def _adf(text: str) -> dict:
        """Plain text as ADF — one paragraph per line, which is what Jira's API accepts."""
        return {
            "type": "doc", "version": 1,
            "content": [
                {"type": "paragraph",
                 "content": ([{"type": "text", "text": line}] if line else [])}
                for line in (text or "").splitlines() or [""]
            ],
        }

    # ---- the contract ---------------------------------------------------------------------

    def get_ticket(self, ref: str) -> Ticket:
        """Through `parse_ticket_body`, exactly like GitHub — because `Ticket` is not
        `{id,title,body}`: it is the parsed contract (objective, acceptance criteria, budget…)
        that the sizing gate and the executor read. The first version constructed `Ticket(...,
        body=...)` directly — a field the model does not have, missing two required ones — so
        EVERY Jira job would have died on its first step with a ValidationError, and the audit
        found it because `runtime_checkable` checks method NAMES, never what they build."""
        from openfactory.adapters.tracker.parse import parse_ticket_body

        data = self._call("GET", f"issue/{ref}")
        fields = data.get("fields") or {}
        ticket = parse_ticket_body(
            id=str(data.get("key", ref)),
            title=str(fields.get("summary") or ""),
            body=self._text(fields.get("description")),
            repo=self.project_key,
        )
        # Jira has no `open`/`closed` — it has a workflow status, whose CATEGORY is the vendor's
        # own answer to "is this finished". `statusCategory.key == "done"` is that, and reading
        # the category rather than the status NAME is what keeps this working on a board whose
        # done column is called "Donee", "Entregue" or anything else a client chose.
        category = (((fields.get("status") or {}).get("statusCategory")) or {}).get("key")
        ticket.state = "closed" if str(category or "").lower() == "done" else "open"
        # `reporter` is who the card is FOR — Jira lets it be set to somebody other than the
        # account that clicked Create, which is `creator`, and the park escalation and the
        # requester lookup both want the former. `displayName`, for the reason `comments` gives:
        # this field is read by a person or a model, never written back, and an accountId is
        # legible to neither. GitHub and Azure Boards both answer None when the vendor did not
        # say; the third vendor answered None ALWAYS until 2026-09-06 (the slice-2 critique), so
        # a Jira card could never be routed back to whoever asked for it.
        ticket.author = (_display(fields.get("reporter")) or _display(fields.get("creator"))
                         or None)
        return ticket

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> bool | None:
        """Transition the issue, if this deployment mapped the state.

        UNMAPPED IS A NO-OP WITH A WARNING, never a guess: every Jira project has its own workflow,
        and an invented transition either fails or moves the card somewhere nobody expects."""
        match = self._transition_for(ref, state, needs_person=needs_person)
        if match is None:
            return False
        self._call("POST", f"issue/{ref}/transitions", {"transition": {"id": match["id"]}})
        if reason and state == JobState.NEEDS_REFINEMENT:
            self.comment(ref, reason)
        return True

    def _transition_for(self, ref: str, state: JobState | None = None, *,
                        needs_person: bool | None = None, status: str = "") -> dict | None:
        """The transition that takes `ref` to the status this deployment mapped `state` to, or
        `None` with the warning that says which of the two things is missing. ONE lookup, because a
        close that records the work as withdrawn posts the same transition `set_state` does with
        one field more — and a second copy of "how a status is found" is how the two would come to
        disagree about where Done is.

        `status` IS A NAME THE DEPLOYMENT DECLARED OUTRIGHT, for the one move that is not a job's
        state (`not_delivered_status`): it skips the map and is found by the same match, so the
        withdrawn close and `set_state` cannot disagree about a name's case either."""
        target = str(status or "").strip()
        if not target:
            key = _column_key(state, needs_person=needs_person)
            target = self.status_map.get(key or "", "")
            if not target:
                log.warning("no jira status mapped for %s (status_map key %r) — the issue stays "
                            "where it is; add the mapping in the project's tracker options",
                            state, key)
                return None
        transitions = (self._call("GET", f"issue/{ref}/transitions").get("transitions") or [])
        match = next((t for t in transitions
                      if str((t.get("to") or {}).get("name", "")).lower() == target.lower()
                      or str(t.get("name", "")).lower() == target.lower()), None)
        if match is None:
            log.warning("jira issue %s has no transition to %r from its current status — not "
                        "forcing a workflow it does not have", ref, target)
            return None
        return match

    def _refusal_of(self, ref: str, move: dict) -> str:
        """Post one transition of a withdrawn close: `""` when Jira took it, Jira's OWN WORDS when
        it answered 400. ONE PLACE, because both words a deployment can name for "not delivered"
        meet the same rule: a 400 is the site refusing THIS move — a field its screen does not
        carry, a name it does not have, a validator on the workflow — and the close goes on to the
        next way of saying it. Any other failure — a credential, a 5xx, a transport error — raises
        as it always did, and nothing is retried."""
        try:
            self._call("POST", f"issue/{ref}/transitions", move)
        except JiraRefused as exc:
            if exc.code != 400:
                raise
            return str(exc)[:200]
        return ""

    def comment(self, ref: str, body: str) -> None:
        self._call("POST", f"issue/{ref}/comment", {"body": self._adf(body)})

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        """`GET issue/{key}/comment`, which answers OLDEST FIRST and — unlike `search/jql` — still
        carries a `total`, so completeness here is a comparison rather than a walk.

        `limit` is served by asking Jira for `orderBy=-created` and reversing, not by fetching
        everything and slicing: a ticket that has been argued over for a month is the exact one the
        tech-lead asks about, and pulling its whole history to keep four comments is a page of ADF
        per comment for nothing.
        """
        try:
            if limit > 0:
                page = self._call(
                    "GET", f"issue/{ref}/comment?maxResults={int(limit)}&orderBy=-created")
                # newest first on the wire, oldest first out of the port (the contract's promise)
                rows = list(reversed(page.get("comments") or []))
            else:
                rows = self._all_comments(ref)
        except Exception as exc:  # noqa: BLE001 — an unread thread is None, never []
            log.warning("could not read the comments of %s (%s) — the caller is being told "
                        "UNREADABLE, not empty", ref, str(exc)[:200])
            return None
        return [
            TicketComment(
                # `displayName`, deliberately — see `TicketComment.author`. Jira's writable
                # identity is an opaque accountId, and this field is read by a model deciding
                # whether a human already told it something.
                author=str((c.get("author") or {}).get("displayName") or ""),
                body=self._text(c.get("body")),
                created_at=str(c.get("created") or ""),
            )
            for c in rows
        ]

    def _all_comments(self, ref: str) -> list[dict]:
        """Every comment, paged. `total` is authoritative on this endpoint; the page-count cap is
        the backstop for a server that keeps answering non-empty pages past it."""
        rows: list[dict] = []
        start = 0
        for _page in range(_MAX_PAGES):
            page = self._call("GET", f"issue/{ref}/comment?startAt={start}&maxResults={_PAGE}")
            got = page.get("comments") or []
            rows.extend(got)
            start += len(got)
            total = page.get("total")
            if not got or not isinstance(total, int) or start >= total:
                return rows
        log.warning("stopped reading the comments of %s after %d pages — the answer is the oldest "
                    "%d and there are more", ref, _MAX_PAGES, len(rows))
        return rows

    def ticket_url(self, ref: str) -> str:
        """`<site>/browse/<KEY>` — Jira's own shape. The park alert used to hand a Jira operator
        a github.com link to an issue that never existed there."""
        key = (ref or "").strip().lstrip("#")
        return f"{self.site}/browse/{key}" if key else ""

    def budget(self) -> BudgetAnswer:
        """Jira Cloud publishes no per-credential quota a probe could read (its throttling is
        per-tenant and answered with a 429 at the moment it bites), so the honest answer is the
        declared sentinel — a state the floor and the doctor render as "no budget on this vendor",
        never a `None` that reads as fine."""
        return NOT_REPORTED

    def person(self, ref: str) -> dict:
        """`GET user?accountId=…` — see `TrackerAdapter.person`.

        AN `accountId` IS OPAQUE AND MEANS NOTHING OUTSIDE JIRA, which is exactly why this method
        exists: the mention path used to hand one to `gh api users/<id>` and get a 404.

        `emailAddress` IS OFTEN ABSENT, and that is a workspace's privacy setting rather than an
        error — Atlassian omits the field unless the caller has the scope for it. The name alone
        still identifies the person to a reader and still feeds a conservative match, so a partial
        answer is returned rather than nothing.
        """
        account = (ref or "").strip()
        if not account:
            return {}
        try:
            data = self._call("GET", f"user?accountId={urllib.parse.quote(account)}")
        except Exception as exc:  # noqa: BLE001 — a mention is never worth failing a message for
            log.info("could not look up %s in Jira (%s) — they will be named, not notified",
                     account, exc)
            return {"id": account}
        return {"id": account, "name": data.get("displayName") or "",
                "email": (data.get("emailAddress") or "").lower()}

    def assignees(self, ref: str) -> list[str]:
        """Jira has ONE assignee, the protocol speaks in lists — so this is a list of at most one.
        Callers already treat the first entry as the owner, so the semantics survive."""
        fields = (self._call("GET", f"issue/{ref}").get("fields") or {})
        assignee = fields.get("assignee") or {}
        account = assignee.get("accountId")
        return [account] if account else []

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        account = logins[0] if logins else None
        self._call("PUT", f"issue/{ref}",
                   {"fields": {"assignee": {"accountId": account} if account else None}})

    @staticmethod
    def jira_label(label: str) -> str:
        """The platform's label in the shape THIS provider accepts.

        JIRA LABELS CANNOT CONTAIN SPACES, and the platform's marker was `🤖 sdlc-working` —
        GitHub-shaped, because GitHub is where it was written. Jira answers 400 *"A categoria
        '🤖 sdlc-working' não pode…"*, the caller swallows it (labelling is best-effort by
        design), and the marker that says a ticket is being worked on simply never appears on a
        Jira board. Found live on the first Jira ticket this platform ever ran (DAR-2, F-02,
        2026-08-05).

        The emoji is kept — Jira accepts it, and it is what makes the marker legible at a glance
        on a board full of human labels. Only the space, which Jira treats as a separator, is
        closed up."""
        return "-".join((label or "").split()) or "openfactory"

    def add_label(self, ref: str, label: str) -> None:
        self._call("PUT", f"issue/{ref}",
                   {"update": {"labels": [{"add": self.jira_label(label)}]}})

    def remove_label(self, ref: str, label: str) -> None:
        self._call("PUT", f"issue/{ref}",
                   {"update": {"labels": [{"remove": self.jira_label(label)}]}})

    def create_ticket(self, *, title: str, body: str) -> str:
        created = self._call("POST", "issue", {
            "fields": {
                "project": {"key": self.project_key},
                "summary": title,
                "description": self._adf(body),
                "issuetype": {"name": self.issue_type},
            },
        })
        return str(created.get("key") or "")

    def find_ticket(self, *, title: str) -> str | None:
        """An OPEN issue with exactly this summary. JQL escaping matters here: a title with a
        quote in it would otherwise break the query — or, worse, match the wrong issue."""
        escaped = title.replace("\\", "\\\\").replace('"', '\\"')
        jql = (f'project = "{self.project_key}" AND statusCategory != Done '
               f'AND summary ~ "\\"{escaped}\\""')
        # `~` is PHRASE search, not equality — Jira has no exact-match operator for summary — so
        # the page is wide and the equality check happens here. At 5 results the exact match
        # could sit on page two whenever one title prefixes others (the split parent prefixing
        # its children is the guaranteed case), find_ticket would answer None, and the splitter's
        # idempotency — this method's entire reason to exist — would file a duplicate.
        found = self._call("POST", "search/jql", {"jql": jql, "maxResults": 50,
                                                  "fields": ["summary"]})
        for issue in found.get("issues") or []:
            if str((issue.get("fields") or {}).get("summary", "")).strip() == title.strip():
                return str(issue.get("key"))
        return None

    #: The fields one board row is built from. Asked for BY NAME because `search/jql` returns only
    #: `id`/`key`/`self` otherwise — a page of issues with no summary and no status, which parses
    #: into a board of blank cards rather than into an error.
    #: `resolution` is here for `_closed_reason` and for nothing else: a field that is not asked
    #: for is not answered, and a withdrawn card would read as delivered for want of one word.
    _LIST_FIELDS = ["summary", "description", "status", "resolution", "labels", "assignee",
                    "updated"]

    def list_tickets(self, *, state: str = "all", updated_since: str = "",
                     limit: int = 0) -> list[TicketSummary] | None:
        """The project's issues through `search/jql`, newest-updated first.

        `/rest/api/3/search` IS GONE — 410, *"A API solicitada foi removida. Migre para
        /rest/api/3/search/jql"* (called live, 2026-08-06). The replacement is token-paginated and
        **returns no `total`**, so how much of the board this saw is knowable only from `isLast`,
        and that is what the loop below reads. A page walk that stopped on a short page instead
        would report a partial board as a whole one.

        OPEN VERSUS CLOSED IS `statusCategory`, NEVER A STATUS NAME — the same rule `get_ticket`
        follows, and the reason this deployment's Jira board can have a done column spelled
        "Donee" (it does) without the platform reading live work as delivered.
        """
        wanted = list_state(state)
        clauses = [f'project = "{self.project_key}"']
        if self.scope_jql:
            clauses.append(f"({self.scope_jql})")
        if wanted == "open":
            clauses.append("statusCategory != Done")
        elif wanted == "closed":
            clauses.append("statusCategory = Done")
        since = _jql_since(updated_since)
        if since:
            clauses.append(f'updated >= "{since}"')
        jql = " AND ".join(clauses) + " ORDER BY updated DESC"

        rows: list[dict] = []
        token: str | None = None
        try:
            for page_number in range(_MAX_PAGES):
                payload: dict = {"jql": jql, "fields": self._LIST_FIELDS,
                                 "maxResults": min(limit, _PAGE) if limit > 0 else _PAGE}
                if token:
                    payload["nextPageToken"] = token
                page = self._call("POST", "search/jql", payload)
                rows.extend(page.get("issues") or [])
                token = page.get("nextPageToken")
                if page.get("isLast") or not token or (0 < limit <= len(rows)):
                    break
                if page_number == _MAX_PAGES - 1:
                    log.warning("stopped listing %s after %d pages (%d issues) and the board says "
                                "there is more — the caller is about to judge a partial board",
                                self.project_key, _MAX_PAGES, len(rows))
        except Exception as exc:  # noqa: BLE001 — an unread board is None, never []
            log.warning("could not list the tickets of %s (%s) — the caller is being told "
                        "UNREADABLE, not empty", self.project_key, str(exc)[:200])
            return None

        if not rows and not self._project_exists():
            return None

        found = [self._summary(issue) for issue in rows]
        # already ORDER BY updated DESC on the wire; sorted again so the port's promise does not
        # depend on a clause a future edit could drop
        found.sort(key=lambda t: t.updated_at, reverse=True)
        return found[:limit] if limit > 0 else found

    def _project_exists(self) -> bool:
        """Whether this deployment's `project_key` names a real, visible Jira project.

        ASKED ONLY WHEN THE BOARD CAME BACK EMPTY, AND THAT IS THE WHOLE POINT. Measured live
        against a production client's Jira Cloud site:

            POST search/jql  {"jql": 'project = "DAR"  ORDER BY updated DESC'}  →  200, 3 issues
            POST search/jql  {"jql": 'project = "NOPE" ORDER BY updated DESC'}  →  200, []

        A project key that does not exist is not an error on this endpoint — it is an empty page.
        So a typo in one registry row, or a token that lost Browse Projects on the client's
        project, arrives at `product/board.py` as *the board is empty*, and every caller there
        treats that as a fact: "nothing is queued", "no findings", "the open questions resolved
        themselves". All three of those sentences have already been produced by this platform from
        a board it could not read.

        The cost is one extra request per EMPTY answer and none at all otherwise: a board that
        returned issues has proved its own existence. `GET project/{key}` answers 404 for both the
        missing project and the invisible one, which are the same answer to the only question being
        asked — can this deployment see the board it is configured for.
        """
        try:
            self._call("GET", f"project/{self.project_key}")
        except Exception as exc:  # noqa: BLE001
            log.warning("jira answered no issues for %r AND cannot show the project itself (%s) — "
                        "reporting the board as UNREADABLE rather than as empty",
                        self.project_key, str(exc)[:200])
            return False
        return True

    def _summary(self, issue: dict) -> TicketSummary:
        fields = issue.get("fields") or {}
        category = (((fields.get("status") or {}).get("statusCategory")) or {}).get("key")
        closed = str(category or "").lower() == "done"
        assignee = (fields.get("assignee") or {}).get("accountId")
        return TicketSummary(
            ref=str(issue.get("key") or ""),
            title=str(fields.get("summary") or ""),
            body=self._text(fields.get("description")),
            state="closed" if closed else "open",
            state_reason=self._closed_reason(fields) if closed else "",
            labels=[str(x) for x in (fields.get("labels") or [])],
            assignees=[str(assignee)] if assignee else [],
            updated_at=str(fields.get("updated") or ""),
        )

    def _closed_reason(self, fields: dict) -> str:
        """`"not_planned"` when the card carries the resolution, or sits in the status, THIS
        DEPLOYMENT named as "not delivered"; `""` for every other closed card.

        A RESOLUTION IS A NAME A SITE ADMINISTRATOR CHOSE ("Won't Do", "Duplicate", "Não será
        feito"), and deciding delivery from a name this module GUESSED is the thing `statusCategory`
        is used everywhere else to avoid. That is why this answered `""` for every card until #203,
        and why it still does for a deployment that configured nothing. A name the deployment
        DECLARED is a different thing — it is `status_map`'s rule, applied to the other half of a
        close: the same option `close_ticket(delivered=False)` writes is the one read back here, so
        the two halves cannot disagree. A person who closes a card as that resolution by hand reads
        the same way, which is what GitHub's `not planned` has always done.

        NEVER `"completed"`. Any other resolution — `Done`, and equally a `Duplicate` nobody
        configured — is a name this module was not told the meaning of, so the answer stays the
        port's "this tracker does not say". `""` reads as delivered downstream on purpose
        (`triage.Ticket.delivered`): a possible false delivery is traded for never losing a real
        one.

        THE STATUS IS READ THE SAME WAY, AND EITHER ANSWERS (2026-09-19). A site that says
        "withdrawn" with a status of its own holds the card IN it, so the read is of where the card
        is now: moved back out, it stops reading as withdrawn with nothing for anybody to clear —
        the stale mark `close_ticket` refused a label over cannot happen. A deployment that named
        both words is answered by whichever the card carries, because a person closing by hand
        picks either. This is asked only of a CLOSED card (`_summary`): a status of that name which
        the site files outside its Done category is open work, whatever it is called."""
        wanted = self.not_delivered_resolution.lower()
        got = str((fields.get("resolution") or {}).get("name") or "").strip().lower()
        withdrawn = self.not_delivered_status.lower()
        sits_in = str((fields.get("status") or {}).get("name") or "").strip().lower()
        said = (wanted and got == wanted) or (withdrawn and sits_in == withdrawn)
        return "not_planned" if said else ""

    def update_body(self, ref: str, body: str) -> None:
        self._call("PUT", f"issue/{ref}", {"fields": {"description": self._adf(body)}})

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        """Close the issue with a final comment: the transition into whatever this deployment
        mapped to `done`.

        CLOSED IS NOT DELIVERED, and until #203 this row could not say so: it took no `delivered`,
        so a card an operator withdrew, a duplicate the product owner folded and work that shipped
        all landed in Done alike — and the product owner's close did not land at all, because it
        passes the keyword and this signature raised on it.

        `delivered=True` IS UNTOUCHED: the bare transition, no fields. Which resolution the card
        then shows is the site's workflow's business — a post-function on a company-managed
        project, automatic on a team-managed one — and nothing here overrides it.

        `delivered=False` sends the SAME transition with `fields.resolution` set to the name this
        deployment configured (`not_delivered_resolution`). TWO THINGS CAN BE MISSING, and both
        degrade the way the Azure Boards row does for a process with no Removed state — the card is
        still closed, a note on it says the work was withdrawn, and a named log line says which
        option to set:

          - the deployment configured no resolution. There is no default, on purpose: the list is
            the site's, and a literal `Won't Do` would be refused on every site that spells it
            otherwise;
          - Jira refused the field with a 400 — the transition's screen does not carry
            `resolution` (Atlassian documents team-managed projects as having no such screen),
            or the site has no resolution of that name. The transition is posted again WITHOUT the
            field. Any other failure — a credential, a 5xx, a transport error — raises as it
            always did.

        A CARD CLOSED ON EITHER DEGRADED PATH READS AS DELIVERED DOWNSTREAM, and that is said here
        rather than papered over. What Jira holds for it is the Done status and the resolution the
        site's own workflow set, which is exactly what it holds for shipped work; the note is
        prose, and deciding delivery from a sentence is what `azure_devops._summary` refuses for
        `System.Reason`. A label written here was considered and rejected: the board adapter and
        every person with the board open move cards without passing through this class, so nothing
        would clear it when a withdrawn card is reopened and then really delivered — and it would
        then hide a real delivery, the failure `TicketSummary.state_reason` ranks as the worse one.
        Jira clears a resolution on reopen by itself; that is why the resolution is the mechanism.

        SHAPES FROM ATLASSIAN'S REST v3 DOCUMENTATION, NOT FROM A LIVE SITE: `POST
        issue/{key}/transitions` with `{"transition": {"id"}, "fields": {"resolution": {"name"}}}`,
        refused as `400 {"errors": {"resolution": "Field 'resolution' cannot be set. It is not on
        the appropriate screen, or unknown."}}`. A site that answers otherwise lands in the log
        line below with Jira's own words in it, which is the thing to send back.

        A SITE MAY SAY IT WITH A STATUS INSTEAD, AND THAT ONE IS TRIED FIRST (2026-09-19).
        `not_delivered_status` names a status of the site's own in the Done category; the withdrawn
        close is then the BARE transition into it — no field for a screen to refuse, which is why a
        team-managed project can be told the truth at all. When a deployment names both words, the
        status is the record and the resolution is what is left for a card whose workflow has no
        move into that status from where it is: a status is where the site's own people look for
        withdrawn work, it is read back from where the card IS rather than from a field a workflow
        may overwrite, and sending the field along with it would bring the screen's refusal back
        into the one path that has none. THREE THINGS CAN STOP THE STATUS, and each passes the close
        on to the resolution and then to the degraded path above, saying what it met in the same
        log line:

          - the workflow offers no transition into it from the card's current status;
          - the site files that status OUTSIDE its Done category. Moving the card there would
            answer "closed" for a card every read then shows as open work, so it is not used —
            asked of the transition's own `to.statusCategory`, and only a category the site
            actually states can refuse;
          - Jira answered 400 to the move (a workflow validator). Anything else raises."""
        if reason:
            self.comment(ref, reason)
        if delivered:
            self.set_state(ref, JobState.DONE)
            return
        met: list[str] = []     # what each word this deployment named ran into, for the one line
        status = self.not_delivered_status
        into = self._transition_for(ref, status=status) if status else None
        if into is not None and not _closes_a_card(into):
            log.warning("jira status %r is not in the site's Done category, so moving %s there "
                        "would not close it — it is not used for a withdrawn close", status, ref)
            met.append(f"the status {status!r} is not in the site's Done category, so a card moved "
                       f"there is still open — name one that is, in `not_delivered_status`")
        elif into is not None:
            refused = self._refusal_of(ref, {"transition": {"id": into["id"]}})
            if not refused:
                return
            met.append(f"jira refused the move into the status {status!r} ({refused}) — see what "
                       f"its workflow asks for, or name another in `not_delivered_status`")
        elif status:
            met.append(f"the workflow has no transition into the status {status!r} from where the "
                       f"issue is — add one, or name another in `not_delivered_status`")
        match = self._transition_for(ref, JobState.DONE)
        if match is None:
            return  # `set_state`'s own contract, and the warning it logs has already said which
        move = {"transition": {"id": match["id"]}}
        wanted = self.not_delivered_resolution
        if wanted:
            refused = self._refusal_of(ref, {**move, "fields": {"resolution": {"name": wanted}}})
            if not refused:
                return
            met.append(f"jira refused the resolution {wanted!r} on the closing transition "
                       f"({refused}) — name one this site has, on a transition whose screen "
                       f"carries the Resolution field, in `not_delivered_resolution`")
        if not met:
            met.append("this deployment names no status and no resolution that means 'not "
                       "delivered' — set `not_delivered_status` (a status in the site's Done "
                       "category) or `not_delivered_resolution`")
        landed = str((match.get("to") or {}).get("name") or match.get("name") or "")
        log.warning("OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED issue=%s: %s (the project's "
                    "tracker options). The card is closed into %r with a "
                    "note saying the work was withdrawn, and everything that reads the board will "
                    "count it as delivered", ref, "; and ".join(met), landed)
        # IN THE PROJECT'S LANGUAGE, asked of the catalogue (#160): this is the one sentence the
        # row says to a person in its own name, and one composed here would reach a Portuguese
        # board in English. `product.voice` imports nothing but the standard library.
        from openfactory.product.voice import closed_not_delivered_note

        self.comment(ref, closed_not_delivered_note(status=landed, language=self.language))
        self._call("POST", f"issue/{ref}/transitions", move)

    def update_title(self, ref: str, title: str) -> None:
        """Jira calls it `summary`, and that is the whole of the difference."""
        self._call("PUT", f"issue/{ref}", {"fields": {"summary": (title or "").strip()}})

    def reopen_ticket(self, ref: str) -> None:
        """The mirror of `close_ticket`: a transition back to whatever this deployment mapped to
        `todo`. Unmapped stays a no-op with a warning — `set_state`'s own contract, and the reason
        is the same one it gives: an invented transition either fails or moves the card somewhere
        nobody expects."""
        self.set_state(ref, JobState.TODO)

    # ---- optional linkage (ADR-0013 D3) ---------------------------------------------------

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        """Jira's native parent link. Best-effort by contract: a project whose issue types forbid
        the link still splits correctly through the deterministic titles."""
        try:
            self._call("PUT", f"issue/{child_ref}", {"fields": {"parent": {"key": parent_ref}}})
        except Exception as exc:  # noqa: BLE001 — the split works without native linkage
            log.info("could not link %s under %s (%s) — the split still holds through titles",
                     child_ref, parent_ref, exc)

    def children_of(self, parent_ref: str) -> list[str]:
        try:
            found = self._call("POST", "search/jql",
                               {"jql": f'parent = "{parent_ref}"', "maxResults": 50,
                                "fields": ["summary"]})
            return [str(i.get("key")) for i in (found.get("issues") or []) if i.get("key")]
        except Exception as exc:  # noqa: BLE001 — "unknown" must never read as "no children"
            log.warning("could not list the children of %s (%s) — the splitter will fall back to "
                        "matching by title, which is correct but slower", parent_ref, exc)
            return []

    # ---- identity, the two optional capabilities (ADR-0049 D7) --------------------------
    def identity_of(self, subject_id: str) -> str:
        """`""` — a Jira display name is not a platform id.

        NOT A FAILURE AND NOT A GAP: the bridge between a platform id and this vendor's
        namespace is a thing the deployment DECLARES (`Project.people`), and the caller
        reads that map first. A row inventing an answer here would put one person's name
        on another person's question."""
        return ""

    def mention(self, login: str) -> str:
        """The name unchanged — today's answer, now said by the row rather than inferred from
        the provider's name somewhere else. Jira notifies on an ACCOUNT ID carried in a
        comment's ADF (`[~accountid:…]`), never on a bare `@name` in text, so an `@`
        here would be decoration wearing the shape of a notification."""
        return (login or "").strip()


def _closes_a_card(transition: dict) -> bool:
    """Whether the status this transition leads to is one the site files under Done — the same
    `statusCategory` that decides open against closed on every read here, asked BEFORE the move
    instead of after it. ONLY A CATEGORY THE SITE STATES CAN SAY NO: a transition that carries none
    is not evidence of anything, and refusing on it would disable the option on a site whose answer
    is merely thinner than the documented one."""
    category = (((transition.get("to") or {}).get("statusCategory")) or {}).get("key")
    return not category or str(category).lower() == "done"


def _display(value: object) -> str:
    """The `displayName` of a Jira identity blob, "" when there is none — the readable half, never
    the accountId (see `TicketComment.author`)."""
    if isinstance(value, dict):
        return str(value.get("displayName") or "")
    return ""

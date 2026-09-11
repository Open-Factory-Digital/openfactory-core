"""GitHub Projects v2 board integration — align the card's Status with the job state.

The framework's states must be reflected on the real board the human watches, not
just as issue labels. This moves the item's single-select **Status** field via the
`gh project` CLI. Project/field/option/item ids are resolved once and cached.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

from openfactory.adapters.tracker.base import Budget, BudgetUnreadable
from openfactory.contracts import JobState
from openfactory.contracts.refs import qualify_ref, ref_number, split_repo_ref

log = logging.getLogger("openfactory.tracker.github_project")

#: The DEFAULT column names — what a board created by the platform's own template uses. A client
#: whose board says "A Fazer" / "Fazendo" overrides them per key in the registry's tracker
#: options (`columns:`), exactly the model the Jira adapter has always used (`status_map`); the
#: STATES stay closed, only the LABELS open (C-14, ADR-0022 §4).
DEFAULT_COLUMNS: dict[str, str] = {
    "todo": "TO-DO",
    "in_progress": "In progress",
    "in_review": "In review",
    # Parked waiting on a HUMAN → a dedicated column, NOT Backlog: a ticket that needs you must
    # never hide among the ones you haven't started. Falls back to the backlog column if the
    # board has no such column (set_status keeps the old fallback).
    "needs_action": "Needs Action",
    "done": "Done",
    "backlog": "Backlog",
}

# framework state -> board Status option name — the DEFAULT rendering, kept because callers and
# tests read it as the canonical answer for an unconfigured board.
STATUS_MAP: dict[JobState, str] = {
    JobState.TODO: "TO-DO",
    JobState.READY: "TO-DO",
    JobState.SPEC_VALIDATION: "In progress",
    JobState.PREPARING: "In progress",
    JobState.PLANNING: "In progress",
    JobState.IMPLEMENTING: "In progress",
    JobState.VALIDATING: "In progress",
    JobState.REPAIRING: "In progress",
    JobState.REVIEWING: "In review",
    JobState.PR_OPEN: "In review",
    # Parked waiting on a HUMAN decision → a dedicated column, NOT Backlog: a ticket that needs
    # you must never hide among the ones you haven't started. The "why" is in the ticket's
    # comment. (A rate-limit PAUSED job auto-resumes and isn't mapped here — it stays "In
    # progress".) Falls back to Backlog if the board has no such column (set_status no-ops).
    JobState.NEEDS_REFINEMENT: "Needs Action",
    JobState.ON_HOLD: "Needs Action",
    JobState.BLOCKED: "Needs Action",  # parked on a DecisionRequest — options are in the ticket
    JobState.FAILED: "Needs Action",
    JobState.MERGED: "In review",  # merged → deploying/verifying, still overseen
    JobState.STAGING_VERIFYING: "In review",
    # A PRODUCTION GATE IS A PERSON (#166) — `view.ATTENTION_STATES` has always named it, so the
    # floor said "Needs you" while this board said "In review" about the one gesture that puts
    # software in front of real users. Kept in step with `STATE_KEYS` by the guard that caught
    # this edit one-sided.
    JobState.AWAITING_PROD_APPROVAL: "Needs Action",
    JobState.PROD_VERIFYING: "In review",
    JobState.DONE: "Done",
    # A human took it off the floor. Open work nobody is working on — not shipped, not waiting.
    JobState.SKIPPED: "Backlog",
}


def _env(token: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    return env


#: What `gh` says when it cannot decide whether a `--owner` login is a user or an organisation.
#: It resolves both in one GraphQL document, and a token without `read:org` — which a PERSONAL
#: account has no reason to carry — fails the organisation half and takes the whole answer with
#: it. Measured in the pilot (2026-08-13): a board this platform had just CREATED for
#: `solo-dev` could not be read back, while creation succeeded because that path asks our own
#: GraphQL and falls through to the user query.
_UNKNOWN_OWNER = "unknown owner type"


def _as_me(args: list[str]) -> list[str] | None:
    """The same command addressed at `@me`, or None when it names no `--owner`."""
    if "--owner" not in args:
        return None
    retry = list(args)
    retry[retry.index("--owner") + 1] = "@me"
    return retry


def _run_gh(args: list[str], token: str | None):
    """One `gh` call, retried once as `@me` when gh cannot type the owner.

    THE RETRY IS THE PERSONAL-ACCOUNT PATH, not a workaround for a broken credential: `@me` is
    gh's own spelling for "the authenticated user", and it needs no organisation scope. It is
    tried ONLY on that one error string, so a real permission failure still surfaces as itself
    rather than being retried into a confusing second message."""
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60,
                           env=_env(token))
    except FileNotFoundError:
        raise RuntimeError(
            "the `gh` CLI is not installed — the GitHub board speaks through it. Install it "
            "(https://cli.github.com) and run `gh auth login`.") from None
    if p.returncode != 0 and _UNKNOWN_OWNER in (p.stderr or "").lower():
        retry = _as_me(args)
        if retry is not None:
            log.info("gh could not type the owner of this board — retrying as `@me` (a personal "
                     "account's board needs no organisation scope)")
            try:
                second = subprocess.run(["gh", *retry], capture_output=True, text=True,
                                        timeout=60, env=_env(token))
            except FileNotFoundError:  # pragma: no cover — the first call would have raised
                return p
            if second.returncode == 0:
                return second
    return p


def _gh_json(args: list[str], token: str | None = None) -> dict:
    p = _run_gh(args, token)
    if p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {p.stderr}")
    return json.loads(p.stdout)


class BoardUnreadable(RuntimeError):
    """The board could not be READ — as opposed to living under a different root, or being empty.

    Its own type because the caller's answer differs: a wrong root is retried under the other one,
    an unreadable board is reported. Never turned into an empty list — a board nobody could read
    is not a board with no cards, which is the conflation this codebase pays for everywhere."""


#: What the FORGE says when the root we guessed is simply the wrong one. A project owned by a
#: person answers `organization(login:)` with NOT_FOUND, and an org's answers `user(login:)` the
#: same way — that is an ANSWER, and the caller's move is to try the other root.
#:
#: Everything NOT in this list is the call FAILING: a 502/503, a timeout, a revoked token, a
#: rate-limit. None of those is evidence about which root owns the board.
_WRONG_ROOT = ("not_found", "could not resolve to an organization",
               "could not resolve to a user", "type_mismatch")


def _is_wrong_root(message: str) -> bool:
    """Does this error mean "the board is not under this root", or that the call failed? (#132)

    Matched on the FORGE's own words, and TEXT NOBODY RECOGNISES IS READ AS A FAILURE, not as a
    wrong root: the safe direction is refusing to buy the hundredfold read, because the cost of
    guessing wrong in the other direction is the quota disappearing on the worst possible day."""
    said = (message or "").lower()
    return any(marker in said for marker in _WRONG_ROOT)


#: Below this many API calls left, the poller stops taking cards. GITHUB'S OWN NUMBER, kept here:
#: a board scan plus a job start spend a handful of calls, so the cushion keeps real work alive
#: while polls stop; the hourly reset restores it. It travels on `Budget.floor` and the core
#: carries no copy — `poller._RATE_FLOOR` and the doctor's `max(200, limit // 10)` were two
#: thresholds for one behaviour, and the second said "nearly gone" at a level the first was
#: still scanning through.
BUDGET_FLOOR = 200


def github_rate(token: str | None = None) -> Budget:
    """The GitHub API budget for the MOST-constrained of graphql/core (the board scan spends
    graphql, issue ops spend core), as the port's `Budget`. Reached through
    `GitHubIssuesTracker.budget()` — the floor, the poller, the doctor and the cockpit ask the
    PORT, so a deployment whose tracker is not GitHub never runs this. Cheap: /rate_limit costs
    nothing against the quota it reports.

    RAISES `BudgetUnreadable` ON ANY FAILURE, where it used to return `None`. `None` was also
    what a vendor with no budget would answer, and the doctor rendered both as ok; the callers
    that fail open (the poller scans anyway) still do — they catch the error and say "unread",
    which is the honest word for a safety net that is not there right now."""
    try:
        d = _gh_json(["api", "rate_limit"], token).get("resources", {})
    except Exception as exc:  # noqa: BLE001 — every failure shape is the same answer: unreadable
        raise BudgetUnreadable(
            f"could not read the GitHub rate limit ({str(exc)[:200]})") from exc
    worst: Budget | None = None
    for res in ("graphql", "core"):
        r = d.get(res)
        if not r:
            continue
        cand = Budget(resource=res, remaining=int(r.get("remaining", 0)),
                      limit=int(r.get("limit", 0)), reset_epoch=int(r.get("reset", 0)),
                      floor=BUDGET_FLOOR, vendor="GitHub")
        if worst is None or cand.remaining < worst.remaining:
            worst = cand
    if worst is None:
        raise BudgetUnreadable("the GitHub rate-limit answer named neither graphql nor core")
    return worst


#: login → `"orgs"` or `"users"`, for the process. The answer cannot change for a login and the
#: panel renders the board link on every load.
_OWNER_KIND: dict[str, str] = {}


def _gh_host() -> str:
    """github.com, or an Enterprise deployment's own host — the same question `clone_url` asks."""
    import os

    return (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") or "github.com").strip()


def _owner_kind(owner: str) -> str:
    """`"orgs"` or `"users"` for a GitHub login — asked, never assumed.

    A FAILED PROBE ANSWERS `users`, because that is the shape which also works for a personal
    account and the one this platform got wrong. Cached for the process: the answer cannot change
    for a login, and the panel asks on every cockpit load.
    """
    cached = _OWNER_KIND.get(owner)
    if cached:
        return cached
    kind = "users"
    try:
        import subprocess

        out = subprocess.run(["gh", "api", f"users/{owner}", "--jq", ".type"],
                             capture_output=True, text=True, timeout=15, check=False)
        if out.returncode == 0 and (out.stdout or "").strip().lower() == "organization":
            kind = "orgs"
    except Exception as exc:  # noqa: BLE001 — a link is never worth failing a page over
        log.info("could not type the board owner %r (%s) — linking as a user", owner, exc)
    _OWNER_KIND[owner] = kind
    return kind


class GitHubProjectBoard:
    def __init__(
        self, owner: str, number: str, *, token: str | None = None, token_provider=None,
        columns: dict[str, str] | None = None, default_repo: str = ""
    ) -> None:
        self.owner = owner
        self.number = str(number)
        # the client's own column names, keyed by the neutral lifecycle keys; defaults otherwise
        self._columns = {**DEFAULT_COLUMNS, **{k: str(v) for k, v in (columns or {}).items()}}
        # C-18: the repo a BARE ref means. A Projects v2 board is org-level and carries cards
        # from any repository; refs leaving this adapter are qualified (`owner/name#n`) exactly
        # when the card's repo differs from this. Empty = never qualify — today's single-repo
        # behaviour, byte-for-byte.
        self._default_repo = default_repo
        self._static_token = token
        self._token_provider = token_provider  # re-mints a fresh token at use (long jobs)
        self._project_id: str | None = None
        self._status_field_id: str | None = None
        self._option_ids: dict[str, str] = {}
        self._item_ids: dict[tuple[int, str], str] = {}  # (number, repo) -> project item id

    @property
    def token(self) -> str | None:
        # Resolved at each use, never frozen: App installation tokens last ~1h, and a board
        # write in a job that outlives one must still authenticate (same rule as the forge
        # and the tracker's own issue ops).
        return self._token_provider() if self._token_provider else self._static_token

    def _ensure_meta(self) -> None:
        if self._project_id:
            return
        try:
            proj = _gh_json(
                ["project", "view", self.number, "--owner", self.owner, "--format", "json"],
                self.token)
            fields = _gh_json(
                ["project", "field-list", self.number, "--owner", self.owner, "--format", "json"],
                self.token,
            )["fields"]
        except RuntimeError as exc:
            if _UNKNOWN_OWNER not in str(exc).lower():
                raise
            # THE OWNER IS RESOLVED THE WAY CREATION ALREADY RESOLVES IT. `gh project` types the
            # `--owner` login itself, in one document that asks the organisation and the user at
            # once — so a token without `read:org` (which a PERSONAL account has no reason to
            # carry, and our own guide does not ask for) fails the whole answer, and the `@me`
            # retry above cannot save every gh build either. Board CREATION never had this
            # problem: it asks our own GraphQL, organisation first and user second, treating a
            # failed org probe as "not an org" (`github_board_setup._owner_id`). The board this
            # platform had just created was unreadable by the same platform — measured in the
            # pilot, twice (2026-08-13, and again after the first fix, 2026-08-14).
            log.info("gh could not type the owner of %s/%s — resolving the project through "
                     "GraphQL, organisation first and user second", self.owner, self.number)
            proj, fields = self._meta_via_graphql(exc)
        for f in fields:
            if f.get("name") == "Status":
                self._status_field_id = f["id"]
                self._option_ids = {o["name"]: o["id"] for o in f.get("options", [])}
        # The early-return key is written LAST: a raise on either fetch above must leave the
        # instance untouched so the next call retries, not half-initialised forever (a one-blip
        # rate limit used to poison every subsequent set_column on this instance).
        self._project_id = proj["id"]

    def _meta_via_graphql(self, first: Exception) -> tuple[dict, list[dict]]:
        """`(project, fields)` for a board `gh` could not address — one query, no owner typing.

        Both roots are tried because only the owner knows which it is, and the ORG probe may not
        decide the outcome: without `read:org` GitHub FAILS that query rather than answering
        null, which is exactly how a personal account's board became unreadable. Both failures
        travel into the message if neither answers — a retry whose own error is swallowed is a
        fix nobody can confirm from the field."""
        from openfactory.adapters.tracker.github_board_setup import BoardSetupError, _gh_graphql

        number = int(str(self.number).strip())
        why: list[str] = [f"as `--owner {self.owner}`: {first}"]
        for root in ("organization", "user"):
            query = (
                f"query($login: String!) {{ {root}(login: $login) "
                f"{{ projectV2(number: {number}) {{ id "
                'field(name: "Status") { ... on ProjectV2SingleSelectField '
                "{ id options { id name } } } } } }"
            )
            try:
                data = _gh_graphql(query, self.token, login=self.owner)
            except BoardSetupError as exc:
                why.append(f"as a {root}: {str(exc)[:160]}")
                continue
            project = (data.get(root) or {}).get("projectV2")
            if not project:
                why.append(f"as a {root}: no project {number} is visible there")
                continue
            status = project.get("field") or {}
            fields = ([{"name": "Status", "id": status.get("id"),
                        "options": status.get("options") or []}] if status.get("id") else [])
            return {"id": project["id"]}, fields
        raise RuntimeError(
            f"the board {self.owner}/{self.number} could not be read — " + "; ".join(why))

    def add_item(self, *, issue_url: str) -> None:
        """Add an issue to the board (idempotent — re-adding is a no-op on GitHub's side).
        It lands with no Status, i.e. the intake column (Backlog on our boards). Raises when it
        could not be done: a card that silently never appears is invisible to everyone who works
        from the board, and the callers' warning paths exist for exactly this failure.

        OUR OWN MUTATION, NOT `gh project item-add` — the FIFTH sighting of the organisation/user
        asymmetry, and the first on the WRITE side (pilot, 2026-08-15). `gh project` types the
        `--owner` login itself, in one document that asks the organisation and the user at once,
        so a token without `read:org` — which a PERSONAL account has no reason to carry and our
        own setup guide does not ask for — fails the whole call with *"unknown owner type"*. The
        reads were moved to our own GraphQL for this exact reason; the writes were left behind,
        so on a user-owned board every card add and every column move failed while the job ran on
        regardless."""
        self._ensure_meta()
        if not self._project_id:
            raise RuntimeError(f"the board {self.owner}/{self.number} could not be identified")
        content_id = self._content_id(issue_url)
        p = _run_gh(["api", "graphql", "-f", "query=" + """
            mutation($project:ID!, $content:ID!) {
              addProjectV2ItemById(input:{projectId:$project, contentId:$content}) {
                item { id } } }""",
                     "-f", f"project={self._project_id}", "-f", f"content={content_id}"],
                    self.token)
        if p.returncode != 0:
            # `gh api graphql` exits non-zero whenever the response carries GraphQL errors, so
            # the code is a reliable verdict — no payload to parse for a mutation whose result
            # this caller does not use.
            raise RuntimeError(
                f"adding {issue_url} to the board {self.owner}/{self.number} failed: "
                f"{(p.stderr or '').strip()[:300]}")

    def _content_id(self, issue_url: str) -> str:
        """The issue's own node id — what `addProjectV2ItemById` takes, since a URL is not an id.

        Read from the issue rather than from the board, because the card is precisely what does
        not exist yet."""
        import re as _re

        m = _re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url or "")
        if not m:
            raise RuntimeError(f"{issue_url!r} is not a GitHub issue URL")
        owner, repo, number = m.groups()
        data = _gh_json(["api", "graphql", "-f", "query=" + """
            query($owner:String!, $repo:String!, $number:Int!) {
              repository(owner:$owner, name:$repo) { issue(number:$number) { id } } }""",
                         "-f", f"owner={owner}", "-f", f"repo={repo}", "-F", f"number={number}"],
                        self.token)
        node = (((data.get("data") or {}).get("repository") or {}).get("issue") or {}).get("id")
        if not node:
            raise RuntimeError(f"could not read the id of {issue_url}")
        return str(node)

    def _board_items(self) -> list[dict]:
        """Every card as `{id, number, status}` — ONE GraphQL page per 100, not one per card.

        MEASURED, 2026-07-28, on a 256-card board: `gh project item-list` cost **303 GraphQL
        points** per read because the CLI issues a request PER ITEM; the same data through a
        hand-written query costs **~3** (one per page). The poller reads this board every three
        minutes — 20 reads/hour × 303 = 6,060 points against a 5,000/hour ceiling, so the
        installation exhausted its own quota every hour, all by itself, and the poller's own
        low-budget guard then skipped the ticks. The board was unreadable for the product role at
        exactly the moment somebody was talking to it.

        AND THE CHEAP READ ASKED ONLY FOR AN ORGANISATION, so a PERSONAL account never got it.
        A user-owned project answers `organization(login:)` with an ERROR, which landed in the
        fallback below and bought the 303-point read back — every three minutes, silently,
        behind a log line nobody reads. Measured live on the pilot (2026-08-14): 5,000 → 4,688
        points in five minutes, ~300 per tick, and the operator's personal quota went to zero
        while the factory's own App budget sat untouched at 5,600. He asked the right question:
        *"what limit? I never got any warning"*.

        Both roots are tried, in the order that costs least on the common case, exactly as
        `_meta_via_graphql` and board CREATION already do — this is the third sighting of the
        organisation/user asymmetry in one week, so it is now the same shape in all three."""
        # THE FALLBACK IS FOR A SHAPE WE CANNOT ADDRESS, NEVER FOR A CALL THAT FAILED (#132).
        # `_board_items_via_graphql` raises `BoardUnreadable` for the second, and it is deliberately
        # NOT caught here: paying a hundredfold to re-ask a forge that just refused us is the worst
        # possible answer to a 503, and the poller already knows how to skip a tick it cannot read.
        for root in ("organization", "user"):
            items = self._board_items_via_graphql(root)
            if items is not None:
                return items
        log.warning("board %s/%s could not be read as an organisation OR a user project — "
                    "falling back to the CLI path (100x costlier per read)",
                    self.owner, self.number)
        return self._board_items_via_cli()

    def _board_items_via_graphql(self, root: str) -> list[dict] | None:
        """One page-per-100 read under `organization` or `user` — or None when the board is not
        under THIS root. RAISES `BoardUnreadable` when the call itself failed (#132).

        THE TWO USED TO BE ONE VALUE, and the expensive branch won. This returned `None` for both,
        its own docstring said so — *"or None when that root is not the right one (or the query
        failed)"* — and `_board_items` reads two `None`s as "neither root owns this board", which
        buys the CLI read at one request PER CARD.

        So on the afternoon GitHub spent 503-ing (measured on the pilot, 2026-08-17), the cheap
        query failed for a reason that had nothing to do with roots, and the platform answered by
        spending a hundredfold more quota — accelerating its own burn at exactly the moment the
        forge was unhealthy and the budget mattered most. The tick then failed anyway, so the
        points bought nothing at all."""
        query = f"""
        query($owner:String!, $number:Int!, $cursor:String) {{
          {root}(login:$owner) {{ projectV2(number:$number) {{
            items(first:100, after:$cursor) {{
              pageInfo {{ hasNextPage endCursor }}
              nodes {{
                id
                content {{
                  ... on Issue {{ number repository {{ nameWithOwner }} }}
                  ... on PullRequest {{ number repository {{ nameWithOwner }} }}
                }}
                fieldValueByName(name:"Status") {{
                  ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
                }}
              }} }} }} }}
        }}"""
        out: list[dict] = []
        cursor: str | None = None
        for _ in range(20):  # 2000 cards; a bound, never a silent truncation (logged below)
            # `-f` (raw string) for owner and cursor, `-F` (typed) ONLY for number: `-F` infers
            # types, and a purely numeric org login — legal on GitHub — would be coerced to Int
            # against `$owner:String!` and fail a read the old CLI path handled fine.
            args = ["api", "graphql", "-f", f"query={query}",
                    "-f", f"owner={self.owner}", "-F", f"number={self.number}"]
            if cursor:
                args += ["-f", f"cursor={cursor}"]
            try:
                data = _gh_json(args, self.token)
            except RuntimeError as exc:
                # `gh api graphql` exits non-zero whenever the response carries GraphQL errors,
                # and a project that is not under THIS root arrives exactly that way
                # (`organization: NOT_FOUND` is an error, not a null) — the caller answers that by
                # trying the other root. ANY OTHER failure is the call not working, and reading it
                # as "wrong root" is what bought the hundredfold read on a 503 afternoon (#132).
                if not _is_wrong_root(str(exc)):
                    raise BoardUnreadable(
                        f"could not read board {self.owner}/{self.number} under {root}: "
                        f"{str(exc)[:200]}") from exc
                log.info("board %s/%s is not a %s project (%s)",
                         self.owner, self.number, root, str(exc)[:120])
                return None
            project = ((data.get("data") or {}).get(root) or {}).get("projectV2")
            if not project:
                log.info("board %s/%s: the %s root carried no project",
                         self.owner, self.number, root)
                return None
            items = project.get("items") or {}
            for node in items.get("nodes") or []:
                content = node.get("content") or {}
                field = node.get("fieldValueByName") or {}
                out.append({"id": node.get("id"), "number": content.get("number"),
                            "repo": (content.get("repository") or {}).get("nameWithOwner") or "",
                            "status": field.get("name") or ""})
            page = items.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return out
            cursor = page.get("endCursor")
        log.warning("board %s/%s has more than 2000 cards — this read stopped there, so the "
                    "queue may be missing items", self.owner, self.number)
        return out

    def _board_items_via_cli(self) -> list[dict]:
        """The old path, kept only for boards the GraphQL query cannot address (a user-owned
        project). Costs one request PER CARD — see `_board_items`."""
        items = _gh_json(
            ["project", "item-list", self.number, "--owner", self.owner,
             "--format", "json", "--limit", "800"],
            self.token,
        ).get("items", [])
        return [{"id": it.get("id"), "number": (it.get("content") or {}).get("number"),
                 "repo": (it.get("content") or {}).get("repository") or "",
                 "status": it.get("status") or ""} for it in items]

    def _item_id(self, issue_number: int, issue_url: str, repo: str = "") -> str | None:
        """The project item id for (number, repo). The repo is part of the identity (C-18): on a
        multi-repo board `…-api#3` and `…-web#3` are two cards, and matching by number alone
        moves whichever the scan met first. A caller without a repo (a pre-C-18 shape, or a
        provider whose items carry none) matches by number, today's behaviour."""
        key = (issue_number, repo)
        if key in self._item_ids:
            return self._item_ids[key]
        try:
            # idempotent: adds the issue to the project if not already there
            self.add_item(issue_url=issue_url)
        except Exception as exc:  # noqa: BLE001 — the scan below is the authority on presence
            log.warning("OPENFACTORY_BOARD_ADD_FAILED %s/%s issue=%s (%s) — looking for "
                        "an existing "
                        ""
                        "card",
                        self.owner, self.number, issue_number, str(exc)[:160])
        for it in self._board_items():
            if it.get("number") != issue_number or not it.get("id"):
                continue
            if repo and it.get("repo") and it["repo"] != repo:
                continue
            self._item_ids[key] = it["id"]
            return it["id"]
        return None

    def columns(self) -> dict[str, str] | None:
        """`{ticket ref: column}` for the whole board — the BoardAdapter read (see adapters/board).

        `None` when it could not be read, `{}` for a genuinely empty board: three separate bugs in
        this codebase came from collapsing those two into one value.

        STRINGIFIED AT THIS EDGE (C-05). GitHub's own item number IS an integer, and it stays one
        inside this adapter — the conversion happens here, on the way OUT through the port, which
        is the whole point of having a port: the vendor's shape stops at its own boundary.

        QUALIFIED AT THIS EDGE TOO (C-18): a card whose repo is not the default leaves as
        `owner/name#n`, so two same-numbered issues from different repos never collapse into one
        key — a board that thinks two tickets are one moves the wrong card, silently."""
        try:
            return {qualify_ref(it.get("repo") or "", it["number"], self._default_repo):
                    (it.get("status") or "")
                    for it in self._board_items() if it.get("number")}
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read the columns of %s/%s (%s) — the caller must treat this "
                        "as UNREADABLE, never as an empty board", self.owner, self.number, exc)
            return None

    def column_names(self) -> list[str] | None:
        """The Status field's options, in board order — which columns EXIST.

        Free: `_ensure_meta` already resolves them to map a column name to its option id, so this
        exposes a fact the adapter had all along and no caller could reach. That gap is why
        `openfactory doctor` asked `columns()` instead and reported every empty board as broken."""
        try:
            self._ensure_meta()
        except Exception as exc:  # noqa: BLE001 — unreadable is NOT "has no columns"
            log.warning("could not read the columns of %s/%s (%s) — the caller must treat this as "
                        "UNREADABLE, never as a board without columns", self.owner, self.number,
                        exc)
            return None
        return list(self._option_ids)

    def items_in_status(self, status: str) -> list[str]:
        """Issue refs whose board Status is `status` (e.g. 'TO-DO') — the pickup queue. Order
        follows the board.

        Returns strings, converted here (C-05). Three of this method's four callers already wrote
        `[str(n) for n in ...]` around it, and the in-memory fake in `testing/local_flow.py`
        already declared `list[str]` — the port said `int` and almost nothing believed it.

        Qualified when the card's repo is not the default (C-18) — the pickup queue is where the
        repository starts travelling WITH the ticket, so everything downstream (the clone, the
        tracker call, the board move) acts on the card's own repo."""
        return [qualify_ref(it.get("repo") or "", it["number"], self._default_repo)
                for it in self._board_items()
                if it.get("status") == status and it.get("number")]


    def url(self) -> str:
        """`https://github.com/{orgs|users}/{owner}/projects/{n}` — see `BoardAdapter.url`.

        `/orgs/` OR `/users/`, ASKED. A user-owned board lives at `/users/<login>/projects/<n>`
        and the `/orgs/` URL 404s: an operator clicked the panel's Board button and landed on a
        page that does not exist (2026-08-14). The probe lived in `api/app.py` until this method
        existed to hold it — a `gh api` call, in the panel, about one vendor.
        """
        if not (self.owner and self.number):
            return ""
        return f"https://{_gh_host()}/{_owner_kind(self.owner)}/{self.owner}/projects/{self.number}"

    def pickup_column(self) -> str:
        """`TO-DO` here, or whatever this client renamed it to. See `BoardAdapter.pickup_column`.

        The platform's own literal happens to match this provider's default, which is exactly why
        the missing question went unnoticed for so long: on the only board anybody tested, the
        guess was right."""
        return self._columns.get("todo") or DEFAULT_COLUMNS["todo"]

    def set_status(self, *, issue: str, issue_url: str, state: JobState,
                   needs_person: bool | None = None) -> bool:
        """Move the card to the Status mapped from `state`. Returns True on success. If the
        mapped column doesn't exist on this board yet (e.g. 'Needs Action' before the owner
        adds it in the UI — GitHub has no API to create it), fall back to Backlog so a parked
        ticket still leaves the active columns instead of getting stuck showing 'In progress'."""
        from openfactory.adapters.tracker.base import column_key

        key = column_key(state, needs_person=needs_person)
        name = self._columns.get(key or "")
        if not name:
            return False
        return self.set_column(issue=issue, issue_url=issue_url, name=name)

    def place_after(self, *, issue: str, issue_url: str, after: str | None, column: str) -> bool:
        """Put the card right after `after` in the project's item order — the top when `after` is
        None — with `updateProjectV2ItemPosition` (see `Rankable`).

        POSITION IS PER PROJECT, NOT PER COLUMN, in Projects v2: the board view groups one ordered
        list by Status, so "first among the Backlog cards" and "first in the project" are the same
        move for a card that is in Backlog. `column` is therefore not consulted here.

        THE ANCHOR IS LOOKED UP, NEVER ADDED. `_item_id` adds the issue to the project before it
        scans, which is right for the card being placed and wrong for its neighbour — the
        neighbour is already on the board or the caller's order is nonsense, and adding it on a
        typo would put a stranger's issue on a client's board."""
        self._ensure_meta()
        repo, bare = split_repo_ref(issue, self._default_repo)
        issue_number = ref_number(bare)
        item = (self._item_id(issue_number, issue_url, repo=repo)
                if issue_number is not None else None)
        after_item = None
        if after:
            arepo, abare = split_repo_ref(after, self._default_repo)
            anumber = ref_number(abare)
            after_item = (self._existing_item_id(anumber, repo=arepo)
                          if anumber is not None else None)
        if not (item and self._project_id) or (after and not after_item):
            why = ("no card for the issue" if not item
                   else f"no card for {after!r} to place it after" if after and not after_item
                   else "the project could not be resolved")
            log.error("OPENFACTORY_BOARD_RANK_FAILED %s/%s issue=%s after=%r: %s",
                      self.owner, self.number, issue_number, after, why)
            return False
        args = ["api", "graphql", "-f", "query=" + """
            mutation($project:ID!, $item:ID!, $after:ID) {
              updateProjectV2ItemPosition(input:{
                projectId:$project, itemId:$item, afterId:$after})
                { items(first:1) { totalCount } } }""",
                "-f", f"project={self._project_id}", "-f", f"item={item}"]
        if after_item:
            args += ["-f", f"after={after_item}"]
        p = _run_gh(args, self.token)
        if p.returncode != 0:
            log.error("OPENFACTORY_BOARD_RANK_FAILED %s/%s issue=%s after=%r: %s",
                      self.owner, self.number, issue_number, after, (p.stderr or "")[:300])
            return False
        return True

    def _existing_item_id(self, issue_number: int, *, repo: str = "") -> str | None:
        """The item id of a card ALREADY on the board, by number (and repo, C-18) — or None."""
        key = (issue_number, repo)
        if key in self._item_ids:
            return self._item_ids[key]
        for it in self._board_items():
            if it.get("number") != issue_number or not it.get("id"):
                continue
            if repo and it.get("repo") and it["repo"] != repo:
                continue
            self._item_ids[key] = it["id"]
            return it["id"]
        return None

    def set_column(self, *, issue: str, issue_url: str, name: str) -> bool:
        """Move the card to a column BY NAME. `set_status` is the state-mapped wrapper over this.

        Exists because not every placement comes from a job state: the product module files new
        issues straight into Backlog (ADR-0019), and no `JobState` means "written down, not
        started". Keeping the by-name primitive separate also keeps the money gate honest — a
        caller that may only ever use Backlog passes the literal, and cannot reach TO-DO by
        picking a different state."""
        self._ensure_meta()
        option = self._option_ids.get(name) or (
            self._option_ids.get(self._columns["backlog"])
            if name == self._columns["needs_action"] else None)
        # BACK TO GITHUB'S OWN SHAPE, here at the entrance (C-05). The port hands this adapter the
        # provider's ref as a string; `_item_id` matches it against `it["number"]` from GraphQL,
        # which is an int — and `"412" == 412` is False in Python, silently. Without this line
        # every card move would find no item and log OPENFACTORY_BOARD_MOVE_FAILED "no card for the
        # issue" on a card sitting right there. A GitHub ref is always numeric, so the conversion
        # cannot fail for this provider; `None` would mean somebody handed a GitHub board a Jira
        # ref, which is a configuration error the log below already names.
        #
        # The ref may carry its repository (C-18, `owner/name#n`): split first, and let the
        # (number, repo) pair find the card — on a multi-repo board the number alone is ambiguous.
        repo, bare = split_repo_ref(issue, self._default_repo)
        issue_number = ref_number(bare)
        item = (self._item_id(issue_number, issue_url, repo=repo)
                if issue_number is not None else None)
        if not (option and item and self._status_field_id and self._project_id):
            # A card that silently never moves is indistinguishable from a poller that stopped —
            # every False leaves a trace, so the caller's bool has a WHY next to it in the log.
            why = (f"the board has no {name!r} column" if not option
                   else "no card for the issue" if not item
                   else "the board has no Status field")
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r: %s",
                      self.owner, self.number, issue_number, name, why)
            return False
        # OUR OWN MUTATION, for the reason `add_item` states at length: `gh project item-edit`
        # types the owner login and demands `read:org`, which a personal account's token has no
        # reason to carry — so on a user-owned board every move failed with *"missing required
        # scopes"* while the job ran on and the card sat in TO-DO (pilot, 2026-08-15). The reads
        # were moved to GraphQL for this same asymmetry; this is the write half.
        p = _run_gh(["api", "graphql", "-f", "query=" + """
            mutation($project:ID!, $item:ID!, $field:ID!, $option:String!) {
              updateProjectV2ItemFieldValue(input:{
                projectId:$project, itemId:$item, fieldId:$field,
                value:{singleSelectOptionId:$option}}) { projectV2Item { id } } }""",
                     "-f", f"project={self._project_id}", "-f", f"item={item}",
                     "-f", f"field={self._status_field_id}", "-f", f"option={option}"],
                    self.token)
        if p.returncode != 0:
            log.error("OPENFACTORY_BOARD_MOVE_FAILED %s/%s issue=%s -> %r: %s",
                      self.owner, self.number, issue_number, name,
                      (p.stderr or "").strip()[:200])
            return False
        return True


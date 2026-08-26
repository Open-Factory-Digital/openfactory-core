"""GitHubIssuesTracker — tickets as GitHub Issues + a Projects v2 board (v1).

The board must move: when a project is registered with a GitHub Projects board
(owner + number), each state transition moves the card's Status column. Without a
board configured, the state falls back to a single transitioning `openfactory:<state>`
label. Runs as the bot when a token is provided (GH_TOKEN), else ambient auth.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

from openfactory.adapters.tracker.base import (
    Budget,
    TicketComment,
    TicketSummary,
    TrackerAdapter,
    list_state,
)
from openfactory.adapters.tracker.github_project import GitHubProjectBoard
from openfactory.adapters.tracker.parse import parse_ticket_body
from openfactory.contracts import JobState, Ticket
from openfactory.contracts.refs import canonical_ref, split_repo_ref

log = logging.getLogger("openfactory.tracker.github")

#: The state label this tracker writes when a board refuses a move (or there is no board) — the
#: fallback carrier of truth, on the CLIENT's own issue. It carries the product's name for the
#: same reason the branches do (#106 item 5): it is the name a client reads.
_STATE_LABEL_PREFIX = "openfactory:"

#: The fields a `TicketSummary` is built from, in `gh`'s spelling. One string because the sweep and
#: the incremental refresh must ask for exactly the same shape — two lists is how a field arrives on
#: one path and is missing on the other, which reads downstream as a card that changed.
_LIST_FIELDS = "number,title,body,state,stateReason,labels,assignees,updatedAt"

#: What `limit=0` ("everything") costs at most. `gh issue list` defaults to 30 and has no "all", so
#: some number has to go on the wire; this one is high enough that no board this platform runs comes
#: near it and low enough to bound a single read. Reaching it is LOGGED, because a silently
#: truncated board is a board that reads as smaller than it is.
_LIST_CEILING = 1000


class GitHubIssuesTracker(TrackerAdapter):
    def __init__(
        self,
        repo: str,
        *,
        board_owner: str | None = None,
        board_number: str | None = None,
        token: str | None = None,
        token_provider=None,
        board_columns: dict[str, str] | None = None,
    ) -> None:
        self.repo = repo  # "owner/name"
        self._static_token = token
        self._token_provider = token_provider  # re-mints a fresh token at use (long jobs)
        # The PROVIDER goes in, never `self.token`: evaluating the property here would bake a
        # ~1h App token string into the board, and every board move after expiry would fail
        # silently while the issue ops (which resolve per call) kept working.
        self.board = (
            GitHubProjectBoard(board_owner, board_number, token=token,
                               token_provider=token_provider, columns=board_columns,
                               default_repo=repo)
            if board_owner and board_number
            else None
        )

    @property
    def token(self) -> str | None:
        return self._token_provider() if self._token_provider else self._static_token

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.token:
            env["GH_TOKEN"] = self.token
        return env

    _RATE_MARKERS = ("rate limit", "abuse detection", "submitted too quickly", "retry your request")

    def _gh(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        try:
            p = subprocess.run(
                ["gh", *args], capture_output=True, text=True, timeout=timeout, env=self._env()
            )
        except FileNotFoundError:
            # A stranger's first hour must not end in a stack trace about a binary the docs never
            # named (pre-pilot review, 2026-08-09). One refusal, one remedy, greppable.
            raise RuntimeError(
                "the `gh` CLI is not installed — the GitHub tracker/board speak through it. "
                "Install it (https://cli.github.com) and run `gh auth login` (or set "
                "OPENFACTORY_BOT_TOKEN / the GitHub App variables).") from None
        # RESILIENCE: GitHub's SECONDARY / abuse-detection limits clear in seconds — one brief
        # backoff + retry rides them out instead of failing the whole ticket. (A primary limit,
        # minutes away, still fails here and the caller degrades; the poller's own budget check
        # keeps us from spending into it in the first place.)
        if p.returncode != 0 and any(m in (p.stderr or "").lower() for m in self._RATE_MARKERS):
            time.sleep(8)
            p = subprocess.run(
                ["gh", *args], capture_output=True, text=True, timeout=timeout, env=self._env()
            )
        return p

    def _write(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        """Run a mutating `gh` call and RAISE when the forge refused it.

        `gh` reports failure only in its exit code, and this adapter had no one place that read it —
        so each method decided for itself and three forgot. What that bought, in this repository's
        own history: a client told a card was closed while it was still open, and the impediment a
        real failure opened CLOSED by the write that never happened.

        The contract lives in `adapters/tracker/base.py`: returning is this adapter saying the
        change is on the ticket, and best-effort is the CALLER's decision, written as a `try` where
        the next reader can see it.
        """
        p = self._gh(args, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(
                f"gh {' '.join(args[:2])} failed ({p.returncode}): "
                f"{(p.stderr or p.stdout or '')[-300:]}")
        return p

    def _locate(self, ref: str) -> tuple[str, str]:
        """(the repository this ref lives in, the bare number) — C-18.

        A ref may carry its own repository (`owner/name#12`): one board routes cards to several
        source repos, and every per-ticket op below must act on the CARD's repo, not this
        adapter's default. A bare ref resolves to `self.repo`, byte-for-byte today's behaviour."""
        repo, bare = split_repo_ref(ref, self.repo)
        return repo, bare.lstrip("#")

    def get_ticket(self, ref: str) -> Ticket:
        repo, num = self._locate(ref)
        p = self._gh(
            ["issue", "view", num, "--repo", repo,
             # `state` because `scan_todo` refuses to re-run a delivered ticket and cannot know
             # without asking — it was never in this list, so the guard read a default forever.
             "--json", "number,title,body,labels,author,state"]
        )
        if p.returncode != 0:
            raise RuntimeError(f"gh issue view failed: {p.stderr}")
        data = json.loads(p.stdout)
        ticket = parse_ticket_body(
            id=f"#{data['number']}", title=data["title"],
            body=data.get("body") or "", repo=repo,
        )
        ticket.labels = [(lbl.get("name") or "").lower() for lbl in data.get("labels", [])]
        ticket.author = (data.get("author") or {}).get("login") or None
        ticket.state = str(data.get("state") or "").lower() or None
        return ticket

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> None:
        # `needs_person` carries what the state cannot (#166): an armed auto-merge and a
        # human merge gate are both `pr_open`, and only the caller knows which.
        repo, bare = self._locate(ref)
        num = int(bare)
        moved = True
        if self.board is not None:
            # the possibly-qualified ref goes THROUGH: the board splits it against its own
            # default, and on a multi-repo board the (number, repo) pair is what finds the card
            moved = self.board.set_status(
                needs_person=needs_person,
                issue=str(ref).strip().lstrip("#"),
                issue_url=self.ticket_url(ref),
                state=state,
            )
        if self.board is None or not moved:
            # The board refused/failed the move (the board logs the why). The openfactory:<state>
            # label is the fallback carrier of truth: a card stuck in its old column with the
            # platform recording the transition as done is a silent forever-wait for whoever
            # watches the board.
            if self.board is not None:
                log.error("OPENFACTORY_BOARD_MOVE_FAILED %s#%s -> %s — falling back to the "
                          "openfactory:<state> label", repo, num, state.value)
            self._transition_label(str(num), state, repo=repo)
        if reason:
            self.comment(ref, f"[{state.value}] {reason}")

    def comment(self, ref: str, body: str) -> None:
        repo, num = self._locate(ref)
        self._write(["issue", "comment", num, "--repo", repo, "--body", body])

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        """`gh issue view --json comments`, which answers OLDEST FIRST (verified live on #81 of
        this repository: 16:42 → 18:01 → 21:33). So the port's promised order is what GitHub
        already gives, and `limit` slices off the FRONT.

        `None` on any failure — a missing issue exits 1 with *"Could not resolve to an issue"*, and
        a rate limit exits 1 too. Both mean the same thing to the caller: it did not get to look.
        """
        repo, num = self._locate(ref)
        p = self._gh(["issue", "view", num, "--repo", repo, "--json", "comments"])
        if p.returncode != 0:
            log.warning("could not read the comments of %s#%s (%s) — the caller is being told "
                        "UNREADABLE, not empty", repo, num, (p.stderr or "")[-200:])
            return None
        try:
            payload = json.loads(p.stdout or "{}")
        except ValueError:
            log.warning("gh answered unparseable JSON for the comments of %s#%s", repo, num)
            return None
        raw = payload.get("comments")
        if not isinstance(raw, list):
            # A 200 without the field is not a ticket with no comments — it is a shape this
            # adapter does not recognise, and the whole reason the method returns an option type.
            log.warning("gh returned no `comments` field for %s#%s (%r) — reading as UNREADABLE",
                        repo, num, sorted(payload))
            return None
        found = [
            TicketComment(
                # `login`, not `name`: the display name is optional on GitHub and empty for most
                # accounts, and a bot posts under `<app>[bot]`, which is the one spelling that lets
                # a reader tell the platform's own note from a person's.
                author=str((c.get("author") or {}).get("login") or ""),
                body=str(c.get("body") or ""),
                created_at=str(c.get("createdAt") or ""),
            )
            for c in raw
        ]
        return found[-limit:] if limit > 0 else found

    def list_tickets(self, *, state: str = "all", updated_since: str = "",
                     limit: int = 0) -> list[TicketSummary] | None:
        """`gh issue list`, ordered by last update.

        THE SORT IS NOT FREE AND THE BRANCH SAYS WHY. `gh issue list` has no `--sort`; ordering by
        update means `--search "sort:updated-desc"`, which routes the read through GitHub's SEARCH
        rather than the plain issue list — a narrower quota on the credential the poller and every
        job share, and one this deployment has already exhausted once. The plain path orders by
        CREATION (verified: #96 came back before #95, created-desc, while their update times run
        the other way), so it is only usable when nothing is being dropped. Hence: search when the
        answer is truncated or filtered, plain list when everything comes back anyway, and a local
        sort in both cases so the port's promise holds whichever route ran.
        """
        # `gh --state` happens to spell these exactly as the port does, so the shared validator IS
        # the translation here. It still goes through it: the next provider's does not.
        wanted = list_state(state)
        ceiling = limit if limit > 0 else _LIST_CEILING
        args = ["issue", "list", "--repo", self.repo, "--state", wanted,
                "--limit", str(ceiling), "--json", _LIST_FIELDS]
        terms = []
        if updated_since:
            terms.append(f"updated:>={updated_since}")
        if terms or limit > 0:
            terms.append("sort:updated-desc")
        if terms:
            args += ["--search", " ".join(terms)]

        # 120s rather than the 60 every other call here uses: a full sweep is up to `_LIST_CEILING`
        # issues WITH their bodies, which is pages of GraphQL, not one request.
        p = self._gh(args, timeout=120)
        if p.returncode != 0:
            log.warning("could not list the tickets of %s (%s) — the caller is being told "
                        "UNREADABLE, not empty", self.repo, (p.stderr or "")[-200:])
            return None
        try:
            rows = json.loads(p.stdout or "[]")
        except ValueError:
            log.warning("gh answered unparseable JSON listing the tickets of %s", self.repo)
            return None
        if not isinstance(rows, list):
            return None
        # ONLY WHEN THE CEILING WAS OURS. A caller that asked for three and got three learned
        # nothing; a caller that asked for EVERYTHING and got exactly `_LIST_CEILING` is holding a
        # partial board and has no way to know it, because the ceiling is this module's own number.
        if limit <= 0 and len(rows) >= ceiling:
            log.warning("%s answered with %d tickets, which is this adapter's own ceiling — the "
                        "board is larger than what the caller is about to judge",
                        self.repo, ceiling)

        found = [
            TicketSummary(
                # `canonical_ref`, so `142` and `#142` are one ticket and not two. `get_ticket`
                # renders `#142` for a human; a key does not get to be decorated.
                ref=canonical_ref(row.get("number")),
                title=str(row.get("title") or ""),
                body=str(row.get("body") or ""),
                # GitHub's GraphQL enums arrive SHOUTING — `"CLOSED"`, `"NOT_PLANNED"` (verified
                # live). The port's vocabulary is lowercase, and `triage.Ticket.delivered` compares
                # against the literal `"not_planned"`, so the fold happens here rather than in each
                # of the readers that would otherwise each have to remember.
                state=str(row.get("state") or "open").lower(),
                state_reason=str(row.get("stateReason") or "").lower(),
                labels=[str(x.get("name") or "") for x in (row.get("labels") or [])],
                assignees=[str(x.get("login") or "") for x in (row.get("assignees") or [])],
                updated_at=str(row.get("updatedAt") or ""),
            )
            for row in rows
        ]
        found.sort(key=lambda t: t.updated_at, reverse=True)
        return found

    def ticket_url(self, ref: str) -> str:
        """The web URL for this issue, honouring the ref's own repository (C-18) and the host.

        `GH_HOST` because a GitHub Enterprise deployment is not on github.com, and a link there is
        not merely dead: a same-named repository on the public site may belong to somebody else."""
        import os

        repo, num = self._locate(ref)
        host = (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") or "github.com").strip()
        return f"https://{host}/{repo}/issues/{num}"

    def budget(self) -> Budget:
        """The rate limit of the credential this tracker holds — the worst of graphql/core.

        THE ONE VENDOR THAT REPORTS ONE, through the port. Before this method the core reached
        `github_rate` by module name from four places, so every deployment paid for a `gh`
        subprocess whether or not it had a GitHub tracker. `BudgetUnreadable` propagates: the
        caller decides what an unread budget means on its surface."""
        from openfactory.adapters.tracker.github_project import github_rate

        return github_rate(self.token)

    def person(self, ref: str) -> dict:
        """`gh api users/<login>` — see `TrackerAdapter.person`.

        MOVED HERE FROM `runtime/slack/people.py`, where it was the only person resolution the
        mention path had and ran for every tracker's refs."""
        login = (ref or "").strip().lstrip("@")
        if not login:
            return {}
        try:
            p = self._gh(["api", f"users/{login}"])
        except Exception as exc:  # noqa: BLE001 — the contract says NEVER RAISES, and it means it
            # `_gh` raises when the `gh` binary is absent, and lets a timeout out. Both are
            # ordinary on a machine composing a Slack message, and this method's caller is
            # mid-sentence: an exception here loses the whole message rather than one mention.
            log.info("could not look up %s on GitHub (%s) — they will be named, not notified",
                     login, exc)
            return {"id": login}
        if p.returncode != 0:
            # THE LOGIN ALONE STILL NAMES THEM in text. A private profile, a rate-limited quota
            # and a login that does not exist are the same answer here, and all three are better
            # served by a plain name than by nothing.
            return {"id": login}
        try:
            data = json.loads(p.stdout or "{}")
        except ValueError:
            return {"id": login}
        return {"id": login, "name": data.get("name") or "",
                "email": (data.get("email") or "").lower()}

    def assignees(self, ref: str) -> list[str]:
        repo, num = self._locate(ref)
        p = self._gh(["issue", "view", num, "--repo", repo, "--json", "assignees"])
        if p.returncode != 0:
            # "nobody is assigned" is an ANSWER, and it decides who a parked ticket goes back to.
            raise RuntimeError(f"gh issue view (assignees) failed: {(p.stderr or '')[-200:]}")
        return [a["login"] for a in json.loads(p.stdout).get("assignees", [])]

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        # gh only adds/removes; diff current vs desired. (GitHub App bot users can't be
        # assignees — use a real bot-account login.)
        repo, num = self._locate(ref)
        current = self.assignees(ref)
        add = [x for x in logins if x not in current]
        remove = [x for x in current if x not in logins]
        if not (add or remove):
            return
        args = ["issue", "edit", num, "--repo", repo]
        for x in add:
            args += ["--add-assignee", x]
        for x in remove:
            args += ["--remove-assignee", x]
        self._write(args)

    def add_label(self, ref: str, label: str) -> None:
        """Add a label to the ticket, creating it in the repo first if it doesn't exist yet
        (`gh issue edit --add-label` fails on a missing label). Best-effort — a labelling
        failure must never derail a job. Used to mark 'the bot is working this' on pickup."""
        repo, num = self._locate(ref)
        # idempotent create (a label the repo already has is left as-is)
        self._ensure_label(label, repo=repo)
        self._write(["issue", "edit", num, "--repo", repo, "--add-label", label])

    def remove_label(self, ref: str, label: str) -> None:
        """Remove a label from the ticket (best-effort; a missing label is a no-op)."""
        repo, num = self._locate(ref)
        self._write(["issue", "edit", num, "--repo", repo, "--remove-label", label])

    def create_ticket(self, *, title: str, body: str) -> str:
        """Create an issue and (when a board is configured) add it to the board — it lands in
        the board's default intake column (Backlog): sequencing to TO-DO stays a human
        decision by default (ADR-0013 D3)."""
        p = self._gh(["issue", "create", "--repo", self.repo,
                      "--title", title, "--body", body])
        if p.returncode != 0:
            raise RuntimeError(f"gh issue create failed: {p.stderr[:300]}")
        url = (p.stdout or "").strip().splitlines()[-1].strip()
        num = url.rstrip("/").rsplit("/", 1)[-1]
        if self.board is not None:
            try:
                self.board.add_item(issue_url=url)
            except Exception as exc:  # noqa: BLE001 — the issue exists either way
                # An issue with no card is invisible to everyone who works from the board, which
                # for this factory is everyone.
                log.error("OPENFACTORY_BOARD_ADD_FAILED #%s created but never added to the board "
                          "(%s)",
                          num, str(exc)[:200])
        return f"#{num}"

    def find_ticket(self, *, title: str) -> str | None:
        """Ref of an OPEN issue with exactly this title (splitter idempotency)."""
        p = self._gh(["issue", "list", "--repo", self.repo, "--state", "open",
                      "--search", f'in:title "{title}"', "--json", "number,title",
                      "--limit", "20"])
        if p.returncode != 0:
            # "I could not ask" is not "there is none" — and this is the gate in front of a create,
            # so conflating them files the duplicate it exists to prevent. GitHub's search carries
            # a far lower limit than issue creation, so it failing while `create` still works is
            # the ordinary case, not the exotic one.
            raise RuntimeError(f"gh issue list (search) failed: {(p.stderr or '')[-200:]}")
        for it in json.loads(p.stdout or "[]"):
            if (it.get("title") or "").strip() == title.strip():
                return f"#{it['number']}"
        return None

    def update_body(self, ref: str, body: str) -> None:
        """`gh issue edit --body-file -`: the body goes over STDIN, never as an argument.

        A requirement runs to thousands of characters and contains quotes, backticks and newlines;
        passing that on a command line is how a body gets truncated at the first surprising byte,
        or worse, how part of it is read as a flag."""
        repo, num = self._locate(ref)
        p = subprocess.run(
            ["gh", "issue", "edit", num, "--repo", repo, "--body-file", "-"],
            input=body, text=True, capture_output=True, timeout=60, check=False, env=self._env(),
        )
        if p.returncode != 0:
            # The only write here that replaces rather than appends: reporting it as landed when it
            # did not is how a card keeps criteria written against a retired requirement while
            # everybody is told it was realigned.
            raise RuntimeError(f"gh issue edit (body) failed: {(p.stderr or '')[-300:]}")

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        # `--reason` AND `--comment` ARE DIFFERENT FIELDS, and only the comment was ever set. The
        # prose went into a comment and GitHub defaulted `stateReason` to COMPLETED — so a card
        # closed as a duplicate was indistinguishable, to every reader downstream, from one that
        # shipped. `not_planned` is what `Ticket.delivered` reads.
        repo, num = self._locate(ref)
        self._write(["issue", "close", num, "--repo", repo,
                     "--reason", "completed" if delivered else "not planned",
                     "--comment", reason])

    # --- native parent/child linkage via GitHub sub-issues --------------------------------
    def _issue_rest_id(self, ref: str) -> int | None:
        """The issue's numeric REST id (NOT its #number) — the sub-issues API links by id."""
        repo, num = self._locate(ref)
        p = self._gh(["api", f"repos/{repo}/issues/{num}", "--jq", ".id"])
        if p.returncode != 0:
            return None
        try:
            return int((p.stdout or "").strip())
        except ValueError:
            return None

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        """Attach `child_ref` as a native sub-issue of `parent_ref` so the split lineage shows
        on the board and children_of can answer 'already split?'. Best-effort + idempotent:
        an already-linked child (or a repo without sub-issues) just fails quietly — the split
        never depends on it."""
        cid = self._issue_rest_id(child_ref)
        if cid is None:
            return
        prepo, pnum = self._locate(parent_ref)
        self._gh(["api", "--method", "POST",
                  f"repos/{prepo}/issues/{pnum}/sub_issues",
                  "-F", f"sub_issue_id={cid}"])

    def children_of(self, parent_ref: str) -> list[str]:
        """The parent's native sub-issues as refs ('#378', …). Empty on none, error, or a repo
        without the sub-issues API — so the caller degrades to title-level idempotency."""
        prepo, pnum = self._locate(parent_ref)
        p = self._gh(["api", "--paginate",
                      f"repos/{prepo}/issues/{pnum}/sub_issues",
                      "--jq", ".[].number"])
        if p.returncode != 0:
            return []
        return [f"#{n.strip()}" for n in (p.stdout or "").splitlines() if n.strip()]

    def _ensure_label(self, label: str, repo: str | None = None) -> None:
        """Create the label if the repo lacks it — `gh issue edit --add-label` fails on a missing
        one, and a fallback that cannot work on a fresh repository is not a fallback."""
        self._gh(["label", "create", label, "--repo", repo or self.repo, "--color", "5319e7",
                  "--description", "worked by the OpenFactory bot", "--force"])

    def _transition_label(self, num: str, state: JobState, repo: str | None = None) -> None:
        """Fallback when no board: keep exactly one state label on the issue.

        THIS IS THE CARRIER OF TRUTH when the board refused the move, so it is the last thing that
        may fail quietly: a card stuck in its old column while the platform records the transition
        as done is the silent forever-wait the whole state machine exists to prevent."""
        repo = repo or self.repo
        want = f"{_STATE_LABEL_PREFIX}{state.value}"
        self._ensure_label(want, repo=repo)
        view = self._gh(["issue", "view", num, "--repo", repo, "--json", "labels"])
        stale = []
        if view.returncode == 0:
            labels = [lbl["name"] for lbl in json.loads(view.stdout).get("labels", [])]
            stale = [lbl for lbl in labels if lbl.startswith(_STATE_LABEL_PREFIX) and lbl != want]
        args = ["issue", "edit", num, "--repo", repo, "--add-label", want]
        for lbl in stale:
            args += ["--remove-label", lbl]
        self._write(args)

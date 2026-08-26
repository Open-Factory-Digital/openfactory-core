"""Reading the board into something triage can judge.

`triage.Ticket` is deliberately not the pipeline's ticket: this reads the WHOLE board, including
issues the factory has never touched and never will, and it needs the two fields that stop it
misreading a column — the labels and the body.

BEST-EFFORT, ALWAYS. A board this cannot read produces an empty list and a reason, never an
exception: the product role reporting "I couldn't read the board" is useful, and a traceback in a
chat listener is not.

SWEEP ONCE, THEN ONLY WHAT CHANGED. Every operation this role has — the situation it opens with, a
queue proposal, a triage, a refinement — wants the board, and each of them read the whole thing: 300
issues plus 400 project items, two heavy GraphQL queries. On 2026-07-27 that helped exhaust the
GitHub App installation's hourly quota, and the first casualty was a real job: #478 parked with "API
rate limit exceeded", and then the tech-lead could not diagnose the park because the same limit
blocked it too.

A cache would only have made the same full read less often. So the first read is full and every one
after it asks the tracker for the tickets UPDATED SINCE — which on a quiet afternoon is none, and
costs one cheap query instead of two expensive ones. The quota is shared by the poller, every job
and every human at a terminal, so a read here is never free. The watermark goes back in the
PROVIDER's own spelling and is therefore stored verbatim: it is fed into that provider's own date
syntax, and a stamp from anywhere else is accepted by at least one vendor and silently matches
nothing.

WHAT INCREMENTAL CANNOT SEE, stated rather than discovered: a card DRAGGED between columns without
touching its issue changes nothing the tracker reports as an update. So the columns are re-read
whenever anything at all changed, and a full sweep runs again after `_FULL_AFTER` regardless — the
board is correct within that window, not within a second, and every caller here tolerates that. None
of them tolerates a rate limit.

AND IT READS THROUGH THE PORT NOW (#95/#97). Everything above was true and GitHub-only: the tickets
arrived from `gh issue list` and the columns from the provider registry, so on an Azure DevOps
deployment the issue half failed first and the neutral half below it executed exactly never. The
module answered that with a NAMED refusal rather than an empty board, which was the right shape and
still an apology — the capability simply did not exist. `TrackerAdapter.list_tickets` is what it was
waiting for: it answers with the same fields this sweep judges on (`state_reason`, `assignees`,
`updated_at`), ordered newest-updated-first, and it draws the one distinction this whole file is
built around — `None` = I could not read, `[]` = I read and there is nothing.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from pydantic import BaseModel, field_validator

from openfactory.adapters.forge.registry import repo_of
from openfactory.contracts.refs import canonical_ref, ref_sort_key
from openfactory.product.triage import Ticket

log = logging.getLogger("openfactory.product")

#: How many issues to pull. A board with thousands of closed issues would otherwise cost minutes on
#: every triage; the interesting ones are open or recently closed.
#:
#: IT IS A WINDOW ON THE NEWEST-UPDATED CARDS, which it was not before. `gh issue list --limit 300`
#: with no search term orders by CREATION, so the 300 this reader took were the 300 most recently
#: FILED — on a board where the interesting card is the one that moved. The port promises
#: newest-updated-first whatever route the provider takes to answer, so the same number now buys the
#: 300 cards a triage would have chosen.
_LIMIT = 300

#: How many CHANGED tickets one incremental read merges. Its own constant rather than a literal,
#: because it is the ceiling that decides what a quiet refresh can silently miss: more than this
#: many cards updated since the watermark and the oldest of them wait for the next full sweep.
_REFRESH_LIMIT = 100

#: How long before the whole board is swept again from scratch. The backstop for what an
#: incremental read cannot see — chiefly a card moved between columns without its issue being
#: touched. Hours, not minutes: that is a stale COLUMN, not a stale ticket, and no caller here
#: makes a decision that a few hours of column drift would reverse.
_FULL_AFTER = 6 * 3600.0

#: The board as we last saw it, per project: `(swept_at, last_update_seen, tickets)`. In process,
#: so a worker replaced by a deploy pays one full sweep — which is the right trade against
#: persisting a snapshot that could then be wrong in a way nobody notices.
_SNAPSHOT: dict[str, tuple[float, str, list[Ticket]]] = {}
_LOCK = threading.Lock()


def forget_board(project_name: str | None = None) -> None:
    """Drop what we remember — after a write that changes the board, and in tests."""
    with _LOCK:
        if project_name is None:
            _SNAPSHOT.clear()
        else:
            _SNAPSHOT.pop(project_name, None)


def _credential(project, token: str | None) -> str | None:
    """The credential the TICKETS and the BOARD travel on — this project's, not the process's.

    THE BOARD IS A TRACKER OBJECT AND SO IS EVERY READ BELOW IT, which is why this is not the token
    the caller happens to be holding. `ProductModule.token` resolves through `forge_token_for`, so
    on an Azure project it is that project's Azure PAT and on a GitHub project the GitHub one —
    right for cloning the documentation repository, and the wrong axis for asking a tracker
    anything. A deployment now hosts projects on different vendors, and the failure does not
    announce itself: a token that authenticates against the wrong system answers an empty search
    (F-02 on fx-jira, where a board with a ticket in TO-DO produced a pickup queue of `[]`).

    `tracker_token_for` already falls back to the DEPLOYMENT's own value when the project names no
    variable, so every GitHub project that exists behaves byte for byte as it did. The caller's
    token is consulted only after that — the one case being a worker with no ambient tracker
    credential at all, where `ProductModule.token` may be carrying a freshly minted GitHub App
    token and dropping it would turn a working board read into a failing one. Same order,
    deliberately, as `ProductModule._board()`."""
    from openfactory.credentials import tracker_token_for

    return tracker_token_for(project) or token


def _tracker(project, credential: str | None):
    """The project's tracker, through the registry — or None when the deployment does not name one.

    NEVER A CONCRETE CLASS AND NEVER A DEFAULT KIND. An unknown (or unset) tracker is a
    configuration error, and `build_tracker` raises rather than falling back to GitHub for the
    reason its own docstring gives: a supported-LOOKING provider pointed at the wrong system is the
    one failure worse than an unsupported one. Caught here because this reader's contract is
    `(tickets, error)` — a chat listener must get the sentence, not the traceback."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.factory import _bot_token_provider

    try:
        return build_tracker(project, token=credential,
                             token_provider=None if credential else _bot_token_provider())
    except ValueError as exc:
        log.error("product board: no tracker for %s (%s) — the board cannot be read at all",
                  getattr(project, "name", "?"), exc)
        return None


def _days_ago(stamp: str) -> int | None:
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        return max(0, (datetime.now(UTC) - then).days)
    except Exception as exc:  # noqa: BLE001 — an unparseable date is not a reason to lose a ticket
        # None means "age unknown", which is right; it also means every staleness rule quietly
        # stops applying to this ticket, so it must be visible when it is happening to many.
        log.debug("could not read the timestamp %r (%s) — this ticket has no age", stamp, exc)
        return None


def read_board(project, *, token: str | None = None, limit: int = _LIMIT,
               fresh: bool = False, tracker=None) -> tuple[list[Ticket], str]:
    """`(tickets, error)` — swept once, then refreshed with only what changed.

    `fresh=True` forces a full sweep, for the caller that just changed the board and has to see its
    own write. The error is a sentence for a human, not a traceback.

    `tracker` is the injection point for a caller that already holds one (and for tests). Left out,
    this builds the project's own through the registry — the reader is reached from a chat listener
    and from a scheduled sweep, and neither of them has an adapter to hand."""
    name = str(getattr(project, "name", "") or "")
    repo = repo_of(project)
    if not repo:
        return [], "this project does not name a repository"
    if tracker is None:
        tracker = _tracker(project, _credential(project, token))
        if tracker is None:
            # A DEPLOYMENT WITH NO TRACKER IS UNREADABLE, NEVER EMPTY. Every caller here branches
            # on `error`, and an empty board is an ANSWER: "nothing is queued", "no findings",
            # "the open questions resolved themselves" are the three wrong answers this module has
            # already produced from a board it could not read.
            return [], (f"this deployment does not name a tracker for {name or repo}, so there is "
                        f"nothing to read the board from — treat this as an unreadable board, "
                        f"never as an empty one")
    with _LOCK:
        snapshot = None if fresh else _SNAPSHOT.get(name)

    if snapshot and (time.monotonic() - snapshot[0]) < _FULL_AFTER:
        tickets, error = _refresh(snapshot, project=project, tracker=tracker, repo=repo,
                                  token=token, name=name)
        if not error:
            return tickets, ""
        # An incremental read that failed tells us nothing about the board — fall through to a full
        # sweep rather than serving a snapshot we just failed to confirm.

    return _sweep(project=project, tracker=tracker, repo=repo, token=token, name=name, limit=limit)


def _list(tracker, repo: str, **kw) -> list | None:
    """`tracker.list_tickets(**kw)` — `None` when it could not be read, and never an exception.

    THE PORT PROMISES NOT TO RAISE (`adapters/tracker/base.py`: the read side degrades, because its
    callers are a chat answer and a board sweep). This is the belt for the day an implementation
    breaks that promise: this module's contract is `(tickets, error)`, and a traceback out of a
    Slack listener is the one outcome it exists to prevent. It is a belt and not a policy — the
    failure is logged with its traceback, because an adapter raising here is a defect in the
    adapter, not a condition of the board."""
    try:
        found = tracker.list_tickets(**kw)
    except Exception:  # noqa: BLE001 — see above: the port says this cannot happen
        log.warning("product board: the tracker of %s raised while listing tickets — the caller is "
                    "being told UNREADABLE, not empty", repo, exc_info=True)
        return None
    if found is None:
        return None
    return list(found)


def _sweep(*, project, tracker, repo: str, token, name: str,
           limit: int) -> tuple[list[Ticket], str]:
    """Read everything: the first look, and the backstop for what incremental cannot see."""
    summaries = _list(tracker, repo, state="all", limit=limit)
    if summaries is None:
        return [], f"could not list the tickets of {repo}"

    columns = _columns(project, _credential(project, token))
    if columns is None:
        # A board whose columns cannot be read is an UNREADABLE board, not a column-less one:
        # every downstream judgement (idle floor, stalled work, closing questions) keys on where
        # cards sit, and half-data here becomes confident wrong answers there.
        return [], f"the board columns of {repo} could not be read (throttled or unreachable)"
    tickets = [_ticket(s, columns) for s in summaries]
    _remember(name, tickets)
    return tickets, ""


def _refresh(snapshot, *, project, tracker, repo: str, token,
             name: str) -> tuple[list[Ticket], str]:
    """Ask only for issues updated since we last looked, and merge them in.

    On a quiet afternoon this returns nothing and costs one cheap query. When something DID change,
    the columns are re-read too: a state change and a card move usually travel together, and reusing
    stale columns after an update is how a ticket shows as queued minutes after it started.

    THE WATERMARK GOES BACK IN THE PROVIDER'S OWN SPELLING, which is why it is stored verbatim
    (`_remember`) rather than parsed and re-rendered: it is fed into that provider's own date
    syntax, and the port is explicit that a stamp from somewhere else is accepted by at least one
    vendor and silently matches nothing."""
    _, since, known = snapshot
    if not since:
        return [], "no watermark"

    changed = _list(tracker, repo, state="all", updated_since=since, limit=_REFRESH_LIMIT)
    if changed is None:
        return [], "could not read the updates"

    if not changed:
        with _LOCK:
            _SNAPSHOT[name] = (snapshot[0], since, known)
        return list(known), ""

    columns = _columns(project, _credential(project, token))
    by_number = {t.number: t for t in known}
    if columns is None:
        # The columns could not be read THIS refresh. Stale beats blank: the previous column is
        # the last thing that was true, while "" would erase where every changed card sits and
        # feed the same not-seen-equals-fixed confusion the sweep path just closed. Findings judged
        # on a stale column persist unchanged, which is the conservative direction.
        log.warning("board refresh for %s: columns unreadable — keeping the previous ones", name)
        for issue in changed:
            fresh_ticket = _ticket(issue, {})
            was = by_number.get(fresh_ticket.number)
            if was is not None:
                fresh_ticket = fresh_ticket.model_copy(update={"column": was.column})
            by_number[fresh_ticket.number] = fresh_ticket
        # NEWEST FIRST, and the ref is a string now (C-05): `-t.number` cannot negate one, and
        # plain string order would put #10 above #9. `ref_sort_key` gives a numeric key
        # per prefix; `reversed` is how you descend a tuple key.
        merged = sorted(by_number.values(), key=lambda t: ref_sort_key(t.number),
                        reverse=True)
        _remember(name, merged, swept_at=snapshot[0])
        return merged, ""
    for issue in changed:
        fresh_ticket = _ticket(issue, columns)
        by_number[fresh_ticket.number] = fresh_ticket
    if columns:
        # every card may have moved, not only the ones whose issue changed
        for n, col in columns.items():
            if n in by_number:
                by_number[n] = by_number[n].model_copy(update={"column": col})

    # NEWEST FIRST, and the ref is a string now (C-05): `-t.number` cannot negate one, and plain
    # string order would put #10 above #9. `ref_sort_key` gives a numeric key per prefix;
    # `reverse` is how you descend a tuple key.
    #
    # OUTSIDE the `if columns:` above, deliberately. A comment does not open a block, so an
    # earlier draft of this left the assignment indented under that branch and `merged` unbound
    # whenever the board answered with NO columns — readable but empty, which is what a fresh
    # project looks like. Every refresh must produce a list.
    merged = sorted(by_number.values(), key=lambda t: ref_sort_key(t.number), reverse=True)
    _remember(name, merged, swept_at=snapshot[0])
    return merged, ""


def _ticket(summary, columns: dict[str, str]) -> Ticket:
    """One `TicketSummary` from the port as the shape triage judges — the two models line up field
    for field, which is not a coincidence: `TicketSummary` was derived from what this sweep reads.

    NOTHING IS RE-NORMALISED HERE. `state` and `state_reason` arrive in the PORT's vocabulary
    already — lowercase, `"completed"` / `"not_planned"` / `""`, folded by each provider from its
    own spelling (GitHub's enums SHOUT, Azure DevOps derives them from a state CATEGORY, and this
    module used to `.lower()` GitHub's on the way past). Re-folding them here would be a second
    home for a rule that has exactly one, and would quietly hide the day a provider stops keeping
    it.
    """
    # THE TRACKER'S OWN REF, KEPT WHOLE (C-05). `int(... or 0)` used to sit here, which turned a
    # ref this provider does not number — `CONT-412` — into 0, and every such card into the SAME
    # card. Same collapse as #69.
    n = canonical_ref(summary.ref)
    return Ticket(
        number=n,
        title=summary.title,
        body=summary.body,
        state=summary.state,
        # "" when the tracker does not say. A missing reason must NOT read as "completed" — see
        # `followup.delivered`, which requires the positive signal rather than the absence of a
        # negative one.
        state_reason=summary.state_reason,
        column=columns.get(n, ""),
        labels=list(summary.labels),
        assignees=list(summary.assignees),
        updated_days_ago=_days_ago(summary.updated_at),
        updated_at=summary.updated_at,
    )


def _remember(name: str, tickets: list[Ticket], *, swept_at: float | None = None) -> None:
    """Store the board and the watermark: the newest `updated_at` we have actually seen.

    Derived from the tickets rather than from the clock, because a clock watermark skips anything
    updated between the query and the write — which is exactly the ticket somebody just touched.

    VERBATIM, in whatever spelling the provider used (`2026-08-06T11:27:51.75Z` from Azure DevOps,
    `2026-08-06T16:50:51Z` from GitHub). It is handed straight back as `updated_since`, where it is
    fed into that same provider's date syntax — normalising it here would be a courtesy that makes
    the incremental read match nothing on at least one vendor, silently."""
    seen = max((t.updated_at for t in tickets if t.updated_at), default="")
    with _LOCK:
        _SNAPSHOT[name] = (swept_at if swept_at is not None else time.monotonic(), seen, tickets)


def _columns(project, token: str | None) -> dict[str, str] | None:
    """issue number → board column, THROUGH THE SEAM. **None when the read FAILED; `{}` when the
    project has no board or the board is genuinely empty** — the difference carries a week of
    consequences (an unreadable board once closed open questions as "resolved").

    This module imported the GitHub vendor function directly for a day — the audit's phrase was
    exact: "the board is an agnostic concept in the factory and GitHub-hardcoded in its two
    hottest readers". A convenience FUNCTION walked straight through the class-name guard. Now the
    project's own tracker kind picks the provider, which is the whole premise: a Jira client's
    board arrives here by configuration, not by edit."""
    from openfactory.adapters.board import build_board

    try:
        board = build_board(project, token=token)
    except ValueError as exc:
        # an unknown tracker kind is a configuration error, not an empty board
        log.error("board misconfigured for %s: %s", getattr(project, "name", "?"), exc)
        return None
    if board is None:
        return {}  # no board configured — legitimately column-less
    return board.columns()


class Parked(BaseModel):
    """One ticket waiting on a person, with what the tech-lead already said about it."""

    number: str
    title: str = ""
    body: str = ""
    diagnosis: str = ""



    @field_validator("number", mode="before")
    @classmethod
    def _ref_is_a_string(cls, v):
        """A ticket ref is the provider's own string (C-05); an int still constructs, because
        every producer reads a tracker that may hand back either and hundreds of call sites pass
        a bare number."""

        return None if v is None else canonical_ref(v)

def parked_with_diagnosis(project, *, token: str | None = None, limit: int = 10,
                          column: str = "Needs Action",
                          tracker=None) -> tuple[list[Parked], str]:
    """What is parked, newest first, each carrying the last diagnosis left on it.

    The diagnosis is READ from the ticket rather than requested from the tech-lead: it is already
    there, and asking would put two agents in a conversation with no human in it.

    ONE TRACKER FOR THE WHOLE PASS, built once and handed to the board read as well: this is up to
    `limit`+1 provider calls, and building an adapter per card would authenticate once per parked
    ticket."""
    if tracker is None:
        tracker = _tracker(project, _credential(project, token))
        if tracker is None:
            return [], (f"this deployment does not name a tracker for "
                        f"{getattr(project, 'name', '') or repo_of(project)}, so nothing can be "
                        f"read from the board — treat this as unreadable, never as empty")
    tickets, error = read_board(project, token=token, tracker=tracker)
    if error:
        return [], error
    waiting = [t for t in tickets if t.column == column and t.state == "open"]
    waiting.sort(key=lambda t: t.updated_days_ago if t.updated_days_ago is not None else 9999)

    out: list[Parked] = []
    for t in waiting[:limit]:
        out.append(Parked(number=t.number, title=t.title, body=t.body,
                          diagnosis=_last_diagnosis(tracker, t.number)))
    return out, ""


#: What the tech-lead's handoff comments start with (ADR-0015). Matched loosely: the point is to
#: prefer a diagnosis over a passing human remark, and falling back to the newest comment is better
#: than falling back to nothing.
#:
#: `🔧` IS A LEGACY MARKER AND STAYS. The platform stopped writing it — the heading is now
#: `### Tech-lead triage`, which `tech-lead` below matches — but every diagnosis already sitting on
#: a client's ticket still opens with it. Dropping it would make this classifier blind to the whole
#: history of every board that has been running, which is the silent kind of regression: nothing
#: fails, the classifier just quietly stops finding the comment it was written to find.
_DIAGNOSIS_MARKERS = ("🔧", "tech lead", "tech-lead", "diagnóstico", "diagnosis", "impediment")


#: What the classifier is told when the ticket's history could NOT be read.
#:
#: NOT "" AND NOT SILENCE, and this is the sentence the whole `None` vs `[]` rule buys on this path.
#: `needs_action.classify_prompt` renders an empty diagnosis as *"(none was recorded)"* — a fact
#: about the ticket. A comment thread that failed to load is a fact about US, and collapsing the two
#: hands a model the one input it cannot recover from: it concludes nobody has looked at this,
#: repeats an answer that has already failed, and says it with the confidence of a clean read. The
#: qualifier travels WITH the text, as the fallback below does, because a flag returned beside a
#: string is a flag one caller forgets to read.
_HISTORY_UNREADABLE = ("(não consegui ler o histórico deste ticket — isto NÃO quer dizer que "
                       "ninguém comentou nele. Pode já existir um diagnóstico ou uma instrução de "
                       "uma pessoa que eu não estou vendo; leve isso em conta antes de propor "
                       "qualquer coisa.)")


def _last_diagnosis(tracker, number: str) -> str:
    """The tech-lead's note on one parked ticket, or somebody's last comment, or the fact that the
    history could not be read at all.

    THROUGH THE PORT (#97), which is what makes this work anywhere. It was `gh issue view --json
    comments`, so on an Azure DevOps deployment the whole `Needs Action` review was unreachable —
    and the module refused it in one place while `read_board` refused it in another, both of them
    apologising for a capability nobody had ported. `TrackerAdapter.comments` is that capability.

    EVERY COMMENT, NOT THE LAST FEW (`limit=0`). The port's truncation is newest-first because its
    other consumer asks *"has this been tried?"*, which is answered at the end of a thread. This one
    is looking for a MARKED diagnosis, and a tech-lead's note followed by a long human argument is
    exactly the shape a window would hide — while the fallback below would then quietly present a
    bystander's aside instead. The pass is capped at ten tickets by its caller, which is what makes
    reading each thread whole affordable."""
    try:
        comments = tracker.comments(number, limit=0)
    except Exception:  # noqa: BLE001 — the port says the read side degrades; belt, not policy
        log.warning("product board: the tracker raised reading the comments of %s — the classifier "
                    "is being told the history is UNREADABLE, not empty", number, exc_info=True)
        comments = None
    if comments is None:
        # `None` = I could not read. Never rendered as "nobody has commented".
        log.warning("product board: the comment history of %s could not be read — saying so rather "
                    "than classifying it as a ticket nobody has looked at", number)
        return _HISTORY_UNREADABLE
    for comment in reversed(comments):
        if any(m in (comment.body or "").lower() for m in _DIAGNOSIS_MARKERS):
            return comment.body[:6000]
    # NO MARKED DIAGNOSIS EXISTS — the fallback is somebody's last comment, and it SAYS SO
    # (#24 item 4). This text used to be returned bare and then presented downstream under the
    # heading "the tech lead's diagnosis": a human's passing "vou olhar isso amanhã" became the
    # basis for the platform publicly asserting a cause, with invented provenance — contradicting
    # the real tech-lead with his own title. The qualifier travels WITH the text because the two
    # cross a model boundary together, and a flag returned beside a string is a flag one caller
    # forgets to read.
    #
    # AND IT CAN NAME THE AUTHOR NOW, which is the second thing the port brought: `gh --json
    # comments` was read for bodies alone, so "de autor não identificado" was literally true and is
    # a worse sentence than the truth. `TicketComment.author` is each provider's most LEGIBLE
    # identity, chosen so a model can tell a person from the platform — the whole point of showing
    # it here.
    if comments:
        last = comments[-1]
        who = f"de {last.author}" if last.author else "de autor não identificado"
        return (f"(sem diagnóstico do tech-lead — abaixo, o último comentário do ticket, {who})"
                f"\n\n{(last.body or '')[:6000]}")
    return ""

"""TrackerAdapter — where tickets live (GitHub Issues, Jira, Linear...).

Independent axis from the forge: a project may track on Jira but host code on
GitHub. Tickets are born here (by humans); the framework consumes them.

A WRITE THAT DID NOT HAPPEN MUST NOT LOOK LIKE ONE THAT DID. Every method below that changes
something RAISES when the tracker refused it; returning is the adapter saying the change is on the
ticket. `None` is not "no news" — it is the only way this contract has of saying "it landed", so an
implementation that catches a transport error and returns anyway is lying to every caller at once.
What that lie buys, in this codebase's own history: the client is told a card was closed while it
is still open, the impediment that a real failure opened is CLOSED by the write that never
happened, and the two duplicate cards a person asked to merge are both still on the board.

The same rule for a LOOKUP that gates a write (`find_ticket`, `children_of`): "I could not ask" and
"there is none" are different answers, and returning the second for the first files a duplicate.

BEST-EFFORT IS THE CALLER'S DECISION, never the adapter's. Only the caller knows whether the job
survives without this particular write, and it says so with a `try` at the call site where the next
reader can see it. The two exceptions are declared HERE, in the contract, and are optional
capabilities rather than silent failures: `link_child` and `children_of`, whose ordinary failure is
a tracker that does not have the feature at all.

AND THEN THERE IS THE READ SIDE, WHICH THIS PORT DID NOT HAVE (#97). Every method above was derived
from what a JOB needs — post a comment, move a card, close a ticket — so the contract came out
strong at writing and blind at reading. It could WRITE a comment and never read one; it could create
a ticket and never list the board. That was invisible while `gh` was on the path, because `gh issue
view --json comments` and `gh issue list` were sitting right there; when `gh` was removed the two
capabilities did not port, they VANISHED. The tech-lead lost the comment history it used to answer
*"has somebody already tried this?"* (#91) and the product module stopped being able to read any
board that is not GitHub's (#95). Nothing broke. The platform kept running and answered worse, which
is the failure shape nobody reports.

**THE RULE FOR EVERY READ BELOW: `None` = I COULD NOT READ. `[]` = I READ, AND THERE IS NOTHING.**
A provider that cannot tell those apart returns `None`. This is not a style preference — collapsing
them is the most expensive defect class this codebase has, and it has shipped repeatedly: an
unreadable board read as an empty queue, an unparsed review read as a rejection, an unread ticket
read as "open". The reads here feed a MODEL, which has no way at all to tell an absent answer from a
negative one, so a wrong empty does not surface as an error — it surfaces as a confident sentence.

The read side does NOT raise, and that is the one place it differs from `find_ticket`. A lookup that
gates a write raises because answering wrongly files a duplicate; these gate nothing. Their callers
are a chat answer and a board sweep, both of which must degrade to a thinner answer rather than a
traceback — and both of which already branch on `None`.
"""

from __future__ import annotations

from typing import Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openfactory.contracts import JobState, Ticket

#: The tracker's second answer to `budget()`: THIS vendor does not publish one. A declaration, not
#: a failure — Jira Cloud and Azure Boards expose no endpoint that says how much of a quota a
#: token has left, so "not reported" is the true state of the world on those deployments and is
#: rendered as such ("no budget on this vendor"), never as ok-because-nothing-came-back.
NOT_REPORTED: Final = "not_reported"


class BudgetUnreadable(RuntimeError):
    """The third answer: the vendor DOES report a budget and this read of it FAILED.

    Its own type because the caller's move differs from `NOT_REPORTED`'s: a vendor with no budget
    is a fact to state; a probe that failed is a safety net that is gone — the poller fails open
    and scans anyway, so the floor must say "unread" rather than "fine", and the doctor must say
    what broke (the CLI is missing, the token was refused) rather than pass the check."""


class Budget(BaseModel):
    """What the tracker's API lets this credential spend right now — the port's first answer.

    THREE ANSWERS, NOT ONE VALUE WITH `None` IN IT. `budget()` returns this, or `NOT_REPORTED`, or
    raises `BudgetUnreadable`. The shape it replaces was `dict | None`, where `None` meant BOTH
    "this vendor has no budget" and "the read failed" — and the doctor rendered that `None` as
    ok ("the vendor does not report an API budget"), so a broken `gh` on a GitHub deployment read
    as compliance, and a Jira deployment probing github.com for a quota it does not have read as
    compliance too. Measured 2026-08-24: `floor._budget`, the poller's activity and the cockpit's
    route each spawned `gh api rate_limit` on a Jira-only deployment, and the doctor handed that
    deployment's JIRA token to `gh` as `GH_TOKEN`.

    `floor` IS THE VENDOR'S OWN NUMBER. Below it the poller stops taking cards to keep a cushion
    for the job in flight. It travels on the value because it was written down twice in core —
    `poller._RATE_FLOOR = 200` and the doctor's `max(200, limit // 10)` — two thresholds for one
    behaviour, so the doctor could say "nearly gone" at a level the poller was still scanning
    through. Only the adapter knows what a scan costs on its API, so only the adapter says.
    """

    #: The vendor's name for the pool these reads spend (`graphql`, `core`, …), or `"API"`.
    resource: str = "API"
    remaining: int
    limit: int = 0
    #: When the pool refills, epoch seconds; 0 when the vendor did not say.
    reset_epoch: int = 0
    #: Below this many calls the poller pauses pickups — the ADAPTER's threshold, see above.
    floor: int = 0
    #: A human-readable name for the vendor whose budget this is (`"GitHub"`), for the sentence
    #: that tells a person why nothing is being picked up. The core never spells one.
    vendor: str = ""

    @property
    def low(self) -> bool:
        """Whether pickups should pause — decided by the adapter's own floor, nowhere else."""
        return self.remaining < self.floor


#: The port's answer to `budget()`. A `Literal`, not `None`: the two non-value answers are a
#: declared sentinel and a raised error, so nothing downstream can read absence as either.
BudgetAnswer = Budget | Literal["not_reported"]

#: JobState → the neutral lifecycle KEY every board answers with its own column names (C-14).
#: ONE table, in the contract, because there were two: Jira derived these buckets and GitHub
#: hardcoded English column literals per state — the same lifecycle spelled twice, and the
#: GitHub spelling was accidentally closed: a client whose board says "A Fazer" paid a rename
#: tax the Jira adapter never charged. The four buckets are the four questions a board answers;
#: `done` closes the fifth. Derived from JobState so a new state shows up as UNMAPPED (no-op
#: with a warning) rather than silently transitioning somewhere wrong.
_QUEUED = (JobState.TODO, JobState.READY)
_WORKING = (JobState.SPEC_VALIDATION, JobState.PREPARING, JobState.PLANNING,
            JobState.IMPLEMENTING, JobState.VALIDATING, JobState.REPAIRING)
_REVIEW = (JobState.REVIEWING, JobState.PR_OPEN, JobState.MERGED, JobState.STAGING_VERIFYING,
           JobState.PROD_VERIFYING)
#: A PRODUCTION GATE IS A PERSON, NOT A REVIEW (#166). `awaiting_prod_approval` sat in `_REVIEW`
#: while `view.ATTENTION_STATES` — the platform's own list of what needs a human — has always
#: named it. So the floor said "Needs you" and the client's board said "In review" with its
#: `Needs Action` column reading zero, about the one gesture that puts software in front of real
#: users. Two surfaces, one question, opposite answers.
_NEEDS_A_PERSON = (JobState.NEEDS_REFINEMENT, JobState.ON_HOLD, JobState.BLOCKED, JobState.FAILED,
                   JobState.AWAITING_PROD_APPROVAL)

#: A ticket a human took OFF the floor. It belongs with the work nobody is working on — not with
#: what shipped (`done` is the report that must stay trustworthy) and not with what needs somebody
#: (nobody is waiting on it). `backlog` is a fifth key, so a board that does not declare the column
#: no-ops with a warning exactly as an unmapped state does.
_PARKED_BY_A_PERSON = (JobState.SKIPPED,)

STATE_KEYS: dict[JobState, str] = {
    **dict.fromkeys(_QUEUED, "todo"),
    **dict.fromkeys(_PARKED_BY_A_PERSON, "backlog"),
    **dict.fromkeys(_WORKING, "in_progress"),
    **dict.fromkeys(_REVIEW, "in_review"),
    **dict.fromkeys(_NEEDS_A_PERSON, "needs_action"),
    JobState.DONE: "done",
}

def column_key(state: JobState, *, needs_person: bool | None = None) -> str | None:
    """Which column a state belongs in — the ONE resolution, for every tracker and every board.

    `needs_person` IS THE DISTINCTION A STATE CANNOT CARRY (#166). `pr_open` is two situations
    wearing one name: an armed auto-merge, where the machine is watching CI and nobody is needed,
    and a human merge gate, where the READER is the blocker. The engine writes the same
    `JobState.PR_OPEN` for both, and only `view._domain_state` could tell them apart — by reading
    a fact the tracker port never received. So the pilot's panel said *Needs you* while his own
    board said *In review* with `Needs Action` reading zero, about the same card.

    `None` MEANS "THE STATE DECIDES", which is what every existing caller means and what this
    answered before the parameter existed. A caller that knows better says so; nobody has to be
    updated to keep working.

    A NEW JOBSTATE WAS THE OTHER WAY AND IS REJECTED ON THE CARD: `RunResult.state` travels into
    the Temporal workflow, so a new member changes what in-flight jobs replay — and one is parked
    at this exact gate right now.
    """
    # ONLY THE AMBIGUOUS BUCKET IS RE-READ, and the asymmetry is deliberate: a state that is a
    # person's by nature stays theirs however a caller answers. `needs_person=False` on `on_hold`
    # is a caller contradicting the platform's own record, and the record wins.
    if needs_person and state in _REVIEW:
        return "needs_action"
    return STATE_KEYS.get(state)


#: What `list_tickets(state=…)` accepts. ONE table, in the contract, for the same reason
#: `STATE_KEYS` is: three adapters would otherwise each decide privately what an unrecognised value
#: means, and the tempting answer — quietly widen it to "all" — is how a caller asking for the open
#: queue gets handed the closed cards too and never learns it asked wrong.
LIST_STATES = ("all", "open", "closed")


def list_state(state: str) -> str:
    """The canonical `list_tickets` state filter, or `ValueError`.

    IT RAISES, WHICH IS THE OPPOSITE OF EVERY OTHER RULE ON THE READ SIDE, because this is the one
    failure that is not the provider's. A misspelled filter is a bug in the CALLER, and the two
    quiet alternatives are both worse than a traceback in a place a test reaches: widening it to
    "all" hands somebody asking for the open queue the closed cards as well, and narrowing it to
    "open" hides half the board from a triage whose entire job is to find cards that were closed
    without being delivered."""
    got = str(state or "").strip().lower()
    if got not in LIST_STATES:
        raise ValueError(
            f"list_tickets(state={state!r}) — the port knows {', '.join(LIST_STATES)}. This is the "
            f"platform's vocabulary, not a vendor's status name; filter on anything narrower after "
            f"the read.")
    return got


class TicketComment(BaseModel):
    """One comment already on a ticket, in the shape a READER needs.

    NOT `list[str]`, and the difference is the whole point of the method. What the tech-lead does
    with these is decide whether the thing it is about to suggest has already been tried, and by
    whom: its own earlier note is a hypothesis to re-examine, a human's instruction is a
    constraint, and a bare list of bodies makes those two indistinguishable. Its prompt says
    literally *"VERIFY these — a prior fix may be wrong"*, which is a sentence that cannot be acted
    on without knowing who wrote what and when.

    Three fields because three fields is what the callers use. A comment id, a URL and an edit
    history are all things these providers return and nothing here reads; the port stays derived
    from what the Core CALLS (ADR-0022 §3).
    """

    #: WHO wrote it, in the provider's most LEGIBLE stable spelling — GitHub's `login`, Jira's
    #: `displayName`, Azure DevOps's `uniqueName`. Deliberately not the same choice `assignees()`
    #: makes: that one returns the WRITABLE identity because it gets written back, and a comment
    #: author never does. Jira's writable identity is `accountId`
    #: (`712020:607081d5-b8cd-472d-9076-bc05245275fc`, verified live), and putting that in front of
    #: a model asked to tell a person from the platform is handing it a GUID and hoping.
    #:
    #: `""` when the provider did not say. It is a field, not a signal — an unreadable comment
    #: THREAD is `None` from the method, never a comment with a blank author.
    author: str = ""
    #: The text, already through whatever conversion this provider's storage needs (Jira's ADF,
    #: Azure DevOps's HTML sanitiser). A caller pastes this into a prompt.
    body: str = ""
    #: The provider's own timestamp, verbatim, or `""`. Not parsed here: three vendors spell it
    #: three ways and the only consumer renders it, so parsing would be a lossy step taken for
    #: nobody.
    created_at: str = ""


class TicketSummary(BaseModel):
    """One ticket as a BULK read can answer for it — the board's view, not the pipeline's.

    DELIBERATELY NOT `contracts.Ticket`, and this is the same distinction `product/triage.py`
    already draws for the same reason. `Ticket` is the PARSED spec the executor and the sizing gate
    read: it requires an `objective`, and building one means running `parse_ticket_body` over the
    body. Three hundred of those per board sweep is a parse nobody asked for, and the fields the
    sweep actually judges on — why a card was closed, who is on it, when it last moved — are not on
    `Ticket` at all. A shape that cannot express what its caller needs is a promise no adapter can
    keep, whatever it returns.

    There is no `column` here on purpose. Which column a card sits in is the BOARD's question and
    `BoardAdapter.columns()` already answers it; a tracker that guessed at it would be a second
    source for a fact that has already caused enough trouble having one.
    """

    #: The provider's own ref, canonical (no `#`) — `"142"`, `"CONT-412"`, `"1234"`. A STRING,
    #: because `int` is the one shape a Jira board cannot produce and reducing `CONT-412` to `412`
    #: makes it the same ticket as `PROJ-412` (C-05).
    ref: str
    title: str = ""
    body: str = ""
    #: `"open"` | `"closed"` — the neutral vocabulary, never the vendor's status name. Jira and
    #: Azure DevOps both answer this from their own state CATEGORY, so a board whose done column is
    #: called "Donee" (this deployment has one) still reads right.
    state: str = "open"
    #: WHY it was closed: `"completed"` | `"not_planned"` | `""` (open, or a tracker that does not
    #: say). CLOSED IS NOT DELIVERED — `product/triage.py::Ticket.delivered` reads exactly this
    #: word, and the conflation once had the platform announce eleven cards closed as duplicates as
    #: delivered work. `""` reads as delivered on purpose there: a tracker that omits the reason
    #: must not silently stop announcing real deliveries.
    state_reason: str = ""
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    #: The provider's own last-modified timestamp, verbatim — the value a caller stores as its
    #: watermark and hands back as `updated_since`. Round-tripping the provider's OWN spelling is
    #: what keeps the incremental read honest across three vendors that agree on nothing else.
    updated_at: str = ""


@runtime_checkable
class TrackerAdapter(Protocol):
    def get_ticket(self, ref: str) -> Ticket:
        """Fetch a ticket by its native ref and parse it into the Ticket contract."""
        ...

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> None:
        """Reflect the job's lifecycle state back (label/column/status), with a
        reason when moving to NEEDS_REFINEMENT.

        `needs_person` carries what the state alone cannot: whether a PERSON is the blocker. See
        `column_key` — `pr_open` is an armed auto-merge and a human merge gate under one name, and
        the caller is the only thing that knows which. Additive with a default of `None`, so every
        existing call site keeps the answer it had."""
        ...

    def comment(self, ref: str, body: str) -> None:
        """Post a human-readable comment on the ticket (e.g. 'PR ready for review')."""
        ...

    def comments(self, ref: str, *, limit: int = 0) -> list[TicketComment] | None:
        """What has already been SAID on this ticket. `None` when it could not be read.

        THE PAIR TO `comment`, AND IT WAS MISSING FOR A YEAR. Posting was on the port from the
        first day; reading was never asked for, because no job needs it — and then the tech-lead
        did. It read the last three or four comments on a parked ticket to answer the only question
        worth asking before proposing a fix: has somebody already tried this? It did that through
        `gh`, so it worked on exactly one provider, and when `gh` came off the path both
        `techlead/diagnosis.py` and `techlead/conversation.py` were left telling the model *"the
        ticket's comment history is NOT available to you"* — an honest sentence standing in for a
        capability nobody had ported.

        `None` VERSUS `[]` IS THE ENTIRE CONTRACT HERE, and it matters more on this method than
        anywhere else on the port, because the consumer is a language model. A ticket nobody has
        commented on and a ticket whose comments could not be fetched produce the same silence in a
        prompt, and the model resolves that silence the same way both times: it concludes nobody
        has looked at this and confidently repeats an answer that has already failed. `[]` is a
        fact the caller may state ("nobody has commented"); `None` is a caller obligation to say it
        could not look.

        `limit=0` MEANS ALL; `limit=N` MEANS THE MOST RECENT N. Zero is "no ceiling" rather than
        "none" because nobody calls a comment reader wanting zero comments, while a default that
        silently truncated would be a window the caller only discovers after making a wrong call
        about the part it never saw. Most-RECENT rather than first, because "has this been tried?"
        is answered at the end of a thread, not at its beginning.

        THE ORDER IS ALWAYS OLDEST FIRST, including the truncated answer — `limit=3` gives the last
        three, still in the order they were written. Every consumer renders these into a prompt as
        a conversation, and an argument read backwards is a different argument. Providers disagree
        (GitHub hands back ascending, Azure DevOps descending by default), so the port normalises
        rather than leaving each caller to discover which one it got.
        """
        ...

    def list_tickets(self, *, state: str = "all", updated_since: str = "",
                     limit: int = 0) -> list[TicketSummary] | None:
        """The board's tickets in bulk. `None` when they could not be read; `[]` when there are
        none.

        THE READ THAT MADE THE PRODUCT ROLE GITHUB-ONLY (#95). `product/board.py` reads the WHOLE
        board — including cards the factory has never touched — to triage it, and it did so by
        shelling out to `gh issue list`. Its column read was already provider-neutral and was
        therefore never reached: the issue half runs first and returns at the failure. On the Azure
        DevOps deployment that reader has executed exactly never, and it does not fail quietly by
        accident — it is handed the project's tracker token, which it exports as `GH_TOKEN` before
        running a process that talks to github.com. The module now refuses that path with a named
        reason. This method is what lets it stop refusing.

        `state`: one of `LIST_STATES` — `"all"` | `"open"` | `"closed"`, the port's own vocabulary,
        never a vendor status name. Anything else is a caller bug and raises `ValueError`: quietly
        widening an unrecognised filter to "all" would hand a caller asking for the open queue the
        closed cards as well, which is the same confident-wrong-answer shape as an unreadable board
        reading as an empty one.

        `updated_since`: a provider's own `updated_at` value from an earlier call, or `""` for no
        watermark. The incremental read is not an optimisation — a full board sweep is two
        expensive queries, and running one per operation helped exhaust this deployment's hourly
        quota on 2026-07-27, whose first casualty was a real job. **The value handed back must be
        one this same provider produced**, because it is fed into that provider's own date syntax;
        see the Jira adapter, where an ISO-8601 stamp is accepted and silently matches nothing.

        `limit=0` means "everything, up to whatever ceiling this provider must impose to bound one
        read", and `limit=N` means at most N **of the tickets that MATCH `state`** — the limit is a
        window on the filtered board, never a budget spent before the filter runs. That sentence is
        here because leaving it implicit already cost an answer: a provider whose open/closed
        decision happens after the read handed its `$top` to the query, so `state="closed", limit=3`
        asked for the three most recently changed cards, found all three open, and answered `[]` on
        a board holding five closed ones. `[]` means "there are none". A short answer a provider
        cannot avoid — its own ceiling arrived first — is a warning, not a silent trim.
        **ORDERED BY LAST UPDATE, NEWEST FIRST, always** — a
        limit without a promised order is an arbitrary subset dressed as an answer, and the
        interesting card on a rotting board is the one that moved recently, not the one filed
        recently. A caller wanting a different order sorts by `refs.ref_sort_key`; a provider that
        had to truncate says so in a warning rather than pretending it saw the whole board.
        """
        ...

    def ticket_url(self, ref: str) -> str:
        """Where a HUMAN opens this ticket. Empty when the provider cannot say.

        On the port because the platform sends people to tickets — the park alert's one clickable
        line, the provenance link on an authored issue — and those call sites were building
        `https://github.com/{repo}/issues/{n}` by hand. On a Jira deployment that is a link to an
        issue that does not exist, delivered at the exact moment somebody is being asked to act;
        on GitHub Enterprise it points at public github.com, where a same-named repository may
        belong to somebody else. A vendor's URL shape is the provider's knowledge, and asking here
        is what makes a new tracker — Azure DevOps next — answer it instead of being guessed at."""
        ...

    def budget(self) -> BudgetAnswer:
        """How much of its API quota the credential this tracker holds can still spend.

        THREE ANSWERS: a `Budget`, the `NOT_REPORTED` sentinel, or `BudgetUnreadable` raised.
        Never `None` — see `Budget` for what collapsing the last two cost.

        ON THE PORT BECAUSE THE CORE WAS ASKING ONE VENDOR BY NAME. The floor, the poller, the
        doctor and the cockpit each imported `github_project.github_rate` and ran it whatever the
        deployment's tracker was: a Jira-only deployment spawned `gh api rate_limit` on every
        floor read and every poll tick, logged "could not read the GitHub rate limit", and — the
        expensive half — the doctor resolved the project's TRACKER credential and exported a Jira
        token as `GH_TOKEN`. A vendor that has no budget to report answers `NOT_REPORTED` and the
        core renders that as a state of its own; a vendor whose probe failed raises and the core
        renders "unread", which is the only honest word for a safety net that is not there.

        `floor` on the value is the adapter's threshold; the core carries no number of its own.
        """
        ...

    def person(self, ref: str) -> dict:
        """Who this provider's person-ref names: `{"id", "name", "email"}` — or `{}`.

        THE REF IS THE PROVIDER'S OWN, and each vendor means something different by it: a GitHub
        login, a Jira `accountId`, an Azure DevOps sign-in address. `assignees()` hands those
        straight out, so a caller holding one holds a string it cannot interpret without asking
        the tracker that issued it.

        IT WAS BEING ASKED OF GITHUB WHATEVER THE TRACKER (#162). The Slack mention path ran
        `gh api users/<ref>` on every unresolved person, so on a Jira deployment it looked up an
        opaque `accountId` on github.com — 404, one call against the shared App quota, and a
        colleague named in plain text who is never notified. The message then reads answered to
        everybody else, which is the failure that costs most.

        `{}` MEANS "I CANNOT SAY", and a partial answer is normal and useful: a workspace that
        hides emails still yields a name, and the caller's match is conservative by design. What
        it may never do is invent — a wrong Slack mention pings a stranger AND leaves the right
        person unasked.

        NEVER RAISES. Its caller is composing a message somebody is waiting for.
        """
        ...

    def assignees(self, ref: str) -> list[str]:
        """Current assignee logins. The first is treated as the owner to return to.

        Empty means nobody is assigned. A read that failed raises instead: the answer decides who
        a parked ticket goes back to, and "nobody" is precisely the state that leaves it with no
        owner at all."""
        ...

    def set_assignees(self, ref: str, logins: list[str]) -> None:
        """Replace the assignees. On pickup the framework sets itself as the sole
        assignee (remembering the old owner); on an impediment it restores the owner
        (or leaves it unassigned if there was none)."""
        ...

    def add_label(self, ref: str, label: str) -> None:
        """Add a label to the ticket (creating it in the tracker if needed). Used to mark
        'the bot is actively working this' — a GitHub App can't be an issue assignee.

        A job survives without its label, and the callers that decide so wrap this in a `try`."""
        ...

    def remove_label(self, ref: str, label: str) -> None:
        """Remove a label from the ticket (a label the ticket does not carry is a no-op)."""
        ...

    def create_ticket(self, *, title: str, body: str) -> str:
        """Create a new ticket (ADR-0013 D3 — the autonomous splitter's children) and
        return its native ref (e.g. '#123'). The child lands wherever the tracker's intake
        is (GitHub: the board's Backlog) — sequencing to TO-DO stays a human decision by
        default."""
        ...

    def find_ticket(self, *, title: str) -> str | None:
        """Ref of an OPEN ticket with exactly this title, or None. The splitter is
        idempotent through this: a retry must reuse the child it already created.

        `None` means the tracker answered and holds no such ticket. A lookup that could not be
        performed raises: it is the gate in front of a create, so answering `None` to it is how the
        platform files the duplicate it was asked to prevent."""
        ...

    def update_body(self, ref: str, body: str) -> None:
        """Replace a ticket's description.

        The product role's one destructive write, and the reason it is a separate method rather
        than a flag on something else: a caller reaching for this is rewriting what somebody else
        wrote, and that should be visible at the call site."""
        ...

    def close_ticket(self, ref: str, reason: str, *, delivered: bool = True) -> None:
        """Close a ticket with a final comment (the split parent becomes an epic record).

        Returning means the ticket is closed. A caller announces this act to a human — "fechei o
        #511 em favor do #288" — and there is no second signal it could consult.

        `delivered=False` records that the work did NOT happen — a duplicate, a card withdrawn, a
        plan abandoned. CLOSED IS NOT DELIVERED (`triage.Ticket.delivered`), and until this
        existed every close looked like one: `#511`, closed as a duplicate of `#288` at a client's
        request, came back from the tracker marked as completed and read as delivered work by
        everything downstream — the weekly announcement, the queue, the prompt. Eleven cards closed
        as `not_planned` in one sitting is the incident that made the distinction matter; this is
        the write side of the same rule.

        Defaulting to True keeps every existing caller's meaning: the ones that close a ticket
        because the work IS done say nothing and stay right."""
        ...

    # --- optional parent/child linkage (ADR-0013 D3) --------------------------------------
    # Native relationship is how a board expresses "these tickets came from that one" — GitHub
    # sub-issues, Jira sub-tasks / epic links, Linear sub-issues. It buys two things the title
    # alone can't: real traceability the board renders, and DECISION idempotency (children_of
    # answers "already split?" as a first-class query, so a re-run never splits twice). Both
    # are OPTIONAL and best-effort: a tracker without the capability simply doesn't implement
    # them, and the splitter still works from its deterministic titles. The core calls these
    # defensively (getattr) so no adapter is forced to provide them.

    def link_child(self, parent_ref: str, child_ref: str) -> None:
        """Record a native parent→child link. Idempotent + best-effort (re-linking is a
        no-op); provider-specific (GitHub sub-issues, Jira sub-task, …)."""
        ...

    def children_of(self, parent_ref: str) -> list[str]:
        """Refs of the parent's linked children (empty if none / unsupported). Non-empty ⇒
        the split decision was already taken — the splitter reuses instead of duplicating.

        Empty is allowed to mean "cannot say" for this one method, because a tracker without the
        capability answers that way on every call. It is safe only because the caller's fallback —
        `find_ticket` by title — tells "no such ticket" apart from "I could not ask"."""
        ...

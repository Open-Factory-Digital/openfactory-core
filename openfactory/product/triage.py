"""Organising the house: what the board says, and where it is lying.

The first thing a person taking over a product does is not read code — it is open the board and ask
what is actually happening. What is in flight that should not be. What has been waiting on someone
for a month. What looks finished but was never closed. It is cheap (tracker reads, no code, no
agent), fast, and it produces something useful in the first hour, which matters more on first
contact than anything else this role can do.

IT IS NOT A ONE-OFF. A board rots continuously. The difference between the first pass and every
later one is not the work — it is whether there is a previous pass to compare against. Once a pass
records what it saw, the next one is a DIFF: what is new, what is still stuck, what got worse. That
is what makes it affordable to repeat, and it is the same shape as the knowledge bundle's
regeneration.

THE FIRST PASS WRITES NOTHING. Not to the board, not to the tickets. On first contact this role has
the least context and the most to misread, and closing a ticket destroys information that took
someone effort to write. Authority grows with grounding: once the corpus is confirmed, routine
hygiene becomes its own. The first pass earns its keep by REPORTING.

AND IT READS BEFORE IT JUDGES — the lesson is expensive and recent. On 2026-07-26 two tickets sat in
"In progress" with no job running, which looks exactly like a board lying about its own state. They
were a human-owned spike whose body says "NOT for the automated coding pipeline. Stays OUT of the
TO-DO column", and an epic whose children were being executed. Both were correct. The reading was
wrong, and it was wrong because it judged a column without opening the ticket. Every check here that
could produce that mistake is required to look at labels and body first.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

#: A ticket whose body or labels say a human owns it. The pipeline is not supposed to touch these,
#: so their sitting in an active column is intended, not rot.
HUMAN_OWNED_LABELS = frozenset({"spike", "research", "human", "manual", "wontfix", "on-hold"})
HUMAN_OWNED_PHRASES = (
    "not for the automated",
    "maintainer/human-owned",
    "human-owned",
    "stays out of the to-do",
    "do not promote",
)

#: An epic is a container: its children are the work, so the epic legitimately stays open while they
#: run. Judging it as a stalled ticket is the same mistake in a different costume.
CONTAINER_LABELS = frozenset({"epic", "milestone", "theme"})


class Ticket(BaseModel):
    """What triage needs about one ticket. Deliberately not the pipeline's `Ticket`: this reads the
    BOARD, including tickets the factory has never touched and never will."""

    number: str
    title: str = ""
    body: str = ""
    state: str = "open"          # open | closed
    #: WHY it was closed, verbatim from the tracker: "completed" | "not_planned" | "" (open, or a
    #: tracker that does not say). CLOSED IS NOT DELIVERED — that conflation made the sweep announce
    #: "o que foi pedido no requisito 7 está pronto" for work closed as a duplicate or as not
    #: planned, which is a delivery the client never received. Eleven cards were closed as
    #: not_planned on 2026-07-29 in one sitting, so this is not a hypothetical.
    state_reason: str = ""
    column: str = ""             # the board column, verbatim
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    updated_days_ago: int | None = None
    #: the raw `updatedAt`, kept so an incremental board read can ask for "everything since"
    updated_at: str = ""
    has_open_pr: bool = False
    parent: str | None = None
    children: list[str] = Field(default_factory=list)

    #: A ticket ref is the PROVIDER'S OWN STRING (C-05) — `412` on GitHub/ADO/GitLab, `CONT-412`
    #: on Jira. `mode="before"` so an int still constructs: every producer of this model reads a
    #: tracker that may hand back either, and hundreds of call sites (and tests) pass `88`. The
    #: value is normalised once, here, so `#88`, `88` and `"88"` are one ticket rather than three.
    @field_validator("number", "parent", mode="before")
    @classmethod
    def _ref_is_a_string(cls, v):
        from openfactory.contracts.refs import canonical_ref

        return None if v is None else canonical_ref(v)

    @field_validator("children", mode="before")
    @classmethod
    def _child_refs_are_strings(cls, v):
        from openfactory.contracts.refs import canonical_ref

        return [canonical_ref(c) for c in v] if isinstance(v, list) else v

    @property
    def human_owned(self) -> bool:
        """Whether a person has claimed this ticket out of the pipeline's reach. Checked from
        LABELS AND BODY, never from the column alone — see this module's docstring."""
        if {label.lower() for label in self.labels} & HUMAN_OWNED_LABELS:
            return True
        text = f"{self.title}\n{self.body}".lower()
        return any(phrase in text for phrase in HUMAN_OWNED_PHRASES)

    @property
    def is_container(self) -> bool:
        return bool({label.lower() for label in self.labels} & CONTAINER_LABELS) or bool(
            self.children)

    @property
    def delivered(self) -> bool:
        """Whether this ticket represents work the client actually GOT.

        CLOSED IS NOT DELIVERED, and this repository has already paid for the difference: eleven
        cards were closed as `not_planned` in one sitting on 2026-07-29, and counting them as
        delivered made the sweep announce "o que foi pedido no requisito 7 está pronto" about work
        nobody ever did.

        THE RULE LIVED IN ONE PLACE AND WAS ABOUT TO BE MISSED IN THE OTHER. It was written inside
        `activities._closed_issue_numbers`, on the SWEEP's path, reading `module._board_tickets`.
        The conversational surface never had it — that path receives only `{number: column}` and
        `{number: title}` — so any answer about delivery given in the channel was ungoverned. That
        is this codebase's second signature defect ("the lesson learned in one file and left
        there"), and putting the predicate where `state_reason` already lives is what stops the
        two surfaces from disagreeing about what "done" means.

        `not_planned` is excluded BY NAME rather than `completed` being required, deliberately: a
        tracker that omits the reason must not silently stop announcing real deliveries — that
        would trade a false delivery for a lost one.
        """
        return self.state != "open" and self.state_reason != "not_planned"


class Observation(BaseModel):
    """One thing worth a human's attention, and what triage suggests — never what it did."""

    ticket: str
    kind: str
    detail: str
    #: what a person might do about it. A SUGGESTION: the first pass does not act.
    suggestion: str = ""



    @field_validator("ticket", mode="before")
    @classmethod
    def _ref_is_a_string(cls, v):
        """A ticket ref is the provider's own string (C-05); an int still constructs, because
        every producer reads a tracker that may hand back either and hundreds of call sites pass
        a bare number."""
        from openfactory.contracts.refs import canonical_ref

        return None if v is None else canonical_ref(v)

class TriageReport(BaseModel):
    observations: list[Observation] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    #: tickets deliberately left alone, and why — so "you ignored these" is answerable
    skipped: dict[str, str] = Field(default_factory=dict)

    def of_kind(self, kind: str) -> list[Observation]:
        return [o for o in self.observations if o.kind == kind]

    def keys(self) -> list[str]:
        """A stable fingerprint of what this pass found, small enough to persist between passes.
        `ticket:kind`, because the same ticket can rot in two ways at once."""
        return sorted(f"{o.ticket}:{o.kind}" for o in self.observations)

    def since(self, previous_keys: list[str] | None) -> TriageReport:
        """What is NEW against a persisted fingerprint. Same rule as `diff`, without needing the
        previous report itself — a scheduled pass only ever has the keys."""
        seen = set(previous_keys or [])
        fresh = [o for o in self.observations if f"{o.ticket}:{o.kind}" not in seen]
        return TriageReport(observations=fresh, counts=self.counts, skipped=self.skipped)

    def diff(self, previous: TriageReport | None) -> TriageReport:
        """What is NEW since a previous pass. The reason this is affordable to repeat: a recurring
        report that lists the same forty things every week is one nobody opens twice."""
        if previous is None:
            return self
        seen = {(o.ticket, o.kind) for o in previous.observations}
        fresh = [o for o in self.observations if (o.ticket, o.kind) not in seen]
        return TriageReport(observations=fresh, counts=self.counts, skipped=self.skipped)


#: A ticket untouched for longer than this in a column that means "someone is on it" is stuck. Not
#: a hard truth — a deliberately long default, because crying wolf is how a report loses its reader.
STALE_DAYS = 14


def triage(tickets: list[Ticket], *, active_columns: tuple[str, ...] = ("In progress",),
           waiting_column: str = "Needs Action", done_column: str = "Done",
           stale_days: int = STALE_DAYS) -> TriageReport:
    """Read the board and report where it disagrees with reality.

    Pure: it takes tickets and returns findings, so every rule here is testable without a network —
    which matters, because the failure mode is a confident wrong reading, not a crash."""
    observations: list[Observation] = []
    skipped: dict[str, str] = {}
    by_number = {t.number: t for t in tickets}

    for t in tickets:
        # ---- the checks that must read the ticket before judging the column -------------------
        if t.column in active_columns and t.state == "open":
            if t.human_owned:
                skipped[t.number] = ("a person owns this deliberately — it says so in the ticket, "
                                     "so its being in an active column is intended")
            elif t.is_container:
                skipped[t.number] = ("this is a container for other tickets; it stays open while "
                                     "its children run")
            elif t.updated_days_ago is not None and t.updated_days_ago > stale_days:
                observations.append(Observation(
                    ticket=t.number, kind="stalled",
                    detail=f"in {t.column!r} but untouched for {t.updated_days_ago} days",
                    suggestion="check whether it is actually being worked on; if not, "
                               "move it back"))

        # ---- waiting on a person, for too long ------------------------------------------------
        if t.column == waiting_column and t.state == "open":
            if t.updated_days_ago is not None and t.updated_days_ago > stale_days:
                observations.append(Observation(
                    ticket=t.number, kind="waiting-too-long",
                    detail=f"waiting on someone for {t.updated_days_ago} days",
                    suggestion="decide it, or say out loud that it is parked on purpose"))

        # ---- a ticket that cannot be sized will park later ------------------------------------
        if t.state == "open" and t.column not in (done_column,) and not _has_criteria(t):
            observations.append(Observation(
                ticket=t.number, kind="no-criteria",
                detail="no acceptance criteria, so nobody can say when it is done",
                suggestion="write what must be true before this is picked up"))

        # ---- finished, but not finished -------------------------------------------------------
        if t.column == done_column and t.state == "open" and not t.has_open_pr:
            observations.append(Observation(
                ticket=t.number, kind="done-but-open",
                detail="sits in Done but the ticket was never closed",
                suggestion="close it, or move it back if it is not actually done"))

        if t.state == "closed" and t.column not in (done_column, ""):
            observations.append(Observation(
                ticket=t.number, kind="closed-elsewhere",
                detail=f"closed, but its card is still in {t.column!r}",
                suggestion="move the card to Done so the board stops showing work that is over"))

        # ---- a container whose work is finished ------------------------------------------------
        if t.is_container and t.state == "open" and t.children:
            kids = [by_number.get(c) for c in t.children]
            known = [k for k in kids if k is not None]
            if known and all(k.state == "closed" for k in known):
                observations.append(Observation(
                    ticket=t.number, kind="container-complete",
                    detail=f"every ticket under it is closed ({len(known)} of "
                           f"{len(t.children)} found)",
                    suggestion="close it, or say what is still missing"))

    counts: dict[str, int] = {}
    for o in observations:
        counts[o.kind] = counts.get(o.kind, 0) + 1
    return TriageReport(observations=observations, counts=counts, skipped=skipped)


#: What counts as "this ticket states something testable" — THE one list (#24 item 7). Two copies
#: lived here and in `queue.py`, and they had already diverged: this one knew "given /dado que",
#: the queue's did not, so a ticket triage approved could be described by the queue's prompt as
#: having nothing testable — the platform disagreeing with itself about the same body text.
CRITERIA_MARKERS = (
    "- [ ]", "- [x]",
    "acceptance criteria", "critério de aceite", "criterios de aceite", "critérios de aceite",
    "definition of done", "must be true", "deve ser verdade", "given ", "dado que",
)


def _has_criteria(t: Ticket) -> bool:
    """Whether the ticket states anything testable. Generous on purpose — a checklist, a
    "Given/When/Then", or a criteria heading all count. Flagging a well-written ticket because it
    used an unusual heading is how a report teaches people to ignore it."""
    text = (t.body or "").lower()
    return any(marker in text for marker in CRITERIA_MARKERS)

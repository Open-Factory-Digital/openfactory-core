"""What should be worked on next — the question a product owner actually loses sleep over.

Everything else this role does keeps the requirements honest. This is the part that keeps the
FACTORY BUSY, and the two are not the same job. A tidy backlog beside an idle floor is not a
success; it is a week of capacity nobody spent, and noticing that is the most valuable thing a
product owner does in a week.

THE SHAPE OF THE ANSWER IS DETERMINISTIC; THE ORDER IS A JUDGEMENT.

Whether the floor is idle, how much is queued, which tickets state something testable — all of that
is arithmetic over the board and is decided here, without a model. What to do FIRST is not: it
depends on what unblocks what, what the product already promised, and what a person is waiting for.
That part is asked, with this analysis as the evidence.

Splitting it that way matters because the arithmetic is what makes the proposal trustworthy. A model
asked "what should we do next?" against 53 tickets will produce a confident list every time,
including when the honest answer is "nothing is ready — these ten need criteria first".

AND IT PROPOSES, NEVER PROMOTES. TO-DO is what the poller pulls, so moving a card there commits real
money. The proposal is the argument; a person's yes is the decision (ADR-0019 §5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from openfactory.contracts.refs import canonical_ref
from openfactory.product.triage import CRITERIA_MARKERS, Ticket


class Readiness(BaseModel):
    """The board's arithmetic: what is queued, what could be, and what is in the way."""

    in_progress: int = 0
    todo: list[str] = Field(default_factory=list)
    #: backlog tickets that state something testable — the ones worth proposing
    ready: list[str] = Field(default_factory=list)
    #: backlog tickets that would fail the sizing gate as written. Refining these is work the
    #: product role can do; proposing them is spending a job to be told so.
    needs_refinement: list[str] = Field(default_factory=list)
    #: open tickets a person is holding — never proposed, and never counted as idle capacity
    parked: list[str] = Field(default_factory=list)

    @property
    def idle(self) -> bool:
        """Nothing being worked on and nothing queued to start."""
        return self.in_progress == 0 and not self.todo

    @property
    def wasting_capacity(self) -> bool:
        """THE finding. An idle floor beside a backlog that has ready work is the one thing here
        that costs something every hour it stays true."""
        return self.idle and bool(self.ready)

    @property
    def blocked_by_refinement(self) -> bool:
        """Idle, with a backlog, and nothing in it is ready. The answer is not "pick something" —
        it is "these need criteria first", which is the product role's own job."""
        return self.idle and not self.ready and bool(self.needs_refinement)



    @field_validator("todo", "ready", "needs_refinement", "parked", mode="before")
    @classmethod
    def _ref_lists_are_strings(cls, v):
        """Same rule as the scalar refs above, for the collections of them."""
        from openfactory.contracts.refs import canonical_ref

        return [canonical_ref(x) for x in v] if isinstance(v, list) else v

def has_criteria(ticket: Ticket) -> bool:
    text = (ticket.body or "").lower()
    # TRIAGE'S OWN LIST (#24 item 7): a second copy here had already drifted — it
    # lacked "given /dado que", so a ticket triage passed could be called untestable
    # by this check. One list, one opinion.
    return any(marker in text for marker in CRITERIA_MARKERS)


def readiness(tickets: list[Ticket], *, todo_column: str = "TO-DO",
              active_columns: tuple[str, ...] = ("In progress",),
              backlog_column: str = "Backlog") -> Readiness:
    """Read the board's state. Pure, so the claim "the factory is idle and could be working" is
    arithmetic a human can check rather than something a model asserted."""
    out = Readiness()
    for t in tickets:
        if t.state != "open":
            continue
        if t.column in active_columns:
            # a human-owned ticket is not the factory working — counting it as busy would hide an
            # idle floor behind a spike somebody parked there months ago
            if t.human_owned or t.is_container:
                out.parked.append(t.number)
            else:
                out.in_progress += 1
        elif t.column == todo_column:
            out.todo.append(t.number)
        elif t.column == backlog_column:
            if t.human_owned or t.is_container:
                out.parked.append(t.number)
            elif has_criteria(t):
                out.ready.append(t.number)
            else:
                out.needs_refinement.append(t.number)
    return out


class Proposed(BaseModel):
    ticket: str
    why: str = ""

    #: WHAT THE CLIENT WILL BE ABLE TO TEST when this and its siblings land — named in their terms,
    #: empty when the item delivers something testable on its own.
    #:
    #: The product owner, 2026-07-31: *"it has to be able to organise logical batches of tasks"*.
    #: The queue was an ordered list cut at five, with no way to say "these three only make sense
    #: delivered together" — and half a change in staging is precisely the thing a client CANNOT
    #: test. Their test is what becomes the production approval, so a queue that can split a
    #: deliverable does not merely look untidy: it produces a staging environment nobody can sign
    #: off, which is the one thing this whole surface exists to reach.
    batch: str = ""



    @field_validator("ticket", mode="before")
    @classmethod
    def _ref_is_a_string(cls, v):
        """A ticket ref is the provider's own string (C-05); an int still constructs, because
        every producer reads a tracker that may hand back either and hundreds of call sites pass
        a bare number."""
        from openfactory.contracts.refs import canonical_ref

        return None if v is None else canonical_ref(v)

class QueueProposal(BaseModel):
    """An ordered suggestion for what to start next, and what is deliberately left out."""

    items: list[Proposed] = Field(default_factory=list)
    #: candidates held back, with the reason. Stated because "why not this one?" is the first thing
    #: anyone asks of a proposed queue, and a silent omission reads as an oversight.
    held_back: list[Proposed] = Field(default_factory=list)
    note: str = ""


def whole_batches(items: list[Proposed], limit: int) -> tuple[list[Proposed], list[Proposed]]:
    """`(kept, cut)` — the proposal truncated at a BATCH boundary, never inside one.

    THE LIMIT WAS THE DEFECT, not the absence of a label. `items[:limit]` is applied after the
    ordering, so a batch straddling position five was silently cut in half: two of its three
    tickets queued, the third left in the backlog, and staging carrying a change the client cannot
    exercise. A group that only means something whole must be admitted whole or not at all.
    N BIGGER THAN THE LIMIT IS ADMITTED ANYWAY when it comes first, because the alternative is
    proposing nothing at all while the floor sits idle — the limit is a courtesy about message
    length, and the batch is a statement about testability. The caller says so in the note; it is
    never a silent stretch.

    Ungrouped items (`batch == ""`) are their own unit of one: an item that delivers something on
    its own is exactly what the limit was written for.
    """
    order: list[str] = []
    groups: dict[str, list[Proposed]] = {}
    for index, item in enumerate(items):
        # an unlabelled item is its own group — keyed by position so two of them never merge
        key = item.batch.strip() or f"\x00{index}"
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(item)

    kept: list[Proposed] = []
    cut: list[Proposed] = []
    for key in order:
        group = groups[key]
        if not kept or len(kept) + len(group) <= limit:
            kept += group
        else:
            cut += group
    return kept, cut


_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences):
{"items": [{"ticket": int, "why": str, "batch": str}],
 "held_back": [{"ticket": int, "why": str}],
 "note": str}
`items` is ORDERED — first is what should start first. Only propose tickets from the candidate list.
`why` is one short sentence in the product's terms: what it unblocks, who is waiting, what it
completes. Never a technical reason.
`batch` groups tickets that ONLY MAKE SENSE DELIVERED TOGETHER — name what the client will be able
to try once the whole group is done, in their words ("emitir e cancelar uma nota", not "backend do
módulo fiscal"). Keep grouped items adjacent in the order. Leave it empty when a ticket delivers
something testable on its own, which is the common case: group only when half of it would be
untestable, never to tidy the list up.
Hold something back when starting it now would be wasteful — it duplicates work already in flight,
it depends on something not done, or it reverses a decision somebody should reconsider first."""


def _named(numbers: list[str], titles: dict[str, str] | None = None) -> str:
    """`#31: título · #32: título` — identity first, description when the caller has it.

    Bare numbers are what made the "not candidates" block unanswerable: the prompt asks whether one
    of them looks MORE VALUABLE than what was proposed, over a list of integers. The role said so
    itself, once: *"tenho só os identificadores dos itens, não o texto de cada um… não consigo
    dizer o que é duplicado, o que ficou obsoleto ou o que é urgente."*"""
    # KEYS NORMALISED BEFORE THE LOOKUP (C-05). A ref is a string now, but `titles` is built by
    # callers from whatever they were holding, and `{47: "…"}.get("47")` is None — so a mismatch
    # would not raise, it would silently hand the role a list of bare numbers and ask it to judge
    # them. It said so itself once: "tenho só os identificadores dos itens, não o texto de cada
    # um… não consigo dizer o que é duplicado". That sentence is the bug report for this line.
    by_ref = {canonical_ref(k): v for k, v in (titles or {}).items()}
    return " · ".join(f"#{n}" + (f": {by_ref[canonical_ref(n)]}" if by_ref.get(canonical_ref(n))
                                 else "") for n in numbers) \
        or "nada"


def proposal_prompt(*, readiness: Readiness, candidates: list[Ticket], limit: int,
                    titles: dict[str, str] | None = None, total_candidates: int = 0) -> str:
    """What the role is asked, with the arithmetic already done for it.

    The candidate list is given as titles, not as whole tickets: ordering is a judgement about what
    each one DELIVERS, and the bodies would cost more than they add.

    TWO FACTS, NEVER ONE BOOLEAN. The opening line used to read "The factory has nothing queued and
    {nothing|work} in flight" — with "nothing queued" HARD-CODED and the single variable choosing
    the word for the OTHER fact. With TO-DO holding two cards and nothing running, it said "nothing
    queued and work in flight" and BOTH clauses were false: the role ordered a queue while reading
    that the queue did not exist, and proposed as "next to start" a card the poller was about to
    pull. `readiness.idle` collapses two independent facts (`todo`, `in_progress`) into one
    boolean; it is a predicate for deciding WHETHER to propose, never a sentence.

    AND NOTHING IS CUT IN SILENCE. `role._board_section` learned this the expensive way — "a cut
    that does not explain itself makes an agent misdiagnose its own blindness" — and the lesson had
    not reached here: the caller sliced the candidates and this rendered the slice under a heading
    that reads as the whole. `total_candidates` is what makes the overflow sayable, and it belongs
    to the renderer because a caller that forgets it is a caller that goes quiet.
    """
    lines = [
        f"Right now — queued in TO-DO: {_named(readiness.todo, titles)}. "
        f"Being worked on: {readiness.in_progress or 'nada'}. "
        f"Propose what should start next, in order, at most {limit} items.",
        "",
        "You are choosing what the product gains soonest — what unblocks other work, what finishes "
        "something half-delivered, what somebody is waiting on. Never order by technical "
        "convenience; that is not yours to judge.",
        "",
        "Ask of every group you form: could the client TRY the result of half of it? Where the "
        "answer is no, those tickets are one batch and go out together — half a change in staging "
        "is something nobody can sign off, and their sign-off is what releases it to production.",
        "",
        "## Candidates (already checked: each states something testable)",
    ]
    lines += [f"- #{t.number}: {t.title}" for t in candidates]
    hidden = max(0, (total_candidates or len(candidates)) - len(candidates))
    if hidden:
        lines.append(
            f"- (+{hidden} outros candidatos omitidos por orçamento deste prompt, NÃO por falta "
            f"de acesso — não afirme que esta lista é tudo o que existe pronto)")
    if readiness.parked:
        # CALCULATED AND THEN THROWN AWAY. `readiness()` reads labels and bodies to decide these
        # are somebody's (triage.human_owned / is_container) — the expensive part — and the prompt
        # never mentioned them. For the role they did not exist, so "não achei mais nada
        # aproveitável no backlog" was a claim of completeness she had no way to make.
        lines += ["", "## Held by people — not candidates, and NOT non-existent",
                  _named(readiness.parked, titles)]
    if readiness.needs_refinement:
        lines += [
            "",
            "## Not candidates — they state nothing testable yet",
            _named(readiness.needs_refinement, titles),
            "Do not propose these. Mention in `note` if one of them looks more valuable than what "
            "you did propose, so a person can decide whether to fix it first.",
        ]
    lines += ["", _SCHEMA]
    return "\n".join(lines)

"""The product role — one implementation over `ask()`, so every harness can play it.

Like the tech-lead's roles (agent/techlead.py), these differ from one another only in their prompt,
and from harness to harness in nothing at all. Each is "run this read-only prompt against a checkout
and give me the text back".

WHAT IT IS GIVEN, AND WHY THAT SHAPE. The prompt carries an INDEX of the requirements — number,
title, status, what each affects — never their contents. The documents themselves are in the
checkout, and the agent opens the ones that matter. That is the same bargain the Knowledge Layer
makes with code: the map locates, the source verifies. Dumping a whole corpus into every prompt
would cost more with every requirement ever written, which is the opposite of what this platform
sells.

UNREADABLE OUTPUT IS NEVER A SILENT SUCCESS. A draft that could not be parsed comes back as an
explicit failure carrying the raw text, never as an empty requirement that looks authored. The
asymmetry is the reviewer's (adapters/reviewer/harness.py): the damage from a confidently empty
artefact is far worse than from a visible error.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from openfactory.adapters.agent.roles import role_prompt
from openfactory.adapters.reviewer.harness import extract_json
from openfactory.product.corpus import Corpus, Requirement
from openfactory.product.voice import AUDIENCE_RULES

log = logging.getLogger("openfactory.product.role")

#: How the role tells the channel "that was a request, not a question". A marker rather than a
#: second model call: classifying costs a whole extra round trip on every message, and the model
#: has already read the sentence.
REQUEST_MARKER = "[[PEDIDO]]"

#: The role marks a message as a DEFECT REPORT — something the product already promised and is not
#: doing — with `[[DEFEITO]]`, optionally naming the broken promise: `[[DEFEITO:REQ-0007]]`.
#: The distinction is HERS to make, not a keyword list's: "a conciliação duplicou lançamentos" has
#: no bug-shaped word in it, and only somebody who knows the corpus can tell a broken promise from
#: a new desire. The difference matters downstream — a defect cites the requirement it violates
#: and skips the "new promise" ceremony (the promise already exists); a desire dressed as a bug
#: must be ARGUED back into the request flow, or the corpus fills with promises nobody made.
DEFECT_MARKER = "[[DEFEITO"

_DEFECT_RE = re.compile(r"\[\[DEFEITO(?::\s*REQ-?(?P<req>\d{1,4}))?\]\]")

#: One per decision she needs from a person. DECLARED by the model rather than parsed out of its
#: prose: guessing "was that a question?" from free text is exactly the kind of inference that
#: produces both silent drops and phantom commitments — and the two existing markers already prove
#: the pattern works. The label is what a human will read weeks later in a reminder, so it has to
#: stand on its own without the conversation around it.
DECISION_MARKER = "[[DECISAO"

#: Generous on purpose. The first version capped the label at 120 characters — while the prompt
#: ASKS for a self-contained sentence naming the cards it is about, which is naturally longer.
#: The product owner's third real conversation produced three markers of 195, 205 and 158
#: characters: none matched, so none were recorded AND none were stripped, and all three appeared
#: raw in a client's channel. One arbitrary constant, two failures, both invisible until a person
#: read the message.
#: NON-GREEDY UP TO THE CLOSING `]]`, not "anything that is not a bracket". The third leak of the
#: day came from `[^\]\n]`: a decision about the card "[Product] Decrypt document metadata …" has a
#: SINGLE `]` inside its own label, the class stopped there, the closing `]]` was never reached, and
#: the marker was neither parsed nor stripped. Card titles carry bracketed prefixes as a matter of
#: course, so the label must be allowed to contain them.
#: A TEMPERED class — any character that is not the start of the closing `]]`. Non-greedy alone was
#: not enough: with a minimum length of three, `[[DECISAO: a]] texto [[DECISAO: b]]` swallowed both
#: into one label, because the shortest legal match had to grow past the first `]]` to reach three
#: characters. Two decisions became one row with a nonsense label.
#:
#: NO UPPER BOUND, AND THE FOURTH TIME THAT CONSTANT COST SOMETHING. It was 120, then 400, and on
#: 2026-07-31 a real decision — the rule for identifying documents left out of the totals — came in
#: longer than 400, so it was stripped (correctly, the net caught it) and LOST: never recorded,
#: never chased. It only reached a person because the product owner happened to be reading the
#: channel.
#: The ceiling was always redundant: the tempered class cannot run past `]]` or a newline, so the
#: DELIMITER bounds the match and the number added nothing but a cliff. Length is a display
#: concern, and it belongs where a label becomes a stored row (`record_decisions` truncates), not
#: where it decides whether a commitment exists at all.
#:
#: AND IT CROSSES A LINE BREAK, for the same reason the net below does — but here the stake is
#: different and higher. The net only decides whether plumbing LEAKS; this decides whether a
#: commitment EXISTS. A decision the model wrapped over two lines was stripped by the net and
#: recorded by nothing: never chased, never answered, and loud only in a log. The label is one
#: sentence, so a blank line ends it; that is the boundary, not a number.
_DECISION_RE = re.compile(
    r"\[\[DECISAO:\s*(?P<label>(?:(?!\]\])(?:[^\n]|\n(?!\s*\n))){3,})\]\]")

#: The person asked to START THE WORK that is already agreed — the gesture the queue proposal
#: answers. Declared by the model for the same reason the three above are, and after the word list
#: that used to be its ONLY door let the most natural phrasing through.
#:
#: On 2026-08-01 the owner asked "podemos avançar?" and got a conversation instead of a queue.
#: `avançar` and `seguir` were not in the verb list; `começar`, `iniciar`, `tocar` and `arrancar`
#: were. The list had been written the day before, to REPLACE operator vocabulary — and it replaced
#: one closed dictionary with another, keeping the shape that fails: a regex guessing at natural
#: language on a surface where a model is already reading every word of it.
#:
#: THE REGEX STAYS, as a shortcut. When it matches, the answer costs one model call instead of two
#: and nothing regresses. What changes is that missing a word now costs a round trip rather than
#: the gesture — the pattern stopped being the only door.
QUEUE_MARKER = "[[FILA]]"

#: PARSE NARROWLY, STRIP BROADLY. Whatever we failed to understand must still never reach a person:
#: a marker with an unexpected shape, a typo, a new one somebody adds later.
#:
#: UNBOUNDED WITHIN A LINE, and that is the whole point. The first version carried `{0,400}` — the
#: SAME bound as the parser above — so a marker of 450 characters escaped BOTH: not recorded, and
#: not stripped either — it reached the client raw. A safety net that shares the failure mode of
#: what it protects is not a safety net; reusing the same number was the reflex to avoid.
#:
#: AND IT CROSSES LINE BREAKS NOW, up to a blank one. `[^\n]` was the third version of the same
#: mistake in one regex: a marker the model wrapped over two lines matched neither the parser nor
#: the net, and reached the client raw. The delimiter is a BLANK line, not a numeric cap — a marker
#: is one directive and never contains a paragraph break, so the boundary is structural and there
#: is no constant here to be wrong by a hundred characters next time.
_ANY_MARKER_RE = re.compile(r"\[\[(?:(?!\]\])(?:[^\n]|\n(?!\s*\n)))*\]\]")

#: A marker OPENED and never closed — `[[SUGGEST: …` with no `]]` anywhere. The net above cannot
#: see it (there is nothing to close the match), so it reached the client whole: the plumbing AND
#: the rest of the line it was on. Recorded as a known limit rather than fixed, which is how it was
#: still there to be found.
#:
#: STRIPPED TO END OF LINE, and only for a marker-SHAPED opener: `[[` followed by three or more
#: capitals. That is what every marker this codebase defines looks like, and it is what keeps the
#: net off ordinary text — "veja [[isto" and a markdown wiki link stay untouched. Deliberately
#: narrower than the net above, because this one deletes text nobody balanced.
_UNCLOSED_MARKER_RE = re.compile(r"\[\[[A-Z]{3,}[^\n]*")

def _cards_from_dicts(board: dict[str, str] | None, titles: dict[str, str]) -> list | None:
    """The two legacy dicts, folded into the one shape every renderer reads.

    Callers that only ever had `{number: column}` and `{number: title}` keep working, and the cards
    they produce carry NO `state` — which is the honest result, not a gap to paper over. A ticket
    whose state is unknown is printed without a verdict about delivery; inferring one from the
    column is precisely the mistake this whole change exists to make impossible.

    `None` in, `None` out: "the board could not be read" must survive the conversion, or the
    prompt would announce an empty board where there was an outage.
    """
    if board is None:
        return None
    from openfactory.product.triage import Ticket

    # `state=""` EXPLICITLY. `Ticket.state` defaults to "open", so a card rebuilt from the legacy
    # dicts would CLAIM to be open — and an open card sitting in `Done` is a real divergence
    # (`triage.done-but-open`) that the renderer marks. Left at the default, every card from a
    # legacy caller was announced as an anomaly it had no evidence for. Unknown must LOOK unknown.
    return [Ticket(number=n, title=titles.get(n, "") or "", column=column or "", state="")
            for n, column in sorted(board.items())]


#: A marker that LOOKS like a decision but did not parse. Stripped like any other plumbing — and
#: shouted, because a decision the agent asked for and nobody recorded is exactly the silent loss
#: the decision ledger exists to prevent.
_DECISION_SHAPED_RE = re.compile(r"\[\[DECISAO", re.IGNORECASE)

_FALLBACK = (
    "You are the product owner, business analyst and delivery manager for this product. You own "
    "WHAT gets built and why; you never write code. Every factual claim cites its source — a "
    "requirement number, a file, an issue — and where you cannot cite, you say you do not know. "
    "Push back, citing evidence, when a request contradicts something already decided."
)


class Conflict(BaseModel):
    """A tension between what was asked for and what the product already promises. The single most
    valuable thing this role produces, so it is a first-class field rather than prose."""

    requirement: int | None = None
    #: `contradicts` · `duplicates` · `narrows` · `depends_on`
    kind: str = "contradicts"
    explanation: str = ""


class RequirementDraft(BaseModel):
    title: str = ""
    why: str = ""
    must_be_true: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    affects: list[str] = Field(default_factory=list)
    #: what the role could not determine and a human must answer. An empty list after a vague
    #: request is a warning sign, not a success.
    questions: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    supersedes: list[int] = Field(default_factory=list)


class IssueDraft(BaseModel):
    title: str = ""
    objective: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    #: which source repo this unit of work lands in. A product spans N repos; a job targets one.
    target_repo: str = ""
    #: the requirement this executes. Nothing may appear in an issue that is not in a requirement.
    cites: int | None = None

    #: THE CARD THAT ALREADY DOES THIS, when the breakdown recognises one on the board.
    #:
    #: Its absence is what filed `#511`, an exact duplicate of `#288`, two messages after the role
    #: had promised the client that "nenhum card novo duplica isso". The board was ALREADY in this
    #: prompt — the diagnosis that it was not is wrong. What was missing is subtler and worse: the
    #: task said "break this into issues" and the answer shape held nothing but issues to create.
    #: A model that DID recognise the duplicate had no way to say so; the only sentence available
    #: to it was "create this". A promise the output schema cannot express is a promise the system
    #: cannot keep, no matter what the prompt says or how good the model is.
    #:
    #: Verified against the board before it is honoured (`module._file_one`) — a number nobody can
    #: confirm files the work anyway, because a duplicate is visible and repairable while work
    #: dropped on an unchecked claim is invisible for ever.
    #: THE TRACKER'S OWN REF (C-05), so a provider that does not number its tickets can still be
    #: answered about. Typed `int` until then, which made this field unable to express the one
    #: thing it exists for on a Jira board — the same class of hole the field itself was written
    #: to close.
    already_on_board: str | None = None

    @field_validator("already_on_board", mode="before")
    @classmethod
    def _ref_as_written(cls, v):
        """A model asked for a card number answers `412` as often as `"412"`, and `#412` too.
        Coerced here rather than at each reader: the verification against the board is an identity
        test, and `412 in {"412"}` is False."""
        from openfactory.contracts.refs import canonical_ref

        return canonical_ref(v) or None if v is not None else None


class ProductAnswer(BaseModel):
    """Any of the role's outputs, plus whether it could be read at all."""

    ok: bool = True
    text: str = ""
    error: str = ""
    draft: RequirementDraft | None = None
    issues: list[IssueDraft] = Field(default_factory=list)
    baseline: object | None = None  # a brownfield.Baseline; typed loosely to avoid a cycle
    #: the person was ASKING FOR SOMETHING rather than asking a question — the signal that turns a
    #: conversation into a draft. Without it the write path is unreachable from a chat: every
    #: message would be answered and nothing would ever be written down.
    is_request: bool = False
    #: Decisions she asked a human for in this reply (see DECISION_MARKER). Each becomes a tracked
    #: loop — otherwise the request exists only in a chat message that scrolls away.
    decisions: list[str] = Field(default_factory=list)
    #: the message reports that an EXISTING promise is broken (see DEFECT_MARKER)
    is_defect: bool = False
    #: A CONVERSATIONAL GESTURE the model recognised (see QUEUE_MARKER) — "" for none.
    #:
    #: A string and not a bool, deliberately. The three markers above each grew their own field,
    #: and a fourth flag would make five booleans describe one question ("what was this person
    #: doing?") that only ever has one answer. The next gesture is a value here, not a column.
    gesture: str = ""
    #: the brownfield reading, when this answer came from `survey`
    baseline: object | None = None
    #: the requirement the role believes is violated — None when it could not name one
    violates: int | None = None
    raw: str = ""


_DRAFT_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences):
{
  "title": str,
  "why": str,
  "must_be_true": [str],
  "out_of_scope": [str],
  "affects": [str],
  "questions": [str],
  "supersedes": [int],
  "conflicts": [{"requirement": int|null,
                 "kind": "contradicts"|"duplicates"|"narrows"|"depends_on",
                 "explanation": str}]
}
Leave a list empty rather than inventing entries. If the request contradicts an existing
requirement, `conflicts` must say so — that is more important than producing a draft.

`supersedes` IS NOT OPTIONAL WHEN YOU ARE REWRITING. If what you are drafting REPLACES a
requirement that already exists — a corrected version, a broader version, the same promise said
better — name that requirement's number there. The field existed and this instruction did not, so a
corrected requirement was written as a SECOND live requirement about the same promise: two texts,
both `proposed`, and a factory that would eventually defend whichever it read first. The product
role warned about exactly this before it happened ("você fica com duas versões do mesmo requisito
para conciliar") and was right.

A revision supersedes. A genuinely new promise does not. If you are unsure which one you are
writing, you are writing a revision."""

_ISSUES_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences):
{"issues": [{"title": str, "objective": str, "acceptance_criteria": [str],
             "out_of_scope": [str], "target_repo": str, "cites": int,
             "already_on_board": str|null}]}
Each issue must be ONE cohesive, independent, testable outcome. If describing it honestly needs the
word "and", split it. Every issue cites the requirement number it executes.

`already_on_board` is how you say "this front already exists": set it to that card's number and it
will be reused instead of created — keep the entry, it is how the requirement gets linked to the
work. Use it whenever an open card covers the same outcome, EVEN IF it is worded differently or in
another language; matching by title is not the test, matching by outcome is. Leave it null when the
work is genuinely new."""


_SURVEY_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences):
{
  "observations": [{"title": str, "behaviour": str,
                    "evidence": "asked"|"tested"|"code",
                    "citations": [str], "area": str}],
  "covered": [str],
  "not_covered": [str],
  "questions": [str],
  "commit": str
}
`citations` carries files, test names or issue numbers — whatever supports the claim. Never claim
`asked` without pointing at where a person asked. An empty `not_covered` says you surveyed
everything, so leave it empty only if that is true."""


#: WHAT SHE MAY SAY ABOUT HER OWN WORKSPACE — the one claim this prompt took on faith.
#:
#: Seven consecutive mounts logged `entries=2 docs_entries=2 code_entries=33` and not one empty,
#: while she told the client "o que está montado para mim veio vazio" — once four minutes after
#: having read and transcribed a requirement out of that same mount. The platform side is ruled out
#: by measurement (`module._log_mount`); what is left is a statement about her own environment that
#: she never tried to verify. Cite-or-say-you-do-not-know (product.md, ADR-0021) always governed
#: what she says about the PRODUCT and never what she says about her own access — and the second is
#: the one a client hears as "your product owner cannot see your product".
#:
#: SHARED BY BOTH MOUNT STATES on purpose: every observed occurrence happened with the code
#: MOUNTED, so a rule living only in the degraded branch would have caught none of them.
_CLAIM_MUST_BE_EARNED = [
    "",
    "The list above was measured when this prompt was built; anything else about your workspace "
    "you establish by opening it.",
    "**That you cannot open something is a CLAIM, and you earn it by trying** — list the "
    "directory, open the file. What a listing LOOKS like decides nothing: an unfamiliar shape is "
    "not an absence, and a guess about your own workspace is invention exactly like an invented "
    "requirement.",
    "So never write that something is empty, missing or unreadable unless an attempt failed and "
    "you can name it: the path you opened and what came back. With no failed attempt to name, "
    "there is nothing to report — read what is there and answer the question.",
]


def requirement_index(corpus: Corpus, *, include_superseded: bool = False) -> str:
    """The corpus as a compact index: where to look, not what it says.

    Superseded requirements are excluded by default — they are kept as history and must never be
    handed to an agent as current truth — but can be included when the question is about history."""
    rows = corpus.requirements if include_superseded else corpus.live()
    if not rows:
        return "(this product has no requirements written down yet)"
    lines = ["| req | status | title | affects | file |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x.number):
        status = r.status if r.superseded_by is None else f"superseded-by {r.superseded_by:04d}"
        # the file column is the point of the index: it is the path the agent opens next
        lines.append(f"| REQ-{r.number:04d} | {status} | {r.title or r.slug} | "
                     f"{', '.join(r.affects) or '—'} | `{r.path}` |")
    return "\n".join(lines)


class ProductRole:
    """The PO/BA/delivery role, over whichever harness a project configured for it.

    Composes an adapter rather than subclassing one: the product axis is separate from the
    executor's, so a deployment can write code with one engine and reason about requirements with
    another."""

    def __init__(self, agent, *, corpus: Corpus | None = None, agent_name: str = "",
                 domain=None, board: dict[int, str] | None = None,
                 titles: dict[int, str] | None = None,
                 #: The board as WHOLE TICKETS — the one the caller should pass. `board`/`titles`
                 #: remain for the tests and callers that only ever had those two dicts, and are
                 #: folded into the same view below. Two parameters describing one thing is a
                 #: transition, not a design: everything that RENDERS reads `self.cards`.
                 cards: list | None = None,
                 mounted: dict[str, str] | None = None,
                 #: Which client's row a metered run belongs to. Defaulted rather than required so
                 #: no existing construction breaks — but a run metered under "" is a row nobody
                 #: can attribute, so the caller that has a project passes it.
                 project_name: str = "",
                 #: What is staged awaiting a person's confirmation, in one line — or "" for
                 #: nothing. THE FACT SHE WAS MISSING when she announced five registered
                 #: requirements: she had no way to know her own proposal was still pending.
                 pending_proposal: str = "",
                 #: The project's language, so the DIALECT reaches the model. It was known all
                 #: along and never passed: the first real conversation came back in European
                 #: Portuguese to a Brazilian reader.
                 language: str = "") -> None:
        self.project_name = project_name
        self.pending_proposal = pending_proposal
        self.language = language
        self.agent = agent
        self.corpus = corpus or Corpus()
        self.domain = domain
        self.board = board
        #: ticket → title. Without it the role sees only NUMBERS, and it said so to the client on
        #: its first real conversation: "tenho só os identificadores dos itens, não o texto de
        #: cada um... não consigo dizer o que é duplicado, o que ficou obsoleto ou o que é
        #: urgente". A board injected as bare ids cannot support a single judgement worth making.
        self.titles = titles or {}
        #: THE BOARD AS WHOLE TICKETS — what every renderer reads. Built from `cards` when the
        #: caller has them, and reconstructed from the two legacy dicts otherwise, so one code path
        #: renders both. A ticket rebuilt from `board`/`titles` carries no `state`, which is
        #: exactly right: it says "unknown", and `_board_section` then refuses to qualify it rather
        #: than guessing from the column — the mistake that would have let "#500 está entregue" be
        #: said about a card closed as `not_planned`.
        self.cards = list(cards) if cards is not None else _cards_from_dicts(board, self.titles)
        #: what is actually readable in the workspace — `{"docs": path, "code": path}`, with an
        #: empty `code` when the source could not be checked out. The prompt is BUILT FROM THIS
        #: rather than asserting access: the role's own instructions promised the source code
        #: while the runtime handed over documentation alone, so it told a client it had verified
        #: things it had no way to open. A prompt that describes what is mounted cannot lie.
        self.mounted = mounted or {}
        self.agent_name = (agent_name or "").strip()
        self.name = getattr(agent, "name", type(agent).__name__)

    # ---- the three things it does ------------------------------------------------------------

    def answer(self, *, sandbox, workspace, question: str, context: str = "",
               conversation: str = "") -> ProductAnswer:
        """A teammate's question about the product. Prose back — this renders as a chat message."""
        prompt = self._prompt(
            "Answer the message below. Be concise and concrete; no preamble, no fenced JSON, no "
            "markdown headers. Point at the REQUIREMENT NUMBER behind every factual claim — that "
            "is shared vocabulary — but never at a file path or a ticket, and say plainly when you "
            "cannot tell from what you have.\n\n"
            "THEN decide what the person was doing. If they ASKED FOR SOMETHING the product does "
            "not do yet — a need, a change, a complaint that implies one — end your reply with the "
            f"marker {REQUEST_MARKER} on its own line. If they asked a question, or were "
            "discussing something already decided, do not add it. The marker is how a conversation "
            "turns into a written requirement, so a missing one loses the request and a spurious "
            "one asks somebody to confirm a requirement they never made.\n\n"
            "If instead they REPORTED THAT SOMETHING ALREADY PROMISED IS NOT WORKING — behaviour "
            "that contradicts an accepted requirement — end with [[DEFEITO:REQ-NNNN]] naming that "
            "requirement, or [[DEFEITO]] alone if you cannot name one. Broken promise and new "
            "desire are different things: the first is registered against the existing promise, "
            "the second must be argued into a new one. When you cannot find any promise the "
            "behaviour breaks, say so in your reply — do NOT use the defect marker for a wish.\n\n"
            "IF THEY ASKED TO START THE WORK that is already agreed — \"podemos avançar?\", "
            "\"pode começar?\", \"vamos seguir\", \"manda ver\", any way of asking for the work to "
            f"BEGIN rather than to be discussed — end with {QUEUE_MARKER} on its own line. Answer "
            "them normally as well; the marker is what puts a proposed queue in front of them, and "
            "an approver's yes on that queue is what SPENDS MONEY. So: a plan (\"vamos começar a "
            "discutir o relatório\"), a question about status, or a request for something new is "
            "NOT this gesture — those are the other markers or no marker at all.\n\n"
            "FINALLY: if your reply ASKS A PERSON TO DECIDE SOMETHING — anything you cannot do "
            "without a human choosing — add one line per decision at the very end:\n"
            "    [[DECISAO: <the decision, in one self-contained sentence>]]\n"
            "ONE MARKER PER DECISION, and one for EVERY decision you asked for — if your reply "
            "lists six things you need decided, there are six marker lines. A decision you wrote "
            "in prose and did not mark is invisible to everything except that one chat message: "
            "nobody is reminded and it is gone the moment it scrolls away.\n"
            "Write the label so it still makes sense to somebody reading it in a week with none "
            "of this conversation in front of them: name the cards or requirement numbers it is "
            "about. Length is not a problem — being self-contained matters more than being short. "
            "Add nothing when you asked for nothing: a decision recorded that nobody was asked "
            "for gets chased at a person who has no idea what it refers to.",
            # ORDER IS LOAD-BEARING (ADR-0024 §2): stable first, volatile last. Prompt caching
            # works by prefix, so anything that changes every turn must sit after everything that
            # does not — the conversation and the question are the only two that do.
            (f"## Current state\n{context}\n\n" if context else "")
            + (f"{conversation}\n\n" if conversation else "")
            + f"## Question\n{question}",
            audience="client",
        )
        res = self._ask(sandbox, workspace, prompt, "product_answer")
        # A FAILED RUN IS NOT AN ANSWER. The harness prints its own error to stdout, so a run that
        # could not authenticate produced text — and publishing it put "Your organization has
        # disabled Claude subscription access · Use an Anthropic API key" into a client's channel,
        # which is the exact opposite of everything voice.py exists to guarantee. Observed on the
        # first real conversation.
        if not res.ok:
            return ProductAnswer(ok=False, raw=res.raw_output or "",
                                 error=_failure_reason(res))
        # THE FULL ANSWER, not the 1000-char summary. `_summarize` caps the agent's final message
        # because an operator scanning a job list wants a line, not an essay — but this text is a
        # REPLY TO A PERSON, and the product owner's first real conversation ended mid-word twice
        # ("ninguém decid", "que o cliente precisa entre"). A truncated answer is worse than a
        # short one: the reader cannot tell whether the agent stopped thinking or the message was
        # cut.
        text = (_full_answer(res) or "").strip()
        asked_for_something = REQUEST_MARKER in text
        # PARSED HERE AND NOT LATER. The safety net below strips anything marker-shaped it does not
        # recognise; a gesture read after it would be read from text the net had already emptied,
        # and the change would be built, tested and reached by nothing — this codebase's signature
        # defect, fifteen times over.
        gesture = "queue" if QUEUE_MARKER in text else ""
        defect = _DEFECT_RE.search(text)
        violates = int(defect.group("req")) if defect and defect.group("req") else None
        # the markers are plumbing between the role and the channel — never let them reach a person
        text = text.replace(QUEUE_MARKER, "").rstrip()
        text = text.replace(REQUEST_MARKER, "").rstrip()
        text = _DEFECT_RE.sub("", text).rstrip()
        decisions = [m.group("label").strip() for m in _DECISION_RE.finditer(text)]
        text = _DECISION_RE.sub("", text).rstrip()
        # the safety net: anything marker-SHAPED that survived the specific parsers above is
        # plumbing we did not recognise, and it goes — loudly, because a marker we could not read
        # is information we just lost, and silence would make this exact bug invisible again
        leftover = _ANY_MARKER_RE.findall(text)
        if leftover:
            lost = [x for x in leftover if _DECISION_SHAPED_RE.match(x)]
            if lost:
                # a DECISION the agent asked for that the parser could not read: it will never be
                # recorded and never chased, so the loss has to be loud rather than a warning in a
                # list of warnings
                log.error("OPENFACTORY_PRODUCT_LOST_MARKER a decision-shaped marker did not parse "
                          "and was "
                          "dropped: %s", "; ".join(x[:200] for x in lost[:3]))
            log.warning("unparsed marker(s) stripped before reaching the client: %s",
                        "; ".join(x[:120] for x in leftover[:4]))
            text = _ANY_MARKER_RE.sub("", text)
        # AFTER the balanced net, never before: an opener that DOES close belongs to the net above,
        # which knows where the marker ends. Running this first would cut the rest of the line off
        # a marker that was perfectly well formed.
        unclosed = _UNCLOSED_MARKER_RE.findall(text)
        if unclosed:
            if any(_DECISION_SHAPED_RE.match(x) for x in unclosed):
                log.error("OPENFACTORY_PRODUCT_LOST_MARKER an unclosed decision marker "
                          "was dropped: "
                          ""
                          "%s",
                          "; ".join(x[:200] for x in unclosed[:3]))
            log.warning("unclosed marker(s) stripped before reaching the client: %s",
                        "; ".join(x[:120] for x in unclosed[:4]))
            text = _UNCLOSED_MARKER_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return ProductAnswer(ok=bool(text), text=text, raw=res.raw_output or "",
                             is_request=asked_for_something, decisions=decisions,
                             gesture=gesture,
                             is_defect=defect is not None, violates=violates,
                             error="" if text else "the harness returned nothing")

    def judge_confirmation(self, *, sandbox, workspace, reply: str, proposal: str) -> str:
        """`approve` | `reject` | `neither` — did this reply confirm the pending proposal?

        WHY A MODEL AND NOT A WORD LIST. The lexical gate accepts "sim" and "pode registrar" and
        nothing that needs interpretation, which is correct for what it is and useless for how
        people actually answer. The product owner answered a staged requirement with "Sim —
        registre. E duas coisas antes das decisões…" ("Yes — record it. And two things before the
        decisions…"), the gate said no, nothing was written, and the agent then told him it had
        been. Widening the list was tried: a first-sentence rule accepted that sentence AND
        "certo — e quem audita isso?" ("right — and who audits that?"), which is a question. No
        vocabulary can separate an affirmation from a word that appears inside one — reading can.

        The product owner, on being shown the narrow fix: *"having to be a literal 'sim, registre'
        every time makes no sense — it has to understand affirmations in their different forms."*

        BIASED TOWARDS `neither`. This gate opens a write in somebody's name, so an unclear answer
        must leave the proposal pending — the person says it again, which costs one message. A
        wrong `approve` records a requirement nobody agreed to, which costs trust.
        """
        prompt = self._prompt(
            "Decide ONE thing and answer with ONE word, nothing else.\n\n"
            "A proposal is waiting for this person's approval. Did their reply APPROVE it?\n\n"
            "`approve` — they agreed, in whatever words. Instructions, praise, corrections to "
            "OTHER matters or extra commentary after the agreement do not weaken it: a person who "
            "says yes and then keeps talking still said yes.\n"
            "`reject` — they declined, or want THIS proposal changed before it is recorded. A "
            "conditional yes is a reject: \"sim, mas mude o prazo primeiro\" has not approved what "
            "is on the table.\n"
            "`neither` — they said something else entirely, asked a question about it, or you are "
            "not sure. WHEN IN DOUBT ANSWER `neither`: approval opens a write in their name, and "
            "leaving it pending only costs them one more message.\n\n"
            "Answer with exactly one of these words — approve, reject or neither — as your whole "
            "reply, or alone on its final line. No punctuation, no explanation: anything else "
            "cannot be read and is treated as `neither`.",
            f"## The proposal awaiting approval\n{proposal[:1200]}\n\n"
            f"## Their reply\n{reply[:2000]}",
            audience="team",  # a one-word verdict for the platform, never shown to a person
        )
        res = self._ask(sandbox, workspace, prompt, "product_confirm")
        if not res.ok:
            # a failed judgment is NOT a rejection and NOT an approval — the proposal stays put
            log.warning("could not judge the confirmation (%s)", _failure_reason(res))
            return "neither"
        raw = _full_answer(res) or ""
        verdict = _verdict_token(raw, ("reject", "approve", "neither"))
        if verdict:
            return verdict
        log.warning("unparseable confirmation verdict %r — leaving the proposal pending", raw[:80])
        return "neither"

    def judge_acceptance(self, *, sandbox, workspace, reply: str, delivered: str) -> str:
        """`worked` | `did-not-work` | `neither` — did the client say the delivery solved it?

        The lexical gate keeps only what ASSERTS the thing works ("resolveu", "funcionou"). It used
        to also take "ok", "beleza", "conferi" and "testei", so "ok, entendi" closed a delivery as
        ACCEPTED and "testei" — a sentence that says somebody tested and nothing about the result —
        did the same. Both are false accepts, and a false accept is the expensive direction: the
        record then says the client signed off on something they never confirmed, which is precisely
        the claim this platform sells and must never fabricate (ADR-0021).

        BIASED TOWARDS `neither`, asymmetrically: an unanswered acceptance stays visibly open and
        costs one reminder, while a wrong `worked` closes it with a sign-off nobody gave.
        """
        prompt = self._prompt(
            "Decide ONE thing and answer with ONE word, nothing else.\n\n"
            "This person was told a delivery was ready and asked whether it solved their problem. "
            "Did their reply say it WORKS?\n\n"
            "`worked` — they said it is solved, in whatever words.\n"
            "`did-not-work` — they said it is not solved, or described something still wrong. Any "
            "remaining complaint means not solved, even alongside praise.\n"
            "`neither` — they acknowledged you without answering (\"ok\", \"entendi\"), said they "
            "will look later, said only that they TESTED without saying the outcome, "
            "asked something else, or you are not sure. WHEN IN DOUBT ANSWER `neither`: an open "
            "acceptance costs one reminder, while a wrong `worked` records a sign-off they never "
            "gave.\n\n"
            "Answer with exactly one of these words — worked, did-not-work or neither — as your "
            "whole reply, or alone on its final line. No punctuation, no explanation: anything "
            "else cannot be read and is treated as `neither`.",
            f"## What they were told was delivered\n{delivered[:900]}\n\n"
            f"## Their reply\n{reply[:1200]}",
            audience="team",
        )
        res = self._ask(sandbox, workspace, prompt, "product_accept")
        if not res.ok:
            log.warning("could not judge an acceptance (%s)", _failure_reason(res))
            return "neither"
        raw = _full_answer(res) or ""
        # did-not-work stays FIRST: it contains "work", so denial must precede affirmation for
        # any parse of this tuple — the exact-token parse never scans a sentence at all
        verdict = _verdict_token(raw, ("did-not-work", "worked", "neither"))
        if verdict:
            return verdict
        log.warning("unparseable acceptance verdict %r — leaving it open", raw[:80])
        return "neither"

    def draft(self, *, sandbox, workspace, request: str, asked_by: str = "") -> ProductAnswer:
        """Turn a request into a requirement draft — and, more importantly, into the conflicts it
        creates with what the product already promises."""
        prompt = self._prompt(
            "Someone has asked for the change below. FIRST check it against the requirements "
            "that already exist: open the ones the index suggests are related. Report any "
            "contradiction, duplication or narrowing you can cite. THEN draft the requirement.",
            f"## The request\n{request}"
            + (f"\n\n## Asked by\n{asked_by}" if asked_by else ""),
            _DRAFT_SCHEMA,
            audience="client",
        )
        res = self._ask(sandbox, workspace, prompt, "product_draft")
        if not res.ok:
            return ProductAnswer(ok=False, raw=res.raw_output or "", error=_failure_reason(res))
        raw = _full_answer(res)
        try:
            draft = RequirementDraft.model_validate_json(extract_json(raw))
        except Exception as exc:  # noqa: BLE001 — any unreadable shape is the same failure
            return ProductAnswer(
                ok=False, raw=raw,
                error=f"the {self.name} harness's draft could not be read ({type(exc).__name__}). "
                      f"Nothing was written — an unreadable draft must not become an empty "
                      f"requirement that looks authored.")
        if not draft.title or not draft.must_be_true:
            return ProductAnswer(
                ok=False, raw=raw, draft=draft,
                error="the draft has no title or nothing that must be true, so it states no "
                      "testable outcome. Refusing it here beats a job parking on it later.")
        return ProductAnswer(ok=True, draft=draft, raw=raw)

    def issues_for(self, *, sandbox, workspace, requirement: Requirement,
                   sources: list[str]) -> ProductAnswer:
        """Break one requirement into units of work, each citing it — REUSING what already exists.

        The board is in this prompt (`_board_section`) and always was. What made `#511` a duplicate
        of `#288` was not blindness: it was that the task said "break this into issues" and every
        answer shape available said "create". See `IssueDraft.already_on_board`."""
        prompt = self._prompt(
            "Break the requirement below into issues. Each must be ONE cohesive, independent, "
            "testable outcome, and must name which source repository it lands in.\n\n"
            "FIRST READ THE BOARD ABOVE. Some of this requirement is usually already carded — a "
            "breakdown that files what exists costs the client a duplicate and costs you a broken "
            "promise, because you will have said the work is being organised while what you "
            "actually did was file the same thing twice. For every front you would create, look "
            "for an open card that already delivers that outcome and set `already_on_board` to "
            "its number instead. Compare OUTCOMES, not titles: the two cards that collided last "
            "time said the same thing in two languages. If the board section above says it could "
            "not be read, then you do not know what exists — file what the requirement needs and "
            "claim nothing about novelty.",
            f"## Requirement REQ-{requirement.number:04d} — {requirement.title}\n"
            f"(file: {requirement.path})\n\n{requirement.body}\n\n"
            "## Source repositories for this product\n"
            + "\n".join(f"- {s}" for s in sources or ["(none declared)"]),
            _ISSUES_SCHEMA,
        )
        res = self._ask(sandbox, workspace, prompt, "product_issues")
        if not res.ok:
            return ProductAnswer(ok=False, raw=res.raw_output or "", error=_failure_reason(res))
        raw = _full_answer(res)
        try:
            import json

            payload = json.loads(extract_json(raw))
            issues = [IssueDraft(**i) for i in (payload.get("issues") or [])]
        except Exception as exc:  # noqa: BLE001
            return ProductAnswer(ok=False, raw=raw,
                                 error=f"the issue breakdown could not be read "
                                       f"({type(exc).__name__}); nothing was filed")
        if not issues:
            return ProductAnswer(ok=False, raw=raw,
                                 error="the harness produced no issues for this requirement")
        # Nothing may appear in an issue that is not in a requirement — an issue that cites nothing,
        # or cites something else, has drifted from the document it claims to execute.
        for issue in issues:
            issue.cites = requirement.number
        return ProductAnswer(ok=True, issues=issues, raw=raw)

    def survey(self, *, sandbox, workspace, areas: list[str], layout: str = "") -> ProductAnswer:
        """The brownfield first pass: read what exists and report OBSERVATIONS (see brownfield.py).

        Never asks for requirements. The prompt is explicit that a reading of the code is not a
        decision, because a model asked to "write the requirements" from a codebase will happily
        produce confident promises nobody ever made."""
        from openfactory.product.brownfield import Baseline

        prompt = self._prompt(
            "This product's requirements have never been written down, and the code already "
            "exists. Survey it and report WHAT THE SYSTEM APPEARS TO DO — observations, not "
            "requirements. You are not deciding anything and you must not phrase anything as a "
            "commitment: a behaviour you find may be an accident or a bug, and you usually cannot "
            "tell which. Classify each by evidence: `asked` if you can point at an issue or PR "
            "where a person asked for it, `tested` if a test asserts it, `code` otherwise. Look "
            "for the `asked` tier deliberately — it means reading history, not just code, and it "
            "is the only tier that carries real provenance. Say what you did NOT cover, and list "
            "what the code could not answer.",
            (layout + "\n\n" if layout else "")
            + "## Areas to survey in this pass\n"
            + "\n".join(f"- {a}" for a in areas or ["(the whole repository)"]),
            _SURVEY_SCHEMA,
        )
        res = self._ask(sandbox, workspace, prompt, "product_survey")
        if not res.ok:
            return ProductAnswer(ok=False, raw=res.raw_output or "", error=_failure_reason(res))
        raw = _full_answer(res)
        try:
            baseline = Baseline.model_validate_json(extract_json(raw))
        except Exception as exc:  # noqa: BLE001
            return ProductAnswer(ok=False, raw=raw,
                                 error=f"the survey could not be read ({type(exc).__name__}); "
                                       f"nothing was written")
        if not baseline.observations:
            return ProductAnswer(ok=False, raw=raw,
                                 error="the survey found nothing to record")
        return ProductAnswer(ok=True, raw=raw, baseline=baseline)
        return ProductAnswer(ok=True, baseline=baseline, raw=raw)

    def ask_json(self, *, sandbox, workspace, prompt: str, phase: str) -> dict | None:
        """A read-only prompt whose answer is a JSON object, or None when it could not be read.

        None rather than an empty dict: the callers treat "could not read" as the safest verdict,
        and an empty dict would look like a parsed answer with every field defaulted."""
        import json

        res = self._ask(sandbox, workspace, self._prompt("", prompt), phase)
        if not res.ok:
            return None
        raw = _full_answer(res)
        try:
            parsed = json.loads(extract_json(raw))
        except Exception as exc:  # noqa: BLE001 — a model that answered in prose, usually
            log.info("%s: the answer for %s was not JSON (%s) — treated as no answer",
                     self.name, phase, exc)
            return None
        return parsed if isinstance(parsed, dict) else None

    # ---- plumbing ----------------------------------------------------------------------------

    #: The board, as the role sees it: `{ticket: column}`, injected by the caller. NEVER fetched
    #: from inside the agent.
    #:
    #: An agent with a terminal WILL reach for `gh project item-list` when it wants to know what is
    #: in progress — that is the obvious move, and it costs 303 GraphQL points per call (the CLI
    #: bills one request PER CARD), uncapped, as many times as it feels like looking. The platform
    #: reads the board ONCE, cheaply (1 point), and hands the answer over. Same architecture as the
    #: knowledge layer: deterministic context injected beforehand beats an agent exploring at
    #: runtime — cheaper, faster, and reproducible.
    def _sources_section(self) -> list[str]:
        """Where the documentation and the code actually are — or that the code is not there.

        Said explicitly because the alternative already happened: told it had "read access to the
        source code" while holding only the requirements folder, the role could either guess or
        refuse. It refused, which was right, and the refusal cost a client conversation.

        The section describes the LANDING POINT too, not only the two paths. She arrives at a root
        holding two symlinks and nothing else (`module._workspace` — copying two checkouts on every
        message is not an option), which is an unusual place to stand: two odd entries and no files
        is precisely the listing she has read as "there is nothing here"."""
        docs = self.mounted.get("docs") or "."
        code = self.mounted.get("code") or ""
        if not code:
            return ["", "# What you can open",
                    f"- the documentation repository, at `{docs}/` — requirements, domain notes",
                    "- **NOT the source code.** It could not be checked out for this "
                    "conversation. Say so plainly if somebody asks what the product does today: "
                    "you cannot verify behaviour you cannot read, and guessing is worse than "
                    "saying you do not know.",
                    "",
                    # THE HONESTY WAS RIGHT AND THE ADDRESSEE WAS WRONG. Told only that the code
                    # was missing, she wrote to a CLIENT: "o que está montado para mim veio vazio…
                    # preciso que alguém me devolva esse acesso" — machinery he does not know
                    # exists, and a support task he cannot possibly do. The product owner: "a PO
                    # saying that to the client makes no sense; she should be asking the factory
                    # for help."
                    # So the prompt now says who is already handling it, and forbids the ask.
                    "**Do NOT ask the person to restore your access, and do not describe how you "
                    "are assembled.** They bought a product that needs no developer; handing them "
                    "a support task breaks that promise in one sentence. The platform has already "
                    "raised this with the team — it opens a ticket the moment it happens — so the "
                    "true and complete thing to say is one clause: you could not open the code to "
                    "check, so what follows comes from what is written rather than from having "
                    "read it, and the team already knows. Then answer the question with what you "
                    "DO have."] + _CLAIM_MUST_BE_EARNED
        return ["", "# What you can open",
                f"- the documentation repository, at `{docs}/` — requirements, domain notes",
                f"- **the product's source code, at `{code}/`** — read it. A claim about what the "
                f"product does today is worth far more when you have opened the file than when "
                f"you inferred it from a title. Cite the file you read.",
                f"You stand at the root of those two, and they hold REAL FILES — open them. The "
                f"root itself carries no files of its own, so a short listing there is a HEALTHY "
                f"mount and never an empty one: everything is one level in, under `{docs}/` and "
                f"`{code}/`. If a listing surprises you, that is a reason to open something, not "
                f"a finding to report.",
                "Both are read-only: what you write goes through a pull request, never through "
                "these directories."] + _CLAIM_MUST_BE_EARNED

    #: How many card titles per column reach the prompt. Raised from 40 after a real backlog of 52
    #: hid twelve cards from the product role — which noticed the gap, could not see WHY, and asked
    #: the client for board access it already had. A title is ~60 characters, so covering a real
    #: backlog costs a few hundred tokens; being blind to a fifth of it costs a wrong plan.
    #: `Done` is exempt and stays counted-only: 190 finished titles answer no question anybody asks.
    _TITLES_PER_COLUMN = 120

    def _agency_section(self) -> list[str]:
        """WHAT THIS TURN CAN AND CANNOT DO — the block whose absence produced the worst defect yet.

        She already had the requirement index in her prompt, and it said in so many words "(this
        product has no requirements written down yet)". She read that and still answered "Registrado
        o Requisito 1 … Vai para o time conferir". So the failure was NOT blindness to the world.

        It was blindness to HERSELF. The prompt described the product and never described her own
        turn: nothing told her that this reply writes nothing, that a write needs an authorised
        confirmation she does not observe, or — the decisive fact — whether the proposal she made
        last time is STILL WAITING. Given no model of her own agency, she narrated the intended
        end-state of the conversation as if it had happened, which is the most useful thing to say
        and the one thing she could not know.

        A voice rule ("never say it is done") treats that as a manners problem. It is an information
        problem, and this is the information.
        """
        lines = ["", "# What THIS reply can and cannot do",
                 "",
                 "This reply WRITES NOTHING. Not a requirement, not an issue, not a board move.",
                 "A write happens only after an authorised person confirms a proposal, on a code "
                 "path you never see and whose result never comes back to you.",
                 "",
                 "So you cannot know whether anything was recorded, and you must not say it was. "
                 "Propose, and say you are proposing.",
                 ""]
        if self.pending_proposal:
            lines += [f"**There is a proposal STILL AWAITING confirmation right now:** "
                      f"{self.pending_proposal[:300]}",
                      "",
                      "It has NOT been recorded. If the person seems to have approved it and you "
                      "are being asked about it, the honest answer is that it is still waiting — "
                      "never that it is done."]
        else:
            lines += ["Nothing of yours is currently awaiting confirmation."]
        return lines

    def _board_section(self) -> list[str]:
        """The board as prose the model can reason over, grouped by column.

        THE BUDGET MAY DROP A TITLE. IT MAY NEVER DROP AN IDENTITY. That is the rule this section
        was rebuilt around, and it comes from a real answer: asked whether the work could start,
        the role said it could not tell what had become of #511 or #492 — "não sei se foram
        fechados, movidos ou renumerados" — because `Done` was rendered as a COUNT and nothing
        else. Both were in `Done`; one of them she had closed herself the day before. A cut that
        removes the answer is not economy, it is information loss under a nicer name.

        So a number always survives, a title is what the budget takes, and the cut says which it
        was. For 200 finished cards that is ~800 characters against the ~12.000 the titles would
        cost: the economy that motivated the original cut is kept almost whole.

        AND IDENTITY NEVER TRAVELS WITHOUT ITS QUALIFIER. Printing the ids alone would have been
        worse than the blindness: the model could then assert "#500 está entregue" about a card
        closed as `not_planned` — the exact sentence `Ticket.delivered` exists to prevent, and
        which is enforced on the SWEEP's path and was absent here. A card whose state is unknown
        (a caller that passed only the legacy dicts) is printed WITHOUT a verdict rather than with
        a guessed one: the column is not the state, and this repository has two triage rules
        (`done-but-open`, `closed-elsewhere`) precisely because they diverge.
        """
        if self.cards is None:
            return ["", "# The board",
                    "The board could not be read just now — say so if somebody asks about "
                    "status, and do not guess what is where."]
        if not self.cards:
            return ["", "# The board", "The board is empty."]
        by_column: dict[str, list] = {}
        for card in sorted(self.cards, key=lambda c: c.number):
            by_column.setdefault(card.column or "(sem coluna)", []).append(card)
        lines = ["", "# The board (already read for you — do NOT run any command to fetch it)",
                 f"This is the board AS READ FOR THIS MESSAGE — {len(self.cards)} cards. A card "
                 f"absent from it is absent from this reading, which is not the same as absent "
                 f"from the product: say the first, never the second."]
        for column, cards in sorted(by_column.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"\n## {column} ({len(cards)})")
            done_col = (column.lower().startswith("done")
                        or column.lower() in ("concluído", "concluido"))
            # `Done` keeps the economy that motivated the original cut — its titles would cost more
            # than every other column together and answer no question anybody asks — but it keeps
            # the NUMBERS, because "what happened to #511?" is a question a product owner is asked
            # constantly and could not answer at all.
            if done_col:
                lines.append("(títulos omitidos por economia; os números ficam. Sem marca = "
                             "concluído e entregue — só o que contradiz isso é anotado.)")
                lines.append("- " + " · ".join(
                    f"#{c.number}{self._outcome(c, in_done=True)}" for c in cards))
                continue
            for c in cards[:self._TITLES_PER_COLUMN]:
                title = (c.title or "").strip()
                lines.append(f"- #{c.number}{self._outcome(c)}"
                             + (f" — {title}" if title else ""))
            if len(cards) > self._TITLES_PER_COLUMN:
                # SAY WHY IT IS CUT, AND CUT ONLY THE TITLE. The old line was "(+12 outros nesta
                # coluna)" and nothing more, so the role could not tell "I am not allowed to see
                # these" from "the prompt truncated them" — and asked the client for board access
                # it already had. Now the ids of the remainder are still there, so the cut costs
                # description and never existence.
                rest = cards[self._TITLES_PER_COLUMN:]
                lines.append(
                    f"- (+{len(rest)} nesta coluna com o título omitido por orçamento deste "
                    f"prompt, NÃO por falta de acesso — os números seguem abaixo e você pode "
                    f"falar deles: "
                    + " · ".join(f"#{c.number}{self._outcome(c)}" for c in rest) + ")")
        return lines

    @staticmethod
    def _outcome(card, *, in_done: bool = False) -> str:
        """What is TRUE about this card beyond where it sits — or "" when it matches expectation.

        THE EXCEPTION IS WHAT IS PRINTED, and both halves of that are deliberate.

        COST: annotating all 203 finished cards with "(fechado: entregue)" cost 5.700 characters
        in every prompt — seven times what was claimed for it, against the ~12.000 the titles would
        have cost. Marking only what CONTRADICTS the column brings it back to ~1.700 while saying
        strictly more, because an unmarked card in `Done` now means something.

        VOCABULARY: it also stopped putting `fechado` in front of the role two hundred times a
        turn. That word is in `voice._CLAIMED_DONE`, so the prompt was priming her to echo the
        exact token the false-claim detector watches for — a trap of our own making, one day after
        `escrito` had to leave that list for the same reason.

        Never inferred from the column: `close_card` closes a ticket without moving its card, and
        the board's own automation moves cards without anyone closing the ticket. `triage` has a
        rule for each direction (`done-but-open`, `closed-elsewhere`) because both really happen —
        so in `Done` an OPEN card is the exception, and elsewhere a CLOSED one is.
        """
        state = getattr(card, "state", "") or ""
        if not state:
            return ""                      # unknown: a caller that passed columns and titles only
        if in_done:
            if state != "closed":
                return " (ainda aberto)"           # triage's `done-but-open`
            return "" if getattr(card, "delivered", False) else " (cancelado)"
        if state == "closed":
            return " (entregue)" if getattr(card, "delivered", False) else " (cancelado)"
        return ""

    def _prompt(self, instruction: str, body: str, schema: str = "", *,
                audience: str = "team") -> str:
        """`audience="client"` prepends the language rules (voice.py).

        Only the conversational operations get them. An issue body and a survey are read by the
        team and by the executor, and softening those into business prose would strip the detail
        the people acting on them need — the fix is two surfaces, not one vague voice."""
        role = role_prompt("product") or _FALLBACK
        parts = [role]
        if self.agent_name:
            parts += ["", f"# Your name\n\nYou are called {self.agent_name}. People in the "
                          f"channel address you by it. Use it naturally when it helps — signing "
                          f"off, or when several people are talking — and never refer to yourself "
                          f"in the third person."]
        if audience == "client":
            from openfactory.product.voice import language_rules

            parts += ["", AUDIENCE_RULES]
            rules = language_rules(self.language)
            if rules:
                parts += ["", rules]
        parts += ["", "# Task", instruction, "",
                 "# Requirements index (where to look — open the files that matter)",
                 requirement_index(self.corpus)]
        # BEFORE the board and the sources: what she can do bounds everything she then says about
        # what she found. Placed in the stable half of the prompt, ahead of the volatile blocks.
        if audience == "client":
            parts += self._agency_section()
        parts += self._board_section()
        parts += self._sources_section()
        if self.domain is not None and self.domain.facts:
            from openfactory.product.domain import glossary_index

            parts += [
                "",
                "# What we have been told about this business",
                glossary_index(self.domain),
                "",
                "`confirmado` may be stated as fact. `aprendido` came from a conversation and is "
                "ATTRIBUTED, never authoritative — say who told you when you use one, and if it "
                "contradicts a requirement, the requirement wins and the contradiction is worth "
                "raising.",
            ]
        parts += ["", body]
        if schema:
            parts += ["", schema]
        return "\n".join(parts)

    def _ask(self, sandbox, workspace, prompt: str, phase: str):
        """Every product invocation passes through here — which is why the metering lives here.

        ADR-0024 §5: before today the product role's runs were the ONLY agent invocations in the
        platform with no telemetry at all. A scan of 500 rows found `executor` and `repair` and
        zero product turns, so nobody could say what a conversation with her costs — while the
        product is sold on being token-efficient. Injecting conversation history makes each turn
        bigger and is supposed to make it cheaper (she stops re-reading the repositories to
        recover what she should have remembered). That trade has to be MEASURED, not asserted,
        and it cannot be measured retroactively from rows that were never written."""
        started = time.monotonic()
        res = self.agent.ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase)
        self._meter(res, phase, wall_s=round(time.monotonic() - started, 2))
        return res

    def _meter(self, res, phase: str, *, wall_s: float | None = None) -> None:
        """Best-effort, like every other write to this table: a reply must never fail because the
        meter did — but a meter that silently stops is why this gap existed unnoticed."""
        try:
            from openfactory.observability.metrics import MetricRecord
            from openfactory.runtime.temporal.activities import _metrics_sink

            _metrics_sink().record(MetricRecord(
                project=self.project_name, ticket=f"_{phase}_",
                ts=datetime.now(UTC).isoformat(), kind="agent_run", role=phase,
                harness=getattr(self.agent, "name", "") or "",
                cost_usd=getattr(res, "cost_usd", None),
                num_turns=getattr(res, "num_turns", None),
                # HOW LONG THE PERSON WAITED. Cost alone answered "what did it spend"; the first
                # real conversation raised the other question — 2min38s of silence — and it had to
                # be inferred from row timestamps. A number you have to reconstruct is a number
                # nobody looks at.
                wall_s=wall_s,
                input_tokens=getattr(res, "input_tokens", None),
                output_tokens=getattr(res, "output_tokens", None)))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not meter the %s run (%s)", phase, exc)


#: What may surround the verdict word without changing it — markdown, quotes, bullets, sentence
#: punctuation. `?` is deliberately absent: "approve?" is the model asking, not answering, and
#: must fall through to the caller's safe default.
_VERDICT_TRIM = " \t\"'`*_.,;:!—–-()[]{}"


def _verdict_word(line: str) -> str:
    # internal whitespace collapses to hyphens so "did not work" still reads as `did-not-work`
    return re.sub(r"\s+", "-", line.strip(_VERDICT_TRIM))


def _verdict_token(raw: str, verdicts: tuple[str, ...]) -> str:
    """The judge's one-word answer, or "" when the reply does not commit to exactly one.

    AN EXACT TOKEN, NEVER A SUBSTRING SCAN. The first parse searched for each verdict inside the
    model's COMPLETE final message, affirmation first — so "neither — this wasn't approved yet"
    contained "approve" and opened a write from a verdict the model explicitly refused to give.
    These gates must fail only in the cheap direction (ADR-0028/0029: ambiguity costs a question,
    never a write), so a verdict is read ONLY from a line that IS the verdict: the first or last
    non-empty line, stripped of punctuation, equal to one of `verdicts`. Two lines that both parse
    but disagree are ambiguity too. Everything else returns "" and the caller falls back safe.

    `verdicts` keeps negation before affirmation — "did-not-work" contains "work" — so that even
    a future scan-shaped regression meets the denial first."""
    lines = [ln for ln in (s.strip() for s in (raw or "").lower().splitlines()) if ln]
    if not lines:
        return ""
    found = {w for w in (_verdict_word(lines[0]), _verdict_word(lines[-1])) if w in verdicts}
    return found.pop() if len(found) == 1 else ""


def _full_answer(res) -> str:
    """The agent's complete final message — delegates to the shared reader.

    Kept as a name in this module because five call sites here use it, but the LOGIC lives once,
    at the source (adapters/agent/base.final_text): this workaround had been written three times
    independently, and the one consumer that never wrote it — the reviewer — was silently parsing
    truncated JSON."""
    from openfactory.adapters.agent.base import final_text

    return final_text(res)


def _failure_reason(res) -> str:
    """Why a run failed, for the TEAM's log — never for the channel.

    The caller turns any failure into "I can't see the product right now", because the difference
    between an expired token and a crashed CLI is not something a client can act on, and the raw
    text is where infrastructure leaks into a business conversation."""
    if getattr(res, "pause_reason", None) == "auth":
        return "the harness could not authenticate"
    if getattr(res, "pause_reason", None) == "rate_limit":
        return "the harness hit a usage limit"
    return f"the harness run failed: {(res.summary or '')[:200]}"

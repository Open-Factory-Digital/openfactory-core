"""The backfill's questions, with an identity and a way to be finished.

`propose_context` has always produced questions — the deterministic ones the survey earns, the
claims whose citations failed, and the ones the agent could not anchor. They are rendered into
`docs/perguntas-abertas.md` and into the onboarding pull request body, and there they stop:
`list[str]`, no identity, no state, no way to know whether one was ever dealt with. Re-run the
backfill next month and the same six questions are asked again, indistinguishable from six new
ones.

This gives the derivable ones an identity and a closing observation, so they become loops the
platform can carry rather than sentences it emits.

WHY ONLY THE DERIVABLE ONES, and it is a scoping decision rather than a first instalment. A loop
needs an identity that survives a re-run. A question the SURVEY earns has one by construction:
`blind-modules` is the same question next month, because the same code derives it from the same
kind of fact. A question an LLM wrote does not — the wording drifts, and hashing the text would
open a fresh loop on every pass and chase a person about a question they already answered. The
model's questions keep going where they already go, into the document that starts the conversation.

The same rule the ledger states about closing applies to opening: what can be re-derived can be
tracked; what cannot, cannot.

WHY A KIND OF ITS OWN, and the ledger already carries the scar. `followup.answered()` closes every
open `QUESTION` whose `subject:about` is not among the board's live findings — closing by ABSENCE.
A question about a codebase has no board finding at all, so the very next product sweep would close
it as "resolved" and it would leave the ledger minutes after being opened. `DECISION` exists for
exactly that reason and says so in its own comment; this is the second instance of the same trap.

`to_open` also refuses to crowd the product's own budget: `followup.MAX_QUESTIONS_PER_PASS` counts
already-open `QUESTION` loops, so context questions sharing that kind would push a stalled ticket's
question out of the batch that reaches a person.
"""

from __future__ import annotations

from dataclasses import dataclass

from openfactory.memory.ledger import CONTEXT, Loop, close_by_observation, open_loop, waiting

#: The closed set of questions the deterministic survey can derive, one per gap it can see.
#:
#: CLOSED, unlike the concept taxonomy that is deliberately open — and the difference is not a
#: preference. A concept type describes a client's system, so every company has its own. These are
#: derived BY THIS CODE from a survey it produced, so the set is exactly what `_survey_questions`
#: can earn: a seventh code without a seventh derivation would be a question nothing can ever ask
#: and nothing can ever close.
BLIND_MODULES = "blind-modules"            # modules whose only description is their folder name
UNREAD_CODE = "unread-code"                # a stack living here the structural map cannot read
UNTESTED_MODULES = "untested-modules"      # modules no test file even names
UNREADABLE_DIRS = "unreadable-dirs"        # directories the walk could not open
NO_ENTRY_POINTS = "no-entry-points"        # nothing that looks like a door was found
DROPPED_TERMS = "dropped-terms"            # vocabulary the stoplist removed, offered back
CODES = (BLIND_MODULES, UNREAD_CODE, UNTESTED_MODULES, UNREADABLE_DIRS, NO_ENTRY_POINTS,
         DROPPED_TERMS)

#: How a context loop ends, in this kind's own vocabulary. The gap the question was about is gone
#: — not "somebody replied", which this never observes and must never claim.
GAP_CLOSED = "gap-closed"


@dataclass(frozen=True)
class SurveyQuestion:
    """One question the survey earned, and the code that makes it the same question next month."""

    code: str
    text: str


def to_open(questions: list[SurveyQuestion], *, repo: str, waiting: list[Loop],
            ts: str) -> list[Loop]:
    """The loops to append for questions not already open on this repository.

    Deduplicated on `(subject, about)` rather than on the text, which is the whole point of the
    code: the same gap re-derived with different wording is the same question, and opening it twice
    would chase a person about something they are already looking at.

    NO CAP, deliberately, where `followup` has one. That cap exists because board findings are
    unbounded — a hundred stalled tickets are a hundred questions. These are bounded at
    `len(CODES)` by construction, so a cap would only ever hide one of six.
    """
    already = {loop.about for loop in waiting
               if loop.kind == CONTEXT and loop.subject == repo and loop.waiting}
    return [open_loop(CONTEXT, repo, owner="onboarding", ts=ts, about=q.code,
                      context={"text": q.text})
            for q in questions if q.code not in already]


def resolved(waiting: list[Loop], *, repo: str, fresh: list[SurveyQuestion],
             surveyed: bool) -> dict[tuple[str, str, str], str]:
    """Which open questions a fresh survey says are gone — `{(kind, subject, about): outcome}`.

    A question the survey no longer earns is a gap that closed: the module now has a description,
    the directory now opens, a test now names the module. That is a closing OBSERVATION in the
    ledger's own sense — a pass that looked at the world — and not a report from anybody about
    what they did.

    `surveyed=False` CLOSES NOTHING, AND IT IS THE WHOLE GUARD OF THIS MODULE. A survey that could
    not run produces zero questions, and zero questions read as "every gap is gone" — so a
    repository that became unreadable, a clone that failed, a walk that raised, would silently mark
    every open question answered and the platform would stop asking about a codebase it can no
    longer see. Absence of evidence arriving as evidence of absence is the failure this whole
    codebase is arranged against, and here it would erase the record rather than merely misreport
    it.

    A loop with no entry in the returned map stays open, which `close_by_observation` already
    guarantees — this only ever ADDS closures it can defend.
    """
    if not surveyed:
        return {}
    earned = {q.code for q in fresh}
    return {(CONTEXT, loop.subject, loop.about): GAP_CLOSED
            for loop in waiting
            if loop.kind == CONTEXT and loop.subject == repo and loop.waiting
            and loop.about not in earned}


def carry(repo: str, *, ledger: list[Loop], fresh: list[SurveyQuestion],
          surveyed: bool, ts: str) -> list[Loop]:
    """The rows to APPEND after one backfill pass: what the world resolved, and what is newly asked.

    Pure — it takes the ledger it is given and returns rows. The read and the write belong to the
    caller, which is where the I/O already lives for every other loop on this platform.

    THE NARROWING IS NOT A SAFETY NET, AND SAYING SO IS THE POINT. `resolved` and `to_open` each
    filter by kind and by repository themselves, so a mutation that handed this the whole ledger
    changed nothing observable — which is what proved the claim, not the code, was wrong. It is
    kept because it is where this module NAMES its kind: `test_loops_are_reachable` refuses a
    ledger kind whose closer no live path calls, and this function is that closer. A third filter
    behind two is cheap; a kind with no reachable closer is a row that stays open for ever.

    Closing comes first and opening second, so a gap that closed and immediately reopened within
    one pass is recorded as both rather than silently deduplicated against the row that is about
    to close."""
    mine = [x for x in waiting(ledger, kind=CONTEXT) if x.subject == repo]
    closed = close_by_observation(
        mine, resolved(mine, repo=repo, fresh=fresh, surveyed=surveyed))
    return closed + to_open(fresh, repo=repo, waiting=mine, ts=ts)

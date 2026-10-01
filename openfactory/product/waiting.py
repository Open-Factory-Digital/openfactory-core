"""What the product role waits for from a person in one conversation — as the STORE says it (#452).

TWO THINGS WAIT ON A PERSON'S NEXT WORDS, and both lived in the worker's memory:

    a staged proposal   waiting for its yes — a card, a defect, a requirement, a close, a reorder
                        (`staging.remember`); its record is the `asked` row the panel has read
                        since C-33, with the frozen entry as its payload
    a held question     the one question a card was held on (ADR-0054 D4, `cards.hold_question`);
                        its record is a `held` row carrying the draft and the findings, written
                        since #452

A process that restarts, or the second worker a bigger deployment runs, must read the answer
against what was waiting when it was asked, or the answer is an ordinary message: measured on
`main` before #452, a card question held, the worker's state dropped, and the person's answer —
"it's the Home screen" — started the role's whole turn over, the question forgotten in public.

THE STORE IS THE RECORD, A PROCESS'S MEMORY IS A COPY. The worker keeps a copy of what it staged
or held (`staging._PENDING`, `cards._OPEN`), and believes it only while the store's latest record
under the same key says the same thing, still open; the store decides whenever it can be read.
The worker reads by the key a turn knows (`staging.pending_for`, `cards.take_question`); a page
reads by conversation, here — the panel's buttons (`staging.waiting_in`, #443/#450) and the
Pending tab ADR-0055 D11 builds, which must never say "nothing pending" after a redeploy because
the list it read was a dictionary that restarted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

#: What waits: a proposal for its yes or no, or a question for the person's words.
PROPOSAL, QUESTION = "proposal", "question"

#: The token a held card question is recorded under: this prefix and the key it waits under —
#: `staging.key_for(conversation, person)`, the person's own key in that conversation.
QUESTION_TOKEN = "card-question:"


def question_token(key: str) -> str:
    """The token of the card question held under `key`."""
    return f"{QUESTION_TOKEN}{key}"


@dataclass(frozen=True)
class Wait:
    """One thing waiting for a person in a conversation. `key` is where it waits; `text` what the
    person was asked (the proposal's summary, or the question); `approve`/`reject` the labels a
    proposal was asked with ("" for a question, which has nothing to press)."""

    kind: str
    key: str
    token: str
    text: str
    ts: str
    approve: str = ""
    reject: str = ""
    payload: str = ""


def seconds(stamp: str) -> float | None:
    """An ISO stamp the store wrote, as epoch seconds — None for "" or one that cannot be read."""
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else None
    except ValueError:
        return None


def past(deadline: str, clock: float) -> bool:
    """Whether a written deadline has passed. A deadline that cannot be read has: a wait nobody
    can age must not hold an answer for ever — the rule `messages.staged` keeps for its own."""
    if not deadline:
        return False
    when = seconds(deadline)
    return when is None or clock > when


def in_conversation(project, conversation: str, person: str = "", *,
                    now: float | None = None) -> list[Wait]:
    """Everything waiting for `person` in `conversation`, as the store says it — [] for nothing.

    Found as a turn finds it: this person's own key first, then the conversation's bare key (what
    was staged for nobody in particular); at each, the proposal and then the held question. A
    proposal older than `staging.PROPOSAL_TTL_SECONDS` waits for nothing (its first read in the
    conversation answers it `expired`), and a question past its written deadline neither.

    RAISES `StoreUnreadable` when the store will not answer (#126): a list that cannot be read is
    not an empty one, and the Pending tab must say which it is. `staging.waiting_in` keeps its own
    contract — no buttons for a store nobody can read — by catching it."""
    from openfactory.memory import messages
    from openfactory.product.staging import PROPOSAL_TTL_SECONDS, key_for

    name = getattr(project, "name", "") or str(project or "")
    conversation = str(conversation or "")
    if not name or not conversation:
        return []
    clock = time.time() if now is None else now
    proposals = {q.token.partition("|")[0]: q for q in messages.pending(name)}
    questions = {m.token: m for m, closed in messages.held(name)
                 if closed is None and m.token.startswith(QUESTION_TOKEN)}
    out: list[Wait] = []
    for key in dict.fromkeys((key_for(conversation, person), conversation)):
        q = proposals.get(key)
        asked_at = seconds(q.ts) if q is not None else None
        # a stamp the store did not write in its own format: its answer decides, as it always has
        if q is not None and (asked_at is None or clock - asked_at <= PROPOSAL_TTL_SECONDS):
            out.append(Wait(kind=PROPOSAL, key=key, token=q.token, text=q.text, ts=q.ts,
                            approve=q.approve, reject=q.reject, payload=q.payload))
        m = questions.get(question_token(key))
        if m is not None and not past(m.expires, clock):
            out.append(Wait(kind=QUESTION, key=key, token=m.token, text=m.text, ts=m.ts,
                            payload=m.payload))
    return out

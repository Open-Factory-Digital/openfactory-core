"""What the tech-lead has SEEN, TRIED, and whether it WORKED — the thing it did not have.

Until this existed, the tech-lead's entire memory was one number: how many distinct tickets had
failed each way lately. It could say "three tickets failed the same way" and nothing else. It could
not answer the three questions that separate a colleague from a status report:

    have I seen this before?      it could count, but not recognise
    what did I try?               `_remedied` lived in the workflow's memory and DIED with the job,
                                  so every ticket restarted the retry budget from zero
    did it work?                  nothing recorded an outcome at all

The third is the one that costs money. A remedy that has never worked here is indistinguishable
from one that always works, so the factory could retry the same useless thing on every ticket, for
ever, at a full agent pass each time — and each retry looked like diligence.

THE MEMORY IS EPISODIC, NOT A MODEL. One row per intervention: what it saw, what it did, what
happened next. Everything read back out is arithmetic over those rows, which is what makes "I have
tried this four times and it has never worked" a checkable claim rather than an impression.

OUTCOMES ARE OBSERVED, NEVER ASSUMED. An attempt is written down as `pending` and resolved by the
NEXT round looking at the world: the ticket is no longer parked on that signature → it worked; it is
still parked the same way → it did not. Nothing self-reports success, because a remedy that reports
its own outcome is the thing this module exists to stop believing.

AND `unknown` STILL NEVER DEGRADES TOWARD ACTION. History can only make the factory MORE cautious —
it removes remedies that have failed, it never invents one that classification did not offer. The
asymmetry is the same as everywhere else in this system: `observed` is not `accepted`, `learned` is
not `confirmed`, and "it worked once" is not "it works".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Outcomes an attempt can have. `PENDING` is not a failure state — it is an honest "we have not
#: looked yet", and treating it as either success or failure is how a memory starts lying.
PENDING, WORKED, DID_NOT_WORK = "pending", "worked", "did-not-work"

#: How many times a remedy may fail on the SAME signature before it stops being offered. Two,
#: because the first failure can be coincidence and the third is money already spent twice.
GIVE_UP_AFTER = 2

#: Beyond this, an old episode says more about a system that no longer exists than about now.
#: Deliberately generous: the failures worth learning about are the ones that recur over weeks.
REMEMBER_LAST = 200

#: Things that are unique per occurrence and would make every failure look brand new. Stripped so
#: that the SAME problem on three tickets collapses to one signature — which is the entire point.
_NOISE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://\S+"), " <url> "),
    (re.compile(r"\b[0-9a-f]{7,40}\b", re.I), " <sha> "),
    (re.compile(r"#\d+"), " <ticket> "),
    # `re.I` matters: the text is lowercased before these run, so an uppercase-only `T`
    # here silently never matched and every timestamp split into loose numbers instead.
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[t ][\d:.+-]+", re.I), " <time> "),
    (re.compile(r"\b\d+\b"), " <n> "),
    (re.compile(r"[\"'`]"), " "),
    (re.compile(r"\s+"), " "),
)

#: How much of the note identifies the problem. Enough to distinguish two failures, short enough
#: that a stack trace's tail does not make every occurrence unique.
_SIGNATURE_CHARS = 120


def signature(note: str) -> str:
    """A fingerprint for "this same failure, wherever it happened".

    "GraphQL: API rate limit exceeded for installation ID 146152259" on #478 and the same message on
    #503 must land on ONE signature, or a recurring problem is remembered as unrelated one-offs and
    nothing is ever learned."""
    text = (note or "").strip().lower()
    for pattern, replacement in _NOISE:
        text = pattern.sub(replacement, text)
    return text.strip()[:_SIGNATURE_CHARS]


@dataclass(frozen=True)
class Episode:
    """One intervention: what it saw, what it did about it, and what happened next."""

    #: The provider's own ref (#69). It was `int`, filled by `int(subject) if subject.isdigit()
    #: else 0` — so on a Jira deployment EVERY episode collapsed to ticket 0, `History.tickets`
    #: was `{0}` no matter how many tickets had failed, and `seen` reported 1 for ever. That
    #: number is not internal: `phrase()` puts it in front of a human as "já vi isso em 1 ticket".
    ticket: str
    cause: str
    sig: str
    #: the remedy attempted — "retry", "rotate", "escalate", "product"
    remedy: str
    outcome: str = PENDING
    ts: str = ""


@dataclass
class History:
    """What the record says about one signature."""

    sig: str = ""
    tickets: set[str] = field(default_factory=set)
    attempts: int = 0
    worked: int = 0
    failed: int = 0
    pending: int = 0

    @property
    def seen(self) -> int:
        return len(self.tickets)

    def hopeless(self, remedy: str = "retry") -> bool:
        """Whether this remedy has earned the right to be tried again.

        Only counts RESOLVED attempts: a pile of `pending` proves nothing except that nobody has
        looked, and treating it as failure would give up on something that may be working."""
        return remedy == "retry" and self.failed >= GIVE_UP_AFTER and self.worked == 0

    def phrase(self) -> str:
        """One sentence a person can act on, in the client's terms. This is the whole value of
        having a memory: "não consegui" is a shrug, "já vi isso 4 vezes e retomar nunca resolveu"
        tells somebody where to look."""
        if not self.attempts:
            return ""
        where = f"em {self.seen} ticket{'s' if self.seen != 1 else ''}"
        if self.worked and not self.failed:
            return f"já vi isso {where} e retomar resolveu todas as vezes"
        if self.failed and not self.worked:
            return (f"já vi isso {where} e retomar não resolveu nenhuma das "
                    f"{self.failed} vezes que tentei")
        if self.worked and self.failed:
            return (f"já vi isso {where}: retomar resolveu {self.worked} "
                    f"e não resolveu {self.failed}")
        return f"já vi isso {where}, mas ainda não sei se o que fiz resolveu"


def collapse(episodes: list[Episode]) -> list[Episode]:
    """One row per ATTEMPT, with its latest known outcome.

    The store is append-only, so resolving an attempt writes a second row rather than editing the
    first — history that can be edited on a later pass is not history, it is an opinion with a
    timestamp. `(ticket, sig, ts)` identifies the attempt; a resolved row supersedes its `pending`.
    Order is preserved so `REMEMBER_LAST` still means the most recent attempts."""
    latest: dict[tuple[int, str, str], Episode] = {}
    order: list[tuple[int, str, str]] = []
    for ep in episodes:
        key = (ep.ticket, ep.sig, ep.ts)
        if key not in latest:
            order.append(key)
        elif latest[key].outcome != PENDING and ep.outcome == PENDING:
            continue  # a late `pending` must never un-resolve a settled attempt
        latest[key] = ep
    return [latest[k] for k in order]


def learn(episodes: list[Episode]) -> dict[str, History]:
    """Fold the record into what it means, per signature. Pure — the claim "this never works" is
    arithmetic somebody can recount, not something a model concluded."""
    out: dict[str, History] = {}
    for ep in collapse(episodes)[-REMEMBER_LAST:]:
        h = out.setdefault(ep.sig, History(sig=ep.sig))
        h.tickets.add(ep.ticket)
        h.attempts += 1
        if ep.outcome == WORKED:
            h.worked += 1
        elif ep.outcome == DID_NOT_WORK:
            h.failed += 1
        else:
            h.pending += 1
    return out


def temper(remedy, history: History | None):
    """The remedy, corrected by what actually happened when it was tried before.

    ONE DIRECTION ONLY. History can withdraw a remedy that has failed; it can never propose one
    classification did not offer, and it never shortens a wait. A memory that could talk the factory
    INTO acting would be a way for a bad week to become a policy."""
    if history is None or remedy.action != "retry" or not history.hopeless():
        return remedy

    from dataclasses import replace

    return replace(
        remedy,
        action="escalate",
        wait_seconds=0,
        attempts_left=0,
        reason=f"retomar já falhou {history.failed}x nesta mesma falha e nunca resolveu",
        say=(f"Não vou tentar de novo: {history.phrase()}. "
             f"Isso precisa de alguém olhando a causa, não de mais uma tentativa."),
        notes=[*remedy.notes, f"history: {history.attempts} tentativas, "
                              f"{history.worked} resolveram, {history.failed} não"],
    )


def learn_from(loops) -> dict[str, History]:
    """What the LEDGER says, per failure signature (ADR-0021 §1).

    The ledger is the durable form; `Episode` is the shape this module reasons in. Converting here
    rather than storing episodes directly keeps one store for every agent's loops — a second store
    is a second thing to provision, and the failure mode of forgetting to is an agent that silently
    stops remembering."""
    from openfactory.memory.ledger import CLOSED, REMEDY, fold

    episodes = [
        Episode(
            # The ledger already stores `subject` as a str (`memory/ledger.py`), so this is a
            # read of what was written rather than a conversion — it was `int(...) if isdigit()
            # else 0` and the `else 0` silently merged every non-numeric ticket into one.
            ticket=str(loop.subject),
            cause=loop.context.get("cause", ""),
            sig=loop.about,
            remedy=REMEDY,
            outcome=loop.outcome if loop.state == CLOSED and loop.outcome else PENDING,
            ts=loop.ts,
        )
        for loop in fold(list(loops))
        if loop.kind == REMEDY
    ]
    return learn(episodes)


def remedy_verdicts(open_remedies, *, parked_now: dict[str, tuple[str, str]],
                    observed: set[str], terminal: dict[str, str]) -> dict:
    """What this round may CONCLUDE about each open remedy — the positive-evidence truth table.

    Pure, and extracted from the activity precisely because the first version lived inline where
    no test could reach it — which is how both of its critical bugs (closing on absence; crediting
    an in-flight job as cured) shipped. The activity gathers `parked_now` (ticket → (signature,
    cause), for jobs it POSITIVELY saw parked), `observed` (tickets whose state it positively saw,
    parked or answering), and `terminal` (prefetched end-states for tickets gone from the floor);
    this decides, and a test can hold every row of the table.

        parked, same signature           → did-not-work
        parked, same cause, new wording  → no verdict (same disease, different rash — a string
                                           drift must be neither credit nor blame)
        parked, different cause          → worked (that failure, at least, is gone)
        gone from the floor              → whatever the workflow's terminal state says, if known
        running, unqueryable, unknown    → no verdict; absence is never an outcome
    """
    from openfactory.memory.ledger import REMEDY

    verdicts: dict = {}
    for loop in open_remedies:
        # THE SUBJECT IS THE TICKET, verbatim (#69). This was `int(subject) if subject.isdigit()
        # else 0`, and 0 can never appear in `parked_now`, `observed` or `terminal` — so on a
        # non-numeric-ref deployment every open remedy fell through all three branches and stayed
        # PENDING for ever. `hopeless()` counts only RESOLVED attempts, so it could never fire:
        # the factory would retry a useless remedy at full price, indefinitely, each attempt
        # looking like diligence.
        ticket = str(loop.subject)
        key = (REMEDY, ticket, loop.about)
        if ticket in parked_now:
            sig_now, cause_now = parked_now[ticket]
            if sig_now == loop.about:
                verdicts[key] = DID_NOT_WORK
            elif cause_now != (loop.context or {}).get("cause", ""):
                verdicts[key] = WORKED
        elif ticket not in observed:
            outcome = terminal.get(ticket, "")
            if outcome:
                verdicts[key] = outcome
    return verdicts


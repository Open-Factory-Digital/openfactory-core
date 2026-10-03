"""A conversation that went quiet, distilled into the context repository — the catch-all for what
no confirmation captured (#269 slice 3, ADR-0053 D4, D6, D10, D14).

SAVED WHEN CONFIRMED IS THE RULE; THIS IS WHAT IT MISSES. A requirement, a decision, a card or a
fact is written the moment a person confirms it (ADR-0051 D10): conversations run side by side,
and the saved record is the only way one learns what another decided. But a conversation also
holds what nobody confirmed — an option refused, a preference, a request that never became a
draft, a question left open — and its raw lines are deleted at the client's retention (ADR-0053
D6). What it came to is written here, once, when it goes quiet: permanent, versioned, cited with
its date as EVIDENCE, and never a requirement, a decision or a fact of the product — only a
person's confirmation makes those (D14).

WHAT "QUIET" IS, AND ITS BOUNDS. A conversation's workflow is long-lived, so nothing "ends" it.
A SPAN is the lines a conversation holds after its last distillate; it is distilled when its newest
line is `QUIET_HOURS` old — a working session is over — and it holds at least a person's line and
the role's. It is bounded: at most `MAX_LINES` lines and `MAX_CHARS` characters, the oldest first,
and what is past the bound is the next span, distilled on a later pass. A pass distils at most
`PER_PASS` conversations and stops at its time budget. And it cannot reach past the retention:
lines the transcript deleted are no longer there to distil.

ONCE PER SPAN, WHOEVER RUNS IT. The repository is the record of what was distilled: each
distillate says, in its front matter, the span it covers (`after`, `since`, `until`), and a span
starts after the latest `until` its conversation's folder holds. The write re-reads that folder in
a fresh clone UNDER THE PRODUCT'S SEMAPHORE (`authoring.record_distillate`): a distillate written
since, by another pass, another process or another registry project of the product, means nothing
is written. So a span is never distilled twice, and the model's reading — which runs BEFORE the
lock, never under it — is the only thing a race can waste.

WHO IS IN IT: NOBODY, BY NAME (the choice ADR-0053 left to this slice). A distillate is permanent
and the raw conversation is deletable (D6); a distillate that named or quoted people would keep, for
ever, the personal data the retention exists to delete — and it is read by every conversation of
the product, across which no name may pass (ADR-0051 D5, D9). So it keeps WHAT, never WHO:

  - the model is handed each line with its speaker's ROLE in the product — a client, a product
    admin, an engineer, the role — and never an id or a name;
  - it is asked to paraphrase, never to quote, and to name nobody;
  - and what it writes is scrubbed before it is written, deterministically: every person the
    product knows (its admins and engineers, the registry's people, every speaker of every
    conversation of the product), every private conversation's key, every e-mail address and every
    mention is withheld (`model.Names`, `model.finish`: the facts pack's own withholdings).

A room's distillate (`conversations/room/<digest>/…`) is the room's reading, the client's: in a
room everybody reads the reply (ADR-0052 D10). A DIRECT one (`conversations/direct/<digest>/…`)
is labelled for its one person's audience and comes back ONLY TO ITS OWN CONVERSATION — in the
index's searches and in a turn's view alike (`documents/record.py::withheld`) — as that
conversation's raw lines do (D10). It names only what its own people saw: the model is handed the
conversation's own addressed lines and nothing else, and a line said in a group to somebody else is
never handed over (D12).

The model is the documents' reader (`adapters/extract/model.py`: the reviewer's harness, or the
role `OPENFACTORY_DOCUMENTS_ROLE` names), in a room holding the conversation and nothing else.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, Field

from openfactory.contracts.document import CLIENT
from openfactory.memory.transcript import ANSWER
from openfactory.product.documents.record import (
    DIRECT,
    DISTILLATES,
    MARKED,
    ROOM,
    distillate_path,
    span_marker_path,
)

log = logging.getLogger("openfactory.product.distil")

#: How long a conversation must have been silent before what it came to is written down. A working
#: session over, not a pause for coffee: a person who answers the role's question the next morning
#: starts a new span, and the two are read together by whoever searches.
QUIET_HOURS = 6
#: A span worth a reading: at least this many lines a model is handed — a person's and the role's
#: ANSWER among them. The platform's own sentences (a crash reply, an unavailable, a hand-off) do
#: not count toward it and are handed to no model (#457, `_is_platform`).
MIN_LINES = 2
#: The most one span holds — the oldest first; the rest is the next span.
MAX_LINES = 200
MAX_CHARS = 40_000
#: How many conversations one pass distils — each is a model call.
PER_PASS = 3
#: The phase the model is asked under.
PHASE = "product_distil"
#: How many items a section keeps, and how long each may be.
MAX_ITEMS = 12
ITEM_CHARS = 400

#: How a speaker is handed to the model, by their role in the product (`speaker.py`) — never by id.
SAID_AS = {"client": "a client", "admin": "a product admin", "engineer": "an engineer"}
THE_ROLE = "the role"

#: The sections of a distillate, in order, and the field each is read from.
SECTIONS = (("agreed", "Agreed"), ("asked", "Asked for"), ("decided", "Decided"),
            ("refused", "Refused or dropped"), ("open", "Left open"))

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
#: A mention, as a chat vendor spells one or as people type one — READ to be withheld, never built
#: (the `@` in a class of its own keeps the core's no-vendor-mention guard reading what it means)
_MENTION = re.compile(r"<[@][^>\s]+>|(?<![\w@])@[A-Za-z][\w.-]{1,}")


# ── what is handed to the model ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Line:
    """One line of a span, as the model reads it: when, and who by their role — never by name."""

    ts: str
    who: str
    text: str


@dataclass(frozen=True)
class Span:
    """The lines of one conversation after its last distillate. `conversation` is its key, which
    is never written anywhere — only its digest is."""

    conversation: str
    digest: str
    private: bool
    audience: str
    after: str
    since: str
    until: str
    #: the lines, each by its speaker's role, with every person the product knows withheld
    lines: tuple[Line, ...] = ()
    #: everybody the product knows (`known_people`) — withheld from what is written, so no name
    #: crosses from one conversation into another's distillate either
    people: frozenset[str] = field(default_factory=frozenset)


class Distilled(BaseModel):
    """What the model read a span as — or, with `error`, why it could not."""

    agreed: list[str] = Field(default_factory=list)
    asked: list[str] = Field(default_factory=list)
    decided: list[str] = Field(default_factory=list)
    refused: list[str] = Field(default_factory=list)
    open: list[str] = Field(default_factory=list)
    #: THE MODEL'S EXPLICIT WAY TO SAY THERE IS NOTHING TO KEEP (#457): no agreement, request or
    #: decision the record does not already hold. `True` makes the span a span read and kept, never
    #: a distillate — the same outcome as an all-empty reading, said outright rather than inferred.
    nothing: bool = False
    #: `harness/model` of what wrote it
    by: str = ""
    error: str = ""

    def kept_something(self) -> bool:
        """Whether this reading is worth a distillate: it keeps something AND did not say there is
        nothing (#457). An all-empty reading keeps nothing; `nothing` says so outright."""
        return not self.nothing and any(getattr(self, name) for name, _title in SECTIONS)


@runtime_checkable
class Distiller(Protocol):
    def distil(self, span: Span) -> Distilled:
        ...


# ── which conversations are ready ───────────────────────────────────────────────────────────────

def distilled_in(root: Path) -> dict[str, str]:
    """`{conversation digest: latest until}` — what the context repository at `root` says was READ
    already, so a span after it is not read again. The position comes from BOTH what was written as
    a distillate (`conversations/…`) AND what marks a span that kept nothing (`.distilled/…`, the
    hidden tree): a deployment upgraded onto this reads its existing distillates through, and a span
    marked empty since is just as read (#457)."""
    from openfactory.product.authoring import distilled_until

    out: dict[str, str] = {}
    for top in (DISTILLATES, MARKED):
        for kind in (ROOM, DIRECT):
            base = Path(root) / top / kind
            if not base.is_dir():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir()):
                until = distilled_until(folder)
                if until:
                    out[folder.name] = max(out.get(folder.name, ""), until)
    return out


def _when(ts: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _who(project, line) -> str:
    from openfactory.product.speaker import person

    if str(getattr(line, "role", "") or "") == "agent":
        return THE_ROLE
    return SAID_AS.get(person(project, str(getattr(line, "actor", "") or "")).role, "a client")


def _audience(project, conversation: str) -> str:
    """Whom a conversation's distillate may be shown: a room is the client's reading, whoever
    spoke in it; a private conversation is its one person's (`record.turn_audience`)."""
    from openfactory.product.conversation import is_private, person_of
    from openfactory.product.documents.record import turn_audience
    from openfactory.product.speaker import person

    if not is_private(conversation):
        return CLIENT
    # THE OWNER, WHICHEVER OF THEIR SESSIONS (#335): `person:ana~k3f9a2` is Ana's
    who = person_of(conversation)
    return turn_audience(person(project, who), private=True) if who else CLIENT


def spans(project, said, *, distilled: dict[str, str], now: datetime | None = None,
          quiet_hours: float = QUIET_HOURS) -> list[Span]:
    """The spans ready to be distilled, the longest-quiet first: each conversation's addressed
    lines after its last distillate, when its newest line is `quiet_hours` old — bounded."""
    from openfactory.memory.recall import CONVERSATION
    from openfactory.product.conversation import is_private
    from openfactory.product.index.items import conversation_digest

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=quiet_hours)
    lines = [s for s in said or ()
             if getattr(s, "store", CONVERSATION) == CONVERSATION and str(s.text or "").strip()]
    people = frozenset(known_people(project, lines))
    by_where: dict[str, list] = {}
    for line in lines:
        by_where.setdefault(str(line.where or ""), []).append(line)
    ready: list[Span] = []
    for where, held in sorted(by_where.items()):
        if not where:
            continue
        digest = conversation_digest(where)
        after = distilled.get(digest, "")
        fresh = sorted((s for s in held if str(s.ts) > after), key=lambda s: str(s.ts))
        newest = _when(fresh[-1].ts) if fresh else None
        if newest is None or newest > cutoff:
            continue  # nothing new, or still talking
        taken: list = []
        size = 0
        for s in fresh:
            if len(taken) >= MAX_LINES or size + len(s.text) > MAX_CHARS:
                break
            taken.append(s)
            size += len(s.text)
        # NEVER A LINE SAID IN A GROUP TO SOMEBODY ELSE (ADR-0053 D12): what was agreed with the
        # role is what was said to it
        addressed = [s for s in taken if s.addressed]
        if len(addressed) < MIN_LINES or not any(s.role != "agent" for s in addressed):
            continue  # not an exchange at all — a lonely line, as it always was: not a span
        # THE PLATFORM'S OWN SENTENCES ARE NOT THE ROLE'S ANSWER (#457): a crash reply, an
        # unavailable, a busy acknowledgement, a hand-off — none is handed to a model, and none
        # counts toward MIN_LINES. What a model reads is the people's lines and the role's ANSWERS;
        # a span whose only role lines are platform sentences keeps nothing, and is marked read with
        # no model call so it is never read again.
        spoken = [s for s in addressed if not _is_platform(s)]
        worth_a_model = (len(spoken) >= MIN_LINES and any(s.role != "agent" for s in spoken)
                         and any(s.role == "agent" for s in spoken))
        ready.append(Span(
            conversation=where, digest=digest, private=is_private(where),
            audience=_audience(project, where), after=after, since=str(taken[0].ts),
            until=str(taken[-1].ts),
            # THE LINES NAME NOBODY THE PRODUCT KNOWS before any model reads them: what it was
            # never handed it cannot write down (`scrub`, again, on what it answers). Empty when
            # nothing is worth a model — the span is still returned, so `distil` marks it read.
            lines=tuple(Line(ts=str(s.ts), who=_who(project, s),
                             text=scrub(str(s.text).strip(), people)) for s in spoken)
                  if worth_a_model else (),
            people=people))
    ready.sort(key=lambda s: s.until)
    return ready


def _is_platform(line) -> bool:
    """A line the platform said in its OWN voice, not the model's answer (#457): a role line
    recorded with a kind that is not `ANSWER`. Only the role speaks these; a person's line, and
    every line recorded before the kind existed, reads as an answer."""
    return (str(getattr(line, "role", "")) == "agent"
            and str(getattr(line, "kind", ANSWER) or ANSWER) != ANSWER)


# ── the reading ─────────────────────────────────────────────────────────────────────────────────

def prompt(span: Span) -> str:
    return (
        f"The file `conversation.txt` in this directory holds one conversation between the people "
        f"of a product and its product role, from {span.since[:16]} to {span.until[:16]}: "
        f"{len(span.lines)} lines, each saying when it was said and who said it — by their role "
        f"in the product, never by name.\n\n"
        "Read it and answer with ONE JSON object and nothing else.\n\n"
        "When nothing in it is worth keeping — no agreement, no request, no decision beyond what "
        "the role says it already recorded, and no question left open — answer EXACTLY:\n\n"
        '{"nothing": true}\n\n'
        "Otherwise:\n\n"
        '{"agreed": ["…"], "asked": ["…"], "decided": ["…"], "refused": ["…"], "open": ["…"]}\n\n'
        "- `agreed`: what the people and the role agreed on.\n"
        "- `asked`: what somebody asked the product to DO, to HAVE or to CHANGE. A question ABOUT "
        "the product — how something works, what it does, whether it already does a thing — is NOT "
        "something they asked the product for: leave it out, or put it in `open` if it was left "
        "unanswered.\n"
        "- `decided`: what a person decided.\n"
        "- `refused`: what was refused, dropped or decided against.\n"
        "- `open`: the questions left without an answer.\n\n"
        "Each item is ONE self-contained sentence, in the conversation's own language, that still "
        "makes sense a year from now to somebody who never saw it — name the requirements and "
        "cards it is about by their numbers. LEAVE OUT what the role says it recorded — a "
        "requirement written, a card opened, a decision or a fact recorded: that is saved "
        "already. NAME NOBODY: no person's name, handle, e-mail or id — say \"a client\", \"a "
        "product admin\", \"an engineer\" or \"the role\". Say it in your own words, never as a "
        "quotation. Never add anything the conversation does not say. An empty list when there "
        "is nothing.")


def _items(value) -> list[str]:
    out = []
    for item in value if isinstance(value, list) else []:
        text = " ".join(str(item or "").split())
        if text:
            out.append(text[:ITEM_CHARS])
    return out[:MAX_ITEMS]


class ModelDistiller:
    """The default distiller: the documents' reader, read-only, one conversation per room."""

    def __init__(self, *, project=None, harness=None) -> None:
        self.project = project
        self._harness = harness
        self._built = harness is not None
        self._why = ""

    def _asker(self):
        if not self._built:
            from openfactory.adapters.extract import model as seam

            self._harness, self._why = seam.asker(self.project)
            self._built = True
        return self._harness

    def distil(self, span: Span) -> Distilled:
        from openfactory.adapters.agent.base import json_envelope
        from openfactory.adapters.extract import model as seam
        from openfactory.product.semaphore import refuse_a_model_here

        refuse_a_model_here(PHASE)
        harness = self._asker()
        if harness is None:
            return Distilled(error=self._why or "no model can distil conversations here")
        with tempfile.TemporaryDirectory(prefix="openfactory-distil-") as scratch:
            room = Path(scratch)
            (room / "conversation.txt").write_text(
                "\n".join(f"[{line.ts[:16]}] {line.who}: {line.text}" for line in span.lines),
                encoding="utf-8")
            said, why = seam.ask(harness, self.project, room, prompt(span), phase=PHASE)
        by = seam.described(harness, self.project)
        if said is None:
            return Distilled(error=why, by=by)
        answer = json_envelope(said)
        if answer is None:
            return Distilled(error="the model's answer was not the JSON object it was asked for",
                             by=by)
        return Distilled(**{name: _items(answer.get(name)) for name, _title in SECTIONS},
                         nothing=bool(answer.get("nothing")), by=by)


# ── what is written ─────────────────────────────────────────────────────────────────────────────

def _compact(ts: str) -> str:
    return re.sub(r"[^0-9T]", "", str(ts)[:19])


def _name_for(span: Span) -> str:
    """The file name a span lands on — its end and its identity, so the same span always lands on
    the same path, whether it is a distillate or a span-read mark."""
    ident = hashlib.sha256(f"{span.digest}|{span.after}|{span.until}".encode()).hexdigest()[:8]
    return f"{_compact(span.until)}-{ident}.md"


def path_for(span: Span) -> str:
    """Where a span's distillate is written: its conversation's folder under `conversations/`."""
    return distillate_path(private=span.private, digest=span.digest, name=_name_for(span))


def marker_path(span: Span) -> str:
    """Where a span that KEPT NOTHING is marked read — the hidden tree, so ingestion never reads it
    as a document (no record, no index item, no Documents entry), while `distilled_in` reads it to
    advance the cursor (#457). The same span always lands on the same path."""
    return span_marker_path(private=span.private, digest=span.digest, name=_name_for(span))


def known_people(project, said) -> set[str]:
    """Everyone a distillate must not name: the product's people as the registry knows them — its
    admins, its engineers, the deployment's logins and channel ids — the speaker of every line of
    every conversation of the product, and the person every private conversation is keyed by."""
    from openfactory.product.conversation import PRIVATE_PREFIXES

    cfg = getattr(project, "product", None)
    known = {str(x) for x in (getattr(cfg, "admins", None) or ())}
    known |= {str(x) for x in (getattr(cfg, "engineers", None) or ())}
    for login, user in (getattr(project, "people", None) or {}).items():
        known |= {str(x) for x in (login, user) if x}
    for line in said or ():
        known.add(str(getattr(line, "actor", "") or ""))
        where = str(getattr(line, "where", "") or "")
        for prefix in PRIVATE_PREFIXES:
            if where.startswith(prefix):
                known.add(where[len(prefix):])
    return {k for k in known if k.strip()}


def scrub(text: str, people) -> str:
    """`text` with nobody in it: known people, private keys, e-mail addresses and mentions
    withheld — plus the spend and the credentials the facts pack withholds (`model.finish`).

    A NAME IS WITHHELD IN ANY CASE, and by the part of an address before its `@`: a model writes
    "Helena" for the speaker the registry knows as `helena` or `helena@tidewater.example`, and the
    facts pack's own withholding (`model.Names`) matches the id as it is spelled."""
    from openfactory.product.model import SOMEONE, Names, finish

    text = _MENTION.sub(SOMEONE, _EMAIL.sub("[an address]", str(text or "")))
    text = finish(text, Names(people))
    spelled = set()
    for who in people or ():
        who = str(who or "").strip().strip("<@>")
        for part in (who, who.split("@", 1)[0], who.rsplit(":", 1)[-1]):
            if len(part) >= 3 and re.search(r"[A-Za-z]", part):
                spelled.add(part)
    if spelled:
        names = "|".join(re.escape(w) for w in sorted(spelled, key=len, reverse=True))
        text = re.sub(rf"(?<![\w.-])(?:{names})(?![\w-])", SOMEONE, text, flags=re.IGNORECASE)
    return text


def render(span: Span, reading: Distilled, *, people) -> str:
    """The distillate as the file it is: front matter that says what it covers and who may read
    it, the reading's sections, and what it is — a reading, never a decision."""
    first, last = span.since[:10], span.until[:10]
    title = (f"A conversation, distilled — {first}" if first == last
             else f"A conversation, distilled — {first} to {last}")
    front = {"title": title, "date": last, "audience": span.audience,
             "kind": "conversation-distillate", "conversation": span.digest,
             "private": span.private, "after": span.after, "since": span.since,
             "until": span.until, "lines": len(span.lines),
             "distilled_by": reading.by or "unknown"}
    body = [f"# {title}", "",
            "A model's reading of one conversation of this product, written after it went quiet. "
            "It is evidence of what was said — cite it with its date — and never a requirement, a "
            "decision or a fact of the product: only a person's confirmation makes those. It "
            "names nobody.", ""]
    said = False
    for name, heading in SECTIONS:
        items = [scrub(item, people) for item in getattr(reading, name)]
        if items:
            said = True
            body += [f"## {heading}", "", *(f"- {item}" for item in items), ""]
    if not said:
        body += ["Nothing was agreed, asked or decided in it that is not recorded elsewhere.", ""]
    return ("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n\n"
            + "\n".join(body).rstrip() + "\n")


def render_marker(span: Span) -> str:
    """The mark a span that kept nothing leaves — the front matter `distilled_in` reads to advance
    the cursor (its `until`), and a line saying why there is no distillate (#457). It names nobody
    and holds none of the conversation: it is the record that the span was read, not its reading.
    Hidden on disk (`marker_path`), so ingestion never reads it as a document."""
    front = {"kind": "conversation-span-read", "conversation": span.digest,
             "private": span.private, "after": span.after, "since": span.since,
             "until": span.until, "lines": len(span.lines)}
    body = ("A span of this conversation that went quiet and kept nothing a distillate would hold "
            "— no agreement, request or decision the product's record does not already have, and "
            "no question left open. Marked read so it is never distilled again. It is not a "
            "document and nobody reads it; it holds none of what was said.")
    return ("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n\n"
            + body + "\n")


# ── the pass ────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Report:
    """What one pass did — the activity's line."""

    written: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    #: spans read that kept nothing — marked read, no distillate (#457); and those a race marked
    #: already
    marked: list[str] = field(default_factory=list)
    marked_already: list[str] = field(default_factory=list)
    left: int = 0

    def sentence(self) -> str:
        said = [f"{len(self.written)} conversation(s) distilled"]
        if self.already:
            said.append(f"{len(self.already)} distilled already by another pass")
        if self.marked:
            said.append(f"{len(self.marked)} read that kept nothing")
        if self.marked_already:
            said.append(f"{len(self.marked_already)} read by another pass")
        if self.unread:
            said.append(f"{len(self.unread)} the model could not read (the reason is in the "
                        f"platform's log)")
        if self.failed:
            said.append(f"{len(self.failed)} not written (the reason is in the platform's log)")
        if self.left:
            said.append(f"{self.left} left for the next pass")
        return ", ".join(said)


def distil(project, *, module, root: Path, said, distiller: Distiller | None = None,
           now: datetime | None = None, limit: int = PER_PASS,
           budget_seconds: float | None = None,
           clock: Callable[[], float] = time.monotonic) -> Report:
    """Distil the product's quiet conversations: read which spans are ready against the context
    repository checked out at `root`, have the model read each — OUTSIDE the semaphore — and write
    each through the product's semaphore (`module.record_distillate`), once.

    `said` is the product's conversation lines (`index/retrieval.py::said_of`). Never raises for a
    conversation: one that could not be read or written is counted, and the next pass reads it
    again."""
    from openfactory.product import semaphore

    if semaphore.held_here(project):
        raise semaphore.ModelUnderSemaphore("a conversation is distilled by a model, and a model "
                                            "is never asked under the product's semaphore")
    report = Report()
    ready = spans(project, said, distilled=distilled_in(root), now=now)
    distiller = distiller or ModelDistiller(project=project)
    deadline = None if budget_seconds is None else clock() + budget_seconds
    for n, span in enumerate(ready):
        if n >= limit or (deadline is not None and clock() > deadline):
            report.left = len(ready) - n
            break
        # A SPAN WITH NOTHING FOR A MODEL — its only role lines were the platform's own — is read
        # without a model call (#457): there is nothing to hand one.
        reading: Distilled | None = None
        if span.lines:
            try:
                reading = distiller.distil(span)
            except Exception as exc:  # noqa: BLE001 — a reading that raised is one that failed
                reading = Distilled(error=f"{type(exc).__name__}: {str(exc)[:200]}")
            if reading.error:
                log.warning("OPENFACTORY_PRODUCT_DISTIL_UNREAD project=%s span=%s (%s)",
                            getattr(project, "name", "?"), path_for(span), reading.error)
                report.unread.append(path_for(span))
                continue
        # KEPT SOMETHING → a distillate; kept nothing (no line for a model, an all-empty reading, or
        # the model's nothing-to-keep answer) → the span is MARKED read, no document. Either way the
        # cursor advances, through the SAME semaphore, once per span.
        if reading is not None and reading.kept_something():
            kept, path, text = True, path_for(span), render(span, reading, people=span.people)
        else:
            kept, path, text = False, marker_path(span), render_marker(span)
        written = module.record_distillate(path=path, text=text, after=span.after)
        if not written.ok:
            report.failed.append(path)
        elif kept and written.existed:
            report.already.append(path)
        elif kept:
            report.written.append(path)
        elif written.existed:
            report.marked_already.append(path)
        else:
            report.marked.append(path)
    log.info("OPENFACTORY_PRODUCT_DISTIL project=%s %s", getattr(project, "name", "?"),
             report.sentence())
    return report


__all__ = [
    "MAX_CHARS", "MAX_LINES", "MIN_LINES", "PER_PASS", "QUIET_HOURS", "Distilled", "Distiller",
    "Line", "ModelDistiller", "Report", "Span", "distil", "distilled_in", "known_people",
    "marker_path", "path_for", "prompt", "render", "render_marker", "scrub", "spans",
]

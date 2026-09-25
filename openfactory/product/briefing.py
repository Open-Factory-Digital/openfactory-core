"""The briefing: what the product's owner carries in their head in the morning, in every answer's
prompt, with its source and its age on every line (#267 slice 2, ADR-0052 D5, D8–D10).

A FACT THE ROLE HAS TO GO AND OPEN IS A FACT IT OPENS ON SOME TURNS AND NOT ON OTHERS. Slice 1
gave the role the product as the panel shows it — as files (`now.md`, `history.md`, a file per
card), which is right for the detail and costs an exploration for the gist: "what is moving?",
"why is #42 stuck?", "is 1.4 out?" each meant opening a file, and the prompt carried a budgeted
board instead (`role.py::_board_section`) that answered none of them. The few facts an owner
answers almost anything from cost one short block here, and the detail stays files (D6).

WHAT IT SAYS, in the order a line is admitted under the bound:

    not read       every gap the model names — unreadable is never absence (ADR-0041)
    documents      the context repository's documents that could not be read (#269) — named
                   only when the turn may read them, counted otherwise
    moving         the cards the factory is building, one line
    in production  each member's newest release tag, one line
    parked         a job stopped on a person, with whether the tech-lead has diagnosed it
    waiting        a job at a gate a person holds, and every open loop that waits on a person
    preview        ADR-0050's previews, once the model carries them (a hook: not on this base)
    delivered      what was merged in the last `DELIVERED_DAYS`, one line

EVERY LINE ENDS WITH ITS SOURCE AND ITS AGE — `(ledger — asked 2 days ago)`. The age is the fact's
own time where the platform recorded one (a loop asked, a job parked, a job ended) and the
reading's otherwise (`read just now`). It is what lets the role say "as of two days ago" instead
of asserting a present it did not see, and it stays honest once slice 3's events keep the model:
a reading an hour old will say so.

BOUNDED, AND THE CUT IS SAID. At most `MAX_LINES` lines and `MAX_CHARS` characters, each line's
text cut at `LINE_CHARS` with its source and age kept whole. What does not fit is dropped from the
bottom of the order above and COUNTED, by kind, on the last line — never a silence. The files hold
every line the bound dropped, and their README names every gap.

THE SAME THREE WITHHOLDINGS AS THE FILES (`_withheld`, in `model.finish`'s order): nobody is named
but the person the turn answers, as "you" — everyone else by relation, "its requester", "the
person it was asked of" (ADR-0052 D9); no spend; no credential. EVERY PIECE OF FREE TEXT is
withheld where it enters a line and BEFORE it is folded onto one line or cut: the factory's
sentence about spend is anchored to a line of its own, and a cut through a token or a person's id
leaves a half that no longer looks like one.

ONE KNOWLEDGE, TWO RENDERINGS OF A DIAGNOSIS (D10). `raw` — an engineer, in a private
conversation, and nobody else (`raw_for`) — quotes the tech-lead's diagnosis as it wrote it, the
engine's own reason and the question a parked job asks. Every other conversation gets what the
job waits on and whether it was diagnosed, and the role opens the card to say what the diagnosis
means for the product: in a room everyone reads the reply, and a client never gets the raw one.
Neither register diagnoses anything (D8): a parked card with no diagnosis is "diagnosis pending".

THE SWITCH (`SWITCH_ENV`). ADR-0052 says the briefing is paid on every turn and is right only if
it replaces the exploration it makes redundant — measured with #266's evaluation battery (#281),
the same questions with and without it. `OPENFACTORY_PRODUCT_BRIEFING=off` is the "without" arm:
no briefing, and the budgeted board section it replaces is back, so that arm is the prompt as it
was before this slice.

PURE TEXT OVER THE MODEL. It reads nothing and never raises for a well-formed model; the module
builds the model once per turn and hands it here (`module._the_briefing`).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from openfactory.product.model import (
    FACTORY_LOOPS,
    WAITS_ON,
    Names,
    ProductModel,
    documents_shown,
    scrub_credentials,
    scrub_spend,
    whom,
)

log = logging.getLogger("openfactory.product")

#: The switch, and its default. Anything but an explicit "off" word leaves it on: the briefing is
#: the role's view of the product, and a typo must not quietly take it away.
SWITCH_ENV = "OPENFACTORY_PRODUCT_BRIEFING"
DEFAULT = "on"
_OFF = frozenset({"off", "0", "false", "no"})

#: The bound. Twelve lines of about one sentence each is what a person reads in the morning; the
#: characters bound it again when the lines are long (a raw diagnosis, a product of many members).
MAX_LINES = 12
MAX_CHARS = 2000
#: One line's text, before its source and age — which are never cut.
LINE_CHARS = 280
#: How many cards the one-line summaries name before they count the rest ("and 4 more").
NAMED = 8
#: How far back "delivered" looks. A week is the owner's "lately"; older deliveries are in
#: `history.md`, and when nothing is this recent the line names the last one instead.
DELIVERED_DAYS = 7
#: How much of a card's title, and of a decision's label, rides on its line.
TITLE_CHARS = 70
LABEL_CHARS = 120

#: Stopped, and waiting on a person to move — the jobs the tech-lead diagnoses.
PARKED = ("on_hold", "needs_refinement")
#: At a gate a person holds: a merge, a release to production.
AT_A_GATE = ("awaiting_your_merge", "awaiting_prod_approval")

#: Where a gap's fact comes from, by the words the model writes it with — the first match wins, so
#: the specific ones come before the words they share a sentence with.
_GAP_SOURCES = (("board", "board"), ("column", "board"), ("floor", "floor"),
                ("engine", "engine"), ("job", "engine"), ("ledger", "ledger"),
                ("release", "release tag"), ("repository", "registry"), ("forge", "forge"),
                ("thread", "tracker"), ("tracker", "tracker"))


def enabled() -> bool:
    """Whether this turn's answer carries the briefing — `SWITCH_ENV`, on unless it says off."""
    return str(os.environ.get(SWITCH_ENV, "") or DEFAULT).strip().lower() not in _OFF


def raw_for(person, *, private: bool) -> bool:
    """Whether the tech-lead's diagnosis is quoted as it wrote it: ONLY to an engineer of the
    product, and only in a conversation that is theirs alone (ADR-0052 D10). In a room everyone
    reads the reply; a client, an admin and a person nobody could name get the translated one."""
    from openfactory.product.speaker import ENGINEER

    return bool(private) and getattr(person, "role", "") == ENGINEER


@dataclass(frozen=True)
class Briefing:
    """The briefing as the prompt carries it: `lines` rendered, withheld and bounded — the line
    that counts what was left out is the last one when there is one — and whether it quotes the
    tech-lead's diagnosis (`raw`)."""

    lines: tuple[str, ...] = ()
    left_out: int = 0
    raw: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class _Line:
    """One fact before it is said: what kind (for the count of what the bound left out), its text
    — already withheld — where it came from, and the time of the fact with the verb it is said
    with. `when` "" means the fact has no time of its own, and the reading's is said instead."""

    kind: str
    body: str
    source: str
    verb: str = "read"
    when: str = ""


def render(model: ProductModel, *, speaker: str = "", raw: bool = False,
           audience: str = "client", now: datetime | None = None) -> Briefing:
    """The briefing of `model` for the conversation the turn answers. `speaker` is the person it
    answers — the one person it may call "you" — and `raw` whether the diagnosis is quoted
    (`raw_for`). `audience` is which documents it may name (#269,
    `documents/record.py::turn_audience`). `now` is for a caller that pins the clock."""
    now = now or datetime.now(UTC)
    say = _Say(Names(model.people, speaker=speaker))
    facts = [*_not_read(model, say), *_documents(model, say, audience),
             *_moving(model), *_in_production(model, say),
             *_parked(model, say, raw=raw), *_at_a_gate(model, say, raw=raw),
             *_waiting(model, say), *_previews(model, say), *_delivered(model, say, now)]
    said = [(line.kind, _said(line, read=model.read_at, now=now)) for line in facts]
    lines, left_out = _bounded(said)
    return Briefing(lines=tuple(lines), left_out=left_out, raw=raw)


class _Say:
    """Free text as a line may carry it — the one door every title, diagnosis, reason, question,
    label and gap passes through on its way into the briefing."""

    def __init__(self, names: Names) -> None:
        self.names = names

    def __call__(self, text, limit: int = 0) -> str:
        text = _withheld(str(text or ""), self.names)
        text = _flat(text)
        return _cut(text, limit) if limit else text


def _withheld(text: str, names: Names) -> str:
    """The three withholdings, in the order `model.finish` gives them: names first (an id may sit
    inside a URL a credential scrub would shorten), then spend, then credentials."""
    text = names.redact(text)
    text = scrub_spend(text)
    text = scrub_credentials(text)
    return text


# ── the lines ───────────────────────────────────────────────────────────────────────────────────

def _not_read(model: ProductModel, say: _Say) -> Iterator[_Line]:
    """Every gap, as the model wrote it: what could not be read, and what not to conclude."""
    for gap in model.gaps:
        lower = gap.lower()
        source = next((said for word, said in _GAP_SOURCES if word in lower), "the read model")
        yield _Line("not read", say(gap), source, "tried")


def _documents(model: ProductModel, say: _Say, audience: str) -> Iterator[_Line]:
    """The context repository's documents that could not be read (#269): the ones this turn may
    be shown, BY NAME, and how many more it is not — an internal document's name is content, and
    it is named only to the product's own people in private (`model.documents_shown`)."""
    documents = model.documents
    if not documents or not documents.get("checked_at"):
        return
    listed, withheld = documents_shown(documents, audience)
    if not listed and not withheld:
        return
    named = ", ".join(say(doc.get("path"), TITLE_CHARS) for doc in listed[:NAMED])
    more = f" and {len(listed) - NAMED} more" if len(listed) > NAMED else ""
    body = (f"{len(listed)} document(s) in the context repository could not be read: "
            f"{named}{more}" if listed else "")
    if withheld:
        body += ("; and " if body else "") + (f"{withheld} internal document(s) that could not "
                                               f"be read, not named here")
    yield _Line("documents", body + " — documents.md says why", "document records", "read",
                str(documents.get("checked_at") or ""))


def _moving(model: ProductModel) -> Iterator[_Line]:
    """The cards the factory is building, as one line — a stalled one marked, a paused one too.
    Nothing is said when no member's jobs could be read: the gap says that, and "no card is
    moving" over a failed read is the claim a gap exists to prevent."""
    refs: list[str] = []
    read = unread = 0
    for member in model.members:
        jobs = (model.now.get(member) or {}).get("jobs")
        if jobs is None:
            unread += 1
            continue
        read += 1
        for job in jobs:
            state = _state(job)
            if state in PARKED or state in AT_A_GATE:
                continue
            marks = []
            if state == "paused":
                marks.append("paused — it resumes by itself")
            if job.get("wedged"):
                marks.append("stalled — nothing left can advance it")
            refs.append(_ref(model, member, job.get("issue"))
                        + (f" ({'; '.join(marks)})" if marks else ""))
    if not read:
        return
    if not refs:
        body = "No card is moving"
    else:
        many = len(refs) != 1
        body = (f"{len(refs)} card{'s' if many else ''} {'are' if many else 'is'} moving: "
                + _named(refs))
    if unread:
        body += " — of the members whose jobs could be read"
    yield _Line("moving", body, "engine")


def _in_production(model: ProductModel, say: _Say) -> Iterator[_Line]:
    """The version in production — each member's newest release tag, what the production approval
    calls the current version. The port answers the tag and not its date, so the age is the
    reading's."""
    parts = []
    for member in model.members:
        release = (model.history.get(member) or {}).get("release")
        tag = ("unknown (it could not be read)" if release is None
               else say(release.get("latest_tag")) or "no release tag yet")
        parts.append(f"{member} {tag}" if len(model.members) > 1 else tag)
    if parts:
        yield _Line("in production", "In production (the newest release tag): "
                    + " · ".join(parts), "release tag")


def _parked(model: ProductModel, say: _Say, *, raw: bool) -> Iterator[_Line]:
    """A job stopped on a person. What it waits on is said to everyone; the tech-lead's diagnosis
    is quoted only in the raw register, and said to exist — or to be pending — in the other."""
    for member, job in _live(model):
        state = _state(job)
        if state not in PARKED:
            continue
        diagnosis = say(job.get("diagnosis"))
        if raw:
            # THE STATE BY ITS NAME, and the room it saves goes to the diagnosis: an engineer
            # reads `on_hold`, and the diagnosis is what the line is cut to fit.
            said = [f"the tech-lead's diagnosis on its card: {diagnosis or 'pending'}"]
            question = say(((_action(job) or {}).get("decision") or {}).get("question"))
            if question:
                said.append(f"it asks: {question}")
            why = say((job.get("detail") or {}).get("why"))
            if why and why not in diagnosis:
                said.append(f"the engine's reason: {why}")
            body = f"{_card(model, member, job, say)} is parked ({state}) — " + "; ".join(said)
        else:
            body = (f"{_card(model, member, job, say)} is parked: it waits on {WAITS_ON[state]}; "
                    + ("the tech-lead's diagnosis is on its card" if diagnosis
                       else "diagnosis pending"))
        parked_at = str((_action(job) or {}).get("parked_at") or "")
        verb, when = ("parked", parked_at) if parked_at else _started(job)
        yield _Line("parked", body, "engine", verb, when)


def _at_a_gate(model: ProductModel, say: _Say, *, raw: bool) -> Iterator[_Line]:
    """A job at a gate a person holds. The engine's own reason — a review's verdict, a gate's
    finding — is the raw register's alone."""
    for member, job in _live(model):
        state = _state(job)
        if state not in AT_A_GATE:
            continue
        body = f"{_card(model, member, job, say)} waits on {WAITS_ON[state]}"
        why = say((job.get("detail") or {}).get("why"))
        if raw and why:
            body += f" — the engine's reason: {why}"
        yield _Line("waiting", body, "engine", *_started(job))


def _waiting(model: ProductModel, say: _Say) -> Iterator[_Line]:
    """Every open loop that waits on a PERSON, the longest-waiting first — never the factory's own
    (`FACTORY_LOOPS`: those are the tech-lead's, in `now.md`)."""
    rows = []
    for member in model.members:
        for loop in (model.now.get(member) or {}).get("loops") or []:
            if loop.get("kind") not in FACTORY_LOOPS:
                rows.append((str(loop.get("opened") or ""), member, loop))
    for opened, member, loop in sorted(rows, key=lambda row: row[0]):
        body = _loop_said(model, member, loop, whom(loop, say.names), say)
        if loop.get("chased"):
            body += " (chased once already)"
        yield _Line("waiting", body, "ledger", "asked" if opened else "read", opened)


def _loop_said(model: ProductModel, member: str, loop: dict, who: str, say: _Say) -> str:
    kind, subject = str(loop.get("kind") or ""), say(loop.get("subject"))
    context = loop.get("context") or {}
    if kind == "decision":
        asked = say(context.get("asked"), LABEL_CHARS) or subject
        return f"The decision «{asked}» waits on {who}"
    if kind == "acceptance":
        # THE SUBJECT AS THE LEDGER WRITES IT: a requirement, a defect's handle, `release-<n>` —
        # never assumed to be a card.
        return f"A delivery (`{subject}`) waits on {who} to say whether it worked"
    if kind == "card_question":
        return (f"{_ref(model, member, subject)} waits on {who} to answer the question the "
                f"factory asked on the card")
    return f"{kind} `{subject}` waits on {who}"


def _previews(model: ProductModel, say: _Say) -> Iterator[_Line]:
    """ADR-0050's previews — THE HOOK. That record is Proposed (#264) and not on this base, so
    the model carries no preview and this makes no line. When it lands, its facts join the *now*
    layer under `previews`, one `{"card", "url", "up_since"}` per preview that is up, and each is
    said here with its age: "#38's preview is up (preview — up 40 min ago)"."""
    for member in model.members:
        for preview in (model.now.get(member) or {}).get("previews") or []:
            url = say(preview.get("url"))
            yield _Line("preview", f"{_ref(model, member, preview.get('card'))}'s preview is up"
                        + (f" at {url}" if url else ""), "preview", "up",
                        str(preview.get("up_since") or ""))


def _delivered(model: ProductModel, say: _Say, now: datetime) -> Iterator[_Line]:
    """What the factory merged lately, one line — or, when nothing is that recent, the last."""
    merged = []
    for member in model.members:
        for job in (model.history.get(member) or {}).get("finished") or []:
            if _state(job) == "merged" and job.get("close_time"):
                merged.append((str(job["close_time"]), member, job))
    merged.sort(key=lambda row: row[0], reverse=True)
    if not merged:
        return
    recent = [row for row in merged if _days(row[0], now) < DELIVERED_DAYS]
    said = [_ref(model, member, job.get("issue"))
            + f" (merged{'; ' + say(job['deploy']) if job.get('deploy') else ''})"
            for _, member, job in recent or merged[:1]]
    body = (f"Delivered in the last {DELIVERED_DAYS} days: {_named(said)}" if recent else
            f"Nothing was merged in the last {DELIVERED_DAYS} days; the last delivery was "
            f"{said[0]}")
    yield _Line("delivered", body, "engine", "ended", (recent or merged)[0][0])


# ── saying a line ───────────────────────────────────────────────────────────────────────────────

def _said(line: _Line, *, read: str, now: datetime) -> str:
    """The line as the prompt carries it: cut, and closed by its source and its age."""
    body = _cut(line.body, LINE_CHARS)
    verb, when = (line.verb, line.when) if line.when else (
        "tried" if line.verb == "tried" else "read", read)
    return f"{body} ({line.source} — {verb} {age(when, now)})"


def age(stamp: str, now: datetime) -> str:
    """How long ago `stamp` was, as a person says it — "just now", "12 min ago", "3 h ago",
    "1 day ago", "5 days ago". A stamp that will not parse is said as written, never guessed."""
    if not stamp:
        return "at a time not recorded"
    then = _when(stamp)
    if then is None:
        return f"at {stamp}"
    seconds = (now - then).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return "1 day ago" if days == 1 else f"{days} days ago"


def _bounded(said: list[tuple[str, str]]) -> tuple[list[str], int]:
    """`(lines, left_out)` — the lines that fit `MAX_LINES` and `MAX_CHARS`, in their order, and
    the last one counting what did not.

    STRICT ORDER: the first line that does not fit ends the briefing, so a short line further down
    never jumps ahead of a longer one that matters more. Room for the count is kept while filling,
    so the count itself never breaks the bound."""
    texts = [text for _, text in said]
    if len(texts) <= MAX_LINES and _size(texts) <= MAX_CHARS:
        return texts, 0
    kept: list[str] = []
    for _kind, text in said:
        trial = [*kept, text]
        note = _left_out(said[len(trial):])
        if len(trial) + 1 > MAX_LINES or _size([*trial, note]) > MAX_CHARS:
            break
        kept.append(text)
    dropped = said[len(kept):]
    return [*kept, _left_out(dropped)], len(dropped)


def _left_out(dropped: list[tuple[str, str]]) -> str:
    counts: dict[str, int] = {}
    for kind, _ in dropped:
        counts[kind] = counts.get(kind, 0) + 1
    n = len(dropped)
    return (f"{n} more line{'s' if n != 1 else ''} left out to keep this briefing short ("
            + ", ".join(f"{count} {kind}" for kind, count in counts.items())
            + ") — the files hold every one, and their README names every gap")


def _size(lines: list[str]) -> int:
    return sum(len(line) for line in lines) + max(0, len(lines) - 1)


# ── small readings ──────────────────────────────────────────────────────────────────────────────

def _live(model: ProductModel) -> Iterator[tuple[str, dict]]:
    for member in model.members:
        for job in (model.now.get(member) or {}).get("jobs") or []:
            yield member, job


def _state(job: dict) -> str:
    return str((job.get("detail") or {}).get("state") or job.get("state") or "")


def _action(job: dict) -> dict | None:
    return job.get("action") or (job.get("detail") or {}).get("action")


def _started(job: dict) -> tuple[str, str]:
    start = str(job.get("start_time") or "")
    return ("started", start) if start else ("read", "")


def _ref(model: ProductModel, member: str, ref) -> str:
    """A card as the prompt names it: `#41`, or `acme-web#41` in a product of several members."""
    ref = str(ref or "?").lstrip("#")
    return f"{member}#{ref}" if len(model.members) > 1 else f"#{ref}"


def _card(model: ProductModel, member: str, job: dict, say: _Say) -> str:
    title = say(job.get("title") or (job.get("detail") or {}).get("title"), TITLE_CHARS)
    return _ref(model, member, job.get("issue")) + (f" «{title}»" if title else "")


def _named(refs: list[str]) -> str:
    more = len(refs) - NAMED
    return ", ".join(refs[:NAMED]) + (f", and {more} more" if more > 0 else "")


def _flat(text: str) -> str:
    """One line out of a markdown body: headings and emphasis marks dropped, whitespace folded."""
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    return " ".join(text.replace("**", "").split())


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _when(stamp: str) -> datetime | None:
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return then if then.tzinfo else then.replace(tzinfo=UTC)


def _days(stamp: str, now: datetime) -> float:
    then = _when(stamp)
    return float("inf") if then is None else (now - then).total_seconds() / 86400


__all__ = ["DEFAULT", "MAX_CHARS", "MAX_LINES", "SWITCH_ENV", "Briefing", "age", "enabled",
           "raw_for", "render"]

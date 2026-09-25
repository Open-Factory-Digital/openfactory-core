"""What the index holds, one ITEM at a time, and how each source becomes items (#269 slice 2).

AN ITEM IS A THING THAT CAN BE CITED. Each carries what a citation needs — where it is (`source`,
and `locator`: a page, a section, a row), when it is dated and by what (`date`, `date_from`), how
it was read (`origin`) — and what the filters need before any ranking: the product, the audience
label, and for a line of a conversation, which conversation (as a digest), whether it is somebody's
private one, and whether it was said to the role.

    document     a chunk of one document's text, as slice 1 read it (`DocumentRecord`) — or, for
                 one that could not be read, the fact that it exists and why: "could not read"
                 never becomes "nothing there" (ADR-0053 D11)
    decision     a decision a model read in a document (marked as a model's reading), or a row of a
                 requirement's decision register
    requirement  one requirement of the corpus — the curated truth — with its status and what
                 superseded it
    card         a closed card of the board, and how it closed
    turn         one line of a conversation of the product
    distillate   a chunk of what a conversation that went quiet agreed, asked and decided, as a
                 model distilled it into the context repository (#269 slice 3, ADR-0053 D4) — a
                 reading, cited as evidence; a DIRECT conversation's comes back only to it

TIME AND SUPERSESSION ARE DATA (ADR-0053 D3). A requirement carries its status and the number that
superseded it, exactly as the corpus says (`corpus.Requirement`); a row of its register carries the
requirement's. A document is not given a status here: whether it speaks for what holds today
depends on the requirements it cites, which the corpus can change without the document changing,
so the search decides it when it reads (`search.py`). Nothing a model wrote is ever given more
weight than that: a decision read from a document is `origin` "a model's reading".

GROUPS. Every item belongs to the GROUP of its source — a document's path, a requirement's number,
a card, a line — and a group is replaced whole when its source's version changes (`sync.py`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from openfactory.contracts.document import CLIENT, INTERNAL, DocumentRecord, narrowest

DOCUMENT, DECISION, REQUIREMENT, CARD, TURN = ("document", "decision", "requirement", "card",
                                               "turn")
DISTILLATE = "distillate"
KINDS = (DOCUMENT, DECISION, REQUIREMENT, CARD, TURN, DISTILLATE)

#: What an item says about itself. `current` is the only one handed over as what holds today;
#: `superseded` and `dropped` are history, `closed` a card that is done with, `unreadable` a
#: document that exists and could not be read.
CURRENT, SUPERSEDED, DROPPED, CLOSED, UNREADABLE = ("current", "superseded", "dropped", "closed",
                                                     "unreadable")

#: How long a chunk of a document is, in characters — about a paragraph or two: long enough to
#: carry a decision with its reason, short enough that a hit points at the page that says it.
CHUNK_CHARS = 1200
#: How much of a card's body is indexed. The title says what it was; the body is for the words.
CARD_CHARS = 4000


@dataclass(frozen=True)
class Item:
    """One citable thing. `grp` is its source's group; `id` is unique within the product."""

    id: str
    grp: str
    product: str
    kind: str
    source: str
    text: str
    audience: str = INTERNAL
    status: str = CURRENT
    locator: str = ""
    title: str = ""
    date: str = ""
    date_from: str = ""
    origin: str = ""
    #: for a requirement, and a row of its register: the requirement that superseded it
    successor: int | None = None
    #: the exact references the item carries — requirement numbers and card refs
    requirements: tuple[int, ...] = ()
    cards: tuple[str, ...] = ()
    #: a line of a conversation, or a conversation's distillate: the conversation's digest,
    #: whether it is one person's, and whether it was said to the role (ADR-0051 D14)
    conversation: str = ""
    private: bool = False
    addressed: bool = True
    extra: dict = field(default_factory=dict, compare=False)


def conversation_digest(key: str) -> str:
    """A conversation's key as the index keeps it — compared, never read back. The same spelling
    the write log keeps a conversation in (`product/semaphore.py::_where`)."""
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16] if key else ""


def digest_of(*parts: object) -> str:
    """A source's version, for a source that has no digest of its own."""
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


# ── documents ───────────────────────────────────────────────────────────────────────────────────

_PAGE = re.compile(r"^\[page (\d+)\]")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def chunks(text: str) -> list[tuple[str, str]]:
    """`(locator, text)` — a document cut into chunks at paragraph boundaries, each told where it
    is: `page N` for a PDF's page (the PDF row marks them, `[page N]`), `§ heading` for a section
    of markdown. A new page or a new section starts a new chunk, so a citation points at it."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    size = 0
    here = where = ""
    for para in re.split(r"\n\s*\n", text or ""):
        piece = para.strip()
        if not piece:
            continue
        page = _PAGE.match(piece)
        heading = _HEADING.match(piece.splitlines()[0])
        if page:
            here = f"page {page.group(1)}"
        elif heading:
            here = f"§ {heading.group(1).strip()[:80]}"
        if buf and (size + len(piece) > CHUNK_CHARS or here != where):
            out.append((where, "\n\n".join(buf)))
            buf, size = [], 0
        if not buf:
            where = here
        while len(piece) > CHUNK_CHARS:
            out.append((here, piece[:CHUNK_CHARS]))
            piece = piece[CHUNK_CHARS:]
        buf.append(piece)
        size += len(piece)
    if buf:
        out.append((where, "\n\n".join(buf)))
    return out


def _read_by(record: DocumentRecord) -> str:
    """How the record's text was read — the part of a citation that says how far to trust it."""
    if record.from_image:
        return (f"read from an image ({record.row or record.type}) — a number read off it may be "
                f"wrong")
    kind = {"email": "an e-mail", "pdf": "a PDF", "markdown": "a markdown document",
            "text": "a text file", "mermaid": "a mermaid diagram", "drawio": "a draw.io diagram",
            "svg": "an SVG drawing", "html": "an HTML page"}.get(record.type, "a document")
    return f"{kind}, parsed ({record.row or record.type})"


#: How a distillate says it was read — a model's reading of a conversation, never its words.
DISTILLED = ("a conversation, distilled by a model after it went quiet — a reading of what was "
             "said, cited as evidence, never a decision")


def from_record(record: DocumentRecord) -> list[Item]:
    """One version of one document as items: its chunks and the decisions a model read in it — or,
    when it could not be read, one item saying that it exists and why.

    A CONVERSATION'S DISTILLATE (`documents/record.py::distillate_of`) is a document of its own
    kind, carrying its conversation's digest and whether it was one person's: the filter that sends
    a private conversation's lines back only to it sends its distillate back only to it too."""
    from openfactory.product.documents.record import distillate_of

    grp = f"doc:{record.path}"
    distilled = distillate_of(record.path)
    kind = DOCUMENT if distilled is None else DISTILLATE
    base = dict(grp=grp, product=record.product, source=record.path,
                audience=narrowest(record.audience), title=record.title or record.path,
                date=record.date, date_from=record.date_from,
                requirements=tuple(record.requirements), cards=tuple(record.cards))
    if distilled is not None:
        base.update(private=distilled[0], conversation=distilled[1])
    if not record.readable:
        # NAMED BY ITS PATH AND ITS TITLE, so a search for it finds it — and finds that it could
        # not be read, which is the answer, rather than nothing
        words = " ".join(re.split(r"[/_.\-]+", record.path))
        return [Item(id=f"{grp}#0", kind=kind, status=UNREADABLE, origin="not read",
                     text=f"{record.title or record.path} ({words}) — this document exists in the "
                          f"context repository and could not be read: {record.reason}",
                     **base)]
    origin = _read_by(record) if distilled is None else DISTILLED
    items = [Item(id=f"{grp}#{n}", kind=kind, locator=locator, text=text, origin=origin,
                  **base)
             for n, (locator, text) in enumerate(chunks(record.text))]
    if distilled is not None:
        # A READING IS NOT READ AGAIN: the decisions of a distillate are its own sections, and a
        # model's reading of a model's reading is not given a line of its own
        return items
    for n, decision in enumerate(record.decisions if record.derived.decisions else ()):
        said = str(decision.text or "").strip()
        if not said:
            continue
        items.append(Item(id=f"{grp}!d{n}", kind=DECISION, locator=f"decision {n + 1}",
                          text=said, origin=f"a model's reading of {origin.split(',')[0]} — not "
                                            f"the document's own words",
                          **{**base, "date": str(decision.date or "") or record.date,
                             "date_from": ("the document, as the model read it" if decision.date
                                           else record.date_from)}))
    return items


# ── requirements ────────────────────────────────────────────────────────────────────────────────

#: The lines of a requirement file that are not what it promises: its heading and its header —
#: status, date, what it supersedes, and who asked (a name, which never crosses into another
#: conversation — ADR-0051 D9) — which the item carries as fields; and the register's own table,
#: indexed row by row as decisions.
_HEADER_LINE = re.compile(r"^\s*(?:#\s+REQ-\d+.*|[-*]\s*\**(?:Asked by|Status|Date|Supersedes)"
                          r":?\**.*)$", re.MULTILINE | re.IGNORECASE)


def _register(body: str) -> tuple[str, list[tuple[str, str]]]:
    """`(body without the register, [(day, decision)])` — the rows of "Decisions taken during
    execution", without who decided (a name, ADR-0051 D9)."""
    from openfactory.product.corpus import find_decisions_table

    span = find_decisions_table(body)
    if span is None:
        return body, []
    rows: list[tuple[str, str]] = []
    for line in body[span[0]:span[1]].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not line.strip().startswith("|"):
            continue
        day, said = cells[0], cells[1]
        if not said or set(said) <= set("-: ") or day.lower() in ("date", "data", "day"):
            continue
        rows.append((day if re.match(r"^\d{4}-\d{2}-\d{2}$", day) else "", said))
    return body[:span[0]] + body[span[1]:], rows


def from_requirement(requirement, *, product: str, requirements_dir: str = "") -> list[Item]:
    """A requirement of the corpus, and each row of its decision register — the curated truth, so
    its status and its successor are the corpus's own (`corpus.Requirement`)."""
    from openfactory.product.corpus import DROPPED as REQ_DROPPED
    from openfactory.product.corpus import SUPERSEDED as REQ_SUPERSEDED
    from openfactory.product.documents.record import cards_cited

    number = int(requirement.number)
    grp = f"req:{number:04d}"
    path = str(PurePosixPath(requirements_dir or ".") / str(requirement.path))
    path = path[2:] if path.startswith("./") else path
    status = (SUPERSEDED if requirement.status == REQ_SUPERSEDED
              else DROPPED if requirement.status == REQ_DROPPED else CURRENT)
    successor = requirement.superseded_by if status == SUPERSEDED else None
    body, rows = _register(str(requirement.body or ""))
    body = re.sub(r"\n{3,}", "\n\n", _HEADER_LINE.sub("", body))
    title = f"REQ-{number:04d} — {requirement.title or requirement.slug}"
    # ITS OWN NUMBER, never the ones it cites: a requirement stands or falls by its own status,
    # and "requirement 4" must find REQ-0004 — not every requirement that mentions it
    base = dict(grp=grp, product=product, source=path, audience=CLIENT, status=status,
                successor=successor, requirements=(number,),
                origin="the requirements corpus — the product's agreed record")
    items = [Item(id=grp, kind=REQUIREMENT, title=title, text=body.strip() or title,
                  date=requirement.date, date_from="the requirement's date" if requirement.date
                  else "", cards=tuple(cards_cited(body)),
                  extra={"corpus_status": requirement.status}, **base)]
    for n, (day, said) in enumerate(rows):
        items.append(Item(id=f"{grp}!d{n}", kind=DECISION, title=title, text=said,
                          locator=f"decision register, row {n + 1}", date=day,
                          date_from="the register's row" if day else "",
                          cards=tuple(cards_cited(said)), **base))
    return items


# ── cards ───────────────────────────────────────────────────────────────────────────────────────

def from_card(card, *, product: str, member: str) -> list[Item]:
    """A CLOSED card, and how it closed — an open one is the board's business (`board.md`), and a
    card reopened leaves the index (`sync.py`). Closed is not delivered: the reason says which."""
    from openfactory.product.documents.record import requirements_cited

    if str(getattr(card, "state", "") or "").lower() != "closed":
        return []
    ref = str(getattr(card, "number", "") or "").strip()
    if not ref:
        return []
    title = str(getattr(card, "title", "") or "").strip()
    body = str(getattr(card, "body", "") or "")[:CARD_CHARS]
    reason = str(getattr(card, "state_reason", "") or "").lower()
    how = {"completed": "closed as delivered", "not_planned": "closed as not planned"}.get(
        reason, "closed (the tracker does not say why)")
    when = str(getattr(card, "updated_at", "") or "")[:10]
    return [Item(id=f"card:{member}:{ref}", grp=f"card:{member}:{ref}", product=product,
                 kind=CARD, source=f"card #{ref} ({member})", title=f"#{ref} — {title}",
                 text=f"{title}\n\n{body}".strip(), audience=CLIENT, status=CLOSED,
                 date=when, date_from="the card's last update" if when else "",
                 origin=f"the board — {how}", cards=(ref,),
                 requirements=tuple(requirements_cited(f"{title}\n{body}")))]


# ── conversations ───────────────────────────────────────────────────────────────────────────────

def from_turn(said, *, product: str) -> Item:
    """One line of a conversation (`memory/recall.py::Said`). Nobody is named: the actor is not
    kept, only whether a person or the role said it (ADR-0051 D9). The conversation is kept as a
    digest, with whether it is somebody's private one — the filter that sends its lines only back
    to it."""
    from openfactory.product.conversation import is_private

    where = str(said.where or "")
    who = "the role" if said.role == "agent" else "a person"
    digest = conversation_digest(where)
    return Item(id=f"turn:{digest}:{said.ts}", grp=f"turn:{digest}:{said.ts}", product=product,
                kind=TURN, source=f"a {'private ' if is_private(where) else ''}conversation",
                text=str(said.text or ""), audience=CLIENT, date=str(said.ts)[:10],
                date_from="when it was said",
                origin=f"a conversation — {who}"
                       + ("" if said.addressed else ", said in a group to somebody else"),
                conversation=digest, private=is_private(where), addressed=bool(said.addressed),
                extra={"ts": str(said.ts)})


__all__ = [
    "CARD", "CLOSED", "CURRENT", "DECISION", "DISTILLATE", "DOCUMENT", "DROPPED", "KINDS",
    "REQUIREMENT", "SUPERSEDED", "TURN", "UNREADABLE", "Item", "chunks", "conversation_digest",
    "digest_of", "from_card", "from_record", "from_requirement", "from_turn",
]

"""The product role's agenda — what it owes, and to whom (#267 slice 3, ADR-0052).

THE LOOPS WERE A LEDGER NOBODY COULD READ AS ONE. ADR-0021 gave the role a memory of what it
expects back — a delivery it will announce, a "did it work?" it asked, a decision it is waiting
for, a question about a card — and the panel showed it only as `/api/loops`, the raw rows of every
agent, to the operator's console. The person the role owes something to had nowhere to see it.
This is the same ledger read as an AGENDA: the product role's open loops, each as what it owes
(a delivery it will announce) or what it is waiting for (an answer, a decision), and to whom.

WHO MAY SEE AN ITEM IS THE ROUTING OF THE CHAT, NOT A SECOND RULE. Every loop belongs to a
conversation — the one it was asked in, or the one its announcement went to — and the product
chat's rule decides who reads it (`api/product_chat.py::may_receive`): a room's items are the
room's, and reach whoever may read the product area; a private conversation's items reach only
the person whose conversation it is. So a person sees their own items and the room's, and never
another person's private items — on the panel (`catalog.product_agenda`, filtered by who the
credential names) and in the role's own prompt (`module._write_facts`, filtered by the
conversation the turn is in), where a room's turn is read by everyone in the room.

WHERE AN ITEM LIVES, read from what each kind already records — digests where the ledger holds
digests (`speaker.sealed`), because the ledger is read into prompts and onto the operator's
screen, and a digest names nobody:

    delivery, acceptance   `conversation` — where it was asked, and where the announcement goes
                           (#267 slice 3); one opened before it was recorded was announced to
                           the room, and is the room's
    decision               `asked_in` — a digest of the conversation it was asked in (#266 slice 4);
                           the room's when it was asked in the room or a thread of it
    everything else        the room: the sweep asks its questions there, and every row opened
                           before a conversation was recorded was read by everybody anyway

AN ITEM NEVER CARRIES A NAME. It says whom the role owes as "you" or "the room", from the viewer's
side; the loop's `person` (a forge login the sweep addresses a question to) and every sealed id
stay in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass

from openfactory.memory.ledger import (
    ACCEPTANCE,
    CARD_QUESTION,
    CONTEXT,
    DECISION,
    DELIVERY,
    QUESTION,
    Loop,
    waiting,
)

#: Whose loops are the product role's agenda. The tech-lead's are the floor's business.
OWNER = "product"

#: Which way an item points: something the role will DO for somebody, or something it is WAITING
#: to hear from somebody. A delivery is owed; everything else is an answer the role expects.
OWED, AWAITED = "owed", "awaited"

#: How much of what the role asked an item carries — a line on a panel, not the whole question.
_WHAT_CHARS = 200


@dataclass(frozen=True)
class Audience:
    """Who may see one item: the whole room, or the one conversation it lives in — kept as a
    digest (`speaker.sealed`), compared and never read. `person` is a digest of whom it is for,
    where the loop recorded one, so a room's item can say "you" to that person alone."""

    room: bool
    conversation: str = ""
    person: str = ""


@dataclass(frozen=True)
class Viewer:
    """Who is looking. `own` is the conversation that is theirs — on the panel the private key the
    credential names (`api/app.py::_conversation_of`), in a turn the conversation the turn is in;
    "" for nobody's. `person` is the viewer's id, only ever compared as a digest.
    `may_read_room` is whether the room's items reach them at all."""

    own: str = ""
    person: str = ""
    may_read_room: bool = True


@dataclass(frozen=True)
class Item:
    """One line of the agenda, as ONE viewer may see it — no name in it, ever."""

    kind: str
    subject: str
    direction: str
    said: str
    what: str
    since: str
    chased: str
    yours: bool
    to: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "subject": self.subject, "direction": self.direction,
                "said": self.said, "what": self.what, "since": self.since,
                "chased": self.chased, "yours": self.yours, "to": self.to}


def _sealed(value: str) -> str:
    from openfactory.product.speaker import sealed

    return sealed(value)


def audience(loop: Loop, *, room: str) -> Audience:
    """Where `loop` lives — see the module's table. `room` is the product's room key
    (`events.room_of`), which a decision asked in the room was sealed from."""
    from openfactory.product.conversation import is_private, owner_of

    ctx = loop.context or {}
    where = str(ctx.get("conversation") or "")
    requester = str(ctx.get("requester") or ctx.get("asked_of") or "")
    if where:
        if is_private(where):
            # SEALED BY ITS OWNER (#335): what is owed in any of a person's sessions is on that
            # person's agenda, the way it was when they had one conversation
            return Audience(room=False, conversation=_sealed(owner_of(where)), person=requester)
        return Audience(room=True, person=requester)
    asked_in = str(ctx.get("asked_in") or "")
    if asked_in:
        # ASKED IN THE ROOM, OR IN A THREAD OF IT (`about` is the room a thread lives in): the
        # room's. Anywhere else — a private conversation, a chat add-on's direct one — only that
        # conversation's: a digest cannot say which it was, and the narrow reading is the one
        # that never shows somebody's private question to the room.
        if asked_in == _sealed(room) or loop.about:
            return Audience(room=True, person=requester)
        return Audience(room=False, conversation=asked_in, person=requester)
    return Audience(room=True, person=requester)


def sees(viewer: Viewer, where: Audience) -> bool:
    """Whether `viewer` may see an item that lives `where` — the chat's rule: a room's item to
    whoever may read the room, a private one only in the conversation it lives in."""
    if where.room:
        return viewer.may_read_room
    from openfactory.product.conversation import owner_of

    # THE VIEWER'S OWNER KEY (#335): a turn in any of Ana's sessions reads what is Ana's
    return bool(viewer.own) and _sealed(owner_of(viewer.own)) == where.conversation


def visible(rows: list[Loop], viewer: Viewer, *, room: str) -> list[Loop]:
    """The ledger's rows as `viewer` may read them — every row of a loop they may see, open and
    closed alike, and none of one they may not. What the role's prompt is handed
    (`module._write_facts`), so a room's turn never reads somebody's private delivery."""
    return [row for row in rows if sees(viewer, audience(row, room=room))]


def _mine(viewer: Viewer, where: Audience) -> bool:
    if not where.room:
        return True
    return bool(viewer.person) and bool(where.person) and _sealed(viewer.person) == where.person


def _said(loop: Loop, *, yours: bool) -> tuple[str, str]:
    """What the role owes or waits for, in one line — and which way it points."""
    who = "you" if yours else "the room"
    ctx = loop.context or {}
    if loop.kind == DELIVERY:
        if ctx.get("defect"):
            return OWED, f"tell {who} when the problem reported is fixed"
        return OWED, f"tell {who} when requirement {loop.subject} is ready"
    if loop.kind == ACCEPTANCE:
        issue = str(ctx.get("release_issue") or "")
        if issue:
            return AWAITED, f"hear from {who} whether #{issue} works, before it goes live"
        if ctx.get("defect"):
            return AWAITED, f"hear from {who} whether the fix works"
        return AWAITED, f"hear from {who} whether requirement {loop.subject} works"
    if loop.kind == DECISION:
        return AWAITED, f"a decision from {who}"
    if loop.kind in (QUESTION, CARD_QUESTION):
        return AWAITED, f"an answer about #{loop.subject}"
    if loop.kind == CONTEXT:
        return AWAITED, "an answer about how the product works"
    return AWAITED, f"{loop.kind} {loop.subject}".strip()


def items(rows: list[Loop], viewer: Viewer, *, room: str) -> list[Item]:
    """The product role's agenda as `viewer` may see it: every open loop of its own, oldest first,
    each saying what is owed or awaited and to whom — "you" or "the room", never a name."""
    out: list[Item] = []
    for loop in sorted(waiting(rows, owner=OWNER), key=lambda x: x.ts):
        where = audience(loop, room=room)
        if not sees(viewer, where):
            continue
        yours = _mine(viewer, where)
        direction, said = _said(loop, yours=yours)
        ctx = loop.context or {}
        what = str(ctx.get("asked") or ctx.get("title") or "").strip()[:_WHAT_CHARS]
        out.append(Item(kind=loop.kind, subject=loop.subject, direction=direction, said=said,
                        what=what, since=loop.ts, chased=loop.chased_ts, yours=yours,
                        to="you" if yours else "the room"))
    return out


def render(found: list[Item]) -> str:
    """The agenda as text — for the CLI and for whoever reads the row's message."""
    if not found:
        return "nothing is owed and nothing is awaited here."
    lines = []
    for item in found:
        tail = f": {item.what}" if item.what else ""
        chased = f", reminded {item.chased[:10]}" if item.chased else ""
        lines.append(f"- {item.said} (since {item.since[:10] or '?'}{chased}){tail}")
    return "\n".join(lines)


__all__ = ["AWAITED", "OWED", "Audience", "Item", "Viewer", "audience", "items", "render",
           "sees", "visible"]

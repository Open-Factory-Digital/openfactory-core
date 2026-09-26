"""Which conversation with the product role a turn belongs to (#33, slice 4).

TWO SHAPES, AND THE KEY IS THE WHOLE DIFFERENCE. A ROOM is a conversation every participant of
the project writes into — what a Slack channel already is, and what every transport without a
per-person key always had: its key is the project's name (the worker's turn resolves an empty
thread to it), or any other thread a caller names. A PRIVATE conversation is one person's alone:
its key is minted by the surface that identified them — `api/app.py::_conversation_of`, `person:`
for a subject either identity row named, `visitor:` for a browser nobody has identified yet — and
is never typed.

WHAT THIS CLOSES. Slice 3 promised that nobody else could reach a private draft, *"not by a new
rule, by the key"* — while `product_say` and `product_ask` took the key as a free parameter. With
`thread="person:ana"`, Bruno's "sim" landed in Ana's conversation and consumed the draft staged
there, in her name: `staging.consume` is a compare-and-swap on the DRAFT's identity, never on who
answers — the room's rule, kept deliberately, which is exactly why the private key had to be the
control. Measured on `bf9752d`: both rows handed the engine `thread='person:ana'` for an actor
whose own conversation was `person:bruno`. `key_for` is the one place the rows resolve a key, so
the panel, the CLI and the tests cannot disagree on it.

A PERSON HAS MORE THAN ONE CONVERSATION (#335). A private key names its person, and a SESSION of
that person's is the same key with a session id after `SESSION_SEP` — `person:ana~k3f9a2`. The
key is still private (its prefix is), and it is still Ana's: every rule that asked "is this the
caller's own key?" now asks "is its OWNER the caller's own key?" (`owner_of`), so a session is as
closed to Bruno as Ana's first conversation always was, and a session id nobody could mint for
Ana is refused like any other private name. Ana's first conversation keeps its key, unchanged, so
what she said before sessions existed is still where it was.
"""

from __future__ import annotations

import re

#: The prefixes a surface mints a private key with. Anything else a caller names is a room.
PERSON = "person:"
VISITOR = "visitor:"
PRIVATE_PREFIXES = (PERSON, VISITOR)

#: What separates a person's key from one of their sessions' (#335): `person:ana~k3f9a2`.
SESSION_SEP = "~"
#: A session id: short, lower-case letters and digits — minted by the page, never a name.
_SESSION = re.compile(r"^[a-z0-9]{4,24}$")


def is_private(key: str) -> bool:
    """A key one surface minted for one person — never a room.

    READ WHATEVER THE CASE. The prefix is the one control over who reads a conversation — the
    recall filter and `key_for`'s refusal both rest on it — and a key a caller names is text they
    choose. Read case-sensitively, `Person:bob` was a room: its turns passed the recall filter into
    other people's prompts, where a model reads `in Person:bob` as bob's."""
    return str(key or "").strip().lower().startswith(PRIVATE_PREFIXES)


def key_for(*, named: str, own: str) -> str | None:
    """The conversation a turn lands in, or None when the caller named somebody else's.

    A thread the caller NAMES wins — that is a room, or their own private key spelled out — and
    none means their own (`Actor.conversation`; a CLI actor leaves it empty, which the worker
    resolves to the project's room, as it always did). A private key that is not the caller's
    own is the one name no argument may carry, and it is refused HERE rather than in each row,
    so the answer is the same on every surface.
    """
    named = str(named or "").strip()
    own = str(own or "").strip()
    if not named:
        return own
    if is_private(named) and (not own or owner_of(named) != own):
        return None
    return named


def owner_of(key: str) -> str:
    """The person's own key a private conversation belongs to — `person:ana` for
    `person:ana~k3f9a2` and for `person:ana` itself. Any other key is returned as it is: a room
    has no owner. A suffix that is not a session id is part of the key, never cut off."""
    key = str(key or "").strip()
    if not is_private(key) or SESSION_SEP not in key:
        return key
    base, _, session = key.rpartition(SESSION_SEP)
    return base if base and _SESSION.match(session) else key


def session_key(own: str, session: str) -> str | None:
    """`own`'s conversation named `session` (#335), or None when either cannot make one: a room
    has no sessions, and a session id is short letters and digits, never free text."""
    own = str(own or "").strip()
    session = str(session or "").strip().lower()
    if not is_private(own) or not _SESSION.match(session):
        return None
    return f"{owner_of(own)}{SESSION_SEP}{session}"


def session_of(key: str) -> str:
    """The session id of a private conversation's key, or "" for a person's first conversation
    and for every room."""
    owner = owner_of(key)
    return key[len(owner) + len(SESSION_SEP):] if owner != key else ""


def person_of(key: str) -> str:
    """The person a `person:` key belongs to — the owner's id, whichever of their conversations
    the key names — or "" for a room, a visitor, or nothing."""
    owner = owner_of(key)
    return owner[len(PERSON):] if owner.lower().startswith(PERSON) else ""

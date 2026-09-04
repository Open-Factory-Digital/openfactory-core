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
"""

from __future__ import annotations

#: The prefixes a surface mints a private key with. Anything else a caller names is a room.
PERSON = "person:"
VISITOR = "visitor:"
PRIVATE_PREFIXES = (PERSON, VISITOR)


def is_private(key: str) -> bool:
    """A key one surface minted for one person — never a room."""
    return str(key or "").startswith(PRIVATE_PREFIXES)


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
    if is_private(named) and named != own:
        return None
    return named

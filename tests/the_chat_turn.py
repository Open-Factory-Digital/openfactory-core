"""A chat message's turn, taken IN PROCESS: the engine and the chat adapter's renderer, without the
door — for the tests that are about the CONVERSATION, not the transport.

WHY THIS EXISTS (#266 slice 3). Twenty-two test modules drove the product conversation through
`product/channel.py::handle` with a module double in hand — the whole conversation used to live
there, and after slice 2 `handle` was the engine's turn plus the adapter's renderer. Since slice 3
`handle` goes through THE DOOR: the message is a signal on its conversation's workflow and the
turn runs on the worker, where no module double can follow it. What those modules pin is the
engine's judgement — settle, intents, the answer, the gestures, the staging — so they take the
turn here exactly as the worker's activity takes it (`engine.turn`, with the module they hand
over) and render it with the adapter's own `deliver`, as the characterisation suite does
(`test_the_conversation_is_pinned.py::_Conversation.say`). What is left out is the door and its
queue, which `tests/test_the_one_door.py` drives on an engine of its own.

The signature is `handle`'s, unchanged, so each call site changed its name and nothing else; `via`
is the chat adapter's own, as `handle` has always said it.
"""

from __future__ import annotations


class PeopleAsNamed:
    """A chat add-on's port (`adapters/channel/base.py::PeopleOfAChannel`) for tests whose users
    ARE the people their registries name — the identity mapping, stated rather than assumed. Since
    #266 slice 6 the chat adapter asks the add-on who its user is before anything is authorised,
    and a user nobody names is a guest who may write nothing; these tests pin what a click or a
    message DOES for a person, so their add-on names each user as that person."""

    def person_of(self, user: str, *, project) -> str:
        return str(user or "")


#: The add-on port the tests hand the chat adapter, and the name that adapter speaks under.
AS_NAMED = PeopleAsNamed()
CHAT = "chat"


def chat_turn(project, *, text: str, user: str, thread: str, module=None, source: str = "",
              channel: str = "", notify=None, confirm=None, fingerprint: str = "") -> str | None:
    """One chat message, answered by the engine in this process and rendered for a chat surface:
    what to say, or None to stay quiet."""
    from openfactory.product.channel import deliver
    from openfactory.product.engine import Message, turn

    replies = turn(project, Message(project=getattr(project, "name", "?"),
                                    conversation=str(thread or ""), room=str(channel or ""),
                                    speaker=str(user or ""), text=str(text or ""),
                                    source=str(source or ""), fingerprint=str(fingerprint or ""),
                                    via="slack"),
                   module=module)
    return deliver(replies, notify=notify, confirm=confirm)

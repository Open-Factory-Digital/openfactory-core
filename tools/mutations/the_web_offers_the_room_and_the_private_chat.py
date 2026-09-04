"""The web offers the room and the private chat — and the private key stops being a parameter.

ROWS 1-2 ARE THE RULE. Row 1 re-opens the hole this slice closes: any private key a caller can
spell is a conversation they may enter. Row 2 undoes slice 3 from the other side: no name means
the room for everybody, so every web turn is one shared conversation again.

ROWS 3-5 ARE THE ROWS IGNORING THE REFUSAL — `say`, `ask` and the read — each anchored through
the line that follows it, because the three-line block is the same in all three by design.

ROW 6 IS THE READ ALWAYS READING THE ROOM: "just me" shows the room's turns and calls them yours.

ROW 7 IS THE SURFACE MINTING A KEY THE RULE DOES NOT RECOGNISE, so a known person's private
conversation is a room anybody may name.

ROWS 8-9 ARE THE PAGE: the room sending no thread (everybody's room is their own private chat,
and nobody notices, because each sees a conversation), and the repaint from the store dropping the
sign-off buttons from under a draft the person is reading.
"""

TEST = "tests/test_the_web_offers_the_room_and_the_private_chat.py"

MUTATIONS = [
    ("the rule lets a caller into any private conversation they can spell — the hole re-opened",
     "openfactory/product/conversation.py",
     "    if is_private(named) and named != own:\n        return None",
     "    if False:\n        return None"),

    ("no name is the ROOM for everybody, not one's own — slice 3 undone",
     "openfactory/product/conversation.py",
     "    if not named:\n        return own",
     "    if not named:\n        return named"),

    ("`say` resolves the key but ignores the refusal",
     "openfactory/actions/catalog.py",
     "    if bad_key:\n        return bad_key\n    routed = await _say_as_an_intent(said,",
     "    if False:\n        return bad_key\n    routed = await _say_as_an_intent(said,"),

    ("`ask` resolves the key but ignores the refusal",
     "openfactory/actions/catalog.py",
     "    if bad_key:\n        return bad_key\n    routed = await _say_as_an_intent(asked,",
     "    if False:\n        return bad_key\n    routed = await _say_as_an_intent(asked,"),

    ("`product_thread` ignores the refusal and reads on",
     "openfactory/actions/catalog.py",
     "    if bad_key:\n        return bad_key\n    from openfactory.memory import transcript\n",
     "    if False:\n        return bad_key\n    from openfactory.memory import transcript\n"),

    ("`product_thread` always reads the room, whatever the caller's own conversation is",
     "openfactory/actions/catalog.py",
     "    key = key or name\n    turns = transcript.recent(name, thread=key)",
     "    key = name\n    turns = transcript.recent(name, thread=key)"),

    ("the surface mints a private key with a prefix the rule does not recognise — a room",
     "openfactory/api/app.py",
     '        return f"{PERSON}{subject.id}"',
     '        return f"user:{subject.id}"'),

    ("the panel's room sends no thread, so everybody's room is their own private chat",
     "openfactory/api/panel.html",
     "function _scopeParam(){return _prod.room?{thread:_prod.project}:{}}",
     "function _scopeParam(){return {}}"),

    ("the panel repaints from the store while a draft waits, and the sign-off buttons vanish",
     "openfactory/api/panel.html",
     '  if(!_prod.project||!$("#prodThread")||_prod.draft)return;',
     '  if(!_prod.project||!$("#prodThread"))return;'),
]

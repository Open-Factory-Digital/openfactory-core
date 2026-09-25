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

THE LAST ROW IS THE PREFIX READ CASE-SENSITIVELY (review of #279): `Person:bob` is a room
anybody may name, and recall hands its turns to everybody.
"""

TEST = "tests/test_the_web_offers_the_room_and_the_private_chat.py"

MUTATIONS = [
    ("the rule lets a caller into any private conversation they can spell — the hole re-opened",
     "openfactory/product/conversation.py",
     "    if is_private(named) and (not own or owner_of(named) != own):\n        return None",
     "    if False:\n        return None"),

    ("no name is the ROOM for everybody, not one's own — slice 3 undone",
     "openfactory/product/conversation.py",
     "    if not named:\n        return own",
     "    if not named:\n        return named"),

    # RE-PINNED 2026-09-24: the intent routing that followed it went into the turn engine
    # (#266 slice 2); the line after the refusal is the engine's client now
    # RE-PINNED 2026-09-24 (#266 slice 3): the row resolves an empty key to the project's room right
    # after it, for the door
    ("`say` resolves the key but ignores the refusal",
     "openfactory/actions/catalog.py",
     "    if bad_key:\n        return bad_key\n    key = key or proj.name\n",
     "    if False:\n        return bad_key\n    key = key or proj.name\n"),

    # RETIRED 2026-09-24: "`ask` resolves the key but ignores the refusal" — `product_ask` is the
    # one row `product_say` now, and the row above cuts its refusal

    ("`product_thread` ignores the refusal and reads on",
     "openfactory/actions/catalog.py",
     "    if bad_key:\n        return bad_key\n    from openfactory.memory import transcript\n",
     "    if False:\n        return bad_key\n    from openfactory.memory import transcript\n"),

    # RE-PINNED 2026-09-24 (#266 slice 3): the read is the product's memory now, handed the project
    ("`product_thread` always reads the room, whatever the caller's own conversation is",
     "openfactory/actions/catalog.py",
     "    key = key or name\n    # THE PRODUCT'S MEMORY (ADR-0051 D2)",
     "    key = name\n    # THE PRODUCT'S MEMORY (ADR-0051 D2)"),

    ("the surface mints a private key with a prefix the rule does not recognise — a room",
     "openfactory/api/app.py",
     '        return f"{PERSON}{subject.id}"',
     '        return f"user:{subject.id}"'),

    # RE-PINNED 2026-09-24 (#266 slice 5): the page no longer names a thread on a row — it asks
    # the product socket for the room, or not, and the server keys "not" by who it is
    ("the panel's room sends no thread, so everybody's room is their own private chat",
     "openfactory/api/panel.html",
     '  s.send(JSON.stringify({kind:"subscribe",project:_pc.project,room:_pc.room,',
     '  s.send(JSON.stringify({kind:"subscribe",project:_pc.project,room:false,'),

    # RE-PINNED 2026-09-24: what waits is the proposal the conversation staged (`_prod.staged`)
    # RE-PINNED 2026-09-24 (#266 slice 5): the repaint from the store is the socket's catch-up
    # (the `history` frame), and what it must leave alone is `_pc.staged`
    ("the panel repaints from the store while a draft waits, and the sign-off buttons vanish",
     "openfactory/api/panel.html",
     "    const kept=_pc.items.filter(i=>i.local||i.pending);\n",
     "    const kept=_pc.items.filter(i=>i.local||i.pending);_pc.staged=null;\n"),

    ("a private key spelled in capitals is a room anybody may name and recall hands to everybody",
     "openfactory/product/conversation.py",
     "    return str(key or \"\").strip().lower().startswith(PRIVATE_PREFIXES)",
     "    return str(key or \"\").startswith(PRIVATE_PREFIXES)"),
]

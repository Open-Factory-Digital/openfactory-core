"""#33 slice 3 (the web conversation is directed at the person in it): every hop is a cut.

The actor's conversation reaching the two product rows, the panel keying a known person and a
visitor, the page minting the cookie, the worker recording the arrival, handing the role the
thread, recording the reply, keying by thread — and the row's declaration, the input's field and
the client's document.

After #266 slice 2 the two rows are ONE (`product_say`) and the worker's two turns are the one
turn engine's: each row whose line moved is RE-PINNED there with its claim unchanged; the say
row's twin and the "a refusal is not recorded" row are RETIRED in place, the first because it
cut the same line as the ask row now, the second because the turn records the client's sentence
for what it could not answer — the conversation's pinned rule — on purpose.

After #266 slice 3 the row sends a `Message` through the door and the worker's turn is
`_conversation_turn`: the row, the arrival record, the worker's keying and the input's field are
RE-PINNED onto those, each marked, with their claims unchanged.
"""

TEST = "tests/test_the_web_conversation_is_directed_at_the_person_in_it.py"
CATALOG = "openfactory/actions/catalog.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
ENGINE = "openfactory/product/engine.py"
IO = "openfactory/runtime/temporal/io.py"
DOC = "docs/reference/product-role.md"

MUTATIONS = [
    # ── the rows ──
    # rows re-pinned 2026-09-07: the key is resolved once (`_conversation_key`, #46) and both rows
    # hand the worker that
    # RE-PINNED 2026-09-24: `product_ask` is the one row `product_say` now (#266 slice 2)
    # RE-PINNED 2026-09-24 (#266 slice 3): the row hands the door a `Message`, whose conversation is
    # the resolved key
    ("the ask row drops the actor's conversation", CATALOG,
     "        Message(id=uuid.uuid4().hex, project=proj.name, conversation=key, speaker=by.id,\n",
     "        Message(id=uuid.uuid4().hex, project=proj.name,\n"
     "                conversation=(thread or \"\").strip() or proj.name, speaker=by.id,\n"),

    # RETIRED 2026-09-24: the say row IS the one row, and the row above cuts its line

    # RE-PINNED 2026-09-24: `product_ask` is the one row `product_say` now (#266 slice 2)
    ("the ask row no longer takes a thread", CATALOG,
     '            required=("project", "message"),\n            optional=("thread",),\n',
     '            required=("project", "message"),\n'),

    # ── the panel ──
    # rows re-pinned 2026-09-07: the prefixes are `product/conversation.py`'s constants now
    ("a known person is not their own key", APP,
     '    if getattr(subject, "known", False):\n        return f"{PERSON}{subject.id}"\n',
     '    if False:\n        return f"{PERSON}{subject.id}"\n'),

    ("a stranger's browser is not its own key", APP,
     '    return f"{VISITOR}{visitor}" if _VISITOR_SHAPE.match(visitor) else ""\n',
     '    return ""\n'),

    ("any cookie value becomes a key", APP,
     '    return f"{VISITOR}{visitor}" if _VISITOR_SHAPE.match(visitor) else ""\n',
     '    return f"{VISITOR}{visitor}" if visitor else ""\n'),

    ("the page mints no visitor cookie", PANEL,
     "  ensureVisitor(); //",
     "  void 0; //"),

    # ── the worker ──
    # RE-PINNED 2026-09-24: moved to engine.py — the worker's turn is the one turn engine's
    # RE-PINNED 2026-09-24 (#266 slice 3): it records under the project, whose product the
    # transcript keys by
    ("the person's turn is not recorded on arrival", ENGINE,
     '        arrival_ts = transcript.record(project, thread=thread, role="person", text=text,\n'
     '                                       actor=user, channel=channel) or ""\n',
     '        arrival_ts = ""\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the role is handed the question alone", ENGINE,
     "    answer = module.answer(text, conversation=said,\n",
     '    answer = module.answer(text, conversation="",\n'),

    # RE-PINNED 2026-09-24: moved to engine.py
    ("the reply is not recorded", ENGINE,
     "        if reply:\n"
     "            # recorded from the TEXT even when it carries options",
     "        if False:\n"
     "            # recorded from the TEXT even when it carries options"),

    # RE-PINNED 2026-09-24: the worker's hand-off into the engine (`_product_turn`)
    # RE-PINNED 2026-09-24 (#266 slice 3): the hand-off is `_conversation_turn`, handed the
    # conversation the door enqueued on
    ("everybody is keyed by the project again", ACTIVITIES,
     "        return turn(project, Message(id=inp.id, project=name, conversation=inp.conversation,\n",
     "        return turn(project, Message(id=inp.id, project=name, conversation=name,\n"),

    # RETIRED 2026-09-24: "a refusal is recorded as the role's reply" — the one turn engine says
    # the client's sentence for an answer it could not give, and records it as what she said:
    # the conversation's pinned rule (tests/test_the_conversation_is_pinned.py), kept on purpose

    # ── the input and the document ──
    # RE-PINNED 2026-09-24: the one row's input (`ProductSayInput`), which the test reads now
    # RE-PINNED 2026-09-24 (#266 slice 3): the message crosses the door as an `Arrival`, which
    # carries its conversation
    ("the input carries no thread", IO,
     "    id: str\n    project: str\n    conversation: str\n    room: str = \"\"\n",
     "    id: str\n    project: str\n    room: str = \"\"\n"),

    ("the client's document forgets it", DOC,
     "**Each person has their own conversation with the role on the panel.**",
     "**Each person shares one conversation with the role on the panel.**"),
]

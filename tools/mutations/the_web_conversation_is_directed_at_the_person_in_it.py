"""#33 slice 3 (the web conversation is directed at the person in it): every hop is a cut.

The actor's conversation reaching the two product rows, the panel keying a known person and a
visitor, the page minting the cookie, the worker recording the arrival, handing the role the
thread, recording the reply, keying by thread — and the row's declaration, the input's field and
the client's document.
"""

TEST = "tests/test_the_web_conversation_is_directed_at_the_person_in_it.py"
CATALOG = "openfactory/actions/catalog.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
IO = "openfactory/runtime/temporal/io.py"
DOC = "docs/reference/product-role.md"

MUTATIONS = [
    # ── the rows ──
    ("the ask row drops the actor's conversation", CATALOG,
     '            ProductAskInput(project=proj.name, question=asked, asked_by=by.id,\n'
     '                            thread=(thread or by.conversation or "").strip()),\n',
     '            ProductAskInput(project=proj.name, question=asked, asked_by=by.id,\n'
     '                            thread=(thread or "").strip()),\n'),

    ("the say row drops the actor's conversation", CATALOG,
     '                            thread=(thread or by.conversation or "").strip(), asked_by=by.id,\n',
     '                            thread=(thread or "").strip(), asked_by=by.id,\n'),

    ("the ask row no longer takes a thread", CATALOG,
     '            name="product_ask",\n            optional=("thread",),\n',
     '            name="product_ask",\n'),

    # ── the panel ──
    ("a known person is not their own key", APP,
     '    if getattr(subject, "known", False):\n        return f"person:{subject.id}"\n',
     '    if False:\n        return f"person:{subject.id}"\n'),

    ("a stranger's browser is not its own key", APP,
     '    return f"visitor:{visitor}" if _VISITOR_SHAPE.match(visitor) else ""\n',
     '    return ""\n'),

    ("any cookie value becomes a key", APP,
     '    return f"visitor:{visitor}" if _VISITOR_SHAPE.match(visitor) else ""\n',
     '    return f"visitor:{visitor}" if visitor else ""\n'),

    ("the page mints no visitor cookie", PANEL,
     "  ensureVisitor(); //",
     "  void 0; //"),

    # ── the worker ──
    ("the person's turn is not recorded on arrival", ACTIVITIES,
     '    arrival = transcript.record(name, thread=key, role="person", text=request, actor=asked_by)\n',
     '    arrival = ""\n'),

    ("the role is handed the question alone", ACTIVITIES,
     "    said = module.answer(request, conversation=before)\n",
     "    said = module.answer(request)\n"),

    ("the reply is not recorded", ACTIVITIES,
     '    if getattr(said, "ok", False) and str(getattr(said, "text", "") or "").strip():\n'
     '        transcript.record(name, thread=key, role="agent", text=str(said.text))\n',
     '    if False:\n'
     '        transcript.record(name, thread=key, role="agent", text=str(said.text))\n'),

    ("everybody is keyed by the project again", ACTIVITIES,
     '    key = (thread or "").strip() or name\n',
     "    key = name\n"),

    ("a refusal is recorded as the role's reply", ACTIVITIES,
     '    if getattr(said, "ok", False) and str(getattr(said, "text", "") or "").strip():\n',
     '    if True:\n'),

    # ── the input and the document ──
    ("the input carries no thread", IO,
     "    #: is a conversation and not a sequence of first questions.\n    thread: str = \"\"\n",
     "    #: is a conversation and not a sequence of first questions.\n"),

    ("the client's document forgets it", DOC,
     "**Each person has their own conversation with the role on the panel.**",
     "**Each person shares one conversation with the role on the panel.**"),
]

"""A clicked yes is answered once, however many times the page catches up (#402).

Run:  .venv/bin/python tools/mutate.py tools/mutations/402_a_clicked_yes_is_answered_once.py

Row 1 is the defect as measured: the catch-up kept every item the page drew itself, so a clicked
yes's answer came back from the transcript beside the bubble drawn when the click returned. Rows
2-4 cut the page's half of the identity (the click's id, the bubble remembering it, the pending
message's twin). Rows 5-7 cut the gate's pair: the person's line with no id, the answer as the
reply to nothing, the page's id replaced by a minted one. Rows 8-10 cut the hops: the row carrying
the id, the row's check on it, the row declaring it; row 11 the worker handing it to the gate.
Rows 12-15 are the other places the class lived: `door.tell` recording without what it answers,
the history read dropping the ids, and the socket's echo matching by the words again.
"""

TEST = "tests/test_a_clicked_yes_is_answered_once.py"

PANEL = "openfactory/api/panel.html"
CONFIRM = "openfactory/product/confirm.py"
CATALOG = "openfactory/actions/catalog.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
DOOR = "openfactory/product/door.py"
CHAT = "openfactory/api/product_chat.py"

MUTATIONS = [
    # ── the page ──
    ("TODAY'S DEFECT: the catch-up keeps every item the page drew, whatever the store now holds",
     PANEL,
     "    const kept=_pc.items.filter(i=>(i.local||i.pending)&&!(i.pending&&i.id&&said.has(i.id))\n"
     "                                   &&!(i.answers&&answered.has(i.answers)));\n",
     "    const kept=_pc.items.filter(i=>i.local||i.pending);\n"),

    ("the click sends no id, so its answer is recorded as the reply to one the page never knew",
     PANEL,
     "  const out=await act(\"product_answer\",{project:_pc.project,token:staged.token,answer,yes:true,\n"
     "                                        message_id:id});\n",
     "  const out=await act(\"product_answer\",{project:_pc.project,token:staged.token,answer,yes:true});\n"),

    ("the bubble drawn for the click does not remember which click it answers", PANEL,
     "local:true,answers:out.ok?id:\"\",",
     "local:true,answers:\"\","),

    ("a message still on its way up is kept beside its own history row", PANEL,
     "(i.local||i.pending)&&!(i.pending&&i.id&&said.has(i.id))",
     "(i.local||i.pending)"),

    # ── the gate ──
    ("the click's line is recorded with no id", CONFIRM,
     "                          channel=where, message_id=said_id)\n",
     "                          channel=where)\n"),

    # RE-PINNED 2026-10-04 (#457): the record now carries a `kind` too — the crash fallback is
    # recorded as the platform's own voice, the answer as an answer
    ("the click's answer is recorded as the reply to nothing", CONFIRM,
     "                              channel=where, in_reply_to=said_id, kind=kind)\n",
     "                              channel=where, kind=kind)\n"),

    ("the page's id is ignored and a fresh one minted, so the page cannot find its answer",
     CONFIRM,
     '    said_id = str(message_id or "").strip() or uuid.uuid4().hex\n',
     "    said_id = uuid.uuid4().hex\n"),

    # ── the hops ──
    ("the row does not carry the click's id to the worker", CATALOG,
     "                               message_id=minted),\n",
     "                               ),\n"),

    ("the row takes any id, and a malformed one travels into a workflow", CATALOG,
     "    minted = str(message_id or \"\").strip()\n"
     "    if minted and not _MESSAGE_ID.match(minted):\n"
     "        return refused(INVALID, \"a message id is 8 to 128 letters, digits, '-' or '_'.\",\n"
     "                       project=proj.name)\n",
     "    minted = str(message_id or \"\").strip()\n"),

    ("the row does not declare the id, so the action layer refuses every click that sends one",
     CATALOG,
     '            optional=("yes", "message_id"),\n',
     '            optional=("yes",),\n'),

    ("the worker does not hand the id to the gate", ACTIVITIES,
     "                             module=ProductModule(project, via=via), via=via,\n"
     "                             message_id=inp.message_id)\n",
     "                             module=ProductModule(project, via=via), via=via)\n"),

    # ── the other places the class lived ──
    # RE-PINNED 2026-10-04 (#457): the record now carries a `kind` too (announcement), kept here
    ("what the role tells is recorded without what it answers, though it is published with it",
     DOOR,
     "        transcript.record(project, thread=conversation, role=\"agent\", text=said, channel=room,\n"
     "                          in_reply_to=in_reply_to, kind=ANNOUNCEMENT)\n",
     "        transcript.record(project, thread=conversation, role=\"agent\", text=said, channel=room,\n"
     "                          kind=ANNOUNCEMENT)\n"),

    ("the history hands the page no ids", CHAT,
     '             "text": t.text, "ts": t.ts, "id": t.id, "in_reply_to": t.in_reply_to,\n',
     '             "text": t.text, "ts": t.ts, "id": "", "in_reply_to": "",\n'),

    ("the echo is keyed by the words again, so an answer that only says the same thing is dropped",
     CHAT,
     '    return (f"{role}#", ident) if ident else (role, str(text or "").strip())\n',
     '    return (role, str(text or "").strip())\n'),

    ("a live frame is matched by its words even when the history row has an identity", CHAT,
     "        for said in (_echo_key(role, frame.get(\"id\") if role == \"person\"\n"
     "                               else frame.get(\"in_reply_to\"), \"\"),\n"
     "                     _echo_key(role, \"\", frame.get(\"text\"))):\n",
     "        for said in (_echo_key(role, \"\", frame.get(\"text\")),):\n"),
]

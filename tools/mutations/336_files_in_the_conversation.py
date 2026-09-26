"""Files are attached in the conversation, read by the turn and kept to their conversation (#336).

ROWS 1-5 ARE THE STORE: a file found in any conversation that holds the same bytes, an id that may
climb out of the store, the size limit gone, a message naming a file of another conversation, and
a deleted conversation's file kept, bytes and all.

ROWS 6-8 ARE THE PANEL: an upload read past its limit, a file served back as a page, and served
without `nosniff`.

ROWS 9-12 ARE THE TURN: a file of another conversation handed over because the message named it,
the reading unfenced, the list of files never reaching the prompt, the engine not handing the files
on, and a pack that takes any name as an image.

ROWS 13-14 ARE THE OFFICE ROWS: a DTD parsed, a ZIP bomb expanded.

ROWS 15-17 ARE THE PAGE AND THE DELETION: a file's name rendered as markup, the say frame without
its files, and a deleted conversation that keeps its files.
"""

TEST = "tests/test_a_file_is_attached_in_the_conversation.py"
OFFICE_TEST = "tests/test_office_documents_are_read.py"
PAGE_TEST = "tests/test_the_product_owner_s_page.py"

FILES = "openfactory/product/attachments.py"
APP = "openfactory/api/app.py"
ROLE = "openfactory/product/role.py"
ENGINE = "openfactory/product/engine.py"
FACTS = "openfactory/product/facts.py"
OFFICE = "openfactory/adapters/extract/office.py"
PANEL = "openfactory/api/panel.html"
SESSIONS = "openfactory/product/sessions.py"

MUTATIONS = [
    ("a file is found in any conversation that holds the same bytes", FILES,
     '    name = (known.get("names") or {}).get(_digest(conversation))',
     '    name = next(iter((known.get("names") or {}).values()), "")'),

    ("an id may climb out of the store", FILES,
     "    if not _ID.match(ident) or not conversation:\n        return None",
     "    if not conversation:\n        return None"),

    ("a file of any size is kept", FILES,
     "    if len(data) > limit:\n        raise Refused(",
     "    if False:\n        raise Refused("),

    ("a message may name a file its conversation was never sent", FILES,
     "        if hit is None:\n            return [], \"one of the files",
     "        if False:\n            return [], \"one of the files"),

    ("a deleted conversation's file keeps its bytes", FILES,
     '            (root / "blobs" / meta.stem).unlink(missing_ok=True)',
     "            pass"),

    ("the upload is read past its limit", APP,
     "        if len(body) > limit:\n            return JSONResponse({\"ok\": False, \"message\": "
     "f\"{files.clean_name(name)} is larger \"",
     "        if False:\n            return JSONResponse({\"ok\": False, \"message\": "
     "f\"{files.clean_name(name)} is larger \""),

    ("a file is served back as a page", APP,
     '    return Response(content=data, media_type=image or "application/octet-stream", headers={',
     '    return Response(content=data, media_type=image or "text/html", headers={'),

    ("a file is served back without nosniff", APP,
     '        "X-Content-Type-Options": "nosniff",\n        "Content-Security-Policy": '
     '"default-src \'none\'; sandbox",',
     '        "Content-Security-Policy": "default-src \'none\'; sandbox",'),

    ("the turn is handed a file of another conversation because the message named it", FILES,
     "        att = find(key, conversation=conversation, ident=att.id) or None",
     "        att = att"),

    ("a file's reading is handed over unfenced", FILES,
     "        fence = _fence(text)",
     '        fence = ""'),

    ("the list of files never reaches the prompt", ROLE,
     '            + (f"{block}\\n\\n" if (block := self._attached_block(attached)) else "")',
     '            + ""'),

    ("the engine never hands the files to the module", ENGINE,
     '                              if ex.message.attachments and _accepts(module.answer, '
     '"attachments")',
     "                              if False"),

    ("the pack takes any name under found/ as an image", FACTS,
     "    if folder != FOUND_DIR or not _ATTACHED_IMAGE.match(leaf):",
     "    if folder != FOUND_DIR:"),

    ("an office part with a DTD is parsed", OFFICE,
     '    if b"<!DOCTYPE" in raw[:4096] or b"<!ENTITY" in raw:',
     "    if False:",
     OFFICE_TEST),

    ("a ZIP bomb is expanded", OFFICE,
     "    if total > TOTAL_BYTES or any(m.file_size > MEMBER_BYTES for m in members):",
     "    if False:",
     OFFICE_TEST),

    ("a file's name is rendered as markup in the conversation", PANEL,
     '<span class="nm">${esc(f.name||"file")}</span>',
     '<span class="nm">${f.name||"file"}</span>',
     PAGE_TEST),

    ("the say frame goes without its files", PANEL,
     "                         ...(files.length?{attachments:files.map(f=>f.id)}:{})}));",
     "                         ...({})}));",
     PAGE_TEST),

    ("a deleted conversation keeps its files", SESSIONS,
     "    files = forget_files(key, conversation)",
     "    files = 0"),
]

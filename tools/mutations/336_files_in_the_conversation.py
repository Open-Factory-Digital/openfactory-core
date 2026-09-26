"""Files are attached in the conversation, read by the turn and kept to their conversation (#336).

ROWS 1-5 ARE THE STORE: a file found in any conversation that holds the same bytes, an id that may
climb out of the store, the size limit gone, a message naming a file of another conversation, and
a deleted conversation's file kept, bytes and all.

ROWS 6-8 ARE THE PANEL: an upload read past its limit, a file served back as a page, and served
without `nosniff`.

ROWS 9-12 ARE THE TURN: a file of another conversation handed over because the message named it,
the reading unfenced, the list of files never reaching the prompt, the engine not handing the files
on, and a pack that takes any name as an image.

ROWS 13-15 ARE THE OFFICE ROWS: a DTD parsed, a DOCTYPE pushed past the part's head parsed (review
of #343), a ZIP bomb expanded.

ROWS 16-18 ARE THE PAGE AND THE DELETION: a file's name rendered as markup, the say frame without
its files, and a deleted conversation that keeps its files.

THE ROWS AFTER THEM ARE THE SECOND PR's: filing (an admin's write, never overwriting, read at once),
discarding (from one conversation alone, its bytes kept while another holds them, the room's an
admin's, a line naming it as gone) and the documents tab (only a recorded document downloaded,
never rendered, the requirements kept to their tab, a search that narrows).
"""

TEST = "tests/test_a_file_is_attached_in_the_conversation.py"
OFFICE_TEST = "tests/test_office_documents_are_read.py"
PAGE_TEST = "tests/test_the_product_owner_s_page.py"

FILES = "openfactory/product/attachments.py"
APP = "openfactory/api/app.py"
CHAT = "openfactory/api/product_chat.py"
ROLE = "openfactory/product/role.py"
ENGINE = "openfactory/product/engine.py"
FACTS = "openfactory/product/facts.py"
OFFICE = "openfactory/adapters/extract/office.py"
PANEL = "openfactory/api/panel.html"
SESSIONS = "openfactory/product/sessions.py"
CATALOG = "openfactory/actions/catalog.py"
AUTHORING = "openfactory/product/authoring.py"

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
     '    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:',
     "    if False:",
     OFFICE_TEST),

    ("a DOCTYPE past the part's head is parsed", OFFICE,
     '    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:',
     '    if b"<!DOCTYPE" in raw[:4096] or b"<!ENTITY" in raw:',
     OFFICE_TEST),

    ("a ZIP bomb is expanded", OFFICE,
     "    if total > TOTAL_BYTES or any(m.file_size > MEMBER_BYTES for m in members):",
     "    if False:",
     OFFICE_TEST),

    ("a file's name is rendered as markup in the conversation", PANEL,
     '<span class="nm">${esc(f.name||"file")}</span>`\n      +`<span class="sz">${esc(pvBytes(f.size))}',
     '<span class="nm">${f.name||"file"}</span>`\n      +`<span class="sz">${esc(pvBytes(f.size))}',
     PAGE_TEST),

    ("the say frame goes without its files", PANEL,
     "                         ...(files.length?{attachments:files.map(f=>f.id)}:{})}));",
     "                         ...({})}));",
     PAGE_TEST),

    ("a deleted conversation keeps its files", SESSIONS,
     "    files = forget_files(key, conversation)",
     "    files = 0"),

    # ── filing a conversation's file, and the documents as files ──────────────────────────────
    ("anybody files into the product, not only a product admin", CATALOG,
     '    if not may_act(proj, by.id, via=getattr(by, "via", "") or "api"):\n'
     '        return refused(DENIED, "filing a document writes',
     "    if False:\n"
     '        return refused(DENIED, "filing a document writes'),

    ("a filed file overwrites one of the same name", AUTHORING,
     "        while (tmp / path).exists():",
     "        while False:"),

    ("a filed file waits for the next pass to be read", CATALOG,
     "            ingest, proj, root=Path(ctx.docs_path), commit=ctx.docs_commit, paths=[written.ref],",
     "            ingest, proj, root=Path(ctx.docs_path), commit=ctx.docs_commit, paths=[],"),

    ("any file of the context repository is downloaded, recorded or not", APP,
     '    if path not in (Store(product_key(proj)).index().get("paths") or {}):',
     "    if False:"),

    ("a document is served to be rendered on the panel's origin", APP,
     '    return Response(content=(root / clean).read_bytes(), media_type="application/octet-stream",',
     '    return Response(content=(root / clean).read_bytes(), media_type="text/html",'),

    ("the requirements are listed again among the documents", PANEL,
     '  const notReq=x=>!/^requirements\\//.test(String(x.path||""));',
     "  const notReq=x=>true;",
     PAGE_TEST),

    ("a discarded file stays in its conversation", FILES,
     "        if names.pop(mine, None) is None:\n            return False\n        if names:\n",
     "        if names.get(mine) is None:\n            return False\n        if names:\n"),

    ("a discarded file's bytes are erased while another conversation holds them", FILES,
     "        if names:\n            replace_atomically(meta, json.dumps({**known, \"names\": names}, ensure_ascii=False,\n",
     "        if False:\n            replace_atomically(meta, json.dumps({**known, \"names\": names}, ensure_ascii=False,\n"),

    ("anybody discards a file in the room", CATALOG,
     '    if asked_room and not may_act(proj, by.id, via=getattr(by, "via", "") or "api"):\n'
     '        return refused(DENIED, "a file in the project\'s room',
     '    if False:\n'
     '        return refused(DENIED, "a file in the project\'s room'),

    ("a line names a discarded file as if it were still there", CHAT,
     '    return {**file, "gone": True} if str(file.get("id") or "") not in held else dict(file)',
     "    return dict(file)"),

    ("a discarded file is still offered as a link", PANEL,
     "    if(f.gone)return`<span class=\"pv-chip gone\"",
     "    if(false)return`<span class=\"pv-chip gone\"",
     PAGE_TEST),

    ("the documents' search finds everything", PANEL,
     "  const hit=x=>!q||[x.title,x.path]",
     "  const hit=x=>true||[x.title,x.path]",
     PAGE_TEST),
]

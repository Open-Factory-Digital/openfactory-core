"""Mutation plan for #266 slice 5 — the panel is a chat (ADR-0051 D13, D15).

Each row takes away one rule the product chat stands on; every row must turn
`tests/test_the_panel_is_a_chat.py` red. The four the brief names come first, in its order — the
per-subscriber filter, the private-key check, the page context's scope check, the no-polling rule —
each cut at every place it is held. After them, the rest of what this slice promises: the socket
asks the gate like every other door and speaks as the person its credential names, no credential
rides in its address, the page is carried with every message and reaches the engine, the
conversation numbers what it heard and published, a page is handed the catch-up, the role's
presence names nobody, and the row that feeds the chat hands the message over without waiting.
"""

TEST = "tests/test_the_panel_is_a_chat.py"

CHAT = "openfactory/api/product_chat.py"
APP = "openfactory/api/app.py"
PAGE = "openfactory/product/page.py"
CATALOG = "openfactory/actions/catalog.py"
PANEL = "openfactory/api/panel.html"
ENGINE = "openfactory/product/engine.py"
DOOR = "openfactory/product/door.py"
CONVERSATION = "openfactory/runtime/temporal/conversation.py"

MUTATIONS = [
    # ── 1. the per-subscriber filter ─────────────────────────────────────────────────────────────
    ("every frame is handed to every subscriber — the filter is never asked", CHAT,
     "            if not may_receive(sub, product=product, conversation=conversation):\n"
     "                continue\n",
     "            if False:\n"
     "                continue\n"),
    ("a frame reaches subscribers of any conversation of any product", CHAT,
     "    if sub.product != product or sub.conversation != conversation:\n        return False\n",
     "    if False:\n        return False\n"),
    # RE-PINNED 2026-09-25 (#335): the rule compares the conversation's OWNER
    ("a private conversation reaches whoever is subscribed to its key, whoever they are", CHAT,
     "        return bool(sub.own) and owner_of(conversation) == sub.own\n",
     "        return True\n"),
    ("a room reaches somebody who may not read the product area", CHAT,
     "    return sub.may_read_room\n",
     "    return True\n"),

    # ── 2. the private-key check ─────────────────────────────────────────────────────────────────
    ("a socket that names somebody else's private conversation is not refused — it is let into "
     "the room", CHAT,
     "    if key is None:\n        return \"\", (",
     "    if False:\n        return \"\", ("),
    ("the key a socket names is checked against itself, so any private key is its own", CHAT,
     "    key = key_for(named=named, own=getattr(actor, \"conversation\", \"\") or \"\")\n",
     "    key = key_for(named=named, own=named)\n"),

    # ── 3. the page context's scope check ────────────────────────────────────────────────────────
    ("a page of another project hands its card to this project's chat", PAGE,
     "    if said and said != name:\n",
     "    if False:\n"),
    ("a card of another repository is read as this board's", PAGE,
     "    if repo != mine:\n",
     "    if False:\n"),
    ("a credential the board is refused has a card read to the role on its behalf", PAGE,
     "    if not may_read_board:\n",
     "    if False:\n"),
    ("the row asks and ignores the answer — a refused context goes to the door without its card",
     CATALOG,
     "    if bad_page:\n        log.warning(\"DENIED_PAGE_CONTEXT",
     "    if False:\n        log.warning(\"DENIED_PAGE_CONTEXT"),
    ("the row tells the rule every person may read the board", CATALOG,
     "    looking, bad_page = page.admit(proj, context, may_read_board=by.may_enter(FLOOR))\n",
     "    looking, bad_page = page.admit(proj, context, may_read_board=True)\n"),

    # ── 4. the no-polling rule ───────────────────────────────────────────────────────────────────
    ("the chat re-subscribes on a clock — the room's thirty seconds, back", PANEL,
     "  else if(changed)pchatSubscribe();\n",
     "  else if(changed)pchatSubscribe();\n  setInterval(()=>pchatSubscribe(),30000);\n"),
    ("the reconnect's backoff becomes a clock that never stops", PANEL,
     "clearTimeout(_pc.timer);_pc.timer=setTimeout(pchatConnect,wait);",
     "clearTimeout(_pc.timer);_pc.timer=setInterval(pchatConnect,wait);"),
    ("an operator's product page boots the floor, and its five clocks with it", PANEL,
     "  if(curProduct()!==null){ bootProduct(); return; }\n",
     ""),
    # RE-PINNED 2026-09-24 (#267 slice 3): the page reads its agenda once as it opens, too;
    # and again the same day (#269): its documents as well
    ("the product page reads the thread again a while after it opens", PANEL,
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadAgenda();loadDocuments()}\n",
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadAgenda();loadDocuments();\n"
     "    setTimeout(()=>act(\"product_thread\",{project:_prod.project}),5000)}\n"),

    # ── the socket is a door like every other ────────────────────────────────────────────────────
    ("the product socket asks nobody: it is open to whoever finds its address", APP,
     "    said_no = await gate.asked()\n",
     "    said_no = None\n"),
    ("the socket speaks as nobody the credential names", APP,
     "    actor = _actor_of(ws, await asyncio.to_thread(_subject_of, presented))\n",
     "    actor = _actor_of(ws, await asyncio.to_thread(_subject_of, \"\"))\n"),
    ("the page puts the credential in the socket's address", PANEL,
     "  try{sock=new WebSocket(`${proto}//${location.host}/api/product/stream`)}\n",
     "  try{sock=new WebSocket(`${proto}//${location.host}/api/product/stream"
     "?token=${localStorage.getItem(\"openfactory_token\")}`)}\n"),

    # ── the page it was written on, all the way to the role ──────────────────────────────────────
    # RE-PINNED 2026-09-25 (#336): the frame carries the message's files on the next line
    ("a message leaves the page without the page it was written on", PANEL,
     "  s.send(JSON.stringify({kind:\"say\",id:it.id,text:said,context:pageContext(),\n",
     "  s.send(JSON.stringify({kind:\"say\",id:it.id,text:said,\n"),
    # RE-PINNED 2026-09-24 (#266 slice 6): the arrival carries what the door knows of who the
    # message is for after the context, so the line goes on
    ("the door drops the context it was handed", DOOR,
     "                   context=dict(message.context or {}), direct=is_direct(message),\n",
     "                   context={}, direct=is_direct(message),\n"),
    # RE-PINNED 2026-09-25 (#336): the turn's files follow the context
    ("the conversation hands the turn no context", CONVERSATION,
     "            language=last.language, context=dict(last.context),",
     "            language=last.language, context={},"),
    ("the engine never reads the context into the role's current state", ENGINE,
     "                           **_looking_at(ex, module),\n",
     ""),
    ("the door carries a context nobody admitted", DOOR,
     "    if set(context) - _CONTEXT_KEYS or any(len(str(v)) > MAX_ID for v in context.values()):\n",
     "    if False:\n"),

    # ── the conversation as a transport reads it ─────────────────────────────────────────────────
    ("a published answer is not numbered, so a transport's cursor never reaches it", CONVERSATION,
     "        said = [r for r in replies if r.get(\"kind\") != \"receipt\"]\n        self._seq += 1\n",
     "        said = [r for r in replies if r.get(\"kind\") != \"receipt\"]\n"),
    ("a page that subscribes is handed no catch-up", CHAT,
     "        fan.release(sub, {\"kind\": \"history\", \"turns\": turns})\n",
     "        fan.release(sub, {\"kind\": \"history\", \"turns\": []})\n"),
    ("a presence names whose messages are waiting", CHAT,
     "    return {\"kind\": \"presence\", \"state\": THINKING if busy else IDLE, \"ahead\": ahead}\n",
     "    return {\"kind\": \"presence\", \"state\": THINKING if busy else IDLE, \"ahead\": ahead,\n"
     "            \"waiting\": waiting}\n"),
    ("the answer goes out with no word that it is going out", CHAT,
     "                           lambda _sub: {\"kind\": \"presence\", \"state\": ANSWERING, "
     "\"ahead\": 0},\n",
     "                           lambda _sub: {\"kind\": \"presence\", \"state\": THINKING, "
     "\"ahead\": 0},\n"),

    # ── the row that feeds the chat ──────────────────────────────────────────────────────────────
    ("the chat's row waits for the answer anyway, as the polling one did", CATALOG,
     "    if not _waits(wait):\n",
     "    if False:\n"),
    ("a message id a page minted reaches the door unread", CATALOG,
     "    if minted and not _MESSAGE_ID.match(minted):\n",
     "    if False:\n"),
]

"""The product chat shows a whole conversation, a page at a time, read by its key (#566), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/566_the_product_chat_pages_the_whole_conversation.py

The panel's catch-up and `product_thread` read `transcript.recent`, the PROMPT's read: the newest
turns within 6,000 characters, out of the product's last 300 rows of every conversation. A person
who reopened a conversation of fourteen turns saw its last four. The claims, each a row:

  1. the store reads ONE conversation by its key (`records_of_ticket`): only that ticket's rows,
     the newest `limit` of them, before the cursor;
  2. `transcript.page` asks the store that can read by key and never walks the product's rows for
     it; reads the product's memory by the one rule of every read — the members' old rows read
     through, a partition's stranger left out; keeps the newest page and hands the cursor of the
     one before, `""` only at the start;
  3. a store without the capability is walked, and pages the same: by the conversation, before
     the cursor;
  4. the panel's socket hands the newest page and its cursor on subscribing, answers `earlier` with
     the page before the cursor it is given, and the page draws a button that asks for it and puts
     the answer above;
  5. `product_thread` takes the cursor and hands back the next one.
"""

TEST = "tests/test_the_product_chat_pages_the_whole_conversation.py"
SINK = "openfactory/observability/sqlite_metrics.py"
TRANSCRIPT = "openfactory/memory/transcript.py"
CHAT = "openfactory/api/product_chat.py"
PANEL = "openfactory/api/panel.html"
CATALOG = "openfactory/actions/catalog.py"

MUTATIONS = [
    # 1. the store reads one conversation by its key
    ("the store reads every conversation of the kind", SINK,
     '"SELECT data FROM metrics WHERE pk = ? AND kind = ? AND ticket = ?"',
     '"SELECT data FROM metrics WHERE pk = ? AND kind = ? AND (ticket = ? OR 1)"'),
    ("the store ignores the cursor", SINK,
     "\" AND (expires_at IS NULL OR expires_at > ?) AND (? = '' OR sk < ?)\"",
     "\" AND (expires_at IS NULL OR expires_at > ?) AND (? = '' OR sk < ? OR 1)\""),
    ("the store keeps the oldest rows, not the newest", SINK,
     '" ORDER BY sk DESC LIMIT ?",',
     '" ORDER BY sk ASC LIMIT ?",'),

    # 2. transcript.page
    ("the store that reads by key is not asked; the product's rows are walked", TRANSCRIPT,
     "    if isinstance(sink, TicketReadingSink):\n",
     "    if False:\n"),
    ("the members' old partitions are not read through", TRANSCRIPT,
     "        names = tuple(dict.fromkeys((where.key, *where.members))) if where.marked "
     "else (where.key,)",
     "        names = (where.key,)"),
    ("a stranger's rows in the product's partition are read as the product's", TRANSCRIPT,
     "                if not where.marked or mark == where.key or (not mark and name in "
     "where.members):",
     "                if True:"),
    ("one row too few is asked, so there is never a page before", TRANSCRIPT,
     "before=before,\n                                              limit=limit + 1):",
     "before=before,\n                                              limit=limit):"),
    ("the oldest of the window is kept, not the newest", TRANSCRIPT,
     "    found = found[-limit:] if limit > 0 else []",
     "    found = found[:limit] if limit > 0 else []"),
    ("the cursor is dropped", TRANSCRIPT,
     '    cursor = str(found[0].get("sk", "") or found[0].get("ts", "")) if more and found '
     'else ""',
     '    cursor = ""'),

    # 3. a store without the capability is walked
    ("the walk ignores the cursor", TRANSCRIPT,
     '\n                 and (not before or str(r.get("sk", "")) < before)]',
     "]"),
    ("the walk reads every conversation", TRANSCRIPT,
     'every if str(r.get("ticket", "")) == thread',
     "every if True"),

    # 4. the panel's socket and page
    ("the catch-up is the prompt's read again", CHAT,
     "    turns, cursor = transcript.page(project, thread=key, before=before)",
     '    turns, cursor = transcript.recent(project, thread=key, overheard=True), ""'),
    ("the catch-up ignores the cursor it is asked for", CHAT,
     "    turns, cursor = transcript.page(project, thread=key, before=before)",
     "    turns, cursor = transcript.page(project, thread=key)"),
    ("the catch-up does not hand the cursor", CHAT,
     '        fan.release(sub, {"kind": "history", "turns": turns, "staged": sub.staged,\n'
     '                          "earlier": earlier})',
     '        fan.release(sub, {"kind": "history", "turns": turns, "staged": sub.staged})'),
    ("an earlier frame is not answered", CHAT,
     '                elif asked.get("kind") == "earlier":\n'
     "                    await _earlier(asked)\n",
     ""),
    ("an earlier frame is answered with the newest page", CHAT,
     'before=str(asked.get("before") or "")[:256])',
     'before="")'),
    ("the page before is put below what is shown", PANEL,
     "_pc.items=older.concat(_pc.items)",
     "_pc.items=_pc.items.concat(older)"),
    ("the button is built and never drawn", PANEL,
     "?earlier+_pc.items.map(pvMsg)",
     "?_pc.items.map(pvMsg)"),
    ("the catch-up's cursor is not kept", PANEL,
     '    _pc.earlier=m.earlier||"";_pc.asking=false;\n    const named',
     "    _pc.asking=false;\n    const named"),

    # 5. product_thread
    ("product_thread ignores the cursor", CATALOG,
     'transcript.page(proj, thread=key, before=(before or "").strip())',
     "transcript.page(proj, thread=key)"),
    ("product_thread does not hand back the next cursor", CATALOG,
     "turns=rows, earlier=earlier)",
     "turns=rows)"),
    ("product_thread is not offered the cursor", CATALOG,
     'optional=("thread", "before"),',
     'optional=("thread",),'),
]

"""#269 slice 2 (the hybrid index, where time and supersession are data, and the retrieval step with
its `[[BUSCA]]` marker), proven by breaking it.

EIGHT CLAIMS, each cut here and each required to go red:

  1. **A superseded item is never handed over as current.** It is returned only under what
     superseded it — the requirement's successor, the live end of a chain — marked, with the
     timeline said; the successor is pulled in when only the old item matched; one whose successor
     cannot be shown is not listed at all. A document, a model's reading of it and a closed card
     that cite only superseded requirements are superseded with them.
  2. **The audience is a filter before ranking.** An internal document reaches no client and no
     room, by any stage; a pack another conversation's turn may read is searched as a room's.
  3. **Product is a hard partition.** One file per product, a file of another product is not read,
     a write of another product's item is refused, and every read filters on the product.
  4. **The search before the turn never includes an unaddressed line** — an explicit search may, and
     a private conversation's lines reach only that conversation.
  5. **The marker is bounded**: a few searches a round, a few rounds a turn, the last one said, the
     prompt continued, the marker offered only where it can run, and stripped by name.
  6. **Every search is recorded** — who asked, the query, the hits, the conversation as a digest —
     and the record forgets what the transcript forgets.
  7. **Exact terms beat semantic neighbours** — a requirement number, a card, a rare name — and the
     item that IS the one named comes before what cites it.
  8. **Degraded, never silent; local, never downloaded**: without an embedder the search says so,
     vectors of another model are not compared, and the local row loads only a pinned model from an
     absolute folder with the hub switched off. And the step itself: the pre-turn file is written,
     once per turn, never under the semaphore, the switch turns it off, the scheduled pass brings
     the index up to its documents, and the sync reads only what changed.

The guards under test: `tests/test_the_hybrid_index.py` (the default) and
`tests/test_the_retrieval_step.py`.
"""

TEST = "tests/test_the_hybrid_index.py"
STEP = "tests/test_the_retrieval_step.py"

SEARCH = "openfactory/product/index/search.py"
ITEMS = "openfactory/product/index/items.py"
STORE = "openfactory/product/index/store.py"
SYNC = "openfactory/product/index/sync.py"
RETRIEVAL = "openfactory/product/index/retrieval.py"
ROLE = "openfactory/product/role.py"
MODULE = "openfactory/product/module.py"
FACTS = "openfactory/product/facts.py"
LOCAL = "openfactory/adapters/embed/local.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── 1. a superseded item is never handed over as current ──────────────────────────────────
    ("a superseded item stays among the hits, handed over as current", SEARCH,
     "    current = [h for h in best.values() if h.status != SUPERSEDED]\n"
     "    superseded = [h for h in best.values() if h.status == SUPERSEDED]",
     "    current = list(best.values())\n    superseded = []"),

    ("a superseded requirement is read as current", SEARCH,
     "            return SUPERSEDED, _ends(row[\"successor\"], requirements)",
     "            return CURRENT, ()"),

    ("a document that cites only superseded requirements is read as current", SEARCH,
     "        if cited and not any(requirements[n][\"status\"] == CURRENT for n in cited):",
     "        if False:"),

    # re-pinned 2026-09-24: a conversation's distillate joins the kinds read this way (#269 s. 3)
    ("the card that built a superseded rule is read as current", SEARCH,
     "    if row[\"kind\"] in (DOCUMENT, DECISION, CARD, DISTILLATE) and status != UNREADABLE:",
     "    if row[\"kind\"] in (DOCUMENT, DECISION, DISTILLATE) and status != UNREADABLE:"),

    ("the successor is never pulled in when only what it replaced matched", SEARCH,
     "            if home is None and number in requirements:",
     "            if False:"),

    ("a superseded item whose successor cannot be shown is listed anyway", SEARCH,
     "        if not homes:\n            withheld += 1\n            continue",
     "        if not homes:\n            withheld += 1\n            current.append(old)\n"
     "            continue"),

    ("a chain of supersessions stops at its first link", SEARCH,
     "        here = row[\"successor\"]\n    return ()",
     "        return (row[\"successor\"],)\n    return ()"),

    ("what holds does not bring what it replaced unless the words matched it", SEARCH,
     "    for home in list(by_number.values()):\n        listed = {h.number for h in home.history}",
     "    for home in []:\n        listed = {h.number for h in home.history}"),

    # re-pinned 2026-09-24: the cap keeps the NEWEST of a long chain (the first run's chain test,
    # written for a survivor, found the oldest were kept and the last link dropped)
    ("the history is told newest first", SEARCH,
     "        home.history = sorted(home.history, key=lambda h: (_day(h.date), h.id))"
     "[-HISTORY_PER_HIT:]",
     "        home.history = sorted(home.history, key=lambda h: (_day(h.date), h.id), "
     "reverse=True)[:HISTORY_PER_HIT]"),

    ("a long chain keeps its far past and drops the link that replaced the others last", SEARCH,
     "        home.history = sorted(home.history, key=lambda h: (_day(h.date), h.id))"
     "[-HISTORY_PER_HIT:]",
     "        home.history = sorted(home.history, key=lambda h: (_day(h.date), h.id))"
     "[:HISTORY_PER_HIT]"),

    ("a requirement the corpus says is superseded is indexed as current", ITEMS,
     "    status = (SUPERSEDED if requirement.status == REQ_SUPERSEDED",
     "    status = (CURRENT if requirement.status == REQ_SUPERSEDED"),

    ("a requirement is indexed without the one that superseded it", ITEMS,
     "    successor = requirement.superseded_by if status == SUPERSEDED else None",
     "    successor = None"),

    ("the timeline is never said", RETRIEVAL,
     "        lines.append(f\"- timeline: {_timeline(hit)}\")",
     "        pass"),

    # ── 2. the audience is a filter before ranking ────────────────────────────────────────────
    ("every audience label passes the filter", SEARCH,
     "    allowed = [label for label in AUDIENCES if may_read(label, query.audience)]",
     "    allowed = list(AUDIENCES)"),

    ("a document's label is lost when it is indexed", ITEMS,
     "                audience=narrowest(record.audience), title=record.title or record.path,",
     "                audience=CLIENT, title=record.title or record.path,"),

    ("the module searches every turn as an internal reader", MODULE,
     "    audience = getattr(module, \"_documents_audience\", CLIENT) if own else CLIENT\n"
     "    return audience, str(getattr(module, \"_conversation\", \"\") or \"\"), own",
     "    audience = \"internal\"\n"
     "    return audience, str(getattr(module, \"_conversation\", \"\") or \"\"), own", STEP),

    ("a pack another conversation's turn may read is searched with its turn's audience", MODULE,
     "    audience = getattr(module, \"_documents_audience\", CLIENT) if own else CLIENT\n"
     "    return audience, str(getattr(module, \"_conversation\", \"\") or \"\"), own",
     "    audience = getattr(module, \"_documents_audience\", CLIENT)\n"
     "    return audience, str(getattr(module, \"_conversation\", \"\") or \"\"), own", STEP),

    ("the search before the turn keeps a shared pack's audience", RETRIEVAL,
     "    query = Query(text=query_of(question, said), audience=audience if own else CLIENT,",
     "    query = Query(text=query_of(question, said), audience=audience,", STEP),

    ("the role's search keeps a shared pack's audience", RETRIEVAL,
     "    founds = [run(project, Query(text=q, audience=audience if own else CLIENT,",
     "    founds = [run(project, Query(text=q, audience=audience,", STEP),

    # ── 3. product is a hard partition ────────────────────────────────────────────────────────
    ("every product shares one index file", STORE,
     "    return product_state_dir(key) / DIRNAME / FILENAME",
     "    return product_state_dir(\"shared\") / DIRNAME / FILENAME"),

    ("an index file built for another product is read", STORE,
     "        if found.get(\"product\") not in (None, self.key):",
     "        if False:"),

    ("a write takes another product's item", STORE,
     "            if item.product != self.key:",
     "            if False:"),

    ("the search reads every product's rows in the file", SEARCH,
     "    clauses = [\"items.product = ?\", ",
     "    clauses = [\"? != ''\", "),

    # ── 4. unaddressed lines, and private conversations ───────────────────────────────────────
    ("the engine's own search reads what was said to somebody else", RETRIEVAL,
     "own=conversation if own else \"\", exclude=conversation, overheard=False)",
     "own=conversation if own else \"\", exclude=conversation, overheard=True)", STEP),

    # re-pinned 2026-09-24: the distillates' clause follows it in the list (#269 slice 3)
    ("the filter lets an unaddressed line through whatever the search", SEARCH,
     "               \"AND (? = 1 OR items.addressed = 1) AND items.conversation != ?))\",",
     "               \"AND (? = 1 OR 1 = 1) AND items.conversation != ?))\",", STEP),

    ("a line's mark — said to somebody else — is lost when it is indexed", ITEMS,
     "addressed=bool(said.addressed),",
     "addressed=True,", STEP),

    ("a search the role asked for never finds what a group said to somebody else", RETRIEVAL,
     "                                 own=conversation if own else \"\", overheard=True),",
     "                                 own=conversation if own else \"\", overheard=False),", STEP),

    ("a private conversation's lines reach every conversation", SEARCH,
     "               \"(items.kind != 'turn' OR ((items.private = 0 OR items.conversation = ?) \"",
     "               \"(items.kind != 'turn' OR ((1 = 1 OR items.conversation = ?) \"", STEP),

    ("a line's privacy is lost when it is indexed", ITEMS,
     "private=is_private(where), addressed",
     "private=False, addressed", STEP),

    ("a shared pack's search reads the turn's own private lines", RETRIEVAL,
     "                                 own=conversation if own else \"\", overheard=True),",
     "                                 own=conversation, overheard=True),", STEP),

    # ── 5. the marker is bounded ──────────────────────────────────────────────────────────────
    ("the role's rounds are not bounded", ROLE,
     "        for round_ in range(1, SEARCH_ROUNDS + 1):",
     "        for round_ in range(1, SEARCH_ROUNDS + 5):", STEP),

    ("a round runs every search the model asked for", ROLE,
     "                note = self.search(asked[:SEARCHES_PER_ROUND], round_)",
     "                note = self.search(asked, round_)", STEP),

    ("the last round is never told it is the last", ROLE,
     "            last = round_ == SEARCH_ROUNDS",
     "            last = False", STEP),

    ("a search the bound did not run is left to the safety net", ROLE,
     "        text = _SEARCH_RE.sub(\"\", text).rstrip()",
     "        pass", STEP),

    ("the marker is never offered", ROLE,
     "            + self._search_instruction(),",
     "            + \"\",", STEP),

    ("the turn continues with the note alone, not the prompt it was asked", ROLE,
     "            res = self._ask(sandbox, workspace, prompt + _continuation(notes, last=last),",
     "            res = self._ask(sandbox, workspace, _continuation(notes, last=last),", STEP),

    ("the module never hands the role its search", MODULE,
     "                           search=(getattr(self, \"_search_for_the_role\", None)",
     "                           search=(None", STEP),

    ("a round's file is never named in the manifest", FACTS,
     "            readme.write_text(text, encoding=\"utf-8\")",
     "            pass", STEP),

    # ── 6. every search is recorded ───────────────────────────────────────────────────────────
    ("a search is never recorded", RETRIEVAL,
     "    record(key, by=by, found=found, conversation=conversation, round_=round_)",
     "    pass", STEP),

    ("the record keeps the conversation's key as it is", RETRIEVAL,
     "\"conversation\": conversation_digest(conversation),",
     "\"conversation\": conversation,", STEP),

    ("the record never forgets", RETRIEVAL,
     "            _forget_old(path, cutoff)",
     "            pass", STEP),

    ("the record does not say who formulated the search", RETRIEVAL,
     "\"ts\": when.isoformat(timespec=\"seconds\"), \"by\": by,",
     "\"ts\": when.isoformat(timespec=\"seconds\"), \"by\": ENGINE,", STEP),

    ("the record keeps no hits", RETRIEVAL,
     "\"hits\": [_entry(h) for h in found.hits]}",
     "\"hits\": []}", STEP),

    # ── 6b. a deletion request reaches what was derived from the conversations ────────────────
    ("a deletion request leaves the index's lines", RETRIEVAL,
     "                Index.drop_groups(con, lines)",
     "                pass", STEP),

    ("a deletion request leaves the recall index the sync reads the lines back from", RETRIEVAL,
     "        (Path(project_memory_dir(project)) / INDEX_FILE).unlink(missing_ok=True)",
     "        pass", STEP),

    ("the deletion command never reaches the derived stores", "openfactory/cli.py",
     "        lines = forget_conversations(where.key, members)",
     "        lines = 0", STEP),

    # ── 7. exact terms beat semantic neighbours ───────────────────────────────────────────────
    ("the exact-term tier is not the first key of the order", SEARCH,
     "    return (-hit.exact, -hit.score, 0 if day else 1, tuple(-ord(c) for c in day))",
     "    return (-hit.score, 0 if day else 1, tuple(-ord(c) for c in day))"),

    ("a card named is not an exact term", SEARCH,
     "    tier += sum(2 if itself else 1 for c in exact.cards if c in cards)",
     "    tier += 0"),

    ("a requirement named is not an exact term", SEARCH,
     "    tier = sum(2 if n == number else 1 for n in exact.requirements "
     "if n == number or n in cited)",
     "    tier = 0"),

    ("the requirement named counts no more than a document that cites it", SEARCH,
     "    tier = sum(2 if n == number else 1 for n in exact.requirements "
     "if n == number or n in cited)",
     "    tier = sum(1 for n in exact.requirements if n == number or n in cited)"),

    ("a name is never an exact term", SEARCH,
     "        if 0 < int(seen[0]) <= ceiling:",
     "        if False:"),

    ("a word the whole product says counts as a name", SEARCH,
     "        if 0 < int(seen[0]) <= ceiling:",
     "        if 0 < int(seen[0]):"),

    ("the lexical stage never asks for a requirement's own token", SEARCH,
     "    words += [ref_token(\"req\", n) for n in sorted(exact.requirements)]",
     "    words += []"),

    ("the index keeps no exact reference as a word", STORE,
     "    return \" \".join([*(ref_token(\"req\", n) for n in item.requirements),\n"
     "                     *(ref_token(\"card\", c) for c in item.cards)])",
     "    return \"\""),

    # ── 8. degraded, never silent; local, never downloaded; the step itself ───────────────────
    ("a search without an embedder says nothing about it", SEARCH,
     "        why = degraded or (\"\" if embedder is not None else \"no embedder is configured\")",
     "        why = \"\""),

    ("the file the role reads does not say the search was degraded", RETRIEVAL,
     "    if found.degraded:",
     "    if False:"),

    ("vectors made by another model are compared with this one's", SEARCH,
     "    if made_by and made_by != embedder.id:",
     "    if False:"),

    ("the search runs under the product's semaphore", SEARCH,
     "    refuse_a_model_here(\"product_search\")",
     "    pass"),

    ("an unpinned model is loaded", LOCAL,
     "        if digest not in PINNED and digest != declared:",
     "        if False:"),

    ("the hub's client is left on when the library loads", LOCAL,
     "        os.environ[\"HF_HUB_OFFLINE\"] = \"1\"",
     "        pass"),

    ("a bare model name is handed to the library, which would download it", LOCAL,
     "        if not folder.is_absolute():",
     "        if False:"),

    ("the search before the turn is never written into the pack", MODULE,
     "        found, found_gaps = _the_search_before_the_turn(self, root)",
     "        found, found_gaps = {}, []", STEP),

    ("the pack refuses the found files", FACTS,
     "                  if name.startswith(f\"{FOUND_DIR}/\")})",
     "                  if False})", STEP),

    ("the search before the turn runs again for every role a turn builds", MODULE,
     "    if \"_found_before\" in vars(module):\n        return module._found_before",
     "    if False:\n        return module._found_before", STEP),

    ("the search before the turn runs while the semaphore is held", MODULE,
     "    if semaphore.held_here(project):\n        return {}, []",
     "    if False:\n        return {}, []", STEP),

    ("what retrieval costs a turn is never measured", RETRIEVAL,
     "    _measured(project, ENGINE, [found], text)",
     "    pass", STEP),

    ("the switch turns nothing off", RETRIEVAL,
     "    return (os.environ.get(SWITCH_ENV) or \"\").strip().lower() not in (\"off\", \"0\", "
     "\"false\", \"no\")",
     "    return True", STEP),

    ("the scheduled pass leaves the index behind its documents", ACTIVITIES,
     "        from openfactory.product.index.retrieval import refresh\n",
     "        refresh = None\n", STEP),

    ("a requirement file is indexed a second time, as a plain document", SYNC,
     "        if is_requirement_file(path, requirements_dir):",
     "        if False:"),

    ("a document gone from the repository stays in the index", SYNC,
     "        Index.drop_groups(con, gone)\n        done.removed += len(gone)\n"
     "        for grp, (path, digest, version) in wanted.items():",
     "        done.removed += len(gone)\n"
     "        for grp, (path, digest, version) in wanted.items():"),

    ("an unchanged document is read and written again on every sync", SYNC,
     "            if known.get(grp) == version:\n                continue\n"
     "            record = records.get(path, digest)",
     "            if False:\n                continue\n            record = records.get(path, digest)"),

    ("a card reopened stays in the index as closed", SYNC,
     "                if grp in known:  # reopened: no longer a closed card",
     "                if False:  # reopened: no longer a closed card"),

    ("a line past the transcript's retention stays in the index", SYNC,
     "    if old:\n        with con:\n            Index.drop_groups(con, old)",
     "    if False:\n        with con:\n            Index.drop_groups(con, old)"),

    ("a turn embeds without bound", SYNC,
     "    left = limit",
     "    left = None"),

    ("vectors of another model are kept and never made again", SYNC,
     "    if Index.meta(con, \"embedder\") != embedder.id:",
     "    if False:"),
]

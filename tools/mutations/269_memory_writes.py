"""#269 slice 3 (memory writes: "done before?" over the whole memory, the visibility of documents in
every path into a client's turn, the distillation of a quiet conversation, and a yes that is never
lost to contention), proven by breaking it.

FOUR CLAIMS, each cut here and each required to go red:

  1. **"Was this done before?" reads the whole memory.** The module hands `already_asked` what the
     product's index found — dropped and superseded requirements, closed cards of any age,
     documents, distillates — each held to the same word overlap, cited with what became of it,
     searched in the turn's scope, recorded, never under the semaphore; and the draft is checked
     against the same section.
  2. **An internal document never reaches a client's turn.** The view a turn reads is made to its
     audience: nothing labelled internal or labelled by nobody, no other conversation's direct
     distillate, no folder of only those, the curated truth kept; decided before the view is made,
     never falling back to the shared directory, and said in the manifest by a count. The index
     keeps a distillate's conversation and sends a direct one back only to it.
  3. **A quiet conversation is distilled once per span, through the semaphore, naming nobody.**
     Only when quiet, bounded, after what was distilled, from its addressed lines by role; the
     model outside the lock and the write under it, re-checked in the base; everybody the product
     knows, every address and mention withheld; labelled for its conversation's reader; never read
     again nor announced by the documents' pass; on the knowledge tick, registered.
  4. **Saved when confirmed.** Every kind a person says yes to writes in the confirmation; a yes the
     semaphore refused wrote nothing and is staged again, and only then.

The guards under test: `tests/test_the_memory_writes.py` (the default), and the rows that name
another file.
"""

TEST = "tests/test_the_memory_writes.py"
TICK = "tests/test_the_documents_are_read_on_the_schedule_and_on_an_event.py"

ASKED = "openfactory/product/asked.py"
MODULE = "openfactory/product/module.py"
ROLE = "openfactory/product/role.py"
RETRIEVAL = "openfactory/product/index/retrieval.py"
SEARCH = "openfactory/product/index/search.py"
ITEMS = "openfactory/product/index/items.py"
RECORD = "openfactory/product/documents/record.py"
INGEST = "openfactory/product/documents/ingest.py"
WORKSPACE = "openfactory/product/workspace.py"
DISTIL = "openfactory/product/distil.py"
AUTHORING = "openfactory/product/authoring.py"
CONFIRM = "openfactory/product/confirm.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
WORKER = "openfactory/runtime/temporal/worker.py"

MUTATIONS = [
    # ── 1. "was this done before?" reads the whole memory ─────────────────────────────────────
    ("the module hands the index's hits to nothing", MODULE,
     "                                      found=_done_before(self, text))",
     "                                      found=())"),

    ("the done-before search reads the requirements alone", RETRIEVAL,
     "DONE_BEFORE_KINDS = (REQUIREMENT, DECISION, CARD, DOCUMENT, DISTILLATE)",
     "DONE_BEFORE_KINDS = (REQUIREMENT,)"),

    ("a closed card the index found is not a lead", ASKED,
     "    if kind == \"card\":",
     "    if False:"),

    ("a dropped requirement is not said to be dropped", ASKED,
     "_STANDING = {\"superseded\": \"superseded\", \"dropped\": \"dropped\", "
     "\"unreadable\": \"could not be read\"}",
     "_STANDING = {\"superseded\": \"superseded\", \"unreadable\": \"could not be read\"}"),

    ("what a live requirement replaced is never read", ASKED,
     "        yield from getattr(hit, \"history\", None) or ()",
     "        yield from ()"),

    ("a superseded requirement is not said to be superseded by what replaced it", ASKED,
     "        said = \"superseded by \" + \", \".join(f\"REQ-{int(n):04d}\" for n in successors)",
     "        said = \"\""),

    ("an index hit is a lead whatever it shares with the request", ASKED,
     "    if not _plausible(shared, score):\n        return None\n    date = ",
     "    if False:\n        return None\n    date = "),

    ("a distilled conversation is not a lead", ASKED,
     "    if kind == \"distillate\":",
     "    if False:"),

    ("a document is not a lead", ASKED,
     "    if kind == \"document\":",
     "    if False:"),

    ("the done-before search of a pack another conversation may read is the turn's own",
     RETRIEVAL,
     "    query = Query(text=text, audience=audience if own else CLIENT,\n"
     "                  own=conversation if own else \"\", overheard=False, "
     "kinds=DONE_BEFORE_KINDS)",
     "    query = Query(text=text, audience=audience,\n"
     "                  own=conversation, overheard=False, kinds=DONE_BEFORE_KINDS)"),

    ("the done-before search tries under the semaphore", MODULE,
     "        if semaphore.held_here(project):\n            return []\n"
     "        audience, conversation, own = _the_search_scope(module, getattr(module, "
     "\"_combined\", None))",
     "        audience, conversation, own = _the_search_scope(module, getattr(module, "
     "\"_combined\", None))"),

    ("the done-before search is recorded as the engine's", RETRIEVAL,
     "    return run(project, query, by=DONE_BEFORE, conversation=conversation)",
     "    return run(project, query, by=ENGINE, conversation=conversation)"),

    ("the draft is not checked against what the answer was shown", MODULE,
     "        section = self.already_asked(request) if _takes(role.draft, \"asked\") else \"\"",
     "        section = \"\""),

    ("the draft is not told to report a dropped twin as a duplicate", ROLE,
     "               \"that cites it by its reference and says what became of it.\" if asked "
     "else \"\"),",
     "               \"that cites it by its reference and says what became of it.\" if False "
     "else \"\"),"),

    # ── 2. an internal document never reaches a client's turn ─────────────────────────────────
    ("the view is made with nothing withheld", MODULE,
     "            made = turn_view(turns, docs=docs, sources=sources, withheld=withheld)",
     "            made = turn_view(turns, docs=docs, sources=sources, withheld=())"),

    ("a document nobody labelled is shown to a client's view", RECORD,
     "        if not may_read(label, reader):\n            out.append(path)",
     "        if not may_read(label, reader) and _from != \"default\":\n            "
     "out.append(path)"),

    ("a document's own front matter is not read for the view", RECORD,
     "        label, _from, _notes = audience(path, \"\" if link else declared(root, path))",
     "        label, _from, _notes = audience(path, \"\")"),

    ("another conversation's direct distillate is in the view", RECORD,
     "        if distilled is not None and distilled[0] and distilled[1] != mine:",
     "        if False:"),

    ("the curated truth is withheld from a client's view", RECORD,
     "        if curated is not None and curated(path):\n            continue\n",
     ""),

    ("a folder holding only what is withheld is made anyway", WORKSPACE,
     "            if rel in files or (rel in folders and rel not in kept_dirs):",
     "            if rel in files:"),

    ("a view that cannot be made to its audience falls back to the shared one", MODULE,
     "            if withheld:\n                log.warning(\"the view of %s could not be made",
     "            if False:\n                log.warning(\"the view of %s could not be made"),

    ("a view whose documents could not be judged hands over everything", MODULE,
     "        if withheld is None:\n            return self._an_empty_view(",
     "        if False:\n            return self._an_empty_view("),

    ("the audience is decided after the view is made", MODULE,
     "        self._documents_audience = turn_audience(speaker, private=private)\n"
     "        sandbox, ws = self._workspace()\n",
     "        sandbox, ws = self._workspace()\n"
     "        self._documents_audience = turn_audience(speaker, private=private)\n"),

    ("a view made before the answer is the widest", MODULE,
     "        audience = str(getattr(self, \"_documents_audience\", \"\") or CLIENT)",
     "        audience = str(getattr(self, \"_documents_audience\", \"\") or \"internal\")"),

    ("the manifest does not say what the view left out", MODULE,
     "                                 gaps=[*gaps, *found_gaps, *_the_view_s_gap(self)])",
     "                                 gaps=[*gaps, *found_gaps])"),

    ("the index sends a direct distillate to every conversation", SEARCH,
     "               \"(items.kind != 'distillate' OR items.private = 0 OR "
     "items.conversation = ?)\"]",
     "               \"(items.kind != 'distillate' OR 1 = 1 OR items.conversation = ?)\"]"),

    ("a distillate is indexed as a plain document", ITEMS,
     "    kind = DOCUMENT if distilled is None else DISTILLATE",
     "    kind = DOCUMENT"),

    ("a distillate's conversation is not kept in the index", ITEMS,
     "    if distilled is not None:\n        base.update(private=distilled[0], "
     "conversation=distilled[1])\n",
     ""),

    # ── 3. a quiet conversation, distilled once per span, through the semaphore, naming nobody ─
    ("the base is not re-read for what was distilled since", AUTHORING,
     "        if target.exists() or (latest and latest > after):",
     "        if target.exists():"),

    ("the distillate is written outside the semaphore", MODULE,
     "            return self._checked_write(\n                act=\"distil a conversation\"",
     "            return (lambda **kw: kw[\"write\"]())(\n                act=\"distil a "
     "conversation\""),

    ("a pass distils under the semaphore", DISTIL,
     "    if semaphore.held_here(project):\n        raise semaphore.ModelUnderSemaphore(",
     "    if False:\n        raise semaphore.ModelUnderSemaphore("),

    ("the model distils under the semaphore", DISTIL,
     "        refuse_a_model_here(PHASE)\n", ""),

    ("what the model wrote is written with its names", DISTIL,
     "        items = [scrub(item, people) for item in getattr(reading, name)]",
     "        items = list(getattr(reading, name))"),

    ("the model is handed the lines with their names", DISTIL,
     "                             text=scrub(str(s.text).strip(), people)) for s in spoken),",
     "                             text=str(s.text).strip()) for s in spoken),"),

    ("a speaker is handed to the model by id", DISTIL,
     "    return SAID_AS.get(person(project, str(getattr(line, \"actor\", \"\") or \"\")).role, "
     "\"a client\")",
     "    return str(getattr(line, \"actor\", \"\") or \"\")"),

    ("a line said in a group to somebody else is handed over", DISTIL,
     "        spoken = [s for s in taken if s.addressed]",
     "        spoken = list(taken)"),

    ("a conversation still talking is distilled", DISTIL,
     "        if newest is None or newest > cutoff:",
     "        if newest is None:"),

    ("a span is unbounded", DISTIL,
     "            if len(taken) >= MAX_LINES or size + len(s.text) > MAX_CHARS:",
     "            if False:"),

    ("a span starts at the conversation's first line, whatever was distilled", DISTIL,
     "        fresh = sorted((s for s in held if str(s.ts) > after), key=lambda s: str(s.ts))",
     "        fresh = sorted(held, key=lambda s: str(s.ts))"),

    ("an address and a mention are kept", DISTIL,
     "    text = _MENTION.sub(SOMEONE, _EMAIL.sub(\"[an address]\", str(text or \"\")))",
     "    text = str(text or \"\")"),

    ("a name spelled in another case is kept", DISTIL,
     "        text = re.sub(rf\"(?<![\\w.-])(?:{names})(?![\\w-])\", SOMEONE, text, "
     "flags=re.IGNORECASE)",
     "        text = re.sub(rf\"(?<![\\w.-])(?:{names})(?![\\w-])\", SOMEONE, text)"),

    ("a private conversation's distillate is labelled for the room", DISTIL,
     "    return turn_audience(person(project, who), private=True) if who else CLIENT",
     "    return CLIENT"),

    ("a direct distillate lands in the room's folder", DISTIL,
     "    return distillate_path(private=span.private, digest=span.digest,",
     "    return distillate_path(private=False, digest=span.digest,"),

    ("what was distilled is never read back", DISTIL,
     "            if until:\n                out[folder.name] = max(out.get(folder.name, \"\"), "
     "until)",
     "            if False:\n                out[folder.name] = max(out.get(folder.name, \"\"), "
     "until)"),

    ("a pass distils without bound", DISTIL,
     "        if n >= limit or (deadline is not None and clock() > deadline):",
     "        if deadline is not None and clock() > deadline:"),

    ("the documents' pass has a model read a distillate again", INGEST,
     "            and facts.distillate_of(record.path) is None)",
     "            )"),

    ("the documents' pass announces a distillate", INGEST,
     "    if facts.distillate_of(record.path) is not None:\n        return None",
     "    if False:\n        return None"),

    ("the knowledge tick distils nothing", WORKFLOW,
     "        if workflow.patched(\"conversations-distilled\"):",
     "        if False:", TICK),

    ("the worker does not register the distillation", WORKER,
     "    ingest_documents, distil_conversations,\n",
     "    ingest_documents,\n", TICK),

    # ── 4. saved when confirmed ───────────────────────────────────────────────────────────────
    ("a yes the semaphore refused is lost with its proposal", CONFIRM,
     "    if _refused_for_contention(module, before):",
     "    if False:"),

    ("a write the semaphore refused is not counted as refused", MODULE,
     "            outcomes.append(\"refused\")\n            return _could_not(semaphore_busy(",
     "            return _could_not(semaphore_busy("),

    ("a yes that wrote something is staged again", CONFIRM,
     "    return bool(outcomes) and outcomes[0] == \"refused\" and \"written\" not in outcomes",
     "    return \"refused\" in outcomes"),

    ("a decision confirmed is drafted as a requirement instead of written", CONFIRM,
     "    \"decision\": _confirm_decision,\n", ""),
]

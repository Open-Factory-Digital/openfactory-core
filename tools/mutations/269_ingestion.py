"""#269 slice 1 (ingestion: every document in the context repository becomes text plus a record),
proven by breaking it.

SIX CLAIMS, each cut here and each required to go red:

  1. **Once per version.** A version is keyed by `(product, path, digest)` and the record decides:
     a second pass, a pass whose index was lost, a pass racing another and a second registry
     project of the product never read it again — and the size-and-mtime shortcut is taken only
     when both still match. What only a model writes is written once, retried a bounded number of
     times, and never for a text shorter than a summary.
  2. **Never silent.** Every file that cannot be read is a record with its reason — a protected
     PDF, a scanned one with no OCR, an unknown format, a Git LFS pointer, binary wearing a text
     suffix, a file over the limit, a link — and the reason reaches the panel and the role's
     facts.
  3. **Nothing leaves the tree, nothing is executed, nothing is expanded.** A link is recorded and
     not followed; an event cannot name a path above, outside or hidden; the PDF child is handed no
     credential and a clock; XML declares no DTD of its own, and its tree and a compressed page are
     bounded; a script in an e-mail is dropped.
  4. **The audience label is never lost.** A folder's label and the document's own, the narrowest
     winning; nothing declared, or a word nobody knows, is internal — on the record, read back from
     disk, and on an unreadable one. AND AN INTERNAL DOCUMENT IS NAMED ONLY TO WHO MAY READ IT: the
     role's facts and briefing name one only to an engineer or a product admin in private, and
     count it for a room and a client; the panel's route names one only to a credential that may
     read the floor, and counts it for a product credential; the room is never told its name.
  5. **A chart says its content came from an image** — whatever the row that read it said.
  6. **The seam and the ways in.** Rows are chosen by configuration and an add-on's row is built;
     the knowledge pipeline's tick runs the pass after the map, the worker registers it, the
     activity reads the role's own checkout, and the event reads the named file alone and only
     for an admin — and "a document was ingested" reaches the door (#305's
     `events.document_ingested`) where the document was brought, once, never for the backfill,
     never for one that could not be read, and at most a few per pass.

The guards under test: `tests/test_the_documents_are_read.py` (the default), the schedule and
event file beside it, the read model's guard, and the stranger's add-on.
"""

TEST = "tests/test_the_documents_are_read.py"
EVENTS = "tests/test_the_documents_are_read_on_the_schedule_and_on_an_event.py"
READ_MODEL = "tests/test_the_read_model.py"
STRANGER = "tests/test_a_stranger_can_add_an_adapter.py"

INGEST = "openfactory/product/documents/ingest.py"
RECORD = "openfactory/product/documents/record.py"
STORE = "openfactory/product/documents/store.py"
CONTRACT = "openfactory/contracts/document.py"
MARKUP = "openfactory/adapters/extract/markup.py"
TEXT = "openfactory/adapters/extract/text.py"
MAIL = "openfactory/adapters/extract/mail.py"
PDF = "openfactory/adapters/extract/pdf.py"
VISION = "openfactory/adapters/extract/vision.py"
REGISTRY = "openfactory/adapters/extract/registry.py"
MODEL = "openfactory/product/model.py"
FACTS = "openfactory/product/facts.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. once per version ────────────────────────────────────────────────────────────────────
    ("a version already recorded is extracted again on every pass", INGEST,
     "        if store.has(path, found.digest):\n            report.unchanged += 1\n"
     "            if line.get",
     "        if False:\n            report.unchanged += 1\n            if line.get"),

    ("a version another pass finished while this one looked is read a second time", INGEST,
     "            if store.has(path, found.digest):  # another pass finished it while this one "
     "looked",
     "            if False:  # another pass finished it while this one looked"),

    ("two passes take two different locks, so both read the same version", INGEST,
     "            lock.acquire(timeout=0)",
     "            lock = type(lock)(lock.path + \".elsewhere\")\n"
     "            lock.acquire(timeout=0)"),

    ("the shortcut is taken on the size alone, so a file rewritten to the same size is never "
     "read again", INGEST,
     "            and line.get(\"size\") == st.st_size and line.get(\"mtime_ns\") == "
     "st.st_mtime_ns):",
     "            and line.get(\"size\") == st.st_size):"),

    ("an index that outlived its records stands in for them, and the pass writes a record with "
     "no reason", INGEST,
     "        if found is not _MISSING and found.cached and not store.has(path, found.digest):",
     "        if False:"),

    # re-pinned 2026-09-24: a distillate is never read again, a clause of its own after these
    # (#269 slice 3)
    ("a reading that failed is retried for ever", INGEST,
     "            and not record.derived.summary and record.derived.attempts < MODEL_ATTEMPTS\n",
     "            and not record.derived.summary\n"),

    ("a version already summarised is summarised again", INGEST,
     "            and not record.derived.summary and record.derived.attempts < MODEL_ATTEMPTS\n",
     "            and record.derived.attempts < MODEL_ATTEMPTS\n"),

    ("a text shorter than a summary is sent to a model anyway", INGEST,
     "    return (record.readable and len(record.text) >= SUMMARY_MIN_CHARS",
     "    return (record.readable"),

    ("a reading that failed is never retried", INGEST,
     "            if line.get(\"reading\") == \"pending\":",
     "            if False:"),

    # re-pinned 2026-09-24: the announcement goes where `_told_where` says, through #305's door
    ("a new version is never announced — the event's producer has no call site", INGEST,
     "                if announce(project, made, conversation=where):",
     "                if False:"),

    ("the announcement never reaches the door — the producer only logs", INGEST,
     "    told = events.document_ingested(project, name=record.path, conversation=conversation,",
     "    told = bool(project) or events.document_ingested(project, name=record.path, "
     "conversation=conversation,"),

    ("the announcement is said in the room instead of where the document was brought", INGEST,
     "    if brought_to or not scheduled:\n        return brought_to\n",
     "    if brought_to or not scheduled:\n        return \"\"\n"),

    ("the backfill of a product's first reading is announced, file by file", INGEST,
     "    if not first and new:\n        return \"\"\n",
     "    if new:\n        return \"\"\n"),

    ("a pass announces every new document, however many a push brought", INGEST,
     "        if where is not None and whole and report.told >= TOLD_PER_PASS:",
     "        if False:"),

    # re-pinned 2026-09-24: a distillate is nobody's news, said between these (#269 slice 3)
    ("a document that could not be read is announced as read", INGEST,
     "    if not record.readable:\n        return None\n    if facts.distillate_of",
     "    if False:\n        return None\n    if facts.distillate_of"),

    ("the room is told the name of an internal document", INGEST,
     "    if not may_read(record.audience, CLIENT) and not (brought_to and is_private(brought_to)):",
     "    if False:"),

    ("the row does not say whose conversation the document was brought to",
     "openfactory/actions/catalog.py",
     "        conversation=str(getattr(by, \"conversation\", \"\") or \"\"),",
     "        conversation=\"\","),

    # ── 2. never silent ────────────────────────────────────────────────────────────────────────
    ("a file over the limit is read into memory whole", INGEST,
     "                if len(kept) > limit:",
     "                if False:"),

    ("a Git LFS pointer is handed to the PDF row as if it were the PDF", INGEST,
     "    if found.data.startswith(_LFS) and found.size < 1024:",
     "    if False:"),

    ("an unknown format is sent to no row and says nothing a person can act on", INGEST,
     "    if not doc_type:\n",
     "    if False:\n"),

    ("a PDF with no text layer is never handed to OCR", PDF,
     "row=PdfRow.kind, fallback=\"scanned\", pages=total)",
     "row=PdfRow.kind, pages=total)"),

    ("the dispatcher ignores a row's fallback", INGEST,
     "    if first.readable or not first.fallback:",
     "    if True:"),

    ("a protected PDF is parsed undecrypted and reported as a broken one", PDF,
     "            if not opened:\n",
     "            if False:\n"),

    ("with tesseract absent the row does not say OCR is not available", PDF,
     "        if not tesseract:\n",
     "        if False:\n"),

    ("binary data with a text suffix is indexed as text", TEXT,
     "    if b\"\\x00\" in data[:_SNIFF]:",
     "    if False:"),

    ("an illegible image is recorded as a description that says ILLEGIBLE", VISION,
     "        if text.strip().strip(\".\").upper() == ILLEGIBLE or not text:",
     "        if not text:"),

    # re-pinned 2026-09-24: the screen's list is the client's, and the internal one its own
    ("the panel's documents screen shows nothing unreadable", INGEST,
     "           \"unreadable\": listed[True],",
     "           \"unreadable\": [],"),

    ("the panel route answers without the documents", APP,
     "        return {\"project\": proj.name,\n"
     "                **overview(product_key(proj), internal=_reads_the_floor(request))}",
     "        return {\"project\": proj.name}"),

    ("the product page never asks for the documents", PANEL,
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadAgenda();"
     "loadDocuments()}",
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadAgenda()}"),

    ("the product page draws an unreadable document without its reason", PANEL,
     "        <div class=\"sub\">unreadable · ${esc(x.reason)}</div></div>",
     "        <div class=\"sub\">unreadable</div></div>"),

    ("the read model never reads the documents, so the role's facts do not say what could not "
     "be read", MODEL,
     "    model.documents = _documents(model)",
     "    model.documents = None",
     READ_MODEL),

    ("the documents are never rendered into the role's files", MODEL,
     "        files[\"documents.md\"] = _render_documents(model.documents, audience=audience)",
     "        pass",
     READ_MODEL),

    ("the role's file names an unreadable document without why", MODEL,
     "                     f\"{doc.get('audience', '')}; why: {doc.get('reason', '')}\")",
     "                     f\"{doc.get('audience', '')}\")"),

    ("the facts pack refuses to write documents.md", FACTS,
     "MODEL_FILES = (\"now.md\", \"history.md\", \"requirements.md\", \"documents.md\")",
     "MODEL_FILES = (\"now.md\", \"history.md\", \"requirements.md\")",
     READ_MODEL),

    ("a file gone from the repository stays in the index for ever", INGEST,
     "    if whole and not report.left:",
     "    if False:"),

    ("a pass never stops at its budget", INGEST,
     "        if deadline is not None and clock() > deadline:",
     "        if False:"),

    # ── 3. nothing leaves the tree, nothing is executed, nothing is expanded ──────────────────
    ("a link is followed to what it points at", INGEST,
     "        st = os.lstat(full)",
     "        st = os.stat(full)"),

    ("a link to a folder is walked past in silence", INGEST,
     "            if (Path(here) / folder).is_symlink():\n"
     "                found.append((rel / folder).as_posix())\n",
     "            if (Path(here) / folder).is_symlink():\n"),

    ("an event may name a path under a folder that links out of the tree", INGEST,
     "        inside = parent == root.resolve() or parent.is_relative_to(root.resolve())",
     "        inside = True"),

    ("an event may name git's and the platform's own files", INGEST,
     "    if _hidden(spelled):",
     "    if False:"),

    ("a hidden folder is walked like a folder of documents", INGEST,
     "            if folder.startswith(\".\"):\n                continue\n",
     ""),

    ("the PDF child inherits every credential of the deployment", PDF,
     "    return {\"PATH\": os.environ.get(\"PATH\", \"\"), \"PYTHONPATH\": here,",
     "    return {**os.environ, \"PATH\": os.environ.get(\"PATH\", \"\"), \"PYTHONPATH\": here,"),

    ("the PDF child has no clock", PDF,
     "capture_output=True, timeout=self.seconds, env=_child_env(), check=False)",
     "capture_output=True, timeout=None, env=_child_env(), check=False)"),

    ("a document type of its own is admitted", MARKUP,
     "        if has_internal_subset:\n",
     "        if False:\n"),

    ("an XML document may nest without end", MARKUP,
     "        if len(stack) >= MAX_DEPTH:\n",
     "        if False:\n"),

    ("an XML document may hold any number of elements", MARKUP,
     "        if count[0] > MAX_ELEMENTS:\n",
     "        if False:\n"),

    ("a compressed page inflates past its ceiling", MARKUP,
     "    if len(out) > MAX_INFLATED or inflater.unconsumed_tail:",
     "    if False:"),

    ("an HTML label is kept as markup", MARKUP,
     "    if \"<\" in label and \">\" in label:",
     "    if False:"),

    ("a label written on a connector becomes a shape of its own", MARKUP,
     "            edge_labels.setdefault(cell[\"parent\"], []).append(words)",
     "            labels[cell.get(\"id\", \"\")] = words"),

    ("an HTML e-mail's script is kept as words", TEXT,
     "    _SKIP = (\"script\", \"style\", \"head\")",
     "    _SKIP = ()"),

    ("an e-mail's attachments are dropped in silence", MAIL,
     "        notes = [f\"attachment not read here: {part.get_filename() or '(unnamed)'}\"\n"
     "                 for part in message.iter_attachments()]",
     "        notes = []"),

    ("a record is read back from any file under its name", STORE,
     "        if (record.product, record.path, record.digest) != (self.key, path, digest):",
     "        if False:"),

    ("a digest that is a path climbs out of the records", STORE,
     "        if not all(c in \"0123456789abcdef\" for c in digest) or len(digest) != 64:",
     "        if False:"),

    ("a tree inside another repository is dated by that repository's history", RECORD,
     "    if not (Path(root) / \".git\").exists():\n        return \"\"\n",
     ""),

    # ── 4. the audience label is never lost ────────────────────────────────────────────────────
    ("the widest label wins when two disagree", CONTRACT,
     "    return max(known, key=AUDIENCES.index)",
     "    return min(known, key=AUDIENCES.index)"),

    ("a document nobody labelled is the client's", CONTRACT,
     "DEFAULT_AUDIENCE = INTERNAL",
     "DEFAULT_AUDIENCE = CLIENT"),

    ("a record read back with a label nobody knows keeps it", CONTRACT,
     "        return text if text in AUDIENCES else DEFAULT_AUDIENCE",
     "        return text or DEFAULT_AUDIENCE"),

    ("an unreadable record may say nothing about why", CONTRACT,
     "        if not self.readable and not self.reason.strip():",
     "        if False:"),

    ("an `internal/` folder labels nothing", RECORD,
     "            labels.append(INTERNAL)",
     "            labels.append(CLIENT)"),

    ("a label nobody knows is read as the client's", RECORD,
     "            from_text = INTERNAL\n",
     "            from_text = CLIENT\n"),

    ("nothing declared is the client's", RECORD,
     "        return DEFAULT_AUDIENCE, \"default\", notes",
     "        return CLIENT, \"default\", notes"),

    ("the document's own front matter is never read for its audience", TEXT,
     "        declared = fields.get(\"audience\", fields.get(\"visibility\", \"\"))",
     "        declared = \"\""),

    ("the label is decided before the row read the document, and never after", INGEST,
     "    label, label_from, label_notes = facts.audience(path, got.audience)",
     "    label, label_from, label_notes = facts.audience(path)"),

    # ── 4b. an internal document is NAMED only to a reader who may read it ────────────────────
    ("a product credential is handed the internal documents by name", APP,
     "    return _gate_verdict(_A_FLOOR_PATH, _credential_of(request)) is None",
     "    return True"),

    ("the screen lists every unreadable document to everybody, the internal ones among them",
     INGEST,
     "        listed[may_read(label, CLIENT)].append({",
     "        listed[True].append({"),

    ("a reader nobody may show internal documents is shown them anyway", CONTRACT,
     "    return AUDIENCES.index(narrowest(label or DEFAULT_AUDIENCE)) <= AUDIENCES.index(shown)",
     "    return True"),

    ("every turn is an internal reader: a room and a client are shown the internal documents",
     RECORD,
     "    return INTERNAL if private and getattr(person, \"role\", \"\") in (ADMIN, ENGINEER) "
     "else CLIENT",
     "    return INTERNAL"),

    ("a room is a private conversation: an engineer asking in a room is shown them", RECORD,
     "    return INTERNAL if private and getattr(person, \"role\", \"\") in (ADMIN, ENGINEER) "
     "else CLIENT",
     "    return INTERNAL if getattr(person, \"role\", \"\") in (ADMIN, ENGINEER) else CLIENT"),

    ("the turn's audience is never decided, so every turn keeps the client's",
     "openfactory/product/module.py",
     "        self._documents_audience = turn_audience(speaker, private=private)",
     "        self._documents_audience = \"client\""),

    # re-pinned 2026-09-24 (#269 slice 2): the search's scope (`_the_search_scope`) spells the same
    # line, so the anchor carries the read model's own comment above it
    ("a pack another conversation's turn may read is written for the internal reader",
     "openfactory/product/module.py",
     "is written for a client\n"
     "    audience = getattr(module, \"_documents_audience\", CLIENT) if own else CLIENT",
     "is written for a client\n"
     "    audience = getattr(module, \"_documents_audience\", CLIENT)"),

    ("the role's files name every document whatever the turn", MODEL,
     "    listed = [doc for doc in every if may_read(str(doc.get(\"audience\") or \"\"), audience)]",
     "    listed = every"),

    ("the facts are rendered without the turn's audience", "openfactory/product/facts.py",
     "        files.update(render(model, speaker=speaker, audience=audience))",
     "        files.update(render(model, speaker=speaker, audience=\"internal\"))"),

    ("the briefing is rendered for the internal reader whoever asks",
     "openfactory/product/module.py",
     "                                    audience=getattr(module, \"_documents_audience\", CLIENT))",
     "                                    audience=\"internal\")"),

    ("the briefing names nothing about the documents", "openfactory/product/briefing.py",
     "    facts = [*_not_read(model, say), *_documents(model, say, audience),",
     "    facts = [*_not_read(model, say),"),

    ("a turn is not told how many internal documents it is not shown", MODEL,
     "    if withheld:\n        lines += [f\"{withheld} internal document(s)",
     "    if False:\n        lines += [f\"{withheld} internal document(s)"),

    # ── 5. a chart says its content came from an image ─────────────────────────────────────────
    ("an image read by a row that forgot to say so is recorded as exact", INGEST,
     "    from_image = got.from_image or doc_type == \"image\"",
     "    from_image = got.from_image"),

    ("an image's record carries no note that its numbers may be wrong", INGEST,
     "    notes = [*label_notes, *got.notes, *([FROM_AN_IMAGE] if from_image else [])]",
     "    notes = [*label_notes, *got.notes]"),

    # ── 6. the seam and the ways in ────────────────────────────────────────────────────────────
    ("the configuration never chooses a row", REGISTRY,
     "    return configured().get(doc_type) or DEFAULT_ROWS.get(doc_type, \"\")",
     "    return DEFAULT_ROWS.get(doc_type, \"\")"),

    ("an add-on's row is never built", REGISTRY,
     "    builder = EXTRACTORS.get(kind) or plugins.builder(AXIS, kind, builtin=EXTRACTORS)",
     "    builder = EXTRACTORS.get(kind)",
     STRANGER),

    ("the knowledge pipeline's tick never reads the documents",
     "openfactory/runtime/temporal/workflow.py",
     "        if not workflow.patched(\"documents-ingested\"):\n            return refreshed\n",
     "        if True:\n            return refreshed\n",
     EVENTS),

    ("the worker does not register the documents activity",
     "openfactory/runtime/temporal/worker.py",
     # re-pinned 2026-09-24: registered beside the distillation's activity (#269 slice 3)
     "    ingest_documents, distil_conversations,\n",
     "    distil_conversations,\n",
     EVENTS),

    ("the scheduled pass forgets the commit the role's checkout is at",
     "openfactory/runtime/temporal/activities.py",
     "        report = ingest(project, root=Path(ctx.docs_path), commit=ctx.docs_commit, "
     "terms=terms,",
     "        report = ingest(project, root=Path(ctx.docs_path), commit=\"\", terms=terms,",
     EVENTS),

    ("the event reads the whole tree instead of the file it names",
     "openfactory/actions/catalog.py",
     "        paths=wanted or None, terms=[fact.term for fact in ctx.domain.live()],",
     "        paths=None, terms=[fact.term for fact in ctx.domain.live()],",
     EVENTS),

    ("anybody who may read the product may make it spend on reading its documents",
     "openfactory/actions/catalog.py",
     "            name=\"product_ingest\",\n            scope=PRODUCT,",
     "            name=\"product_ingest\",\n            needs_admin=False,\n            scope=PRODUCT,",
     EVENTS),
]

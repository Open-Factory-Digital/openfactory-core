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
     disk, and on an unreadable one.
  5. **A chart says its content came from an image** — whatever the row that read it said.
  6. **The seam and the ways in.** Rows are chosen by configuration and an add-on's row is built;
     the knowledge pipeline's tick runs the pass after the map, the worker registers it, the
     activity reads the role's own checkout, and the event reads the named file alone and only
     for an admin.

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

    ("a reading that failed is retried for ever", INGEST,
     "            and not record.derived.summary and record.derived.attempts < MODEL_ATTEMPTS)",
     "            and not record.derived.summary)"),

    ("a version already summarised is summarised again", INGEST,
     "            and not record.derived.summary and record.derived.attempts < MODEL_ATTEMPTS)",
     "            and record.derived.attempts < MODEL_ATTEMPTS)"),

    ("a text shorter than a summary is sent to a model anyway", INGEST,
     "    return (record.readable and len(record.text) >= SUMMARY_MIN_CHARS",
     "    return (record.readable"),

    ("a reading that failed is never retried", INGEST,
     "            if line.get(\"reading\") == \"pending\":",
     "            if False:"),

    ("a new version is never announced — the event's producer has no call site", INGEST,
     "            announce(project, made)",
     "            pass"),

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

    ("the panel's documents screen shows nothing unreadable", INGEST,
     "            \"unreadable\": unreadable}",
     "            \"unreadable\": []}"),

    ("the panel route answers without the documents", APP,
     "        return {\"project\": proj.name, **overview(product_key(proj))}",
     "        return {\"project\": proj.name}"),

    ("the product page never asks for the documents", PANEL,
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements();loadDocuments()}",
     "  if(_prod.project){paintScope();loadProductStatus();loadRequirements()}"),

    ("the product page draws an unreadable document without its reason", PANEL,
     "        <div class=\"sub\">unreadable · ${esc(x.reason)}</div></div>",
     "        <div class=\"sub\">unreadable</div></div>"),

    ("the read model never reads the documents, so the role's facts do not say what could not "
     "be read", MODEL,
     "    model.documents = _documents(model)",
     "    model.documents = None",
     READ_MODEL),

    ("the documents are never rendered into the role's files", MODEL,
     "        files[\"documents.md\"] = _render_documents(model.documents)",
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
     "    # #269 — the product's documents, read on the knowledge refresh's own tick\n"
     "    ingest_documents,\n",
     "",
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

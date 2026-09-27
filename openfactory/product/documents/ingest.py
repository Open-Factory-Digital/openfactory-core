"""Every document in a product's context repository becomes normalised text plus a record — one
file at a time, once per version (#269 slice 1, ADR-0053 "The guardian's memory").

ONE ENTRY POINT, TWO WAYS IN. `ingest(project, root=…)` compares the whole tree with what was
recorded and reads only what changed: the knowledge pipeline's schedule runs it
(`KnowledgeRefreshWorkflow`). `ingest(project, root=…, paths=[…])` reads exactly the files named:
the EVENT, "this file was added or changed" — the `product_ingest` row today, the panel's upload
and a push to the context repository when they exist (#269 point 10). Either way a file is read
alone, and a version already recorded is never read again: records are keyed by
`(product, path, digest)` and the record's existence is the answer (`store.py`).

WHAT HAPPENS TO ONE FILE, in order, each step able to stop it with a reason:

  1. it is ADMITTED: a relative path inside the repository, not hidden (`.git/`, `.openfactory/`,
     `.okf/` are git's and the platform's own), never a symbolic link — a link is recorded as
     unreadable and not followed, so no read leaves the tree; the file is opened with
     `O_NOFOLLOW` and checked to be a regular file on the handle it is read from;
  2. it is HASHED as it is read, and read into memory only up to the size limit — a file over it is
     recorded as too large, with its size, and never handed to a row;
  3. its TYPE is read off its name and its ROW chosen by configuration (`adapters/extract/
     registry.py`); a Git LFS pointer, an unknown format, a row that cannot be built or that fails
     are each recorded as unreadable with their reason;
  4. the row's text is CUT at `MAX_TEXT_CHARS`, and what can be read without a model is read
     (`record.py`); its AUDIENCE is the narrowest of its path's and its own (`record.py`);
  5. what needs a MODEL — the summary, the decisions — is written once, now (`reading.py`);
  6. the record is written, and the event "a document was ingested" is PRODUCED (`announce`).

NEVER SILENT (#269 point 8). Every file the tree holds ends as a record, readable or not, and an
unreadable one carries its reason to the panel and to the role's facts (`overview`). "Could not
read" never becomes "nothing there".

BOUNDED. A pass may be handed a time budget; what it did not reach is counted in `left` and read by
the next pass, so the first reading of a product with years of documents spreads over several
passes instead of holding one activity for hours.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from openfactory.contracts.document import CLIENT, DEFAULT_AUDIENCE, DocumentRecord, may_read
from openfactory.product.documents import record as facts
from openfactory.product.documents.reading import ModelReader, Reader
from openfactory.product.documents.store import Store
from openfactory.util.filelock import Waited

log = logging.getLogger("openfactory.product.documents")

#: The deployment's size limit, in bytes, and its default. A file over it is recorded, not read.
MAX_BYTES_ENV = "OPENFACTORY_DOCUMENTS_MAX_BYTES"
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
#: The longest normalised text a record keeps; the rest is named in its notes.
MAX_TEXT_CHARS = 2_000_000
#: A text shorter than this is its own summary — no model is asked to shorten it.
SUMMARY_MIN_CHARS = 280
#: How many times the model step is tried for one version, across passes.
MODEL_ATTEMPTS = 3
#: How often a long pass writes the index down — so a pass stopped half-way keeps its progress.
INDEX_EVERY = 50

#: What a Git LFS pointer starts with: the file's content was never fetched into the checkout.
# vendor-url-ok: the pointer format's own first line, compared with a file, never fetched
_LFS = b"version https://git-lfs.github.com/spec/v1"

#: The note on every record whose content came from an image — the weakest case, said on the
#: record itself (#269, "What happens when someone drops a PDF or a chart").
FROM_AN_IMAGE = ("its content was read from an image — the message is understood, but an exact "
                 "number read off the picture may be wrong; the source data placed beside it "
                 "makes the numbers exact")


def max_bytes() -> int:
    raw = (os.environ.get(MAX_BYTES_ENV) or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_MAX_BYTES
    except ValueError:
        log.error("%s=%r is not a number of bytes — using %d", MAX_BYTES_ENV, raw,
                  DEFAULT_MAX_BYTES)
        return DEFAULT_MAX_BYTES
    return value if value > 0 else DEFAULT_MAX_BYTES


@dataclass
class Report:
    """What one pass did, per path — the activity's line and the row's answer."""

    product: str
    ingested: list[str] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)
    unchanged: int = 0
    reread: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)
    left: int = 0
    #: how many were said in a conversation, and how many more the pass's bound kept to the log
    told: int = 0
    untold: int = 0

    def sentence(self) -> str:
        said = [f"{len(self.ingested)} new version(s) recorded"]
        if self.unreadable:
            said.append(f"{len(self.unreadable)} of them unreadable")
        said.append(f"{self.unchanged} unchanged")
        if self.reread:
            said.append(f"{len(self.reread)} summarised again")
        if self.removed:
            said.append(f"{len(self.removed)} gone from the repository")
        if self.refused:
            said.append(f"{len(self.refused)} refused ("
                        + "; ".join(f"{p}: {why}" for p, why in self.refused[:3]) + ")")
        if self.busy:
            said.append(f"{len(self.busy)} being read by another pass")
        if self.left:
            said.append(f"{self.left} left for the next pass")
        if self.told:
            said.append(f"{self.told} announced")
        if self.untold:
            said.append(f"{self.untold} more new not announced — a pass tells at most "
                        f"{TOLD_PER_PASS}")
        return ", ".join(said)


# ── the event ───────────────────────────────────────────────────────────────────────────────────

def announce(project, record: DocumentRecord, *, conversation: str = "") -> bool:
    """THE PRODUCER OF "A DOCUMENT WAS INGESTED" (ADR-0052 D11): `events.document_ingested`, which
    says it through the door — to `conversation`, where the document was brought, else the
    product's room — once per version (its id is the record's `(product, path, digest)`).
    Returns whether it was told. WHICH documents are told, and where, is `_told_where`'s."""
    from openfactory.product import events

    told = events.document_ingested(project, name=record.path, conversation=conversation,
                                    key=f"{record.product}|{record.path}|{record.digest}")
    log.info("OPENFACTORY_DOCUMENT_INGESTED product=%s path=%s digest=%s told=%s", record.product,
             record.path, record.digest[:12], "yes" if told else "no")
    return told


#: How many NEW documents one scheduled pass tells the room about. A push of two hundred files is
#: news; two hundred messages in a room are noise nobody reads — the rest are counted in the log.
TOLD_PER_PASS = 5


def _told_where(record: DocumentRecord, *, brought_to: str, scheduled: bool, first: bool,
                new: bool) -> str | None:
    """Where "a document was ingested" is said for `record` — a conversation key, "" for the
    product's room — or None when it is said nowhere.

    ONLY WHAT WAS READ: "I have read the new document" over one that could not be read would be
    false; that one is on the panel and in the role's `documents.md`, with why.

    WHERE IT WAS BROUGHT, WHEN SOMEBODY BROUGHT IT: that person's conversation — and the room
    for a file an event named with nobody's conversation (a script after a push), as
    `events.document_ingested` routes it.

    EVERY DOCUMENT IS NEWS WHERE ANY DOCUMENT IS: whoever talks to the role may read everything
    the product exposes (the product owner's decision of 2026-09-25), so an internal document is
    told in the room as a client's is. And on the schedule only a NEW document is news — not a
    product's first reading, which is a backfill, nor a new version of a known one."""

    if not record.readable:
        return None
    if facts.distillate_of(record.path) is not None:
        return None  # the platform's own reading of a conversation is nobody's news (#269 slice 3)
    if brought_to or not scheduled:
        return brought_to
    if not first and new:
        return ""
    return None


# ── the tree ────────────────────────────────────────────────────────────────────────────────────

def _hidden(path: PurePosixPath) -> bool:
    return any(part.startswith(".") for part in path.parts)


def documents_in(root: Path) -> list[str]:
    """Every document under `root`, `/`-spelled and sorted — a symbolic link included (it is
    recorded as unreadable, never followed), a hidden file or folder never (git's, the
    platform's, a tool's own)."""
    found: list[str] = []
    for here, folders, files in os.walk(root, followlinks=False):
        rel = Path(here).relative_to(root)
        keep = []
        for folder in folders:
            if folder.startswith("."):
                continue
            if (Path(here) / folder).is_symlink():
                found.append((rel / folder).as_posix())
                continue
            keep.append(folder)
        folders[:] = sorted(keep)
        found += [(rel / name).as_posix() for name in files if not name.startswith(".")]
    return sorted(found)


def admitted(root: Path, path: str) -> tuple[str, str]:
    """`(path, "")` in `/` spelling — or `("", why)` for a path an event may not name: absolute,
    climbing out, hidden, or under a folder that is a link out of the tree."""
    spelled = PurePosixPath(str(path or "").replace("\\", "/").strip())
    if (not spelled.parts or spelled.is_absolute() or ".." in spelled.parts
            or str(spelled) == "."):
        return "", "not a path inside the context repository"
    if _hidden(spelled):
        return "", "a hidden path — git's or the platform's own, not a document"
    try:
        if stat.S_ISDIR(os.lstat(root / spelled).st_mode):
            return "", "a folder — name the documents in it"
    except OSError:
        pass  # absent: the pass records it as gone
    try:
        parent = (root / spelled).parent.resolve()
        inside = parent == root.resolve() or parent.is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        inside = False
    if not inside:
        return "", "it leaves the context repository"
    return spelled.as_posix(), ""


@dataclass
class _Read:
    """One file as it was found: its version, and its bytes when they may be handed to a row.
    `cached` is a version taken from the index because the file's size and mtime have not moved
    since — its bytes were not read."""

    digest: str
    size: int
    mtime_ns: int
    data: bytes | None = None
    why: str = ""
    cached: bool = False


_MISSING = object()


def _look(root: Path, path: str, limit: int, line: dict | None = None):
    """`_Read`, or `_MISSING` when the path holds nothing. Never follows a link, never reads past
    `limit` into memory, never reads a file that is not a regular one.

    With the index's `line` for the path, a regular file whose size and mtime are the ones it
    recorded is taken to hold the version it recorded, unread — the same check a version control
    index makes before it hashes a file again."""
    full = root / path
    try:
        st = os.lstat(full)
    except FileNotFoundError:
        return _MISSING
    if (line and stat.S_ISREG(st.st_mode) and line.get("digest")
            and line.get("size") == st.st_size and line.get("mtime_ns") == st.st_mtime_ns):
        return _Read(digest=str(line["digest"]), size=st.st_size, mtime_ns=st.st_mtime_ns,
                     cached=True)
    if stat.S_ISDIR(st.st_mode):
        return _Read(digest=hashlib.sha256(b"folder").hexdigest(), size=0,
                     mtime_ns=st.st_mtime_ns, why="a folder, not a document")
    if stat.S_ISLNK(st.st_mode):
        target = os.readlink(full)
        return _Read(digest=hashlib.sha256(f"link:{target}".encode()).hexdigest(), size=0,
                     mtime_ns=st.st_mtime_ns,
                     why="a symbolic link — it is not followed, so no read leaves the "
                         "context repository")
    if not stat.S_ISREG(st.st_mode):
        return _Read(digest=hashlib.sha256(f"special:{st.st_mode}".encode()).hexdigest(),
                     size=0, mtime_ns=st.st_mtime_ns, why="not a regular file")
    try:
        fd = os.open(full, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        # unreadable to this process, or swapped for a link since it was looked at — a reason,
        # keyed by what was seen, so it is said once per version and never read through a link
        seen = f"unopened:{st.st_size}:{st.st_mtime_ns}".encode()
        return _Read(digest=hashlib.sha256(seen).hexdigest(), size=st.st_size,
                     mtime_ns=st.st_mtime_ns,
                     why=f"it could not be opened ({exc.strerror or type(exc).__name__})")
    with os.fdopen(fd, "rb") as handle:
        held = os.fstat(handle.fileno())
        if not stat.S_ISREG(held.st_mode):
            return _Read(digest=hashlib.sha256(b"special").hexdigest(), size=0,
                         mtime_ns=held.st_mtime_ns, why="not a regular file")
        digest = hashlib.sha256()
        kept: bytearray | None = bytearray()
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            if kept is not None:
                kept += chunk
                if len(kept) > limit:
                    kept = None
        size = held.st_size
    if kept is None:
        return _Read(digest=digest.hexdigest(), size=size, mtime_ns=held.st_mtime_ns,
                     why=f"larger than the {limit // (1024 * 1024) or limit} "
                         f"{'MB' if limit >= 1024 * 1024 else 'bytes'} this deployment reads "
                         f"({size} bytes) — it was not read")
    return _Read(digest=digest.hexdigest(), size=size, mtime_ns=held.st_mtime_ns,
                 data=bytes(kept))


# ── one file ────────────────────────────────────────────────────────────────────────────────────

class _Rows:
    """The rows of one pass, built once each — or the reason one could not be."""

    def __init__(self, project) -> None:
        self.project = project
        self._built: dict[str, Any] = {}

    def extract(self, doc_type: str, source):
        from openfactory.adapters.extract.base import unreadable
        from openfactory.adapters.extract.registry import build_extractor, row_for

        kind = row_for(doc_type)
        if not kind:
            return unreadable(f"no row reads {doc_type} documents on this deployment")
        if kind not in self._built:
            try:
                self._built[kind] = build_extractor(kind, project=self.project)
            except Exception as exc:  # noqa: BLE001 — a row that cannot be built is a reason
                self._built[kind] = exc
        row = self._built[kind]
        if isinstance(row, Exception):
            return unreadable(f"the row configured for {doc_type} documents cannot be built "
                              f"({row})", row=kind)
        try:
            out = row.extract(source.model_copy(update={"type": doc_type}))
        except Exception as exc:  # noqa: BLE001 — a row that raised is recorded, never fatal
            log.warning("the %s row raised on %s", kind, source.path, exc_info=True)
            return unreadable(f"the {kind} row failed ({type(exc).__name__}: "
                              f"{str(exc)[:200]})", row=kind)
        return out if out.row else out.model_copy(update={"row": kind})


def _extract(rows: _Rows, doc_type: str, source):
    """The row's reading — and, for one that found nothing and names where to go next, that
    type's row, once."""
    first = rows.extract(doc_type, source)
    if first.readable or not first.fallback:
        return first
    second = rows.extract(first.fallback, source)
    if second.readable:
        return second.model_copy(update={"notes": [first.reason, *second.notes]})
    return second.model_copy(update={"reason": f"{first.reason}; {second.reason}",
                                     "pages": second.pages or first.pages})


def _cut(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    return text[:MAX_TEXT_CHARS], True


def _unreadable_record(base: dict, why: str, *, notes=()) -> DocumentRecord:
    return DocumentRecord(**base, readable=False, reason=why, notes=list(notes))


def _record(project, key: str, root: Path, path: str, found: _Read, *, rows: _Rows,
            commit: str, now: str, terms: list[str]) -> DocumentRecord:
    """One version's record — everything but the model's part. Never raises for the document."""
    from openfactory.adapters.extract.base import Source
    from openfactory.adapters.extract.registry import document_type

    doc_type = document_type(path)
    label, label_from, label_notes = facts.audience(path)
    base = dict(product=key, path=path, digest=found.digest, size=found.size, commit=commit,
                ingested_at=now, type=doc_type, audience=label, audience_from=label_from,
                area=facts.area(path), title=PurePosixPath(path).stem)
    if found.data is None:
        return _unreadable_record(base, found.why, notes=label_notes)
    if found.data.startswith(_LFS) and found.size < 1024:
        return _unreadable_record(base, "a Git LFS pointer — the file's content was never "
                                        "fetched into this checkout (`git lfs pull`)",
                                  notes=label_notes)
    if not doc_type:
        suffix = PurePosixPath(path).suffix.lower()
        return _unreadable_record(base, f"an unknown format ({suffix or 'no suffix'}) — no row "
                                        f"reads it", notes=label_notes)
    got = _extract(rows, doc_type, Source(path=path, type=doc_type, data=found.data,
                                          digest=found.digest))
    label, label_from, label_notes = facts.audience(path, got.audience)
    # AN IMAGE IS READ FROM AN IMAGE WHATEVER THE ROW SAYS: a stranger's vision row that forgot to
    # say so does not make a chart's numbers exact.
    from_image = got.from_image or doc_type == "image"
    base.update(audience=label, audience_from=label_from, row=got.row, from_image=from_image,
                pages=got.pages)
    if not got.readable:
        return _unreadable_record(base, got.reason, notes=[*label_notes, *got.notes])
    text, truncated = _cut(got.text)
    notes = [*label_notes, *got.notes, *([FROM_AN_IMAGE] if from_image else [])]
    if truncated:
        notes.append(f"its text was cut at {MAX_TEXT_CHARS} characters")
    date, date_from = got.date, got.date_from
    if not date:
        date, date_from = facts.file_name_date(path), "file name"
    if not date:
        date, date_from = facts.commit_date(root, path), "commit"
    return DocumentRecord(
        **{**base, "title": got.title or base["title"]}, readable=True, text=text,
        truncated=truncated, date=date, date_from=date_from if date else "",
        authors=got.authors, entities=facts.entities(text, terms),
        requirements=facts.requirements_cited(text), cards=facts.cards_cited(text), notes=notes,
        derived={"text": bool(got.model), "by": got.model})


def _needs_reading(record: DocumentRecord) -> bool:
    """Whether a model still owes this version its summary and its decisions. Never for a
    conversation's distillate (#269 slice 3): it IS a model's reading, and a reading of a reading
    would cost a model call to say less."""
    return (record.readable and len(record.text) >= SUMMARY_MIN_CHARS
            and not record.derived.summary and record.derived.attempts < MODEL_ATTEMPTS
            and facts.distillate_of(record.path) is None)


def _read_with_model(record: DocumentRecord, reader: Reader) -> DocumentRecord:
    """The record with the model's part written — or with why it was not, and one attempt more.

    `derived.by` names every model that wrote into the record: the vision row's, when the text
    itself is a model's, and the reader's."""
    try:
        reading = reader.read(record)
        error = reading.error
    except Exception as exc:  # noqa: BLE001 — a reader that raised is a reading that failed
        log.warning("the reading of %s raised", record.path, exc_info=True)
        reading, error = None, f"{type(exc).__name__}: {str(exc)[:200]}"
    derived = record.derived.model_copy(update={"attempts": record.derived.attempts + 1})
    if reading is None or error:
        return record.model_copy(update={"derived": derived.model_copy(update={"error": error})})
    writers = [w for w in (derived.by if derived.text else "", reading.by) if w]
    return record.model_copy(update={
        "summary": reading.summary, "decisions": reading.decisions,
        "derived": derived.model_copy(update={
            "summary": True, "decisions": True, "error": "",
            "by": "; ".join(dict.fromkeys(writers))})})


def _entry(record: DocumentRecord, found: _Read) -> dict:
    """The index's line for a path: its version and what the panel shows of it."""
    return {"digest": record.digest, "size": found.size, "mtime_ns": found.mtime_ns,
            "type": record.type, "audience": record.audience, "readable": record.readable,
            "reason": record.reason, "title": record.title,
            "reading": "pending" if _needs_reading(record) else ""}


# ── the pass ────────────────────────────────────────────────────────────────────────────────────

def ingest(project, *, root: Path, paths: Iterable[str] | None = None, commit: str = "",
           terms: Iterable[str] = (), reader: Reader | None = None,
           announce: Callable[..., bool] = announce, conversation: str = "",
           budget_seconds: float | None = None, clock: Callable[[], float] = time.monotonic,
           store: Store | None = None) -> Report:
    """Read what changed in `project`'s context repository checked out at `root` — the whole tree
    compared with the records, or exactly `paths` (the event). Never raises for a document.

    `conversation` is where the documents were BROUGHT — the conversation of the person who asked
    for them to be read — and where "a document was ingested" is said (`_told_where`)."""
    from openfactory.product.key import product_key

    root = Path(root)
    key = product_key(project)
    store = store or Store(key)
    report = Report(product=key)
    try:
        known = store.index()["paths"]
    except (OSError, ValueError) as exc:
        log.warning("[%s] the document index could not be read (%s) — every file is hashed "
                    "again; nothing is extracted twice, the records decide that", key, exc)
        known = {}
    whole = paths is None
    if whole:
        wanted = documents_in(root)
    else:
        wanted = []
        for asked in paths or ():
            path, why = admitted(root, asked)
            if why:
                report.refused.append((str(asked), why))
            elif path not in wanted:
                wanted.append(path)
    reader = reader or ModelReader(project=project)
    rows = _Rows(project)
    terms = [str(t) for t in terms]
    limit = max_bytes()
    deadline = None if budget_seconds is None else clock() + budget_seconds
    now = datetime.now(UTC).isoformat(timespec="seconds")
    changed: dict[str, dict] = {}
    removed: list[str] = []

    def flush() -> None:
        store.update_index(dict(changed), removed=list(removed), checked_at=now, commit=commit)
        changed.clear()
        removed.clear()

    for number, path in enumerate(wanted):
        if deadline is not None and clock() > deadline:
            report.left = len(wanted) - number
            break
        line = known.get(path) or {}
        found = _look(root, path, limit, line)
        if found is not _MISSING and found.cached and not store.has(path, found.digest):
            found = _look(root, path, limit)  # the index outlived its record: read the file again
        if found is _MISSING:
            if path in known:
                removed.append(path)
                report.removed.append(path)
            elif not whole:
                report.refused.append((path, "there is no such file in the context repository"))
            continue
        if store.has(path, found.digest):
            report.unchanged += 1
            if line.get("reading") == "pending":
                _reread(project, store, path, found, reader, report, changed)
            elif line.get("digest") != found.digest or line.get("mtime_ns") != found.mtime_ns:
                kept = store.get(path, found.digest)
                if kept is not None:
                    changed[path] = _entry(kept, found)
            continue
        lock = store.version_lock(path, found.digest)
        try:
            lock.acquire(timeout=0)
        except Waited:
            report.busy.append(path)
            continue
        try:
            if store.has(path, found.digest):  # another pass finished it while this one looked
                report.unchanged += 1
                continue
            made = _record(project, key, root, path, found, rows=rows, commit=commit, now=now,
                           terms=terms)
            if _needs_reading(made):
                made = _read_with_model(made, reader)
            store.put(made)
        finally:
            lock.release()
        report.ingested.append(path)
        if not made.readable:
            report.unreadable.append((path, made.reason))
        changed[path] = _entry(made, found)
        where = _told_where(made, brought_to=conversation, scheduled=whole, first=not known,
                            new=path not in known)
        if where is not None and whole and report.told >= TOLD_PER_PASS:
            report.untold += 1
        elif where is not None:
            try:
                if announce(project, made, conversation=where):
                    report.told += 1
            except Exception:  # noqa: BLE001 — the record is written; only the telling failed
                log.warning("[%s] could not announce %s", key, path, exc_info=True)
        if len(changed) >= INDEX_EVERY:
            flush()
    if whole and not report.left:
        seen = set(wanted)
        for path in known:
            if path not in seen:
                removed.append(path)
                report.removed.append(path)
    flush()
    log.info("OPENFACTORY_DOCUMENTS_PASS product=%s %s", key, report.sentence())
    return report


def _reread(project, store: Store, path: str, found: _Read, reader: Reader, report: Report,
            changed: dict) -> None:
    """The model step again for a version whose reading failed — the text is not extracted again."""
    lock = store.version_lock(path, found.digest)
    try:
        lock.acquire(timeout=0)
    except Waited:
        report.busy.append(path)
        return
    try:
        kept = store.get(path, found.digest)
        if kept is None:
            return
        if _needs_reading(kept):
            kept = _read_with_model(kept, reader)
            store.put(kept)
            report.reread.append(path)
        changed[path] = _entry(kept, found)
    finally:
        lock.release()


# ── what the panel and the role are shown ───────────────────────────────────────────────────────

#: How many readable documents the overview lists — a page, not an export.
MAX_LISTED = 500


def overview(key: str, *, internal: bool = False, store: Store | None = None) -> dict:
    """What the panel shows about a product's documents, and what the role's facts carry — ONE
    read for both (#267's read model): how many were read, and every one that could not be, with
    its type, its audience and why. Raises when the index cannot be read: the caller says so,
    never "no documents".

    THE INTERNAL ONES ARE A LIST OF THEIR OWN, AND ONLY WHEN ASKED FOR. `unreadable` is the
    client's documents — anybody who reads this may be shown them; `unreadable_internal` is there
    only for a reader who may see internal documents (`internal=True`: a floor credential, or the
    read model, whose files are filtered per turn — `model._render_documents`), and everybody
    else is handed `internal_withheld`, a count and nothing else: a document's name is content."""
    index = (store or Store(key)).index()
    lines = index.get("paths") or {}
    listed: dict[bool, list[dict]] = {True: [], False: []}
    # THE DOCUMENTS THEMSELVES, not only the ones that failed (#335): the product owner's page
    # lists what the role reads, by the same audience rule — an internal one only to a reader
    # who may see it, since its name is content
    readable: dict[bool, list[dict]] = {True: [], False: []}
    for path, line in sorted(lines.items()):
        if line.get("readable"):
            label = line.get("audience") or DEFAULT_AUDIENCE
            readable[may_read(label, CLIENT)].append({
                "path": path, "title": str(line.get("title") or ""),
                "type": line.get("type") or "", "audience": label})
            continue
        label = line.get("audience") or DEFAULT_AUDIENCE
        listed[may_read(label, CLIENT)].append({
            "path": path, "type": line.get("type") or "unknown format", "audience": label,
            "reason": line.get("reason") or "no reason was recorded"})
    out = {"product": key, "checked_at": index.get("checked_at"),
           "read": sum(1 for line in lines.values() if line.get("readable")),
           "documents": readable[True][:MAX_LISTED],
           "listed_all": len(readable[True]) + (len(readable[False]) if internal else 0)
                         <= MAX_LISTED,
           "unreadable": listed[True],
           "internal_withheld": 0 if internal else len(listed[False])}
    if internal:
        out["unreadable_internal"] = listed[False]
        out["documents_internal"] = readable[False][:MAX_LISTED]
    return out

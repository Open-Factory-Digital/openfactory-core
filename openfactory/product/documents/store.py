"""Where a product's document records live (#269 slice 1).

UNDER THE PRODUCT'S STATE DIRECTORY, `<product_state_dir>/documents/` (`paths.py`). Three reasons,
each the one that directory already exists for:

  - KEYED BY PRODUCT, NEVER BY REGISTRY PROJECT (#266 decision 1): two registry projects of one
    context repository read one set of documents, so they share one set of records — kept per
    registry project, the second would read every PDF again;
  - SHARED BY THE WORKER AND THE PANEL: compose mounts the deployment's journal root into both, so
    the pass that writes a record on the worker and the panel that shows it unreadable read one
    directory;
  - DERIVED STATE, BESIDE THE OTHER DERIVED STATE: nothing here is the only copy of anything.
    Delete the directory and the next pass reads the repository again — raw is sacred, derived is
    disposable (ADR-0024).

TWO THINGS ARE KEPT, AND ONLY ONE IS THE TRUTH:

    records/<path key>/<digest>.json   one DocumentRecord per version — written once, never edited
                                       but for the model step's retry; the key is (path, digest)
                                       inside the product's directory, so (product, path, digest)
    index.json                         what the tree looked like at the last pass: per path, the
                                       version it held and what the panel shows of it. A shortcut
                                       — "has this path changed since?" answered from its size
                                       and mtime — and rebuilt by the next pass when it is lost.

"Has this version been extracted?" is answered by the RECORD existing, never by the index: a pass
killed between the two leaves a record and no index line, and the next pass finds the record and
extracts nothing.

EVERY WRITE IS ATOMIC, AND EACH VERSION HAS ITS OWN LOCK (`util/filelock.py`). Two passes at once —
the schedule and an event — never extract the same version twice: the second finds the lock held,
or finds the record the first wrote, and moves on. The index is read, merged and replaced under a
lock of its own, so two passes never lose each other's lines.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from openfactory.contracts.document import DocumentRecord
from openfactory.util.filelock import lock_beside, replace_atomically

log = logging.getLogger("openfactory.product.documents")

DIRNAME = "documents"
RECORDS = "records"
INDEX = "index.json"

#: How long a pass waits for the index's lock — a merge and a write, never a model call.
INDEX_WAIT_SECONDS = 30.0


def documents_dir(key: str) -> Path:
    from openfactory.paths import product_state_dir

    return product_state_dir(key) / DIRNAME


def path_key(path: str) -> str:
    """A path in a spelling a directory name can carry — a digest of the EXACT path, so two paths
    that read alike never share a directory, and no path can climb out of `records/`."""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]


class Store:
    """One product's records and index."""

    def __init__(self, key: str, *, root: Path | None = None) -> None:
        self.key = key
        self.root = Path(root) if root is not None else documents_dir(key)

    # ── records ─────────────────────────────────────────────────────────────────────────────

    def record_path(self, path: str, digest: str) -> Path:
        if not all(c in "0123456789abcdef" for c in digest) or len(digest) != 64:
            raise ValueError(f"{digest!r} is not a SHA-256 digest")
        return self.root / RECORDS / path_key(path) / f"{digest}.json"

    def has(self, path: str, digest: str) -> bool:
        return self.record_path(path, digest).is_file()

    def get(self, path: str, digest: str) -> DocumentRecord | None:
        """The record of this version, or None — also for a file that is not this version's
        record (another product's, another path's): a record is read back only as what it claims
        to be."""
        where = self.record_path(path, digest)
        try:
            record = DocumentRecord.model_validate_json(where.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log.warning("the document record %s could not be read (%s) — it is read again from "
                        "the repository", where, exc)
            return None
        if (record.product, record.path, record.digest) != (self.key, path, digest):
            log.warning("the document record %s is not %s@%s of %s — ignored", where, path,
                        digest[:12], self.key)
            return None
        return record

    def put(self, record: DocumentRecord) -> None:
        if record.product != self.key:
            raise ValueError(f"a record of {record.product!r} was handed the store of {self.key!r}")
        replace_atomically(self.record_path(record.path, record.digest),
                           record.model_dump_json(indent=1))

    def version_lock(self, path: str, digest: str):
        return lock_beside(self.record_path(path, digest))

    # ── the index ───────────────────────────────────────────────────────────────────────────

    def index(self) -> dict:
        """`{"checked_at", "commit", "paths": {path: entry}}` — empty before the first pass.
        Raises `OSError`/`ValueError` for one that cannot be read: an unreadable index is a gap
        the caller says, never "no documents"."""
        where = self.root / INDEX
        try:
            data = json.loads(where.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"checked_at": None, "commit": "", "paths": {}}
        if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
            raise ValueError(f"{where} is not a document index")
        return data

    def update_index(self, changed: dict[str, dict], *, removed=(), checked_at: str,
                     commit: str = "") -> None:
        """Merge `changed` into the index and drop `removed`, under the index's lock — the index
        re-read inside it, so another pass's lines written meanwhile are kept."""
        where = self.root / INDEX
        with lock_beside(where).held(timeout=INDEX_WAIT_SECONDS):
            try:
                data = self.index()
            except (OSError, ValueError) as exc:
                log.warning("the document index of %s could not be read (%s) — it is rebuilt "
                            "from this pass", self.key, exc)
                data = {"checked_at": None, "commit": "", "paths": {}}
            paths = data["paths"]
            paths.update(changed)
            for path in removed:
                paths.pop(path, None)
            data.update(checked_at=checked_at, commit=commit or data.get("commit", ""),
                        product=self.key)
            replace_atomically(where, json.dumps(data, ensure_ascii=False, sort_keys=True))

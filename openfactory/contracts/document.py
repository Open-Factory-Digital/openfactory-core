"""The record of one version of one document in a product's context repository (#269 slice 1,
ADR-0053 "The guardian's memory") — the contract slice 2's index is built from.

RAW IS SACRED, DERIVED IS DISPOSABLE (ADR-0024). The document is the raw: it stays in the context
repository, versioned, exactly as somebody put it there. This record is derived from it — the
normalised text and what can be said about it — and can be thrown away and rebuilt at any time
from the repository. Nothing here is ever the only copy of anything.

ONE RECORD PER VERSION, KEYED BY `(product, path, digest)`. `digest` is the SHA-256 of the file's
bytes, so the same bytes at the same path are one record however many times they are seen, and an
edit is a new record beside the old one — the old version stays readable, which is what lets the
index answer "what did this say in March" (#269 point 2: time is data).

WHAT A MODEL WROTE IS MARKED, FIELD BY FIELD. Everything a parser can read is read without one:
the date, the authors, the type, the area, the entities, the requirements and cards the text
cites. What needs a model — the summary and the decisions the document mentions, and the whole
text of an image described by a vision model — is generated once per version, never per
question, and `derived` says which fields came from a model and which model. A reader that cannot
tell "the document says" from "a model said the document says" cites the second as the first.

THE AUDIENCE LABEL IS NEVER LOST (#266 decision 8, #269 point 7). Every record carries one, an
unreadable record included, and a record read back with a label this contract does not know — or
none — is `internal`: "could not tell" never becomes "a client may read it". And what is SHOWN
of a document is decided by it (`may_read`): its name is content ("plano-de-demissoes.pdf"), so
the role's facts, its briefing and the panel's documents screen list an internal document only
to a reader of that audience, and count it for everybody else. What the role may say from a
document's TEXT is slice 3's, with the index.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

#: The version of this contract. Slice 2 indexes records of this version; a record of another is
#: re-derived from the repository rather than read — derived data is rebuilt, never migrated.
RECORD_VERSION = 1

#: THE TWO AUDIENCE LABELS a document carries, from the widest reader to the narrowest. `client`
#: may be shown to anybody the role talks to; `internal` only to the product's own people — its
#: admins and its engineers, two of #266's three audiences — and never to a client.
CLIENT, INTERNAL = "client", "internal"
AUDIENCES: tuple[str, ...] = (CLIENT, INTERNAL)

#: What a document nobody labelled is. The narrow one, on purpose: an internal e-mail dropped into
#: the repository without a label must not surface in an answer to a client because somebody
#: forgot to say so.
DEFAULT_AUDIENCE = INTERNAL


def narrowest(*labels: str) -> str:
    """The narrowest of `labels` — the one a document keeps when two sources disagree. A label
    this contract does not know counts as `internal`, so no spelling can widen a document."""
    known = [label if label in AUDIENCES else INTERNAL for label in labels if label]
    if not known:
        return DEFAULT_AUDIENCE
    return max(known, key=AUDIENCES.index)


def may_read(label: str, reader: str) -> bool:
    """Whether a reader of the `reader` audience may be shown a document labelled `label` — by
    its name, its type, its reason, anything. A label nobody knows is internal, and a reader
    nobody knows is a client: no spelling on either side can widen what is shown."""
    shown = reader if reader in AUDIENCES else CLIENT
    return AUDIENCES.index(narrowest(label or DEFAULT_AUDIENCE)) <= AUDIENCES.index(shown)


class Decision(BaseModel):
    """A decision the document mentions, as a model read it: what was decided and, when the
    document says, when. Kept close to the document's own words — slice 2 dates and orders them."""

    text: str
    date: str = ""


class Derived(BaseModel):
    """Which fields of the record a MODEL wrote, and with what — never mistaken for what was read.

    `text` is True when the normalised text itself is a model's description (an image read by a
    vision row). `summary` and `decisions` are True once a model has written them. `by` names the
    harness and model that did, and `error` why the model step did not run or failed — a record
    with an error has no summary, which is not the same as a document with nothing to summarise.
    `attempts` bounds the retries of that step; the extraction itself is never repeated."""

    text: bool = False
    summary: bool = False
    decisions: bool = False
    by: str = ""
    error: str = ""
    attempts: int = 0


class DocumentRecord(BaseModel):
    """One version of one document: its normalised text and everything said about it."""

    version: int = RECORD_VERSION
    #: the product it belongs to (`product/key.py::product_key`) — never a registry project
    product: str
    #: where it is, relative to the context repository's root, in `/` spelling
    path: str
    #: the SHA-256 of its bytes: which version this is
    digest: str
    size: int = 0
    #: the context repository's commit it was read at, when it was read from a checkout
    commit: str = ""
    ingested_at: str = ""

    #: `text`, `markdown`, `mermaid`, `drawio`, `svg`, `email`, `pdf`, `image` — or "" for a format
    #: no row reads (`adapters/extract/registry.py::TYPES`)
    type: str = ""
    audience: str = DEFAULT_AUDIENCE
    #: where the label came from: `path`, `front matter`, both, or `default`
    audience_from: str = "default"

    #: False when it could not be read — and then `reason` says why, in a sentence
    readable: bool = False
    reason: str = ""
    #: the extraction row that produced the text (`adapters/extract/registry.py::EXTRACTORS`)
    row: str = ""
    text: str = ""
    #: the text was cut at the platform's limit; `notes` says where
    truncated: bool = False
    #: the content was read from pixels — by OCR or a vision model — so exact numbers may be wrong
    from_image: bool = False
    pages: int | None = None

    # ── read without a model ─────────────────────────────────────────────────────────────────
    title: str = ""
    #: ISO date (`YYYY-MM-DD`), or "" when nothing said one
    date: str = ""
    #: `front matter`, `header`, `metadata`, `file name`, `commit`
    date_from: str = ""
    authors: list[str] = Field(default_factory=list)
    #: the top-level folder it sits in — "" at the repository's root
    area: str = ""
    #: the product's vocabulary (its glossary's terms) the text uses
    entities: list[str] = Field(default_factory=list)
    #: requirement numbers the text cites (`REQ-0041`, "requirement 41")
    requirements: list[int] = Field(default_factory=list)
    #: card references the text cites (`#512`, "card 512")
    cards: list[str] = Field(default_factory=list)
    #: what the row saw and did not read — an e-mail's attachments, a cut, a label it did not know
    notes: list[str] = Field(default_factory=list)

    # ── written by a model, once per version ─────────────────────────────────────────────────
    summary: str = ""
    decisions: list[Decision] = Field(default_factory=list)
    derived: Derived = Field(default_factory=Derived)

    @field_validator("audience", mode="before")
    @classmethod
    def _a_label_is_never_widened(cls, value):
        """Absent, empty or unknown reads as `internal` — the one direction a mistake may go."""
        text = str(value or "").strip().lower()
        return text if text in AUDIENCES else DEFAULT_AUDIENCE

    @model_validator(mode="after")
    def _an_unreadable_record_says_why(self):
        if not self.readable and not self.reason.strip():
            raise ValueError("an unreadable record must say why it could not be read")
        return self

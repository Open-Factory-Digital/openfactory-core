"""The extraction port — a document's bytes in, its normalised text out (#269 slice 1, ADR-0053).

A REPLACEABLE SEAM, THE SAME KIND AS EVERY OTHER AXIS. What reads a PDF, what reads a scanned one
and what describes a chart are rows in `registry.py::EXTRACTORS`, chosen per document type by
configuration (`OPENFACTORY_EXTRACT_ROWS`), and a stranger's package adds a row through the
`extract.<kind>` entry point without editing a file of ours (`plugins.py`). Choosing and tuning OCR
and vision models is not this seam's business; making each of them a row is.

PYDANTIC IN, PYDANTIC OUT. A row is handed a `Source` — the bytes the dispatcher already read,
bounded and hashed — and answers an `Extraction`. It NEVER OPENS A PATH: containment, symbolic
links and the size limit are decided once, before any row is asked (`product/documents/ingest.py`),
so no row can be the one that forgot. `Source.path` is for sentences and for a row that needs a
file name's suffix, not for reading.

NOTHING IN A DOCUMENT IS EVER EXECUTED. No macro runs, no script in a PDF is interpreted, no
external entity in XML is resolved; a row that would need any of those does not read that part.

NEVER SILENT. A row that cannot read what it was handed answers `readable=False` with the reason
in a sentence — a protected PDF, an image nobody can describe here, a format it does not know —
and never an empty text that reads as "nothing there". A row that RAISES is caught by the
dispatcher and recorded the same way, with the exception's words.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Source(BaseModel):
    """What a row is handed: one version of one document, already read and bounded."""

    model_config = ConfigDict(frozen=True)

    #: where it is in the context repository, `/`-spelled — for messages and a suffix, never opened
    path: str
    #: the document type the dispatcher read off the path (`registry.py::TYPES`)
    type: str
    data: bytes
    #: the SHA-256 of `data`
    digest: str


class Extraction(BaseModel):
    """What a row answers: the normalised text and what the row could read about the document —
    or, with `readable=False`, why it could not."""

    readable: bool
    text: str = ""
    reason: str = ""
    #: the row that answered — filled by the dispatcher when a row leaves it empty
    row: str = ""
    title: str = ""
    #: ISO date the document states about itself (a header, its metadata, its front matter)
    date: str = ""
    date_from: str = ""
    authors: list[str] = Field(default_factory=list)
    #: the audience the document DECLARES about itself (front matter) — combined with the path's
    #: by the dispatcher, the narrowest winning (`contracts/document.py::narrowest`)
    audience: str = ""
    pages: int | None = None
    #: the text was read from pixels (OCR, a vision model)
    from_image: bool = False
    #: the text itself is a MODEL's — `harness/model` of whatever wrote it, "" when a parser did
    model: str = ""
    #: what the row saw and did not read, in sentences
    notes: list[str] = Field(default_factory=list)
    #: the document type to hand it to next when this row found nothing to read in it — a PDF with
    #: no text layer answers `scanned`, and the dispatcher asks that type's row once
    fallback: str = ""


def unreadable(reason: str, *, row: str = "", fallback: str = "", **more) -> Extraction:
    """The one way a row says it could not read — so no row can forget the reason."""
    return Extraction(readable=False, reason=reason.strip() or "it could not be read", row=row,
                      fallback=fallback, **more)


@runtime_checkable
class Extractor(Protocol):
    """A row on the extraction axis. `extract` NEVER RAISES for a document it cannot read — it
    answers `unreadable(...)`; an exception is the row's own failure, and is recorded as one."""

    def extract(self, source: Source) -> Extraction:
        ...

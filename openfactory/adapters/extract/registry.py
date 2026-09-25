"""Which row reads each type of document — from configuration, never from an import (#269 slice 1).

TWO TABLES AND ONE LINE OF CONFIGURATION. `TYPES` reads a document's type off its name (the suffix
— never its content, which is the untrusted part); `DEFAULT_ROWS` says which row reads each type;
`OPENFACTORY_EXTRACT_ROWS` overrides that per type, for the deployment:

    OPENFACTORY_EXTRACT_ROWS="image=ocr, scanned=acme_ocr"

A row is a kind in `EXTRACTORS` or an add-on's `extract.<kind>` entry point (`plugins.py`), built
with the project it reads for. So a lighter OCR, a specialised vision model or a better PDF reader
is a package and a line, never a redesign — which is the seam #269 asked for, and the choice of
which model is not decided here.

AN UNKNOWN ROW RAISES, NAMING WHAT IS KNOWN — the house rule: falling back to another row would
read a deployment's documents with something nobody chose. The dispatcher turns that refusal into
the documents' reason (`product/documents/ingest.py`), so a typo in the configuration is visible
on the panel as every image being unreadable, with the typo in the sentence — never silence.

A TYPE WITH NO ROW IS AN UNKNOWN FORMAT, and is recorded as unreadable with its suffix.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import PurePosixPath

from openfactory import plugins
from openfactory.adapters.extract.base import Extractor

log = logging.getLogger("openfactory.extract")

#: The entry-point axis: `extract.<kind>` — a builder `build(project=None) -> Extractor`.
AXIS = "extract"

#: The deployment's overrides, `type=kind` pairs separated by commas.
ROWS_ENV = "OPENFACTORY_EXTRACT_ROWS"


def _text(**_kw):
    from openfactory.adapters.extract.text import TextRow

    return TextRow()


def _markdown(**_kw):
    from openfactory.adapters.extract.text import MarkdownRow

    return MarkdownRow()


def _mermaid(**_kw):
    from openfactory.adapters.extract.text import MermaidRow

    return MermaidRow()


def _html(**_kw):
    from openfactory.adapters.extract.text import HtmlRow

    return HtmlRow()


def _drawio(**_kw):
    from openfactory.adapters.extract.markup import DrawioRow

    return DrawioRow()


def _svg(**_kw):
    from openfactory.adapters.extract.markup import SvgRow

    return SvgRow()


def _eml(**_kw):
    from openfactory.adapters.extract.mail import EmailRow

    return EmailRow()


def _pdf(**_kw):
    from openfactory.adapters.extract.pdf import PdfRow

    return PdfRow()


def _ocr(**_kw):
    from openfactory.adapters.extract.pdf import OcrRow

    return OcrRow()


def _vision(*, project=None, **_kw):
    from openfactory.adapters.extract.vision import VisionRow

    return VisionRow(project=project)


#: kind → builder, `build(project=None) -> Extractor`. Every row the platform ships; an add-on's
#: join through the entry point, and a built-in wins a collision (`plugins.builder`).
EXTRACTORS: dict[str, Callable[..., object]] = {
    "text": _text,
    "markdown": _markdown,
    "mermaid": _mermaid,
    "html": _html,
    "drawio": _drawio,
    "svg": _svg,
    "eml": _eml,
    "pdf": _pdf,
    "ocr": _ocr,
    "vision": _vision,
}

#: suffix → document type. Read off the NAME: the bytes are what is untrusted, and a type sniffed
#: from them would let a file choose its own parser.
TYPES: dict[str, str] = {
    ".txt": "text", ".text": "text", ".rst": "text", ".adoc": "text", ".org": "text",
    ".csv": "text", ".tsv": "text", ".json": "text", ".yaml": "text", ".yml": "text",
    ".md": "markdown", ".markdown": "markdown",
    ".mmd": "mermaid", ".mermaid": "mermaid",
    ".html": "html", ".htm": "html",
    ".drawio": "drawio", ".dio": "drawio",
    ".svg": "svg",
    ".eml": "email",
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image",
}

#: document type → the row that reads it unless the deployment says otherwise. `scanned` is not
#: a suffix: it is where a PDF with no text layer goes next (`pdf.py`).
DEFAULT_ROWS: dict[str, str] = {
    "text": "text", "markdown": "markdown", "mermaid": "mermaid", "html": "html",
    "drawio": "drawio", "svg": "svg", "email": "eml", "pdf": "pdf", "scanned": "ocr",
    "image": "vision",
}


def document_type(path: str) -> str:
    """The type of the document at `path`, or "" for a format no row reads."""
    name = PurePosixPath(path).name.lower()
    if name.endswith(".drawio.xml"):
        return "drawio"
    return TYPES.get(PurePosixPath(name).suffix, "")


#: Overrides already warned about, one line each — this is read once per pass, not once per file.
_SAID: set[str] = set()


def configured() -> dict[str, str]:
    """The deployment's `type → kind` overrides. An entry that is not `type=kind`, or names a
    type no suffix and no fallback produces, is warned about once and ignored — it could never
    apply, and saying so is the only useful thing to do with it."""
    raw = (os.environ.get(ROWS_ENV) or "").strip()
    out: dict[str, str] = {}
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        doc_type, _, kind = (p.strip().lower() for p in entry.partition("="))
        if not doc_type or not kind or doc_type not in DEFAULT_ROWS:
            if entry not in _SAID:
                _SAID.add(entry)
                log.warning("%s: %r is not `type=kind` for a known type (%s) — ignored",
                            ROWS_ENV, entry, ", ".join(sorted(DEFAULT_ROWS)))
            continue
        out[doc_type] = kind
    return out


def row_for(doc_type: str) -> str:
    """The row that reads `doc_type` on this deployment — "" when none does."""
    return configured().get(doc_type) or DEFAULT_ROWS.get(doc_type, "")


def build_extractor(kind: str, *, project=None) -> Extractor:
    """The row `kind`, built for `project` — or `ValueError` naming every row this deployment
    has."""
    builder = EXTRACTORS.get(kind) or plugins.builder(AXIS, kind, builtin=EXTRACTORS)
    if builder is None:
        raise ValueError(f"unknown extract row {kind!r} — known: "
                         f"{', '.join(plugins.known(AXIS, EXTRACTORS))}")
    row = builder(project=project)
    if not callable(getattr(row, "extract", None)):
        raise ValueError(f"the extract row {kind!r} built something with no `extract(source)` — "
                         f"it cannot read a document")
    return row  # type: ignore[return-value]

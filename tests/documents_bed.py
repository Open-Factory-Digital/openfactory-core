"""A product's context repository, copied from the fixture, and the documents dropped into it
(#269 slice 1) — the bed the ingestion tests run on.

WHAT IS REAL. The pass, the rows, the child process that reads a PDF, the store under the
product's state directory, the audience labels. What is stood in for is only the MODEL: a vision
row and a reader that answer from here, and count how often they were asked — because "once per
version" is a count.

THE PDFS ARE BUILT HERE, NOT CHECKED IN: a PDF's bytes are unreadable in a diff, and every one
these tests drop says what it is in the function that makes it.
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

from openfactory.adapters.extract import registry
from openfactory.adapters.extract.base import Extraction
from openfactory.product.documents.reading import Reading

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "context"
#: The product's key, as `product_key` spells a registry project linked to `lark/context`.
KEY = "repo:lark/context"
#: The product's glossary terms — what `entities` looks for.
TERMS = ("Reconciled Statement", "monthly close", "Ledger")


def project(tmp_path, name: str = "lark"):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name=name, repo_path=str(tmp_path / name),
                   tracker=ProviderRef(kind="github", repo=f"lark/{name}"),
                   forge=ProviderRef(kind="github", repo=f"lark/{name}"),
                   product=ProductConfig(docs_repo="lark/context"))


def context(tmp_path) -> Path:
    """A copy of the fixture's context repository — a test drops files into its own."""
    root = tmp_path / "context"
    shutil.copytree(FIXTURE, root)
    return root


# ── PDFs ─────────────────────────────────────────────────────────────────────────────────────────

def _assemble(objects: list[bytes]) -> bytes:
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
            .encode())
    return out


def text_pdf(*lines: str, title: str = "") -> bytes:
    """A one-page PDF with a text layer: each line in Helvetica, 18 points."""
    shown = " ".join(f"({line}) Tj 0 -28 Td" for line in lines)
    content = f"BT /F1 18 Tf 72 720 Td {shown} ET".encode("latin-1")
    info = [f"<< /Title ({title}) /Author (Lark Legal) /CreationDate (D:20240312090000Z) >>"
            .encode()] if title else []
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        *info,
    ]
    pdf = _assemble(objects)
    if info:
        pdf = pdf.replace(b"/Root 1 0 R >>", b"/Root 1 0 R /Info 6 0 R >>")
    return pdf


def image_pdf() -> bytes:
    """A one-page PDF that is a picture and nothing else — what a scanner makes."""
    pixels = bytes(range(64))
    content = b"q 200 0 0 200 72 500 cm /Im1 Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 64 >>\nstream\n" + pixels + b"\nendstream",
    ]
    return _assemble(objects)


def protected_pdf(*lines: str, password: str = "s3cret") -> bytes:
    """A PDF that needs a password to be opened."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf(*lines))))
    writer.encrypt(user_password=password, owner_password="owner-" + password,
                   algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def restricted_pdf(*lines: str) -> bytes:
    """A PDF encrypted with an EMPTY user password — "no printing, no copying" — which opens."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf(*lines))))
    writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


#: The smallest PNG there is: one grey pixel.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010800000000"
    "3a7e9b550000000a4944415478da63f80f00010101001b4b59ec0000000049454e44ae426082")


# ── the model, stood in for ─────────────────────────────────────────────────────────────────────

class StubReader:
    """The model step, answering from here and counting — "once per version" is a count."""

    def __init__(self, *, summary: str = "The board moved the export to CSV.", error: str = "",
                 decisions=None) -> None:
        self.summary, self.error = summary, error
        self.decisions = decisions if decisions is not None else [
            {"text": "the monthly export moves to CSV", "date": "2024-03-12"}]
        self.read_paths: list[str] = []

    def read(self, record):
        self.read_paths.append(record.path)
        if self.error:
            return Reading(error=self.error, by="stub/reader")
        return Reading(summary=self.summary, decisions=self.decisions, by="stub/reader")


class StubVision:
    """A vision row that describes every image as a revenue chart — and counts."""

    kind = "stub_vision"
    described: list[str] = []

    def extract(self, source):
        StubVision.described.append(source.path)
        return Extraction(readable=True, row=self.kind, model="stub/vision",
                          title="A bar chart of revenue per month",
                          text="A bar chart of revenue per month: January about 1200, February "
                               "about 1350.")


def use_stub_vision(monkeypatch) -> list[str]:
    """Configure the `image` type to the stub row — by the configuration a deployment uses."""
    StubVision.described = []
    monkeypatch.setitem(registry.EXTRACTORS, StubVision.kind, lambda **_k: StubVision())
    monkeypatch.setenv(registry.ROWS_ENV, f"image={StubVision.kind}")
    return StubVision.described


def count_extractions(monkeypatch) -> list[tuple[str, str]]:
    """Every `(row, path)` a row was asked to read — every built-in row wrapped, none replaced."""
    calls: list[tuple[str, str]] = []
    for kind, build in list(registry.EXTRACTORS.items()):
        def counted(*, _build=build, _kind=kind, **kw):
            row = _build(**kw)

            class _Counted:
                def extract(self, source):
                    calls.append((_kind, source.path))
                    return row.extract(source)

            return _Counted()

        monkeypatch.setitem(registry.EXTRACTORS, kind, counted)
    return calls

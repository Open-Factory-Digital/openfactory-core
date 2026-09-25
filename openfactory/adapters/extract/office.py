"""The rows that read office documents: Word, Excel and PowerPoint in their open formats (#336).

THE FILES CLIENTS SEND. A specification in Word, a price table in Excel, a deck from a meeting —
the extraction axis read none of them, so a person who attached one to the conversation was
answered from its name alone. `.docx`, `.xlsx` and `.pptx` are ZIP archives of XML (ECMA-376), and
their words are read here with the standard library: `zipfile` and `ElementTree`. No office suite
is installed, no macro is looked at, nothing in them runs.

A HOSTILE ARCHIVE IS REFUSED, NEVER EXPANDED. A ZIP says how big each member is before it is read,
and a member larger than `MEMBER_BYTES`, an archive of more than `MEMBERS` members or more than
`TOTAL_BYTES` in all is refused with that sentence — the shape of a ZIP bomb. The parts are read
through a bounded stream, so a header that lies is caught too. An XML part with a DTD is refused
(OOXML never carries one, and a DTD is how an entity expansion attack starts); `ElementTree`
resolves no external entity. A password-protected document is an encrypted container, not a
ZIP, and is said to be one.

THE OLD BINARY FORMATS ARE NAMED, NOT GUESSED: a `.doc`, `.xls` or `.ppt` is refused with the
remedy — save it in the open format — rather than read by a parser nobody here can vouch for.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from openfactory.adapters.extract.base import Extraction, Source, unreadable
from openfactory.adapters.extract.text import normalise

#: The most members, the largest member and the most bytes in all an archive may unpack to.
MEMBERS = 5000
MEMBER_BYTES = 64 * 1024 * 1024
TOTAL_BYTES = 256 * 1024 * 1024
#: How much of a spreadsheet is read: rows per sheet, columns per row, sheets.
SHEET_ROWS = 5000
SHEET_COLUMNS = 60
SHEETS = 50

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DC = "{http://purl.org/dc/elements/1.1/}"
#: What an encrypted OOXML document starts with: an OLE compound file, not a ZIP.
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class _Refused(Exception):
    pass


def _archive(data: bytes) -> zipfile.ZipFile:
    if data[:8] == _OLE:
        raise _Refused("it is password-protected or in the old binary format — save it without a "
                       "password, in the open format (.docx, .xlsx, .pptx)")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise _Refused("it is not the ZIP archive its suffix says it is") from None
    members = archive.infolist()
    if len(members) > MEMBERS:
        raise _Refused(f"it holds {len(members)} parts, more than the {MEMBERS} this reads")
    total = sum(m.file_size for m in members)
    if total > TOTAL_BYTES or any(m.file_size > MEMBER_BYTES for m in members):
        raise _Refused("it would unpack to more than this reads — the shape of a ZIP bomb")
    return archive


def _xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    with archive.open(info) as handle:
        raw = handle.read(MEMBER_BYTES + 1)
    if len(raw) > MEMBER_BYTES:
        raise _Refused("one of its parts is larger than it said — it was not read")
    if b"<!DOCTYPE" in raw[:4096] or b"<!ENTITY" in raw:
        raise _Refused("one of its parts declares a DTD, which no office document does")
    try:
        return ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise _Refused(f"its part {name} is not well-formed XML") from None


def _title(archive: zipfile.ZipFile) -> str:
    core = _xml(archive, "docProps/core.xml")
    node = core.find(f"{_DC}title") if core is not None else None
    return (node.text or "").strip()[:200] if node is not None and node.text else ""


def _rels(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
    root = _xml(archive, name)
    if root is None:
        return {}
    return {r.get("Id", ""): r.get("Target", "") for r in root.iter(f"{_REL}Relationship")}


def _read(source: Source, kind: str, reader) -> Extraction:
    try:
        archive = _archive(source.data)
        text, notes = reader(archive)
        title = _title(archive)
    except _Refused as refused:
        return unreadable(str(refused), row=kind)
    text = normalise(text)
    if not text.strip():
        return unreadable("it holds no text", row=kind)
    return Extraction(readable=True, text=text, row=kind, title=title, notes=notes)


# ── Word ───────────────────────────────────────────────────────────────────────────────────────

def _paragraph(node: ElementTree.Element) -> str:
    out = []
    for part in node.iter():
        if part.tag == f"{_W}t" and part.text:
            out.append(part.text)
        elif part.tag == f"{_W}tab":
            out.append("\t")
        elif part.tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
    return "".join(out)


def _blocks(parent: ElementTree.Element, lines: list[str]) -> None:
    """The document's blocks IN ORDER — paragraphs, tables, and the content controls that wrap
    either — so a table's text is read once, as rows, and never again as loose paragraphs."""
    for block in parent:
        if block.tag == f"{_W}p":
            lines.append(_paragraph(block))
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(_paragraph(p) for p in cell.iter(f"{_W}p")).strip()
                         for cell in row.iter(f"{_W}tc")]
                lines.append(" | ".join(cells))
            lines.append("")
        elif block.tag == f"{_W}sdt":
            content = block.find(f"{_W}sdtContent")
            if content is not None:
                _blocks(content, lines)


def _word(archive: zipfile.ZipFile) -> tuple[str, list[str]]:
    document = _xml(archive, "word/document.xml")
    body = document.find(f"{_W}body") if document is not None else None
    if body is None:
        raise _Refused("it has no document part — it is not a Word document")
    lines: list[str] = []
    _blocks(body, lines)
    return "\n".join(lines), []


# ── Excel ──────────────────────────────────────────────────────────────────────────────────────

def _column(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    n = 0
    for ch in letters.group(0) if letters else "":
        n = n * 26 + (ord(ch) - 64)
    return max(n - 1, 0)


def _sheets(archive: zipfile.ZipFile) -> tuple[str, list[str]]:
    shared: list[str] = []
    strings = _xml(archive, "xl/sharedStrings.xml")
    if strings is not None:
        shared = ["".join(t.text or "" for t in si.iter(f"{_S}t")) for si in strings.iter(f"{_S}si")]
    book = _xml(archive, "xl/workbook.xml")
    if book is None:
        raise _Refused("it has no workbook part — it is not an Excel workbook")
    rels = _rels(archive, "xl/_rels/workbook.xml.rels")
    out: list[str] = []
    notes: list[str] = []
    sheets = list(book.iter(f"{_S}sheet"))
    if len(sheets) > SHEETS:
        notes.append(f"only the first {SHEETS} of {len(sheets)} sheets were read")
    for sheet in sheets[:SHEETS]:
        target = rels.get(sheet.get(f"{_R}id", ""), "")
        if not target:
            continue
        part = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        grid = _xml(archive, part)
        if grid is None:
            continue
        out.append(f"## {sheet.get('name', 'Sheet')}")
        rows = list(grid.iter(f"{_S}row"))
        if len(rows) > SHEET_ROWS:
            notes.append(f"sheet {sheet.get('name', '')!r}: only the first {SHEET_ROWS} of "
                         f"{len(rows)} rows were read")
        for row in rows[:SHEET_ROWS]:
            cells: dict[int, str] = {}
            for cell in row.iter(f"{_S}c"):
                col = _column(cell.get("r", ""))
                if col >= SHEET_COLUMNS:
                    continue
                kind = cell.get("t", "")
                value = cell.find(f"{_S}v")
                if kind == "s" and value is not None and (value.text or "").isdigit():
                    index = int(value.text or "0")
                    text = shared[index] if index < len(shared) else ""
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(f"{_S}t"))
                else:
                    text = (value.text or "") if value is not None else ""
                if text.strip():
                    cells[col] = text.strip()
            if cells:
                width = max(cells) + 1
                out.append(" | ".join(cells.get(i, "") for i in range(width)))
        out.append("")
    return "\n".join(out), notes


# ── PowerPoint ─────────────────────────────────────────────────────────────────────────────────

def _slides(archive: zipfile.ZipFile) -> tuple[str, list[str]]:
    names = sorted((n for n in archive.namelist()
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                   key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
    if not names:
        raise _Refused("it has no slides — it is not a PowerPoint presentation")
    out = []
    for number, name in enumerate(names, start=1):
        slide = _xml(archive, name)
        if slide is None:
            continue
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{_A}t"))
                      for p in slide.iter(f"{_A}p")]
        out.append(f"## Slide {number}\n" + "\n".join(p for p in paragraphs if p.strip()))
    return "\n\n".join(out), []


class DocxRow:
    kind = "docx"

    def extract(self, source: Source) -> Extraction:
        return _read(source, self.kind, _word)


class XlsxRow:
    kind = "xlsx"

    def extract(self, source: Source) -> Extraction:
        return _read(source, self.kind, _sheets)


class PptxRow:
    kind = "pptx"

    def extract(self, source: Source) -> Extraction:
        return _read(source, self.kind, _slides)


class LegacyOfficeRow:
    """`.doc`, `.xls`, `.ppt`: refused by name, with the remedy."""

    kind = "legacy-office"

    def extract(self, source: Source) -> Extraction:
        return unreadable("it is in an old binary office format this does not read — save it as "
                          ".docx, .xlsx or .pptx and send it again", row=self.kind)


__all__ = ["DocxRow", "LegacyOfficeRow", "PptxRow", "XlsxRow"]

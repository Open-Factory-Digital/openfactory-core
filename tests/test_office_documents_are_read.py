"""Word, Excel and PowerPoint are read, and a hostile archive is refused, never expanded (#336).

The documents clients send most — a specification in Word, a price table in Excel, a meeting's
deck — were read by no row: a person who attached one was answered from its name. The archives
here are built with the standard library, the shape each format really has.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from openfactory.adapters.extract import office
from openfactory.adapters.extract.base import Source
from openfactory.adapters.extract.registry import build_extractor, document_type, row_for

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
PKG = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
CORE = ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{}</dc:title>'
        '</cp:coreProperties>')


def _zip(parts: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return buf.getvalue()


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def docx(*paragraphs: str, table: list[list[str]] | None = None, title: str = "") -> bytes:
    rows = "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>"
                   for row in (table or []))
    body = "".join(_p(t) for t in paragraphs) + (f"<w:tbl>{rows}</w:tbl>" if table else "")
    parts = {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"}
    if title:
        parts["docProps/core.xml"] = CORE.format(title)
    return _zip(parts)


def xlsx(rows: list[list[str]], sheet: str = "Preços") -> bytes:
    shared = sorted({c for r in rows for c in r if not c.replace(".", "").isdigit()})
    cells = []
    for y, row in enumerate(rows, start=1):
        out = []
        for x, value in enumerate(row):
            ref = f"{chr(65 + x)}{y}"
            if value in shared:
                out.append(f'<c r="{ref}" t="s"><v>{shared.index(value)}</v></c>')
            else:
                out.append(f'<c r="{ref}"><v>{value}</v></c>')
        cells.append(f'<row r="{y}">{"".join(out)}</row>')
    return _zip({
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="{sheet}" sheetId="1" '
                           f'r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships {PKG}><Relationship Id="rId1" '
                                      f'Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": f"<sst {S}>" + "".join(f"<si><t>{s}</t></si>" for s in shared)
                                + "</sst>",
        "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>{''.join(cells)}</sheetData>"
                                    f"</worksheet>",
    })


def pptx(*slides: str) -> bytes:
    return _zip({f"ppt/slides/slide{n}.xml":
                 f"<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\" "
                 f"{A}><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>"
                 for n, text in enumerate(slides, start=1)})


def _read(path: str, data: bytes):
    kind = document_type(path)
    return build_extractor(row_for(kind)).extract(Source(path=path, type=kind, data=data,
                                                         digest="0" * 64))


def test_a_word_document_is_read_with_its_tables_as_rows():
    said = _read("especificacao.docx", docx("Requisito de prazo", "O prazo tem só a data.",
                                             table=[["Campo", "Tipo"], ["prazo", "data"]],
                                             title="Especificação"))
    assert said.readable and said.row == "docx" and said.title == "Especificação"
    assert "O prazo tem só a data." in said.text
    assert "Campo | Tipo\nprazo | data" in said.text
    assert said.text.count("prazo | data") == 1, "a table's text was read twice"


def test_a_spreadsheet_is_read_sheet_by_sheet_row_by_row():
    said = _read("precos.xlsx", xlsx([["Plano", "Mensal"], ["Empresarial", "1900"]]))
    assert said.readable and said.row == "xlsx"
    assert "## Preços" in said.text and "Plano | Mensal" in said.text
    assert "Empresarial | 1900" in said.text


def test_a_presentation_is_read_slide_by_slide():
    said = _read("kickoff.pptx", pptx("Objetivo do trimestre", "Prazo em outubro"))
    assert said.readable and "## Slide 1\nObjetivo do trimestre" in said.text
    assert "## Slide 2\nPrazo em outubro" in said.text


@pytest.mark.parametrize("path", ["velho.doc", "velho.xls", "velho.ppt"])
def test_the_old_binary_formats_are_named_with_the_remedy(path):
    said = _read(path, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    assert not said.readable and "save it as .docx, .xlsx or .pptx" in said.reason


def test_a_password_protected_document_is_said_to_be_one():
    said = _read("secreto.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64)
    assert not said.readable and "password-protected" in said.reason


def test_a_file_that_is_not_the_zip_its_suffix_says_is_refused():
    said = _read("falso.xlsx", b"not a zip at all")
    assert not said.readable and "not the ZIP archive" in said.reason


def test_a_zip_bomb_is_refused_before_it_is_expanded(monkeypatch):
    monkeypatch.setattr(office, "MEMBER_BYTES", 1024)
    bomb = _zip({"word/document.xml": f"<w:document {W}><w:body>{_p('x' * 5000)}</w:body>"
                                      f"</w:document>"})
    said = _read("bomba.docx", bomb)
    assert not said.readable and "ZIP bomb" in said.reason


def test_a_part_with_a_dtd_is_refused():
    evil = _zip({"word/document.xml": '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]>'
                                      f"<w:document {W}><w:body>{_p('&a;')}</w:body>"
                                      f"</w:document>"})
    said = _read("evil.docx", evil)
    assert not said.readable and "DTD" in said.reason


def test_the_office_types_have_rows_by_default():
    for path, kind in (("a.docx", "docx"), ("a.xlsx", "xlsx"), ("a.pptx", "pptx"),
                       ("a.doc", "legacy-office")):
        assert document_type(path) == kind and row_for(kind) == kind

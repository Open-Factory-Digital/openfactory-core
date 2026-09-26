"""Every document in a product's context repository becomes text plus a record — once per
version, and never silently (#269 slice 1, ADR-0053).

THE FOUR ACCEPTANCE CRITERIA, each a test below by name:

  - a PDF dropped into the fixture's context repository is ingested and has a record, driven
    through the incremental path — the schedule's pass and the event alike;
  - an unreadable PDF appears on the panel as unreadable, with its reason;
  - a chart image's record states that its content came from an image (a stub vision row,
    configured the way a deployment configures one);
  - the same file version is never extracted twice — counted, across passes, across two
    registry projects of one product, and against a second pass racing the first.

And the security rules the slice was given, each proven: nothing in a document is executed, no
XML entity is resolved, no read leaves the tree, the size limit holds, and a document marked
internal never loses the label.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.adapters.extract import registry
from openfactory.adapters.extract.base import Source
from openfactory.contracts.document import DocumentRecord
from openfactory.product.documents.ingest import ingest, overview
from openfactory.product.documents.store import Store, documents_dir
from tests import documents_bed as bed


def _every_unreadable(key: str) -> list[dict]:
    """Every unreadable document, the client's and the internal ones, as a floor reads them."""
    seen = overview(key, internal=True)
    return [*seen["unreadable"], *seen["unreadable_internal"]]


def _why(key: str) -> dict[str, str]:
    return {doc["path"]: doc["reason"] for doc in _every_unreadable(key)}


def _record(key: str, path: str) -> DocumentRecord:
    store = Store(key)
    line = store.index()["paths"][path]
    record = store.get(path, line["digest"])
    assert record is not None, path
    return record


@pytest.fixture
def lark(tmp_path):
    return bed.project(tmp_path)


@pytest.fixture
def tree(tmp_path):
    return bed.context(tmp_path)


# ── acceptance ──────────────────────────────────────────────────────────────────────────────────

def test_a_pdf_dropped_into_the_context_repository_is_ingested_by_the_schedule_s_pass(
        lark, tree, monkeypatch):
    """The whole tree is read once; then a PDF is dropped, and the next pass reads IT alone."""
    calls = bed.count_extractions(monkeypatch)
    reader = bed.StubReader()
    first = ingest(lark, root=tree, reader=reader, terms=bed.TERMS)
    assert first.unreadable == [] and len(first.ingested) == 7, first.sentence()
    calls.clear()

    (tree / "contracts").mkdir()
    (tree / "contracts" / "sla-v3.pdf").write_bytes(bed.text_pdf(
        "SLA contract v3", "Availability of 99.9 percent a month", "The monthly close is REQ-0003",
        title="SLA contract v3"))
    second = ingest(lark, root=tree, reader=reader, terms=bed.TERMS)

    assert second.ingested == ["contracts/sla-v3.pdf"]
    assert calls == [("pdf", "contracts/sla-v3.pdf")], "only the dropped file was read"
    record = _record(bed.KEY, "contracts/sla-v3.pdf")
    assert record.readable and record.type == "pdf" and record.row == "pdf"
    assert record.pages == 1 and record.text.startswith("[page 1]\nSLA contract v3")
    assert record.title == "SLA contract v3" and record.authors == ["Lark Legal"]
    assert (record.date, record.date_from) == ("2024-03-12", "metadata")
    assert record.requirements == [3] and record.entities == ["monthly close"]
    assert record.area == "contracts" and record.audience == "internal"
    assert record.digest == __import__("hashlib").sha256(
        (tree / "contracts" / "sla-v3.pdf").read_bytes()).hexdigest()


def test_a_pdf_dropped_into_the_context_repository_is_ingested_by_the_event_alone(
        lark, tree, monkeypatch):
    """The event names one file, and nothing else in the tree is read — not even the files the
    schedule has never seen."""
    calls = bed.count_extractions(monkeypatch)
    (tree / "sla.pdf").write_bytes(bed.text_pdf("Service level agreement", "card #512 applies"))

    report = ingest(lark, root=tree, paths=["sla.pdf"], reader=bed.StubReader())

    assert report.ingested == ["sla.pdf"] and calls == [("pdf", "sla.pdf")]
    record = _record(bed.KEY, "sla.pdf")
    assert record.readable and record.cards == ["512"]
    assert list(Store(bed.KEY).index()["paths"]) == ["sla.pdf"]


def test_an_unreadable_pdf_appears_on_the_panel_as_unreadable_with_its_reason(
        lark, tree, monkeypatch):
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(lark)
    (tree / "client").mkdir()
    (tree / "client" / "nda.pdf").write_bytes(bed.protected_pdf("Mutual NDA"))
    ingest(lark, root=tree, reader=bed.StubReader())

    shown = TestClient(app).get("/api/product/lark/documents").json()

    assert shown["project"] == "lark" and shown["product"] == bed.KEY
    assert shown["read"] == 7 and shown["checked_at"]
    assert shown["unreadable"] == [{
        "path": "client/nda.pdf", "type": "pdf", "audience": "client",
        "reason": "a protected PDF: it needs a password to be opened"}]


@pytest.fixture
def two_credentials(monkeypatch, lark, tree):
    """A deployment with one floor credential and one product credential, and a product with an
    unreadable document of each audience — the one an internal name must not reach."""
    from fastapi.testclient import TestClient

    from openfactory.api.app import app
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "floor-secret")
    monkeypatch.setenv("OPENFACTORY_PRODUCT_TOKEN", "product-secret")
    monkeypatch.delenv("OPENFACTORY_PANEL_TOKENS", raising=False)
    monkeypatch.delenv("OPENFACTORY_PRODUCT_TOKENS", raising=False)
    ProjectRegistry().add(lark)
    (tree / "client").mkdir()
    (tree / "client" / "terms.pdf").write_bytes(bed.protected_pdf("Terms"))
    (tree / "internal" / "plano-de-demissoes.pdf").write_bytes(bed.protected_pdf("Layoffs"))
    ingest(lark, root=tree, reader=bed.StubReader())
    client = TestClient(app)

    def as_(token: str) -> dict:
        answer = client.get("/api/product/lark/documents",
                            headers={"authorization": f"Bearer {token}"})
        assert answer.status_code == 200, answer.text
        return answer.json()

    return as_


def test_a_product_credential_is_told_how_many_internal_documents_and_never_which(
        two_credentials):
    seen = two_credentials("product-secret")
    assert [d["path"] for d in seen["unreadable"]] == ["client/terms.pdf"]
    assert seen["internal_withheld"] == 1 and "unreadable_internal" not in seen
    assert "demissoes" not in str(seen) and "Layoffs" not in str(seen)


def test_a_floor_credential_is_shown_the_internal_documents_by_name(two_credentials):
    seen = two_credentials("floor-secret")
    assert [d["path"] for d in seen["unreadable"]] == ["client/terms.pdf"]
    assert seen["internal_withheld"] == 0
    assert seen["unreadable_internal"] == [{
        "path": "internal/plano-de-demissoes.pdf", "type": "pdf", "audience": "internal",
        "reason": "a protected PDF: it needs a password to be opened"}]


def test_the_panel_page_draws_the_unreadable_documents_with_their_reason():
    """The product page asks the documents route and draws each unreadable one with its reason
    and its audience — read off the page's own source, the one thing a person opens."""
    page = (Path(__file__).parents[1] / "openfactory" / "api" / "panel.html").read_text()
    assert 'api("/api/product/"+encodeURIComponent(_prod.project)+"/documents")' in page
    assert "loadDocuments()" in page.split("function loadDocuments")[0]
    painted = page.split("function paintDocuments(){", 1)[1].split("\n}\n", 1)[0]
    for said in ("esc(x.path)", "esc(x.reason)", "esc(x.audience)", "unreadable"):
        assert said in painted, said
    # an internal document is a row only when the server listed it; otherwise it is a number
    assert "d.unreadable_internal" in painted and "d.internal_withheld" in painted
    assert "internal document(s) could not be read" in painted


def test_a_chart_image_s_record_says_its_content_came_from_an_image(lark, tree, monkeypatch):
    described = bed.use_stub_vision(monkeypatch)
    (tree / "charts").mkdir()
    (tree / "charts" / "revenue.png").write_bytes(bed.PNG)

    ingest(lark, root=tree, paths=["charts/revenue.png"], reader=bed.StubReader())

    record = _record(bed.KEY, "charts/revenue.png")
    assert described == ["charts/revenue.png"]
    assert record.type == "image" and record.row == "stub_vision"
    assert record.from_image is True
    assert record.derived.text is True and record.derived.by.startswith("stub/vision")
    assert any("read from an image" in note and "source data" in note for note in record.notes)


def test_an_image_is_marked_as_read_from_an_image_even_when_its_row_forgets_to_say(
        lark, tree, monkeypatch):
    """A stranger's vision row that leaves `from_image` False does not make a chart exact."""
    from openfactory.adapters.extract.base import Extraction

    class Forgetful:
        def extract(self, source):
            return Extraction(readable=True, text="a pie chart", row="forgetful")

    monkeypatch.setitem(registry.EXTRACTORS, "forgetful", lambda **_k: Forgetful())
    monkeypatch.setenv(registry.ROWS_ENV, "image=forgetful")
    (tree / "pie.png").write_bytes(bed.PNG)
    ingest(lark, root=tree, paths=["pie.png"], reader=bed.StubReader())

    record = _record(bed.KEY, "pie.png")
    assert record.from_image and any("read from an image" in n for n in record.notes)


def test_the_same_file_version_is_never_extracted_twice(lark, tree, monkeypatch):
    calls = bed.count_extractions(monkeypatch)
    reader = bed.StubReader()
    ingest(lark, root=tree, reader=reader)
    read_once = sorted(calls)
    summarised_once = list(reader.read_paths)
    assert len(read_once) == 7

    again = ingest(lark, root=tree, reader=reader)
    assert again.ingested == [] and again.unchanged == 7
    assert sorted(calls) == read_once and reader.read_paths == summarised_once

    # A file whose mtime moved and whose bytes did not is hashed again, never extracted again.
    note = tree / "notes" / "call-with-ana.txt"
    os.utime(note, ns=(1_000_000_000, 1_000_000_000))
    ingest(lark, root=tree, reader=reader)
    ingest(lark, root=tree, paths=["notes/call-with-ana.txt"], reader=reader)
    assert sorted(calls) == read_once

    # The index lost: the records still decide — nothing is extracted again.
    (documents_dir(bed.KEY) / "index.json").unlink()
    assert ingest(lark, root=tree, reader=reader).ingested == []
    assert sorted(calls) == read_once and reader.read_paths == summarised_once


def test_one_version_is_extracted_once_for_every_registry_project_of_the_product(
        tmp_path, tree, monkeypatch):
    """Two registry projects of one context repository are one product: one set of records."""
    calls = bed.count_extractions(monkeypatch)
    web, api = bed.project(tmp_path, "lark-web"), bed.project(tmp_path, "lark-api")
    ingest(web, root=tree, reader=bed.StubReader())
    before = len(calls)

    report = ingest(api, root=tree, reader=bed.StubReader())

    assert report.ingested == [] and len(calls) == before
    assert documents_dir(bed.KEY) == Store(bed.KEY).root


def test_a_version_another_pass_is_reading_is_left_to_it(lark, tree, monkeypatch):
    """Two passes at once — the schedule and an event — never read one version twice: the second
    finds its lock held and moves on, saying so."""
    import hashlib

    calls = bed.count_extractions(monkeypatch)
    path = "notes/call-with-ana.txt"
    digest = hashlib.sha256((tree / path).read_bytes()).hexdigest()
    held = Store(bed.KEY).version_lock(path, digest)
    held.acquire(timeout=1)
    import threading

    out: dict = {}
    try:
        worker = threading.Thread(target=lambda: out.setdefault("report", ingest(
            lark, root=tree, paths=[path], reader=bed.StubReader())))
        worker.start()
        worker.join()
    finally:
        held.release()
    assert out["report"].busy == [path] and out["report"].ingested == []
    assert calls == []


def test_a_changed_file_is_a_new_version_and_the_old_one_stays(lark, tree):
    ingest(lark, root=tree, reader=bed.StubReader())
    old = _record(bed.KEY, "notes/call-with-ana.txt")
    (tree / "notes" / "call-with-ana.txt").write_text("Call with Ana, rewritten.\n")

    report = ingest(lark, root=tree, reader=bed.StubReader())

    new = _record(bed.KEY, "notes/call-with-ana.txt")
    assert report.ingested == ["notes/call-with-ana.txt"] and new.digest != old.digest
    assert Store(bed.KEY).get("notes/call-with-ana.txt", old.digest) == old


def test_a_file_rewritten_to_the_same_size_is_read_again(lark, tree):
    """The size-and-mtime shortcut is taken only when BOTH still match the index."""
    note = tree / "notes" / "call-with-ana.txt"
    ingest(lark, root=tree, reader=bed.StubReader())
    old = _record(bed.KEY, "notes/call-with-ana.txt")
    rewritten = note.read_bytes().replace(b"Ana", b"Bia")
    before = note.stat()
    note.write_bytes(rewritten)
    os.utime(note, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    report = ingest(lark, root=tree, reader=bed.StubReader())

    assert report.ingested == ["notes/call-with-ana.txt"]
    assert _record(bed.KEY, "notes/call-with-ana.txt").digest != old.digest


def test_records_lost_under_an_index_that_survived_are_read_again(lark, tree):
    """Derived is disposable: the records wiped and the index kept, the next pass rebuilds them
    from the repository — the index's shortcut never stands in for a record that is not there."""
    import shutil as sh

    ingest(lark, root=tree, reader=bed.StubReader())
    sh.rmtree(documents_dir(bed.KEY) / "records")

    report = ingest(lark, root=tree, reader=bed.StubReader())

    assert len(report.ingested) == 7 and _record(bed.KEY, "README.md").readable


def test_a_version_another_pass_finished_while_this_one_looked_is_not_read_again(
        lark, tree, monkeypatch):
    """Between "no record yet" and taking the version's lock, another pass may write the record:
    this pass looks again under the lock, and reads nothing."""
    calls = bed.count_extractions(monkeypatch)
    path = "notes/call-with-ana.txt"
    raced: list[bool] = []

    class Racing(Store):
        def has(self, asked_path, digest):
            if asked_path == path and not raced:
                raced.append(True)
                ingest(lark, root=tree, paths=[path], reader=bed.StubReader())  # the other pass
                return False
            return super().has(asked_path, digest)

    report = ingest(lark, root=tree, paths=[path], reader=bed.StubReader(),
                    store=Racing(bed.KEY))

    assert raced and calls == [("text", path)], "the other pass read it; this one did not"
    assert report.ingested == [] and report.unchanged == 1


def test_a_file_gone_from_the_repository_leaves_the_index_and_keeps_its_records(lark, tree):
    ingest(lark, root=tree, reader=bed.StubReader())
    gone = _record(bed.KEY, "data/revenue.csv")
    (tree / "data" / "revenue.csv").unlink()

    report = ingest(lark, root=tree, reader=bed.StubReader())

    assert report.removed == ["data/revenue.csv"]
    assert "data/revenue.csv" not in Store(bed.KEY).index()["paths"]
    assert Store(bed.KEY).get("data/revenue.csv", gone.digest) == gone


def test_a_pass_with_a_budget_stops_and_the_next_one_goes_on(lark, tree):
    ticks = iter(range(100))
    first = ingest(lark, root=tree, reader=bed.StubReader(), budget_seconds=2.5,
                   clock=lambda: float(next(ticks)))
    assert len(first.ingested) == 2 and first.left == 5, first.sentence()
    assert "5 left for the next pass" in first.sentence()

    second = ingest(lark, root=tree, reader=bed.StubReader())
    assert len(second.ingested) == 5 and second.unchanged == 2 and second.removed == []


# ── what is read, per format ────────────────────────────────────────────────────────────────────

def test_every_format_in_the_fixture_is_read_into_its_record(lark, tree):
    ingest(lark, root=tree, reader=bed.StubReader(), terms=bed.TERMS)

    readme = _record(bed.KEY, "README.md")
    assert (readme.type, readme.row, readme.title) == ("markdown", "markdown",
                                                       "Lark Ledger — the context repository")
    assert (readme.date, readme.date_from, readme.authors) == ("2024-02-01", "front matter",
                                                               ["The product team"])
    assert readme.requirements == [3] and readme.cards == ["41"]
    assert readme.entities == ["Ledger", "Reconciled Statement", "monthly close"]
    assert "---" not in readme.text and "audience" not in readme.text

    mermaid = _record(bed.KEY, "diagrams/checkout.mmd")
    assert mermaid.title == "Checkout flow" and "Payment -->|charges the card| Bank" in mermaid.text

    drawio = _record(bed.KEY, "diagrams/services.drawio")
    assert drawio.title == "Services"
    assert "- Order service → Payments gateway: charges the card" in drawio.text
    assert "- Payments gateway → Ledger: records the payment" in drawio.text
    assert "<b>" not in drawio.text

    mail = _record(bed.KEY, "mail/2021-05-03-export-format.eml")
    assert (mail.type, mail.title, mail.date, mail.date_from) == (
        "email", "Export format", "2021-05-03", "header")
    assert mail.authors == ["Ana Client <ana@lark.example>"]
    assert "To: The team <team@lark.example>, Bruno <bruno@lark.example>" in mail.text
    assert "keep the export in XLSX" in mail.text and mail.requirements == [7]
    assert mail.notes == ["attachment not read here: terms.pdf"]

    minutes = _record(bed.KEY, "internal/2024-03-12-board-minutes.md")
    assert (minutes.date, minutes.date_from) == ("2024-03-12", "file name")
    assert minutes.requirements == [7] and minutes.cards == ["512"]

    csv = _record(bed.KEY, "data/revenue.csv")
    assert csv.type == "text" and "2024-02,1350" in csv.text


def _commit(where: Path, message: str, when: str) -> None:
    import subprocess

    dated = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    for argv in ([["init", "-q"]] if not (where / ".git").exists() else []) + [
            ["add", "-A"], ["commit", "-qm", message]]:
        subprocess.run(["git", "-C", str(where), *argv], check=True, capture_output=True,
                       env=dated)


def test_a_document_with_no_date_of_its_own_is_dated_by_its_last_commit(lark, tmp_path):
    """Only when the tree IS the repository: a context tree that merely sits inside another
    repository is not dated by that one's history."""
    import shutil as sh

    outer = tmp_path / "outer"
    tree = outer / "context"
    sh.copytree(bed.FIXTURE, tree)
    _commit(outer, "somebody else's repository", "2019-02-02T10:00:00+00:00")
    ingest(lark, root=tree, paths=["notes/call-with-ana.txt"], reader=bed.StubReader())
    assert _record(bed.KEY, "notes/call-with-ana.txt").date == ""

    _commit(tree, "the context", "2023-11-05T10:00:00+00:00")
    (tree / "notes" / "call-with-ana.txt").write_text("Call with Ana, again.\n")
    _commit(tree, "again", "2024-01-09T10:00:00+00:00")
    ingest(lark, root=tree, paths=["notes/call-with-ana.txt"], reader=bed.StubReader())

    record = _record(bed.KEY, "notes/call-with-ana.txt")
    assert (record.date, record.date_from) == ("2024-01-09", "commit")


def test_a_hidden_file_or_folder_is_not_a_document(lark, tree):
    """`.git/`, `.openfactory/`, `.okf/` are git's and the platform's own; a dot-file is a tool's."""
    (tree / ".okf" / "repos").mkdir(parents=True)
    (tree / ".okf" / "repos" / "map.yaml").write_text("modules: []\n")
    (tree / "notes" / ".DS_Store").write_bytes(b"\x00\x01")
    ingest(lark, root=tree, reader=bed.StubReader())
    assert not [p for p in Store(bed.KEY).index()["paths"] if "/." in f"/{p}"]


def test_what_a_text_cites_is_read_without_a_model():
    from openfactory.product.documents.record import cards_cited, requirements_cited

    text = ("It&#39;s REQ-0041 and req 7, requirement nº 12, requisito 003 and "
            "requirements/0099-export.md; card #512, cartão 8, issue #33, colour #0a0a0a, "
            "page#44, &#8212; and #0012.")
    assert requirements_cited(text) == [3, 7, 12, 41, 99]
    assert cards_cited(text) == ["8", "33", "512"]


def test_the_text_is_normalised_and_its_encoding_found(lark, tmp_path):
    from openfactory.adapters.extract.text import TextRow

    def read(data: bytes):
        return TextRow().extract(Source(path="a.txt", type="text", data=data, digest="0" * 64))

    said = read(b"one  \r\ntwo\r\n\r\n\r\n\r\nthree\x07\n")
    assert said.text == "one\ntwo\n\nthree" and said.notes == []
    latin = read("réunion".encode("cp1252"))
    assert latin.text == "réunion" and "cp1252" in latin.notes[0]
    binary = read(b"\x00\x01\x02 not text")
    assert not binary.readable and binary.reason == "not a text file: it holds binary data, not text"


def test_an_html_only_e_mail_is_read_as_words_and_its_script_is_dropped():
    from openfactory.adapters.extract.mail import EmailRow

    raw = (b"From: a@x.example\r\nSubject: Hi\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: text/html; charset=utf-8\r\n\r\n"
           b"<html><head><style>p{}</style></head><body><p>Approved.</p>"
           b"<script>alert('run me')</script><p>Ship it.</p></body></html>")
    said = EmailRow().extract(Source(path="m.eml", type="email", data=raw, digest="0" * 64))
    assert said.readable and "Approved." in said.text and "Ship it." in said.text
    assert "alert" not in said.text and "p{}" not in said.text


def test_a_compressed_draw_io_page_is_inflated_and_read(lark, tree):
    import base64
    import zlib
    from urllib.parse import quote

    inner = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
             '<mxCell id="2" value="Invoice" vertex="1" parent="1"/>'
             '<mxCell id="3" value="Statement" vertex="1" parent="1"/>'
             '<mxCell id="4" value="becomes" edge="1" source="2" target="3" parent="1"/>'
             '</root></mxGraphModel>')
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = base64.b64encode(deflate.compress(quote(inner).encode()) + deflate.flush()).decode()
    (tree / "diagrams" / "billing.drawio").write_text(
        f'<mxfile><diagram name="Billing">{packed}</diagram></mxfile>')

    ingest(lark, root=tree, paths=["diagrams/billing.drawio"], reader=bed.StubReader())

    assert "- Invoice → Statement: becomes" in _record(bed.KEY, "diagrams/billing.drawio").text


def test_a_pdf_whose_pages_are_pictures_goes_to_ocr_and_says_when_ocr_is_not_there(
        lark, tree, monkeypatch):
    monkeypatch.setattr("openfactory.adapters.extract.pdf.shutil.which", lambda _name: None)
    (tree / "scan.pdf").write_bytes(bed.image_pdf())

    ingest(lark, root=tree, paths=["scan.pdf"], reader=bed.StubReader())

    record = _record(bed.KEY, "scan.pdf")
    assert not record.readable and record.row == "ocr"
    assert record.reason == ("no text layer — a scanned PDF, or one made of pictures; "
                             "OCR not available: tesseract is not installed on this machine")


def test_the_ocr_row_reads_what_its_two_binaries_answer():
    from openfactory.adapters.extract.pdf import OcrRow

    ran: list[list[str]] = []

    def run(argv, **kw):
        ran.append(argv)
        if argv[0] == "/bin/pdftoppm":
            Path(argv[-1] + "-1.png").write_bytes(bed.PNG)
            Path(argv[-1] + "-2.png").write_bytes(bed.PNG)
            return type("Done", (), {"returncode": 0, "stderr": b"", "stdout": b""})()
        page = Path(argv[1]).name
        return type("Done", (), {"returncode": 0, "stderr": b"",
                                 "stdout": f"Scanned invoice text on {page}".encode()})()

    row = OcrRow(which=lambda name: f"/bin/{name}", run=run)
    said = row.extract(Source(path="scan.pdf", type="scanned", data=bed.image_pdf(),
                              digest="0" * 64))
    assert said.readable and said.from_image and said.pages == 2
    assert said.text == ("[page 1]\nScanned invoice text on page-1.png\n\n"
                         "[page 2]\nScanned invoice text on page-2.png")
    assert ran[0][:2] == ["/bin/pdftoppm", "-r"] and all(a[0] == "/bin/tesseract"
                                                          for a in ran[1:])
    image = row.extract(Source(path="shot.png", type="image", data=bed.PNG, digest="0" * 64))
    assert image.readable and image.from_image and "Scanned invoice text" in image.text

    rendered_nothing = OcrRow(which=lambda name: None if name == "pdftoppm" else f"/bin/{name}",
                              run=run)
    assert rendered_nothing.extract(Source(path="s.pdf", type="scanned", data=b"%PDF",
                                           digest="0" * 64)).reason.startswith(
        "OCR not available: pdftoppm (poppler) is not installed")


@pytest.mark.skipif(not (__import__("shutil").which("tesseract")
                         and __import__("shutil").which("pdftoppm")),
                    reason="tesseract and pdftoppm are not both installed on this machine")
def test_the_ocr_row_reads_a_rendered_page_with_the_real_binaries():
    from openfactory.adapters.extract.pdf import OcrRow

    said = OcrRow().extract(Source(path="scan.pdf", type="scanned",
                                   data=bed.text_pdf("INVOICE TOTAL 4321", "PAID IN FULL"),
                                   digest="0" * 64))
    assert said.readable and said.from_image
    assert "INVOICE" in said.text and "4321" in said.text


def test_an_empty_user_password_opens_and_a_real_one_does_not():
    from openfactory.adapters.extract.pdf import PdfRow

    def read(data: bytes):
        return PdfRow().extract(Source(path="x.pdf", type="pdf", data=data, digest="0" * 64))

    opened = read(bed.restricted_pdf("Terms that may not be printed but may be read"))
    assert opened.readable and "may not be printed" in opened.text
    closed = read(bed.protected_pdf("Board pay scales"))
    assert not closed.readable and closed.reason == "a protected PDF: it needs a password to be opened"
    assert "Board pay" not in closed.model_dump_json()
    broken = read(b"%PDF-1.4 this is not a PDF at all")
    assert not broken.readable and broken.reason.startswith("a PDF this reader could not parse")


def test_a_pdf_that_will_not_finish_is_stopped_and_said(monkeypatch):
    from openfactory.adapters.extract.pdf import PdfRow

    said = PdfRow(seconds=0.001).extract(Source(path="slow.pdf", type="pdf",
                                                data=bed.text_pdf("x"), digest="0" * 64))
    assert not said.readable and said.reason.startswith("the PDF was still being read after 0 ")


def test_the_pdf_child_is_handed_no_credential_of_this_deployment(monkeypatch):
    from openfactory.adapters.extract import pdf

    monkeypatch.setenv("OPENFACTORY_GH_TOKEN", "ghp_q7SECRETSECRETSECRETSECRET01")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-q7-secret-secret-secret")
    handed = pdf._child_env()
    assert set(handed) == {"PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING"}
    assert Path(handed["PYTHONPATH"], "openfactory", "adapters", "extract", "pdf.py").is_file()


def test_without_the_pdf_library_the_reason_names_the_extra(monkeypatch):
    import sys

    from openfactory.adapters.extract.pdf import INSTALL_PDF, read_pdf

    monkeypatch.setitem(sys.modules, "pypdf", None)
    said = read_pdf(bed.text_pdf("x"))
    assert not said.readable and said.reason == INSTALL_PDF and "'.[ingest]'" in said.reason


# ── never silent ────────────────────────────────────────────────────────────────────────────────

def test_every_file_that_cannot_be_read_is_recorded_with_why(lark, tree, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_DOCUMENTS_MAX_BYTES", "4096")
    (tree / "specs").mkdir()
    (tree / "specs" / "legacy.docx").write_bytes(b"PK\x03\x04 a word processor's zip")
    (tree / "specs" / "big.txt").write_bytes(b"x" * 5000)
    (tree / "specs" / "video.mp4").write_bytes(b"\x00\x00\x00 ftyp")
    (tree / "specs" / "lfs.pdf").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 9\n")
    (tree / "specs" / "notes.txt").write_bytes(b"\x00\x00binary in disguise")

    ingest(lark, root=tree, reader=bed.StubReader())
    why = _why(bed.KEY)

    assert why == {
        "specs/big.txt": "larger than the 4096 bytes this deployment reads (5000 bytes) — it "
                         "was not read",
        "specs/legacy.docx": "an unknown format (.docx) — no row reads it",
        "specs/lfs.pdf": "a Git LFS pointer — the file's content was never fetched into this "
                         "checkout (`git lfs pull`)",
        "specs/notes.txt": "not a text file: it holds binary data, not text",
        "specs/video.mp4": "an unknown format (.mp4) — no row reads it",
    }


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode says")
def test_a_file_this_process_may_not_open_is_a_reason_never_a_crash(lark, tree):
    locked = tree / "notes" / "locked.txt"
    locked.write_text("nobody may read this")
    locked.chmod(0)
    try:
        ingest(lark, root=tree, reader=bed.StubReader())
    finally:
        locked.chmod(0o600)
    why = _why(bed.KEY)
    assert why == {"notes/locked.txt": "it could not be opened (Permission denied)"}


def test_a_row_that_raises_or_cannot_be_built_is_a_reason_never_a_crash(lark, tree, monkeypatch):
    class Broken:
        def extract(self, source):
            raise RuntimeError("the row's own defect")

    monkeypatch.setitem(registry.EXTRACTORS, "text", lambda **_k: Broken())
    monkeypatch.setenv(registry.ROWS_ENV, "mermaid=nonexistent")
    ingest(lark, root=tree, reader=bed.StubReader())
    why = _why(bed.KEY)

    assert why["notes/call-with-ana.txt"] == "the text row failed (RuntimeError: the row's own defect)"
    assert why["diagrams/checkout.mmd"].startswith(
        "the row configured for mermaid documents cannot be built (unknown extract row "
        "'nonexistent' — known: ")


@pytest.fixture
def both_kinds(lark, tree, monkeypatch):
    """The read model of a product with an unreadable document of each audience — built the way a
    turn builds it, less the engine and the members' boards, which are not what is under test."""
    from openfactory.product import model as read_model

    (tree / "client").mkdir()
    (tree / "client" / "terms.pdf").write_bytes(bed.protected_pdf("Terms"))
    (tree / "internal" / "plano-de-demissoes.pdf").write_bytes(bed.protected_pdf("Layoffs"))
    ingest(lark, root=tree, reader=bed.StubReader())
    monkeypatch.setattr(read_model, "_engine_reads", lambda names: {
        "error": "", "floors": {}, "jobs": [], "details": {}})
    monkeypatch.setattr(read_model, "_one_member", lambda *a, **k: None)
    return read_model.build(lark, corpus=None)


INTERNAL_LINE = ("- `internal/plano-de-demissoes.pdf` — type: pdf; audience: internal; why: a "
                 "protected PDF: it needs a password to be opened")
CLIENT_LINE = ("- `client/terms.pdf` — type: pdf; audience: client; why: a protected PDF: it "
               "needs a password to be opened")


def _documents_md(model, person, *, private: bool) -> str:
    from openfactory.product import facts
    from openfactory.product.documents.record import turn_audience

    files, _gaps = facts.gather("lark", [], model=model,
                                audience=turn_audience(person, private=private))
    return files["documents.md"]


@pytest.mark.parametrize(("role", "private", "named"), [
    ("engineer", False, False),   # a room: everybody in it reads the reply
    ("admin", False, False),
    ("client", True, False),      # a client, even alone with the role
    ("engineer", True, True),     # the product's own people, in a conversation of their own
    ("admin", True, True),
])
def test_the_role_s_facts_name_an_internal_document_only_to_a_turn_that_may_read_it(
        both_kinds, role, private, named):
    from openfactory.product.speaker import Person

    said = _documents_md(both_kinds, Person(id="p1", role=role), private=private)

    assert "7 read, 2 could not be read" in said
    assert CLIENT_LINE in said, "the client's document is named to every turn"
    assert "EXISTS in the context repository and could not be read" in said
    if named:
        assert INTERNAL_LINE in said and "not listed here" not in said
    else:
        assert "demissoes" not in said and "Layoffs" not in said
        assert "1 internal document(s) that could not be read are not listed here" in said


def test_a_turn_nobody_named_and_a_pack_another_turn_may_read_name_no_internal_document(
        both_kinds):
    """The default is the client's: a caller that says nothing about the turn gets the narrow
    rendering, and so does a view another conversation's turn may read (`_the_read_model`)."""
    from openfactory.product import facts
    from openfactory.product.module import _the_read_model

    files, _ = facts.gather("lark", [], model=both_kinds)
    assert "demissoes" not in files["documents.md"]

    module = SimpleNamespace(project=None, _facts_for="p1", _documents_audience="internal",
                             _product_model=both_kinds, _turn_view="/views/mine")
    assert _the_read_model(module, "/views/mine")["audience"] == "internal"
    assert _the_read_model(module, "/views/shared")["audience"] == "client"
    assert _the_read_model(module, "")["audience"] == "client"


def test_a_turn_s_documents_are_decided_by_the_speaker_and_the_conversation(monkeypatch):
    """Through the path a turn takes: `answer` hands the facts and the briefing the audience its
    speaker and its conversation make (the briefing's register rule, ADR-0052 D10)."""
    from openfactory.product.config import ProductLink
    from openfactory.product.loader import ProductContext
    from openfactory.product.module import ProductModule
    from openfactory.product.speaker import ADMIN, CLIENT, ENGINEER, Person

    seen: list = []
    module = ProductModule(bed.project(Path("/tmp")), context=ProductContext(
        link=ProductLink(active=True, docs_repo="lark/context")))
    monkeypatch.setattr(module, "_workspace", lambda: (None, None))
    monkeypatch.setattr(module, "already_asked", lambda _q: "")

    class _Role:
        def answer(self, **_kw):
            seen.append(module._documents_audience)
            return SimpleNamespace(ok=True, text="ok", reading=None)

    monkeypatch.setattr(module, "_role", lambda **_kw: _Role())
    monkeypatch.setattr("openfactory.product.module._bound_answer", lambda _m, answer: answer)
    for role, private in ((ENGINEER, True), (ADMIN, True), (ENGINEER, False), (CLIENT, True)):
        module.answer("what could not be read?", speaker=Person(id="p1", role=role),
                      private=private)

    assert seen == ["internal", "internal", "client", "client"]


def test_the_briefing_names_a_document_only_to_a_turn_that_may_read_it(both_kinds):
    from openfactory.product import briefing

    def line(audience: str) -> str:
        said = briefing.render(both_kinds, audience=audience)
        found = [x for x in said.lines if "document(s) in the context repository" in x]
        assert len(found) == 1, said.lines
        return found[0]

    internal = line("internal")
    assert "2 document(s) in the context repository could not be read: " in internal
    assert "internal/plano-de-demissoes.pdf" in internal and "client/terms.pdf" in internal
    client = line("client")
    assert "demissoes" not in client and "client/terms.pdf" in client
    assert "1 internal document(s) that could not be read, not named here" in client
    assert "(document records — read " in client, "its source, and the pass's own age"


@pytest.mark.parametrize(("audience", "named"), [("client", False), ("internal", True)])
def test_the_module_briefs_in_the_audience_its_turn_was_answered_in(both_kinds, audience,
                                                                     named):
    from openfactory.product.module import _the_briefing

    module = SimpleNamespace(project=SimpleNamespace(name="lark"), _facts_for="p1",
                             _raw_diagnosis=False, _documents_audience=audience,
                             _product_model=both_kinds)
    said = _the_briefing(module).text
    assert ("internal/plano-de-demissoes.pdf" in said) is named
    assert "client/terms.pdf" in said


def test_records_that_cannot_be_read_are_a_gap_in_the_role_s_facts_never_none(lark, monkeypatch):
    from openfactory.product import model as read_model

    documents_dir(bed.KEY).mkdir(parents=True)
    (documents_dir(bed.KEY) / "index.json").write_text("[not an index")
    model = read_model.ProductModel(key=bed.KEY, members=["lark"])

    assert read_model._documents(model) is None
    assert any("could not be read" in gap and "not none" in gap for gap in model.gaps)


# ── what is never done ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("xml", [
    # an entity declared in the document's own DTD — the billion laughs start here
    '<!DOCTYPE m [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><mxfile><diagram name="&b;"/>'
    '</mxfile>',
    # an external entity: a file on this machine
    '<!DOCTYPE m [<!ENTITY x SYSTEM "file:///etc/passwd">]><mxfile><diagram name="&x;"/></mxfile>',
    # a parameter entity reaching out for a DTD
    '<!DOCTYPE m [<!ENTITY % p SYSTEM "http://127.0.0.1:9/evil.dtd"> %p;]><mxfile/>',
])
def test_no_xml_entity_is_ever_declared_expanded_or_fetched(xml):
    from openfactory.adapters.extract.markup import DrawioRow, SvgRow

    for row in (DrawioRow(), SvgRow()):
        said = row.extract(Source(path="x", type="drawio", data=xml.encode(), digest="0" * 64))
        assert not said.readable and "refused" in said.reason, said.reason
        assert "root:" not in said.model_dump_json()


def test_a_document_type_of_its_own_is_refused_even_when_it_declares_no_entity():
    """The subset is refused whole — an attribute default a DTD injects is content nobody wrote
    in the document, and the subset is where every entity would be declared."""
    from openfactory.adapters.extract.markup import DrawioRow

    xml = b'<!DOCTYPE mxfile [<!ATTLIST diagram name CDATA "injected">]><mxfile><diagram/></mxfile>'
    said = DrawioRow().extract(Source(path="x", type="drawio", data=xml, digest="0" * 64))
    assert not said.readable and "declares a document type of its own" in said.reason


def test_the_tree_an_xml_document_builds_is_bounded(monkeypatch):
    from openfactory.adapters.extract import markup

    deep = b"<a>" * (markup.MAX_DEPTH + 1) + b"</a>" * (markup.MAX_DEPTH + 1)
    said = markup.SvgRow().extract(Source(path="d.svg", type="svg", data=deep, digest="0" * 64))
    assert not said.readable and f"nests deeper than {markup.MAX_DEPTH} levels" in said.reason
    monkeypatch.setattr(markup, "MAX_ELEMENTS", 10)
    wide = b"<svg>" + b"<text>x</text>" * 11 + b"</svg>"
    said = markup.SvgRow().extract(Source(path="w.svg", type="svg", data=wide, digest="0" * 64))
    assert not said.readable and "more than 10 elements" in said.reason


def test_a_plain_doctype_with_nothing_declared_is_read():
    from openfactory.adapters.extract.markup import SvgRow

    svg = (b'<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
           b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns="http://www.w3.org/2000/svg">'
           b'<title>Revenue</title><text x="1">Q1 <tspan>1200</tspan></text></svg>')
    said = SvgRow().extract(Source(path="c.svg", type="svg", data=svg, digest="0" * 64))
    assert said.readable and said.title == "Revenue" and "Q1 1200" in said.text
    shapes = SvgRow().extract(Source(path="s.svg", type="svg", digest="0" * 64,
                                     data=b'<svg><rect width="1" height="1"/></svg>'))
    assert not shapes.readable and "only shapes" in shapes.reason


def test_a_compressed_page_cannot_inflate_past_its_ceiling(monkeypatch):
    import base64
    import zlib

    from openfactory.adapters.extract import markup

    monkeypatch.setattr(markup, "MAX_INFLATED", 1024)
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
    bomb = base64.b64encode(deflate.compress(b"<" * 50_000) + deflate.flush()).decode()
    said = markup.DrawioRow().extract(Source(
        path="b.drawio", type="drawio", digest="0" * 64,
        data=f'<mxfile><diagram name="p">{bomb}</diagram></mxfile>'.encode()))
    assert not said.readable and "inflates past" in said.reason


def test_no_read_leaves_the_tree(lark, tree, tmp_path):
    """A link out of the repository is recorded and never followed — its target's words reach no
    record — and an event cannot name a path outside, above, or hidden."""
    secret = tmp_path / "outside" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("q7-the-deployment-secret")
    (tree / "leak.txt").symlink_to(secret)
    (tree / "leak-folder").symlink_to(secret.parent, target_is_directory=True)

    report = ingest(lark, root=tree, reader=bed.StubReader())
    events = ingest(lark, root=tree, reader=bed.StubReader(), paths=[
        "../outside/secret.txt", str(secret), ".git/config", "leak-folder/secret.txt", "notes"])

    why = _why(bed.KEY)
    link = "a symbolic link — it is not followed, so no read leaves the context repository"
    assert why["leak.txt"] == link and why["leak-folder"] == link
    assert dict(events.refused) == {
        "../outside/secret.txt": "not a path inside the context repository",
        str(secret): "not a path inside the context repository",
        ".git/config": "a hidden path — git's or the platform's own, not a document",
        "leak-folder/secret.txt": "it leaves the context repository",
        "notes": "a folder — name the documents in it"}
    assert events.ingested == []
    for stored in documents_dir(bed.KEY).rglob("*.json"):
        assert "q7-the-deployment-secret" not in stored.read_text()
    assert "leak.txt" in report.ingested


# ── the audience label ──────────────────────────────────────────────────────────────────────────

def test_a_document_marked_internal_never_loses_the_label(lark, tree):
    (tree / "internal" / "nda.pdf").write_bytes(bed.protected_pdf("NDA"))
    (tree / "internal" / "old.docx").write_bytes(b"PK\x03\x04 no row reads this")
    (tree / "client").mkdir()
    (tree / "client" / "old.docx").write_bytes(b"PK\x03\x04 no row reads this")
    (tree / "client" / "welcome.md").write_text("# Welcome\n")
    (tree / "client" / "confidential").mkdir()
    (tree / "client" / "confidential" / "pricing.md").write_text("---\naudience: client\n---\nx\n")
    (tree / "client" / "odd.md").write_text("---\naudience: board-only\n---\nx\n")
    (tree / "client" / "team.md").write_text("---\nvisibility: internal\n---\nx\n")
    ingest(lark, root=tree, reader=bed.StubReader())

    def label(path):
        record = _record(bed.KEY, path)
        return record.audience, record.audience_from

    # the folder says internal and the front matter says client: internal
    assert label("internal/2024-03-12-board-minutes.md") == ("internal", "path and front matter")
    # unreadable, and still internal — whether a row was asked or the format stopped it first
    assert label("internal/nda.pdf") == ("internal", "path")
    assert label("internal/old.docx") == ("internal", "path")
    assert label("client/old.docx") == ("client", "path")
    assert label("client/welcome.md") == ("client", "path")
    assert label("client/confidential/pricing.md") == ("internal", "path and front matter")
    assert label("client/team.md") == ("internal", "path and front matter")
    assert label("client/odd.md") == ("internal", "path and front matter")
    assert any("'board-only' is not a label" in n for n in _record(bed.KEY, "client/odd.md").notes)
    # nothing declared: internal, never the client's
    assert label("notes/call-with-ana.txt") == ("internal", "default")
    assert label("README.md") == ("client", "front matter")
    shown = {d["path"]: d["audience"] for d in _every_unreadable(bed.KEY)}
    assert shown == {"internal/nda.pdf": "internal", "internal/old.docx": "internal",
                     "client/old.docx": "client"}


def test_a_record_read_back_without_a_label_or_with_a_strange_one_is_internal():
    base = dict(product=bed.KEY, path="a.md", digest="0" * 64, readable=True)
    assert DocumentRecord(**base).audience == "internal"
    assert DocumentRecord(**base, audience="").audience == "internal"
    assert DocumentRecord(**base, audience="everyone-please").audience == "internal"
    assert DocumentRecord(**base, audience="CLIENT").audience == "client"
    with pytest.raises(ValueError, match="must say why"):
        DocumentRecord(product=bed.KEY, path="a.md", digest="0" * 64, readable=False)


# ── the model's part: once per version, and marked ─────────────────────────────────────────────

def test_the_summary_and_the_decisions_are_written_once_and_marked_as_a_model_s(lark, tree):
    long = tree / "minutes" / "2024-04-02-steering.md"
    long.parent.mkdir()
    long.write_text("# Steering, 2 April 2024\n\n" + "We reviewed the export. " * 20
                    + "\n\nDecided: the export moves to CSV.\n")
    reader = bed.StubReader()

    ingest(lark, root=tree, reader=reader)
    ingest(lark, root=tree, reader=reader)

    record = _record(bed.KEY, "minutes/2024-04-02-steering.md")
    assert reader.read_paths == ["minutes/2024-04-02-steering.md"], "short texts are not summarised"
    assert record.summary == "The board moved the export to CSV."
    assert [d.model_dump() for d in record.decisions] == [
        {"text": "the monthly export moves to CSV", "date": "2024-03-12"}]
    assert record.derived.summary and record.derived.decisions and not record.derived.text
    assert (record.derived.by, record.derived.attempts, record.derived.error) == (
        "stub/reader", 1, "")


def test_a_reading_that_failed_is_retried_a_bounded_number_of_times_without_reading_the_file_again(
        lark, tree, monkeypatch):
    from openfactory.product.documents.ingest import MODEL_ATTEMPTS

    long = tree / "long.md"
    long.write_text("# Long\n\n" + "A sentence that goes on. " * 30)
    calls = bed.count_extractions(monkeypatch)
    failing = bed.StubReader(error="the model did not answer (rate limited)")

    for _ in range(MODEL_ATTEMPTS + 2):
        ingest(lark, root=tree, paths=["long.md"], reader=failing)

    assert calls == [("markdown", "long.md")]
    assert failing.read_paths == ["long.md"] * MODEL_ATTEMPTS
    record = _record(bed.KEY, "long.md")
    assert record.summary == "" and not record.derived.summary
    assert record.derived.error == "the model did not answer (rate limited)"
    assert record.derived.attempts == MODEL_ATTEMPTS
    assert Store(bed.KEY).index()["paths"]["long.md"]["reading"] == ""


def test_a_reading_retried_after_a_failure_lands_on_the_same_version(lark, tree):
    long = tree / "long.md"
    long.write_text("# Long\n\n" + "A sentence that goes on. " * 30)
    ingest(lark, root=tree, reader=bed.StubReader(error="down"))
    assert Store(bed.KEY).index()["paths"]["long.md"]["reading"] == "pending"

    report = ingest(lark, root=tree, reader=bed.StubReader())

    record = _record(bed.KEY, "long.md")
    assert report.reread == ["long.md"] and report.ingested == []
    assert record.derived.summary and record.derived.attempts == 2 and record.derived.error == ""


def test_the_vision_row_asks_the_model_once_in_a_room_holding_only_the_image():
    from openfactory.adapters.extract.vision import VisionRow

    asked = []

    class Harness:
        name, model = "stub_harness", "stub-model"

        def ask(self, *, sandbox, workspace, prompt, phase):
            asked.append((sorted(p.name for p in Path(workspace.path).iterdir()), prompt, phase))
            return type("Res", (), {"ok": True, "summary": "", "raw_output":
                                    '{"type":"result","result":"A flowchart: Cart to Payment."}'})()

    said = VisionRow(harness=Harness()).extract(Source(path="d/flow.PNG", type="image",
                                                       data=bed.PNG, digest="0" * 64))
    assert said.readable and said.from_image and said.model == "stub_harness/stub-model"
    assert said.text == "A flowchart: Cart to Payment."
    assert len(asked) == 1 and asked[0][0] == ["image.png"] and asked[0][2] == "documents_vision"
    assert "`image.png`" in asked[0][1] and "ILLEGIBLE" in asked[0][1]


def test_an_illegible_image_and_an_absent_model_are_reasons():
    from openfactory.adapters.extract.vision import VisionRow

    class Blind:
        def ask(self, **_kw):
            return type("Res", (), {"ok": True, "summary": "ILLEGIBLE.", "raw_output": ""})()

    source = Source(path="x.png", type="image", data=bed.PNG, digest="0" * 64)
    blind = VisionRow(harness=Blind()).extract(source)
    assert not blind.readable and blind.from_image and blind.reason.startswith("an illegible image")
    nobody = VisionRow().extract(source)
    assert not nobody.readable and nobody.reason.startswith("no model could describe this image: "
                                                            "no model is called inside the test")


def test_the_model_reader_hands_the_text_in_a_room_and_parses_its_json():
    from openfactory.product.documents.reading import ModelReader

    seen = []

    class Harness:
        name, model = "stub_harness", "m1"

        def ask(self, *, sandbox, workspace, prompt, phase):
            seen.append(((Path(workspace.path) / "document.txt").read_text(), phase))
            return type("Res", (), {"ok": True, "summary": "", "raw_output": (
                '{"type":"result","result":"{\\"summary\\": \\"Minutes.\\", \\"decisions\\": '
                '[{\\"text\\": \\"CSV\\", \\"date\\": \\"2024-03-12\\"}, \\"XLSX dropped\\"]}"}')})()

    record = DocumentRecord(product=bed.KEY, path="m.md", digest="0" * 64, readable=True,
                            type="markdown", text="the minutes' text")
    reading = ModelReader(harness=Harness()).read(record)
    assert seen == [("the minutes' text", "documents_record")]
    assert reading.summary == "Minutes." and reading.by == "stub_harness/m1"
    assert [(d.text, d.date) for d in reading.decisions] == [("CSV", "2024-03-12"),
                                                             ("XLSX dropped", "")]


# ── the seam ────────────────────────────────────────────────────────────────────────────────────

def test_rows_are_chosen_by_configuration(monkeypatch):
    monkeypatch.delenv(registry.ROWS_ENV, raising=False)
    assert registry.row_for("image") == "vision" and registry.row_for("scanned") == "ocr"
    monkeypatch.setenv(registry.ROWS_ENV, "image=ocr, scanned = acme_ocr, nonsense, video=x")
    assert registry.row_for("image") == "ocr" and registry.row_for("scanned") == "acme_ocr"
    assert registry.row_for("pdf") == "pdf" and registry.row_for("video") == ""
    assert registry.document_type("A/B/Report.PDF") == "pdf"
    assert registry.document_type("x.drawio.xml") == "drawio"
    assert registry.document_type("x.xlsx") == ""
    with pytest.raises(ValueError, match=r"unknown extract row 'acme_ocr' — known: .*vision"):
        registry.build_extractor("acme_ocr")


def test_every_shipped_row_answers_the_port():
    from openfactory.adapters.extract.base import Extractor

    for kind in registry.EXTRACTORS:
        assert isinstance(registry.build_extractor(kind), Extractor), kind
    assert set(registry.DEFAULT_ROWS.values()) <= set(registry.EXTRACTORS)
    assert set(registry.TYPES.values()) <= set(registry.DEFAULT_ROWS)


def test_the_records_live_under_the_product_s_state_directory(lark, tree):
    from openfactory.paths import product_state_dir

    ingest(lark, root=tree, reader=bed.StubReader())
    assert documents_dir(bed.KEY) == product_state_dir(bed.KEY) / "documents"
    records = sorted(documents_dir(bed.KEY).glob("records/*/*.json"))
    assert len(records) == 7
    assert all(DocumentRecord.model_validate_json(p.read_text()).product == bed.KEY
               for p in records)


def test_a_record_is_read_back_only_as_what_it_claims_to_be(lark, tree):
    ingest(lark, root=tree, reader=bed.StubReader())
    store = Store(bed.KEY)
    line = store.index()["paths"]["README.md"]
    other = store.record_path("notes/call-with-ana.txt",
                              store.index()["paths"]["notes/call-with-ana.txt"]["digest"])
    store.record_path("README.md", line["digest"]).write_text(other.read_text())
    assert store.get("README.md", line["digest"]) is None
    with pytest.raises(ValueError):
        store.record_path("README.md", "../../escape")


def _heard(monkeypatch) -> list[dict]:
    """What reached the door: every announcement `door.announce_now` was asked to make."""
    from openfactory.product import door

    heard: list[dict] = []
    monkeypatch.setattr(door, "announce_now", lambda project, **kw: heard.append(kw) or True)
    return heard


def test_a_document_brought_to_a_conversation_is_announced_there_through_the_door(
        lark, tree, monkeypatch):
    """#267 slice 3's `document_ingested`, reached by the ingestion's own producer: the event
    arrives at the door, once, in the conversation the document was brought to."""
    heard = _heard(monkeypatch)
    (tree / "client").mkdir()
    (tree / "client" / "sla.md").write_text("# SLA v3\n\nAvailability of 99.9 percent.\n")

    ingest(lark, root=tree, paths=["client/sla.md"], conversation="person:ana",
           reader=bed.StubReader())
    ingest(lark, root=tree, paths=["client/sla.md"], conversation="person:ana",
           reader=bed.StubReader())

    assert len(heard) == 1, "a version is announced once"
    assert heard[0]["conversation"] == "person:ana" and heard[0]["room"] == ""
    assert "client/sla.md" in heard[0]["text"] and heard[0]["id"].startswith("document_ingested-")


def test_an_internal_document_is_announced_only_in_the_private_conversation_it_was_brought_to(
        lark, tree, monkeypatch):
    heard = _heard(monkeypatch)
    (tree / "internal" / "plano.md").write_text("# O plano\n")
    (tree / "internal" / "outro.md").write_text("# Outro\n")
    (tree / "internal" / "terceiro.md").write_text("# Terceiro\n")

    ingest(lark, root=tree, paths=["internal/plano.md"], conversation="person:ana",
           reader=bed.StubReader())
    ingest(lark, root=tree, paths=["internal/outro.md"], reader=bed.StubReader())
    ingest(lark, root=tree, paths=["internal/terceiro.md"], conversation="lark",
           reader=bed.StubReader())

    assert [h["conversation"] for h in heard] == ["person:ana"], heard
    assert "outro" not in str(heard) and "terceiro" not in str(heard)


def test_the_schedule_announces_a_new_client_document_to_the_room_and_nothing_else(
        lark, tree, monkeypatch):
    """The first reading of a product is a backfill, not news; after it, a NEW document the
    room may read is said there — never an internal one, a new version of a known one, or one
    that could not be read."""
    heard = _heard(monkeypatch)
    ingest(lark, root=tree, reader=bed.StubReader())
    assert heard == [], "the backfill is announced to nobody"

    (tree / "client").mkdir()
    (tree / "client" / "new.md").write_text("# New\n")
    (tree / "internal" / "new.md").write_text("# Internal and new\n")
    (tree / "client" / "locked.pdf").write_bytes(bed.protected_pdf("Locked"))
    (tree / "notes" / "call-with-ana.txt").write_text("rewritten\n")
    report = ingest(lark, root=tree, reader=bed.StubReader())

    assert [(h["conversation"], h["room"]) for h in heard] == [("lark", "lark")]
    assert "client/new.md" in heard[0]["text"]
    assert report.told == 1 and "1 announced" in report.sentence()


def test_a_pass_announces_at_most_a_few_new_documents(lark, tree, monkeypatch):
    from openfactory.product.documents.ingest import TOLD_PER_PASS

    heard = _heard(monkeypatch)
    ingest(lark, root=tree, reader=bed.StubReader())
    (tree / "client").mkdir()
    for n in range(TOLD_PER_PASS + 3):
        (tree / "client" / f"new-{n}.md").write_text(f"# New {n}\n")

    report = ingest(lark, root=tree, reader=bed.StubReader())

    assert len(heard) == report.told == TOLD_PER_PASS and report.untold == 3
    assert f"a pass tells at most {TOLD_PER_PASS}" in report.sentence()


def test_the_row_announces_in_the_conversation_of_the_person_who_brought_the_file(
        lark, tree, monkeypatch):
    import asyncio
    import types

    from openfactory import actions
    from openfactory.product.domain import Domain
    from openfactory.product.module import ProductModule
    from openfactory.registry import ProjectRegistry

    heard = _heard(monkeypatch)
    ProjectRegistry().add(lark)
    monkeypatch.setattr(ProductModule, "context", lambda self, **_k: types.SimpleNamespace(
        docs_path=str(tree), docs_commit="c0ffee", reason="", domain=Domain()))
    monkeypatch.setattr("openfactory.product.documents.ingest.ModelReader",
                        lambda **_k: bed.StubReader())
    (tree / "internal" / "plano.md").write_text("# O plano\n")
    ana = actions.Actor(id="ana", display="Ana", via="panel", admin=True,
                        conversation="person:ana")

    out = asyncio.run(actions.perform("product_ingest", by=ana, project="lark",
                                      path="internal/plano.md"))

    assert out.ok and [h["conversation"] for h in heard] == ["person:ana"]


def test_the_documents_are_listed_to_each_credential_as_it_may_read_them(two_credentials):
    """#335: the product owner's page lists the product's documents, not only the ones that
    failed — by the same rule: an internal document's name reaches only a credential that may
    read the floor."""
    product, floor = two_credentials("product-secret"), two_credentials("floor-secret")
    assert product["documents"], "the product's documents are not listed at all"
    assert {d["audience"] for d in product["documents"]} == {"client"}
    assert "documents_internal" not in product
    assert {d["audience"] for d in floor["documents"]} == {"client"}
    assert {d["audience"] for d in floor["documents_internal"]} == {"internal"}
    assert set(product["documents"][0]) == {"path", "title", "type", "audience"}
    assert product["listed_all"] is True

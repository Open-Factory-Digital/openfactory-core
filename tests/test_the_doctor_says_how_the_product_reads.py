"""`openfactory doctor` says how this machine searches a product's memory and reads its documents
(#337).

A deployment made from the published images searched by exact words only and could not read a
scanned PDF, and nothing said so: an operator found out from worse answers. Two lines now say it —
the search (by meaning, and which model, verified; or by words, and why) and the reading (PDF text
layer, OCR and its languages, images). Neither is a FAIL: a product whose search is degraded still
answers, so a degraded mode is a pass whose note the verdict repeats, with its remedy.
"""
from __future__ import annotations

import pytest

from openfactory import doctor
from openfactory.doctor import ReadingState, diagnose
from tests.test_doctor import _probes

SEMANTIC = ReadingState(search="semantic", search_detail="minishlab/potion-multilingual-128M at "
                        "revision 73908c3, verified by its weights' SHA-256, in /opt/models/m",
                        pdf_text=True, ocr=True, ocr_detail="languages: por+eng")


def _lines(state: ReadingState) -> dict:
    report = diagnose(_probes(product_reading=lambda: state))
    return {f.check: f for f in report.findings if f.check.startswith("product_")}


def test_a_healthy_product_is_said_to_search_by_meaning_and_read_everything():
    lines = _lines(SEMANTIC)
    search, reading = lines["product_search"], lines["product_reading"]
    assert search.ok and "by meaning" in search.message and "verified" in search.message
    assert not search.note
    assert reading.ok and "text layer read" in reading.message
    assert "read by OCR (languages: por+eng)" in reading.message
    assert "charged per image" in reading.message and not reading.note


def test_search_by_words_is_a_pass_that_says_why_and_how_to_fix_it():
    state = ReadingState(search="words", search_detail="no local embedding model is configured",
                         pdf_text=True, ocr=True, ocr_detail="languages: por+eng")
    search = _lines(state)["product_search"]
    assert search.ok, "a product whose search is degraded still answers — never a FAIL"
    assert "exact words, metadata and time only" in search.message
    assert "no local embedding model" in search.message
    assert "OPENFACTORY_EMBED_MODEL" in search.note and ".[embed]" in search.note


def test_search_turned_off_on_purpose_says_so():
    state = ReadingState(search="off", search_detail="turned off on purpose (OPENFACTORY_EMBED="
                         "none)", pdf_text=True, ocr=True, ocr_detail="languages: por")
    search = _lines(state)["product_search"]
    assert search.ok and "on purpose" in search.message and "unset" in search.note


@pytest.mark.parametrize(("state", "said", "remedy"), [
    (ReadingState(search="semantic", search_detail="m", pdf_text=True, ocr=False,
                  ocr_detail="tesseract is not installed on this machine"),
     "scanned PDFs: NOT read — tesseract is not installed", "poppler-utils"),
    (ReadingState(search="semantic", search_detail="m", pdf_text=False, ocr=True,
                  ocr_detail="languages: eng"),
     "PDFs: NOT read — the `ingest` extra", ".[ingest]"),
    (ReadingState(search="semantic", search_detail="m", pdf_text=True, ocr=True,
                  ocr_detail="languages: eng", ocr_missing=("por",)),
     "not in por, which is not installed", "tesseract-ocr-por"),
])
def test_what_cannot_be_read_is_named_with_its_remedy(state, said, remedy):
    reading = _lines(state)["product_reading"]
    assert reading.ok and said in reading.message
    assert remedy in reading.note


def test_a_project_without_a_product_is_not_told_about_its_reading():
    report = diagnose(_probes())
    assert not [f for f in report.findings if f.check in ("product_search", "product_reading")]


def test_a_probe_that_raises_is_a_finding_not_a_crash():
    def boom():
        raise RuntimeError("the store would not open")

    lines = {f.check: f for f in diagnose(_probes(product_reading=boom)).findings}
    assert not lines["product_search"].ok and "the store would not open" in lines[
        "product_search"].message


def test_the_real_probe_reads_the_rows_own_answers(monkeypatch, tmp_path):
    """The probe asks the platform's rows, never a second opinion: no model configured is the
    embed row's own sentence, and a tesseract with English only names Portuguese as missing."""
    import shutil
    import subprocess

    from openfactory.adapters.embed import registry
    from openfactory.adapters.embed.local import MODEL_ENV

    monkeypatch.delenv(registry.KIND_ENV, raising=False)
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv("OPENFACTORY_OCR_LANGS", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")

    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout=b"List of available languages (2):\n"
                                                         b"eng\nosd\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    state = doctor._reading_probe()
    assert state.search == "words" and "no local embedding model is configured" in \
        state.search_detail
    assert state.ocr and state.ocr_detail == "languages: eng" and state.ocr_missing == ("por",)
    assert state.image_row == "vision"


@pytest.mark.parametrize("library", [True, False])
def test_a_verified_model_is_semantic_only_with_its_library(tmp_path, monkeypatch, library):
    """The doctor never loads the model — a gigabyte to say "on" — and never says "on" for one the
    row could not load: the folder, the files, the digest AND the library are what it checks."""
    import importlib.util
    import sys

    from openfactory.adapters.embed import registry
    from openfactory.adapters.embed.local import DIGEST_ENV, MODEL_ENV
    from tests.test_the_hybrid_index import _model_folder

    folder, digest = _model_folder(tmp_path)
    monkeypatch.delenv(registry.KIND_ENV, raising=False)
    monkeypatch.setenv(MODEL_ENV, str(folder))
    monkeypatch.setenv(DIGEST_ENV, digest)
    monkeypatch.delitem(sys.modules, "model2vec", raising=False)
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: (
        (object() if library else None) if name == "model2vec" else real(name, *a)))

    mode, detail = registry.readiness()
    if library:
        assert mode == "semantic" and "declared" in detail and str(folder) in detail
    else:
        assert mode == "words" and "`embed` extra" in detail
    assert "model2vec" not in sys.modules, "the diagnostic imported the library"


def test_a_model_nobody_pinned_or_declared_is_never_said_to_be_on(tmp_path, monkeypatch):
    from openfactory.adapters.embed import registry
    from openfactory.adapters.embed.local import DIGEST_ENV, MODEL_ENV
    from tests.test_the_hybrid_index import _model_folder

    folder, _digest = _model_folder(tmp_path)
    monkeypatch.delenv(registry.KIND_ENV, raising=False)
    monkeypatch.setenv(MODEL_ENV, str(folder))
    monkeypatch.delenv(DIGEST_ENV, raising=False)
    mode, detail = registry.readiness()
    assert mode == "words" and "not one this platform pins" in detail

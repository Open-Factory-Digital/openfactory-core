"""Intake classification and the teaching answer (#33 slice 7, holes 5 and 6).

A message was a broken promise (`[[DEFEITO`) or a wish (`[[PEDIDO]]`) — or the system WORKING AS
DESIGNED, which had no shape: the role registered a defect that was not one, or argued a wish
nobody had. `[[USO: <concept file>; REQ-<n>]]` is the third reading, and the reply that carries
it TEACHES: how it works today, the file that does it, the requirement that promises it. Every
reading names its evidence (`[[EVIDENCIA]]`), and `product/reading.py` does the half a model
cannot: it checks that evidence against the bundle (present? fresh?) and the corpus (does the
requirement exist?) and BOUNDS the confidence a person is shown — `baixa` for nothing checkable,
`média` for a stale concept or a missing requirement, `alta` only when the evidence stands. The
case moves to `classified` when the role has read it.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.knowledge.contracts import Concept, ConceptSource, Gap, OkfManifest
from openfactory.knowledge.okf import OKF_INDEX_FILE, write_okf
from openfactory.product import case
from openfactory.product.case import CLASSIFIED, COLLECTING, PROPOSED, current, note_turn
from openfactory.product.reading import ALTA, BAIXA, MEDIA, bound, render_reading
from openfactory.product.role import (
    _EVIDENCE_RE,
    _TEACH_RE,
    EVIDENCE_MARKER,
    TEACH_MARKER,
    ProductAnswer,
    ProductRole,
    Reading,
)
from openfactory.product.voice import reading_caveat

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr("openfactory.paths.project_memory_dir",
                        lambda project: tmp_path / "memory" / str(getattr(project, "name", "")))
    case._reset_for_tests()
    yield
    case._reset_for_tests()


# ── the markers ─────────────────────────────────────────────────────────────────────────────────

def test_the_two_markers_and_their_shapes():
    assert TEACH_MARKER == "[[USO" and EVIDENCE_MARKER == "[[EVIDENCIA"
    m = _TEACH_RE.search("ok\n[[USO: concepts/policy/billing.md; REQ-12]]")
    assert m and m.group("evidence") == "concepts/policy/billing.md; REQ-12"
    assert _TEACH_RE.search("[[USO]]") is not None
    m = _EVIDENCE_RE.search("[[EVIDENCIA: concepts/policy/billing.md, REQ-0012, Tax rules]]")
    assert m and "Tax rules" in m.group("evidence")


def test_the_answer_model_has_the_reading_and_it_defaults_off():
    answer = ProductAnswer(ok=True, text="x")
    assert answer.is_misuse is False and answer.reading is None


def test_the_prompt_teaches_the_third_reading_after_the_gestures_and_asks_for_evidence():
    """After the four gestures (defect, card, order, queue) and before the decisions: the third
    reading, then the evidence every reading owes. The card paragraph keeps following the defect
    one immediately — #44's guard pins that, and it is why the reading does not sit between."""
    src = (ROOT / "openfactory" / "product" / "role.py").read_text(encoding="utf-8")
    queue_at = src.index("NOT this gesture — those are the other markers or no marker at all")
    teach_at = src.index("[[USO: <concept file>; REQ-<n>]]", queue_at)
    evidence_at = src.index("[[EVIDENCIA: <the concept files you relied on>", teach_at)
    finally_at = src.index("FINALLY: if your reply ASKS A PERSON TO DECIDE", evidence_at)
    assert 0 < teach_at - queue_at < 800 and 0 < finally_at - evidence_at < 600
    assert "never by how sure you sound" in src


def test_a_teaching_reply_is_parsed_with_its_evidence_and_stripped(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _h = _answering_module(
        tmp_path, answer="Funciona assim hoje: o desconto aplica antes do imposto — "
                         "`billing/rules.py:14`, e o REQ-12 promete isso.\n"
                         "[[USO: concepts/policy/billing.md; REQ-12]]\n"
                         "[[EVIDENCIA: concepts/policy/billing.md; REQ-12]]")
    answer = mod.answer("o desconto está vindo antes do imposto, é bug?")
    assert answer.is_misuse and not answer.is_defect and not answer.is_request
    assert answer.reading.kind == "misuse"
    assert answer.reading.concepts == ["concepts/policy/billing.md"]
    assert answer.reading.requirements == [12]
    assert "[[USO" not in answer.text and "[[EVIDENCIA" not in answer.text
    assert answer.text.startswith("Funciona assim hoje")


def test_a_defect_reply_carries_its_evidence_and_a_plain_answer_carries_none(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _h = _answering_module(tmp_path, answer="Isso contraria o prometido.\n"
                                                 "[[DEFEITO:REQ-7]]\n[[EVIDENCIA: Tax rules; REQ-7]]")
    answer = mod.answer("o total sai errado")
    assert answer.is_defect and answer.reading.kind == "defect"
    assert answer.reading.concepts == ["Tax rules"] and answer.reading.requirements == [7]
    mod, _h = _answering_module(tmp_path, answer="O prazo é dia 5.")
    assert mod.answer("qual o prazo?").reading is None


# ── the bound ───────────────────────────────────────────────────────────────────────────────────

def _bundle(tmp_path: Path, *, stale: bool = False) -> Path:
    bundle = tmp_path / "bundle"
    concept = Concept(type="policy", title="Billing rules", description="d", what_it_does="w",
                      sources=[ConceptSource(repo="r", path="billing/rules.py", commit="c",
                                             fingerprint="f", lines="1-2")])
    gaps = [Gap(kind="stale", path="billing/rules.py",
                detail="'Billing rules' no longer matches the source and was not re-authored")] \
        if stale else []
    write_okf(bundle, manifest=OkfManifest(source_commit="c", gaps=gaps), concepts=[concept])
    (bundle / OKF_INDEX_FILE).write_text("# index\n", encoding="utf-8")
    return bundle


def _corpus(*numbers: int):
    return SimpleNamespace(by_number=lambda n: object() if n in numbers else None)


def test_evidence_that_stands_is_alta(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["concepts/policy/billing-rules.md"],
                        requirements=[12]), bundle_dir=_bundle(tmp_path), corpus=_corpus(12))
    assert got.confidence == ALTA and got.bounded_by == ""
    assert got.verified == {"concepts": {"concepts/policy/billing-rules.md": "fresh"},
                            "requirements": {12: True}}


def test_a_concept_cited_by_title_is_found(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["Billing rules"]), bundle_dir=_bundle(tmp_path),
                corpus=_corpus())
    assert got.confidence == ALTA


def test_a_stale_concept_bounds_it_to_media(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["concepts/policy/billing-rules.md"]),
                bundle_dir=_bundle(tmp_path, stale=True), corpus=_corpus())
    assert got.confidence == MEDIA and "bytes that have since moved" in got.bounded_by


def test_a_missing_requirement_bounds_it_to_media(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["Billing rules"], requirements=[99]),
                bundle_dir=_bundle(tmp_path), corpus=_corpus(12))
    assert got.confidence == MEDIA and "REQ-99 is not in the requirements" in got.bounded_by
    assert got.verified["requirements"] == {99: False}


def test_a_concept_not_in_the_bundle_is_baixa(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["concepts/policy/ghost.md"]),
                bundle_dir=_bundle(tmp_path), corpus=_corpus())
    assert got.confidence == BAIXA and "`concepts/policy/ghost.md` is not in the bundle" in (
        got.bounded_by)


def test_nothing_cited_or_no_bundle_is_baixa_however_sure_the_model_sounded(tmp_path):
    assert bound(Reading(kind="defect"), bundle_dir=_bundle(tmp_path),
                 corpus=_corpus()).confidence == BAIXA
    got = bound(Reading(kind="misuse", concepts=["Billing rules"]), bundle_dir=None,
                corpus=_corpus())
    assert got.confidence == BAIXA and "no knowledge bundle" in got.bounded_by


def test_the_line_says_kind_confidence_and_what_it_stood_on(tmp_path):
    got = bound(Reading(kind="misuse", concepts=["Billing rules"], requirements=[12]),
                bundle_dir=_bundle(tmp_path, stale=True), corpus=_corpus(12))
    line = render_reading(got, language="pt-BR")
    assert line.startswith("leitura: funciona assim · confiança média · Billing rules (stale), REQ-12")
    assert render_reading(got, language="en").startswith("reading: working as designed")


# ── the module: bounded after the answer, caveat in the client's voice ─────────────────────────

def test_the_module_bounds_the_reading_and_says_so_when_it_cannot_back_it(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _h = _answering_module(
        tmp_path, answer="Funciona assim hoje.\n[[USO: concepts/policy/billing.md; REQ-12]]")
    answer = mod.answer("é bug?")
    assert answer.reading.confidence == BAIXA, answer.reading
    assert answer.text.rstrip().endswith(reading_caveat(language="pt-BR"))
    assert "[[USO" not in answer.text


def test_with_a_bundle_the_module_reads_it_from_the_workspace(tmp_path, monkeypatch):
    from openfactory.product.module import ProductModule
    from tests.test_product_module import _module as _answering_module

    bundle = _bundle(tmp_path)
    monkeypatch.setattr(ProductModule, "_okf_dir", lambda self: bundle)
    mod, _h = _answering_module(
        tmp_path, answer="Funciona assim.\n[[USO: Billing rules]]")
    answer = mod.answer("é bug?")
    assert answer.reading.confidence == ALTA and not answer.text.endswith(")")


def test_a_defect_reading_never_carries_the_caveat(tmp_path):
    from tests.test_product_module import _module as _answering_module

    mod, _h = _answering_module(tmp_path, answer="Quebra o prometido.\n[[DEFEITO]]\n[[EVIDENCIA]]")
    answer = mod.answer("x")
    assert answer.reading.confidence == BAIXA
    assert reading_caveat(language="pt-BR") not in answer.text


# ── the case ────────────────────────────────────────────────────────────────────────────────────

def test_a_read_intake_is_classified_with_its_evidence_and_confidence():
    P = SimpleNamespace(name="acme")
    reading = Reading(kind="misuse", concepts=["Billing rules"], requirements=[12],
                      confidence=ALTA)
    answer = SimpleNamespace(ok=True, text="Funciona assim.", is_misuse=True, is_defect=False,
                             is_ticket=False, is_reorder=False, is_request=False, gesture="",
                             decisions=[], reading=reading)
    got = note_turn(P, "acme", "ana", "é bug?", answer)
    assert got.state == CLASSIFIED and got.kind == "misuse"
    assert got.evidence == ["Billing rules", "REQ-12"] and got.confidence == ALTA
    assert "confidence: alta" in case.render_case(got) and "evidence: Billing rules" in (
        case.render_case(got))
    first = note_turn(P, "acme", "bruno", "e o prazo?", SimpleNamespace(ok=True, text="?",
                                                                       reading=None))
    assert first.state == COLLECTING and first.kind == ""


def test_a_classified_case_still_takes_a_proposal():
    P = SimpleNamespace(name="acme")
    answer = SimpleNamespace(ok=True, text="Registro.", is_defect=True, is_misuse=False,
                             is_ticket=False, is_reorder=False, is_request=False, gesture="",
                             decisions=[], reading=Reading(kind="defect"))
    note_turn(P, "acme", "ana", "quebrou", answer)
    assert current(P, "acme", "ana").state == CLASSIFIED
    case.proposed(P, "acme", {"kind": "defect", "restated": "quebrou"})
    assert current(P, "acme", "ana").state == PROPOSED


def test_the_role_prompt_still_builds_with_nothing_new():
    """The reading changes what `answer()` asks for, not the standing prompt; a role built with
    nothing new still composes."""
    assert ProductRole(None)._prompt("x", "y", audience="client").startswith("You are the ")

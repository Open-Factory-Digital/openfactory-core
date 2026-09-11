"""An open question can be retired — found by the slice-2 design critique (2026-09-06).

WHAT WAS MEASURED. Designing the gather that asks a card's requester before the factory spends,
the critique traced what would happen to an `open-question` the person had answered: nothing.
`Gap` had no identity and no state; `renew._manifest_for` kept every gap that was not stale;
`cover_paths` appended the new round's gaps to the old ones without looking; the concept pass
minted one question per caveat, in fresh wording each time; and the gate matched a question to a
change by path alone. So on the round after an answer the same file was re-judged, the same module
re-authored, and the same question asked again — beside the first one, which now had a twin. A
gather built on that could not terminate, and the person would learn to stop answering.

THE REMEDY, IN FOUR PIECES, EACH GUARDED HERE. A gap has a key derived from its own fields, so
the same question re-minted is the same gap (1). A retired question STAYS in the manifest with its
answer beside it — the record — and stops being about the file for the gate (2). The renewal and
the covering merge by key, the record first, so the answered question is never shadowed by its
re-derivation (3, 4). And the author is told what was answered about its area, so it does not
raise the same caveat in other words (5).
"""

from __future__ import annotations

import json
from pathlib import Path

from openfactory.knowledge.contracts import (
    ANSWERED,
    Concept,
    ConceptSource,
    Gap,
    OkfManifest,
    gap_key,
)
from openfactory.knowledge.gaps import about, answered_gaps, merge_gaps, retire, retire_in_bundle
from openfactory.knowledge.gate import CLEAR, GAP_BLOCKED, judge
from openfactory.knowledge.inventory import (
    coverage_by_kind,
    inventory_gaps,
    take_inventory,
    write_inventory,
)
from openfactory.knowledge.okf import (
    OKF_INDEX_FILE,
    parse_manifest,
    read_manifest,
    render_manifest,
    write_okf,
)
from openfactory.onboarding import cover as _cover
from openfactory.onboarding.concepts import Authored, concept_prompt, propose_concepts
from openfactory.onboarding.context import RepoSurvey, SurveyedModule
from openfactory.onboarding.cover import cover_paths
from openfactory.onboarding.renew import _manifest_for
from tests.test_the_merge_re_authors_what_it_invalidated import _PROJECT

QUESTION = "Is the 2% late fee decided anywhere, or only in the environment?"
ANSWER = "2%, the finance rule since 2021 — it is a product decision, not a setting."


def _question(path: str = "billing", detail: str = QUESTION, severity: str = "") -> Gap:
    return Gap(kind="open-question", path=path, detail=detail, severity=severity)


def _answered(path: str = "billing", detail: str = QUESTION) -> Gap:
    return _question(path, detail).model_copy(update={
        "status": ANSWERED, "answer": ANSWER, "answered_by": "carol",
        "answered_at": "2026-09-06T10:00:00Z"})


# ── 1. identity ─────────────────────────────────────────────────────────────────────────────────

def test_the_key_is_the_question_not_the_object():
    """Two constructions with the same fields are the same gap; case and spacing do not make a
    new one; a different question or a different place does."""
    a, b = _question(), _question()
    assert a.key == b.key and len(a.key) == 12 and int(a.key, 16) >= 0
    assert a.key == gap_key("open-question", "billing", QUESTION)
    assert _question(detail="  is the 2% LATE fee decided anywhere, or only in the environment?"
                     ).key == a.key, "the same caveat re-typed must land on the same key"
    # a dropped question mark — the likeliest near-miss when a model restates a caveat — was a
    # new key (review of #73); trailing punctuation is folded like case and spacing now
    assert _question(detail=QUESTION.rstrip("?")).key == a.key
    assert _question(detail=QUESTION.rstrip("?") + "?!").key == a.key
    assert _question(detail="Who owns the tax table?").key != a.key
    assert _question(path="billing/tax.py").key != a.key
    assert Gap(kind="open-question", path="billing", detail=QUESTION, key="human-set").key == (
        "human-set"), "a key the writer set is kept"


def test_the_key_and_the_state_round_trip_through_the_manifest():
    """A manifest written before keys existed reads back keyed — the same key the writer would
    have derived — so nothing already published has to be regenerated."""
    manifest = OkfManifest(gaps=[_question(), _answered("billing/tax.py", "Which table?")])
    back = parse_manifest(render_manifest(manifest))
    assert [g.key for g in back.gaps] == [g.key for g in manifest.gaps]
    assert back.gaps[1].status == ANSWERED and back.gaps[1].answer == ANSWER
    assert back.gaps[1].answered_by == "carol" and back.gaps[1].answered
    legacy = parse_manifest("okf_version: '0.2'\ngaps:\n- kind: open-question\n  path: billing\n"
                            f"  detail: {json.dumps(QUESTION)}\n")
    assert legacy.gaps[0].key == _question().key and not legacy.gaps[0].answered


# ── 2. the record, and the gate ─────────────────────────────────────────────────────────────────

def _source(tmp_path: Path) -> Path:
    repo = tmp_path / "src"
    for rel, body in {
        "billing/rules.py": "def charge():\n    return 1\n",
        "billing/tax.py": "RATE = 0.2\n",
        "tests/test_rules.py": "def test():\n    pass\n",
    }.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return repo


def _bundle(tmp_path: Path, repo: Path, *, gaps: list[Gap]) -> Path:
    bundle = tmp_path / "fetched" / "bundle"
    taken = take_inventory(repo, commit="c1")
    fps = {r.path: r.fingerprint for r in taken.files}
    concepts = [Concept(type="policy", title="Billing rules", description="d", what_it_does="w",
                        sources=[ConceptSource(repo="r", path="billing/rules.py", commit="c1",
                                               fingerprint=fps["billing/rules.py"], lines="1-2")])]
    manifest = OkfManifest(source_commit="c1", coverage=coverage_by_kind(taken, concepts),
                           gaps=[*inventory_gaps(taken), *gaps])
    write_okf(bundle, manifest=manifest, concepts=concepts)
    write_inventory(bundle, taken)
    (bundle / OKF_INDEX_FILE).write_text("# old\n", encoding="utf-8")
    return bundle


def test_a_retired_question_is_the_record_and_holds_nothing(tmp_path):
    """MEASURED BEFORE: a question graded `high` on `billing` holds `billing/rules.py`
    (`gap-blocked`) — and kept holding it after the person answered, because nothing could say
    so. AFTER: the file is clear, the question is still in the manifest with the answer beside
    it, and the front door shows who answered."""
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, gaps=[_question(severity="high")])
    (row,) = judge(bundle, repo, ["billing/rules.py"]).files
    assert row.verdict == GAP_BLOCKED, "the toll, before the answer"

    key = _question().key
    assert retire_in_bundle(bundle, key, answer=ANSWER, by="carol",
                            at="2026-09-06T10:00:00Z") is True

    (row,) = judge(bundle, repo, ["billing/rules.py"]).files
    assert row.verdict == CLEAR, row
    assert "open question" not in row.reason, "answered, and still shown as an offer"
    [gap] = [g for g in read_manifest(bundle).gaps if g.kind == "open-question"]
    assert gap.key == key and gap.status == ANSWERED and gap.answer == ANSWER
    assert gap.answered_by == "carol" and gap.detail == QUESTION, "the question is kept as asked"
    assert answered_gaps(read_manifest(bundle)) == [gap]
    door = (bundle / OKF_INDEX_FILE).read_text(encoding="utf-8")
    assert QUESTION in door and "**answered** by carol" in door and ANSWER in door


def test_a_key_nothing_holds_writes_nothing(tmp_path):
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, gaps=[_question()])
    before = {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()}
    assert retire_in_bundle(bundle, "000000000000", answer="x", by="y", at="z") is False
    assert {p.name: p.read_bytes() for p in bundle.iterdir() if p.is_file()} == before
    manifest = OkfManifest(gaps=[_question()])
    assert retire(manifest, "", answer="x", by="y", at="z") is manifest
    assert retire(manifest, "000000000000", answer="x", by="y", at="z").gaps == manifest.gaps


# ── 3. the renewal keeps the record, and its twin lands on it ───────────────────────────────────

def test_the_renewal_keeps_the_answered_question_and_appends_no_twin(tmp_path):
    """The next round's author raises the same caveat again (in the same words — the other case
    is the prompt's, §5). Before: two entries, one answered and one open, and the gate names the
    open one. After: one, answered."""
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, gaps=[_answered()])
    inventory = take_inventory(repo, commit="c2")

    manifest = _manifest_for(bundle, inventory, [], commit="c2", generated_at="t2",
                             new_gaps=[_question(), _question("billing", "Who owns tax?")])

    questions = [g for g in manifest.gaps if g.kind == "open-question"]
    assert [(g.detail, g.status) for g in questions] == [(QUESTION, ANSWERED),
                                                         ("Who owns tax?", "")]
    assert questions[0].answer == ANSWER


def test_merge_keeps_the_record_first_and_adds_only_what_is_new():
    merged = merge_gaps([_answered()], [_question(), _question("billing", "Who owns tax?")])
    assert [(g.detail, g.status) for g in merged] == [(QUESTION, ANSWERED), ("Who owns tax?", "")]
    assert merge_gaps([], []) == []


# ── 4. the covering ─────────────────────────────────────────────────────────────────────────────

def test_cover_appends_no_duplicate_key_and_tells_the_author(tmp_path, monkeypatch):
    """MEASURED BEFORE: `cover_paths` appended `manifest.gaps + authored.gaps` — the answered
    question and its re-derivation both in the manifest (the same question twice) — and
    `author_for_paths` was never told what had been answered."""
    repo = _source(tmp_path)
    bundle = _bundle(tmp_path, repo, gaps=[_answered(), _question("billing/tax.py", "Rate?")])
    told: list[list[Gap]] = []

    def fake_author(project, source, paths, *, commit, generated_at, answered=None):
        told.append(list(answered or []))
        fp = take_inventory(repo, commit="c2").files
        rules = next(r.fingerprint for r in fp if r.path == "billing/tax.py")
        concept = Concept(type="policy", title="Tax", what_it_does="w", sources=[
            ConceptSource(repo="r", path="billing/tax.py", commit="c2", fingerprint=rules)])
        return Authored([concept], [_question(), _question("billing", "New one?")], "fake")

    monkeypatch.setattr(_cover, "author_for_paths", fake_author)
    got = cover_paths(_PROJECT, bundle, repo, ["billing/tax.py"], commit="c2", generated_at="t2")

    assert got.authored == 1 and got.covered == ("billing/tax.py",)
    assert told == [[_answered()]], "the author must be told exactly what was answered"
    questions = [g for g in read_manifest(bundle).gaps if g.kind == "open-question"]
    assert [(g.detail, g.status) for g in questions] == [
        (QUESTION, ANSWERED), ("Rate?", ""), ("New one?", "")]


# ── 5. the author is told ───────────────────────────────────────────────────────────────────────

def _module(name: str, path: str) -> SurveyedModule:
    return SurveyedModule(name=name, path=path, purpose=name, purpose_is_folder_name=True,
                          files=1, file_changes=3)


def test_the_prompt_carries_the_answer_as_a_fact():
    prompt = concept_prompt(_module("billing", "billing"), answered=[_answered()])
    assert f"ALREADY ANSWERED — do not ask again: {QUESTION} → {ANSWER} (carol)" in prompt
    assert "ALREADY ANSWERED" not in concept_prompt(_module("billing", "billing"))
    assert "ALREADY ANSWERED" not in concept_prompt(_module("billing", "billing"), answered=[])


def test_each_module_is_told_its_own_area_and_a_repeat_is_not_minted(tmp_path):
    """Bundle-wide answers, module-wide prompts: `billing` hears about `billing` and the file
    under it, not about `orders`. A caveat the author raises anyway in the same words as an
    answered question is not a new gap; one in new words still is (that is what the prompt is
    for — nothing here can read intent)."""
    repo = _source(tmp_path)
    (repo / "orders").mkdir()
    (repo / "orders" / "ship.py").write_text("X = 1\n", encoding="utf-8")
    survey = RepoSurvey(repo=str(repo), modules=[_module("billing", "billing"),
                                                   _module("orders", "orders")])
    answered = [_answered(), _answered("billing/tax.py", "Which table?"),
                _answered("orders/ship.py", "Ship on Sundays?")]
    prompts: dict[str, str] = {}

    def ask(prompt: str) -> str:
        module = "billing" if "`billing`" in prompt else "orders"
        prompts[module] = prompt
        return json.dumps({"type": "policy", "title": module, "what_it_does": "w",
                           "business_rules": [], "caveats": [QUESTION, "Who owns tax?"]})

    _, gaps = propose_concepts(survey, ask=ask, budget=2, modules=survey.modules,
                               answered=answered)

    assert QUESTION in prompts["billing"] and "Which table?" in prompts["billing"]
    assert "Ship on Sundays?" not in prompts["billing"]
    assert "Ship on Sundays?" in prompts["orders"] and QUESTION not in prompts["orders"]
    minted = [(g.path, g.detail) for g in gaps if g.kind == "open-question"]
    assert ("billing", QUESTION) not in minted, "asked again in the same words — the answer stands"
    assert ("billing", "Who owns tax?") in minted and ("orders", QUESTION) in minted, (
        "a question in new words, or on another area, is still a question")


def test_about_reads_the_prefix_both_ways():
    gaps = [_question("billing"), _question("billing/tax.py", "Rate?"),
            _question("orders", "Ship?"), _question("", "Whole repo?")]
    assert [g.path for g in about(gaps, "billing")] == ["billing", "billing/tax.py"]
    assert [g.path for g in about(gaps, "billing/rules.py")] == ["billing"]
    assert about(gaps, "") == []

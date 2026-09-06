"""An open question is an offer, not a toll — the product owner's call, 2026-09-06.

THE FIRST LIVE BUNDLE HELD 40 OPEN QUESTIONS ON A 133-FILE REPOSITORY, and reading them showed
three things at once:

  1. nearly all said "decided in another module, not observable here" — the prompt said
     "THIS MODULE only", so the agent stopped at the folder's edge where a person opens the next
     file. That is the agent's reading bound, not the product's unknown;
  2. the concept pass records a question on the MODULE (`billing`) and the gate matched gaps by
     exact file path (`billing/rules.py`), so none of the 40 was ever shown on a change — nor did
     any hold one, whatever the policy said;
  3. the onboarding printed them as a prerequisite ("Only your team can answer these — before
     merging", "YOUR STEP: review and merge the pull request(s) above" under a run that opened
     none), and the operator read the list as work owed before the factory could work.

The decision: the prompt follows the references and keeps a caveat for what the CODE does not
decide; a question recorded on a file or on a directory above it is SHOWN beside that file's
verdict and holds nothing unless somebody grades it `high`; the pull request body, the closing of
`onboard` and the questions document say that nothing waits on them.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.cli import _handover_lines
from openfactory.knowledge.contracts import Concept, ConceptSource, Gap, OkfManifest
from openfactory.knowledge.gate import CLEAR, GAP_BLOCKED, GREEN, NO_CONCEPT, judge
from openfactory.knowledge.inventory import (
    coverage_by_kind,
    inventory_gaps,
    take_inventory,
    write_inventory,
)
from openfactory.knowledge.okf import write_okf
from openfactory.onboarding import context as ctx
from openfactory.onboarding.concepts import concept_prompt
from openfactory.onboarding.context import SurveyedModule
from openfactory.onboarding.onboard import RepoOutcome, _pr_body

# ── 1. the prompt ────────────────────────────────────────────────────────────────────────────


def _module() -> SurveyedModule:
    return SurveyedModule(name="routes", path="services/api/src/routes", purpose="routes",
                          purpose_is_folder_name=True, files=4, file_changes=12)


def test_the_concept_prompt_sends_the_reader_across_modules():
    prompt = concept_prompt(_module(), language="pt-PT")

    assert "FOLLOW THE REFERENCES" in prompt
    assert "anywhere in the repository resolves" in prompt
    assert "Never for what this folder" in prompt, "the caveat must be for what the CODE decides"
    assert "THIS MODULE only" not in prompt, "the folder's edge is where a person opens the next file"
    assert "does not decide" in prompt, "the JSON shape still describes a caveat as a closed door"


# ── 2-4. the gate ────────────────────────────────────────────────────────────────────────────


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
    return bundle


def _question(path: str, severity: str = "") -> Gap:
    return Gap(kind="open-question", path=path, severity=severity,
               detail="the role hierarchy is decided in auth/middleware.js")


def test_an_open_question_on_a_described_file_is_shown_and_holds_nothing(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo, gaps=[_question("billing/rules.py")]), repo,
                   ["billing/rules.py"])

    (row,) = report.files
    assert row.verdict == CLEAR, row
    assert "1 open question(s) recorded about this area" in row.reason
    assert "nothing waits on them" in row.reason
    assert report.stance() == GREEN


def test_a_question_recorded_on_the_module_reaches_the_files_under_it(tmp_path):
    """The concept pass writes `billing`; the change names `billing/rules.py`. An exact match is
    how 40 questions reached nobody."""
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo, gaps=[_question("billing"), _question("billing")]),
                   repo, ["billing/rules.py", "billing/tax.py"])

    rows = {f.path: f for f in report.files}
    assert rows["billing/rules.py"].verdict == CLEAR
    assert "2 open question(s) recorded" in rows["billing/rules.py"].reason
    assert rows["billing/tax.py"].verdict == NO_CONCEPT, "dark for its own reason, not the questions"
    assert "2 open question(s) recorded" in rows["billing/tax.py"].reason


def test_a_question_graded_high_still_holds_the_files_under_it(tmp_path):
    repo = _source(tmp_path)
    report = judge(_bundle(tmp_path, repo, gaps=[_question("billing", severity="high")]), repo,
                   ["billing/rules.py", "billing/tax.py"])

    for row in report.files:
        assert row.verdict == GAP_BLOCKED and row.reason.startswith("open-question:"), row


# ── 5-7. the presentation ────────────────────────────────────────────────────────────────────


def test_the_pull_request_body_offers_the_questions_and_owes_nothing_on_them():
    out = RepoOutcome(repo="acme/api")
    out.proof = "skipped: no docker on this machine"
    out.modules = 3
    out.questions = ["Is the audit log retained anywhere?"]

    body = _pr_body("acme/api", out, manifest_proposed=True)

    assert "Is the audit log retained anywhere?" in body
    assert "nothing waits on these" in body
    assert "before merging" not in body, "the questions read as a prerequisite again"


def test_the_handover_names_a_merge_only_when_something_was_proposed():
    proposed = "\n".join(_handover_lines("dsk", proposed=True))
    nothing = "\n".join(_handover_lines("dsk", proposed=False))

    assert "YOUR STEP" in proposed and "merge the pull request" in proposed
    assert "YOUR STEP" not in nothing and "merge the pull request" not in nothing
    assert "nothing waits on them" in nothing
    assert "openfactory doctor dsk" in proposed and "openfactory doctor dsk" in nothing


def test_the_questions_document_says_nothing_waits_in_both_languages(tmp_path):
    repo = _source(tmp_path)
    for language, heading in (("en", "Questions only the developers can answer"),
                              ("pt-BR", "Perguntas que só os desenvolvedores respondem")):
        docs = tmp_path / f"docs-{language}"
        docs.mkdir()
        survey = ctx.survey(repo)
        proposal = ctx.propose_context(survey, ask=None, docs_root=docs, language=language)
        ctx.write_documents(proposal, docs, consent=True)

        written = [p.read_text(encoding="utf-8") for p in docs.rglob("*.md")]
        (questions,) = [t for t in written if f"# {heading}" in t]
        assert ctx._words(language)["questions_note"] in questions, questions[:400]
        assert "nothing waits" in questions.lower() or "nada espera" in questions.lower()

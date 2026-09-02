"""A concept is a claim the repository can be checked against, or it is not written.

THE MODULE MAP SAYS WHERE, AND NOBODY COULD LEARN WHAT A RULE IS FROM IT. `knowledge/` carries
path, purpose, dependencies and public surface — the right artifact for an agent that needs to
jump to a file, and structurally incapable of holding *"a charge is never issued twice"*. That
sentence is what a product owner and a tech lead actually need, and it is worth nothing unless a
reader can get from it to the line in one hop.

So the rule this file exists to hold: **a sentence with no surviving citation never becomes a
concept.** It is demoted into a gap that names the citation that did not resolve — the same move
`onboarding/context.py::_Anchorer` already makes for the five documents, reused here rather than
reinvented, because a second verification path would be a second place for an unverified sentence
to enter the bundle.

AND THE COST IS BOUNDED BY A NUMBER, NOT BY THE CLIENT'S REPOSITORY. `propose_context` refuses a
per-module fan-out in as many words, and what it protects is a quotable cost. A budget the project
declares keeps that protection: ten modules and ten thousand cost the same declared N. The tests
below pin both halves — that the budget is honoured, and that what the budget cannot buy
(coverage) is stated in the manifest rather than implied away.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from openfactory.contracts import Manifest
from openfactory.knowledge.contracts import Concept, OkfManifest
from openfactory.knowledge.okf import (
    assign_paths,
    parse_concept,
    read_concepts,
    render_concept,
    render_index,
    write_okf,
)
from openfactory.onboarding.concepts import (
    DEFAULT_CONCEPT_BUDGET,
    MAX_CONCEPT_BUDGET,
    propose_concepts,
    rank_modules,
)
from openfactory.onboarding.context import RepoSurvey, SurveyedModule


def _repo(tmp_path: Path) -> Path:
    """A repository with one real file, so a citation has something to resolve against."""
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "rules.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _survey(repo: Path, modules: list[SurveyedModule] | None = None) -> RepoSurvey:
    return RepoSurvey(repo=str(repo), modules=modules or [
        SurveyedModule(name="billing", path="billing", purpose="billing",
                       purpose_is_folder_name=True, files=1, file_changes=9)])


def _answer(**over) -> str:
    base = {
        "type": "policy", "title": "Billing rules", "description": "How charging works.",
        "what_it_does": "Charges once per order.",
        "business_rules": [{"text": "A charge is never issued twice",
                            "cites": ["billing/rules.py:2"]}],
        "caveats": [],
    }
    base.update(over)
    return json.dumps(base)


# ── the citation is the whole contract ──────────────────────────────────────────────────────────

def test_a_rule_whose_citation_does_not_resolve_never_becomes_a_concept_rule(tmp_path):
    """THE PROPERTY THIS FILE IS NAMED FOR. A model that invents a source loses the sentence —
    and the sentence is not merely dropped, it is recorded as a gap naming what was cited, so the
    difference between "nothing to say here" and "it said something it could not support" survives
    into the bundle a human reads."""
    repo = _repo(tmp_path)
    answer = _answer(business_rules=[
        {"text": "a real rule", "cites": ["billing/rules.py:2"]},
        {"text": "an invented rule", "cites": ["billing/ghost.py:9"]},
    ])

    concepts, gaps = propose_concepts(_survey(repo), ask=lambda _p: answer, budget=1)

    assert [r.text for r in concepts[0].business_rules] == ["a real rule"]
    unresolved = [g for g in gaps if g.kind == "unresolved"]
    assert unresolved, "the unsupported sentence vanished instead of becoming a gap"
    assert "an invented rule" in unresolved[0].detail
    assert "billing/ghost.py:9" in unresolved[0].detail, (
        "the gap must name the citation that did not resolve — otherwise a reader cannot tell a "
        "wrong belief from a mistyped path")


def test_the_sources_are_derived_from_citations_that_survived(tmp_path):
    """SOURCES ARE EARNED, NOT DECLARED. The fingerprints that will later invalidate a concept
    describe exactly the files its claims were actually read from — never a list the model was
    asked to provide, which would be one more unverified field."""
    repo = _repo(tmp_path)

    concepts, _ = propose_concepts(
        _survey(repo), ask=lambda _p: _answer(), budget=1,
        commit="deadbee", fingerprints={"billing/rules.py": "fp-1"})

    [source] = concepts[0].sources
    assert (source.path, source.commit, source.fingerprint, source.lines) == (
        "billing/rules.py", "deadbee", "fp-1", "2")


# ── the budget: what it buys, and what it cannot ────────────────────────────────────────────────

def test_the_ranking_spends_the_budget_where_the_platform_knows_least(tmp_path):
    """`churn × blast radius × uncertainty`, every term already measured by the survey and two of
    them read by nothing before this. A big, documented, tested module nobody has touched is the
    LAST place a model call buys anything."""
    modules = [
        SurveyedModule(name="quiet", path="quiet", purpose="Well documented.",
                       purpose_is_folder_name=False, files=40, file_changes=0, tested_by=["t.py"]),
        SurveyedModule(name="hot", path="hot", purpose="hot", purpose_is_folder_name=True,
                       files=3, file_changes=37, depended_on_by=["a", "b", "c"]),
    ]

    assert [m.name for m in rank_modules(_survey(tmp_path, modules), budget=2)] == ["hot", "quiet"]


def test_the_budget_is_a_number_the_project_declares_not_the_repository_size(tmp_path):
    """The protection `propose_context` states — a quotable cost — kept as a mechanism. Ten
    modules and ten thousand cost the same declared N."""
    many = [SurveyedModule(name=f"m{i}", path=f"m{i}", purpose="p",
                           purpose_is_folder_name=False, files=1, file_changes=i)
            for i in range(200)]
    survey = _survey(tmp_path, many)

    assert len(rank_modules(survey, budget=3)) == 3
    assert rank_modules(survey, budget=0) == [], "a declared 0 must author nothing at all"
    assert len(rank_modules(survey, budget=10_000)) <= MAX_CONCEPT_BUDGET, (
        "a typo of two extra zeros must not become a bill")


def test_the_manifest_carries_the_dial_with_both_ends_bounded():
    assert Manifest().okf_concept_budget == DEFAULT_CONCEPT_BUDGET
    assert Manifest(okf_concept_budget=0).okf_concept_budget == 0  # off, map untouched
    for refused in (-1, MAX_CONCEPT_BUDGET + 1):
        with pytest.raises(Exception):  # noqa: B017 — pydantic's own type is not the point
            Manifest(okf_concept_budget=refused)


# ── every failure is a typed gap, never a silence and never a crash ─────────────────────────────

@pytest.mark.parametrize("label,ask", [
    ("unparseable", lambda _p: "not json at all"),
    ("the harness raised", None),  # replaced below — a lambda cannot raise
    ("no agent configured", "none"),
])
def test_a_module_that_could_not_be_described_says_so(tmp_path, label, ask):
    """ONE MODULE'S FAILURE MUST NOT LOSE THE OTHERS AND MUST NOT VANISH. The bundle records that
    this module was chosen and could not be described — the difference between "nothing to say
    here" and "we tried and could not"."""
    repo = _repo(tmp_path)
    if label == "the harness raised":
        def ask(_p):
            raise RuntimeError("harness died")
    elif label == "no agent configured":
        ask = None

    concepts, gaps = propose_concepts(_survey(repo), ask=ask, budget=1)

    assert concepts == []
    assert [g.kind for g in gaps] == ["not-described"]
    assert gaps[0].path == "billing"
    assert gaps[0].detail, "a gap with no reason is a label, not a finding"


def test_a_caveat_the_model_raised_becomes_an_open_question(tmp_path):
    """A gap said out loud is worth more than a confident sentence nobody can check — and it
    reaches the bundle as DATA, so the index can lead with it."""
    repo = _repo(tmp_path)

    _, gaps = propose_concepts(
        _survey(repo), ask=lambda _p: _answer(caveats=["the retry window is not in the code"]),
        budget=1)

    assert [g.kind for g in gaps] == ["open-question"]
    assert "retry window" in gaps[0].detail


# ── the file layout: nothing is silently merged, and nothing is silently deleted ─────────────────

def test_two_concepts_sharing_a_title_keep_both_files(tmp_path):
    """MEASURED ON THE FIRST END-TO-END RUN, and every unit test passed while it was broken: a
    filename derived from the title alone let the second concept overwrite the first, the bundle
    still read as complete, and the index listed two entries pointing at one file."""
    same = [Concept(type="policy", title="Billing rules", description="first"),
            Concept(type="policy", title="Billing rules", description="second")]

    written = write_okf(tmp_path, manifest=OkfManifest(), concepts=same)

    assert sorted(p.name for p in written if p.suffix == ".md") == [
        "billing-rules-2.md", "billing-rules.md"]
    index = render_index(OkfManifest(), same)
    assert "concepts/policy/billing-rules.md" in index
    assert "concepts/policy/billing-rules-2.md" in index, (
        "the index re-derived the path instead of using the writer's own assignment, so a link "
        "points at a concept it does not open")


def test_the_assignment_is_stable_between_runs():
    """A suffix that moved between runs would make every diff unreadable and would silently
    relabel a file a human had already edited."""
    same = [Concept(type="policy", title="A", description=str(i)) for i in range(3)]

    assert [p.as_posix() for _, p in assign_paths(same)] == [
        p.as_posix() for _, p in assign_paths(list(reversed(same)))]


def test_a_refresh_never_deletes_a_concept_it_did_not_write(tmp_path):
    """A concept this pass did not produce may be a human's, or an earlier pass's about code this
    run could not reach. Pruning what it cannot currently see would turn one bad run into data
    loss — a decision belongs in a diff somebody reads."""
    write_okf(tmp_path, manifest=OkfManifest(), concepts=[Concept(type="policy", title="Older")])

    write_okf(tmp_path, manifest=OkfManifest(), concepts=[Concept(type="policy", title="Newer")])

    assert {c.title for c in read_concepts(tmp_path)} == {"Older", "Newer"}


def test_a_concept_round_trips_through_its_own_file():
    """The frontmatter is what a later pass reads to know this concept already exists — and what
    the checker will read to invalidate it. If it cannot be read back, neither can happen."""
    concept = Concept(type="contract", title="Shared keys", description="d",
                      generated_by="machine:backfill", generated_at="2026-09-02T00:00:00Z")

    back = parse_concept(render_concept(concept))

    assert (back.type, back.title, back.generated_by) == ("contract", "Shared keys",
                                                          "machine:backfill")


def test_an_unreadable_concept_file_does_not_take_the_bundle_with_it(tmp_path):
    """One hand-edited file with broken frontmatter must not make the other forty unreadable to
    the role that needs them."""
    write_okf(tmp_path, manifest=OkfManifest(), concepts=[Concept(type="policy", title="Good")])
    broken = tmp_path / ".okf" / "concepts" / "policy" / "broken.md"
    broken.write_text("no frontmatter here", encoding="utf-8")

    assert [c.title for c in read_concepts(tmp_path)] == ["Good"]


# ── the index leads with what is missing ────────────────────────────────────────────────────────

def test_the_index_says_what_is_missing_before_it_says_what_is_there(tmp_path):
    """THE ORDER IS THE ARGUMENT. A reader who scrolls forty concepts and never reaches a "what we
    could not establish" section at the bottom has been told, by the layout, that the bundle is
    complete. `techlead/pack.py`'s manifest makes the same choice for the same reason."""
    from openfactory.knowledge.contracts import Gap

    manifest = OkfManifest(gaps=[Gap(kind="open-question", detail="which index wins")])

    index = render_index(manifest, [Concept(type="policy", title="Billing")])

    assert index.index("could not establish") < index.index("## Concepts")


def test_an_empty_gap_list_is_a_measurement_not_a_silence(tmp_path):
    """"Nothing was recorded as missing" and "nobody looked" must not render identically — the
    same three-state discipline `BundleManifest` already keeps for its own blindness counters."""
    index = render_index(OkfManifest(), [])

    assert "Nothing was recorded as missing" in index


def test_the_coverage_row_carries_the_denominator(tmp_path):
    """What the budget CANNOT buy is coverage: N concepts on a 900-module repository describe N
    modules. A bundle that omits the denominator implies a completeness it does not have."""
    from openfactory.knowledge.contracts import CoverageRow

    manifest = OkfManifest(coverage=[CoverageRow(
        kind="module", inventoried=900, concepts=5, reason="a budget of 5 was declared")])

    index = render_index(manifest, [])

    assert "900" in index and "5" in index and "budget of 5" in index

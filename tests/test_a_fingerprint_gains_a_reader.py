"""`ConceptSource.fingerprint` gains a reader — ADR-0045's definition of done, measured.

    $ grep -rn "\\.fingerprint" openfactory/ --include=*.py     # 2026-09-04, before this
    $

Two writers, zero readers, while `okf.py::render_concept`'s docstring already named "the checker
that invalidates it reads the fingerprints". The promise at the centre of the OKF — the bytes move,
the fingerprint moves, the concept is stale with nobody in the loop — had no mechanism. These guards
pin the mechanism, and the last one pins the grep.

THE FIXTURE IS THE REAL PIPELINE, NOT A HAND-WRITTEN FRONTMATTER. A concept is authored through
`propose_concepts` with a real fingerprint from `compute_checksums`, written with `write_okf`, and
read back through `read_concepts` — so what is checked is what the platform actually publishes,
including the round trip through YAML. A guard fed a frontmatter it typed itself would prove the
checker agrees with the guard's author.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from openfactory.knowledge.bundle import compute_checksums
from openfactory.knowledge.check import (
    FRESH,
    MISSING,
    STALE,
    UNSOURCED,
    UNVERIFIABLE,
    CheckReport,
    ConceptCheck,
    SourceCheck,
    check_concepts,
    stale_bundle_gap,
)
from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
from openfactory.knowledge.okf import write_okf
from openfactory.onboarding.concepts import propose_concepts
from openfactory.onboarding.context import RepoSurvey, SurveyedModule

ROOT = Path(__file__).resolve().parents[1]


# ── the real pipeline, end to end ───────────────────────────────────────────────────────────────

def _repo(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    (src / "billing").mkdir(parents=True)
    (src / "billing" / "rules.py").write_text("def charge():\n    return 1\n", encoding="utf-8")
    (src / "billing" / "refunds.py").write_text("def refund():\n    return 0\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    return src


def _answer(cites: list[str], title: str = "Billing rules") -> str:
    return json.dumps({
        "type": "policy", "title": title, "description": "How charging works.",
        "what_it_does": "Charges once per order.",
        "business_rules": [{"text": "A charge is never issued twice", "cites": cites}],
        "caveats": [],
    })


def _published(tmp_path: Path, *, cites: list[str] | None = None,
               concepts: list[Concept] | None = None) -> tuple[Path, Path]:
    """`(bundle_dir, repo)` — concepts authored against `repo` and written the way the backfill
    writes them, with the fingerprints `compute_checksums` produces."""
    repo = _repo(tmp_path)
    if concepts is None:
        survey = RepoSurvey(repo=str(repo), modules=[
            SurveyedModule(name="billing", path="billing", purpose="billing",
                           purpose_is_folder_name=True, files=2, file_changes=9)])
        fingerprints = {c.file: c.sha256 for c in compute_checksums(repo)}
        concepts, _gaps = propose_concepts(
            survey, ask=lambda _p: _answer(cites or ["billing/rules.py:2"]), budget=1,
            commit="deadbee", fingerprints=fingerprints)
        assert concepts and concepts[0].sources[0].fingerprint, "the fixture authored nothing"
    bundle = tmp_path / "context" / ".okf" / "repos" / "acme--src"
    write_okf(bundle, manifest=OkfManifest(source_commit="deadbee"), concepts=concepts)
    return bundle, repo


def test_a_bundle_that_still_describes_its_checkout_is_fresh(tmp_path):
    bundle, repo = _published(tmp_path)

    report = check_concepts(bundle, repo)

    assert report.holds
    assert [c.verdict for c in report.concepts] == [FRESH]
    assert report.summary() == "1 concepts checked: 1 fresh"


def test_the_bytes_move_and_the_concept_is_stale_with_nobody_in_the_loop(tmp_path):
    """THE SENTENCE `ConceptSource` PROMISES, made true. Nothing is regenerated, nobody signs
    anything: the file changed, so the concept that read it no longer holds."""
    bundle, repo = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")

    report = check_concepts(bundle, repo)

    assert not report.holds
    [concept] = report.concepts
    assert concept.verdict == STALE
    [source] = concept.sources
    assert (source.path, source.verdict) == ("billing/rules.py", STALE)
    assert "bytes moved" in source.detail


def test_a_source_that_is_gone_is_missing_not_stale(tmp_path):
    """Two different facts: the file changed, or the file is not here. A reader repairs them
    differently — one re-reads, the other looks for where the code went."""
    bundle, repo = _published(tmp_path)
    (repo / "billing" / "rules.py").unlink()

    report = check_concepts(bundle, repo)

    [concept] = report.concepts
    assert concept.verdict == MISSING
    assert concept.sources[0].detail == "not in this checkout"
    assert not report.holds


def test_the_fingerprint_that_is_compared_is_the_one_the_backfill_wrote(tmp_path):
    """The checker must hash the way `compute_checksums` hashes, or every bundle is stale on the
    day it is published. Pinned by round-tripping a real fingerprint rather than by reading the
    import line."""
    bundle, repo = _published(tmp_path)
    recorded = {c.file: c.sha256 for c in compute_checksums(repo)}["billing/rules.py"]

    report = check_concepts(bundle, repo)

    assert report.concepts[0].verdict == FRESH
    assert len(recorded) == 64, "sha256 hex — the fixture is not exercising the real hash"


# ── the verdict is the WORST source, and absence of a measurement is not a measurement ─────────

def test_a_concept_is_as_good_as_its_weakest_source(tmp_path):
    """One fresh source and one stale one is a STALE concept. A claim supported by two files loses
    its support when either moves; averaging would call it half-true.

    THE WEAK SOURCE IS THE LAST ONE, AND THAT IS THE GUARD. `_verified_rules` returns sources
    sorted by path, so `refunds.py` comes before `rules.py`. The first version of this guard moved
    `refunds.py` — and a checker that took the FIRST source's verdict instead of the worst passed
    it, because the first source happened to be the moved one. The mutation plan caught the guard
    being decoration; moving `rules.py` instead makes "first" and "worst" disagree."""
    bundle, repo = _published(tmp_path, cites=["billing/refunds.py:2", "billing/rules.py:2"])
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 9\n", encoding="utf-8")

    report = check_concepts(bundle, repo)

    [concept] = report.concepts
    assert [s.path for s in concept.sources] == ["billing/refunds.py", "billing/rules.py"], (
        "the fixture depends on the fresh source sorting FIRST")
    assert {s.path: s.verdict for s in concept.sources} == {
        "billing/refunds.py": FRESH, "billing/rules.py": STALE}
    assert concept.verdict == STALE


def test_missing_outranks_stale_within_one_concept(tmp_path):
    """Same ordering discipline: the stale source sorts first, the missing one last, so "first"
    says stale and only "worst" says missing."""
    bundle, repo = _published(tmp_path, cites=["billing/refunds.py:2", "billing/rules.py:2"])
    (repo / "billing" / "refunds.py").write_text("changed\n", encoding="utf-8")
    (repo / "billing" / "rules.py").unlink()

    [concept] = check_concepts(bundle, repo).concepts

    assert [s.verdict for s in concept.sources] == [STALE, MISSING]
    assert concept.verdict == MISSING


def test_a_bundle_written_before_fingerprints_is_unverifiable_and_never_called_fresh(tmp_path):
    """An older bundle carries sources with no fingerprint. The check cannot be made, and that is
    what is reported — it neither fails the bundle (nothing is contradicted) nor passes it as
    verified (nothing was measured)."""
    old = Concept(type="policy", title="Legacy", status="stable",
                  sources=[ConceptSource(path="billing/rules.py", commit="0ld")])
    bundle, repo = _published(tmp_path, concepts=[old])

    report = check_concepts(bundle, repo)

    [concept] = report.concepts
    assert concept.verdict == UNVERIFIABLE
    assert report.holds, "an unverifiable bundle is not a broken one"
    assert report.count(FRESH) == 0, "and it is not a verified one either"
    assert "unverifiable" in report.summary()


def test_a_directory_source_is_unverifiable_and_never_missing(tmp_path):
    """`propose_concepts` falls back to the MODULE PATH as the source when no citation survived —
    a directory. Read as a file it raises, and the first checker called that `missing`: broken on
    every refresh, re-authored and paid for forever. There is no verified line to hash, which is
    unverifiable, and it does not fail the bundle."""
    dir_sourced = Concept(type="policy", title="Whole module", status="draft",
                          sources=[ConceptSource(path="billing", fingerprint="")])
    bundle, repo = _published(tmp_path, concepts=[dir_sourced])

    report = check_concepts(bundle, repo)

    [concept] = report.concepts
    assert concept.verdict == UNVERIFIABLE
    assert "directory" in concept.sources[0].detail
    assert report.holds and not concept.broken


def test_a_concept_with_no_sources_is_unsourced(tmp_path):
    bare = Concept(type="policy", title="Unsourced", status="draft")
    bundle, repo = _published(tmp_path, concepts=[bare])

    [concept] = check_concepts(bundle, repo).concepts

    assert concept.verdict == UNSOURCED
    assert concept.sources == ()


def test_an_unreadable_bundle_costs_the_check_and_never_the_caller(tmp_path):
    """Like everything under `knowledge/`: a boolean at the caller, never a traceback."""
    report = check_concepts(tmp_path / "nowhere", tmp_path)

    assert report.concepts == ()
    assert report.holds
    assert report.summary() == "0 concepts checked"


# ── the gap the tech-lead's pack carries ────────────────────────────────────────────────────────

def _report(*verdicts: str) -> CheckReport:
    return CheckReport(tuple(
        ConceptCheck(title=f"C{i}", type="policy", verdict=v,
                     sources=(SourceCheck(f"f{i}.py", v),))
        for i, v in enumerate(verdicts)))


def test_the_gap_names_the_stale_concepts_by_title_and_counts_both_kinds():
    gap = stale_bundle_gap(_report(FRESH, STALE, MISSING, FRESH))

    assert gap.startswith("2 of 4 concepts")
    assert "1 stale, 1 missing" in gap
    assert "'C1'" in gap and "'C2'" in gap and "'C0'" not in gap
    assert "history" in gap, "the reader is told HOW to read a stale concept, not just that it is"


def test_a_fresh_bundle_produces_no_gap_at_all():
    assert stale_bundle_gap(_report(FRESH, FRESH, UNVERIFIABLE)) == ""


def test_the_gap_is_one_sentence_when_everything_moved():
    gap = stale_bundle_gap(_report(*([STALE] * 10)))

    assert gap.count("'C") == 6 and "and 4 more" in gap


# ── the tech-lead is the reader that holds both halves ──────────────────────────────────────────

class _Project:
    name = "fake"
    product = SimpleNamespace(docs_repo="acme/src-context")
    forge = SimpleNamespace(repo="acme/src")  # what `repo_of` reads


def _wire(monkeypatch, bundle: Path):
    from openfactory import credentials as creds
    from openfactory.adapters.forge import registry
    from openfactory.knowledge import pipeline
    from openfactory.knowledge.pipeline import Fetched

    monkeypatch.setattr(creds, "forge_token_for", lambda p: "tok")
    monkeypatch.setattr(creds, "deployment_forge_token", lambda p: "tok")
    monkeypatch.setattr(registry, "clone_url_for", lambda *a, **k: "https://x/y.git")
    monkeypatch.setattr(pipeline, "fetch_bundle", lambda *a, **k: Fetched(bundle))


def test_the_techlead_keeps_a_stale_bundle_AND_names_what_moved(monkeypatch, tmp_path):
    """THE FIRST READER OF THE FINGERPRINT. It has the bundle and the checkout at once, so it is
    where 'the bytes moved' becomes a fact. And it keeps the bundle: one moved file must not cost
    the tech-lead the other thirty-nine concepts — the gap names which to distrust."""
    from openfactory.techlead import conversation

    bundle, repo = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("def charge():\n    return 2\n", encoding="utf-8")
    _wire(monkeypatch, bundle)

    got, gaps = conversation._bundle_for(_Project(), source=repo)

    assert got == bundle, "a stale bundle is still carried into the pack"
    [gap] = gaps
    assert "1 of 1 concepts" in gap and "'Billing rules'" in gap


def test_the_techlead_reports_no_gap_for_a_bundle_that_still_holds(monkeypatch, tmp_path):
    from openfactory.techlead import conversation

    bundle, repo = _published(tmp_path)
    _wire(monkeypatch, bundle)

    assert conversation._bundle_for(_Project(), source=repo) == (bundle, [])


def test_with_no_checkout_the_techlead_does_not_pretend_to_have_checked(monkeypatch, tmp_path):
    """`source=None` is 'no checkout to check against', not 'checked and fine'. The gap is
    absent because the check was not made, and the caller that has no checkout also writes no
    pack — there is nowhere a false 'fresh' could land."""
    from openfactory.techlead import conversation

    bundle, repo = _published(tmp_path)
    (repo / "billing" / "rules.py").unlink()
    _wire(monkeypatch, bundle)

    assert conversation._bundle_for(_Project()) == (bundle, [])


def test_the_call_site_hands_the_checkout_it_just_cloned():
    """The wiring, read out of the source: `answer()` passes the clone to `_bundle_for`, so the
    check happens on the real path and not only in a guard that calls it directly."""
    src = (ROOT / "openfactory" / "techlead" / "conversation.py").read_text(encoding="utf-8")

    assert "_bundle_for(project, source=tmp)" in src, (
        "the tech-lead clones the source and fetches the bundle, and must hand the first to the "
        "check of the second — otherwise nothing on the real path re-verifies anything")


# ── the CLI is the separate pass that fails a run ───────────────────────────────────────────────

def test_the_command_exits_non_zero_on_a_stale_bundle_and_names_it(tmp_path):
    from typer.testing import CliRunner

    from openfactory.cli import app

    bundle, repo = _published(tmp_path)
    (repo / "billing" / "rules.py").write_text("moved\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["knowledge", "check-concepts", str(bundle), str(repo)])

    assert result.exit_code == 1, result.output
    assert "stale" in result.output and "Billing rules" in result.output
    assert "billing/rules.py" in result.output


def test_the_command_exits_zero_on_a_fresh_bundle(tmp_path):
    from typer.testing import CliRunner

    from openfactory.cli import app

    bundle, repo = _published(tmp_path)

    result = CliRunner().invoke(app, ["knowledge", "check-concepts", str(bundle), str(repo)])

    assert result.exit_code == 0, result.output
    assert "1 fresh" in result.output


# ── the measurement in the ADR ──────────────────────────────────────────────────────────────────

def test_the_fingerprint_has_a_reader_now():
    """ADR-0045's definition of done, as a guard: the grep that came back empty on 2026-09-04 does
    not come back empty. Pinned so a refactor cannot quietly remove the only reader and return the
    field to being a promise."""
    readers = [
        p for p in (ROOT / "openfactory").rglob("*.py")
        if p.name != "contracts.py" and ".fingerprint" in p.read_text(encoding="utf-8")
        and "ConceptSource" in p.read_text(encoding="utf-8")
    ]

    assert readers, "`ConceptSource.fingerprint` is written and read by nothing again"
    assert any(p.name == "check.py" for p in readers)


@pytest.mark.parametrize("verdict", [STALE, MISSING])
def test_broken_means_exactly_stale_or_missing(verdict):
    assert ConceptCheck("t", "policy", verdict, ()).broken


@pytest.mark.parametrize("verdict", [FRESH, UNVERIFIABLE, UNSOURCED])
def test_the_other_verdicts_are_not_broken(verdict):
    assert not ConceptCheck("t", "policy", verdict, ()).broken

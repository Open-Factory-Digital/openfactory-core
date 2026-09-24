"""`openfactory doctor` reports the DEPLOYMENT's central guidelines directory as its own line (#318).

A setting that names a missing or empty directory leaves every job running without the
organisation's standards while nothing else fails — the exact silence doctor exists to break.
"""

from __future__ import annotations

from pathlib import Path

from pinned_probes import a_fully_pinned_probe_set

from openfactory import doctor
from openfactory.orchestrator.operator_guidelines import OperatorTier


def _finding(tier: OperatorTier) -> doctor.Finding:
    report = doctor.diagnose(a_fully_pinned_probe_set(operator_guidelines=lambda: tier))
    return next(f for f in report.findings if f.check == "op_guidelines")


def test_not_configured_is_a_pass(tmp_path: Path):
    f = _finding(OperatorTier(configured=False))
    assert f.ok and "OPENFACTORY_GUIDELINES_DIR" in f.message


def test_a_missing_directory_is_a_failing_line_with_a_remedy(tmp_path: Path):
    f = _finding(OperatorTier(configured=True, dir=tmp_path / "gone", dir_exists=False))
    assert not f.ok
    assert "no such directory exists" in f.message
    assert f.remedy and "OPENFACTORY_GUIDELINES_DIR" in f.remedy


def test_an_empty_directory_is_a_failing_line_with_a_remedy(tmp_path: Path):
    f = _finding(OperatorTier(configured=True, dir=tmp_path, dir_exists=True))
    assert not f.ok and "no .md guidelines" in f.message and f.remedy


def test_a_populated_directory_passes_and_names_the_version(tmp_path: Path):
    tier = OperatorTier(configured=True, dir=tmp_path, dir_exists=True,
                        guideline_docs=[tmp_path / "a.md", tmp_path / "b.md"],
                        reference_docs=[tmp_path / "reference" / "c.md"],
                        version="abc1234")
    f = _finding(tier)
    assert f.ok
    assert "2 guidelines" in f.message and "1 reference doc" in f.message
    assert "abc1234" in f.message


def test_the_probe_reads_the_environment(tmp_path: Path, monkeypatch):
    """The wiring: `probes_for` reads the same directory `build_context` feeds the agent."""
    (tmp_path / "central.md").write_text("rule")
    monkeypatch.setenv("OPENFACTORY_GUIDELINES_DIR", str(tmp_path))
    tier = doctor._operator_guidelines_tier()
    assert tier.configured and tier.dir_exists
    assert [p.name for p in tier.guideline_docs] == ["central.md"]

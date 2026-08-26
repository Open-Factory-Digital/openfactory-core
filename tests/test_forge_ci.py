"""CI-status aggregation for the durable CI-aware repair loop (ADR-0004)."""

from __future__ import annotations

from openfactory.adapters.forge.github import _ci_status_from_checks


def test_ci_status_aggregation():
    assert _ci_status_from_checks([]) == "none"
    assert _ci_status_from_checks([{"bucket": "pass"}, {"bucket": "pass"}]) == "success"
    assert _ci_status_from_checks([{"bucket": "pass"}, {"bucket": "pending"}]) == "pending"
    # fail wins over pending; a cancelled required check must never read as green
    assert _ci_status_from_checks([{"bucket": "pending"}, {"bucket": "fail"}]) == "failure"
    assert _ci_status_from_checks([{"bucket": "cancel"}]) == "failure"
    # skipping is not a failure
    assert _ci_status_from_checks([{"bucket": "pass"}, {"bucket": "skipping"}]) == "success"


def test_a_repo_with_CI_but_no_branch_protection_reads_as_none(monkeypatch):
    """FOUND LIVE the moment fx-jira gained its ci.yml (F-02, 2026-08-05). gh has TWO sentences
    for "nothing gates this merge": "no checks reported" (no CI at all) and "no REQUIRED checks
    reported" — workflows exist, branch protection does not. Only the first was known, so every
    status poll on the commonest real client shape raised, the activity retried forever, and the
    merge watch died on a repo that was perfectly healthy. CI existing does not mean CI is
    required."""
    from openfactory.adapters.forge.github import GitHubForge

    f = GitHubForge("acme/x")
    monkeypatch.setattr(f, "_gh", lambda args, timeout=120: type("P", (), {
        "returncode": 8, "stdout": "",
        "stderr": "no required checks reported on the 'sdlc/DAR-3' branch"})())

    assert f.pr_ci_status(pr="https://github.com/acme/x/pull/2") == "none"


def test_an_UNRECOGNISED_empty_answer_still_raises(monkeypatch):
    """The widening must not swallow a genuine failure — an empty stdout with an unknown stderr
    is still an error somebody has to see."""
    import pytest

    from openfactory.adapters.forge.github import GitHubForge

    f = GitHubForge("acme/x")
    monkeypatch.setattr(f, "_gh", lambda args, timeout=120: type("P", (), {
        "returncode": 1, "stdout": "", "stderr": "API rate limit exceeded"})())

    with pytest.raises(RuntimeError, match="gh pr checks failed"):
        f.pr_ci_status(pr="https://github.com/acme/x/pull/2")

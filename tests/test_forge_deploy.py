"""Post-merge deploy-status reads for the deploy-watch (ADR-0005)."""

from __future__ import annotations

import json
import subprocess

from openfactory.adapters.forge.github import GitHubForge


def _cp(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=rc, stdout=stdout, stderr=stderr)


def _forge(monkeypatch, responses: dict[str, subprocess.CompletedProcess]) -> GitHubForge:
    """A forge whose `_gh` is keyed by the subcommand ('pr view' / 'run list')."""
    forge = GitHubForge("owner/repo", token="t")

    def fake_gh(args, timeout=120):
        key = " ".join(args[:2])
        return responses[key]

    monkeypatch.setattr(forge, "_gh", fake_gh)
    return forge


def test_merge_commit_sha_reads_the_merge_oid(monkeypatch):
    forge = _forge(monkeypatch, {
        "pr view": _cp(json.dumps({"mergeCommit": {"oid": "abc123"}})),
    })
    assert forge.merge_commit_sha(pr="https://x/pr/1") == "abc123"


def test_merge_commit_sha_none_when_unmerged(monkeypatch):
    forge = _forge(monkeypatch, {"pr view": _cp(json.dumps({"mergeCommit": None}))})
    assert forge.merge_commit_sha(pr="https://x/pr/1") is None


def test_deploy_run_status_matches_the_run_on_the_merge_sha(monkeypatch):
    # two runs of the deploy workflow; only the one on our sha counts
    runs = [
        {"databaseId": 9, "headSha": "other", "status": "completed",
         "conclusion": "failure", "url": "u/9"},
        {"databaseId": 7, "headSha": "abc123", "status": "completed",
         "conclusion": "success", "url": "u/7"},
    ]
    forge = _forge(monkeypatch, {"run list": _cp(json.dumps(runs))})
    assert forge.deploy_run_status(sha="abc123", workflow="deploy.yml") == ("success", "u/7")


def test_deploy_run_status_pending_until_completed(monkeypatch):
    runs = [{"databaseId": 7, "headSha": "abc123", "status": "in_progress",
             "conclusion": None, "url": "u/7"}]
    forge = _forge(monkeypatch, {"run list": _cp(json.dumps(runs))})
    assert forge.deploy_run_status(sha="abc123", workflow="deploy.yml") == ("pending", "u/7")


def test_deploy_run_status_failure(monkeypatch):
    runs = [{"databaseId": 7, "headSha": "abc123", "status": "completed",
             "conclusion": "failure", "url": "u/7"}]
    forge = _forge(monkeypatch, {"run list": _cp(json.dumps(runs))})
    assert forge.deploy_run_status(sha="abc123", workflow="deploy.yml") == ("failure", "u/7")


def test_deploy_run_status_none_when_no_run_on_that_sha(monkeypatch):
    # a run exists for the workflow but not (yet) on our commit → nothing to judge
    runs = [{"databaseId": 9, "headSha": "other", "status": "completed",
             "conclusion": "success", "url": "u/9"}]
    forge = _forge(monkeypatch, {"run list": _cp(json.dumps(runs))})
    assert forge.deploy_run_status(sha="abc123", workflow="deploy.yml") == ("none", None)

"""GitHubForge idempotency — retries must not double-open PRs or double-cut tags.

The durable runtime auto-retries activities (ADR-0001 D-16), so the side-effecting
forge calls must be safe to repeat. These drive the real GitHubForge with a fake
`_gh` that records calls and simulates GitHub's responses.
"""

from __future__ import annotations

import subprocess

from openfactory.adapters.forge.github import GitHubForge


def _cp(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class RecordingGh:
    """Stand-in for GitHubForge._gh: routes by the gh subcommand, records calls."""

    def __init__(self, *, existing_pr=None, tag_exists=False, sha="abc123"):
        self.existing_pr = existing_pr
        self.tag_exists = tag_exists
        self.sha = sha
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=120):
        self.calls.append(args)
        sub = args[0]
        if sub == "pr" and args[1] == "list":
            return _cp(stdout=(self.existing_pr or "") + ("\n" if self.existing_pr else ""))
        if sub == "pr" and args[1] == "create":
            return _cp(stdout="https://github.com/o/r/pull/9")
        if sub == "api":
            joined = " ".join(args)
            if "git/ref/tags/" in joined:  # tag existence probe
                return _cp(returncode=0 if self.tag_exists else 1)
            if "/commits/" in joined:  # sha resolution
                return _cp(stdout=self.sha + "\n")
            if "--method" in args and "git/refs" in joined:  # create ref
                return _cp(stdout="{}")
        return _cp()

    def count(self, sub, verb=None) -> int:
        return sum(1 for c in self.calls if c[0] == sub and (verb is None or c[1] == verb))


def _forge(gh: RecordingGh) -> GitHubForge:
    f = GitHubForge("o/r", token="t")
    f._gh = gh  # type: ignore[method-assign]
    return f


# --- open_pr ---
def test_open_pr_reuses_existing_and_does_not_create():
    gh = RecordingGh(existing_pr="https://github.com/o/r/pull/7")
    url = _forge(gh).open_pr(head="feat/x", base="main", title="t", body="b")
    assert url == "https://github.com/o/r/pull/7"
    assert gh.count("pr", "create") == 0  # no second PR


def test_open_pr_creates_when_none_exists():
    gh = RecordingGh(existing_pr=None)
    url = _forge(gh).open_pr(head="feat/x", base="main", title="t", body="b")
    assert url == "https://github.com/o/r/pull/9"
    assert gh.count("pr", "create") == 1


def test_open_pr_does_not_create_a_duplicate_when_the_lookup_fails():
    # a transient `gh pr list` error is "unknown", not "no PR" — must NOT blindly create
    def failing_gh(args, timeout=120):
        if args[0] == "pr" and args[1] == "list":
            return _cp(returncode=1, stderr="network error")
        return _cp(stdout="https://github.com/o/r/pull/9")

    f = GitHubForge("o/r", token="t")
    f._gh = failing_gh  # type: ignore[method-assign]
    import pytest

    with pytest.raises(RuntimeError, match="pr list failed"):
        f.open_pr(head="feat/x", base="main", title="t", body="b")


# --- create_tag ---
def test_create_tag_is_noop_when_tag_exists():
    gh = RecordingGh(tag_exists=True)
    _forge(gh).create_tag(tag="v1.4.0", ref="main")
    # probed existence, but never resolved a sha or POSTed a ref
    assert not any("/commits/" in " ".join(c) for c in gh.calls)
    assert not any("--method" in c for c in gh.calls)


def test_create_tag_creates_when_absent():
    gh = RecordingGh(tag_exists=False, sha="deadbeef")
    _forge(gh).create_tag(tag="v1.4.0", ref="main")
    posted = [c for c in gh.calls if "--method" in c]
    assert len(posted) == 1
    assert "ref=refs/tags/v1.4.0" in posted[0]
    assert "sha=deadbeef" in posted[0]

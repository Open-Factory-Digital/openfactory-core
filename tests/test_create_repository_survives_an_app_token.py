"""`create_repository` under a GitHub App installation token (pilot, 2026-08-13).

`gh repo create` is a GraphQL mutation GitHub refuses to EVERY App installation token, and the
pilot met it raw: "GraphQL: Resource not accessible by integration (createRepository)" — a
vendor's vocabulary, no remedy, the context half dead. What holds now:

  1. an ORGANISATION owner falls back to REST (`POST /orgs/{org}/repos`), which an App token
     with Administration write CAN use — the creation succeeds instead of refusing;
  2. that REST path failing too names the exact permission and the App settings page;
  3. a PERSONAL owner is told the truth — no App permission can do this — with both remedies
     named: the classic PAT the board already uses, or create-by-hand + `product declare`;
  4. any OTHER failure keeps the plain passthrough (no translation of what we cannot read).
"""

from __future__ import annotations

import pytest

from openfactory.adapters.forge.github import GitHubForge

_INTEGRATION = "GraphQL: Resource not accessible by integration (createRepository)"


class _Run:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _forge(monkeypatch, *, owner: str, owner_type: str, rest_ok: bool) -> tuple[GitHubForge,
                                                                                list[list[str]]]:
    forge = GitHubForge(f"{owner}/api", token="ghs_app")
    calls: list[list[str]] = []

    def gh(args, timeout=120):
        calls.append(list(args))
        key = " ".join(args)
        if key.startswith("repo view"):
            made = any(" ".join(c).startswith("api --method POST orgs/") and rest_ok
                       for c in calls[:-1])
            return _Run(stdout='{"name":"x"}' if made else "", returncode=0 if made else 1)
        if key.startswith("repo create"):
            return _Run(stderr=_INTEGRATION, returncode=1)
        if key.startswith(f"api users/{owner}"):
            return _Run(stdout=f"{owner_type}\n")
        if key.startswith(f"api --method POST orgs/{owner}/repos"):
            return _Run(returncode=0 if rest_ok else 1,
                        stderr="" if rest_ok else "HTTP 403: Resource not accessible")
        raise AssertionError(f"unrouted gh command: {key}")

    monkeypatch.setattr(forge, "_gh", gh)
    monkeypatch.setattr(forge, "_gh_read", lambda args, why: gh(args))
    return forge, calls


def test_an_organisation_owner_falls_back_to_REST_and_creates(monkeypatch):
    forge, calls = _forge(monkeypatch, owner="acme-org", owner_type="Organization",
                          rest_ok=True)

    full, created = forge.create_repository(name="dsk-context")

    assert (full, created) == ("acme-org/dsk-context", True)
    posted = [c for c in calls if " ".join(c).startswith("api --method POST orgs/")]
    assert posted, "the REST creation route was never taken"
    assert "name=dsk-context" in " ".join(posted[0])


def test_the_org_REST_path_failing_names_the_permission_and_the_page(monkeypatch):
    forge, _ = _forge(monkeypatch, owner="acme-org", owner_type="Organization", rest_ok=False)

    with pytest.raises(RuntimeError) as err:
        forge.create_repository(name="dsk-context")

    text = str(err.value)
    assert "Administration" in text and "Read and write" in text
    assert "product declare" in text, "the create-by-hand remedy must name the command"


def test_a_personal_owner_is_told_no_permission_fixes_this_and_both_remedies(monkeypatch):
    forge, calls = _forge(monkeypatch, owner="solo-dev", owner_type="User", rest_ok=False)

    with pytest.raises(RuntimeError) as err:
        forge.create_repository(name="podbeam-context")

    text = str(err.value)
    assert "personal account" in text
    assert "OPENFACTORY_TRACKER_TOKEN" in text, "the PAT the board already uses must be named"
    assert "product declare" in text
    assert not any(" ".join(c).startswith("api --method POST orgs/") for c in calls), (
        "the org REST route was tried against a user account")


def test_any_other_failure_keeps_the_plain_passthrough(monkeypatch):
    forge = GitHubForge("acme-org/api", token="ghs_app")

    def gh(args, timeout=120):
        key = " ".join(args)
        if key.startswith("repo view"):
            return _Run(returncode=1)
        if key.startswith("repo create"):
            return _Run(stderr="HTTP 502: bad gateway", returncode=1)
        raise AssertionError(f"unrouted gh command: {key}")

    monkeypatch.setattr(forge, "_gh", gh)
    monkeypatch.setattr(forge, "_gh_read", lambda args, why: gh(args))

    with pytest.raises(RuntimeError) as err:
        forge.create_repository(name="dsk-context")

    assert "bad gateway" in str(err.value)
    assert "Administration" not in str(err.value), (
        "a network failure was translated into a permission story nobody measured")

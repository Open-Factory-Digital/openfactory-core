"""When a client has no context repository, the platform can make one — #99 slice 2b.

`ProductConfig.docs_repo` is required, and the contract says why in as many words: *"a product
module with nowhere to write requirements is not a configuration, it is a mistake."* The product
owner decided where that somewhere is (2026-08-07): *"sempre na org do cliente. Definimos que se o
cliente não tiver um repositório de contexto temos que criar um. Se o cliente já tiver, ótimo,
usamos ele."*

MEASURED BEFORE IT WAS WRITTEN: nothing in `sdlc/` created or cloned a repository — there was no
`repo create` anywhere. So a client who already had a context repository could be onboarded and a
client who did not could not be. That is most of them, and it is the first hour of the engagement.

A SEPARATE PROTOCOL, like `ConfirmingChannel`. Creating a repository in somebody's organisation is
the most consequential thing this platform asks of a credential — everything else edits inside a
repository we were pointed at; this makes a new one, under their name, visible to their whole
company. Not every forge will have it and some deployments will withhold it, so a caller asks
`isinstance(forge, RepositoryCreatingForge)` and says so plainly when the answer is no, rather
than every adapter claiming an ability it may not have.
"""

from __future__ import annotations

import subprocess

import pytest

from openfactory.adapters.forge.base import RepositoryCreatingForge
from openfactory.adapters.forge.github import GitHubForge


class _Gh:
    """Records every `gh` invocation and answers from a script. The boundary is the CLI, so this
    is where a double belongs — everything above it is production code."""

    def __init__(self, *, exists: bool = False, create_fails: str = "",
                 vanishes_after_create: bool = False):
        self.calls: list[list[str]] = []
        self._exists = exists
        self._create_fails = create_fails
        self._vanishes = vanishes_after_create
        self._created = False

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        cmd = args[1:] if args and args[0] == "gh" else args
        if cmd[:2] == ["repo", "view"]:
            here = self._exists or (self._created and not self._vanishes)
            return subprocess.CompletedProcess(args, 0 if here else 1,
                                               '{"name":"x"}' if here else "", "not found")
        if cmd[:2] == ["repo", "create"]:
            if self._create_fails:
                return subprocess.CompletedProcess(args, 1, "", self._create_fails)
            self._created = True
            return subprocess.CompletedProcess(args, 0, "created", "")
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def gh(monkeypatch):
    def _install(**kw):
        fake = _Gh(**kw)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake
    return _install


def _forge() -> GitHubForge:
    return GitHubForge(repo="acme-corp/their-app", token="t")


# ── the capability is declared, not assumed ─────────────────────────────────────────────────────

def test_the_github_forge_declares_the_capability():
    assert isinstance(_forge(), RepositoryCreatingForge)


def test_a_forge_that_cannot_create_one_says_NO_rather_than_failing_later():
    """The whole reason this is a separate protocol. A caller must be able to ASK, and get a
    truthful no — an adapter that claimed the ability and raised at the call site would turn a
    configuration question into a failure in the middle of an onboarding."""
    class _ReadOnly:
        def push_remote(self):
            return None

    assert not isinstance(_ReadOnly(), RepositoryCreatingForge)


# ── the expected case is that it already exists ─────────────────────────────────────────────────

def test_a_repository_that_ALREADY_EXISTS_is_used_and_said_so(gh):
    """The enterprise-shaped client has one already, and so does any client onboarded once
    before, and so does a retry of an activity the durable runtime is re-running.

    The second value is the whole point: "we created a repository in your organisation" and "we
    found the one you already had" are different sentences to a client, and only one of them
    belongs in an email."""
    fake = gh(exists=True)

    repo, created = _forge().create_repository(name="their-app-context")

    assert (repo, created) == ("acme-corp/their-app-context", False)
    assert not any(c[1:3] == ["repo", "create"] for c in fake.calls), (
        "an existing repository was created over — the check before the create is what makes this "
        "idempotent")


def test_a_repository_that_does_NOT_exist_is_created(gh):
    fake = gh(exists=False)

    repo, created = _forge().create_repository(name="their-app-context")

    assert (repo, created) == ("acme-corp/their-app-context", True)
    assert any(c[1:3] == ["repo", "create"] for c in fake.calls), fake.calls


def test_it_is_PRIVATE_unless_asked_otherwise(gh):
    """A client's requirements are their business. Public by default would publish a company's
    internal roadmap on the day somebody ran onboarding, and no flag would undo it."""
    fake = gh(exists=False)

    _forge().create_repository(name="ctx")

    create = next(c for c in fake.calls if c[1:3] == ["repo", "create"])
    assert "--private" in create and "--public" not in create, create


# ── the organisation is never a parameter ───────────────────────────────────────────────────────

def test_the_ORGANISATION_comes_from_the_project_not_from_the_caller(gh):
    """The credential here is an installation with write access to a client's whole organisation.
    A caller that could name the org could create a repository in one this deployment was never
    pointed at — which is not a hypothetical, it is the blast radius of the token."""
    fake = gh(exists=False)

    repo, _ = _forge().create_repository(name="somebody-elses-org/ctx")

    assert repo == "acme-corp/ctx", (
        f"the caller's organisation was honoured: {repo}. The org must come from the project this "
        f"forge was built for")
    create = next(c for c in fake.calls if c[1:3] == ["repo", "create"])
    assert "acme-corp/ctx" in create, create


def test_a_forge_with_no_repo_at_all_REFUSES_rather_than_guessing():
    forge = GitHubForge(repo="", token="t")

    with pytest.raises(ValueError, match="no organisation"):
        forge.create_repository(name="ctx")


# ── a refusal must never read as success ────────────────────────────────────────────────────────

def test_a_creation_that_FAILS_raises_with_the_forge_s_own_words(gh):
    """A refusal reported as success would have the onboarding announce a repository nobody can
    push to, and the first sign would be the product role failing to write a requirement an hour
    later, in a message about something else.

    The error here is deliberately OUTSIDE the App-token class: "not accessible by integration"
    now gets a translated message with remedies (its own tests, pilot 2026-08-13); everything
    else keeps the forge's own words — a network failure must never be dressed as a permission
    story nobody measured."""
    gh(exists=False, create_fails="HTTP 502: bad gateway")

    with pytest.raises(RuntimeError, match="502"):
        _forge().create_repository(name="ctx")


def test_a_creation_that_CANNOT_BE_READ_BACK_is_treated_as_not_created(gh):
    """`gh` has answered 0 for requests that changed nothing — `delete_branch` documents the same
    trap one screen up in this adapter. So the exit status is not the answer; re-reading is."""
    gh(exists=False, vanishes_after_create=True)

    with pytest.raises(RuntimeError, match="cannot be read back"):
        _forge().create_repository(name="ctx")

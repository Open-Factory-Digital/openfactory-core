"""Creating a context repository is not a GitHub privilege.

The pilot operator, the moment the mixed-vendor half was fixed: this platform may not be
GitHub-only, because the deployment after the pilot is a 100% Azure DevOps enterprise
(2026-08-12). Until now `RepositoryCreatingForge` had exactly one implementation, so a
deployment with no GitHub anywhere could onboard a client who ALREADY had a context repository
and not one who did not — which is most of them, and it is the first hour of the engagement.

What these guards hold:

  1. the Azure Repos forge SATISFIES the protocol — the `isinstance` check the CLI gates on is
     the whole mechanism, and a method that exists under a different name would pass every unit
     test here while the command still refused;
  2. it is idempotent in both shapes an existing repository arrives in — listed before the
     POST, and the race where somebody creates it between the two calls;
  3. a creation reported and not listable RAISES rather than being believed;
  4. the coordinates come from the adapter, never from the caller — a PAT is organisation-wide;
  5. `private` is refused honestly rather than silently: Azure Repos has no per-repository
     visibility, and a caller must not believe it asked for something.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.azure_devops import AzureDevOpsError
from openfactory.adapters.forge.azure_devops import AzureReposForge
from openfactory.adapters.forge.base import RepositoryCreatingForge


class _Client:
    """The shared ADO client, doubled at its one door: `call`."""

    def __init__(self, *, existing: list[str] | None = None, create_raises: str = "",
                 appears_after_create: bool = True):
        self.existing = list(existing or [])
        self.create_raises = create_raises
        self.appears_after_create = appears_after_create
        self.calls: list[tuple[str, str, dict | None]] = []

    def call(self, method, path, *, body=None, params=None, **kw):
        self.calls.append((method, path, body))
        if method == "GET" and path == "git/repositories":
            return {"value": [{"name": n} for n in self.existing]}
        if method == "POST" and path == "git/repositories":
            if self.create_raises:
                raise AzureDevOpsError(self.create_raises)
            if self.appears_after_create:
                self.existing.append(str((body or {}).get("name")))
            return {"name": (body or {}).get("name")}
        raise AssertionError(f"unexpected call: {method} {path}")


@pytest.fixture
def forge(monkeypatch):
    def _build(client: _Client) -> AzureReposForge:
        f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline",
                            token="pat")
        monkeypatch.setattr(f, "_client", lambda: client)
        return f
    return _build


def test_the_azure_forge_satisfies_the_protocol_the_CLI_gates_on():
    """`product init --create-context` does `isinstance(forge, RepositoryCreatingForge)`. A
    method spelled differently would pass every test below and still be refused there."""
    assert issubclass(AzureReposForge, RepositoryCreatingForge)


def test_it_creates_in_the_adapters_own_project_and_says_it_created(forge):
    client = _Client()
    made, created = forge(client).create_repository(name="podbeam-context")

    assert (made, created) == ("Deskline/podbeam-context", True)
    posted = [c for c in client.calls if c[0] == "POST"]
    assert posted, "nothing was created"
    assert posted[0][2] == {"name": "podbeam-context",
                            "project": {"name": "Deskline"}}, (
        "the project must come from the adapter — a PAT is organisation-wide")


def test_an_existing_repository_is_FOUND_not_created_again(forge):
    client = _Client(existing=["podbeam-context"])

    made, created = forge(client).create_repository(name="podbeam-context")

    assert (made, created) == ("Deskline/podbeam-context", False)
    assert not [c for c in client.calls if c[0] == "POST"], "it created over an existing one"


def test_losing_the_race_to_a_concurrent_create_is_the_expected_case(forge):
    """Somebody — a retry of a durable activity, a person, an earlier onboarding — made it
    between the list and the POST. The name being taken IS the outcome this asked for."""
    client = _Client(create_raises="TF400948: A Git repository with the name already exists.")
    client.existing = []

    class _Racing(_Client):
        def call(self, method, path, *, body=None, params=None, **kw):
            if method == "POST" and path == "git/repositories":
                self.existing.append("podbeam-context")  # the winner's repository appears
            return super().call(method, path, body=body, params=params, **kw)

    racing = _Racing(create_raises="TF400948: A Git repository with the name already exists.")
    made, created = forge(racing).create_repository(name="podbeam-context")

    assert (made, created) == ("Deskline/podbeam-context", False)


def test_a_creation_that_cannot_be_read_back_RAISES(forge):
    """A repository reported created and unreachable surfaces an hour later as the product role
    failing to write a requirement, in a message about something else."""
    client = _Client(appears_after_create=False)

    with pytest.raises(AzureDevOpsError, match=r"cannot be listed back"):
        forge(client).create_repository(name="podbeam-context")


def test_a_failure_that_is_NOT_a_name_clash_is_raised_unchanged(forge):
    client = _Client(create_raises="TF401019: access denied")

    with pytest.raises(AzureDevOpsError, match=r"access denied"):
        forge(client).create_repository(name="podbeam-context")


def test_without_a_project_it_refuses_instead_of_guessing_one(monkeypatch):
    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")
    monkeypatch.setattr(f, "project", "")

    with pytest.raises(ValueError, match=r"no Azure DevOps project|refusing to guess"):
        f.create_repository(name="podbeam-context")


#: The other half of the same requirement: a project that ALREADY has a context repository must
#: be USED, never re-created — and an enterprise organisation has both shapes at once, projects
#: that keep one and projects that do not (2026-08-12). A context
#: repository that already exists may live in ANOTHER project of the same organisation — and
#: every repository route on this vendor is project-scoped, while `_repo_or_self` throws the
#: qualifier away. Aimed at the wrong project the call answers 404: a repository the client can
#: see in their browser, reported missing.

def test_a_context_repo_in_ANOTHER_project_is_cloned_from_that_project():
    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")

    url = f.clone_url("SharedDocs/product-context", token="pat")

    assert "/SharedDocs/_git/product-context" in url, url
    assert "/Deskline/_git/" not in url, "the qualifier was dropped — wrong project"


def test_a_qualifier_naming_THIS_project_still_behaves_exactly_as_before():
    """C-18 qualifies with this adapter's own project on every card. That path must not move."""
    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")

    assert "/Deskline/_git/dsk-ui" in f.clone_url("Deskline/dsk-ui", token="pat")
    assert "/Deskline/_git/dsk-api" in f.clone_url("", token="pat")


def test_the_pull_request_is_opened_in_the_project_the_ref_NAMES(monkeypatch):
    """The idempotency lookup and the create must both land in the other project — a lookup in
    the wrong one answers "no pull request from that branch", which is the single answer that
    makes this open a second one."""
    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")
    asked: list[str] = []

    class _ProjectAwareClient:
        def __init__(self, project):
            self.project = project

        def call(self, method, path, *, body=None, params=None, **kw):
            asked.append(f"{method} {self.project} {path}")
            if method == "GET":
                return {"value": []}
            return {"pullRequestId": 12,
                    "repository": {"name": "product-context",
                                   "webUrl": "https://dev.azure.com/acme-ai/SharedDocs/_git/"
                                             "product-context"}}

    from openfactory.adapters.forge import azure_devops as mod

    monkeypatch.setattr(mod, "AzureDevOpsClient",
                        lambda **kw: _ProjectAwareClient(kw.get("project")))
    f.open_pr(head="openfactory/manifest", base="main", title="t", body="b",
              repo="SharedDocs/product-context")

    assert asked, "no call was made"
    assert all("SharedDocs" in a for a in asked), (
        f"a call went to the wrong project: {asked}")


def test_the_name_is_a_leaf_never_a_path(forge):
    client = _Client()

    made, _ = forge(client).create_repository(name="some/where/podbeam-context")

    assert made == "Deskline/podbeam-context"

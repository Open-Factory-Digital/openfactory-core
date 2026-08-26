"""`product init` reaches a client who has NO context repository — #99 slice 2b, end to end.

The verb to create one exists (`RepositoryCreatingForge`). This is the half that makes it
reachable: until now `product init` on a project with no `docs_repo` planned against an empty
temporary directory with no git remote, so `--write` arrived at a `git push origin` that could not
resolve one — a confusing failure about a remote, for a project whose real problem is that it has
nowhere to keep requirements at all.

TWO PROPERTIES DECIDE WHETHER THIS IS FINISHED, and only one of them is the creation:

    it is CONSENTED — making a repository under a client's name, visible to their whole company,
    is not something a command does because it was convenient;

    it is RECORDED — the product module stays off until the registry names the repository
    (`ProductConfig.docs_repo` is required, and its contract says a module with nowhere to write
    requirements *"is not a configuration, it is a mistake"*). An onboarding that created one and
    did not write it down leaves the client with an empty repository and a role that still
    refuses to speak. That is the shape of "done" that is not done.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory.cli import app


class _Forge:
    """A forge that can create repositories, recording what it was asked for.

    It carries `clone_url` and `open_pr` too, because the command asks the PORT for both now —
    it used to compose a `github.com` URL by hand and shell out to `gh pr create`, which on an
    Azure DevOps deployment cloned a host the client does not use and refused the review
    request after pushing the branch."""

    def __init__(self, *, existing: bool = False, host: str = "github.com"):
        self.asked: list[dict] = []
        self.opened: list[dict] = []
        self._existing = existing
        self._host = host

    def create_repository(self, *, name, private=True, description=""):
        self.asked.append({"name": name, "private": private, "description": description})
        return f"acme-corp/{name}", not self._existing

    def clone_url(self, repo, *, token=None):
        return f"https://{self._host}/{repo}"

    def open_pr(self, *, head, base, title, body, repo=""):
        self.opened.append({"head": head, "base": base, "title": title, "repo": repo})
        return f"https://{self._host}/{repo}/pull/1"


class _CannotCreate:
    """A forge without the capability — the honest no this protocol exists to make possible."""

    def push_remote(self):
        return None


class _Registry:
    """The registry, doubled at the two methods this path uses."""

    def __init__(self, project):
        self._project = project
        self.recorded: list[tuple[str, str]] = []

    def get(self, name):
        return self._project

    def set_docs_repo(self, name, docs_repo):
        self.recorded.append((name, docs_repo))
        # the real registry answers later `get()`s with what was recorded — a double that kept
        # answering the pre-record project would hide exactly the stale-object defect this
        # file's newest test exists to catch
        from openfactory.contracts.product import ProductConfig

        self._project = self._project.model_copy(
            update={"product": ProductConfig(docs_repo=docs_repo)})


def _project(docs_repo: str = ""):
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    return Project(
        name="acme", repo_path="/t",
        tracker=ProviderRef(kind="github", repo="acme-corp/their-app"),
        forge=ProviderRef(kind="github", repo="acme-corp/their-app"),
        product=ProductConfig(docs_repo=docs_repo) if docs_repo else None,
    )


@pytest.fixture
def onboarding(monkeypatch):
    """Wire the CLI to doubles at the two seams that leave this machine: the forge and the
    registry. Everything between them is production code."""
    def _wire(*, forge=None, docs_repo=""):
        from openfactory import registry as registry_module
        from openfactory.adapters.forge import registry as forge_registry

        project = _project(docs_repo)
        reg = _Registry(project)
        monkeypatch.setattr(forge_registry, "build_forge",
                            lambda *a, **kw: forge if forge is not None else _Forge())
        monkeypatch.setattr(registry_module, "ProjectRegistry", lambda: reg)
        return reg
    return _wire


# ── without consent, it refuses and says what to do ─────────────────────────────────────────────

def test_a_project_with_NO_context_repository_is_refused_and_told_what_to_do(onboarding):
    """A refusal that only says no sends somebody to read the source. This one names both ways
    forward — create one, or point at the one they already have."""
    reg = onboarding()

    result = CliRunner().invoke(app, ["product", "init", "acme"])

    assert result.exit_code == 1, result.output
    assert "no context repository" in result.output, result.output
    assert "--create-context" in result.output, (
        f"the refusal does not name the way forward: {result.output}")
    assert "product declare" in result.output, (
        "the client who ALREADY has one is not told the COMMAND that points at it")
    assert reg.recorded == [], "a repository was recorded without consent"


def test_nothing_is_created_without_the_flag(onboarding):
    """The consent is the point, not the message. A command that printed a warning and created it
    anyway would be worse than one that never asked."""
    forge = _Forge()
    onboarding(forge=forge)

    CliRunner().invoke(app, ["product", "init", "acme"])

    assert forge.asked == [], "a repository was created in a client's organisation with no consent"


# ── with consent, it creates, names it deliberately, and RECORDS it ─────────────────────────────

def test_with_consent_it_creates_and_RECORDS_the_repository(onboarding):
    """The half that makes the creation real. Without the record the product module stays off and
    the client is left with an empty repository and a role that will not speak."""
    forge = _Forge()
    reg = onboarding(forge=forge)

    result = CliRunner().invoke(app, ["product", "init", "acme", "--create-context"])

    assert forge.asked, f"nothing was created: {result.output}"
    assert reg.recorded == [("acme", "acme-corp/acme-context")], (
        f"the repository was created and never written to the registry — the product module will "
        f"stay off: {reg.recorded}")


def test_the_create_run_reaches_the_plan_instead_of_refusing_its_own_record(onboarding,
                                                                            monkeypatch):
    """The v2 verification pass reproduced the theatre this guards against: the repository was
    created AND recorded, then `plan()` read the pre-creation project object and refused
    "no `product:` section" — exit 1, no todos, no PR, on the exact run the docs sell as one
    command. Every earlier test's clone failed first, so plan() was never reached. The clone is
    stubbed here precisely so the run gets that far."""
    import subprocess as real_subprocess
    from pathlib import Path

    forge = _Forge()
    reg = onboarding(forge=forge)

    class _Done:
        returncode, stdout, stderr = 0, "", ""

    def _fake_git(cmd, **kw):
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return _Done()

    monkeypatch.setattr(real_subprocess, "run", _fake_git)
    result = CliRunner().invoke(app, ["product", "init", "acme", "--create-context"])

    assert reg.recorded == [("acme", "acme-corp/acme-context")]
    assert result.exit_code == 0, result.output
    assert "no `product:` section" not in result.output, (
        "plan() refused the record the same run just wrote — the project object is stale")
    assert "docs_repo" in result.output, "the remaining wiring was not printed as todos"


def test_the_context_repository_is_reached_THROUGH_THE_PORT_on_any_vendor(onboarding,
                                                                          monkeypatch, tmp_path):
    """`--write` composed a `github.com` clone URL by hand and shelled out to `gh pr create`.
    On an Azure DevOps deployment — where the whole point is that no GitHub exists anywhere —
    that cloned a host the client does not use, and after the branch was pushed the review
    request was refused by a tool that was never going to work there.

    The pilot operator, when this was named as a known gap: *"porque isso ainda está
    hardcoded? deveria estar pronto para GH e ADO"* (2026-08-12). Both acts go through the
    forge contract now, so the vendor is whatever the registry says.
    """
    forge = _Forge(host="dev.azure.com")
    onboarding(forge=forge, docs_repo="acme-corp/acme-context")

    seen: list[list[str]] = []

    class _Done:
        returncode, stdout, stderr = 0, "main\n", ""

    def _fake_git(cmd, **kw):
        seen.append(list(cmd))
        if cmd[:2] == ["git", "clone"]:
            from pathlib import Path

            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return _Done()

    import subprocess as real_subprocess

    monkeypatch.setattr(real_subprocess, "run", _fake_git)
    result = CliRunner().invoke(app, ["product", "init", "acme", "--write"])

    assert result.exit_code == 0, result.output
    cloned = next(c for c in seen if c[:2] == ["git", "clone"])
    assert "dev.azure.com" in " ".join(cloned), (
        f"the clone URL was not asked of the forge: {cloned}")
    assert not any("gh" == c[0] for c in seen), "it still shells out to `gh`"
    assert forge.opened, "no review request was opened through the port"
    assert forge.opened[0]["repo"] == "acme-corp/acme-context"
    assert forge.opened[0]["base"] == "main", "the base must be read from the clone, not assumed"


def test_the_NAME_is_derived_and_not_a_free_parameter(onboarding):
    """A repository in a client's organisation is not a place to accept free text from whoever
    typed the command. The name comes from the project; the organisation from the forge."""
    forge = _Forge()
    onboarding(forge=forge)

    CliRunner().invoke(app, ["product", "init", "acme", "--create-context"])

    assert forge.asked[0]["name"] == "acme-context", forge.asked
    assert forge.asked[0]["private"] is True, (
        "a client's requirements were about to be published")


def test_a_repository_that_ALREADY_EXISTS_is_reported_as_FOUND_not_created(onboarding):
    """"We created a repository in your organisation" and "we found the one you already had" are
    different sentences, and only one of them belongs in an email to a client."""
    onboarding(forge=_Forge(existing=True))

    result = CliRunner().invoke(app, ["product", "init", "acme", "--create-context"])

    assert "found" in result.output and "created" not in result.output.split("found")[0], (
        f"an existing repository was announced as newly created: {result.output}")


# ── a forge that cannot do it says so, once ─────────────────────────────────────────────────────

def test_a_forge_WITHOUT_the_capability_says_so_in_one_sentence(onboarding):
    """The reason `RepositoryCreatingForge` is a separate protocol. A deployment whose forge
    cannot — or may not — create repositories hears it here, before anything is cloned, rather
    than halfway through with a provider's own error."""
    reg = onboarding(forge=_CannotCreate())

    result = CliRunner().invoke(app, ["product", "init", "acme", "--create-context"])

    assert result.exit_code == 1, result.output
    assert "cannot create a repository" in result.output, result.output
    assert "product declare" in result.output, (
        "the operator is not told the command that declares a hand-made repository")
    assert reg.recorded == [], "a repository was recorded that was never created"

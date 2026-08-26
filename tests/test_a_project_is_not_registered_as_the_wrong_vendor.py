"""`project init` registered every non-Azure URL as GitHub (#162, `cli.py:408`).

    kwargs = {"name": name, "repo_path": repo_path,
              "tracker": ProviderRef(kind="github", repo=inferred, options={})}

The Azure branch above it refuses by NAME — it tells the operator which command to use. Everything
else fell through to this line, so a GitLab, Bitbucket, Gitea or self-hosted URL was written into
the registry as GitHub.

IT IS NOT A LABEL THAT STAYS PUT. `factory._authenticated` reads that row and offers a github.com
credential to whatever host the URL actually names — the cross-vendor leak fixed earlier on this
same card, whose PRODUCER is this line. The doctor reads it too and reports a GitHub remedy over a
perfectly good PAT.

Every other registry in this platform refuses to guess a provider — `build_forge` and
`build_tracker` both raise on a kind they do not know, with a sentence saying why. This is the
door they were all guessing behind.
"""

from __future__ import annotations

import pytest

from openfactory.cli import _foreign_host, _known_forges

# ── 1. whose host is it ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://gitlab.com/o/r.git",
    "git@gitlab.com:o/r.git",
    "https://bitbucket.org/o/r",
    "https://git.acme-internal.example/o/r.git",
])
def test_a_host_this_build_does_not_implement_is_NAMED(url):
    """Named, not merely refused: an operator has to know which word in their URL is the problem."""
    assert _foreign_host(url), f"{url} would be registered as GitHub"


@pytest.mark.parametrize("url", [
    "https://github.com/o/r.git",
    "git@github.com:o/r.git",
    "https://dev.azure.com/contoso/Payments/_git/r",
    "git@ssh.dev.azure.com:v3/contoso/Payments/r",
])
def test_and_a_host_it_DOES_implement_is_not(url):
    """The positive twin. Refusing everything would be the same defect facing the other way — a
    command that registers nothing at all."""
    assert _foreign_host(url) == ""


@pytest.mark.parametrize("path", ["/home/me/proj", "./acme", "~/Projects/acme", ""])
def test_a_LOCAL_path_names_no_host_and_is_not_foreign(path):
    """An operator registering a working copy is the ordinary local case this command exists for.
    A path carries no host, so there is nothing to refuse."""
    assert _foreign_host(path) == ""


def test_a_github_ENTERPRISE_host_is_ours_once_the_deployment_says_so(monkeypatch):
    """We cannot know `github.acme.com` is GitHub, and guessing is what this fixes. `GH_HOST` is
    how a deployment says so — the same variable `clone_url`, `ticket_url` and the board link all
    honour — so the refusal names it as the remedy rather than being a dead end."""
    assert _foreign_host("https://github.acme.com/o/r") == "github.acme.com"

    monkeypatch.setenv("GH_HOST", "github.acme.com")

    assert _foreign_host("https://github.acme.com/o/r") == ""


def test_the_known_list_is_READ_from_the_registry():
    """A hand-written list here would go stale the day a fourth forge lands, and the message an
    operator reads would name vendors that no longer match what the build supports."""
    from openfactory.adapters.forge.registry import FORGES

    assert set(_known_forges()) == set(FORGES)
    assert len(_known_forges()) >= 2


# ── 2. the door itself ──────────────────────────────────────────────────────────────────────────

def _init(tmp_path, monkeypatch, url):
    """`project init` against an empty registry, up to the point it would register."""
    import typer

    from openfactory import cli

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    said: list[str] = []
    monkeypatch.setattr(typer, "echo", lambda text="", **k: said.append(str(text)))
    monkeypatch.setattr(cli.typer, "echo", lambda text="", **k: said.append(str(text)))
    try:
        # THE OPTIONS ARE PASSED EXPLICITLY. Calling a typer command as a function leaves its
        # defaults as `OptionInfo` objects, and `repo or _infer_repo(...)` would then hand one to
        # pydantic — a failure of this harness, not of the command a CLI invocation runs.
        cli.project_init(name="acme", repo_path=url, repo=None, board_owner=None, language=None,
                         provider=None)
    except SystemExit as exit_:
        return said, exit_.code
    except typer.Exit as exit_:
        return said, exit_.exit_code
    return said, 0


def test_a_GITLAB_url_is_REFUSED_rather_than_labelled_github(tmp_path, monkeypatch):
    said, code = _init(tmp_path, monkeypatch, "https://gitlab.com/o/r.git")

    assert code != 0, "a GitLab URL was accepted"
    joined = " ".join(said)
    # THE HOST IS NAMED IN THE REFUSAL ITSELF, not only in the remedy line below it: an operator
    # reading "that is not a forge this build implements" cannot tell which word in their URL is
    # the problem, and the `GH_HOST=` line mentions the host for a different reason.
    refusal = next((ln for ln in joined.splitlines() if "not a forge" in ln), "")
    assert "gitlab.com" in refusal, f"the refusal does not name the host: {refusal!r}"
    assert "GH_HOST" in joined, "the Enterprise remedy is not offered"


def test_and_the_registry_is_LEFT_EMPTY(tmp_path, monkeypatch):
    """Refusing after writing the row would be the worst of both: the operator is told no and the
    wrong label is on disk for the doctor and the credential resolver to read."""
    from openfactory.registry import ProjectRegistry

    _init(tmp_path, monkeypatch, "https://gitlab.com/o/r.git")
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))

    with pytest.raises(KeyError):
        ProjectRegistry().get("acme")


def test_a_GITHUB_url_still_registers(tmp_path, monkeypatch):
    """The path every existing deployment takes, unchanged."""
    from openfactory.registry import ProjectRegistry

    _init(tmp_path, monkeypatch, "https://github.com/o/r.git")

    got = ProjectRegistry().get("acme")
    assert got.tracker.kind == "github" and got.tracker.repo == "o/r"


def test_an_AZURE_url_keeps_its_OWN_refusal(tmp_path, monkeypatch):
    """It already refused by name, pointing at the command that carries the coordinates. The new
    check must not swallow that sentence — an operator sent to `project add` gets a working
    registration; one told "unsupported vendor" gives up."""
    said, code = _init(tmp_path, monkeypatch, "https://dev.azure.com/contoso/Payments/_git/r")

    assert code != 0
    joined = " ".join(said)
    assert "Azure DevOps" in joined, f"the Azure refusal lost its own diagnosis: {joined}"
    assert "project add" in joined, f"the Azure remedy was replaced: {joined}"

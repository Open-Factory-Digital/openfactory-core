"""`openfactory project add` produces a VALID Azure DevOps entry — the funnel review's hard stop.

The pre-pilot funnel review (2026-08-09) walked the enterprise ADO scenario start to first
ticket and found it dead at registration: `project add` mapped only `--board-owner`/`--board-number`
into GitHub-shaped options, so NO flag combination produced an entry the ADO adapters could
construct from — the platform sold the axis and the CLI could not register it.

The fix follows the platform's own rule that a declaration is read, not re-asked: the
dev.azure.com clone URL the operator pastes ALREADY names the organisation, the project and the
repository, so registering with it needs no coordinate flags at all. What these tests pin:

  - the three URL shapes ADO itself hands out all parse to the same coordinates
  - the entry splits the axes correctly: tracker.repo = the ADO PROJECT (work items live in a
    project), forge.repo = the git REPOSITORY inside it — collapsing them is how a three-repo
    product sends the agent to the wrong tree
  - a URL that carries no coordinates refuses BY NAME (exit 2), never registers a guess
  - the GitHub path infers `--repo` from a clone URL instead of demanding a flag re-typing it
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from openfactory.cli import _ado_coordinates, app

_URL = "https://dev.azure.com/acme-ai/Deskline/_git/dsk-api"


def _add(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return CliRunner().invoke(app, ["project", "add", "dsk", *args])


def _saved(tmp_path, monkeypatch, name="dsk"):
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    return ProjectRegistry().get(name)


# ── the URL parser: the three shapes ADO hands out ───────────────────────────────────────────


@pytest.mark.parametrize("url", [
    _URL,
    _URL + ".git",
    _URL + "/",
    "https://acme-ai@dev.azure.com/acme-ai/Deskline/_git/dsk-api",  # browser copy
    "git@ssh.dev.azure.com:v3/acme-ai/Deskline/dsk-api",
    "https://acme-ai.visualstudio.com/Deskline/_git/dsk-api",
    "https://acme-ai.visualstudio.com/DefaultCollection/Deskline/_git/dsk-api",
])
def test_every_shape_ado_hands_out_parses_to_the_same_coordinates(url):
    assert _ado_coordinates(url) == ("acme-ai", "Deskline", "dsk-api")


def test_a_project_name_with_spaces_survives_the_url():
    """An ADO project may contain spaces — `%20` in the URL, a real space in every API route."""
    got = _ado_coordinates("https://dev.azure.com/acme/Desk%20Line/_git/dsk-api")
    assert got == ("acme", "Desk Line", "dsk-api")


@pytest.mark.parametrize("not_ado", [
    "https://github.com/acme/repo.git",
    "git@github.com:acme/repo.git",
    "/home/me/checkout",
    "https://dev.azure.com/acme",  # no repository segment — a guess here aims at the wrong tree
])
def test_anything_else_answers_empty_never_a_guess(not_ado):
    assert _ado_coordinates(not_ado) == ("", "", "")


# ── the entry it writes ──────────────────────────────────────────────────────────────────────


def test_the_clone_url_is_the_whole_registration(tmp_path, monkeypatch):
    """No --provider, no coordinate flags: the URL declares the vendor and the coordinates."""
    result = _add(tmp_path, monkeypatch, _URL)

    assert result.exit_code == 0, result.output
    saved = _saved(tmp_path, monkeypatch)
    assert saved.tracker.kind == "azure_devops"
    assert saved.tracker.repo == "Deskline"          # the ADO PROJECT — work items live here
    assert saved.tracker.options["organization"] == "acme-ai"
    assert saved.forge.kind == "azure_devops"
    assert saved.forge.repo == "dsk-api"                 # the git repository inside it
    assert saved.forge.options == {"organization": "acme-ai", "project": "Deskline"}


def test_flags_override_what_the_url_says(tmp_path, monkeypatch):
    result = _add(tmp_path, monkeypatch, _URL, "--repository", "dsk-portal",
                  "--work-item-type", "User Story", "--token-env", "ACME_ADO_PAT")

    assert result.exit_code == 0, result.output
    saved = _saved(tmp_path, monkeypatch)
    assert saved.forge.repo == "dsk-portal"
    assert saved.tracker.options["work_item_type"] == "User Story"
    # the registry names the variable on BOTH axes; the environment holds the value
    assert saved.tracker.options["token_env"] == "ACME_ADO_PAT"
    assert saved.forge.options["token_env"] == "ACME_ADO_PAT"


def test_missing_coordinates_refuse_by_name_and_register_nothing(tmp_path, monkeypatch):
    result = _add(tmp_path, monkeypatch, "/some/local/checkout", "--provider", "azure_devops")

    assert result.exit_code == 2
    for flag in ("--organization", "--ado-project", "--repository"):
        assert flag in result.output
    assert "dev.azure.com/<organization>/<project>/_git/<repository>" in result.output
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    with pytest.raises(KeyError):
        ProjectRegistry().get("dsk")


def test_the_entry_it_writes_is_one_the_adapters_can_construct_from(tmp_path, monkeypatch):
    """The point of the whole card: registration → adapter construction with no hand edit.
    Built for real, not asserted from the YAML — the tracker, the forge and the board all
    resolve from the saved entry without raising."""
    assert _add(tmp_path, monkeypatch, _URL).exit_code == 0
    saved = _saved(tmp_path, monkeypatch)

    from openfactory.adapters.board.factory import build_board
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.adapters.tracker.registry import build_tracker

    tracker = build_tracker(saved)
    forge = build_forge(saved)
    board = build_board(saved)
    assert tracker.organization == forge.organization == board.organization == "acme-ai"
    assert tracker.project == board.project == "Deskline"
    assert forge.repo == "dsk-api"


# ── the GitHub path loses a flag, not a behaviour ────────────────────────────────────────────


def test_github_repo_is_inferred_from_the_clone_url(tmp_path, monkeypatch):
    result = _add(tmp_path, monkeypatch, "https://github.com/acme/api.git")

    assert result.exit_code == 0, result.output
    saved = _saved(tmp_path, monkeypatch)
    assert saved.tracker.kind == "github"
    assert saved.tracker.repo == "acme/api"


def test_an_explicit_repo_flag_still_wins(tmp_path, monkeypatch):
    result = _add(tmp_path, monkeypatch, "https://github.com/acme/api.git",
                  "--repo", "acme/monorepo")

    assert result.exit_code == 0, result.output
    assert _saved(tmp_path, monkeypatch).tracker.repo == "acme/monorepo"


def test_project_init_on_a_registered_ado_project_never_touches_the_github_board(tmp_path,
                                                                                 monkeypatch):
    """The board half of `project init` creates GitHub Projects v2 boards and nothing else.
    On a registered ADO project it must SKIP with the pointer, not build a GitHub board no
    ticket will ever cross — the supported-looking wrong system, again."""
    assert _add(tmp_path, monkeypatch, _URL).exit_code == 0
    from openfactory.adapters.tracker import github_board_setup

    def _never(**kw):
        raise AssertionError("create_board was called for an azure_devops tracker")

    monkeypatch.setattr(github_board_setup, "create_board", _never, raising=True)
    result = CliRunner().invoke(app, ["project", "init", "dsk"])

    assert result.exit_code == 0, result.output
    assert "azure-devops" in result.output


def test_project_init_refuses_to_mint_a_github_entry_over_an_ado_url(tmp_path, monkeypatch):
    """`project init` scaffolds GitHub (kind, board, manifest). Fed an ADO URL it used to
    register a GitHub-shaped entry over Azure coordinates — a supported-looking project pointed
    at the wrong system, the exact failure the tracker registry refuses one layer down."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    result = CliRunner().invoke(app, ["project", "init", "dsk", _URL])

    assert result.exit_code == 2
    assert "project add" in result.output
    assert "azure-devops" in result.output

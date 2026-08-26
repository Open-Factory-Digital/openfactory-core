"""A stranger's first hour fails by NAME, never by stack trace — the pre-pilot review's rule.

Three failures the 2026-08-09 review measured on a clean machine, each ending in a raw traceback
at the exact moment the docs' own order produces it: `doctor` before `project add` (KeyError),
any GitHub command without the `gh` CLI (FileNotFoundError), and board setup the same. Each now
refuses in one line that names the fix — because the person reading it is, by definition, the one
who does not know this codebase yet.
"""

from __future__ import annotations

import subprocess

import pytest
from typer.testing import CliRunner

from openfactory.cli import app


def test_doctor_on_an_unregistered_project_refuses_by_name(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "reg.yaml"))

    result = CliRunner().invoke(app, ["doctor", "ghost"])

    assert result.exit_code == 2, result.output
    assert "not registered" in result.output and "project add ghost" in result.output
    assert "Traceback" not in result.output and "KeyError" not in result.output
    assert "none yet" in result.output  # an empty registry says so instead of listing nothing


def test_the_refusal_lists_what_IS_registered(tmp_path, monkeypatch):
    """The wrong name beside the right ones is usually a typo answering itself."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "reg.yaml"))
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    ProjectRegistry().add(Project(name="myapp", repo_path=str(tmp_path),
                                  tracker=ProviderRef(kind="github", repo="o/myapp"),
                                  forge=ProviderRef(kind="github", repo="o/myapp")))

    result = CliRunner().invoke(app, ["doctor", "myap"])

    assert result.exit_code == 2 and "myapp" in result.output


def _raise_file_not_found(*args, **kwargs):
    raise FileNotFoundError(2, "No such file or directory", "gh")


def test_a_missing_gh_cli_is_a_named_refusal_in_the_tracker(monkeypatch):
    from openfactory.adapters.tracker.github import GitHubIssuesTracker

    monkeypatch.setattr(subprocess, "run", _raise_file_not_found)
    tracker = GitHubIssuesTracker("o/r")

    with pytest.raises(RuntimeError, match=r"`gh` CLI is not installed.*cli\.github\.com"):
        tracker._gh(["issue", "view", "1"])


def test_a_missing_gh_cli_is_a_named_refusal_in_board_setup(monkeypatch):
    from openfactory.adapters.tracker import github_board_setup as setup

    monkeypatch.setattr(setup.subprocess, "run", _raise_file_not_found)

    with pytest.raises(setup.BoardSetupError, match=r"`gh` CLI is not installed"):
        setup._gh_graphql("query {}", None)


def test_board_creation_with_no_credential_refuses_in_OUR_vocabulary(monkeypatch):
    """The first pilot funnel run (2026-08-10) hit this and was handed gh's own words —
    "run `gh auth login` … or populate GH_TOKEN" — inside a container where neither is a thing
    the operator should do. The refusal happens BEFORE the subprocess, names our variable, the
    scopes, the personal-account caveat and the re-run."""
    from openfactory.adapters.tracker import github_board_setup as setup

    monkeypatch.delenv("GH_TOKEN", raising=False)

    def _never(*a, **kw):
        raise AssertionError("gh was invoked with no credential — the refusal must come first")

    monkeypatch.setattr(setup.subprocess, "run", _never)

    with pytest.raises(setup.BoardSetupError) as err:
        setup.create_board(owner="someone", title="demo", token=None)
    text = str(err.value)
    assert "OPENFACTORY_TRACKER_TOKEN" in text
    assert "repo + project" in text or "repo +" in text
    assert "github.md" in text, "the personal-account caveat must be pointed at"
    assert "idempotent" in text, "the re-run path must be named"


#: GitHub's scope refusal, VERBATIM from the pilot's terminal (2026-08-12). It prints TWO
#: lists — what the query requires and what the token holds — and the first version of this
#: translation matched the word `project` anywhere in the message, so a token that already HAD
#: `project` was told to add it while the missing `read:org` went unnamed. This fixture is the
#: real message precisely because the imagined one passed a wrong implementation.
_REAL_SCOPE_REFUSAL = (
    "gh: Your token has not been granted the required scopes to execute this query. "
    "The 'id' field requires one of the following scopes: ['read:org'], but your token has "
    "only been granted the: ['project', 'repo'] scopes.")


def test_a_scope_refusal_names_the_MISSING_scope_not_one_the_token_already_has(monkeypatch):
    from openfactory.adapters.tracker import github_board_setup as setup

    class _Refused:
        returncode = 1
        stdout = ""
        stderr = _REAL_SCOPE_REFUSAL

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: _Refused())

    with pytest.raises(setup.BoardSetupError) as err:
        setup._gh_graphql("query {}", "ghp_has_project_not_read_org")
    text = str(err.value)
    assert "`read:org`" in text, "the refusal must name the scope GitHub actually requires"
    assert "missing `project`" not in text, (
        "the token HAS `project` — naming it as missing sends the operator to re-tick a box "
        "that is already ticked, which is what happened live")
    assert "idempotent" in text


def test_the_missing_scope_list_is_read_from_the_REQUIRED_half(monkeypatch):
    """The unit behind it, both directions: required-minus-granted, and nothing when the
    message is not a scope refusal at all."""
    from openfactory.adapters.tracker.github_board_setup import _missing_scopes

    assert _missing_scopes(_REAL_SCOPE_REFUSAL) == ["read:org"]
    assert _missing_scopes("gh: Bad credentials (HTTP 401)") == []


def test_a_personal_account_board_never_needs_an_ORGANISATION_scope(monkeypatch):
    """The defect under the mistranslation: `_owner_id` probes `organization(login:)` first,
    that query needs `read:org` — an ORG scope, meaningless on a personal account — and GitHub
    FAILS it instead of answering null, so the user fallback that exists for exactly this case
    was never reached. A `repo` + `project` token, exactly what the guide prescribes, could not
    create a personal board (measured live, 2026-08-12)."""
    import json

    from openfactory.adapters.tracker import github_board_setup as setup

    asked = []

    class _Answer:
        def __init__(self, code, out="", err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    def _fake(cmd, **kw):
        query = " ".join(cmd)
        asked.append("organization" if "organization(login" in query else "user")
        if "organization(login" in query:
            return _Answer(1, err=_REAL_SCOPE_REFUSAL)
        return _Answer(0, out=json.dumps({"data": {"user": {"id": "U_kgDO"}}}))

    monkeypatch.setattr(setup.subprocess, "run", _fake)

    assert setup._owner_id("solo-dev", "ghp_repo_and_project") == "U_kgDO"
    assert asked == ["organization", "user"], "the user fallback must be reached"


def test_an_expired_tracker_token_says_EXPIRED_not_bad_credentials(monkeypatch):
    """A classic token defaults to 30 days, so the board stops moving weeks after setup —
    'Bad credentials' sends somebody hunting a wrong token instead of a lapsed one."""
    from openfactory.adapters.tracker import github_board_setup as setup

    class _Refused:
        returncode = 1
        stdout = ""
        stderr = "gh: Bad credentials (HTTP 401)"

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: _Refused())

    with pytest.raises(setup.BoardSetupError, match=r"EXPIRED"):
        setup._gh_graphql("query {}", "ghp_dead")


def test_project_init_hands_the_board_the_app_token_when_no_static_one_exists(tmp_path,
                                                                              monkeypatch):
    """An ORG deployment on the App path holds no static token, and the App token CAN create
    org boards — `tracker_token()` alone sent it to the same dead end the pilot hit. The
    resolution is static-first (a personal board needs it), then the App mint."""
    from typer.testing import CliRunner

    from openfactory import cli as cli_module
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for name in ("OPENFACTORY_TRACKER_TOKEN", "OPENFACTORY_BOT_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    # THE MINT IS THE TRACKER AXIS'S ROW NOW, reached through the composition root: `cli.py` no
    # longer imports it at module scope, so the seam to drive is the one the row calls.
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    assert not hasattr(cli_module, "github_app_token_from_env"), (
        "the CLI imports the reference vendor's mint by name again")
    handed = {}

    def _fake_create_board(*, owner, title, token=None):
        handed["token"] = token
        return "7", "https://github.com/orgs/acme/projects/7"

    from openfactory.adapters.tracker import github_board_setup

    monkeypatch.setattr(github_board_setup, "create_board", _fake_create_board)
    result = CliRunner().invoke(app, ["project", "init", "demo"])

    assert result.exit_code == 0, result.output
    assert handed["token"] == "ghs_minted"


def test_a_missing_gh_cli_is_a_named_refusal_in_the_board_reader(monkeypatch):
    from openfactory.adapters.tracker import github_project as gp

    monkeypatch.setattr(gp.subprocess, "run", _raise_file_not_found)

    with pytest.raises(RuntimeError, match=r"`gh` CLI is not installed"):
        gp._gh_json(["api", "rate_limit"])

"""The GitHub App credential is answered in ONE place (#64, C-28 — the enabling half).

THE ASYMMETRY THE CARD IS ABOUT. The CHANNEL credential is per-project: `notifier_for_project`
reads the env var the registry names, so one deployment hosts N projects across N Slack
workspaces, and `contracts/project.py` documents that as deliberate. The FORGE credential is not —
`OPENFACTORY_GH_APP_ID` and `OPENFACTORY_GH_APP_INSTALLATION_ID` were read inline in four places, so one running
process authenticates against exactly one GitHub App installation, and `Project` has no field that
could say otherwise.

WHAT THIS FILE GUARDS, AND WHAT IT DOES NOT. The card offers two ways to close the asymmetry
(make the credential per-project, or refuse a registry that spans installations) and deliberately
decides neither — that is a product call about whether "one deployment, one org" is a commitment
or a dated limitation. Both options need the same precondition: exactly one place that answers
"which installation is this process?". That precondition is what these tests hold. They assert
nothing about which option is chosen.

`app_private_key` was already centralised in `credentials.py`, for a reason recorded there: two
entry points bridged a delivery-shape gap by writing a temp file at import time and everything
else silently had no credential. The other two members of the same triple were still inline.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The two variables this card is about. `OPENFACTORY_GH_APP_KEY` / `_CONTENT` are excluded: they are
#: already centralised and already guarded by `test_the_app_key_reaches_every_entry_point.py`.
CREDENTIAL_VARS = ("OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_INSTALLATION_ID")

#: The ONE module allowed to read them. Everything else asks it.
HOME = "openfactory/credentials.py"


def _production_modules() -> list[pathlib.Path]:
    return [p for p in (ROOT / "openfactory").rglob("*.py") if "__pycache__" not in str(p)]


def _env_reads(path: pathlib.Path) -> list[str]:
    """Every place this module resolves one of the credential variables FROM THE ENVIRONMENT.

    AST, not a substring scan, and that distinction is the whole guard: `cli.py` and `doctor.py`
    both name these variables in prose a human reads (an error message telling somebody what to
    set), and a text search cannot tell that apart from a read. Two shapes count as a read:

        os.environ.get("OPENFACTORY_GH_APP_ID")     the obvious one
        typer.Option(..., envvar="SDLC_...")  the one that hid — typer resolves it before any of
                                              our code runs, so it is a reader no per-project
                                              override could ever reach
    """
    reads: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func)
            if rendered in ("os.environ.get", "environ.get"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in CREDENTIAL_VARS:
                        reads.append(f"{path.relative_to(ROOT)}:{node.lineno} — {arg.value}")
            for kw in node.keywords:
                if kw.arg == "envvar" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value in CREDENTIAL_VARS:
                    reads.append(f"{path.relative_to(ROOT)}:{node.lineno} — envvar="
                                 f"{kw.value.value}")
        if isinstance(node, ast.Subscript) and ast.unparse(node).startswith("os.environ["):
            inner = node.slice
            if isinstance(inner, ast.Constant) and inner.value in CREDENTIAL_VARS:
                reads.append(f"{path.relative_to(ROOT)}:{node.lineno} — os.environ[…]")
    return reads


def test_exactly_one_module_reads_the_installation_credential():
    """The negative half. Four readers is four places to disagree about precedence, and four
    places a per-project override would have to be threaded through."""
    offenders = [
        line
        for path in _production_modules()
        if path.relative_to(ROOT).as_posix() != HOME
        for line in _env_reads(path)
    ]

    assert offenders == [], (
        f"these read the App installation credential directly instead of asking {HOME}:\n  "
        + "\n  ".join(offenders)
    )


def test_the_one_module_actually_reads_them():
    """The POSITIVE TWIN. "Nothing reads it" is satisfied just as well by NOTHING reading it
    anywhere — a credential resolved by no one is an outage, not a guard passing. This is the
    exact shape that let ADR-0037 D4 ship with `image=` missing from all four launch sites."""
    reads = _env_reads(ROOT / HOME)

    assert any("OPENFACTORY_GH_APP_ID" in r for r in reads), f"{HOME} does not read OPENFACTORY_GH_APP_ID"
    assert any("OPENFACTORY_GH_APP_INSTALLATION_ID" in r for r in reads), (
        f"{HOME} does not read OPENFACTORY_GH_APP_INSTALLATION_ID")


# ── the helpers answer, and the callers get the same answer they always did ─────────────────────

@pytest.mark.parametrize("helper,var,value", [
    ("app_id", "OPENFACTORY_GH_APP_ID", "12345"),
    ("app_installation_id", "OPENFACTORY_GH_APP_INSTALLATION_ID", "67890"),
])
def test_each_helper_reads_its_variable(helper, var, value, monkeypatch):
    import openfactory.credentials as creds

    monkeypatch.setenv(var, value)

    assert getattr(creds, helper)() == value


@pytest.mark.parametrize("helper,var", [
    ("app_id", "OPENFACTORY_GH_APP_ID"),
    ("app_installation_id", "OPENFACTORY_GH_APP_INSTALLATION_ID"),
])
def test_absent_is_None_not_empty_string(helper, var, monkeypatch):
    """`""` and `None` read the same in an `if`, and differently in a `dict.get` default or a
    join. The whole triple answers None so a caller's `if not (aid and key and inst)` means one
    thing."""
    import openfactory.credentials as creds

    monkeypatch.delenv(var, raising=False)

    assert getattr(creds, helper)() is None


@pytest.mark.parametrize("helper,var", [
    ("app_id", "OPENFACTORY_GH_APP_ID"),
    ("app_installation_id", "OPENFACTORY_GH_APP_INSTALLATION_ID"),
])
def test_an_empty_variable_is_also_None(helper, var, monkeypatch):
    """A variable set to the empty string is somebody who started typing, or a compose file with a
    blank default — not a request for the empty installation. Same reasoning `resolve_box_image`
    records for a blank image."""
    import openfactory.credentials as creds

    monkeypatch.setenv(var, "")

    assert getattr(creds, helper)() is None


def test_the_minting_path_still_works_end_to_end(monkeypatch):
    """REACHABILITY. The refactor is behaviour-preserving only if the real entry point still mints
    — a helper nothing calls is the defect this codebase keeps recording."""
    import openfactory.adapters.github_app as ga

    seen: dict = {}

    def _fake(*, app_id, private_key, installation_id):
        seen.update(app_id=app_id, installation_id=installation_id)
        return ("ghs_stub", "2026-01-01T00:00:00Z")

    monkeypatch.setattr(ga, "mint_installation_token", _fake)
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----\nx\n")

    from openfactory.factory import github_app_token_from_env

    assert github_app_token_from_env() == "ghs_stub"
    assert seen == {"app_id": "12345", "installation_id": "67890"}


def test_the_bot_token_command_still_resolves_from_the_environment(monkeypatch):
    """`sdlc bot-token` had `envvar=` on both flags. Dropping it moves the fallback into our own
    code — where a per-project override could one day reach — and this asserts the operator-facing
    behaviour did not change with it."""
    from typer.testing import CliRunner

    import openfactory.adapters.github_app as ga

    monkeypatch.setattr(ga, "mint_installation_token",
                        lambda **kw: (f"ghs_{kw['installation_id']}", "2026-01-01T00:00:00Z"))
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----\nx\n")

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["bot-token"])

    assert result.exit_code == 0, result.output
    assert "ghs_67890" in result.output


def test_the_smoke_test_says_what_it_is_WITHOUT_polluting_the_captured_token(monkeypatch):
    """The pilot operator, holding a printed `ghs_…`: *"isso que fizemos de gerar o token é
    para quê, se eu já tinha colocado tudo no .env.compose?"* Fair question — `--help` showed
    only `export OPENFACTORY_BOT_TOKEN=$(openfactory bot-token)`, so the command read as one
    that produces a fourth credential to paste somewhere. It is a TEST: the token expires in an
    hour and the factory mints its own per job.

    The explanation therefore goes to stderr and the token stays alone on stdout — otherwise
    the export form above would capture the prose too, which is the cure being worse."""
    from typer.testing import CliRunner

    import openfactory.adapters.github_app as ga

    monkeypatch.setattr(ga, "mint_installation_token",
                        lambda **kw: ("ghs_MINTED", "2026-01-01T00:00:00Z"))
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----\nx\n")

    from openfactory.cli import app

    # click 8.4 keeps the two streams apart on its own — `result.stdout` is what a `$(…)`
    # capture would receive, `result.stderr` what the human reads.
    result = CliRunner().invoke(app, ["bot-token"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "ghs_MINTED", (
        "stdout must carry the token and nothing else — `$(openfactory bot-token)` depends on it")
    assert "Nothing to save" in result.stderr
    assert "expires" in result.stderr


def test_an_explicit_flag_still_beats_the_environment(monkeypatch):
    """Most-specific-wins, the precedence this codebase holds everywhere else."""
    from typer.testing import CliRunner

    import openfactory.adapters.github_app as ga

    monkeypatch.setattr(ga, "mint_installation_token",
                        lambda **kw: (f"ghs_{kw['installation_id']}", "2026-01-01T00:00:00Z"))
    monkeypatch.setenv("OPENFACTORY_GH_APP_ID", "12345")
    monkeypatch.setenv("OPENFACTORY_GH_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("OPENFACTORY_GH_APP_KEY_CONTENT", "-----BEGIN RSA PRIVATE KEY-----\nx\n")

    from openfactory.cli import app

    result = CliRunner().invoke(app, ["bot-token", "--installation-id", "999"])

    assert result.exit_code == 0, result.output
    assert "ghs_999" in result.output


# ── the limit is now enforced where a human can act on it ───────────────────────────────────────
#
# The card offered two ways to close the asymmetry and the product owner chose: REFUSE a registry
# that spans GitHub organisations, and say so. One deployment per organisation was already the
# shape the platform is built for; this makes it enforced rather than discovered as a 404.

def _github(name: str, owner: str = "acme", **kw):
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name=name, repo_path=f"/tmp/{name}",
                   tracker=ProviderRef(kind="github", repo=f"{owner}/{name}"), **kw)


def test_a_second_project_in_another_org_is_refused_naming_both(tmp_path):
    """Refused at `add`, where a human is standing right there — not three layers away as a 404
    on a repository they can see in their browser."""
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_github("api", owner="acme"))

    with pytest.raises(ValueError) as exc:
        reg.add(_github("web", owner="othercorp"))

    said = str(exc.value)
    assert "acme" in said and "othercorp" in said, said
    assert "api" in said and "web" in said, "the message must name the projects, not just the orgs"


def test_a_second_project_in_the_SAME_org_is_accepted(tmp_path):
    """THE POSITIVE TWIN. A guard that refuses everything is indistinguishable from a guard that
    works, and N projects on one deployment is the whole multi-project story this platform tells."""
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_github("api", owner="acme"))
    reg.add(_github("web", owner="acme"))

    assert sorted(p.name for p in reg.list()) == ["api", "web"]


def test_a_board_owner_counts_as_an_org(tmp_path):
    """The board is read with the same installation token as the repository. A project whose repo
    is in one org and whose GitHub Project board is in another is the same failure."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_github("api", owner="acme"))

    with pytest.raises(ValueError):
        reg.add(Project(
            name="web", repo_path="/tmp/web",
            tracker=ProviderRef(kind="github", repo="acme/web",
                                options={"board_owner": "othercorp", "board_number": "1"})))


def test_a_non_github_tracker_contributes_no_org(tmp_path):
    """A Jira `repo` is a project key (`CONT`), not an `owner/name`. Reading it as an org would
    refuse a perfectly valid mixed-vendor registry — the thing ADR-0022's whole seam exists for."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_github("api", owner="acme"))
    reg.add(Project(name="legacy", repo_path="/tmp/legacy",
                    tracker=ProviderRef(kind="jira", repo="CONT")))

    assert sorted(p.name for p in reg.list()) == ["api", "legacy"]


def test_a_hand_edited_spanning_registry_WARNS_and_still_loads(tmp_path, caplog):
    """DELIBERATELY NOT A RAISE, and this is the one design choice worth arguing with.

    `add` has a human in front of it. `list` runs on the poller's every tick against a file the
    registry's own `_report_keys` describes as "invisible to every test and reviewer" because it
    is gitignored and baked into an image. Raising here would turn ONE stale line in an
    unreviewable file into a total outage for EVERY project — including the healthy ones — and it
    would surface as a retried activity error in a log nobody watches. That is a silent stall,
    which is strictly worse than the 404s it would be protecting against, and it contradicts the
    reasoning already written down for `extra="ignore"` two methods away."""
    import yaml

    from openfactory.registry import ProjectRegistry

    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump({"projects": {
        "api": {"name": "api", "repo_path": "/tmp/api",
                "tracker": {"kind": "github", "repo": "acme/api"}},
        "web": {"name": "web", "repo_path": "/tmp/web",
                "tracker": {"kind": "github", "repo": "othercorp/web"}},
    }}))

    with caplog.at_level("ERROR"):
        loaded = ProjectRegistry(path).list()

    assert sorted(p.name for p in loaded) == ["api", "web"], "a bad neighbour stopped every project"
    assert "OPENFACTORY_REGISTRY_SPANS_INSTALLATIONS" in caplog.text
    assert "acme" in caplog.text and "othercorp" in caplog.text


def test_a_single_org_registry_is_silent(tmp_path, caplog):
    """The other half of the warning: it must not cry on every healthy load, or it is noise
    somebody learns to filter — the same cost a false alarm has anywhere else here."""
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")
    reg.add(_github("api", owner="acme"))
    reg.add(_github("web", owner="acme"))

    with caplog.at_level("ERROR"):
        reg.list()

    assert "OPENFACTORY_REGISTRY_SPANS_INSTALLATIONS" not in caplog.text


def test_the_factory_board_may_live_elsewhere_and_only_warns(tmp_path, caplog):
    """ADR-0027 puts the factory's OWN impediments on the factory's OWN board, and the shipped
    `deploy/registry.yaml.example` points it at a fork of this platform. Refusing that would break
    a documented design to enforce an undocumented one."""
    from openfactory.contracts.project import FactoryBoard, Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    reg = ProjectRegistry(tmp_path / "r.yaml")

    with caplog.at_level("WARNING"):
        reg.add(Project(
            name="api", repo_path="/tmp/api",
            tracker=ProviderRef(kind="github", repo="acme/api"),
            factory_board=FactoryBoard(
                tracker=ProviderRef(kind="github", repo="AcmeCorp/openfactory"),
                supervisor="someone")))

    assert [p.name for p in reg.list()] == ["api"], "a factory-board pointer was refused"
    assert "factory_board" in caplog.text and "AcmeCorp" in caplog.text

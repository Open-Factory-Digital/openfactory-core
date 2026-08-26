"""`openfactory doctor` — every prerequisite says which one is missing (C-15).

The platform's headline invariant is *never a silent hang: every stall either self-heals or asks a
human with executable options*. It covers the RUNNING factory and stops at its door. Before the
first ticket there is no invariant at all: a board column named wrongly, an App without Projects
permission, a harness not on PATH — each produces the same symptom, which is nothing happening.

**Onboarding is not tedious because it has many steps. It is tedious when it fails without saying
why.** So the bar here is not "reports a problem"; it is that each distinct cause produces a
distinct, actionable line, and that a healthy setup says so.

One check is not a prerequisite but a CONTRADICTION, and it is the one an enterprise hits:
`merge_policy: auto` against a repository whose branch protection requires a human review. Both
settings are individually valid and together they mean the factory can never merge. Today that is
discovered by a timeout — the merge loop reads `blocked`, treats it as a pending check, waits, and
parks. Nobody is told the two policies disagree.
"""

from __future__ import annotations

import pytest

from openfactory.doctor import Finding, diagnose


def _findings(report) -> dict[str, Finding]:
    return {f.check: f for f in report.findings}


# ── the shape of an answer ──────────────────────────────────────────────────────────────────────

def test_a_report_names_every_check_it_ran(healthy):
    """A check that silently did not run is indistinguishable from one that passed."""
    names = {f.check for f in diagnose(healthy).findings}
    assert {"docker", "harness", "manifest", "quality_floor", "forge_access", "board_columns",
            "merge_policy"} <= names


def test_a_healthy_setup_is_ok(healthy):
    report = diagnose(healthy)
    assert report.ok, [f.message for f in report.findings if not f.ok]


def test_every_failing_check_says_what_to_do(broken_everything):
    """A finding with no remedy is a symptom, and the person reading it is exactly the person who
    does not yet know the system."""
    for f in diagnose(broken_everything).findings:
        if not f.ok:
            assert f.remedy, f"{f.check} reports a problem without saying how to fix it"


def test_the_report_is_not_ok_when_anything_is(broken_everything):
    assert not diagnose(broken_everything).ok


# ── each cause produces a DISTINCT line ─────────────────────────────────────────────────────────

def test_docker_not_running_is_named(no_docker):
    f = _findings(diagnose(no_docker))["docker"]
    assert not f.ok and "docker" in f.message.lower()


def test_a_harness_not_on_path_is_named(no_harness):
    f = _findings(diagnose(no_harness))["harness"]
    assert not f.ok
    assert "claude" in f.message.lower() or "harness" in f.message.lower()


def test_a_missing_manifest_is_named(no_manifest):
    f = _findings(diagnose(no_manifest))["manifest"]
    assert not f.ok and "project.yaml" in f.message


def test_a_repository_on_the_retired_name_is_told_to_RENAME_and_nothing_else(retired_manifest):
    """Two doors, one repository. The missing-manifest remedy sends the reader to `openfactory
    onboard`, which reads a repository and proposes a manifest for it — and for a repository that
    HAS one, under the directory's former name, that is a second manifest beside the first
    (review, 2026-08-25). The finding carries the loader's sentence; its remedy and next step
    name the rename and no verb that infers or writes."""
    f = _findings(diagnose(retired_manifest))["manifest"]

    assert not f.ok
    assert ".sdlc/project.yaml" in f.message and ".openfactory/" in f.message, f.message
    for text in (f.remedy, f.next_step):
        assert "rename" in text.lower() and ".openfactory/" in text, text
        for verb in ("onboard", "env apply", "project init"):
            assert verb not in text, (
                f"the doctor routes a repository that has a manifest into writing another: {text}")


def test_a_manifest_that_is_MISSING_is_still_sent_to_onboarding(no_manifest):
    """The twin: absence and the former name are different facts and get different remedies —
    nothing there is the case onboarding exists for."""
    f = _findings(diagnose(no_manifest))["manifest"]

    assert not f.ok
    assert "openfactory onboard" in f.remedy and "openfactory onboard" in f.next_step, (
        f.remedy, f.next_step)


def test_an_invalid_manifest_is_named_with_its_reason(bad_manifest):
    """`load_manifest` already reports the file and the pydantic error; doctor must not flatten
    that into 'manifest problem'."""
    f = _findings(diagnose(bad_manifest))["manifest"]
    assert not f.ok and "version" in f.message.lower()


def test_no_forge_access_is_named(no_forge_access):
    f = _findings(diagnose(no_forge_access))["forge_access"]
    assert not f.ok


def test_a_board_missing_the_pickup_column_is_named(no_todo_column):
    """The specific silent stall: the factory picks up from TO-DO. Without that column nothing
    ever moves and nothing anywhere says why."""
    f = _findings(diagnose(no_todo_column))["board_columns"]
    assert not f.ok and "TO-DO" in f.message


def test_a_project_with_no_board_configured_is_not_an_error(healthy_no_board):
    """A board is optional — `sdlc run` names the ticket itself. Reporting its absence as a
    failure would send someone to fix a setup that is already correct."""
    f = _findings(diagnose(healthy_no_board))["board_columns"]
    assert f.ok


# ── the contradiction check ─────────────────────────────────────────────────────────────────────

def test_auto_merge_against_required_reviews_is_reported(auto_merge_but_protected):
    """Two individually valid settings that together mean the factory can never merge. Today this
    surfaces as a job that waits and parks; here it is a line at setup."""
    f = _findings(diagnose(auto_merge_but_protected))["merge_policy"]
    assert not f.ok
    assert "auto" in f.message and "review" in f.message.lower()
    assert "merge_policy: human" in f.remedy


def test_human_merge_against_required_reviews_is_fine(human_merge_but_protected):
    """The same repository with `merge_policy: human` is the CORRECT configuration — the bot opens
    the PR and a person merges it. Flagging it would train people to ignore doctor."""
    assert _findings(diagnose(human_merge_but_protected))["merge_policy"].ok


def test_auto_merge_without_protection_is_fine(healthy):
    assert _findings(diagnose(healthy))["merge_policy"].ok


# ── it never becomes the thing it diagnoses ─────────────────────────────────────────────────────

def test_a_check_that_raises_is_reported_not_propagated(exploding_probe):
    """Doctor is what someone runs when nothing works. It must never be the ninth thing that is
    broken — a traceback here tells them nothing about their setup."""
    report = diagnose(exploding_probe)
    f = _findings(report)["forge_access"]
    assert not f.ok and "could not" in f.message.lower()


def test_it_reports_every_problem_rather_than_the_first(broken_everything):
    """Stopping at the first failure turns one session into six."""
    failing = [f for f in diagnose(broken_everything).findings if not f.ok]
    assert len(failing) >= 4


# ── the CLI surface ─────────────────────────────────────────────────────────────────────────────

def test_the_cli_exits_nonzero_when_something_is_wrong(monkeypatch, broken_everything):
    from typer.testing import CliRunner

    from openfactory import cli, doctor

    monkeypatch.setattr(doctor, "diagnose", lambda *_a, **_kw: diagnose(broken_everything))
    monkeypatch.setattr(doctor, "probes_for", lambda _p: broken_everything)
    monkeypatch.setattr(cli.ProjectRegistry, "get", lambda self, n: object())
    monkeypatch.setattr(cli, "_load_environment", lambda: None)
    result = CliRunner().invoke(cli.app, ["doctor", "demo"])
    assert result.exit_code == 1
    assert "docker" in result.output.lower()


def test_the_cli_exits_zero_when_healthy(monkeypatch, healthy):
    from typer.testing import CliRunner

    from openfactory import cli, doctor

    monkeypatch.setattr(doctor, "diagnose", lambda *_a, **_kw: diagnose(healthy))
    monkeypatch.setattr(doctor, "probes_for", lambda _p: healthy)
    monkeypatch.setattr(cli.ProjectRegistry, "get", lambda self, n: object())
    monkeypatch.setattr(cli, "_load_environment", lambda: None)
    result = CliRunner().invoke(cli.app, ["doctor", "demo"])
    assert result.exit_code == 0


# ── fixtures: a probe set describing one machine ────────────────────────────────────────────────
#
# `diagnose` takes its probes as an argument so every branch is reachable without Docker, a
# network, or a GitHub App. A doctor that could only be tested on a healthy machine would be a
# doctor nobody could prove reports illness.

from openfactory.doctor import Probes  # noqa: E402


def _probes(**over) -> Probes:
    base = dict(
        docker_running=lambda: (True, ""),
        harness_on_path=lambda kind: True,
        manifest=lambda: _MANIFEST,
        forge_reachable=lambda: (True, ""),
        board_columns=lambda: ["Backlog", "TO-DO", "In progress", "Needs Action", "In review",
                               "Done"],
        pickup_column=lambda: "TO-DO",
        requires_review=lambda: False,
        floor_enforced=lambda: False,
        harness_kind=lambda: "claude_code",
        product_link=lambda: _no_product(),
    )
    base.update(over)
    return Probes(**base)


def _no_product():
    from openfactory.product.config import ProductLink

    return ProductLink(active=False, kind="off", reason="no product module")


def _manifest_obj(**over):
    """A REAL `Manifest` that satisfies the floor, unless a test takes something away.

    This was a two-attribute stub carrying `merge_policy` and nothing else. It could not answer
    `declared_keys()` and could not carry a `validate:` block, so the manifest and floor checks
    would have been proven against an object no loader can produce — the same trap this suite's
    sibling names about the board double that answered "TO-DO" while listing "A Fazer". A double
    that cannot exist proves nothing about the code that meets the real thing.
    """
    from openfactory.contracts import Manifest

    base = dict(
        version=1,
        base_branch="main",
        validate={"test": "pytest -q",
                  "security": {"command": "semgrep --config=auto .", "advisory": True}},
    )
    base.update(over)
    return Manifest(**base)


_MANIFEST = _manifest_obj()


def _auto():
    return _manifest_obj(merge_policy="auto")


@pytest.fixture
def healthy():
    return _probes(manifest=lambda: _auto())


@pytest.fixture
def healthy_no_board():
    return _probes(board_columns=lambda: None)


@pytest.fixture
def no_docker():
    return _probes(docker_running=lambda: (False, ""))


@pytest.fixture
def no_harness():
    return _probes(harness_on_path=lambda kind: False)


@pytest.fixture
def no_manifest():
    def _raise():
        raise FileNotFoundError("no manifest at /repo/.openfactory/project.yaml")

    return _probes(manifest=_raise)


@pytest.fixture
def retired_manifest(tmp_path):
    """The REAL loader's refusal for a repository still on the directory's former name — the
    probe `probes_for` wires is `lambda: load_manifest(project)`, and this is that call."""
    from openfactory import namespace
    from openfactory.contracts.project import Project
    from openfactory.loader import load_manifest

    (tmp_path / namespace.RETIRED_DIR).mkdir()
    (tmp_path / namespace.RETIRED_DIR / "project.yaml").write_text("version: 1\n")
    project = Project(name="acme", repo_path=str(tmp_path))
    return _probes(manifest=lambda: load_manifest(project, repo_root=tmp_path))


@pytest.fixture
def bad_manifest():
    def _raise():
        raise ValueError("/repo/.openfactory/project.yaml is invalid: manifest version 42 …")

    return _probes(manifest=_raise)


@pytest.fixture
def no_forge_access():
    return _probes(forge_reachable=lambda: (False, "Resource not accessible by integration"))


@pytest.fixture
def no_todo_column():
    return _probes(board_columns=lambda: ["Backlog", "Doing", "Done"])


@pytest.fixture
def auto_merge_but_protected():
    return _probes(manifest=lambda: _auto(), requires_review=lambda: True)


@pytest.fixture
def human_merge_but_protected():
    return _probes(requires_review=lambda: True)


@pytest.fixture
def exploding_probe():
    def _boom():
        raise OSError("gh: connection refused")

    return _probes(forge_reachable=_boom)


@pytest.fixture
def broken_everything():
    def _raise():
        raise FileNotFoundError("no manifest at /repo/.openfactory/project.yaml")

    return _probes(
        docker_running=lambda: (False, ""),
        harness_on_path=lambda kind: False,
        manifest=_raise,
        forge_reachable=lambda: (False, "401"),
        board_columns=lambda: ["Backlog"],
    )


# ── the pre-pilot review's honesty pair (2026-08-09) ────────────────────────────────────────────

def test_no_agent_credential_is_a_named_FAIL_not_a_green_light():
    """A fresh install with zero credentials used to read "OK — can run a ticket" and fail at the
    first PAID job. Presence only, deliberately — verifying it works costs a model call, and that
    spend belongs to `box prove`."""
    from openfactory.doctor import diagnose

    report = diagnose(_probes(agent_credential=lambda: (False, "no agent credential")))
    finding = next(f for f in report.findings if f.check == "agent_credential")

    assert not finding.ok and not report.ok
    assert "CLAUDE_CODE_OAUTH_TOKEN" in finding.remedy and "ANTHROPIC_API_KEY" in finding.remedy


def test_a_present_agent_credential_says_what_still_is_not_proven():
    from openfactory.doctor import diagnose

    report = diagnose(_probes(agent_credential=lambda: (True, "")))
    finding = next(f for f in report.findings if f.check == "agent_credential")

    assert finding.ok and "box prove" in finding.message


def test_an_older_probes_without_the_agent_check_skips_it_instead_of_inventing():
    from openfactory.doctor import diagnose

    report = diagnose(_probes())  # no agent_credential → default None
    assert all(f.check != "agent_credential" for f in report.findings)


def test_no_forge_credential_is_ITS_OWN_refusal_not_a_permissions_hint():
    """The old failure message assumed a credential existed and was refused; with none at all the
    remedy ("grant the App access") sent the stranger to fix a grant they had never made."""
    from openfactory.doctor import diagnose

    report = diagnose(_probes(forge_reachable=lambda: (False, "no forge credential is configured")))
    finding = next(f for f in report.findings if f.check == "forge_access")

    assert not finding.ok
    assert "OPENFACTORY_BOT_TOKEN" in finding.remedy and "OPENFACTORY_GH_APP_ID" in finding.remedy


def test_the_REAL_probe_reports_absence_before_reachability(tmp_path, monkeypatch):
    """MR6's lesson: the builder tests above fake `forge_reachable`, so the presence check inside
    `probes_for`'s closure was unproven — a mutation deleting it stayed green. This one goes
    through the real closure with every credential scrubbed."""
    for name in ("OPENFACTORY_FORGE_TOKEN", "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_TRACKER_TOKEN",
                 "OPENFACTORY_GH_APP_ID", "OPENFACTORY_GH_APP_KEY",
                 "OPENFACTORY_GH_APP_KEY_CONTENT", "OPENFACTORY_GH_APP_INSTALLATION_ID"):
        monkeypatch.delenv(name, raising=False)
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.doctor import probes_for

    project = Project(name="bare", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="o/bare"),
                      forge=ProviderRef(kind="github", repo="o/bare"))

    reachable, detail = probes_for(project).forge_reachable()

    assert reachable is False and "no forge credential" in detail, (
        "with nothing configured the probe must refuse by PRESENCE — reachability against a "
        "public endpoint reads 404 as allowed-to-ask and lied green")

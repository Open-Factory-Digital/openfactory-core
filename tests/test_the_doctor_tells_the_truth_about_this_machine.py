"""The doctor tells the truth about the machine it is on (ADR-0049 slice 4d).

MEASURED FIRST, on a one-machine deployment with everything done right — a `git init` repository
with a manifest, a local board with its `TO-DO` column, `OPENFACTORY_SANDBOX=worktree`:

    XX  agent_credential  no agent credential — the coding agent cannot authenticate, so no job
                          can run
    ok  forge_access      the forge is reachable with the configured token
    ok  docker            docker is running

Three sentences about a vendor that is not there. The **credential** one was the verdict: it is
the only red on a correct install, and its remedy sends a person whose harness works to run
`claude setup-token` and paste a token nothing will read — the harness signs in with the login on
that machine, which is what `local` means. `forge_access` claimed a configured token where there
is none and no request was made. And `docker info` was run for a box that runs no image here: on
a machine without Docker, *"no job can run"* over jobs that run fine.

WHAT IS PROVEN HERE:

  · the box is asked what it BOUNDS and what it RUNS (`installed_box_traits`), never what it is
    called — the rule ADR-0037 D4 exists for;
  · a box that isolates nothing needs no token variable, and the note still names the token as
    what an isolating box needs;
  · a box that does not run the project's image on this machine is not asked about Docker at all;
  · a row whose vendor needs no credential says so, in the probe's own words;
  · a box this build has never heard of changes nothing.
"""

from __future__ import annotations

import pytest

from openfactory import doctor
from tests.pinned_probes import a_fully_pinned_probe_set

NO_CREDENTIAL = (False, "no agent credential in this environment")


def _finding(report: doctor.Report, check: str) -> doctor.Finding:
    return next(f for f in report.findings if f.check == check)


def _exploding_docker():
    raise AssertionError("`docker info` was run for a box that containerises nothing")


# ── the credential a box that isolates nothing already has ──────────────────────────────────────

def test_the_LOGIN_is_the_credential_where_the_box_isolates_nothing():
    probes = a_fully_pinned_probe_set(sandbox=lambda: "worktree",
                                      agent_credential=lambda: NO_CREDENTIAL)

    got = _finding(doctor.diagnose(probes), "agent_credential")

    assert got.ok
    assert "login on this machine" in got.message
    # THE OTHER HALF STILL SAID. A pass is not always the end of the sentence: an expired login
    # reads exactly like this until `box prove` calls the model.
    assert "box prove" in got.note and "ISOLATES" in got.note


@pytest.mark.parametrize("box", ["container", "fargate"])
def test_a_box_that_isolates_still_demands_the_token(box):
    """It cannot see this machine's login — that is what isolating means."""
    probes = a_fully_pinned_probe_set(sandbox=lambda: box,
                                      agent_credential=lambda: NO_CREDENTIAL)

    got = _finding(doctor.diagnose(probes), "agent_credential")

    assert not got.ok
    assert "CLAUDE_CODE_OAUTH_TOKEN" in got.remedy


def test_a_present_token_is_still_a_present_token_on_every_box():
    probes = a_fully_pinned_probe_set(sandbox=lambda: "worktree",
                                      agent_credential=lambda: (True, "a token is configured"))

    assert _finding(doctor.diagnose(probes), "agent_credential").ok


# ── the container runtime only a box that runs the image here needs ─────────────────────────────

def test_a_box_that_runs_no_image_here_is_not_asked_about_docker():
    probes = a_fully_pinned_probe_set(sandbox=lambda: "worktree",
                                      docker_running=_exploding_docker)

    got = _finding(doctor.diagnose(probes), "docker")

    assert got.ok and "worktree" in got.message


def test_a_cloud_box_is_not_asked_either_its_image_is_baked():
    probes = a_fully_pinned_probe_set(sandbox=lambda: "fargate",
                                      docker_running=_exploding_docker)

    assert _finding(doctor.diagnose(probes), "docker").ok


def test_the_box_that_runs_the_image_here_is_still_asked():
    probes = a_fully_pinned_probe_set(sandbox=lambda: "container",
                                      docker_running=lambda: (False, ""))

    got = _finding(doctor.diagnose(probes), "docker")

    assert not got.ok and "no job can run" in got.message


# ── a row whose vendor needs no credential ──────────────────────────────────────────────────────

def test_a_forge_that_needs_no_credential_does_not_claim_a_token():
    probes = a_fully_pinned_probe_set(
        forge_reachable=lambda: (True, "the local forge needs no credential — nothing was asked "
                                       "of a vendor and nothing has to be configured"))

    got = _finding(doctor.diagnose(probes), "forge_access")

    assert got.ok and "needs no credential" in got.message
    assert "configured token" not in got.message


def test_a_forge_that_WAS_reached_still_says_so():
    """The probe answers `(True, "")` when it really made the request — the sentence it had."""
    probes = a_fully_pinned_probe_set(forge_reachable=lambda: (True, ""))

    assert "the forge is reachable with the configured token" == _finding(
        doctor.diagnose(probes), "forge_access").message


# ── a box nobody here has heard of ──────────────────────────────────────────────────────────────

def test_a_box_this_build_does_not_know_changes_nothing():
    """An add-on's box that is not installed where doctor runs, or a typo. "Cannot say" must read
    as the world before this probe existed — never as an exemption."""
    probes = a_fully_pinned_probe_set(sandbox=lambda: "nosuchbox",
                                      agent_credential=lambda: NO_CREDENTIAL,
                                      docker_running=lambda: (False, ""))
    report = doctor.diagnose(probes)

    assert not _finding(report, "agent_credential").ok
    assert not _finding(report, "docker").ok


def test_an_older_probe_set_that_names_no_box_changes_nothing():
    probes = a_fully_pinned_probe_set(sandbox=None,
                                      agent_credential=lambda: NO_CREDENTIAL,
                                      docker_running=lambda: (False, ""))
    report = doctor.diagnose(probes)

    assert not _finding(report, "agent_credential").ok
    assert not _finding(report, "docker").ok


# ── the whole verdict, which is what this slice is for ──────────────────────────────────────────

def test_a_ONE_MACHINE_deployment_reports_READY():
    """The three answers a correct one-machine install gives, together: no token variable, no
    Docker, a forge that needs no credential. Before this slice the verdict was NOT ready."""
    report = doctor.diagnose(a_fully_pinned_probe_set(
        sandbox=lambda: "worktree",
        agent_credential=lambda: NO_CREDENTIAL,
        docker_running=_exploding_docker,
        forge_reachable=lambda: (True, "the local forge needs no credential — nothing was asked "
                                       "of a vendor and nothing has to be configured")))

    assert report.ok, [f"{f.check}: {f.message}" for f in report.findings if not f.ok]


# ── the wiring: the same reader the poller uses ─────────────────────────────────────────────────

def test_the_real_probes_read_the_box_the_POLLER_reads(tmp_path, monkeypatch):
    """Not a synthetic machine: `probes_for` must ask `default_sandbox()`, the one function the
    gate and the runner ask. A second way of deciding which box this is would be a second answer.
    """
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "worktree")
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="mine", repo_path=str(tmp_path),
                         tracker=ProviderRef(kind="local", repo="mine")))
    probes = doctor.probes_for(registry.get("mine"))

    assert probes.sandbox is not None and probes.sandbox() == "worktree"
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "container")
    assert probes.sandbox() == "container", "read at ASK time, never cached at construction"


def test_the_real_probe_says_a_local_forge_needs_no_credential(tmp_path, monkeypatch):
    """The other half of the wiring — the sentence the finding renders comes from the probe that
    read the ROW (D1's `vendor_needs_credential`), not from a literal in the finding."""
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    for variable in ("OPENFACTORY_BOT_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    registry = ProjectRegistry()
    registry.add(Project(name="mine", repo_path=str(tmp_path),
                         forge=ProviderRef(kind="local", repo="mine"),
                         tracker=ProviderRef(kind="local", repo="mine")))
    reachable, detail = doctor.probes_for(registry.get("mine")).forge_reachable()

    assert reachable and "needs no credential" in detail

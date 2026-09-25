"""A deployment says where its previews run, and every door that can see a missing piece says which
(#265 slice 2; ADR-0050 D7, D11; the design's §5.2 and §7).

- THE COMPOSE STACK runs previews on its own daemon: the worker carries the pinned compose plugin
  the CLI image carries, names the runtime, the reach and the panel's container, and the panel has
  that name.
- `init` RENDERS IT PER KIND and generates the preview key like the panel's token: compose runs
  previews, one machine opts in with four commented lines, a hosted worker runs none.
- `doctor`, inside the worker, says what the runtime lacks, refuses a preview domain that is
  same-site with a plain-http panel, names a `required` project on a `none` runtime, slug twins
  and registry names the worker does not hold — and says nothing at all where previews cannot
  matter. `preflight`, on the host, says what `.env.compose`'s preview rows owe this machine.
- `openfactory preview prove` refuses where no runtime can run a proof, and `preview login` keeps
  the password off the argument list.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

import pytest
import yaml
from typer.testing import CliRunner

from openfactory import doctor, preflight, preview
from openfactory.onboarding.deployment import Answers, Probes, render
from tests.pinned_probes import a_fully_pinned_probe_set

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def _instructions(dockerfile: str) -> str:
    return "\n".join(ln for ln in (ROOT / "docker" / dockerfile).read_text().splitlines()
                     if not ln.lstrip().startswith("#"))


# ── the compose stack ────────────────────────────────────────────────────────────────────────────


def test_the_worker_carries_the_compose_plugin_the_cli_image_pins():
    worker, cli = _instructions("worker.Dockerfile"), _instructions("cli.Dockerfile")
    pin = re.search(r"FROM (docker/compose-bin:\S+) AS compose-plugin", cli).group(1)

    assert f"FROM {pin} AS compose-plugin" in worker, (
        "the worker's compose plugin is not the one the fixtures were recorded with")
    assert ("COPY --from=compose-plugin /docker-compose "
            "/usr/local/lib/docker/cli-plugins/docker-compose") in worker


def test_the_stack_names_the_runtime_and_the_panel_is_the_container_it_names():
    worker = COMPOSE["services"]["worker"]["environment"]
    panel = COMPOSE["services"]["panel"]

    def default(expr: str) -> str:
        return re.fullmatch(r"\$\{[A-Z_]+:-([^}]*)\}", expr).group(1)

    assert default(worker["OPENFACTORY_PREVIEW_RUNTIME"]) == "compose"
    assert default(worker["OPENFACTORY_PREVIEW_REACH"]) == "network"
    assert default(worker["OPENFACTORY_PANEL_CONTAINER"]) == panel["container_name"] == \
        "openfactory-panel"
    assert default(worker["OPENFACTORY_PREVIEW_DOCKER_CONFIG"]).startswith("/var/lib/openfactory/")
    assert default(worker["OPENFACTORY_PREVIEW_DOMAIN"]) == default(
        panel["environment"]["OPENFACTORY_PREVIEW_DOMAIN"]), (
        "the worker writes preview addresses under a domain the panel does not serve")
    assert "openfactory-preview" not in (COMPOSE.get("networks") or {}), (
        "a network shared by every preview is back")


# ── init, per kind ───────────────────────────────────────────────────────────────────────────────


def _rows(text: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M))


def test_the_compose_stack_renders_a_runtime_and_a_generated_key():
    out = render(Answers(runtime="compose", forge="github", tracker="github"),
                 Probes(secret=lambda: "K3Y"))
    rows = _rows(out.text)

    assert rows["OPENFACTORY_PREVIEW_SECRET"] == "K3Y"
    assert "OPENFACTORY_PREVIEW_SECRET" in out.obtained
    assert (rows["OPENFACTORY_PREVIEW_RUNTIME"], rows["OPENFACTORY_PREVIEW_REACH"],
            rows["OPENFACTORY_PANEL_CONTAINER"]) == ("compose", "network", "openfactory-panel")
    assert rows["OPENFACTORY_PREVIEW_DOCKER_CONFIG"] == "/var/lib/openfactory/docker"


def test_one_machine_runs_none_and_writes_the_opt_in_commented():
    out = render(Answers(), Probes(secret=lambda: "K3Y"))
    rows = _rows(out.text)

    assert rows["OPENFACTORY_PREVIEW_RUNTIME"] == "none"
    assert rows["OPENFACTORY_PREVIEW_SECRET"] == "K3Y", "the key was left for somebody to fill"
    for line in ("# OPENFACTORY_PREVIEW_RUNTIME=compose", "# OPENFACTORY_PREVIEW_REACH=loopback",
                 "# OPENFACTORY_PREVIEW_PORTS=42000-42999",
                 "# OPENFACTORY_PREVIEW_DOMAIN=preview.localhost"):
        assert line in out.text
    assert len(out.remaining) == 1, "a preview added a to-do to the one-machine install"


def test_a_hosted_worker_runs_none_and_says_how_one_is_added():
    out = render(Answers(runtime="fargate", forge="github", tracker="github"))
    assert _rows(out.text)["OPENFACTORY_PREVIEW_RUNTIME"] == "none"
    assert "`preview.<kind>`" in out.text and "holds no Docker daemon" in out.text


# ── the domain rule ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("domain, panel, refused", [
    ("preview.acme.com", "http://panel.acme.com:8787", True),
    ("previews.acme.co.uk", "http://factory.acme.co.uk", True),
    ("preview.acme.com", "https://panel.acme.com", False),        # `__Host-` over TLS
    ("preview.acme-previews.com", "http://panel.acme.com", False),
    ("preview.localhost", "http://localhost:8787", False),
    ("preview.acme.com", "http://localhost:8787", False),
    ("preview.acme.com", "http://10.0.0.4:8787", False),
    ("", "http://panel.acme.com", False),
    ("preview.acme.co.uk", "http://panel.other.co.uk", False),
])
def test_a_preview_domain_same_site_with_a_plain_http_panel_is_refused(domain, panel, refused):
    said = preview.domain_refusal(domain, panel)
    assert bool(said) is refused, said
    if refused:
        assert "same-site with the panel" in said and "https" in said


# ── doctor, inside the worker ────────────────────────────────────────────────────────────────────


def _report(state):
    return doctor.diagnose(a_fully_pinned_probe_set(preview=lambda: state))


def _finding(report, check):
    return next((f for f in report.findings if f.check == check), None)


def test_a_ready_runtime_is_one_ok_line_and_nothing_else():
    report = _report(doctor.PreviewState(kind="compose"))
    assert _finding(report, "preview").ok
    assert [f.check for f in report.findings if f.check.startswith("preview")] == ["preview"]


def test_where_previews_cannot_matter_doctor_says_nothing_about_them():
    report = _report(None)
    assert not [f for f in report.findings if f.check.startswith("preview")]


def test_what_the_runtime_lacks_is_each_said():
    report = _report(doctor.PreviewState(kind="compose", prerequisites=[
        "OPENFACTORY_PANEL_CONTAINER is not set", "the compose plugin is not usable"]))
    f = _finding(report, "preview")
    assert not f.ok and "OPENFACTORY_PANEL_CONTAINER is not set" in f.message
    assert "the compose plugin is not usable" in f.message and "doctor" in f.remedy


def test_a_required_project_on_a_none_runtime_is_refused():
    report = _report(doctor.PreviewState(kind="none", prerequisites=["…none…"], required=True))
    f = _finding(report, "preview")
    assert not f.ok and "waits for a person who can never look" in f.message
    assert "--no-required" in f.remedy and "OPENFACTORY_PREVIEW_RUNTIME=compose" in f.remedy
    assert _finding(_report(doctor.PreviewState(kind="none")), "preview").ok


def test_the_domain_twins_and_missing_names_are_each_a_row():
    report = _report(doctor.PreviewState(
        kind="compose", domain_refusal="the preview domain `x` shares …",
        slug_twins=["Acme"], missing_env=["ACME_PV_DATABASE_URL"], legacy_network=True))

    assert not _finding(report, "preview_domain").ok
    names = _finding(report, "preview_names")
    assert not names.ok and "`Acme`" in names.message
    env = _finding(report, "preview_env")
    assert not env.ok and "ACME_PV_DATABASE_URL" in env.message
    assert "`.env.compose`" in env.remedy and "docker compose up -d worker" in env.remedy
    legacy = _finding(report, "preview_network")
    assert legacy.ok and "`docker network rm openfactory-preview`" in legacy.message


def test_the_live_probe_asks_the_row_and_the_registry(monkeypatch, tmp_path):
    from openfactory.contracts.project import PreviewPolicy, Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.delenv("OPENFACTORY_PREVIEW_RUNTIME", raising=False)
    monkeypatch.setenv("OPENFACTORY_PANEL_URL", "http://panel.acme.com:8787")
    monkeypatch.setenv("OPENFACTORY_PREVIEW_DOMAIN", "preview.acme.com")
    monkeypatch.delenv("ACME_PV_DATABASE_URL", raising=False)
    plain = Project(name="plain", repo_path=str(tmp_path))
    acme = Project(name="acme", repo_path=str(tmp_path), preview=PreviewPolicy(
        required=True, env={"api": {"DATABASE_URL": "ACME_PV_DATABASE_URL"}}))
    ProjectRegistry().add(acme)

    assert doctor.probes_for(plain).preview() is None, "a project that never asked was told"
    state = doctor.probes_for(acme).preview()

    assert state.kind == "none" and state.required
    assert state.missing_env == ["ACME_PV_DATABASE_URL"]
    assert "shares `acme.com`" in state.domain_refusal
    assert state.prerequisites and "OPENFACTORY_PREVIEW_RUNTIME=none" in state.prerequisites[0]


def test_the_green_baseline_names_a_ready_preview_runtime():
    fields = {f.name for f in dataclasses.fields(doctor.Probes)}
    assert "preview" in fields
    assert _finding(doctor.diagnose(a_fully_pinned_probe_set()), "preview").ok


# ── preflight, on the host ───────────────────────────────────────────────────────────────────────


def _preflight(rows, compose=(True, "2.32.4")):
    from tests.test_preflight_names_a_remedy_for_every_thing_it_refuses import _probes

    report = preflight.check(_probes(preview_rows=lambda: rows, compose=lambda: compose))
    return next(f for f in report.findings if f.check == "preview")


def test_preflight_says_previews_are_off_when_nothing_names_a_runtime():
    assert _preflight({}).ok and "previews are off" in _preflight({}).message


def test_preflight_needs_the_plugin_a_compose_runtime_runs_through():
    f = _preflight({"OPENFACTORY_PREVIEW_RUNTIME": "compose"}, compose=(False, "not found"))
    assert not f.ok and "compose plugin" in f.message and "OPENFACTORY_PREVIEW_RUNTIME" in f.remedy


def test_preflight_refuses_a_loopback_reach_with_no_ports():
    assert not _preflight({"OPENFACTORY_PREVIEW_RUNTIME": "compose",
                           "OPENFACTORY_PREVIEW_REACH": "loopback"}).ok
    assert _preflight({"OPENFACTORY_PREVIEW_RUNTIME": "compose",
                       "OPENFACTORY_PREVIEW_REACH": "loopback",
                       "OPENFACTORY_PREVIEW_PORTS": "42000-42999"}).ok


# ── the two doors ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def registered(monkeypatch, tmp_path):
    from openfactory.contracts.project import Project
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    ProjectRegistry().add(Project(name="acme", repo_path=str(tmp_path)))
    return tmp_path


def test_prove_is_refused_where_the_deployment_names_no_runtime(registered, monkeypatch):
    from openfactory.adapters.preview.none import REFUSAL
    from openfactory.cli import app

    monkeypatch.delenv("OPENFACTORY_PREVIEW_RUNTIME", raising=False)
    result = CliRunner().invoke(app, ["preview", "prove", "acme"])

    assert result.exit_code == 2, result.output
    assert REFUSAL in result.output.replace("\n", " ") or "names no preview runtime" in \
        result.output


def test_prove_says_what_came_up_and_what_did_not(registered, monkeypatch):
    from openfactory.adapters.preview import compose
    from openfactory.cli import app
    from openfactory.preview.plan import PreviewUp

    monkeypatch.setenv("OPENFACTORY_PREVIEW_RUNTIME", "compose")
    monkeypatch.setattr(compose.ComposeRuntime, "prerequisites", lambda self: [])
    monkeypatch.setattr(compose, "prove_project", lambda project, runtime: PreviewUp(
        ok=True, services={"web": 3000, "api": 8000}, health={"web": "started", "api": "healthy"},
        log_dir="/logs/preview--acme--0"))

    ok = CliRunner().invoke(app, ["preview", "prove", "acme"])
    assert ok.exit_code == 0, ok.output
    assert "api: healthy" in ok.output and "web: started, not health-checked" in ok.output

    monkeypatch.setattr(compose, "prove_project", lambda project, runtime: PreviewUp(
        ok=False, why="`migrate` exited with code 3", log_dir="/logs/preview--acme--0"))
    failed = CliRunner().invoke(app, ["preview", "prove", "acme"])
    assert failed.exit_code == 1 and "`migrate` exited with code 3" in failed.output


def test_login_reads_the_password_from_stdin_and_never_echoes_it(monkeypatch):
    from openfactory.adapters.preview import compose
    from openfactory.adapters.preview.compose import Ran
    from openfactory.cli import app

    seen = {}
    monkeypatch.setattr(compose, "login", lambda registry, **kw: seen.update(
        registry=registry, **kw) or Ran(0, "Login Succeeded", ""))

    result = CliRunner().invoke(app, ["preview", "login", "ghcr.io", "-u", "bot",
                                      "--password-stdin"], input="t0ken-v4lue\n")

    assert result.exit_code == 0, result.output
    assert seen == {"registry": "ghcr.io", "username": "bot", "password": "t0ken-v4lue"}
    assert "t0ken-v4lue" not in result.output

"""`docker compose up` describes a factory that can actually run (C-13).

The compose file is the OSS distribution AND the development loop — the same artefact, which is
why it comes early rather than last. It is also the file nobody runs in CI, so every claim in it is
a claim nothing checks. These are the checks.

They deliberately do NOT build or start anything: that needs a Docker daemon, several minutes and a
network, and a test that only runs on a good day is a test nobody trusts. What they assert is that
the distribution is INTERNALLY COHERENT — that it selects providers the platform actually has, that
it does not quietly re-introduce a cloud dependency, and that the things a human must supply are
the two we said were irreducible.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]

#: `${NAME}` / `${NAME:-default}` / `${NAME-default}` — the whole of compose's interpolation syntax
#: that this file uses.
_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _interpolate(text: str) -> str:
    """The value compose sees on a machine that has set NONE of these variables — which is the
    machine every claim in this file is about, and the state of any install written before the
    variable existed."""
    return _INTERPOLATION.sub(lambda m: m.group(2) or "", text)


def _env(service: str) -> dict[str, str]:
    return {k: str(v) for k, v in (SERVICES[service].get("environment") or {}).items()}


# ── the stack is complete ───────────────────────────────────────────────────────────────────────

def test_every_piece_a_factory_needs_is_declared():
    """A durable engine, something that runs jobs, and something a human can look at. Missing any
    one leaves a stack that starts and then does nothing, which is the hardest kind to diagnose."""
    assert {"temporal", "worker", "panel"} <= set(SERVICES)


def test_the_worker_waits_for_a_temporal_that_is_actually_READY():
    """A port that accepts connections is not a server that can hold a workflow. Starting the
    worker against the first gives a crash loop that reads like a configuration error."""
    dep = SERVICES["worker"]["depends_on"]["temporal"]
    assert dep["condition"] == "service_healthy"
    assert "healthcheck" in SERVICES["temporal"]


def test_temporal_has_its_own_database_and_waits_for_it():
    assert SERVICES["temporal"]["depends_on"]["temporal-db"]["condition"] == "service_healthy"


# ── no cloud dependency sneaks back in ──────────────────────────────────────────────────────────

def test_the_distribution_names_no_aws_service():
    """The whole point. A compose file that quietly needed DynamoDB or CloudWatch would be a demo
    that only works on our account."""
    text = (ROOT / "docker-compose.yml").read_text().lower()
    for banned in ("dynamodb", "cloudwatch", "secretsmanager", "fargate", "ecr.", "amazonaws"):
        for line in text.splitlines():
            if banned in line and not line.strip().startswith("#"):
                pytest.fail(f"the OSS distribution references {banned!r}: {line.strip()}")


@pytest.mark.parametrize("service", ["worker", "panel"])
def test_telemetry_is_configured_explicitly_rather_than_inferred(service):
    """`metrics_sink_kind()` infers `null` when OPENFACTORY_METRICS_TABLE is absent, so leaving it unsaid
    would give a distribution that silently records nothing and loses the cost dashboard —
    described in architecture.md §8 as the ruler every other decision is measured with."""
    assert _env(service)["OPENFACTORY_METRICS_SINK"] == "sqlite"


@pytest.mark.parametrize("service", ["worker", "panel"])
def test_the_sink_kind_is_one_the_platform_actually_has(service):
    from openfactory.observability.registry import METRICS_SINKS

    assert _env(service)["OPENFACTORY_METRICS_SINK"] in METRICS_SINKS


def test_the_box_kind_is_one_the_platform_actually_has():
    """`container` and `fargate` are strings the runtime branches on. A typo here is a stack that
    boots and then never runs a job."""
    assert _env("worker")["OPENFACTORY_SANDBOX"] in ("container", "worktree", "fargate")


def test_the_box_is_NOT_fargate():
    """The distribution must not point at the cloud path — it is the one that needs an AWS account
    and an ECS cluster."""
    assert _env("worker")["OPENFACTORY_SANDBOX"] != "fargate"


def test_the_panel_is_not_told_boxes_are_remote():
    """`_boxes_are_remote()` gates the CloudWatch fallback (C-11c). If the compose set
    OPENFACTORY_SANDBOX=fargate on the panel, every request for a job with no journal yet would reach for
    AWS and log an alarm about a service this deployment does not run."""
    from openfactory.api.app import _boxes_are_remote

    env = _env("panel")
    assert env.get("OPENFACTORY_SANDBOX", "container") != "fargate"
    assert not env.get("OPENFACTORY_FARGATE_CLUSTER")
    assert callable(_boxes_are_remote)


# ── state survives a rebuild ────────────────────────────────────────────────────────────────────

def test_the_registry_lives_on_a_volume_not_in_the_image():
    """C-12's whole point. A registry inside the image means onboarding a repository costs a
    rebuild, and this is the file that decides whether the fix is actually wired."""
    worker = SERVICES["worker"]
    live = _env("worker")["OPENFACTORY_REGISTRY"]
    assert live.startswith("/var/lib/openfactory/")
    assert any(v.split(":")[1].startswith("/var/lib/openfactory") for v in worker["volumes"]
               if ":" in v and not v.startswith("/"))


def test_the_panel_and_the_worker_share_the_registry_and_the_journals():
    """Two processes, one truth. A panel reading a different registry would list no jobs and say
    nothing about why."""
    w, p = _env("worker"), _env("panel")
    assert w["OPENFACTORY_REGISTRY"] == p["OPENFACTORY_REGISTRY"]
    shared = {v.split(":")[0] for v in SERVICES["worker"]["volumes"] if not v.startswith("/")}
    assert shared & {v.split(":")[0] for v in SERVICES["panel"]["volumes"] if not v.startswith("/")}


def test_every_named_volume_is_declared():
    """A volume reference that is not a host path must be a volume this file DECLARES, or compose
    invents an anonymous one and the state it was supposed to keep disappears on the next `down`.

    `startswith("/")` USED TO BE HOW A HOST BIND WAS RECOGNISED, and on 2026-08-30 that stopped
    being true: the work directory became `${OPENFACTORY_WORK_DIR:-/var/lib/openfactory-work}:…`
    so a new install could own it without `sudo`. The source is still a host path — it just does
    not start with a slash until compose has interpolated it. Read literally, this guard called
    the token `${OPENFACTORY_WORK_DIR` an undeclared named volume and went red over a correct
    change, which is the shape of a guard that has to be widened by hand every time and eventually
    is widened once too often.

    So the interpolation is resolved FIRST, with an empty environment — the state of every machine
    that has not set the variable — and the host-bind test is then the same one it always was."""
    named = {_interpolate(v).split(":")[0] for s in SERVICES.values()
             for v in (s.get("volumes") or [])}
    named = {v for v in named if not v.startswith("/")}
    assert named <= set(COMPOSE.get("volumes") or {}), named - set(COMPOSE.get("volumes") or {})


def test_the_interpolation_reader_can_TELL_a_host_bind_from_a_named_volume():
    """Verify the verifier. A resolver that returned its input unchanged would make the guard above
    pass by classifying every interpolated bind as a named volume that happens to be declared —
    and a resolver that swallowed everything would make it pass by finding nothing at all."""
    assert _interpolate("${OPENFACTORY_WORK_DIR:-/var/lib/openfactory-work}") == \
        "/var/lib/openfactory-work"
    assert _interpolate("openfactory_state:/var/lib/openfactory") == \
        "openfactory_state:/var/lib/openfactory"
    assert _interpolate("${NOT_SET_ANYWHERE}") == ""


def test_the_worker_can_launch_a_sibling_container():
    """Docker-out-of-docker: the box is a sibling on the host daemon, not a nested one. Without
    the socket the worker starts, accepts a ticket, and fails at the first job — the worst place
    to discover a missing mount."""
    assert any("/var/run/docker.sock" in v for v in SERVICES["worker"]["volumes"])


# ── the images build anywhere ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["base-python", "worker", "sandbox"])
def test_no_image_is_pinned_to_one_cpu_architecture(name):
    """Both prospect stacks run x86 Linux. `FROM --platform=linux/arm64` made every image
    unbuildable for them, bought the cloud build nothing (deploy.sh passes --platform explicitly
    on the command line), and would have been discovered by a stranger, not by us."""
    text = (ROOT / "docker" / f"{name}.Dockerfile").read_text()
    for line in text.splitlines():
        if line.startswith("FROM"):
            assert "--platform" not in line, f"{name}.Dockerfile pins a platform: {line.strip()}"


# ── the images build on a network that re-signs HTTPS ───────────────────────────────────────────
#
# An organisation that terminates outbound TLS presents a certificate signed by a root no public
# image ships, and every `pip install` / `npm install -g` in this directory then dies on
# CERTIFICATE_VERIFY_FAILED. `docker/extra-ca/` is where such a deployment puts its root; these
# guard the two properties that make it worth having: it is WIRED into every image that installs
# from the network, EARLY ENOUGH to matter, and it costs the public build nothing.

#: Images that install from the network with their own `FROM`. `sandbox` is absent deliberately —
#: it builds FROM the base and inherits everything, which the next test asserts rather than assumes.
_IMAGES_THAT_FETCH = ["base-python", "worker"]

#: What the block must do, in the order a build needs it: take the certs out of the context, put
#: them in the system store, and point the two package managers at the result.
_CA_STEPS = ("COPY docker/extra-ca/", "update-ca-certificates",
             "NODE_EXTRA_CA_CERTS", "/etc/pip.conf")


def _instructions(name: str) -> list[str]:
    """A Dockerfile's lines with the comments removed.

    Every guard below reads these rather than the file. Twice now a check has passed against a
    broken Dockerfile because the COMMENT explaining the trap contained the string the check was
    looking for — a test satisfied by the sentence describing the bug."""
    return [line for line in (ROOT / "docker" / f"{name}.Dockerfile").read_text().splitlines()
            if not line.lstrip().startswith("#")]


def _stages(name: str) -> list[list[str]]:
    """One list per `FROM`. Checked PER STAGE and never per file, because the worker builds its
    toolbox in a `node:20-slim` of its own: a step present in the final stage only leaves that one
    broken, which is exactly how it broke."""
    out: list[list[str]] = []
    for line in _instructions(name):
        if line.startswith("FROM "):
            out.append([])
        if out:
            out[-1].append(line)
    return out


@pytest.mark.parametrize("name", _IMAGES_THAT_FETCH)
def test_an_image_that_fetches_can_be_told_which_root_to_trust(name):
    """Without this the corporate-proxy failure is unfixable without editing this repository —
    which is a fork, for a certificate."""
    text = "\n".join(_instructions(name))
    for step in _CA_STEPS:
        assert step in text, f"{name}.Dockerfile has no extra-CA step {step!r}"


@pytest.mark.parametrize("name", _IMAGES_THAT_FETCH)
def test_the_root_is_trusted_BEFORE_the_first_install_that_needs_it(name):
    """The ordering IS the feature. `apt` survives a re-signing proxy (Debian's mirrors are plain
    HTTP), so a block placed after the first apt line looks fine and still leaves every `pip` and
    `npm` line failing — which is how this was found: the stock base image died on `pip install
    uv`, four lines in, on a network where `apt-get update` had just succeeded."""
    for stage in _stages(name):
        installs = [i for i, line in enumerate(stage)
                    if ("pip install" in line or "npm install" in line)]
        if not installs:
            continue
        copies = [i for i, line in enumerate(stage) if line.startswith("COPY docker/extra-ca/")]
        assert copies, f"{name}.Dockerfile stage `{stage[0]}` installs with no extra CA"
        assert min(copies) < min(installs), (
            f"{name}.Dockerfile stage `{stage[0]}` trusts the extra CA at line {min(copies)}, "
            f"after its first install at line {min(installs)} — too late to help it")


@pytest.mark.parametrize("name", _IMAGES_THAT_FETCH)
def test_node_learns_the_CA_by_the_one_route_a_caller_cannot_move(name):
    """npm's config is `$PREFIX/etc/npmrc` and `--prefix` REDEFINES that prefix, so no file this
    repository writes is read by `npm install -g --prefix /toolbox/pkg` — the worker's own toolbox
    line. Two fixes died there: `/etc/npmrc` (right for Debian's npm, so the base image went green
    while the toolbox stage failed) and then three prefixes at once, because the one that matters
    is chosen by the caller. `NODE_EXTRA_CA_CERTS` is read by node itself.

    THE FILE MUST ALWAYS EXIST, empty when nothing was supplied: node warns on every invocation
    about a MISSING extra-certs file and says nothing about an empty one (measured, both), so
    creating it unconditionally is what leaves the public build's output unchanged."""
    text = "\n".join(_instructions(name))
    assert "ENV NODE_EXTRA_CA_CERTS=" in text, (
        f"{name}.Dockerfile relies on an npmrc, which `--prefix` moves out from under it")
    assert ": > /usr/local/share/openfactory/extra-ca.crt" in text, (
        f"{name}.Dockerfile does not always create the file NODE_EXTRA_CA_CERTS names — a missing "
        "one makes node warn on every invocation of the public build")
    for stage in _stages(name):
        installs = [i for i, line in enumerate(stage) if "npm install" in line]
        if not installs:
            continue
        envs = [i for i, line in enumerate(stage) if line.startswith("ENV NODE_EXTRA_CA_CERTS=")]
        assert envs and min(envs) < min(installs), (
            f"{name}.Dockerfile stage `{stage[0]}` runs npm before node is told about the CA")


@pytest.mark.parametrize("name", _IMAGES_THAT_FETCH)
def test_apt_can_be_pointed_somewhere_reachable(name):
    """Debian's mirrors are plain HTTP by design, and a network that inspects 443 while throttling
    80 lets `apt-get update` succeed and then drops the install part way through — a failed fetch
    that reads like a broken mirror. Without a knob, the only fix is editing this repository."""
    text = "\n".join(_instructions(name))
    assert "ARG DEBIAN_MIRROR" in text, f"{name}.Dockerfile cannot be pointed at another mirror"
    assert 'if [ -n "${DEBIAN_MIRROR}" ]' in text, (
        f"{name}.Dockerfile must ACT on the mirror being declared, so that leaving it empty is a "
        "no-op — an unconditional rewrite would move the public build off Debian's own mirror")


@pytest.mark.parametrize("name", _IMAGES_THAT_FETCH)
def test_the_root_is_trusted_BEFORE_apt_is_pointed_at_an_https_mirror(name):
    """The two knobs are ordered, and reversing them fails in the least informative way there is.

    MEASURED IN THAT ORDER, and by making the mistake: an image told to fetch over https before it
    trusts the root its proxy presents does not say "TLS refused". `apt-get update` comes back with
    no package lists at all, and every install line then reports `E: Unable to locate package git`
    — a missing certificate wearing a broken mirror's clothes."""
    for stage in _stages(name):
        mirrors = [i for i, line in enumerate(stage) if line.startswith("ARG DEBIAN_MIRROR")]
        if not mirrors:
            continue
        copies = [i for i, line in enumerate(stage) if line.startswith("COPY docker/extra-ca/")]
        assert copies, f"{name}.Dockerfile stage `{stage[0]}` retargets apt but takes no CA"
        assert min(copies) < min(mirrors), (
            f"{name}.Dockerfile stage `{stage[0]}` points apt elsewhere at line {min(mirrors)}, "
            f"before trusting the extra CA at line {min(copies)} — unverifiable there")


def test_the_deployment_declares_the_mirror_where_it_declares_everything_else():
    """A build arg nobody can reach from `.env.compose` is a knob only somebody reading the
    Dockerfiles knows exists, on the one file the OSS distribution asks a human to fill in.

    THE SERVICES ARE DERIVED, NEVER LISTED. Written as a hand-kept pair this passed while `panel` —
    which builds from the WORKER's Dockerfile — was missing the row, and the stack then failed on
    the panel's copy of the toolbox stage while the worker's was still running. Which services need
    it is a fact about the compose file, not a fact somebody remembered."""
    for name, service in SERVICES.items():
        build = service.get("build")
        if not build:
            continue
        if "ARG DEBIAN_MIRROR" not in (ROOT / build["dockerfile"]).read_text():
            continue
        args = build.get("args") or {}
        assert args.get("DEBIAN_MIRROR") == "${DEBIAN_MIRROR:-}", (
            f"{name} builds from {build['dockerfile']}, which takes DEBIAN_MIRROR, and is not "
            "given it — that image fetches from a mirror this deployment did not choose")
    assert "DEBIAN_MIRROR=" in (ROOT / ".env.compose.example").read_text()


def test_the_sandbox_is_exempt_because_it_inherits_and_not_because_it_forgot():
    """The exemption is a property of the image, so it expires by itself: an image that stopped
    building on the base would stop inheriting the trust store, and this fails."""
    text = (ROOT / "docker" / "sandbox.Dockerfile").read_text()
    assert "FROM openfactory-python" in text
    assert "COPY docker/extra-ca/" not in text


def test_the_public_tree_ships_no_certificate_and_the_build_is_unchanged_without_one():
    """The no-op half. A `.crt` committed here would be one deployment's network imposed on every
    reader; an empty directory with no README would be deleted by the next person to tidy up.

    THE CLAIM IS ABOUT THE REPOSITORY, NOT ABOUT THE MACHINE RUNNING THIS. The first cut globbed
    the directory for `*.crt` and went red the moment a deployment actually adopted the feature —
    a certificate sitting in that working tree is the entire point of it being there. A guard that
    fails on the one behaviour it exists to enable is a guard somebody deletes, and then the
    accident it was written for is the one nothing catches. So what is asserted is the property
    that survives adoption: the certificate cannot reach a COMMIT by accident."""
    here = ROOT / "docker" / "extra-ca"
    assert (here / "README.md").is_file(), "docker/extra-ca must explain itself or it is clutter"
    rules = [line.strip() for line in (here / ".gitignore").read_text().splitlines()]
    assert "*.crt" in rules, (
        "docker/extra-ca/.gitignore must ignore *.crt — without it, one `git add -A` on a machine "
        "behind a corporate proxy publishes that organisation's root certificate")
    for name in _IMAGES_THAT_FETCH:
        text = (ROOT / "docker" / f"{name}.Dockerfile").read_text()
        assert "ls /tmp/extra-ca/*.crt" in text, (
            f"{name}.Dockerfile must ACT on a certificate being there, so that none being there "
            "does nothing — an unconditional install would change the public build")


# ── what a human must supply ────────────────────────────────────────────────────────────────────

def test_the_example_env_exists_and_the_compose_reads_it():
    example = (ROOT / ".env.compose.example").read_text()
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_PANEL_TOKEN"):
        assert var in example
        assert f"${{{var}" in (ROOT / "docker-compose.yml").read_text()


def test_no_credential_has_a_default_baked_into_the_compose():
    """A default credential is worse than none: it looks configured. Every one must resolve to
    empty and let `doctor` report it."""
    text = (ROOT / "docker-compose.yml").read_text()
    # The chat channel's token was on this list until 2026-08-26, when the compose file stopped
    # naming any add-on package's variable at all (`test_the_core_names_no_add_on_variable…`).
    for var in ("OPENFACTORY_BOT_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_GH_APP_KEY_CONTENT"):
        assert f"${{{var}:-}}" in text, f"{var} must default to empty, not to a value"


def test_the_example_says_that_an_empty_panel_token_means_open():
    """The one default that is dangerous rather than merely absent. It has to be said where
    somebody reads it, not only in the code that implements it."""
    example = (ROOT / ".env.compose.example").read_text().lower()
    assert "open" in example and "panel_token" in example


def test_the_example_says_the_harness_costs_money():
    """The asterisk on "everything free". Better read here than discovered after installing."""
    example = (ROOT / ".env.compose.example").read_text().lower()
    assert "costs" in example or "custa" in example


# ── the setting the compose file makes must actually be read ────────────────────────────────────

@pytest.mark.parametrize("env,expected", [
    ({}, "container"),
    ({"OPENFACTORY_FARGATE_CLUSTER": "openfactory-sandbox"}, "container"),
    ({"OPENFACTORY_SANDBOX": "fargate"}, "fargate"),
    ({"OPENFACTORY_SANDBOX": "container", "OPENFACTORY_FARGATE_CLUSTER": "openfactory-sandbox"}, "container"),
    ({"OPENFACTORY_SANDBOX": "worktree"}, "worktree"),
    ({"OPENFACTORY_SANDBOX": ""}, "container"),
])
def test_the_box_kind_resolves_from_the_deployments_own_configuration(monkeypatch, env, expected):
    """The compose file set `OPENFACTORY_SANDBOX: container` and NOTHING READ IT — the models split three
    ways and the cloud worked only because `api/app.py` passed `sandbox="fargate"` by hand. A
    configuration that looks configured and is ignored is this repository's signature defect.

    AND A VENDOR'S VARIABLE DECIDES NOTHING. `OPENFACTORY_FARGATE_CLUSTER` used to make the answer
    `fargate` — the core answering the name of a box it does not implement, from a variable only
    that box's add-on reads. A deployment that runs its boxes remotely says so in the one
    variable every box uses; one that says nothing gets the container the distribution ships."""
    from openfactory.runtime.temporal.io import default_sandbox

    for k in ("OPENFACTORY_SANDBOX", "OPENFACTORY_FARGATE_CLUSTER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert default_sandbox() == expected


@pytest.mark.parametrize("model", ["JobParams", "RunJobInput", "PollInput", "StartJobsInput",
                                   "CiRepairInput"])
def test_every_model_that_carries_a_box_kind_resolves_it_the_same_way(monkeypatch, model):
    """They used to disagree: JobParams and RunJobInput defaulted to `container`, the rest to
    `fargate`. One of those was always wrong for whichever world you were in. (`PromoteInput` and
    `ReleaseInput` carry a box kind too, but are built INSIDE the workflow body, so their default
    is `""` — resolved by the activity, never by a factory that reads the environment there.)"""
    import openfactory.runtime.temporal.io as io

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    cls = getattr(io, model)
    import typing

    kwargs = {f: (["x"] if typing.get_origin(i.annotation) is list else "x")
              for f, i in cls.model_fields.items() if i.is_required()}
    assert cls(**kwargs).sandbox == "fargate"


def test_the_deployed_worker_declares_its_box_like_every_other_deployment(monkeypatch):
    """The inverse of the rule this test used to pin. A cloud worker's task definition must now
    say `OPENFACTORY_SANDBOX=fargate` — one variable, the same one the compose file already sets
    to `container` — because the core no longer infers a connector's box from that connector's
    cluster variable. A worker that sets only the cluster gets the container and fails loudly at
    its first job, rather than the core knowing one vendor by heart."""
    from openfactory.runtime.temporal.io import JobParams

    monkeypatch.delenv("OPENFACTORY_SANDBOX", raising=False)
    monkeypatch.setenv("OPENFACTORY_FARGATE_CLUSTER", "openfactory-sandbox")
    assert JobParams(project="books", issue="189").sandbox == "container"
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    assert JobParams(project="books", issue="189").sandbox == "fargate"

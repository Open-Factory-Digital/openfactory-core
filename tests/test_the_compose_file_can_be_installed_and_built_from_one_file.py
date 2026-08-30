"""One `docker-compose.yml` serves the installer and the contributor, and cannot serve one badly.

THE PROBLEM THIS FILE GUARDS (ADR-0043). Until 2026-08-30 every service in this stack carried
`build:` and nothing else, so the README's first command built three images from source —
`docker/worker.Dockerfile` alone runs a `node:20-slim` stage that `npm install -g`s four agent CLIs
before Python is reached. Multi-minute and multi-GB, on the one command a stranger types first.
Publishing the images fixes that only if the compose file can PULL them, and the obvious way to
arrange that is a second "release" compose file — which is the defect this codebase names most
often, the truth about one stack split across two places. So each service carries BOTH `image:` and
`build:`: `up -d` pulls, `--profile build up -d --build` builds and tags the result as that same
name, and the tracked file IS the release asset.

Three ways that arrangement rots, and one of them is not a matter of taste:

  A `build:` WITH NO `image:` builds to a compose-invented name (`<project>-<service>`), which no
  registry has and no `pull` can find — the contributor's path silently stops producing the
  artefact the installer's path consumes.

  AN `image:` THAT IS NOT PINNED TO `${OPENFACTORY_VERSION…}` puts somebody on a moving tag. The
  tracked default is `main` on purpose (a contributor gets what they are working on); every
  install written by the installer carries an explicit `vX.Y.Z`, and a hard-coded tag here would
  take that choice away from both.

  A BUILD-ONLY SERVICE WITHOUT ITS PROFILE makes `up -d` build the box image it could have pulled
  — and the reverse, a profile on a service something profile-less DEPENDS ON, makes the default
  project INVALID. That last one is not a slow install, it is a total refusal, and it is the whole
  reason the worker no longer declares `depends_on: sandbox-image`. Measured 2026-08-30 with
  Docker Compose against a two-service probe:

      service "app" depends on undefined service "builder": invalid compose project

  `docker compose up -d` exits non-zero before it starts anything. `test_no_service_the_installer_
  starts_depends_on_a_service_hidden_behind_a_profile` is that measurement, kept.

WHY `base-image` IS EXEMPT FROM THE ghcr RULE, AND WHY THE EXEMPTION IS DERIVED. It is not a
distributed artefact: it is the layer `docker/sandbox.Dockerfile` says `FROM openfactory-python:
latest` about, a build stage spelled as a service because Compose has no other way to order one
build before another. The exemption is computed from that `FROM` line rather than read from a list
here, so an image that stopped being another Dockerfile's base would stop being exempt — the same
shape as `test_the_sandbox_is_exempt_because_it_inherits_and_not_because_it_forgot`, and for the
same reason: a name in a list is an exemption nobody re-earns.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
SERVICES: dict[str, dict] = COMPOSE["services"]

#: The registry and organisation the release publishes to. Lower case is not a style choice — OCI
#: rejects an upper-case path component, so `Open-Factory-Digital` would be a tag nothing can push.
REGISTRY_PREFIX = "ghcr.io/open-factory-digital/"

#: The interpolation every published reference must be tagged with. Spelled once; the two guards
#: below and the mutation plan all read this rather than repeating the string.
VERSION_TAG = "${OPENFACTORY_VERSION:-main}"


def _from_bases() -> set[str]:
    """Every image some Dockerfile in this tree builds `FROM`.

    Derived, because this is the whole exemption: an image another image is built on is a build
    stage, whatever it is spelled as in the compose file."""
    bases: set[str] = set()
    for dockerfile in sorted((ROOT / "docker").glob("*.Dockerfile")):
        for line in dockerfile.read_text().splitlines():
            if match := re.match(r"^FROM\s+(\S+)", line):
                bases.add(match.group(1))
    return bases


def _builders() -> dict[str, dict]:
    """Services that build an image — the ones both readers of this file care about."""
    return {name: svc for name, svc in SERVICES.items() if svc.get("build")}


def test_the_sweep_finds_the_services_this_file_is_about():
    """Verify the verifier. Every assertion below is a loop, and a loop over nothing passes — which
    is how a guard survives the deletion of its own subject."""
    assert len(_builders()) >= 4, sorted(_builders())
    assert _from_bases(), "no Dockerfile in docker/ declares a FROM — the exemption measures nothing"


def test_every_service_that_builds_an_image_also_names_it():
    """`build:` alone tags the result `<project>-<service>`, which no registry holds. The two paths
    have to converge on ONE name or the contributor is not building what the installer pulls."""
    unnamed = sorted(name for name, svc in _builders().items() if not svc.get("image"))
    assert not unnamed, (
        f"{unnamed} declare `build:` and no `image:`, so `--build` tags them with a name compose "
        f"invented and `docker compose up -d` has nothing to pull. Give each the "
        f"`{REGISTRY_PREFIX}<name>:{VERSION_TAG}` reference the release publishes.")


def test_every_image_this_project_distributes_is_pinned_to_the_declared_version():
    """The published references, and the one exemption, computed rather than listed."""
    bases = _from_bases()
    wrong = []
    for name, svc in sorted(_builders().items()):
        image = svc["image"]
        if image in bases:
            continue  # a build stage: another Dockerfile is built FROM it. Nothing pulls it.
        if not image.startswith(REGISTRY_PREFIX):
            wrong.append(f"{name}: {image!r} is neither a {REGISTRY_PREFIX}… reference nor the "
                         f"FROM of another Dockerfile in this tree")
        elif not image.endswith(f":{VERSION_TAG}"):
            wrong.append(f"{name}: {image!r} is not pinned to `{VERSION_TAG}` — a hard-coded tag "
                         f"here overrides the version the installer wrote into .env.compose")
    assert not wrong, "\n  ".join([""] + wrong)


def test_the_services_that_exist_only_to_build_are_kept_out_of_the_install():
    """`command: ["true"]` is how this file spells "produces an image, runs nothing" — both such
    services hand their image to something that is not compose (the sandbox to the worker's own
    `docker run`, the base to another Dockerfile's `FROM`). Without the profile, the installer's
    `up -d` builds a multi-GB box image it could have pulled in a fraction of the time."""
    for name, svc in sorted(SERVICES.items()):
        builds_only = svc.get("command") == ["true"]
        profiled = "build" in (svc.get("profiles") or [])
        assert builds_only == profiled, (
            f"{name}: command={svc.get('command')!r} and profiles={svc.get('profiles')!r}. A "
            f"service that only builds must carry `profiles: [\"build\"]` so `up -d` skips it, "
            f"and a service the stack actually RUNS must not be hidden behind one.")


def test_no_service_the_installer_starts_depends_on_a_service_hidden_behind_a_profile():
    """THE measurement, and the reason `worker` lost its `sandbox-image` dependency.

    Compose does not quietly enable the profile of something you depend on — it refuses the whole
    project, before starting anything (2026-08-30, Docker Compose, two-service probe):

        service "app" depends on undefined service "builder": invalid compose project

    So this is not a slow `up`, it is a stack that cannot start at all, on the exact command the
    one-line install runs. A pure check over the parsed file, so it fails on a laptop with no
    daemon as loudly as it would in the job that finally runs compose."""
    hidden = {name for name, svc in SERVICES.items() if svc.get("profiles")}
    broken = []
    for name, svc in sorted(SERVICES.items()):
        if svc.get("profiles"):
            continue  # itself profiled: its dependencies are enabled alongside it
        for dependency in (svc.get("depends_on") or {}):
            if dependency in hidden:
                broken.append(f"{name} depends on {dependency}, which is behind "
                              f"{SERVICES[dependency]['profiles']}")
    assert not broken, (
        "`docker compose up -d` refuses this project outright — it is the installer's one command:"
        "\n  " + "\n  ".join(broken))


def test_the_worker_launches_the_box_image_the_build_profile_tags():
    """The worker does not run the box through compose: it issues `docker run` against the HOST's
    daemon by the name in `OPENFACTORY_SANDBOX_IMAGE`. So the name it launches and the name
    `sandbox-image` is tagged with are connected by NOTHING but agreement, and a disagreement is
    invisible until the first ticket — the failure arriving one layer away from its cause, which is
    the defect the `sandbox-image` service was added to prevent in the first place."""
    launched = SERVICES["worker"]["environment"]["OPENFACTORY_SANDBOX_IMAGE"]
    tagged = SERVICES["sandbox-image"]["image"]
    assert launched == tagged, (
        f"the worker launches {launched!r} and the build tags {tagged!r} — every job would die on "
        f"`image not found` against a box this stack had just built")


# ── the same file, judged by the tool that actually reads it ────────────────────────────────────
#
# SKIPPED AT RUN TIME AND NEVER AT COLLECTION (CONTRIBUTING, `tests/demo_projects.py`): a laptop or
# a fork without Docker still COLLECTS this test and reports it skipped, because a module that
# resolves an optional binary at import can raise during collection and take the whole suite with
# it — that happened here on 2026-08-06 and CI executed zero tests for fifteen days.

_HAS_COMPOSE = shutil.which("docker") is not None


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--env-file", ".env.compose.example", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker is not installed on this machine")
def test_compose_itself_accepts_the_project_on_both_paths():
    """The parsed-file guards above encode what Compose does; this one asks Compose. Both paths,
    because the refusal measured on 2026-08-30 affected only the default one — a build-profile-only
    check would have been green through the entire outage it exists to prevent."""
    for label, args in (("the installer's `up -d`", ()),
                        ("the contributor's `--profile build`", ("--profile", "build"))):
        done = _compose(*args, "config", "--quiet")
        if done.returncode != 0 and "Cannot connect to the Docker daemon" in done.stderr:
            pytest.skip("the Docker daemon is not answering on this machine")
        assert done.returncode == 0, (
            f"docker compose refuses this project on {label}:\n{done.stderr[-1500:]}")


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker is not installed on this machine")
def test_the_version_row_of_the_example_file_is_what_the_images_resolve_to():
    """`.env.compose.example` ships `OPENFACTORY_VERSION=` EMPTY, and `${VAR:-main}` treats empty
    exactly as unset — a fact worth measuring rather than believing, because `${VAR-main}` (no
    colon) does not, and the one-character difference would resolve every image to `…:` and pull
    nothing."""
    done = _compose("config")
    if done.returncode != 0 and "Cannot connect to the Docker daemon" in done.stderr:
        pytest.skip("the Docker daemon is not answering on this machine")
    assert done.returncode == 0, done.stderr[-1500:]

    published = re.findall(rf"^\s*image:\s*({re.escape(REGISTRY_PREFIX)}\S+)$", done.stdout, re.M)
    assert published, f"no {REGISTRY_PREFIX}… image survived interpolation:\n{done.stdout[:800]}"
    assert all(image.endswith(":main") for image in published), (
        f"the empty version row did not fall back to `main`: {sorted(set(published))}")

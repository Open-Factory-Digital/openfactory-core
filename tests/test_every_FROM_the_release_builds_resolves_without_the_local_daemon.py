"""Every `FROM` the release builds must resolve on a machine that has never built anything.

THE FAILURE THIS EXISTS FOR, in full, because it is the most expensive one this repository has had
and the cheapest one to have caught. The v0.1.0 release run (33396474816, 2026-08-31) published
`openfactory-worker` and `openfactory-cli`, and failed on `openfactory-sandbox`:

    ERROR: failed to solve: openfactory-python:latest: failed to resolve source metadata for
    docker.io/library/openfactory-python:latest: pull access denied, repository does not exist
    or may require authorization

`docker/sandbox.Dockerfile` began `FROM openfactory-python:latest`. Under Compose that resolves,
because the `base-image` service tags it on the local daemon and Compose builds ON the daemon.
Under the release it does not, because `docker/setup-buildx-action` creates a **docker-container**
driver builder whose BuildKit has its own content store and cannot read the daemon's images at all
— so the name is resolved as `docker.io/library/openfactory-python`, which is Docker Hub, which has
never heard of this project. Reproduced on a laptop the same day: byte-identical error on the
docker-container driver, exit 0 on the `docker` driver.

`release` needs `images`, so no GitHub Release was created and no assets were published — and
`install.sh` resolves its pinned tag out of that Release. One unqualified word broke the one-liner
end to end, ten minutes into a public release, on the first tag this project ever cut.

THE PROPERTY, STATED SO IT OUTLIVES THIS INCIDENT. A `FROM` is resolvable by a builder with no
local image store when it is one of exactly three things:

  · a STAGE defined earlier in the same file — resolved inside the build, no registry involved;
  · a HOSTED reference (`ghcr.io/…`) — which this project must also publish, or the message merely
    changes from `pull access denied` to `manifest unknown`; or
  · a Docker Hub OFFICIAL image named on `OFFICIAL_BASES` below.

Anything else is the defect, and the bare name is what makes it one: `docker.io/library/<name>` is
where the build will look, and for a name this project produces that repository does not exist and
never will. It then fails everywhere except on the one machine that happens to have built it —
which is every developer's laptop and no CI runner.

WHY NOT SIMPLY "MUST BE FULLY QUALIFIED". Because `FROM python:3.12-slim` is not fully qualified
and is perfectly fine, and a guard that failed on it would be widened within the week until it
meant nothing. The distinction is not syntax, it is whether Docker Hub can serve the name — which
no offline guard can ask. So the official images this project builds on are DECLARED, and every
other bare name is refused.

WHY THE RULE IS NOT "IS IT ONE OF OURS". That was the first version, and its own mutation plan
killed it within the hour: restoring the literal `FROM openfactory-python:latest` passed, because
by then the base had been renamed and `openfactory-python` was no longer a name this project
produced. A dangling bare name is exactly as unbuildable as one of ours, and rather harder to
notice.
"""

from __future__ import annotations

import pathlib

import dockerfiles
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())

#: Where this project publishes. A reference under it is ours to make true.
REGISTRY_PREFIX = "ghcr.io/open-factory-digital/"

#: The Docker Hub OFFICIAL images this project is allowed to build on with a bare name.
#:
#: A LIST, AND DELIBERATELY SO. Docker Hub's `library/` namespace is the only place an unqualified
#: reference resolves, and no offline guard can ask whether a given name is in it — so the decision
#: is written down here instead, where adding one is a one-line commit a reviewer sees. That is the
#: whole difference between `python:3.12-slim`, which is fine, and `openfactory-python:latest`,
#: which took down the v0.1.0 release: both are bare, and only one of them exists.
OFFICIAL_BASES = {"python", "node", "debian", "alpine", "ubuntu", "busybox", "docker"}


def _ours() -> set[str]:
    """Every image name THIS repository produces, however it is spelled.

    Derived from the compose file's `image:` keys — the one place every artefact of this project is
    named — reduced to the bare repository, so `ghcr.io/open-factory-digital/openfactory-base:main`
    and a hypothetical local `openfactory-base` are recognised as the same thing. That reduction is
    the whole point: the defect was a LOCAL spelling of an image we build."""
    names = set()
    for service in COMPOSE["services"].values():
        reference = service.get("image")
        if reference and service.get("build"):
            names.add(dockerfiles.compose_image_name(reference))
    return names


def _release_dockerfiles() -> list[pathlib.Path]:
    """Every Dockerfile the release actually builds, read out of the workflow.

    NOT A GLOB OVER `docker/`, deliberately — the question is what the RELEASE builds, and a
    Dockerfile that nothing publishes cannot break a release. Reading the workflow also means a
    fourth image added to it is covered the day it is added, with nobody remembering this file."""
    found = []
    for job in WORKFLOW["jobs"].values():
        rows = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
        found += [row["dockerfile"] for row in rows]
        found += [str(s["with"]["file"]) for s in job.get("steps", [])
                  if "build-push-action" in str(s.get("uses", "")) and "file" in (s.get("with") or {})
                  and "${{" not in str(s["with"]["file"])]
    return [ROOT / rel for rel in sorted(set(found))]


def test_the_sweep_finds_the_dockerfiles_the_release_builds():
    """Verify the verifier. Every assertion below is a loop, and a loop over nothing passes — which
    is how a guard survives the deletion of its own subject."""
    built = _release_dockerfiles()

    assert len(built) >= 4, [str(p) for p in built]
    for path in built:
        assert path.is_file(), f"the release builds {path}, which is not in this tree"
    assert len(_ours()) >= 3, sorted(_ours())


@pytest.mark.parametrize("dockerfile", [p.name for p in _release_dockerfiles()])
def test_every_FROM_resolves_without_the_local_daemons_image_store(dockerfile):
    """THE guard. One parametrised case per Dockerfile the release builds, so a failure names the
    file rather than the set."""
    path = ROOT / "docker" / dockerfile
    stages: set[str] = set()
    ours = _ours()

    for reference, stage in dockerfiles.froms(path):
        bare = dockerfiles.compose_image_name(reference)

        if reference in stages:
            pass                                   # a stage defined earlier in this same file
        elif "/" in reference or reference == "scratch":
            pass                                   # an explicitly hosted registry reference
        elif bare in OFFICIAL_BASES:
            pass                                   # a Docker Hub official image
        elif bare in ours:
            pytest.fail(
                f"{dockerfile} is built `FROM {reference}` — an unqualified name for an image THIS "
                f"repository builds. A builder with no local image store resolves it as "
                f"`docker.io/library/{bare}`, which does not exist. Name it with its registry, or "
                f"make it a stage in this file.")
        else:
            pytest.fail(
                f"{dockerfile} is built `FROM {reference}`, an unqualified name that is neither a "
                f"stage in this file nor one of the official images this project builds on "
                f"({sorted(OFFICIAL_BASES)}). Only Docker Hub's official namespace resolves a bare "
                f"name, and `docker.io/library/{bare}` is where this build will look. THIS IS THE "
                f"v0.1.0 FAILURE: `FROM openfactory-python:latest` was a bare name for an image "
                f"that lived only on the machine that had built it.")

        if stage:
            stages.add(stage)


@pytest.mark.parametrize("dockerfile", [p.name for p in _release_dockerfiles()])
def test_no_FROM_is_an_unresolved_build_argument(dockerfile):
    """`FROM ${SOMETHING}` with no `ARG SOMETHING=<default>` resolves to the empty string for
    anybody who does not pass a build-arg — including `docker build -f … .`, which is what the
    Dockerfile's own header tells a reader to run. The sandbox is built through exactly such an
    ARG, so this is the way that mechanism breaks quietly."""
    for reference, _ in dockerfiles.froms(ROOT / "docker" / dockerfile):
        assert "$" not in reference, (
            f"{dockerfile} is built `FROM {reference}`, which still contains an unresolved "
            f"variable — the ARG it names has no default, so a plain `docker build` of this file "
            f"resolves it to nothing")
        assert reference.strip(), f"{dockerfile} has an empty FROM after resolution"


def test_an_image_we_build_may_only_be_a_base_when_the_release_publishes_it_first():
    """The other half. Naming our own base with its registry is only honest if that registry has
    it — otherwise the message changes from `pull access denied` to `manifest unknown` and nothing
    else improves."""
    published = set()
    for job in WORKFLOW["jobs"].values():
        rows = ((job.get("strategy") or {}).get("matrix") or {}).get("include") or []
        published |= {row["image"] for row in rows}
        published |= {str(s["with"]["images"]).rsplit("/", 1)[-1].strip()
                      for s in job.get("steps", [])
                      if "metadata-action" in str(s.get("uses", ""))}

    for path in _release_dockerfiles():
        stages: set[str] = set()
        for reference, stage in dockerfiles.froms(path):
            bare = dockerfiles.compose_image_name(reference)
            # OUR REGISTRY *OR* OUR NAME. Asking only "is this one of the images compose builds"
            # missed a `FROM ghcr.io/open-factory-digital/openfactory-baselayer` — a reference in
            # our own organisation that nothing anywhere produces, which fails with `manifest
            # unknown` and is not improved by being fully qualified (mutation, 2026-08-31).
            ours = bare in _ours() or reference.startswith(REGISTRY_PREFIX)
            if reference not in stages and ours:
                assert bare in published, (
                    f"{path.name} is built FROM {reference}, which is this project's to publish "
                    f"and no job in the release publishes — the build fails on `manifest unknown`")
            if stage:
                stages.add(stage)


def test_the_contributor_builds_our_base_rather_than_reaching_for_the_registry():
    """THE OTHER BUILDER, and it had no guard at all until a mutation asked for one.

    `docker compose build` compiles this project into ONE bake plan and builds every target
    CONCURRENTLY — `depends_on` orders container startup and says nothing about builds. So the
    sandbox resolves its `FROM` while the base is still building, and a registry reference sends it
    to ghcr for an image being built three seconds away. Measured on a daemon holding neither
    image (2026-08-31): `403 Forbidden` fetching an anonymous pull token, on a build that needs no
    network at all.

    `additional_contexts: {…: "service:base-image"}` becomes `target:base-image` in the bake plan,
    which IS a dependency bake understands — the base is built first and handed over directly, with
    no tag, no registry and no daemon store in between. Measured after: exits 0 and produces both.

    The release passes the same ARG as a registry reference, and one Dockerfile serves both because
    BuildKit resolves a named context ahead of an image of the same name."""
    sandbox = COMPOSE["services"]["sandbox-image"]["build"]
    contexts = sandbox.get("additional_contexts") or {}
    named = str((sandbox.get("args") or {}).get("OPENFACTORY_BASE_IMAGE", ""))

    assert named in contexts, (
        f"the sandbox build is told to use {named!r} as its base, which is not one of its "
        f"additional_contexts {sorted(contexts)} — compose builds every target at once, so it "
        f"would race its own base and reach for the registry")
    assert contexts[named] == "service:base-image", (
        f"the base context points at {contexts[named]!r} rather than the service that builds it, "
        f"so bake has no dependency edge to order them by")


def test_the_reader_can_tell_a_stage_from_an_image_and_a_comment_from_an_instruction():
    """Verify the verifier, on the two mistakes that made the original guard blind.

    A `FROM` inside a COMMENT is not an instruction — `test_the_sandbox_is_exempt_because_it_
    inherits_and_not_because_it_forgot` kept passing over a changed `FROM` because the comment
    above it quotes the old line. And a stage NAME is not an image: `FROM toolbox` after
    `FROM node:20-slim AS toolbox` needs no registry at all."""
    assert dockerfiles.froms(ROOT / "docker" / "worker.Dockerfile")[0] == ("node:20-slim", "toolbox")

    planted = "# FROM openfactory-python:latest\nFROM python:3.12-slim AS base\nFROM base\n"
    assert "openfactory-python" not in dockerfiles.instructions(planted)

    args = dockerfiles.arg_defaults("ARG X=ghcr.io/o/i:1\nFROM ${X}\n")
    assert dockerfiles.resolve("${X}", args) == "ghcr.io/o/i:1"


def test_the_official_allowlist_can_never_excuse_an_image_we_build_ourselves():
    """Verify the verifier. The allowlist is the one hand-written thing in this file, and the way
    it goes wrong is somebody adding the name they are being refused for — which would turn the
    guard into a rubber stamp for exactly the defect it exists to catch."""
    collision = OFFICIAL_BASES & _ours()

    assert not collision, (
        f"{sorted(collision)} is both an image this project builds and on the list of bare names "
        f"treated as Docker Hub official — one of those two is wrong, and the guard is now blind "
        f"to the v0.1.0 failure for that name")
    assert len(OFFICIAL_BASES) < 15, (
        "the allowlist has grown into a way of saying yes; it is meant to be the short list of "
        "official images this project actually builds on")

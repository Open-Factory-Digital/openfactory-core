"""The images this project references and the images it publishes are one set, in both directions.

TWO WAYS TO GET THIS WRONG, and they fail at opposite ends of the install.

A REFERENCED IMAGE NOTHING PUBLISHES fails at the user. `docker compose up -d` reports
`manifest unknown` for a tag that was never pushed — on the one command the whole one-line install
rests on, from a file that looks entirely correct. This is not hypothetical: measured 2026-08-30,
GHCR carried nothing at all while `docker-compose.yml` was about to start naming three images.

A PUBLISHED IMAGE NOTHING REFERENCES fails at the maintainer, quietly and for longer. It is built
on every tag, cached, attested and pushed; nobody pulls it, so nobody notices when it breaks, and
the day something finally does reference it the image has been wrong for months. `base-python` is
the reason this direction is worth a test rather than a shrug: it is a real Dockerfile that
produces a real image and it is deliberately NOT published, because nothing pulls it — it is the
layer `docker/sandbox.Dockerfile` is built `FROM`. A workflow that started publishing it would be
adding a fourth artefact to keep current for no reader.

WHY THE WORKFLOW IS PARSED RATHER THAN TRUSTED. `.github/workflows/release.yml` cannot be run from
the suite — it needs a registry, a token and twenty minutes — so the only thing a laptop can check
is that the file SAYS what the compose file needs it to say. That is a weaker claim than "the
images exist", and it is the strongest one available offline; it catches the whole class of defect
that is a matrix row deleted, renamed, or never added when a fourth image arrived.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

REGISTRY_PREFIX = "ghcr.io/open-factory-digital/"


def _referenced() -> set[str]:
    """Every image of ours `docker-compose.yml` names, from any key — `image:` on a service, and
    `OPENFACTORY_SANDBOX_IMAGE`, which is a reference the worker resolves against the HOST daemon
    rather than one compose ever pulls. Swept over the whole parsed document rather than over
    `image:` keys, so a reference added in a new place is covered the day it is written."""
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and REGISTRY_PREFIX in node:
            found.add(node.split(REGISTRY_PREFIX, 1)[1].split(":")[0])

    walk(COMPOSE)
    return found


def _published_with_dockerfiles() -> dict[str, str]:
    """Every image `release.yml` pushes, and the Dockerfile each is built from.

    DERIVED FROM EVERY JOB, not from one matrix. It read `jobs.images.strategy.matrix.include`
    alone, which was true until 2026-08-31 and then quietly stopped being: the base layer moved
    into a job of its own (`base_image`) so the sandbox could be built after it was in the
    registry, and a set read off the matrix would have declared the base "published by nothing"
    while the workflow published it on every run. A guard that has to be edited whenever the
    workflow grows a job is a guard that will one day be edited wrongly."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    found: dict[str, str] = {}
    for job in workflow["jobs"].values():
        rows = ((job.get("strategy") or {}).get("matrix") or {}).get("include")
        if rows:
            found.update({row["image"]: row["dockerfile"] for row in rows})
            continue
        # a single-image job: the name comes from its metadata step, the Dockerfile from its build
        pushes = [s for s in job.get("steps", []) if "build-push-action" in str(s.get("uses", ""))]
        images = [s for s in job.get("steps", []) if "metadata-action" in str(s.get("uses", ""))]
        if pushes and images:
            name = str(images[0]["with"]["images"]).rsplit("/", 1)[-1].strip()
            found[name] = str(pushes[0]["with"]["file"])
    return found


def _published() -> set[str]:
    return set(_published_with_dockerfiles())


def _repository(reference: str) -> str:
    """`ghcr.io/org/name:tag` -> `name`."""
    return reference.rsplit(":", 1)[0].rsplit("/", 1)[-1]


def _sandbox_base_reference() -> str:
    """What `docker/sandbox.Dockerfile` is built FROM, with its own `ARG` default substituted in.

    The `FROM` is `${OPENFACTORY_BASE_IMAGE}`, which says nothing on its own — the answer is the
    ARG's default, which is what a bare `docker build` of that file resolves and what every reader
    without a build-arg gets."""
    text = (ROOT / "docker" / "sandbox.Dockerfile").read_text()
    reference = next(m.group(1) for m in re.finditer(r"^FROM\s+(\S+)", text, re.M))
    for name, default in re.findall(r"^ARG\s+([A-Za-z_][A-Za-z0-9_]*)=(\S+)", text, re.M):
        reference = reference.replace(f"${{{name}}}", default).replace(f"${name}", default)
    return reference


def test_the_sweep_finds_images_on_both_sides():
    """Verify the verifier. Two empty sets are equal, and a guard that passes because it read
    nothing is the shape this codebase has been bitten by more than once."""
    assert len(_referenced()) >= 2, sorted(_referenced())
    assert len(_published()) >= 2, sorted(_published())


def test_every_image_the_compose_file_names_is_one_the_release_builds():
    """The direction that fails at the user, on their first command."""
    missing = sorted(_referenced() - _published())
    assert not missing, (
        f"docker-compose.yml references {missing} and .github/workflows/release.yml publishes "
        f"{sorted(_published())} — `docker compose up -d` would answer `manifest unknown` for a "
        f"tag nothing ever pushed, on the one command the install rests on")


def test_every_image_the_release_builds_is_one_something_references():
    """The direction that fails at the maintainer, silently and for months."""
    stray = sorted(_published() - _referenced())
    assert not stray, (
        f"release.yml publishes {stray}, which nothing in docker-compose.yml names — an image "
        f"nobody pulls is an image nobody notices breaking. `base-python` is the shape this is "
        f"about: it is built and deliberately NOT published, because the sandbox is built FROM it")


@pytest.mark.parametrize("image, dockerfile", sorted(_published_with_dockerfiles().items()))
def test_every_published_image_is_built_from_a_dockerfile_this_tree_has(image, dockerfile):
    """A matrix row naming a path that does not exist fails twenty minutes into a tag build, after
    the other two images have already been pushed — a half-published release, which is worse than
    none because `install.sh` will find the tag and pull what is missing."""
    assert (ROOT / dockerfile).is_file(), (
        f"release.yml builds {image} from {dockerfile}, which is not in this tree")


def test_the_base_layer_the_sandbox_needs_is_in_the_registry_before_the_sandbox_builds():
    """THIS GUARD FAILED TO DO ITS JOB AND HAS CHANGED SHAPE (2026-08-31, run 33396474816).

    It used to assert that a STEP existed which built the base before the push step, and its own
    message named the exact error the release then hit: *"the sandbox build would fail on `pull
    access denied` for an image that exists only on the machine that built it"*. It was green, the
    step existed, the step succeeded — and the release still died on precisely that sentence.

    WHAT IT MEASURED WAS ORDER; WHAT MATTERS IS REACHABILITY. `docker/setup-buildx-action` creates
    a **docker-container** driver builder, whose BuildKit has its own content store and cannot read
    the runner daemon's images at all. The old step `--load`ed the base into the daemon, which is
    somewhere the thing that needed it could not look. Reproduced on a laptop the same day:
    identical error on the docker-container driver, exit 0 on the `docker` driver.

    So the property is no longer "a step ran first". It is that the sandbox's base is a REGISTRY
    reference which this same workflow pushes in a job the sandbox waits for — the only arrangement
    in which two builders can agree about an image."""
    base = _sandbox_base_reference()

    assert base.startswith(REGISTRY_PREFIX), (
        f"the sandbox is built FROM {base!r}, which is not a registry reference. A builder with no "
        f"access to the local image store — which is what every CI buildx is — resolves that "
        f"against Docker Hub and fails on `pull access denied`.")
    assert _repository(base) in _published(), (
        f"the sandbox is built FROM {base!r} and no job in release.yml publishes it")

    workflow = yaml.safe_load(WORKFLOW.read_text())
    publisher = next(name for name, job in workflow["jobs"].items()
                     if _repository(base) in str(job.get("steps", "")))
    needs = workflow["jobs"]["images"].get("needs")
    needs = [needs] if isinstance(needs, str) else (needs or [])
    assert publisher in needs, (
        f"the sandbox is built in `images`, which does not wait for `{publisher}` — the two would "
        f"race, and the sandbox would pull a tag that is not pushed yet")


def test_the_sandbox_is_told_which_base_to_use_at_this_runs_own_version():
    """A sandbox built on whatever `main` happened to be, inside a release cutting `v0.1.0`, is a
    mismatched pair nothing reports. The build-arg follows `github.ref_name`, which is the tag on a
    tag build and the branch on a branch build — and the base job publishes exactly those two."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    row = next(r for r in workflow["jobs"]["images"]["strategy"]["matrix"]["include"]
               if r["image"] == "openfactory-sandbox")
    args = str(row.get("build_args", ""))

    assert "OPENFACTORY_BASE_IMAGE=" in args, (
        "the sandbox row passes no base image, so the build falls back to the Dockerfile's default "
        "— which names `main` and would be the wrong base inside a tagged release")
    assert "github.ref_name" in args, (
        f"the base is pinned to something other than this run's own ref: {args!r}")


def test_both_architectures_are_published():
    """Apple Silicon is most of the laptops this gets installed on. An amd64-only image runs there
    under emulation — slow enough that a person concludes the product is slow, which is the most
    expensive possible way to be wrong on a first run. `worker.Dockerfile` already branches on
    `TARGETARCH`, so the second architecture is ready rather than aspirational."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(s for s in workflow["jobs"]["images"]["steps"]
                if "build-push-action" in str(s.get("uses", "")))
    platforms = {p.strip() for p in str(step["with"]["platforms"]).split(",")}

    assert {"linux/amd64", "linux/arm64"} <= platforms, platforms


def test_the_release_never_publishes_a_moving_tag_a_user_could_pin_to():
    """`latest` is the tag somebody reaches for when they do not know which version they want, and
    it is exactly what the pinned install exists to prevent — an upgrade nobody chose, arriving
    between two `up -d`s. `main` IS published, deliberately: it is the tracked compose default, so
    a contributor who has written no `.env.compose` gets the branch they are working on. The
    difference is that no INSTALL ever writes `main` into a file — `install.sh` writes an explicit
    version, which is what makes the default safe to leave floating."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    meta = next(s for s in workflow["jobs"]["images"]["steps"]
                if "metadata-action" in str(s.get("uses", "")))

    assert "latest" not in str(meta["with"]["tags"]), (
        "release.yml publishes a `latest` tag — the one tag a user can pin to and still be moved")


def test_a_push_to_main_publishes_images_but_cuts_no_release():
    """A GitHub Release per commit is a release list nobody reads, and `install.sh` resolves a
    pinned tag out of that list. The images still have to be published on `main`, or the tracked
    compose default `${OPENFACTORY_VERSION:-main}` names something that does not exist."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML reads a bare `on:` key as the boolean True — YAML 1.1's Norway problem, in the one
    # place it actually bites a CI file. Asked for both spellings so this reads what is there.
    triggers = workflow.get("on") or workflow.get(True)

    assert "main" in triggers["push"]["branches"], triggers
    assert any(pattern.startswith("v") for pattern in triggers["push"]["tags"]), triggers

    guard = str(workflow["jobs"]["release"].get("if", ""))
    assert "refs/tags/v" in guard, (
        f"the release job's condition is {guard!r} — every push to main would cut a GitHub Release")


def test_the_release_attaches_what_a_pinned_install_downloads():
    """`install.sh` fetches `docker-compose.yml` and `.env.compose.example` from
    `releases/download/<tag>/` and verifies them against `SHA256SUMS`. An asset list that lost one
    of them leaves the installer fetching a 404 and, worse, a SHA256SUMS that still verifies —
    `--ignore-missing` passes over a file that is not there."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    collect = next(s for s in workflow["jobs"]["release"]["steps"]
                   if "SHA256SUMS" in str(s.get("run", "")))
    script = str(collect["run"])

    for asset in ("docker-compose.yml", ".env.compose.example"):
        assert asset in script, f"the release does not attach {asset}, which install.sh downloads"
    assert "sha256sum" in script, "nothing computes SHA256SUMS, so the installer verifies nothing"

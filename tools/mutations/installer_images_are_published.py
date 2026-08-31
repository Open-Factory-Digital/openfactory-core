"""P0.2 — the images the distribution references and the ones it publishes are one set.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_images_are_published.py

Nine cuts. The first two are the pair the guard exists for and they fail at opposite ends: an
image referenced and not published fails at the USER, on `docker compose up -d`, with `manifest
unknown` for a tag nothing ever pushed; an image published and not referenced fails at the
MAINTAINER, silently, by being built and attested on every tag while nobody pulls it and nobody
notices it break.

The rest are the ways a workflow that still looks right stops doing its job: one architecture, a
`latest` tag somebody can pin to, a Release cut on every commit to main, an asset the installer
downloads and the release stopped attaching, and the local base layer whose absence reads as a
missing credential rather than a missing step.
"""

TEST = "tests/test_every_image_the_compose_file_names_is_one_the_release_builds.py"

WORKFLOW = ".github/workflows/release.yml"
COMPOSE = "docker-compose.yml"

_CLI_ROW = ("          - image: openfactory-cli\n"
            "            dockerfile: docker/cli.Dockerfile")

MUTATIONS = [
    # ── the two directions ──────────────────────────────────────────────────────────────────────
    ("the cli image is referenced and no longer published — `manifest unknown` at the user",
     WORKFLOW, _CLI_ROW, ""),

    ("an image is published that nothing references — built, cached and attested for nobody",
     WORKFLOW, _CLI_ROW,
     _CLI_ROW + "\n          - image: openfactory-panel\n"
                "            dockerfile: docker/worker.Dockerfile"),

    ("the compose file stops naming the published cli image, so the release publishes an orphan",
     COMPOSE,
     "    image: ghcr.io/open-factory-digital/openfactory-cli:${OPENFACTORY_VERSION:-main}",
     "    image: openfactory-cli:local"),

    # ── a matrix row that points nowhere ────────────────────────────────────────────────────────
    ("a matrix row names a Dockerfile this tree does not have — half a release, twenty minutes in",
     WORKFLOW,
     "            dockerfile: docker/sandbox.Dockerfile",
     "            dockerfile: docker/sandbox-image.Dockerfile"),

    # ── the properties a workflow loses without looking wrong ───────────────────────────────────
    # ANCHORED ON THE BASE JOB. `platforms:` stopped being unique when the base got a job of its
    # own, and for the base the property is load-bearing rather than tidy: the sandbox is built
    # FROM it, so an amd64-only base makes the arm64 sandbox unbuildable.
    ("only amd64 is published, so every Apple Silicon install runs under emulation",
     WORKFLOW,
     "          file: docker/base-python.Dockerfile\n          platforms: linux/amd64,linux/arm64",
     "          file: docker/base-python.Dockerfile\n          platforms: linux/amd64"),

    # ANCHORED ON THE BASE JOB, because `type=ref,event=branch` stopped being unique the moment a
    # second job started tagging an image (2026-08-31). The runner refused the ambiguity rather
    # than mutating whichever came first — and the guard it proves now reads every job, which is
    # the gap the ambiguity was pointing at.
    ("a `latest` tag appears — the one moving tag a user can pin to",
     WORKFLOW,
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n"
     "            type=ref,event=branch",
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base\n          tags: |\n"
     "            type=raw,value=latest\n            type=ref,event=branch"),

    # THE ANCHOR CARRIES ITS COMMENT, and it has to. Written as the bare `if:` line it matched
    # ONCE — and then P0.5 added the `pypi` job, guarded by the identical condition, and this plan
    # refused to start with `anchor matches 2x` (2026-08-31). That refusal is the runner working:
    # a `replace(old, new, 1)` would have mutated whichever job came first and proved something
    # about a line nobody chose.
    ("every push to main cuts a GitHub Release, and install.sh resolves a pinned tag out of that list",
     WORKFLOW,
     "    # and `install.sh` resolves a pinned tag out of it.\n"
     "    if: startsWith(github.ref, 'refs/tags/v')",
     "    # and `install.sh` resolves a pinned tag out of it.\n"
     "    if: always()"),

    # ── the assets a pinned install downloads ───────────────────────────────────────────────────
    ("the release stops attaching .env.compose.example, which the installer fetches",
     WORKFLOW,
     "          cp docker-compose.yml .env.compose.example dist/",
     "          cp docker-compose.yml dist/"),

    # ── the local layer the sandbox is built FROM ───────────────────────────────────────────────
    # RE-AIMED 2026-08-31. The step this cut targeted — a hand-rolled `buildx --load` of the base
    # inside the sandbox row — is deleted: it could never have worked, because the docker-container
    # driver cannot read the daemon's image store it loaded into. The base is a published job now,
    # so the equivalent cut points that job at the wrong Dockerfile.
    ("the base job builds the wrong Dockerfile, so the sandbox is built on something else",
     WORKFLOW,
     "          file: docker/base-python.Dockerfile",
     "          file: docker/worker.Dockerfile"),
]

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
    ("only amd64 is published, so every Apple Silicon install runs under emulation",
     WORKFLOW,
     "          platforms: linux/amd64,linux/arm64",
     "          platforms: linux/amd64"),

    ("a `latest` tag appears — the one moving tag a user can pin to",
     WORKFLOW,
     "            type=ref,event=branch",
     "            type=ref,event=branch\n            type=raw,value=latest"),

    ("every push to main cuts a GitHub Release, and install.sh resolves a pinned tag out of that list",
     WORKFLOW,
     "    if: startsWith(github.ref, 'refs/tags/v')",
     "    if: always()"),

    # ── the assets a pinned install downloads ───────────────────────────────────────────────────
    ("the release stops attaching .env.compose.example, which the installer fetches",
     WORKFLOW,
     "          cp docker-compose.yml .env.compose.example dist/",
     "          cp docker-compose.yml dist/"),

    # ── the local layer the sandbox is built FROM ───────────────────────────────────────────────
    ("the base layer step builds the wrong file, so the sandbox fails on `pull access denied`",
     WORKFLOW,
     "              --file docker/base-python.Dockerfile \\",
     "              --file docker/worker.Dockerfile \\"),
]

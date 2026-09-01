"""Task D — every `FROM` the release builds resolves without the local daemon's image store.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_every_FROM_resolves.py

THE FIRST CUT IS THE v0.1.0 FAILURE, RESTORED. It puts `FROM openfactory-python:latest` back into
`docker/sandbox.Dockerfile` — the literal line that published two images, failed the third, cut no
GitHub Release, and left `install.sh` unable to resolve a pinned tag, ten minutes into the first
public release this project ever ran (run 33396474816, 2026-08-31). The whole point of Task D is
that this line now costs a red suite on a laptop instead of a red release in front of strangers, so
the cut has to be exactly that line and it has to go red.

The rest are the ways the same class arrives wearing different clothes: our own image named without
its registry under any other spelling, a base nothing publishes, a `FROM` whose ARG lost its
default (empty string for everyone who does not pass a build-arg), and the two blindnesses that
made the ORIGINAL guard useless — a `FROM` in a comment, and a stage name mistaken for an image.
"""

TEST = "tests/test_every_FROM_the_release_builds_resolves_without_the_local_daemon.py"

SANDBOX = "docker/sandbox.Dockerfile"
COMPOSE = "docker-compose.yml"
WORKFLOW = ".github/workflows/release.yml"
OSS_TEST = "tests/test_the_oss_distribution.py"
RELEASE_TEST = "tests/test_every_image_the_compose_file_names_is_one_the_release_builds.py"

MUTATIONS = [
    # ── the incident itself ─────────────────────────────────────────────────────────────────────
    ("THE v0.1.0 FAILURE: the sandbox is built FROM an unqualified name we produce ourselves",
     SANDBOX,
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main\n"
     "FROM ${OPENFACTORY_BASE_IMAGE}",
     "FROM openfactory-python:latest"),

    ("the same defect under the name the base is published as, minus its registry",
     SANDBOX,
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main",
     "ARG OPENFACTORY_BASE_IMAGE=openfactory-base:main"),

    # ── the ARG mechanism breaking quietly ──────────────────────────────────────────────────────
    ("the ARG loses its default, so a plain `docker build` resolves the FROM to nothing",
     SANDBOX,
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main",
     "ARG OPENFACTORY_BASE_IMAGE"),

    # ── a registry reference nothing publishes ──────────────────────────────────────────────────
    ("the base is named with a registry that no job in the release pushes to it",
     SANDBOX,
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main",
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-baselayer:main"),

    ("the release stops publishing the base the sandbox is built on",
     WORKFLOW,
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-base",
     "          images: ${{ env.REGISTRY }}/${{ env.ORG }}/openfactory-baselayer"),

    # ── the ordering that makes the registry reference true ─────────────────────────────────────
    ("the sandbox no longer waits for the base to be pushed, so the two race",
     WORKFLOW,
     "    needs: base_image\n    runs-on: ubuntu-latest",
     "    runs-on: ubuntu-latest",
     RELEASE_TEST),

    ("the sandbox is built on whatever `main` is, inside a tagged release",
     WORKFLOW,
     "              OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:"
     "${{ github.ref_name }}",
     "              OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main",
     RELEASE_TEST),

    # ── the contributor's build-order edge ──────────────────────────────────────────────────────
    #
    # `docker compose build` compiles ONE bake plan and builds every target concurrently;
    # `depends_on` orders container startup and says nothing about builds. Without the named
    # context the sandbox resolves its FROM while the base is still building and reaches for the
    # registry — measured on a clean daemon, `403 Forbidden` fetching an anonymous pull token.
    ("compose loses the build-order edge, so the contributor's sandbox races its own base",
     COMPOSE,
     "      additional_contexts:\n        openfactory-base: \"service:base-image\"\n"
     "      args:\n        OPENFACTORY_BASE_IMAGE: openfactory-base",
     "      args:\n        OPENFACTORY_BASE_IMAGE: "
     "ghcr.io/open-factory-digital/openfactory-base:${OPENFACTORY_VERSION:-main}"),

    # ── the two blindnesses that made the ORIGINAL guard certify the defect ─────────────────────
    ("the sandbox stops inheriting our base, and the exemption from the CA block expires with it",
     SANDBOX,
     "ARG OPENFACTORY_BASE_IMAGE=ghcr.io/open-factory-digital/openfactory-base:main",
     "ARG OPENFACTORY_BASE_IMAGE=python:3.12-slim",
     OSS_TEST),

    ("the base stops carrying the trust store the sandbox is exempt because it inherits",
     "docker/base-python.Dockerfile",
     "COPY docker/extra-ca/ /tmp/extra-ca/",
     "COPY README.md /tmp/not-a-certificate",
     OSS_TEST),
]

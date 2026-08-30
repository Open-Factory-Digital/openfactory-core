"""P0.1 — one compose file installs AND builds, and every way it can rot is red.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_one_compose_file.py

Seven cuts, one per property the guard claims. The fourth is the one worth reading: it puts back
the `depends_on: sandbox-image` row the worker carried until 2026-08-30, which looks like the safe
and conservative thing to keep and which makes `docker compose up -d` — the single command the
whole one-line install rests on — refuse the project outright.
"""

TEST = "tests/test_the_compose_file_can_be_installed_and_built_from_one_file.py"

COMPOSE = "docker-compose.yml"

MUTATIONS = [
    # ── a build with no name to build INTO ──────────────────────────────────────────────────────
    ("the worker builds to a name compose invented, so nothing can pull it",
     COMPOSE,
     "    image: ghcr.io/open-factory-digital/openfactory-worker:${OPENFACTORY_VERSION:-main}\n"
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/worker.Dockerfile\n"
     "      args:\n"
     "        # Passed from",
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/worker.Dockerfile\n"
     "      args:\n"
     "        # Passed from"),

    # ── a tag the deployment cannot choose ──────────────────────────────────────────────────────
    ("the panel is nailed to `main`, so the version the installer pinned is ignored",
     COMPOSE,
     "    image: ghcr.io/open-factory-digital/openfactory-worker:${OPENFACTORY_VERSION:-main}\n"
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/worker.Dockerfile\n"
     "      args:\n"
     "        # The panel builds",
     "    image: ghcr.io/open-factory-digital/openfactory-worker:main\n"
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/worker.Dockerfile\n"
     "      args:\n"
     "        # The panel builds"),

    # ── the build-only services, both directions of the iff ─────────────────────────────────────
    ("the box image loses its profile, so the installer's `up -d` builds a multi-GB image again",
     COMPOSE,
     "    profiles: [\"build\"]\n"
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/sandbox.Dockerfile",
     "    build:\n"
     "      context: .\n"
     "      dockerfile: docker/sandbox.Dockerfile"),

    ("the panel — a service the stack RUNS — is hidden behind the build profile",
     COMPOSE,
     "  panel:\n    # THE WORKER'S IMAGE",
     "  panel:\n    profiles: [\"build\"]\n    # THE WORKER'S IMAGE"),

    # ── the refusal that is a total outage rather than a slow install ───────────────────────────
    ("the worker depends on a profiled service again — `docker compose up -d` refuses the project",
     COMPOSE,
     "    depends_on:\n      temporal: {condition: service_healthy}",
     "    depends_on:\n      temporal: {condition: service_healthy}\n"
     "      sandbox-image: {condition: service_completed_successfully}"),

    # ── the two names that are connected by nothing but agreement ───────────────────────────────
    ("the worker launches a box image the build never tags — dies at the first ticket",
     COMPOSE,
     "      OPENFACTORY_SANDBOX_IMAGE: ghcr.io/open-factory-digital/openfactory-sandbox:"
     "${OPENFACTORY_VERSION:-main}",
     "      OPENFACTORY_SANDBOX_IMAGE: openfactory-python:sandbox"),

    # ── the exemption stops being earned ────────────────────────────────────────────────────────
    ("the base image is renamed, so no Dockerfile builds FROM it and it is a distributed image "
     "nothing publishes",
     COMPOSE,
     "    image: openfactory-python:latest\n    command: [\"true\"]",
     "    image: openfactory-base:latest\n    command: [\"true\"]"),
]

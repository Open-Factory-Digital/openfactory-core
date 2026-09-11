"""P0.3 — the box image the worker spawns is one the install actually puts on the daemon.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_box_image_is_pulled.py

Every cut here produces the SAME symptom, and that is the point: a flawless install — every
container healthy, the panel serving, `docker compose ps` clean — and then the first ticket dies on
`image not found`. Hours later, one layer away from its cause, against an image the compose file
names and the release publishes.

The first cut is the one that would really happen. `install.sh` pulls the box image on a line of
its own, and that line looks redundant beside `docker compose up -d` — until you notice that
`sandbox-image` is behind the `build` profile and compose therefore neither builds nor fetches it,
and that the worker launches it on the HOST daemon as a sibling container rather than through
compose at all.
"""

TEST = "tests/test_the_box_image_the_worker_spawns_is_one_the_install_pulls.py"

SH = "install.sh"
COMPOSE = "docker-compose.yml"
WORKFLOW = ".github/workflows/release.yml"

MUTATIONS = [
    # RE-AIMED 2026-09-04 for the same reason as the row below: the pulls are chained now.
    ("the explicit box-image pull is dropped as redundant beside `up -d`",
     SH,
     ' \\\n            && docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1',
     ""),

    # RE-AIMED 2026-09-04: the two background pulls are chained with `&&` now, because a subshell
    # reports only its last command and a failed WORKER pull was exiting 0.
    ("the box image is pulled at a different version from the worker beside it",
     SH,
     '            && docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1',
     '            && docker pull --quiet "${REGISTRY}/openfactory-sandbox:main" >/dev/null 2>&1'),

    ("the worker launches an image the build never tags",
     COMPOSE,
     "      OPENFACTORY_SANDBOX_IMAGE: ghcr.io/open-factory-digital/openfactory-sandbox:"
     "${OPENFACTORY_VERSION:-main}",
     "      OPENFACTORY_SANDBOX_IMAGE: ghcr.io/open-factory-digital/openfactory-box:"
     "${OPENFACTORY_VERSION:-main}"),

    ("the box image stops being pinned to the deployment's version",
     COMPOSE,
     "      OPENFACTORY_SANDBOX_IMAGE: ghcr.io/open-factory-digital/openfactory-sandbox:"
     "${OPENFACTORY_VERSION:-main}",
     "      OPENFACTORY_SANDBOX_IMAGE: ghcr.io/open-factory-digital/openfactory-sandbox:main"),

    ("the release stops publishing the box image the install pulls",
     WORKFLOW,
     "          - image: openfactory-sandbox\n            dockerfile: docker/sandbox.Dockerfile",
     "          - image: openfactory-boxes\n            dockerfile: docker/sandbox.Dockerfile"),

    ("preflight stops naming `docker pull` as the way to get the image",
     "openfactory/preflight.py",
     'f"docker pull {image}   (the worker launches it as a SIBLING container on this daemon, so "',
     'f"ask your administrator about {image} "'),

    # ── the v0.1.5 run: named at preflight, then declared a success ─────────────────────────────
    ("the box image is never re-checked, so a silently failed pull is declared a good install",
     SH,
     "    confirm_the_box_image\n",
     ""),

    ("the confirmation happens after the stack has started, too late to be cheap",
     SH,
     "    wait_for_images\n    confirm_the_box_image\n",
     "    wait_for_images\n"),

    ("the two background pulls become separate statements, so a failed worker pull exits 0",
     SH,
     '        docker pull --quiet "${REGISTRY}/openfactory-worker:${VERSION}" >/dev/null 2>&1 \\\n'
     '            && docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1',
     '        docker pull --quiet "${REGISTRY}/openfactory-worker:${VERSION}" >/dev/null 2>&1\n'
     '        docker pull --quiet "${REGISTRY}/openfactory-sandbox:${VERSION}" >/dev/null 2>&1'),

    # THE PREMISE ITSELF. If `sandbox-image` left the build profile, `up -d` would fetch the image
    # and the explicit pull would genuinely be redundant — but `worker` would then be a
    # profile-less service depending on… nothing, and the real hazard would have moved. The guard
    # says so rather than going on asserting a line whose reason had vanished.
    ("the build profile is dropped, so the premise this whole file rests on is gone",
     COMPOSE,
     "    profiles: [\"build\"]\n    build:\n      context: .\n"
     "      dockerfile: docker/sandbox.Dockerfile",
     "    build:\n      context: .\n      dockerfile: docker/sandbox.Dockerfile"),
]

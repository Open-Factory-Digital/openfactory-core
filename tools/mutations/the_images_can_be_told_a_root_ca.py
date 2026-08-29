"""The two corporate-network knobs, and the four ways the first cut of them looked right.

`docker/extra-ca/` and `DEBIAN_MIRROR` are both no-ops in this repository, which is the property
that makes them safe to ship and also the property that makes them easy to break silently: a
knob that does nothing by default goes on doing nothing when it is wired wrong.

THREE OF THESE SIX ARE MISTAKES THAT WERE ACTUALLY MADE, not hypotheticals — the npmrc that
`--prefix` moves out from under, the guard satisfied by the comment quoting the bug, and the
hand-kept service list that forgot the panel.
"""

TEST = "tests/test_the_oss_distribution.py"

MUTATIONS = [
    # ── node learns the CA by the one route a caller cannot move ────────────────────────────────
    ("the CA reaches node through prose instead of an instruction — the shape that passed twice",
     "docker/base-python.Dockerfile",
     "ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt",
     "# ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt"),

    ("the file NODE_EXTRA_CA_CERTS names is created only when a certificate was supplied, so the "
     "public build warns on every node invocation",
     "docker/base-python.Dockerfile",
     "    : > /usr/local/share/openfactory/extra-ca.crt; \\",
     "    true; \\"),

    # ── the root is trusted before anything that needs it ───────────────────────────────────────
    ("the image fetches from the network with no way to be told a root",
     "docker/base-python.Dockerfile",
     "COPY docker/extra-ca/ /tmp/extra-ca/",
     "# COPY docker/extra-ca/ /tmp/extra-ca/"),

    # ── apt can be pointed somewhere reachable, and only when asked ─────────────────────────────
    ("apt cannot be pointed anywhere, so a throttled port 80 is fixable only by editing this repo",
     "docker/base-python.Dockerfile",
     'ARG DEBIAN_MIRROR=""',
     '# ARG DEBIAN_MIRROR=""'),

    ("the rewrite runs unconditionally, so leaving the mirror empty is no longer a no-op",
     "docker/base-python.Dockerfile",
     '    if [ -n "${DEBIAN_MIRROR}" ]; then \\',
     "    if true; then \\"),

    # ── which services need the arg is derived, never remembered ────────────────────────────────
    ("the panel builds from the worker's Dockerfile and is not given the mirror — the exact row "
     "a hand-kept service list left out",
     "docker-compose.yml",
     "        # while the worker's was still running — a service list written by hand instead of "
     "derived.\n"
     '        DEBIAN_MIRROR: "${DEBIAN_MIRROR:-}"',
     "        # while the worker's was still running — a service list written by hand instead of "
     "derived."),
]

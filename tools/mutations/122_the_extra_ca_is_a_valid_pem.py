"""#122: the file `NODE_EXTRA_CA_CERTS` names is always a PEM, never an empty file.

THE FIRST ROW IS THE SHIPPED DEFECT RESTORED. It went out on the published v0.2.0 images and no
guard saw it, because the only thing describing the behaviour was a comment asserting the opposite
— which is why this plan's guard EXECUTES the block instead of reading it.

The reverse matters as much: a deployment behind an inspecting proxy drops a `.crt` in
`docker/extra-ca/` and needs it TRUSTED. A fix that made the file always the system store and
nothing else would be silent, green, and would break exactly the customers the mechanism exists
for.
"""

TEST = "tests/test_the_extra_ca_file_is_always_a_valid_pem.py"
BASE = "docker/base-python.Dockerfile"
WORKER = "docker/worker.Dockerfile"

_COPY = "      cp /etc/ssl/certs/ca-certificates.crt /usr/local/share/openfactory/extra-ca.crt; \\"

MUTATIONS = [
    # ── the shipped defect, one image at a time ────────────────────────────────────────────────
    ("base-python leaves the file empty again, as v0.2.0 shipped it", BASE,
     _COPY + "\n", ""),

    # NO WORKER-SPECIFIC ROW, and the reason is the runner's own rule rather than an oversight:
    # `worker.Dockerfile` carries the block TWICE, byte for byte (two stages), so no anchor inside
    # it can match exactly once. The guard still measures both — it iterates every RUN block in
    # every file — and the row below cuts the identical shape in `base-python.Dockerfile`, which
    # the worker's stages are copies of. Coverage is real; only the cut cannot be aimed.

    # ── the reverse: the supplied certificate must still reach the file ───────────────────────
    ("…and the reverse: an extra certificate is dropped and the system store wins everywhere",
     BASE,
     "      cat /etc/ssl/certs/ca-certificates.crt /tmp/extra-ca/*.crt \\\n"
     "        > /usr/local/share/openfactory/extra-ca.crt; \\",
     "      cp /etc/ssl/certs/ca-certificates.crt /usr/local/share/openfactory/extra-ca.crt; \\"),

    # REVIEW OF #124. The guard agreed with the CODE rather than with the comment, and the comment
    # was the thing this whole change is about. Extras-only is correct only if the harness runtime
    # extends its roots — an assumption measured with node, which is the divergence that caused
    # this PR. Cut the store away and an enterprise behind a proxy trusts the corp CA alone.
    ("the supplied-certificate branch writes the extras alone, costing the system roots", BASE,
     "      cat /etc/ssl/certs/ca-certificates.crt /tmp/extra-ca/*.crt \\\n"
     "        > /usr/local/share/openfactory/extra-ca.crt; \\",
     "      cat /tmp/extra-ca/*.crt > /usr/local/share/openfactory/extra-ca.crt; \\"),

    # ── the two halves of the claim, forty lines apart ────────────────────────────────────────
    ("the ENV stops naming the file every block writes", BASE,
     "ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt",
     "ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/somewhere-else.crt"),

    ("the cli image quietly acquires the variable with nobody measuring its file",
     "docker/cli.Dockerfile",
     "COPY docker/extra-ca/ /tmp/extra-ca/",
     "ENV NODE_EXTRA_CA_CERTS=/usr/local/share/openfactory/extra-ca.crt\nCOPY docker/extra-ca/ /tmp/extra-ca/"),
]

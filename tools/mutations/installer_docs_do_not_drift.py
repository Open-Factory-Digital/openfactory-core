"""P1.3 — the README's install block, and the guards that keep it true.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_docs_do_not_drift.py

Two families.

THE UN-PIPED EQUIVALENT is the "read it first" row's promise made concrete, and it rots in both
directions: a step dropped from the README leaves a reader with a different install from everybody
else, and a step dropped from the SCRIPT leaves the README teaching a previous version. Both
directions are cut, because only one of them is the one people expect.

THE IMAGE/PACKAGE DISTINCTION is the R4 rewrite. An image reference is not a package name, and the
old sweep could not tell them apart — the moment the README named a `ghcr.io/…` image, two of them
became "add-on packages docs/STATUS.md does not list" and CI went red over a correct change. The
fix strips references and judges them by a STRONGER rule (a workflow builds it), so the cuts have
to show both halves working: a stray package name is still caught, and an image nothing publishes
is caught too.
"""

TEST = "tests/test_the_install_line_the_readme_prints_is_the_url_the_release_publishes_to.py"

README = "README.md"
SH = "install.sh"
CUT_TEST = "tests/test_the_public_cut_is_written_down.py"

MUTATIONS = [
    # ── the headline itself ─────────────────────────────────────────────────────────────────────
    ("the one-liner points at a file this repository does not track",
     README,
     "curl -fsSL https://openfactory.digital/install.sh | sh",
     "curl -fsSL https://openfactory.digital/setup.sh | sh"),

    ("a pinned asset is fetched from the domain, which can checksum nothing",
     README,
     "curl -fsSL $REPO/releases/download/$VERSION/docker-compose.yml -o docker-compose.yml",
     "curl -fsSL https://openfactory.digital/v0.1.0/docker-compose.yml -o docker-compose.yml"),

    # ── the un-piped block loses a step ─────────────────────────────────────────────────────────
    ("the un-piped block stops verifying the checksums",
     README,
     "curl -fsSL $REPO/releases/download/$VERSION/SHA256SUMS | sha256sum -c --ignore-missing\n",
     ""),

    ("the un-piped block stops pinning the version, so it installs from a moving tag",
     README,
     'echo "OPENFACTORY_VERSION=$VERSION" >> .env.compose\n',
     ""),

    ("the un-piped block stops pulling the box image `up -d` will not fetch",
     README,
     "docker pull ghcr.io/open-factory-digital/openfactory-sandbox:$VERSION\n",
     ""),

    ("the un-piped block runs `init` as root, so the 0600 file belongs to nobody usable",
     README,
     'docker run --rm -it -v "$PWD:/out" -u "$(id -u):$(id -g)" \\',
     'docker run --rm -it -v "$PWD:/out" \\'),

    ("the un-piped block hard-codes a release tag — a version number with a second home",
     README,
     "VERSION=$(curl -fsSLI -o /dev/null -w '%{url_effective}' $REPO/releases/latest); "
     "VERSION=${VERSION##*/tag/}",
     "VERSION=v0.1.0"),

    # ── the other direction: the script stops doing what the README teaches ─────────────────────
    ("the script stops pinning the version while the README still teaches it",
     SH,
     "        printf 'OPENFACTORY_VERSION=%s\\n' \"$VERSION\" >> \"$DIR/.env.compose\"",
     "        :"),

    ("the script stops running init as the invoking user while the README still teaches it",
     SH,
     '        -u "$(id -u):$(id -g)" \\\n',
     ""),

    # ── image references are not package names, and are judged more strictly ────────────────────
    ("the README names an image no workflow builds",
     README,
     "docker pull ghcr.io/open-factory-digital/openfactory-sandbox:$VERSION",
     "docker pull ghcr.io/open-factory-digital/openfactory-boxes:$VERSION",
     CUT_TEST),

    ("a genuine stray PACKAGE name survives the image stripping and is still caught",
     README,
     "## Install\n",
     "## Install\n\nSee the openfactory-nowhere package.\n",
     CUT_TEST),
]

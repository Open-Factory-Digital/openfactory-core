"""P0.5 — the wheel is published under the name the documents tell you to install.

Run:  .venv/bin/python tools/mutate.py tools/mutations/installer_the_wheel_is_published.py

Six cuts. The third and fourth are the pair worth reading: PyPI accepts any version that does not
already exist, so a tag that disagrees with `project.version` does not FAIL — it publishes this
code under a number nobody chose, and a wrong version on PyPI can be yanked but never replaced.
The check has to exist and it has to run before `python -m build`, so both are cut separately.
"""

TEST = "tests/test_the_wheel_is_published_under_the_name_the_docs_tell_you_to_install.py"

WORKFLOW = ".github/workflows/release.yml"

_CHECK_STEP = """      - name: the tag and the package version agree
        run: |
          set -euo pipefail
          tagged="${GITHUB_REF_NAME#v}"
          declared=$(python -c 'import tomllib,pathlib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')
          if [ "$tagged" != "$declared" ]; then
            echo "tag ${GITHUB_REF_NAME} says version ${tagged}; pyproject.toml says ${declared}." >&2
            echo "Set project.version to ${tagged} and re-tag — a version published under the" >&2
            echo "wrong number cannot be replaced on PyPI, only yanked." >&2
            exit 1
          fi

"""

MUTATIONS = [
    ("the wheel is published on every push to main, spending a version number per commit",
     WORKFLOW,
     "  pypi:\n    if: startsWith(github.ref, 'refs/tags/v')",
     "  pypi:\n    if: always()"),

    ("the publish job loses its OIDC permission, so trusted publishing cannot mint a credential",
     WORKFLOW,
     "    permissions:\n      contents: read\n      id-token: write\n    steps:\n"
     "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5",
     "    permissions:\n      contents: read\n    steps:\n"
     "      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5"),

    ("a long-lived PyPI token is introduced — a secret that can publish the package",
     WORKFLOW,
     "        with:\n          attestations: true",
     "        with:\n          attestations: true\n          password: ${{ secrets.PYPI_API_TOKEN }}"),

    ("nothing reconciles the tag with project.version — the wrong number gets published for ever",
     WORKFLOW, _CHECK_STEP, ""),

    ("the tag/version check runs AFTER the build, so the refusal arrives with artefacts on disk",
     WORKFLOW,
     _CHECK_STEP + "      - run: python -m pip install --upgrade build\n"
                   "      - run: python -m build\n",
     "      - run: python -m pip install --upgrade build\n"
     "      - run: python -m build\n" + _CHECK_STEP),

    # ── the version has two homes and nothing held them equal ───────────────────────────────────
    # Found while cutting v0.1.0 (2026-08-31). `release.yml` reconciles the tag against
    # `pyproject.toml` and never reads `__init__.py`, so the second home could drift for ever
    # without a red run — a wheel labelled 0.1.0 by every packaging tool and answering 0.0.1 when
    # imported. Both directions are cut, because bumping one and forgetting the other is the
    # failure, and which one gets forgotten is a coin toss.
    ("the package's __version__ is left behind when pyproject.toml is bumped",
     "openfactory/__init__.py",
     '__version__ = "0.1.1"',
     '__version__ = "0.0.1"'),

    ("pyproject.toml is left behind when the package's __version__ is bumped",
     "pyproject.toml",
     'version = "0.1.1"',
     'version = "0.2.0"'),

    # ── the gate: v0.1.0 publishes images, not the wheel (2026-08-31) ───────────────────────────
    # A PyPI trusted publisher must be registered in a browser before the first upload and cannot
    # be created from CI. Ungated, this job dies inside `pypa/gh-action-pypi-publish` on the first
    # tag and turns the project's first public release run red for a reason no code caused.
    ("the publish is ungated, so the first tag dies on a publisher that does not exist",
     WORKFLOW,
     "    if: startsWith(github.ref, 'refs/tags/v') && vars.PYPI_TRUSTED_PUBLISHER == 'true'",
     "    if: startsWith(github.ref, 'refs/tags/v')"),

    ("the gate becomes a secret, so the state is invisible to everybody without admin",
     WORKFLOW,
     "    if: startsWith(github.ref, 'refs/tags/v') && vars.PYPI_TRUSTED_PUBLISHER == 'true'",
     "    if: startsWith(github.ref, 'refs/tags/v') && secrets.PYPI_TRUSTED_PUBLISHER == 'true'"),

    # THE THIRD STATE COLLAPSING. With both conditions identical, a tag whose gate is off runs
    # NEITHER job — and the release is silent about the wheel in a way indistinguishable from a
    # workflow that forgot it. This is the failure a bare `if: … == 'true'` with no twin gives.
    ("both jobs share one condition, so a disabled publish says nothing at all",
     WORKFLOW,
     "    if: startsWith(github.ref, 'refs/tags/v') && vars.PYPI_TRUSTED_PUBLISHER != 'true'",
     "    if: startsWith(github.ref, 'refs/tags/v') && vars.PYPI_TRUSTED_PUBLISHER == 'true'"),

    ("the announcement fires on every push to main, not only on a tag",
     WORKFLOW,
     "  pypi_not_enabled:\n    if: startsWith(github.ref, 'refs/tags/v') && "
     "vars.PYPI_TRUSTED_PUBLISHER != 'true'",
     "  pypi_not_enabled:\n    if: vars.PYPI_TRUSTED_PUBLISHER != 'true'"),

    ("a deliberately unpublished wheel fails the release run",
     WORKFLOW,
     '            "Then cut the next tag. Nothing in the code changes." \\',
     '            "Then cut the next tag. Nothing in the code changes." \\\n'
     '            ; exit 1 \\'),

    ("the announcement stops naming the variable a human would set",
     WORKFLOW,
     '            "       PYPI_TRUSTED_PUBLISHER = true" \\',
     '            "       (ask an admin)" \\'),

    ("the announcement stops naming the browser step nobody can infer from this repository",
     WORKFLOW,
     '            "  1. pypi.org -> Your projects -> Publishing -> Add a pending publisher" \\',
     '            "  1. enable publishing" \\'),

    ("the announcement is only in the log, where the person cutting the release will not look",
     WORKFLOW,
     '            | tee -a "$GITHUB_STEP_SUMMARY"',
     "            | cat"),

    ("the GitHub Release waits on the publish, so a disabled wheel cancels the assets too",
     WORKFLOW,
     "    needs: images",
     "    needs: [images, pypi]"),

    ("the release notes advertise a wheel this run declined to publish",
     WORKFLOW,
     "            Verify the assets below with `sha256sum -c SHA256SUMS --ignore-missing`.",
     "            Also on PyPI: `pip install openfactory`.\n\n"
     "            Verify the assets below with `sha256sum -c SHA256SUMS --ignore-missing`."),

    # ── nothing downstream may claim the wheel while the publish is gated ───────────────────────
    ("the README offers the core by name again while no index serves it",
     "README.md",
     "| **no script at all** | the four commands below |",
     "| **no script at all** | the four commands below |\n"
     "| **on your PATH** | `uv tool install openfactory` |",
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    # AIMED AT THE GATE DETECTION ITSELF. The first version of this row cut the same line and
    # SURVIVED — not because the guard was weak but because the cut had nothing to bite on: with
    # no document naming the core, ungating changes which names are forbidden and forbids nothing
    # either way. `test_a_publish_nobody_has_enabled_is_not_evidence…` asserts the fact rather
    # than its consequences, so the cut now lands.
    ("a gated publish is read as evidence that an index serves the core",
     WORKFLOW,
     "    if: startsWith(github.ref, 'refs/tags/v') && vars.PYPI_TRUSTED_PUBLISHER == 'true'",
     "    if: startsWith(github.ref, 'refs/tags/v')",
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    ("the publish environment points at another project's page",
     WORKFLOW,
     "      url: https://pypi.org/p/openfactory",
     "      url: https://pypi.org/p/openfactory-core"),

    # ── the premise the OTHER guard rests on ────────────────────────────────────────────────────
    #
    # `test_the_remedy_a_refusal_hands_you_can_be_followed.py` used to stand down entirely the day
    # anything here published — `pytest.skip`, by its own design. That would have retired it at
    # the exact moment its subject became the ONLY subject left: the core is served now, and the
    # add-on packages are still on no index. These two cuts prove the narrowed rule still bites,
    # and that it bites the right names.
    ("a document hands a reader the bare name of a package no index serves",
     "docs/writing-an-addon.md", "",
     "\n\nInstall it with `pip install openfactory-slack`.\n",
     "tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py"),

    ("the publish step disappears, so the core's own name stops being followable",
     WORKFLOW,
     "      - uses: pypa/gh-action-pypi-publish@release/v1\n        with:\n"
     "          attestations: true",
     "      - run: echo 'not publishing today'"),
]

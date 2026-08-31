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
     '__version__ = "0.1.0"',
     '__version__ = "0.0.1"'),

    ("pyproject.toml is left behind when the package's __version__ is bumped",
     "pyproject.toml",
     'version = "0.1.0"',
     'version = "0.2.0"'),

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

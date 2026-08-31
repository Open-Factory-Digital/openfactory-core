"""Nobody who runs the one-liner ends up on a tag that moves under them.

THE TWO DEFAULTS THAT LOOK ALIKE AND ARE OPPOSITE. `docker-compose.yml` reads
`${OPENFACTORY_VERSION:-main}`, and `main` is rebuilt on every push to `main` — which is exactly
right for a CONTRIBUTOR, who runs `docker compose up -d` in a checkout and wants the branch they
are working on. It is exactly wrong for an INSTALL: an upgrade nobody chose, arriving between two
`up -d`s, on a machine running somebody's factory. What makes the floating default safe is that
`install.sh` writes an explicit `OPENFACTORY_VERSION=vX.Y.Z` into `.env.compose`, so the two
readers of the same file get opposite and correct behaviour.

THAT LINE IS THE WHOLE MECHANISM, and it is one line. This file is what stops it being deleted as
redundant — which is precisely how it would look to somebody reading the compose file, where a
default is already present.

NO HARD-CODED TAG EITHER, and that is the second half. A version literal in `install.sh` would be a
second home for a number that already lives on the release, bumped by hand every time, and stale
the first time somebody forgets. The script resolves `releases/latest` to a CONCRETE tag by
following the redirect, and everything downstream — the assets, the three image pulls, the row it
writes — uses that one resolved value.
"""

from __future__ import annotations

import pathlib
import re

import installer_script
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = installer_script.SCRIPT


def _code_lines() -> list[str]:
    return [line for line in SCRIPT.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_the_installer_writes_the_version_into_the_environment_file():
    """THE line. Without it the install inherits the compose default, which moves."""
    assert re.search(r"OPENFACTORY_VERSION=%s|OPENFACTORY_VERSION=\$\{?VERSION", SCRIPT), (
        "install.sh never writes OPENFACTORY_VERSION into .env.compose — the install would "
        "inherit `${OPENFACTORY_VERSION:-main}` from docker-compose.yml and be moved by somebody "
        "else's push to main")

    writes = [line.strip() for line in _code_lines() if "OPENFACTORY_VERSION=" in line
              and (">>" in line or ">" in line)]
    assert writes, "the version is mentioned but never appended to the file"


def test_the_version_it_writes_is_the_one_it_installed():
    """A pin that names a different release from the one whose assets were downloaded is worse
    than no pin: the compose file and the images would come from two tags."""
    appends = [line for line in _code_lines()
               if "OPENFACTORY_VERSION=" in line and "printf" in line]
    assert appends, "the version row is not written with the resolved value"
    assert any('"$VERSION"' in line for line in appends), (
        f"the row is written from something other than the resolved version: {appends}")


@pytest.mark.parametrize("floating", ["latest", "main", "master", "edge", "nightly"])
def test_no_image_is_ever_pulled_at_a_floating_tag(floating):
    """Every `docker pull` in the script has to carry the resolved version. A single `:latest`
    here would pull an image that changes without anybody choosing it — and `release.yml`
    deliberately publishes no `latest` tag precisely so this cannot be done by accident."""
    offenders = [line.strip() for line in _code_lines()
                 if re.search(rf"(docker\s+(pull|run)|ghcr\.io)[^\n]*:{floating}\b", line)]

    assert not offenders, (
        f"install.sh uses the floating tag `{floating}`: {offenders}")


def test_every_image_reference_carries_the_resolved_version():
    """The positive twin of the four negatives above: not "no known floating tag", but "every
    reference is pinned". A tag nobody thought to blacklist fails this one."""
    references = [line.strip() for line in _code_lines() if "${REGISTRY}/" in line]
    assert len(references) >= 3, f"only {len(references)} image references — worker, sandbox, cli"

    for line in references:
        assert "${VERSION}" in line, (
            f"this image reference is not pinned to the resolved version: {line}")


def test_the_installer_hard_codes_no_release_tag_of_its_own():
    """A literal `v1.2.3` in this file is a second home for the release number: bumped by hand,
    and stale the first time somebody forgets. The tag is resolved, once, from the release."""
    offenders = [line.strip() for line in _code_lines()
                 if re.search(r"=\s*[\"']?v\d+\.\d+\.\d+", line)]

    assert not offenders, (
        f"install.sh carries a hard-coded release tag: {offenders}. Resolve it from "
        f"`releases/latest` instead, so there is one home for the number.")


def test_it_resolves_a_concrete_tag_rather_than_fetching_from_latest():
    """`releases/latest/download/…` would work and would be the trap: the assets would come from
    whatever the newest release is AT THE MOMENT OF EACH FETCH, so a release cut mid-install would
    hand somebody a compose file from one tag and images from another. The redirect is followed
    ONCE, to a concrete tag, and everything downstream uses it.

    READ THROUGH THE SCRIPT'S OWN VARIABLES (`installer_script.expand`). The first version of this
    test collected lines by pattern-matching their literal text, and a mutation that changed
    `base="${RELEASES}/download/${VERSION}"` to `base="${RELEASES}/latest/download"` — the exact
    defect it exists to catch — was not collected at all and survived green (2026-08-31)."""
    assert re.search(r"url_effective", SCRIPT), (
        "install.sh does not resolve the redirect from `releases/latest` to a concrete tag")

    # THE DECISION IS THE ASSIGNMENT, NOT THE `curl`. `curl "${base}/${asset}"` carries no version
    # and never will — what decides whether the assets are pinned is the one line that builds
    # `base`. Reading the property off the `curl` line accused a correct script twice while writing
    # this (2026-08-31); reading it off the assignment is where the choice is actually made.
    #
    # AND THE TWO HALVES ARE READ ON DIFFERENT TEXTS. The URL SHAPE is only visible after the
    # script's own variables are expanded; the VERSION REFERENCE only before, because `expand`
    # resolves `VERSION` to the shell expression that computes it (`${resolved##*/tag/}`) and the
    # name disappears.
    base = [line for line in _code_lines() if line.strip().startswith("base=")]
    assert len(base) == 1, f"expected one asset-base assignment, found {base}"
    raw, full = base[0], installer_script.expand(base[0])

    assert "releases/download" in full, (
        f"the asset base is not a release download path: {full.strip()}")
    assert "/latest/" not in full, (
        f"the assets are fetched through the moving `latest` path rather than the resolved tag — "
        f"a release cut mid-install would hand somebody a compose file from one tag and images "
        f"from another: {raw.strip()}")
    assert "VERSION" in raw, (
        f"the asset base does not carry the resolved version: {raw.strip()}")

    # `-o /dev/null` IS NOT A DOWNLOAD. That is the redirect probe — a HEAD request whose only
    # output is the effective URL — and it is the one `curl` in the script that is SUPPOSED to
    # touch `releases/latest`, because resolving it is how the concrete tag is learned.
    fetches = [line for line in _code_lines()
               if "curl" in line and "-o " in line and "-o /dev/null" not in line]
    assert fetches, "nothing downloads a release asset"
    for line in fetches:
        assert "${base}" in line, (
            f"an asset is downloaded from somewhere other than the pinned base: {line.strip()}")


def test_the_resolved_tag_is_refused_when_it_is_not_a_tag():
    """`${resolved##*/tag/}` on a URL that is not a release page yields the whole URL, and the
    install would go on to fetch `releases/download/https:/github.com/...`. A network that
    intercepts and redirects is exactly the environment where that happens, and the failure would
    be four steps later and unreadable."""
    assert re.search(r"case\s+\"\$VERSION\"", SCRIPT), (
        "install.sh does not check that what it resolved actually looks like a release tag")
    assert re.search(r"v\*\)", SCRIPT), "the check does not test for a `v`-prefixed tag"


def test_the_compose_default_stays_floating_because_a_contributor_needs_it_to():
    """The other half of the pair, asserted here so the two are read together. If somebody 'fixed'
    the compose default to a pinned tag, every contributor's `up -d` would silently run a release
    instead of their branch — and this file's whole argument would evaporate."""
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "${OPENFACTORY_VERSION:-main}" in compose, (
        "docker-compose.yml no longer defaults to `main` — a contributor running `up -d` would "
        "get a published release rather than the branch they are working on, and install.sh's "
        "explicit pin would stop being the thing that protects users")

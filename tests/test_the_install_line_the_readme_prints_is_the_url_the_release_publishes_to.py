"""The one line the README prints, and the un-piped block beside it, both stay true.

THE README'S FIRST COMMAND IS THE PRODUCT'S FRONT DOOR, and it is now a URL rather than a `git
clone` — which means it can be wrong in a way a clone never could: the string can be perfect while
the file it names is stale, missing, or served from somewhere nobody publishes to.

LOCAL AND OFFLINE, ALWAYS. This suite may never need DNS. "Your machine is not the reference" is
not a slogan here — a module that resolves something outside the clone at import time took the
whole suite down for fifteen days in 2026-08, and a guard that needs the network changes what a
fork and a laptop can even collect. So what is checked here is what one clone can know: the
one-liner's path is the file this repository tracks, the release attaches that file, and the
un-piped block is genuinely the same steps the script takes. Whether `openfactory.digital` is
serving the current bytes is a different question, answered by a network-marked check that SKIPS
at run time (P3.5), and it may never gate a laptop.

WHY THE UN-PIPED BLOCK IS GUARDED AT ALL. It is the "read it first" row's promise made concrete —
a person who does not want to pipe a URL into their shell is told, in the README, exactly what the
script would have done. The moment those diverge, that row becomes a lie, and it is the row read
by precisely the people least willing to be lied to.
"""

from __future__ import annotations

import pathlib
import re

import installer_script
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())

#: The domain the one-liner is served from. One home for the string, so the assertions below
#: cannot disagree with each other about what they are checking.
DOMAIN = "openfactory.digital"

_ONE_LINER = re.compile(r"curl\s+-fsSL\s+https://([^/\s]+)/(\S+?)\s*\|\s*sh")


def test_the_readme_prints_the_one_line_install():
    """It is the headline. A README that lost it would have lost the whole point of Phase 1."""
    assert _ONE_LINER.search(README), (
        "the README no longer carries `curl -fsSL https://…/install.sh | sh` — the one line the "
        "entire installer work exists to make true")


def test_the_one_liner_names_the_file_this_repository_actually_tracks():
    """The canonical `install.sh` lives HERE, in the core, where `make lint` shellchecks it and the
    suite guards it; the website carries a published COPY. So the path in the URL has to be the
    name of the tracked file — if the README ever pointed at `/setup.sh` or `/install`, the copy
    that gets published would be a file nobody reviews."""
    match = _ONE_LINER.search(README)
    host, path = match.group(1), match.group(2)

    assert host == DOMAIN, f"the one-liner is served from {host!r}, not {DOMAIN!r}"
    assert (ROOT / path).is_file(), (
        f"the README serves `{path}` and this repository tracks no such file — the published copy "
        f"would be something nobody here reviews")


def test_the_release_attaches_the_file_the_one_liner_serves():
    """The domain serves what a person TYPES; the release serves what is PINNED. Both carry
    `install.sh`, and the release's copy is the one with a checksum beside it — which is why the
    script fetches its versioned assets from the release and never from the domain."""
    path = _ONE_LINER.search(README).group(2)
    collect = next(s for s in WORKFLOW["jobs"]["release"]["steps"]
                   if "SHA256SUMS" in str(s.get("run", "")))

    assert path in str(collect["run"]), (
        f"release.yml does not attach `{path}` — the domain would be the only place it exists, on "
        f"a static host that can checksum nothing")


def test_the_readme_never_tells_anybody_to_fetch_a_pinned_asset_from_the_domain():
    """§8/C2, made structural. GitHub Pages serves static files and cannot checksum one, so every
    VERSIONED asset comes from the release. The domain carries exactly two stable paths — the two
    strings a person types — and a `openfactory.digital/v0.1.0/…` would be a second, unverifiable
    copy of the truth about this stack."""
    offenders = [line.strip() for line in README.splitlines()
                 if DOMAIN in line and re.search(r"docker-compose\.yml|SHA256SUMS|\.env\.compose",
                                                 line)]

    assert not offenders, (
        f"the README fetches a pinned asset from {DOMAIN}: {offenders}. Those come from the "
        f"release, which can checksum them.")


def test_an_html_meta_refresh_is_never_offered_as_the_way_to_serve_it():
    """WRITTEN DOWN AS FORBIDDEN because it is the shortcut that looks reasonable at 2 a.m. on
    launch day. GitHub Pages has no server-side redirects, so somebody reaches for a meta refresh —
    and `curl -fsSL … | sh` would then pipe an HTML document into a shell."""
    for rel in ("README.md", "docs/adr/0043-the-distribution-is-a-published-image.md"):
        text = (ROOT / rel).read_text()
        assert "meta http-equiv" not in text.lower(), (
            f"{rel} mentions a meta refresh — piping an HTML document into `sh` is what that "
            f"would do to every person who runs the headline command")


# ── the un-piped equivalent is the commands the script runs ────────────────────────────────────

def _un_piped_block() -> str:
    """The fenced block the README offers to somebody who will not pipe a URL into a shell."""
    anchor = README.index("the-un-piped-equivalent")
    block = README[anchor:]
    start = block.index("```bash") + len("```bash")
    return block[start:block.index("```", start)]


@pytest.mark.parametrize("step, why", [
    ("releases/download", "the assets come from the release, where they can be checksummed"),
    ("SHA256SUMS", "the download is verified — the whole reason it is not fetched from the domain"),
    ("openfactory-cli", "`init` runs in the small image, not on a host Python"),
    ("id -u", "the file it writes belongs to the person, not to root"),
    ("OPENFACTORY_VERSION=", "the install is pinned; the compose default is `main`"),
    ("openfactory-sandbox", "the box image is pulled by hand — `up -d` does not fetch it"),
    ("docker compose", "the stack is started"),
])
def test_the_unpiped_equivalent_is_the_commands_the_script_runs(step, why):
    """Every step the script takes has to appear in the block, or the "read it first" row promises
    a person an equivalent that leaves something out. The three easiest to drop are the last three
    — each looks like a detail and each is the reason a later thing works at all."""
    block = _un_piped_block()

    assert step in block, (
        f"the un-piped block omits `{step}` — {why}. install.sh does it, so a reader following the "
        f"README by hand ends up with a different install from everybody else.")


@pytest.mark.parametrize("step", [
    "releases/download", "SHA256SUMS", "openfactory-cli", "id -u", "openfactory-sandbox",
    # THE WRITE, NOT THE MENTION. `OPENFACTORY_VERSION=` alone is satisfied by the `grep -q
    # '^OPENFACTORY_VERSION='` that guards the append — so a mutation replacing the append itself
    # with `:` left the script pinning nothing and this guard green (2026-08-31). The format string
    # belongs to the line that actually writes the row.
    "OPENFACTORY_VERSION=%s",
])
def test_the_script_really_does_each_step_the_block_claims(step):
    """The other direction, and it is the one that rots. The block is prose and the script is code;
    a step REMOVED from the script leaves the README teaching something nothing does any more —
    the "read it first" row turned into a description of a previous version."""
    script = "\n".join(installer_script.expand(line) for line in installer_script.code_lines())

    assert step in script, (
        f"the README's un-piped block teaches `{step}` and install.sh no longer does it")


def test_the_block_never_pins_to_a_tag_typed_into_the_readme():
    """A `v0.1.0` in the README is a version number with a second home, bumped by hand on every
    release and stale the first time somebody forgets — and stale here means the un-piped path
    installs an old release while the one-liner installs the new one."""
    block = _un_piped_block()

    assert not re.search(r"\bv\d+\.\d+\.\d+\b", block), (
        "the un-piped block hard-codes a release tag. It resolves one, the way the script does.")
    assert ":latest" not in block, (
        "the un-piped block pulls `:latest`, which release.yml deliberately never publishes — the "
        "command would fail with `manifest unknown`")

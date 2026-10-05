"""A release's page tells how to install THAT release (#531).

MEASURED. On 2026-10-05 the page of v0.5.0-rc.1, the first release candidate, printed the one-line
install, `curl -fsSL https://openfactory.digital/install.sh | sh`. That line resolves the latest
FINAL release, and a candidate never is one (docs/RELEASING.md), so the page told its testers to
install v0.4.2. The release manager corrected it by hand.

The page's top is now written by `scripts/release-page-body.sh <tag>`, which the workflow runs and
this file runs for both kinds of tag:

  a final       the one-line install, and the upgrade by `--force`
  a candidate   its own installer with `--version`, the upgrade, the way back, and the wheel's
                exact version — and NOT the one-line install
  every tag     the three images published under it
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release-page-body.sh"
ONE_LINE = "curl -fsSL https://openfactory.digital/install.sh | sh"
ASSETS = "https://github.com/Open-Factory-Digital/openfactory-core/releases/download"


def _page(tag: str) -> str:
    done = subprocess.run(["sh", str(SCRIPT), tag], capture_output=True, text=True, check=True)
    return done.stdout


@pytest.mark.parametrize("tag, wheel", [("v0.5.0-rc.1", "0.5.0rc1"), ("v0.6.0-rc.12", "0.6.0rc12")])
def test_a_candidates_page_installs_the_candidate_by_name(tag, wheel):
    page = _page(tag)
    assert f"curl -fsSL {ASSETS}/{tag}/install.sh -o install.sh" in page, page
    assert f"sh install.sh --version {tag}\n" in page, page
    assert f"sh install.sh --version {tag} --dir <the installation's directory> --force" in page
    assert f"pip install openfactory=={wheel}" in page, page
    assert "pre-release" in page and "not rehearsed" in page, page
    assert ONE_LINE not in page, "a candidate's page tells its testers to install the last final"


def test_a_final_page_installs_with_the_one_line_install():
    page = _page("v0.5.0")
    assert ONE_LINE + "\n" in page, page
    assert "--force" in page, "the upgrade path is not on the page"
    assert "pre-release" not in page and "--version" not in page, page


@pytest.mark.parametrize("tag", ["v0.5.0-rc.1", "v0.5.0"])
def test_every_page_names_the_images_published_under_its_tag(tag):
    page = _page(tag)
    for image in ("worker", "sandbox", "cli"):
        assert f"`ghcr.io/open-factory-digital/openfactory-{image}:{tag}`" in page, page
    assert "sha256sum -c SHA256SUMS --ignore-missing" in page


def test_a_paragraph_on_the_page_is_one_line():
    """A release page renders a newline inside a paragraph as a line break."""
    for tag in ("v0.5.0-rc.1", "v0.5.0"):
        for block in _page(tag).split("```")[::2]:          # the prose, between the fences
            for paragraph in block.split("\n\n"):
                lines = [line for line in paragraph.strip().splitlines() if line]
                if lines and not lines[0].startswith(("#", "- ")):
                    assert len(lines) == 1, f"{tag}: a paragraph wrapped over lines: {lines}"


def test_something_that_is_not_a_version_tag_is_refused():
    done = subprocess.run(["sh", str(SCRIPT), "main"], capture_output=True, text=True)
    assert done.returncode == 2 and "is not a version tag" in done.stderr


def test_the_workflow_writes_the_page_with_the_script_and_publishes_it():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    steps = workflow["jobs"]["release"]["steps"]
    [write] = [s for s in steps if "release-page-body.sh" in str(s.get("run", ""))]
    assert write["env"]["TAG"] == "${{ github.ref_name }}"
    assert write["run"].strip() == 'sh scripts/release-page-body.sh "$TAG" > release-page.md'
    [publish] = [s for s in steps if str(s.get("uses", "")).startswith("softprops/action-gh-release")]
    assert publish["with"]["body_path"] == "release-page.md"
    assert "body" not in publish["with"], "a second, inline page that the script does not write"
    assert steps.index(write) < steps.index(publish)

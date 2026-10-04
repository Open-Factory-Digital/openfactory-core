"""A release candidate is published as a pre-release, and never becomes what `install.sh` installs.

docs/RELEASING.md tags a candidate `vX.Y.Z-rc.N` and publishes it like a release, so that it can be
installed by name and verified before the final tag. Two things make that safe, and both live in
files nothing else connects:

- **The GitHub release.** `install.sh` resolves `releases/latest` when no `--version` is given, and
  GitHub answers that with the newest release that is neither a draft nor a pre-release. The
  workflow's release step created every release as a final one, so the first candidate would have
  been every new installation's version.
- **The wheel.** PyPI and pip read `0.5.0-rc.1` (normalised `0.5.0rc1`) as a pre-release, which
  `pip install openfactory` skips. That holds only while the workflow's version check compares the
  tag with the package's own declaration, character for character.

And the process itself is reviewed like code: the agent that runs it is tracked, not ignored with
the rest of `.claude/`.
"""

from __future__ import annotations

import pathlib
import subprocess

import yaml
from packaging.version import Version

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

A_CANDIDATE = "contains(github.ref_name, '-')"


def _release_step() -> dict:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["release"]["steps"]
    [step] = [s for s in steps if str(s.get("uses", "")).startswith("softprops/action-gh-release")]
    return step["with"]


def test_a_hyphenated_tag_is_published_as_a_pre_release_and_never_as_latest():
    """`prerelease` and `make_latest` read the same condition, in opposite directions: a candidate
    is a pre-release and not Latest, and a final release is the other way round."""
    step = _release_step()

    assert step.get("prerelease") == "${{ " + A_CANDIDATE + " }}", step.get("prerelease")
    assert step.get("make_latest") == "${{ !" + A_CANDIDATE + " }}", step.get("make_latest")


def test_the_candidate_s_version_is_a_pre_release_to_pip():
    """The workflow compares the tag without its `v` with `pyproject.toml`'s version, verbatim, so
    the package declares `0.5.0-rc.1` for `v0.5.0-rc.1`. That string must be one packaging reads
    as a pre-release, below the final release it is a candidate for, or `pip install openfactory`
    would install it."""
    candidate = Version("0.5.0-rc.1")

    assert candidate.is_prerelease
    assert str(candidate) == "0.5.0rc1"
    assert candidate < Version("0.5.0")
    assert "tagged=\"${GITHUB_REF_NAME#v}\"" in WORKFLOW.read_text(), (
        "the version check no longer reads the tag the way docs/RELEASING.md tells the release "
        "manager to declare it")


def test_the_release_process_and_its_agent_are_tracked():
    """`.claude/` is local scratch and ignored, except the agents a maintainer runs on this
    repository: the release agent is how the process is replicated by whoever holds the role, so
    it is reviewed like the document it executes."""
    agent = ROOT / ".claude" / "agents" / "release-manager.md"

    assert agent.is_file()
    ignored = subprocess.run(["git", "check-ignore", "-q", str(agent)], cwd=ROOT, check=False)
    assert ignored.returncode == 1, "the release agent is ignored by git, so it can never be reviewed"
    assert "docs/RELEASING.md" in agent.read_text()
    assert (ROOT / "docs" / "RELEASING.md").is_file()

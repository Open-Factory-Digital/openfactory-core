"""A release candidate is published as a pre-release, and never becomes what `install.sh` installs.

docs/RELEASING.md tags a candidate `vx.y.z-rc.N` and publishes it like a release, so that it can be
installed by name and verified before the final tag. Two things make that safe, and both live in
files nothing else connects:

- **The GitHub release.** `install.sh` resolves `releases/latest` when no `--version` is given, and
  GitHub answers that with the newest release that is neither a draft nor a pre-release. The
  workflow's release step created every release as a final one, so the first candidate would have
  been every new installation's version.
- **The wheel.** PyPI and pip read `0.5.0-rc.1` (normalised `0.5.0rc1`) as a pre-release, which an
  install from the index by the bare name skips. That holds only while the workflow's version check compares the
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


def _image_tag_steps() -> list[dict]:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"].values()
    return [s["with"] for job in jobs for s in job.get("steps", [])
            if "metadata-action" in str(s.get("uses", ""))]


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


def test_a_candidate_s_images_are_published_under_its_own_tag_and_move_nothing():
    """`install.sh --version v0.5.0-rc.1` pulls `…:v0.5.0-rc.1`, and the sandbox is built FROM the
    base image under the same tag. `docker/metadata-action` discards a configured semver pattern
    for a pre-release, so the tag is published as the tag itself (`type=raw` on the ref), and the
    floating `1.2` / `1` are off for a hyphenated tag, so a candidate never moves them (review of
    #510). Every job that tags an image, the base included."""
    steps = _image_tag_steps()
    assert len(steps) >= 2, f"only {len(steps)} jobs tag an image"

    for meta in steps:
        tags = str(meta["tags"])
        assert ("type=raw,value=${{ github.ref_name }},"
                "enable=${{ startsWith(github.ref, 'refs/tags/') }}") in tags, meta["images"]
        assert "pattern=v{{version}}" not in tags, (
            f"{meta['images']}: a semver `v{{{{version}}}}` pattern is discarded for a candidate")
        for floating in ("{{major}}.{{minor}}", "{{major}}"):
            assert (f"type=semver,pattern={floating},enable=${{{{ !contains(github.ref_name, "
                    f"'-') }}}}") in tags, (meta["images"], floating)


def test_the_candidate_s_version_is_a_pre_release_to_pip():
    """The workflow compares the tag without its `v` with `pyproject.toml`'s version, verbatim, so
    the package declares `0.5.0-rc.1` for `v0.5.0-rc.1`. That string must be one packaging reads
    as a pre-release, below the final release it is a candidate for, or an install from the index
    by the bare name would pick it."""
    candidate = Version("0.5.0-rc.1")

    assert candidate.is_prerelease
    assert str(candidate) == "0.5.0rc1"
    assert candidate < Version("0.5.0")
    assert "tagged=\"${GITHUB_REF_NAME#v}\"" in WORKFLOW.read_text(), (
        "the version check no longer reads the tag the way docs/RELEASING.md tells the release "
        "manager to declare it")


def test_the_supported_versions_have_one_home():
    """`SECURITY.md` is what a reporter reads and what GitHub's Security tab shows. It said "only
    `main` receives fixes" while docs/RELEASING.md patches release lines (review of #510): two
    homes for one policy, in the one place where being wrong costs something. It points at the
    process now, and states no policy of its own."""
    text = (ROOT / "SECURITY.md").read_text()
    section = text.split("## Supported versions", 1)[1].split("\n## ", 1)[0]

    assert "docs/RELEASING.md" in section, section
    assert "only the `main` branch" not in section, section


def test_the_release_process_and_its_agent_are_tracked():
    """`.claude/` is local scratch and ignored, except the agents a maintainer runs on this
    repository: the release agent is how the process is replicated by whoever holds the role, so
    it is reviewed like the document it executes."""
    agent = ROOT / ".claude" / "agents" / "release-manager.md"

    assert agent.is_file()
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(agent)], cwd=ROOT,
                             capture_output=True, check=False)
    assert tracked.returncode == 0, "the release agent is not tracked by git"
    # `--no-index`: a file already tracked is never reported as ignored, so without it a rule that
    # ignores the agent again would pass here and bite the next person who adds an agent
    ignored = subprocess.run(["git", "check-ignore", "-q", "--no-index", str(agent)], cwd=ROOT,
                             check=False)
    assert ignored.returncode == 1, "the release agent is ignored by git, so it can never be reviewed"
    assert "docs/RELEASING.md" in agent.read_text()
    assert (ROOT / "docs" / "RELEASING.md").is_file()

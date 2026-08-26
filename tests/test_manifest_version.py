"""The manifest declares a schema version, and an unsupported one is refused (C-12b).

`.sdlc/project.yaml` is the platform's **most-used public API** — the one file every client writes,
living in the client's own repository, outside our release cycle. On publication its shape becomes
a compatibility commitment whether or not anybody decided to make one.

`version: int = 1` was already there and nothing read it. `extra="forbid"` catches a field we do
not know; it cannot catch a field whose MEANING changed under a name we do. That is the failure
this closes, and it is the expensive shape: a manifest written for a newer platform, loaded by an
older one, running with quietly different semantics.

The rule is ADR-0022's, one layer up: **an unsupported version raises, naming what IS supported.**
A wrong version does not fail like a missing one.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openfactory import namespace
from openfactory.contracts.manifest import SUPPORTED_MANIFEST_VERSIONS, Manifest


def test_the_current_version_loads():
    assert Manifest(version=1).version == 1


def test_a_manifest_with_no_version_is_read_as_version_1():
    """Every manifest in the field today omits it. Refusing those would break every existing
    client to gain a guarantee about the future."""
    assert Manifest().version == 1


def test_a_version_from_the_future_is_refused():
    """The platform cannot know what it does not know. A newer manifest may mean something
    different by a field this build already understands, and guessing is the whole failure."""
    with pytest.raises(ValidationError) as e:
        Manifest(version=2)
    assert "2" in str(e.value)


def test_the_error_names_what_IS_supported():
    """ADR-0022's rule: the message has to be actionable at startup, not just a refusal."""
    with pytest.raises(ValidationError) as e:
        Manifest(version=99)
    msg = str(e.value)
    assert "manifest version" in msg.lower()
    assert "1" in msg  # the supported set is spelled out


@pytest.mark.parametrize("bad", [0, -1, -99])
def test_a_nonsense_version_is_refused(bad):
    with pytest.raises(ValidationError):
        Manifest(version=bad)


def test_a_non_integer_version_is_refused():
    with pytest.raises(ValidationError):
        Manifest(version="latest")


def test_the_supported_set_is_public_and_not_empty():
    """Callers — `doctor`, an installer, a migration tool — need to ask what this build accepts
    without parsing an exception message."""
    assert SUPPORTED_MANIFEST_VERSIONS
    assert 1 in SUPPORTED_MANIFEST_VERSIONS


def test_the_refusal_happens_at_LOAD_time_not_at_first_use(tmp_path):
    """A manifest that parses and then misbehaves halfway through a job has already cost an agent
    pass. `load_manifest` is the door, and the door is where it stops."""
    from openfactory.contracts.project import Project
    from openfactory.loader import load_manifest

    (tmp_path / namespace.DIR).mkdir()
    (tmp_path / namespace.MANIFEST).write_text("version: 42\nbase_branch: main\n")
    project = Project(name="demo", repo_path=str(tmp_path))
    with pytest.raises(ValueError) as e:
        load_manifest(project)
    assert "42" in str(e.value)


def test_the_load_error_names_the_file(tmp_path):
    """Two projects, one bad manifest: the message has to say which."""
    from openfactory.contracts.project import Project
    from openfactory.loader import load_manifest

    (tmp_path / namespace.DIR).mkdir()
    (tmp_path / namespace.MANIFEST).write_text("version: 42\n")
    with pytest.raises(ValueError) as e:
        load_manifest(Project(name="demo", repo_path=str(tmp_path)))
    assert "project.yaml" in str(e.value)


def test_an_unknown_field_is_still_refused():
    """The version check must not have loosened `extra="forbid"` — a typo'd key silently ignored
    is a gate somebody thinks they configured and did not."""
    with pytest.raises(ValidationError):
        Manifest(version=1, mrege_policy="auto")


def test_the_example_manifest_declares_a_supported_version():
    """`docs/project.yaml.example` is what every client copies. If it drifted past what this build
    accepts, onboarding would fail on the very first file."""
    from pathlib import Path

    import yaml

    example = Path(__file__).resolve().parent.parent / "docs" / "project.yaml.example"
    data = yaml.safe_load(example.read_text()) or {}
    assert data.get("version", 1) in SUPPORTED_MANIFEST_VERSIONS


def test_every_fixture_manifest_declares_a_supported_version():
    """The demo projects are what a stranger's first onboarding looks like. A fixture whose
    manifest this build refuses would send them debugging our template, not their setup."""
    import yaml

    # `Path.home()`, NOT an absolute path with somebody's login in it. Three sibling tests already
    # resolve this directory that way; this one hardcoded it, which published the author's home
    # directory AND made the test unrunnable for anybody else — it skipped, silently, forever.
    from tests.demo_projects import demo_projects_root

    demos = demo_projects_root()
    if not demos.exists():  # the fixtures are optional working state, not a test dependency
        pytest.skip("demo projects not present")
    found = list(demos.glob(f"*/{namespace.MANIFEST}")) + list(demos.glob(f"*/*/{namespace.MANIFEST}"))
    for f in found:
        data = yaml.safe_load(f.read_text()) or {}
        assert data.get("version", 1) in SUPPORTED_MANIFEST_VERSIONS, f

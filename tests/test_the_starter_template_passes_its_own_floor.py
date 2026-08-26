"""The file `sdlc project init` writes must survive the very next command in our own script.

`_MANIFEST_TEMPLATE` declared only a `test` role. `openfactory/policy/floor.py` requires `{"test",
"security"}`. And `docs/ONBOARDING.md` tells a client to run `project init` and then `conformance`,
in that order — so the official script was: create the project, then run the command that refuses
what you just created.

It is the FIRST CONTACT, and there was nothing the client could have done differently: we wrote the
file. In a room with their developers, that moment is spent for nothing — they conclude either that
the tool is confusing or that the rule is decorative, and both readings are reasonable.

WHY THE GATE IS INLINE AND NOT `stack: security-oss`. The obvious fix does not work, and finding
that out cost a real attempt: `stack` is a COMPONENT field (`contracts/manifest.py:57`), and
presets are unioned per touched component (`orchestrator/validation.py:82-85`). A starter project
declares no components, so a top-level `stack:` is simply an unknown field and the manifest fails to
load. The preset's own semgrep line is inlined instead, with the same advisory reasoning.
"""

from __future__ import annotations

import pathlib
import tempfile

from openfactory import namespace
from openfactory.cli import _MANIFEST_TEMPLATE
from openfactory.contracts.project import Project, ProviderRef
from openfactory.loader import load_manifest
from openfactory.policy.conformance import floor_reason


def _loaded():
    """Through the REAL loader, because that is what a client's next command uses.

    Hand-constructing `Manifest(**yaml)` silently drops any key whose name does not match a field —
    which is how a first attempt at this test reported a template as fine while `load_manifest`
    would have raised on it.
    """
    root = pathlib.Path(tempfile.mkdtemp())
    (root / namespace.DIR).mkdir()
    (root / namespace.MANIFEST).write_text(_MANIFEST_TEMPLATE)
    project = Project(name="novo", repo_path=str(root),
                      tracker=ProviderRef(kind="github", repo="o/r"))
    return load_manifest(project)


def test_the_template_the_platform_writes_passes_the_platforms_floor():
    reason = floor_reason(_loaded())
    assert reason is None, (
        "`sdlc project init` writes a manifest that `sdlc conformance` refuses, and ONBOARDING.md "
        f"tells the client to run them in that order: {reason}"
    )


def test_the_security_gate_is_ADVISORY_so_a_starter_project_is_not_blocked():
    """Passing the floor must not be bought by blocking day one.

    A first scan of any real codebase reports the accumulated debt of its whole history, and none
    of it is the first ticket's fault. Blocking on day one means the client turns the gate off —
    and a gate that gets turned off protects nothing.
    """
    gate = _loaded().validation["security"]

    assert getattr(gate, "advisory", False) is True, "the starter would block on pre-existing debt"


def test_the_template_still_declares_a_test_role():
    """The positive twin: satisfying the floor by deleting the requirement would also pass."""
    assert "test" in _loaded().validation

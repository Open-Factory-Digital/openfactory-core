"""Which image the box runs is decided once, from configuration (ADR-0037 D4).

`"openfactory-python"` was a literal in SIX places — `cli.py:380`, `cli.py:395`, `io.py:42`, `io.py:59`,
`activities.py:783` and `registry.py:75` — and `OPENFACTORY_SANDBOX_IMAGE`, which `docker-compose.yml`
sets, was read by nothing. So the OSS distribution already ran an image different from the one it
declared, and no deployment could change the box at all.

That is C-13 exactly, the defect `io.py`'s own docstring names: *"a configuration that looks
configured and is ignored"*. It was fixed there for `OPENFACTORY_SANDBOX` and left standing one line below
for `OPENFACTORY_SANDBOX_IMAGE`.

D4 IS A BUG FIX, not new capability, which is why it lands before D1 and D2 — everything else in
ADR-0037 needs somewhere to put the answer, and there was nowhere.

THE PRECEDENCE, most specific first:

    an explicit --image        the operator overriding for one run
    the project's box.image    what this client's stack needs (registry, not manifest: the
                               manifest lives in the repo the executor edits, so an agent able
                               to write it would be choosing its own root filesystem)
    OPENFACTORY_SANDBOX_IMAGE         a deployment-wide default
    the framework's default    one constant, one place

AND ONE REFUSAL. A deployment whose box is `fargate` runs the whole job inside a task whose image
is baked into the task definition. Accepting `box.image` there and ignoring it would mint a fresh
instance of the very defect this fixes, in the release that fixes it — so it RAISES, naming both.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory.contracts.project import BoxConfig, Project
from openfactory.factory import resolve_box_image

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_ambient_image(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_SANDBOX_IMAGE", raising=False)


def _project(image: str | None = None) -> Project:
    box = BoxConfig(image=image) if image is not None else None
    return Project(name="acme", repo_path="/tmp/acme", box=box)


# ── the precedence ──────────────────────────────────────────────────────────────────────────────

def test_the_framework_default_when_nothing_is_configured():
    """The pilot declares no box and must keep running the image it runs today. Zero migration is
    the whole reason D4 can land first."""
    from openfactory.adapters.sandbox.registry import DEFAULT_BOX_IMAGE

    assert resolve_box_image(_project()) == DEFAULT_BOX_IMAGE == "openfactory-python"


def test_the_deployment_wide_env_is_finally_read(monkeypatch):
    """`docker-compose.yml` has set this since the file was written and nothing ever read it."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX_IMAGE", "openfactory-python:sandbox")
    assert resolve_box_image(_project()) == "openfactory-python:sandbox"


def test_the_project_beats_the_deployment(monkeypatch):
    """One deployment, N clients, N stacks. The whole point."""
    monkeypatch.setenv("OPENFACTORY_SANDBOX_IMAGE", "openfactory-python:sandbox")
    assert resolve_box_image(_project("mcr.microsoft.com/dotnet/sdk:10.0")) == \
        "mcr.microsoft.com/dotnet/sdk:10.0"


def test_an_explicit_image_beats_everything(monkeypatch):
    monkeypatch.setenv("OPENFACTORY_SANDBOX_IMAGE", "openfactory-python:sandbox")
    assert resolve_box_image(_project("mycorp/ci:1"), explicit="scratch-test:2") == \
        "scratch-test:2"


def test_a_blank_declaration_does_not_win():
    """An empty string in YAML is somebody who started typing, not a request for the empty image.
    Falling through is the only reading that cannot produce `docker run ''`."""
    assert resolve_box_image(_project("")) == "openfactory-python"
    assert resolve_box_image(_project("   ")) == "openfactory-python"
    assert resolve_box_image(_project("mycorp/ci:1"), explicit="  ") == "mycorp/ci:1"


def test_no_project_at_all_still_resolves():
    """`build_sandbox` and the CLI are reachable without a registered project."""
    assert resolve_box_image(None) == "openfactory-python"


# ── the refusal that stops D4 from re-creating C-13 ─────────────────────────────────────────────

def test_declaring_an_image_on_a_fargate_deployment_raises():
    """The task definition's image is baked. Both live deployments are Fargate, so silently
    ignoring the field is the likeliest way this release recreates the defect it fixes."""
    with pytest.raises(ValueError) as err:
        resolve_box_image(_project("mycorp/ci:1"), sandbox="fargate")

    message = str(err.value)
    assert "fargate" in message and "mycorp/ci:1" in message
    assert "box.image" in message


def test_fargate_without_a_declaration_is_fine():
    """The pilot must not start failing: it is Fargate and declares no box."""
    assert resolve_box_image(_project(), sandbox="fargate") == "openfactory-python"


# ── one literal, one resolver ───────────────────────────────────────────────────────────────────

def test_the_image_name_is_written_down_exactly_once():
    """Six literals is six places to disagree. The guard is what keeps the seventh from appearing
    the next time somebody needs a default."""
    offenders: list[str] = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if '"openfactory-python"' not in line and "'openfactory-python'" not in line:
                continue
            rel = path.relative_to(ROOT)
            if str(rel) == "openfactory/adapters/sandbox/registry.py" and "DEFAULT_BOX_IMAGE" in line:
                continue  # the one definition
            offenders.append(f"{rel}:{lineno} — {line.strip()[:90]}")
    assert not offenders, (
        "the box image is named outside its one definition; import DEFAULT_BOX_IMAGE or call "
        "resolve_box_image:\n  " + "\n  ".join(offenders)
    )


LAUNCH_SITES = ["openfactory/cli.py", "openfactory/runtime/temporal/activities.py", "openfactory/factory.py"]


@pytest.mark.parametrize("rel", LAUNCH_SITES)
def test_no_launch_site_hard_codes_an_image(rel):
    """`activities.py:783` built a CI-repair runner with `image="openfactory-python"` while holding the
    project — so even a client who configured a box got the framework's image on the repair path,
    which is the shape of bug that only shows up on the second failure of the day."""
    offenders = []
    for node in ast.walk(ast.parse((ROOT / rel).read_text())):
        if not isinstance(node, ast.keyword) or node.arg != "image":
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            offenders.append(f"{rel}:{node.lineno} — image={node.value.value!r}")
    assert not offenders, "\n  ".join([""] + offenders)


def test_the_resolver_is_never_called_from_a_workflow_body():
    """It reads the environment. `adapters/sandbox/registry.py` states the rule: anything a
    workflow body calls must be pure, or it replays differently on a worker started with a
    different configuration. The image is resolved at LAUNCH and stamped into the input."""
    body = (ROOT / "openfactory/runtime/temporal/workflow.py").read_text()
    assert "resolve_box_image" not in body, (
        "the workflow body resolves the image itself; it must receive one already resolved"
    )


# ── the guard that the FIRST version of this file was missing ───────────────────────────────────
#
# `test_no_launch_site_hard_codes_an_image` asserts no launch site passes a string LITERAL for
# `image=`. Every launch site passed it — by passing no image at all. The four production
# constructions of `JobParams` omitted the field entirely, so `default_factory` supplied the
# framework constant and `project.box.image` and `OPENFACTORY_SANDBOX_IMAGE` reached no job started by the
# poller, the panel, the REST API or the starter: no job in either live deployment, and none in the
# compose stack the whole change exists to fix.
#
# ABSENCE LOOKED LIKE COMPLIANCE. A guard that forbids the wrong value cannot see a missing one,
# and "built, tested, reached by nothing" is this repository's signature defect — committed here in
# the change whose test file already had a section called reachability. The lesson is narrower than
# "write reachability tests": a negative guard needs a positive twin.

JOB_LAUNCH_SITES = [
    "openfactory/runtime/temporal/activities.py",
    "openfactory/runtime/temporal/starter.py",
    "openfactory/api/app.py",
]


@pytest.mark.parametrize("rel", JOB_LAUNCH_SITES)
def test_every_job_launch_stamps_a_resolved_image(rel):
    """The positive twin. A workflow input built without `image=` silently takes the framework
    default, which is exactly the state D4 exists to end."""
    missing = []
    for node in ast.walk(ast.parse((ROOT / rel).read_text())):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "JobParams"):
            continue
        if "image" not in {kw.arg for kw in node.keywords}:
            missing.append(f"{rel}:{node.lineno} — JobParams(...) with no image=")
    assert not missing, (
        "a job is launched without a resolved image, so the project's box.image and "
        "OPENFACTORY_SANDBOX_IMAGE are ignored for every job this path starts:\n  " + "\n  ".join(missing)
    )


def test_the_poller_launch_carries_the_projects_declared_image(monkeypatch):
    """Behavioural, from the launch site inward — the poller is how both live deployments and the
    compose stack actually start work."""
    import openfactory.runtime.temporal.activities as acts

    captured: list[object] = []

    class _Client:
        async def start_workflow(self, _name, params, **kw):
            captured.append(params)

    async def _connect():
        return _Client()

    monkeypatch.setattr("openfactory.runtime.temporal.connection.connect", _connect)
    monkeypatch.setattr(acts.ProjectRegistry, "get",
                        lambda self, name: _project("mycorp/ci:1"))

    import asyncio

    from openfactory.runtime.temporal.io import StartJobsInput

    asyncio.run(acts.start_jobs(
        StartJobsInput(project="acme", issues=["12"], sandbox="container")
    ))

    assert captured, "no workflow was started"
    assert captured[0].image == "mycorp/ci:1", captured[0].image


def test_poll_resolves_too(monkeypatch):
    """`sdlc poll` passed its raw --image straight through. After the default changed to None that
    became `None`, which only survives because `_container` has an `or` — so poll honoured neither
    the project nor the environment, and never got the fargate refusal."""
    src = (ROOT / "openfactory/cli.py").read_text()
    poll_body = src[src.index("def poll("):]
    poll_body = poll_body[:poll_body.index("\n@app.command") if "\n@app.command" in poll_body
                          else len(poll_body)]
    assert "resolve_box_image" in poll_body, (
        "`sdlc poll` builds runners without resolving the image"
    )


# ── the refusal must not be a vendor name, and must not be an outage ────────────────────────────
#
# Three defects the adversarial panel found in the FIRST version of this change, all of which
# survived thirteen green guards.

def test_a_typo_inside_box_does_not_make_the_registry_unreadable(tmp_path):
    """`BoxConfig` shipped with `extra="forbid"`, which reintroduces one level down the exact
    outage `registry.py:150` documents as forbidden: *"making an unknown key fatal would turn one
    stale line into an outage the operator could not have reviewed, since the file is invisible to
    every test and reviewer."* `deploy/registry.yaml` is gitignored and baked into the worker
    image. A mistyped `netwrok:` made `list()` raise — so EVERY project became unloadable, and the
    worker that shipped with it raises on every job.

    Ignored, but never silent: the same rule `Project` follows."""
    import yaml

    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"acme": {
        "name": "acme", "repo_path": "/tmp/acme",
        "box": {"image": "mycorp/ci:1", "netwrok": "none"}}}}))

    projects = ProjectRegistry(path=path).list()

    assert len(projects) == 1
    assert projects[0].box.image == "mycorp/ci:1", "the good keys must still take effect"


def test_a_typo_inside_box_is_reported_by_name(tmp_path, caplog):
    """Ignoring silently is the other half of the same defect — a dropped `netwrok:` means the
    egress restriction somebody thought they configured is not configured, and the first report
    comes from an incident."""
    import yaml

    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"acme": {
        "name": "acme", "repo_path": "/tmp/acme", "box": {"netwrok": "none"}}}}))

    with caplog.at_level("WARNING"):
        ProjectRegistry(path=path).list()

    assert any("netwrok" in r.getMessage() for r in caplog.records), caplog.text


def test_the_refusal_is_a_property_of_the_box_not_a_vendor_name():
    """`worktree` ignores `box.image` just as completely as `fargate` does — `WorktreeSandbox`
    takes no image at all — and `worktree` is the CLI's DEFAULT. So the failure the fargate branch
    refuses was happening silently, by default, one sandbox over.

    Driven off `BoxTraits` so a new box cannot be added without answering the question, which is
    the whole reason that dataclass exists (ADR-0022: no vendor name in the lifecycle)."""
    from openfactory.adapters.sandbox.registry import BOXES, box_traits

    for kind in BOXES:
        assert hasattr(box_traits(kind), "honours_image"), kind

    assert box_traits("container").honours_image is True
    assert box_traits("fargate").honours_image is False
    assert box_traits("worktree").honours_image is False


def test_declaring_an_image_for_a_worktree_run_also_refuses():
    with pytest.raises(ValueError) as err:
        resolve_box_image(_project("mycorp/ci:1"), sandbox="worktree")

    assert "worktree" in str(err.value) and "mycorp/ci:1" in str(err.value)


def test_an_unknown_box_kind_does_not_crash_the_resolver():
    """`resolve_box_image` is called at launch, before `build_sandbox` would reject the kind. It
    must not turn a typo'd sandbox into a confusing image error — let the box registry own that
    message."""
    assert resolve_box_image(_project(), sandbox="contianer") == "openfactory-python"

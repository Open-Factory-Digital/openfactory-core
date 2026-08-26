"""What the box's docstrings promise must be what the box does (ADR-0037).

`ContainerSandbox`'s module docstring made four claims. One was true.

1. *"CPU/mem limits … bound the blast radius"* — TRUE. `--cpus 2 --memory 4g` are applied.
2. *"a deny-by-default network policy"* — **FALSE**, and not fixable: the default is
   `network="bridge"`, i.e. full outbound internet, and it has to be. The harness dials
   `api.anthropic.com` and `setup:` runs `pip install` / `dotnet restore`. `--network none` would
   break every job. The claim is repeated in `adapters/sandbox/base.py:6` and
   `adapters/sandbox/registry.py:79`.
3. *"A dep-cache volume is mounted so we don't pay a full install per job"* — **FALSE**.
   `registry.py`'s `_container()` constructs `ContainerSandbox(image=...)` and passes nothing else,
   so `cache_volume` is None on every job the platform actually runs and the install is paid in
   full every time.
4. *"not yet exercised end-to-end … treat as unverified"* — **STALE**. This is the production path
   and has been for months.

WHY THIS IS WORSE THAN A DOCUMENTATION BUG. A security claim that is written down and false is
consumed as a control: somebody deciding what a client's box may reach reads "deny-by-default" and
stops thinking. Under ADR-0037 D1 the image becomes the CLIENT's, which makes "what can code in
this box reach?" a question that will genuinely be asked — and the honest answer is *everything
your worker's network can reach*, which is a fact a deployment can design around and a lie is not.

So the resolution is asymmetric, deliberately: claims 2 and 4 are DELETED and replaced with the
truth, claim 3 is IMPLEMENTED (the knob exists and was simply never wired), and every constructor
knob becomes reachable from configuration so a deployment that wants an egress-restricted network
can have one.
"""

from __future__ import annotations

import inspect
import pathlib

import pytest

from openfactory.adapters.sandbox.container import ContainerSandbox
from openfactory.adapters.sandbox.registry import build_sandbox

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = [
    "openfactory/adapters/sandbox/container.py",
    "openfactory/adapters/sandbox/base.py",
    "openfactory/adapters/sandbox/registry.py",
]


# ── the claims that must go ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", SOURCES)
def test_nothing_claims_a_deny_by_default_network(rel):
    """The box has outbound internet and must. Saying otherwise is a control somebody will trust."""
    text = (ROOT / rel).read_text()
    assert "deny-by-default" not in text, (
        f"{rel} promises a deny-by-default network policy; the default is `bridge`, which is full "
        "outbound internet, and it cannot be otherwise while the harness dials out"
    )


@pytest.mark.parametrize("rel", SOURCES)
def test_nothing_claims_network_isolation_for_the_container_box(rel):
    """`network policy` in a list of what the container box provides reads as isolation."""
    text = (ROOT / rel).read_text()
    for phrase in ("network policy", "network isolation"):
        # the worktree box legitimately says it has NO network isolation — that sentence is true
        offending = [
            line.strip() for line in text.splitlines()
            if phrase in line and " no " not in line.lower() and "not " not in line.lower()
        ]
        assert not offending, f"{rel}: {offending}"


def test_the_unverified_note_is_gone():
    """`treat as unverified until run against Docker` on the production path is a note that tells
    a reader the opposite of the truth."""
    text = (ROOT / "openfactory/adapters/sandbox/container.py").read_text()
    assert "treat as unverified" not in text
    assert "not yet exercised end-to-end" not in text


def test_the_box_says_plainly_what_it_can_reach():
    """Deleting a false claim is half the job; the replacement has to be usable by whoever is
    deciding what a client's box may touch."""
    text = (ROOT / "openfactory/adapters/sandbox/container.py").read_text().lower()
    assert "outbound" in text and "network" in text


# ── every knob must be reachable from configuration ─────────────────────────────────────────────

KNOBS = [k for k in inspect.signature(ContainerSandbox.__init__).parameters if k != "self"]


def test_the_sweep_finds_the_knobs():
    assert set(KNOBS) >= {"image", "project", "toolbox", "cache_volume", "cpus", "memory",
                          "network"}, KNOBS


@pytest.mark.parametrize("knob", KNOBS)
def test_every_knob_is_reachable_through_the_registry(knob):
    """`_container()` passed ONLY `image`, so four documented knobs were unreachable — the
    signature-level version of this repository's signature defect. A parameter no caller can set
    is a parameter that does not exist."""
    sentinel = {"image": "mycorp/ci:1", "project": "acme", "toolbox": "openfactory_toolbox",
                "cache_volume": "openfactory_cache", "cpus": "7", "memory": "13g",
                "network": "openfactory-egress",
                # box.env: variable NAMES a deployment's auth shape passes through (Bedrock,
                # a gateway, a scanner) — tuple, because the sandbox freezes it
                "extra_env": ("AWS_REGION",)}[knob]
    box = build_sandbox("container", **{"image": "img", knob: sentinel})

    assert getattr(box, knob) == sentinel, (
        f"build_sandbox drops {knob!r}: the registry constructs the box and this knob never "
        "reaches it, so no deployment can set it"
    )


def test_the_defaults_are_unchanged_for_the_pilot():
    """Wiring the knobs must not move the running deployment: same cpus, same memory, same
    network, and still no cache volume unless one is asked for."""
    box = build_sandbox("container", image="openfactory-python")

    assert (box.cpus, box.memory, box.network) == ("2", "4g", "bridge")
    assert box.cache_volume is None


def test_a_restricted_network_actually_reaches_docker_run(monkeypatch):
    """Reachability, not just assignment: the value has to appear in the argv. A knob that is
    stored on the instance and never passed is the same defect one layer down."""
    import openfactory.adapters.sandbox.container as mod

    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "_host", lambda args, timeout=None: (calls.append(list(args)), (0, ""))[1])

    box = build_sandbox("container", image="img", network="openfactory-egress", cache_volume="openfactory_cache")
    box.prepare(repo_path=ROOT, base_branch="main", branch="sdlc/1")

    run_argv = next(a for a in calls if "run" in a)
    assert "--network" in run_argv and "openfactory-egress" in run_argv, run_argv
    assert any("openfactory_cache:/cache" in part for part in run_argv), run_argv


# ── the registry's knobs must reach the box, not just exist ─────────────────────────────────────
#
# `BoxConfig` (ADR-0037 D1) declares network / cache_volume / cpus / memory. `build_runner` passed
# none of them — declarable in the registry, consumed by nobody: exactly the defect D4 fixed for
# `image`, one field over, introduced by the change that fixed it. Two of the four are the ones a
# real client needs: `network` is how a deployment bounds what agent-written code can reach, and
# `cache_volume` is the difference between a dependency install per job and one per fleet.

BOX_KNOBS = ["network", "cache_volume", "cpus", "memory"]


def _runner_box(monkeypatch, box):
    """Build a runner and hand back the box it constructed."""
    import openfactory.adapters.sandbox.registry as reg
    from openfactory.contracts.project import Project

    built: list[object] = []
    traits, real = reg.BOXES["container"]

    def _spy(**kw):
        made = real(**kw)
        built.append(made)
        return made

    reg.BOXES["container"] = (traits, _spy)
    try:
        from openfactory import factory

        project = Project(name="acme", repo_path="/tmp/acme", box=box)
        try:
            factory.build_runner(project, "#1", sandbox="container", image="img", review=False)
        except Exception:
            pass  # downstream wiring may need credentials; the box construction is the subject
    finally:
        reg.BOXES["container"] = (traits, real)
    assert built, "no container box was built"
    return built[0]


@pytest.mark.parametrize("knob", BOX_KNOBS)
def test_a_declared_knob_reaches_the_box(monkeypatch, knob):
    from openfactory.contracts.project import BoxConfig

    sentinel = {"network": "openfactory-egress", "cache_volume": "openfactory_cache",
                "cpus": "7", "memory": "13g"}[knob]
    box = _runner_box(monkeypatch, BoxConfig(**{knob: sentinel}))

    assert getattr(box, knob) == sentinel, (
        f"box.{knob} is declarable in the registry and reaches nothing"
    )


def test_a_project_with_no_box_block_is_unchanged(monkeypatch):
    """Every project that exists today. The knobs must default exactly as before."""
    box = _runner_box(monkeypatch, None)

    assert (box.cpus, box.memory, box.network) == ("2", "4g", "bridge")
    assert box.cache_volume is None


def test_the_declared_network_reaches_docker_run(monkeypatch):
    """End of the chain, not the middle: the value has to appear in the argv."""
    import openfactory.adapters.sandbox.container as mod
    from openfactory.contracts.project import BoxConfig

    box = _runner_box(monkeypatch, BoxConfig(network="openfactory-egress"))
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "_host",
                        lambda args, timeout=None: (calls.append(list(args)), (0, ""))[1])
    box.prepare(repo_path=ROOT, base_branch="main", branch="sdlc/1")

    run_argv = next(a for a in calls if "run" in a)
    assert run_argv[run_argv.index("--network") + 1] == "openfactory-egress", run_argv


def test_knobs_declared_for_a_box_that_cannot_honour_them_are_reported(monkeypatch, caplog):
    """`worktree` is a git worktree on the host: no container, so no network namespace and no cpu
    limit. `fargate`'s task definition sets its own. Both ignore all four knobs as completely as
    they ignore `box.image` — and `image` RAISES while these would have gone silent.

    A warning rather than a raise, and the asymmetry is deliberate: `image` changes WHAT CODE RUNS,
    so accepting it and running something else is a lie about the work. These bound resources, and
    a deployment that declares them on the wrong box has a misconfiguration to fix, not a job to
    stop. What is not acceptable is silence — a `network:` nobody applies means the egress
    restriction somebody believes is in place is not."""
    import openfactory.adapters.sandbox.registry as reg
    from openfactory.contracts.project import BoxConfig, Project
    from openfactory.factory import build_runner

    project = Project(name="acme", repo_path="/tmp/acme",
                      box=BoxConfig(network="openfactory-egress", cpus="7"))
    with caplog.at_level("WARNING"):
        try:
            build_runner(project, "#1", sandbox="worktree", image="img", review=False)
        except Exception:
            pass

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "network" in said and "cpus" in said, said
    assert "worktree" in said, said
    assert reg  # keep the import meaningful to a reader


def test_the_container_box_is_not_warned_about(monkeypatch, caplog):
    """A warning that fires on the correct configuration is a warning nobody reads."""
    from openfactory.contracts.project import BoxConfig

    with caplog.at_level("WARNING"):
        _runner_box(monkeypatch, BoxConfig(network="openfactory-egress"))

    assert "cannot honour" not in caplog.text

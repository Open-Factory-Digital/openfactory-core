"""The cockpit reports the axes it RESOLVES, not the ones it was written with (C-38, #81).

The product owner, looking at the panel for a project mid-demo: *"anybody looking at the board
thinks it is Claude."* That was right, and it was not a rendering slip — the endpoint could not
say anything else:

    "harness": "Claude Code",                                       # a literal
    "models": {"executor": os.environ.get("OPENFACTORY_EXECUTOR_MODEL") or "default"}   # env only

Both predate the axes being configurable and both survived the axes becoming configurable. So a
project on `harness: opencode` with `model: amazon-bedrock/…` displayed "Claude Code" and
"default" — on the surface ADR-0038 calls the REFERENCE one, about the axis whose entire purpose
is being a per-project choice, in a product sold as harness-agnostic.

The same defect twice over: the harness axis got a registry, the model axis got one this morning,
and the panel asked neither.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from openfactory.api.app import _axes
from openfactory.contracts.project import Project

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """The env override outranks the registry by design, so a leaked variable would make every
    assertion here pass for the wrong reason — which is exactly how the bug hid."""
    from openfactory.adapters.agent import registry as harnesses

    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values(), "OPENFACTORY_PLANNER_MODEL",
                "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "OPENFACTORY_HARNESS_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


def _registered(monkeypatch, **kw):
    project = Project(name="p", repo_path="/tmp/p", **kw)
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, name: project)
    return project


# ── what the cockpit says ────────────────────────────────────────────────────────────────────────

def test_a_project_on_another_harness_is_not_called_claude(monkeypatch):
    _registered(monkeypatch, harness="opencode")
    harness, _models, _route = _axes("p")
    assert harness == "OpenCode"


def test_the_default_still_reads_as_claude_code(monkeypatch):
    """The deployment every reader knows. Fixing the lie must not rename the truth."""
    _registered(monkeypatch)
    assert _axes("p")[0] == "Claude Code"


def test_a_harness_with_no_label_shows_its_own_name(monkeypatch):
    """A new harness must not need a display table to be reported HONESTLY — only to be reported
    prettily. Falling back to the kind is what keeps the table optional."""
    from openfactory.adapters.agent import registry as harnesses

    monkeypatch.setitem(harnesses.HARNESSES, "newthing", lambda **kw: object())
    _registered(monkeypatch, harness="newthing")
    assert _axes("p")[0] == "newthing"


def test_MIXED_harnesses_are_shown_rather_than_collapsed(monkeypatch):
    """"An independent reviewer on a different engine" is the case the per-role axis exists for.
    Showing only the executor's would hide the very decision worth seeing."""
    _registered(monkeypatch, harness={"executor": "opencode", "reviewer": "claude_code"})
    harness = _axes("p")[0]
    assert "OpenCode" in harness and "Claude Code" in harness
    assert "executor" in harness and "reviewer" in harness


def test_the_model_comes_from_the_registry_not_the_environment(monkeypatch):
    _registered(monkeypatch, model="amazon-bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    models = _axes("p")[1]
    assert models["executor"].startswith("amazon-bedrock/")


def test_every_role_is_reported(monkeypatch):
    """A client paying for a frontier executor and a cheap tech-lead must be able to SEE that."""
    from openfactory.adapters.agent import registry as harnesses

    _registered(monkeypatch, model={"executor": "big-1", "techlead": "cheap-1"})
    models = _axes("p")[1]
    assert set(models) == set(harnesses.ROLES)
    assert models["executor"] == "big-1" and models["techlead"] == "cheap-1"
    assert models["reviewer"] == "default"


def test_the_auth_ROUTE_is_named_rather_than_unknown(monkeypatch):
    """The cockpit showed the token pool's format, so a Bedrock deployment — which has no pool at
    all — read `unknown`. The route is the thing a reader actually wants.

    Declared through the REGISTRY, not the environment: an earlier version of this test set
    `CLAUDE_CODE_USE_BEDROCK` in the process and expected `bedrock`, which asserted the very bug
    the panel had — reading a route out of a container that never carries one."""
    _registered(monkeypatch, box={"env": ["CLAUDE_CODE_USE_BEDROCK", "AWS_REGION"]})
    assert _axes("p")[2] == "bedrock"


def test_an_unregistered_project_still_renders(monkeypatch):
    """The cockpit is informational; it must degrade, not 500."""
    def _boom(self, name):
        raise ValueError("nope")

    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", _boom)
    harness, models, _route = _axes("nope")
    assert harness and models


# ── the guards ───────────────────────────────────────────────────────────────────────────────────

VENDOR_STRINGS = ("Claude Code", "OpenAI", "Codex", "Kimi", "OpenCode", "Anthropic")


def test_no_vendor_name_is_returned_as_a_FACT_about_a_project():
    """The regression guard for the actual bug. A vendor name may appear in the display-label
    table (`_HARNESS_LABELS`) — that is where it belongs — but never as a value assigned to a key
    the panel presents as this project's configuration."""
    src = (ROOT / "openfactory/api/app.py").read_text()
    tree = ast.parse(src)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value not in ("harness", "model", "models", "auth_format"):
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                offenders.append(f"app.py:{node.lineno} — {key.value!r} = {value.value!r}")
    assert offenders == [], (
        "the panel states a project's axis as a constant, so it says the same thing whatever the "
        "registry holds:\n  " + "\n  ".join(offenders)
    )


def test_the_panel_does_not_read_the_model_from_the_environment_ITSELF():
    """`model_for` already applies the documented order (env → project → default). A second,
    env-only read beside it is how the two answers came to disagree."""
    src = (ROOT / "openfactory/api/app.py").read_text()
    for var in ("OPENFACTORY_EXECUTOR_MODEL", "OPENFACTORY_PLANNER_MODEL"):
        assert var not in src, f"{var} is read directly in the panel; ask model_for instead"


def test_no_library_module_loads_dotenv_ON_IMPORT():
    """The class guard. `cli.py` carries a docstring about this exact defect — a bare
    `load_dotenv()` at module scope, found when `pytest-randomly` ordered an importing test ahead
    of others and handed them live write-capable credentials for a client's repository. The panel
    had the same line, and it stayed until the harness axis made it visible: resolving a project's
    model returned a value from a `.env` nobody had asked to load.

    An entry point may load its environment. A module that is merely imported may not."""
    offenders = []
    for path in sorted((ROOT / "openfactory").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in tree.body:  # MODULE SCOPE ONLY — inside a function is the correct place
            call = node.value if isinstance(node, ast.Expr) else None
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "load_dotenv":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], (
        "importing these mutates the whole process's environment:\n  " + "\n  ".join(offenders)
    )


# ── the route: answered from what the PANEL can see, never from its own environment ──────────────

def test_a_bedrock_project_is_not_reported_as_anthropic(monkeypatch):
    """The panel's container carries none of the discriminating variables — its terraform
    enumerates its environment and there is no CLAUDE_CODE_USE_BEDROCK, no ANTHROPIC_BASE_URL, no
    harness credential at all. So `resolve_route` fell through every branch and returned
    `anthropic`: a vendor name reached by ABSENCE, rendered identically to a resolved one. A
    Bedrock client's operator would read it and go ask their security team to open a host their
    deployment never contacts."""
    _registered(monkeypatch, box={"env": ["CLAUDE_CODE_USE_BEDROCK", "AWS_REGION"]})
    assert _axes("p")[2] == "bedrock"


def test_a_gateway_project_says_gateway(monkeypatch):
    _registered(monkeypatch, box={"env": ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"]})
    assert _axes("p")[2] == "gateway"


def test_an_opencode_project_takes_its_route_from_the_MODEL(monkeypatch):
    """For opencode the provider IS the model's prefix, and the model is a registry value — so
    the panel can know this one exactly."""
    _registered(monkeypatch, harness="opencode",
                model="amazon-bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    assert _axes("p")[2] == "bedrock"


def test_a_project_naming_nothing_is_anthropic_by_CONCLUSION(monkeypatch):
    """Not a fallback: `_AUTH_ENV_VARS` is the only set the box passes by default, so a project
    that names no other variable has no channel for another credential to arrive through."""
    _registered(monkeypatch)
    assert _axes("p")[2] == "anthropic"


def test_the_panel_never_asks_the_ENVIRONMENT_for_the_route():
    """The regression guard for the fix that replaced one lie with a subtler one."""
    # AST, not substring: the comment above the fix NAMES `resolve_route` while explaining why the
    # panel must not call it. Text matching would trip on the explanation — the third time that
    # exact trap has been hit in this codebase.
    tree = ast.parse((ROOT / "openfactory/api/app.py").read_text())
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "resolve_route" not in called | imported, (
        "the panel resolves the route from its OWN process environment, which belongs to a "
        "different container than the one the harness runs in"
    )
    assert "declared_route" in imported


def test_the_cockpit_does_not_claim_a_review_mode_it_could_not_read(monkeypatch):
    """`load_manifest` ALWAYS raises on the deployed panel — the registry's `repo_path` is a
    placeholder that exists only inside the Fargate job — so the literal "advisory" was what
    shipped on every cockpit load, describing a `review_mode: blocking` project as advisory."""
    src = (ROOT / "openfactory/api/app.py").read_text()
    assert 'review_mode = True, "advisory"' not in src
    assert 'single_agent, review_mode = True, ""' in src

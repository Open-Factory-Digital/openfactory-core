"""The cloud is a directory delete: the AWS connector is an add-on the core never imports.

THE DOCTRINE (owner, 2026-08-24): the public repository is the core; AWS, Azure DevOps and Slack are
connectors installed from outside through the `openfactory.adapters` entry-point group. The review
that preceded this file measured the box axis against it and found the connector welded in at
fourteen sites: four `if inp.sandbox == "fargate"` dispatches in the activities, each importing the
vendor's launcher by hand; a CloudWatch-named class in the engine's view; the panel keyed on a
cluster variable; three readers that fell through to a vendor's table whenever a table name was
set; and the `dynamodb`/`s3` rows in core tables that no plugin lookup could ever replace. Deleting
`runtime/fargate/`, `observability/dynamo.py` and `adapters/agent/s3_session_store.py` produced
50 failures and 10 collection errors.

THE PROOF IS THE DELETE. With those three paths removed from the tree the core imports, every
registry answers, and the gate is green — the experiment is recorded in the commit that added this
file. What this file pins is what made that true, each piece by behaviour and with a positive twin:

  · no module outside the AWS paths imports from them, however the import is spelled;
  · the engine dispatches on the box's TRAITS, never on a provider's name — a remote add-on box
    reaches its own `launch` and its own `stop` (the two halves of one lifecycle that used to
    disagree);
  · a plugin box's traits reach the workflow as DATA, because the workflow's lookup is pure;
  · the deployment's box is `OPENFACTORY_SANDBOX` or the container, never a vendor's variable;
  · a metrics sink says it can be read by implementing `ReadableSink`, and no reader falls through
    to a vendor's table when it cannot;
  · the token pool comes from a declared source with a free default;
  · the platform's own vendor rows resolve through the same door a stranger's would.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import textwrap

import pytest
from vendor_addons import install, require

from openfactory.adapters.sandbox.registry import (
    BOXES,
    BoxTraits,
    RemoteBox,
    box_traits,
    build_sandbox,
    installed_box_traits,
    no_local_adapter,
    remote_box,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The paths that ARE the AWS connector. Everything else under `openfactory/` is the core.
AWS_PATHS = (
    "openfactory/runtime/fargate/",
    "openfactory/observability/dynamo.py",
    "openfactory/adapters/agent/s3_session_store.py",
)
AWS_MODULES = (
    "openfactory.runtime.fargate",
    "openfactory.observability.dynamo",
    "openfactory.adapters.agent.s3_session_store",
)


# ── 1. the import graph: the core never names the connector ─────────────────────────────────────

def _names_aws(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in AWS_MODULES)


def _static_text(node: ast.AST) -> str:
    """What a string expression says before it runs: its constant pieces, in order. A plain
    literal, `"a." + "b"`, an implicit concatenation and the literal parts of an f-string all
    read; a name or a call contributes nothing, so a module spelled from a VARIABLE is not a hit
    (the adapter packages' own `import_module(module)` loaders are that shape and are the core)."""
    return "".join(n.value for n in ast.walk(node)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str))


def imports_of_aws(tree: ast.AST) -> list[str]:
    """Every way a module can reach the connector: `import`, `from … import` — including
    `from openfactory.observability import dynamo`, where the PACKAGE is the core and the NAME is
    the vendor module (a survivor the review fed this scanner, 2026-08-26) — and the dynamic
    spellings a guard that only looked at import statements would wave through:
    `importlib.import_module("…")` and `__import__("…")`, with the module named by a literal, a
    concatenation of literals or an f-string's literal parts."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if _names_aws(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            if _names_aws(node.module):
                hits.append(node.module)
            else:
                hits += [f"{node.module}.{a.name}" for a in node.names
                         if _names_aws(f"{node.module}.{a.name}")]
        elif isinstance(node, ast.Call):
            fn = node.func
            dynamic = ((isinstance(fn, ast.Attribute) and fn.attr == "import_module")
                       or (isinstance(fn, ast.Name) and fn.id == "__import__"))
            if dynamic and node.args:
                named = _static_text(node.args[0])
                if named.startswith(".") and len(node.args) > 1:  # import_module(".x", "pkg")
                    named = _static_text(node.args[1]) + named
                if _names_aws(named):
                    hits.append(named)
    return hits


def _core_sources() -> list[pathlib.Path]:
    return sorted(p for p in (ROOT / "openfactory").rglob("*.py")
                  if not any(str(p.relative_to(ROOT)).startswith(a) for a in AWS_PATHS))


def test_the_sweep_walks_the_core():
    assert len(_core_sources()) >= 100


def test_no_core_module_imports_the_aws_connector():
    """The guard. Fourteen sites when it was first run (activities.py ×5, view.py ×3, app.py,
    metrics_view.py, query.py, transcript.py, observability/registry.py, session_store.py); a
    connector the core imports is not one a client can decline to install."""
    offenders = {str(p.relative_to(ROOT)): hits
                 for p in _core_sources() if (hits := imports_of_aws(ast.parse(p.read_text())))}
    assert not offenders, (
        "core modules import the AWS connector — the connector is an add-on that registers through "
        f"the `openfactory.adapters` entry-point group, and the core must resolve it by KIND: "
        f"{offenders}")


@pytest.mark.parametrize("spelling", [
    "from openfactory.runtime.fargate.launcher import FargateLauncher",
    "import openfactory.observability.dynamo as d",
    "import importlib\nimportlib.import_module('openfactory.adapters.agent.s3_session_store')",
    "__import__('openfactory.runtime.fargate.observe')",
    # the package is the core and the NAME is the vendor module — the review's planted offender
    "from openfactory.observability import dynamo as _reach_the_vendor",
    "from openfactory.runtime import fargate",
    "from openfactory.adapters.agent import s3_session_store",
    "from openfactory.runtime import (temporal, fargate)",
    # the module spelled in pieces
    "import importlib\nimportlib.import_module('openfactory.runtime.' + 'fargate')",
    "import importlib\nimportlib.import_module(f'openfactory.observability.{\"dynamo\"}')",
    "import importlib\nimportlib.import_module('openfactory.' 'runtime.fargate.launcher')",
    "import importlib\nimportlib.import_module('.fargate', 'openfactory.runtime')",
])
def test_the_sweep_sees_the_connector_however_it_is_spelled(spelling):
    """The positive twin: a scanner that silently stopped matching would report a clean tree."""
    assert imports_of_aws(ast.parse(spelling)), spelling


@pytest.mark.parametrize("spelling", [
    "from openfactory.observability.metrics import MetricRecord",
    "from openfactory import runtime",
    "from openfactory.runtime import temporal",
    "import importlib\nimportlib.import_module(module)",
    "import importlib\nimportlib.import_module(f'openfactory.runtime.{kind}')",
])
def test_the_sweep_ignores_the_core_importing_itself(spelling):
    """A core package, a core module and a module spelled from a variable are not the vendor."""
    assert not imports_of_aws(ast.parse(spelling)), spelling


# ── 2. the engine dispatches on a trait, never on a provider's name ─────────────────────────────

ENGINE_FILES = ("openfactory/runtime/temporal/activities.py", "openfactory/runtime/temporal/view.py",
                "openfactory/runtime/temporal/io.py", "openfactory/api/app.py")


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == name


def _membership_names(node: ast.AST, name: str) -> bool:
    """`x in ("fargate", "ecs")`, `in {"fargate"}`, `in ["fargate"]` — a comparator that is a
    literal collection holding the name."""
    return (isinstance(node, (ast.Tuple, ast.Set, ast.List))
            and any(_is_name(e, name) for e in node.elts))


def compares_to_provider(tree: ast.AST, name: str = "fargate") -> list[int]:
    """Every dispatch on the provider's name, wherever it hides: `x == "fargate"` / `!=`, the
    membership forms `x in ("fargate", …)` / `{…}` / `[…]`, a `match x: case "fargate":` arm and a
    dict dispatch `{"fargate": …}[x]` — the three spellings after the first were survivors the
    review fed this scanner (2026-08-26). Docstrings and comments are not compares, so prose that
    EXPLAINS the rule does not trip the guard."""
    lines: list[int] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            if any(_is_name(c, name) or _membership_names(c, name)
                   for c in [n.left, *n.comparators]):
                lines.append(n.lineno)
        elif isinstance(n, ast.MatchValue) and _is_name(n.value, name):
            lines.append(n.lineno)
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Dict) \
                and any(_is_name(k, name) for k in n.value.keys if k is not None):
            lines.append(n.lineno)
    return sorted(set(lines))


@pytest.mark.parametrize("rel", ENGINE_FILES)
def test_the_engine_never_compares_a_box_to_a_providers_name(rel):
    """The ratchet the workflow already had, extended to where the dispatch actually lived
    (activities.py:383/1072/1282/1343 and app.py:493 when this was written)."""
    lines = compares_to_provider(ast.parse((ROOT / rel).read_text()))
    assert not lines, f"{rel} dispatches on a provider's name at lines {lines} — ask the box's traits"


def test_the_compare_scanner_sees_the_dispatch_shape():
    src = textwrap.dedent('''
        def f(inp):
            """sandbox='fargate' is only prose here"""
            if inp.sandbox != "fargate":  # a comment naming fargate is prose too
                return 0
    ''')
    assert compares_to_provider(ast.parse(src)) == [4]


@pytest.mark.parametrize("dispatch", [
    'kind in ("fargate", "ecs")',        # the review's planted offender
    'kind in {"fargate"}',
    'kind in ["container", "fargate"]',
    'kind not in ("fargate",)',
    'match kind:\n    case "fargate":\n        pass',
    'match kind:\n    case "fargate" | "ecs":\n        pass',
    '{"fargate": remote, "container": local}[kind]',
])
def test_the_compare_scanner_sees_the_membership_and_match_shapes(dispatch):
    """The twin for the widened scanner: each membership, match and dict-dispatch spelling is a
    hit, and the hit is on the line the dispatch is written on."""
    src = "def f(kind, remote, local):\n" + textwrap.indent(dispatch, "    ") + "\n"
    assert compares_to_provider(ast.parse(src)), dispatch


@pytest.mark.parametrize("not_a_dispatch", [
    'x in ("container", "worktree")',
    'match kind:\n    case "container":\n        pass',
    '{"container": local}[kind]',
    'traits = {"fargate": remote}',      # a table, not a subscript on it
])
def test_the_compare_scanner_leaves_other_names_and_plain_tables_alone(not_a_dispatch):
    src = "def f(kind, x, remote, local):\n" + textwrap.indent(not_a_dispatch, "    ") + "\n"
    assert compares_to_provider(ast.parse(src)) == [], not_a_dispatch


# ── 3. the box axis: a stranger's remote box, end to end ────────────────────────────────────────

NOMAD = BoxTraits("nomad", remote=True, honours_image=True, idempotent=False, streams=False,
                  isolates_resources=True, transfers_state=True)


class _Tail:
    def __init__(self, events):
        self._events = events

    def fetch_new(self):
        return list(self._events)


class _NomadRunner:
    """A runner that records what the lifecycle asked of it."""

    def __init__(self):
        self.launched: list[tuple] = []
        self.stopped: list = []

    def launch(self, box, *, journal=None, variant="", extra_env=None, timeout=0, run_id=None):
        from openfactory.contracts import JobState, RunResult

        self.launched.append((box, variant, dict(extra_env or {}), run_id))
        return RunResult(ticket_id=box.issue, state=JobState.PR_OPEN, pr_url="https://x/pr/1")

    def stop(self, box):
        self.stopped.append(box)
        return 2

    def tail(self, project, issue):
        return _Tail([{"message": f"from nomad {project}#{issue}"}])


class _Synthetic:
    """An entry point whose target is an object made for the test."""

    def __init__(self, name, obj):
        self.name, self._obj = name, obj

    def load(self):
        return self._obj


@pytest.fixture
def nomad(monkeypatch):
    runner = _NomadRunner()
    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("box.nomad",
                              lambda: (NOMAD, no_local_adapter("nomad"), lambda **kw: runner)),))
    return runner


def test_a_plugin_box_is_known_on_the_activity_side_and_not_in_the_workflow(nomad):
    """The two lookups, and why there are two: the workflow's is pure and cannot see an add-on;
    the activity's reads the entry points."""
    assert installed_box_traits("nomad") == NOMAD
    with pytest.raises(ValueError, match="unknown box 'nomad'") as e:
        box_traits("nomad")
    assert "container" in str(e.value) and "nomad" not in str(e.value).split("known:")[1]


def test_a_plugin_boxs_runner_is_the_one_that_runs(nomad):
    assert remote_box("nomad") is nomad
    assert isinstance(remote_box("nomad"), RemoteBox)
    with pytest.raises(ValueError, match="remote"):
        build_sandbox("nomad")


def test_the_refusal_names_the_kind_a_stranger_installed(nomad):
    with pytest.raises(ValueError, match="nomad"):
        installed_box_traits("nomadd")


def test_a_local_box_has_no_remote_runner():
    with pytest.raises(ValueError, match="local"):
        remote_box("container")


class _LaunchOnly:
    """A launcher with no `stop`: every abnormal end would be an orphan, silently."""

    def launch(self, box, **kw):
        return None


@pytest.mark.parametrize("door", ["box.nomad", "box_runner.fargate"])
def test_a_runner_that_cannot_stop_is_refused_at_both_doors(monkeypatch, door):
    """Found by mutation: nothing handed the registry a runner that was not a `RemoteBox`, so the
    check that refuses one was decoration. Both doors — a stranger's whole row and the runner an
    add-on supplies for a box the core describes — are held to the same three methods."""
    if door == "box.nomad":
        point = _Synthetic(door, lambda: (NOMAD, no_local_adapter("nomad"), lambda **kw: _LaunchOnly()))
        kind = "nomad"
    else:
        point = _Synthetic(door, lambda **kw: _LaunchOnly())
        kind = "fargate"
    install(monkeypatch, declared_rows=False, extra=(point,))
    with pytest.raises(TypeError, match="RemoteBox"):
        remote_box(kind)


@pytest.mark.parametrize("row,reason", [
    ((NOMAD, no_local_adapter("nomad")), "no runner"),
    ((BoxTraits("nomad", remote=False, honours_image=True, idempotent=False, streams=True,
                isolates_resources=True, transfers_state=True),
      lambda **kw: object(), lambda **kw: object()), "remote runner"),
    ((BoxTraits("elsewhere", remote=True, honours_image=True, idempotent=False, streams=False,
                isolates_resources=True, transfers_state=True),
      no_local_adapter("nomad"), lambda **kw: object()), "describes 'elsewhere'"),
    (lambda **kw: object(), "must be"),
    (("nomad", lambda **kw: object()), "BoxTraits"),
])
def test_a_row_that_does_not_answer_for_itself_is_refused_not_defaulted(monkeypatch, row, reason):
    """A remote box without a runner is the orphaned task the `remote` trait exists to prevent; a
    plugin whose entry point names a bare builder has nowhere to say whether it is remote at all.
    Both are refused with the reason, never read as "a local box"."""
    install(monkeypatch, declared_rows=False, extra=(_Synthetic("box.nomad", lambda: row),))
    with pytest.raises(TypeError, match=reason):
        installed_box_traits("nomad")


def test_every_built_in_row_answered_for_itself_at_import():
    """The same check admits the shipped rows: remote ones carry a runner slot, local ones do not."""
    for kind, row in BOXES.items():
        assert (len(row) == 3) is row[0].remote, kind
        assert row[0].name == kind


def test_a_remote_row_without_a_runner_cannot_be_declared():
    from openfactory.adapters.sandbox.registry import _checked

    with pytest.raises(TypeError, match="no runner"):
        _checked({"nomad": (NOMAD, no_local_adapter("nomad"))})


def test_the_described_box_refuses_by_name_when_its_add_on_is_absent(monkeypatch):
    """The core describes `fargate` and does not implement it. Without the add-on the traits still
    answer (a history in flight needs them) and the runner refuses, naming the entry point."""
    install(monkeypatch, declared_rows=False)
    assert box_traits("fargate").remote is True
    with pytest.raises(RuntimeError, match="box_runner.fargate"):
        remote_box("fargate")


def test_the_described_boxs_runner_arrives_through_the_declared_entry_point(monkeypatch):
    install(monkeypatch, "box_runner.fargate")
    for k, v in {"OPENFACTORY_FARGATE_CLUSTER": "c", "OPENFACTORY_FARGATE_SUBNETS": "s",
                 "OPENFACTORY_FARGATE_SG": "g", "OPENFACTORY_FARGATE_TASKDEF": "t",
                 "OPENFACTORY_FARGATE_LOG_GROUP": "l", "AWS_DEFAULT_REGION": "eu-central-1"}.items():
        monkeypatch.setenv(k, v)
    runner = remote_box("fargate")
    assert isinstance(runner, RemoteBox)
    assert type(runner).__module__.startswith("openfactory.runtime.fargate")


# ── 4. the lifecycle reaches the plugin's launch AND its stop ───────────────────────────────────

@pytest.fixture
def project(tmp_path, monkeypatch):
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.registry import ProjectRegistry

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    (tmp_path / "repo").mkdir()
    p = Project(name="demo", repo_path=str(tmp_path / "repo"),
                tracker=ProviderRef(kind="github", repo="acme/demo"))
    ProjectRegistry().add(p)
    return p


def test_run_job_launches_a_remote_add_on_box_through_its_own_runner(nomad, project):
    """Before: `_do_run_job` built a LOCAL adapter for any kind not literally "fargate"."""
    from openfactory.runtime.temporal import activities

    result = activities._do_run_job(activities.RunJobInput(project="demo", issue="1",
                                                           sandbox="nomad"), "run-1")
    assert result.pr_url == "https://x/pr/1"
    assert len(nomad.launched) == 1
    box, variant, _env, run_id = nomad.launched[0]
    assert (box.project, box.issue, variant, run_id) == ("demo", "1", "", "run-1")


def test_stop_job_stops_a_remote_add_on_box_through_the_same_runner(nomad, project):
    """The other half. Before: `stop_job` returned 0 for any kind not literally "fargate" — the
    orphaned task, reported as a clean sweep."""
    from openfactory.runtime.temporal import activities

    stopped = asyncio.run(activities.stop_job(
        activities.RunJobInput(project="demo", issue="1", sandbox="nomad")))
    assert stopped == 2 and [b.issue for b in nomad.stopped] == ["1"]


def test_stop_job_has_nothing_to_stop_for_a_local_box(project):
    from openfactory.runtime.temporal import activities

    assert asyncio.run(activities.stop_job(
        activities.RunJobInput(project="demo", issue="1", sandbox="container"))) == 0


@pytest.mark.parametrize("phase", ["staging", "release"])
def test_promotion_runs_on_the_remote_add_on_box(nomad, project, phase):
    from openfactory.runtime.temporal import activities

    activities._run_promotion("demo", "1", phase, {"X": "y"}, "run-1", sandbox="nomad")
    _box, variant, env, _run_id = nomad.launched[0]
    assert variant == f"-{phase}" and env["OPENFACTORY_PROMOTE_PHASE"] == phase and env["X"] == "y"


def test_promotion_resolves_the_deployments_box_on_the_worker_not_in_the_workflow(nomad, project,
                                                                                 monkeypatch):
    """The promotion inputs are built inside the workflow body without a box, so `""` reaches the
    activity and the ACTIVITY asks the deployment. A `default_factory` reading the environment on
    the input itself was tried first and hung the promotion tests at the first
    `execute_activity(promote_staging, …)`: the factory ran under the workflow sandbox."""
    from openfactory.runtime.temporal import activities
    from openfactory.runtime.temporal.io import PromoteInput, ReleaseInput

    for model in (PromoteInput, ReleaseInput):
        field = model.model_fields["sandbox"]
        assert field.default == "" and field.default_factory is None, (
            f"{model.__name__}.sandbox resolves the box where the workflow builds it")
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "nomad")
    activities._run_promotion("demo", "1", "staging", {}, "run-1", sandbox="")
    assert [v for _b, v, _e, _r in nomad.launched] == ["-staging"]


def test_promotion_on_a_local_box_is_refused_by_name_not_by_a_vendors_keyerror(project):
    """Fix-time measurement: `promote_staging` had NO branch — it launched the vendor's task for
    every deployment, and a compose install whose manifest declared environments died at the
    promotion tail with `KeyError: missing Fargate env`. There is still no local promotion; the
    refusal now says so, and it is non-retryable because repeating cannot change the answer."""
    from temporalio.exceptions import ApplicationError

    from openfactory.runtime.temporal import activities

    with pytest.raises(ApplicationError, match="no implementation for the local 'container' box") as e:
        activities._run_promotion("demo", "1", "staging", {}, "run-1", sandbox="container")
    assert e.value.non_retryable


def _promotion_input_calls() -> dict[str, ast.Call]:
    """The two places the workflow builds a promotion input, by the input's name."""
    tree = ast.parse((ROOT / "openfactory/runtime/temporal/workflow.py").read_text())
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("PromoteInput", "ReleaseInput"):
            assert node.func.id not in calls, f"{node.func.id} is built twice"
            calls[node.func.id] = node
    assert set(calls) == {"PromoteInput", "ReleaseInput"}, sorted(calls)
    return calls


def test_the_workflow_names_the_jobs_box_on_both_promotion_inputs_behind_one_marker():
    """`PromoteInput(project=…, issue=…)` and `ReleaseInput(…)` were built with no box, so the
    promotion ran on the WORKER'S default while every other phase ran on the JOB'S — the field
    existed and nothing on the product path set it. Both sites now spread `_promotion_box(params,
    live=workflow.patched("promotion-box-kind"))`: the same marker at both, because a history that
    skipped one and took the other would name the box on release and not on staging."""
    for name, call in _promotion_input_calls().items():
        spreads = [kw.value for kw in call.keywords if kw.arg is None]
        boxes = [s for s in spreads if isinstance(s, ast.Call)
                 and getattr(s.func, "attr", "") == "_promotion_box"]
        assert len(boxes) == 1, f"{name} does not spread `_promotion_box(...)`: {ast.unparse(call)}"
        live = next((kw.value for kw in boxes[0].keywords if kw.arg == "live"), None)
        assert isinstance(live, ast.Call) and ast.unparse(live.func) == "workflow.patched", (
            f"{name}: `live=` is not `workflow.patched(...)` — {ast.unparse(boxes[0])}")
        assert [a.value for a in live.args if isinstance(a, ast.Constant)] == ["promotion-box-kind"]


def test_a_history_before_the_marker_keeps_the_deployments_box_and_a_new_one_names_the_jobs():
    """Both arms of the patch, on the pure helper the two sites share: `live=False` is what an
    in-flight job replays (no box → `""` → the activity resolves the deployment's, as before);
    `live=True` names the job's own box, add-on or not."""
    from openfactory.runtime.temporal.io import JobParams, PromoteInput
    from openfactory.runtime.temporal.workflow import JobWorkflow

    params = JobParams(project="p", issue="1", sandbox="nomad", box=NOMAD)
    assert JobWorkflow._promotion_box(params, live=False) == {}
    assert JobWorkflow._promotion_box(params, live=True) == {"sandbox": "nomad"}
    old = PromoteInput(project="p", issue="1", **JobWorkflow._promotion_box(params, live=False))
    assert old.sandbox == ""  # the activity's "resolve the deployment's box" fallback, unchanged


def test_the_review_pass_and_the_ci_repair_reach_the_remote_runner_too(nomad, project):
    from openfactory.runtime.temporal import activities

    activities._run_review_pass(activities.ReviewPassInput(
        project="demo", issue="1", pr_url="https://x/pr/1", sandbox="nomad"), "run-v1")
    activities._run_ci_repair(activities.CiRepairInput(
        project="demo", issue="1", pr_url="https://x/pr/1", sandbox="nomad"), "run-r1")
    assert [v for _b, v, _e, _r in nomad.launched] == ["-review", "-ci-repair"]


# ── 5. the workflow reads the stamped traits, and the stamp is written ──────────────────────────

def test_stamped_traits_win_and_an_unstamped_history_falls_back_to_the_built_in_table():
    from openfactory.runtime.temporal.io import JobParams

    assert JobParams(project="p", issue="1", sandbox="nomad", box=NOMAD).traits() is NOMAD
    # a history from before the field existed: no `box` key at all
    old = JobParams.model_validate_json('{"project": "p", "issue": "1", "sandbox": "container"}')
    assert old.box is None and old.traits() == box_traits("container")
    with pytest.raises(ValueError, match="unknown box 'nomad'"):
        JobParams(project="p", issue="1", sandbox="nomad").traits()


def test_the_stamp_survives_the_engines_serialisation():
    """It crosses into history as JSON; a dataclass that did not round-trip would deserialise as a
    dict and `traits()` would hand the workflow something with no `.remote`."""
    from temporalio.contrib.pydantic import pydantic_data_converter

    from openfactory.runtime.temporal.io import JobParams

    params = JobParams(project="p", issue="1", sandbox="nomad", box=NOMAD)
    payloads = asyncio.run(pydantic_data_converter.encode([params]))
    back = asyncio.run(pydantic_data_converter.decode(payloads, [JobParams]))[0]
    assert back.traits() == NOMAD and back.traits().remote is True


def test_start_jobs_writes_the_stamp(project, monkeypatch):
    """Reachability: a field nothing fills is a fallback that always runs."""
    from openfactory.runtime.temporal import activities, connection

    started: list = []

    class _Client:
        async def start_workflow(self, name, params, **kw):
            started.append(params)

    async def _connect():
        return _Client()

    monkeypatch.setattr(connection, "connect", _connect)
    asyncio.run(activities.start_jobs(activities.StartJobsInput(
        project="demo", issues=["1"], sandbox="container")))
    assert started and started[0].box == box_traits("container")


def test_start_jobs_stamps_an_add_ons_traits_from_the_installed_table(nomad, project, monkeypatch):
    """The reason the stamp exists, at its only writer: a box the built-in table has never heard
    of reaches the workflow as data. The container case above is answered identically by both
    lookups, so a `start_jobs` that asked the built-in `box_traits` stayed green there (a mutation
    survivor, 2026-08-24) — here it refuses `nomad` before a workflow is ever started."""
    from openfactory.runtime.temporal import activities, connection

    started: list = []

    class _Client:
        async def start_workflow(self, name, params, **kw):
            started.append(params)

    async def _connect():
        return _Client()

    monkeypatch.setattr(connection, "connect", _connect)
    asyncio.run(activities.start_jobs(activities.StartJobsInput(
        project="demo", issues=["7"], sandbox="nomad")))
    assert [p.box for p in started] == [NOMAD]
    assert started[0].traits().remote is True and started[0].sandbox == "nomad"


STREAMY = BoxTraits("streamy", remote=False, honours_image=True, idempotent=False, streams=True,
                    isolates_resources=False, transfers_state=True)


def test_a_plugin_box_that_streams_is_watched_and_one_that_does_not_is_unwatched_for_the_right_reason(
        nomad, project, monkeypatch, caplog):
    """`_watch_for` asked the BUILT-IN table, so a plugin box was refused before its `streams`
    was read and the log said "could not build a harness watcher (unknown box)" — a stranger's
    box that streams was never watched, and the reason given was the wrong one."""
    from openfactory.runtime.temporal import activities

    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("box.nomad",
                              lambda: (NOMAD, no_local_adapter("nomad"), lambda **kw: nomad)),
                   _Synthetic("box.streamy", lambda: (STREAMY, lambda **kw: object()))))
    watch = activities._watch_for(activities.RunJobInput(project="demo", issue="1",
                                                         sandbox="streamy"))
    assert isinstance(watch, activities.HarnessWatch) and watch.issue == "1"

    with caplog.at_level("INFO"):
        assert activities._watch_for(activities.RunJobInput(project="demo", issue="1",
                                                            sandbox="nomad")) is None
    assert "cannot be read while it runs" in caplog.text
    assert "could not build a harness watcher" not in caplog.text


def _is_a_table_lookup(name: str) -> bool:
    """`box_traits` and every `*_box_traits` — the built-in table and the installed one alike."""
    return name == "box_traits" or name.endswith("_box_traits")


def table_lookups(tree: ast.AST) -> list[int]:
    """Every CALL of a box-table lookup, however it is reached: a bare name, an attribute
    (`registry.box_traits(...)`), and a call that is only the head of a longer chain
    (`installed_box_traits(params.sandbox).remote` — the review's planted offender, which a
    scanner that matched a bare `box_traits` name alone waved through)."""
    lines: list[int] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) \
            else ""
        if _is_a_table_lookup(called):
            lines.append(n.lineno)
    return sorted(set(lines))


def test_the_workflow_asks_the_params_not_the_table():
    """Every trait question in the workflow body goes through `params.traits()`; a direct table
    lookup there — the built-in table OR the installed one, which is I/O — would refuse a plugin
    box during replay."""
    src = (ROOT / "openfactory/runtime/temporal/workflow.py").read_text()
    tree = ast.parse(src)
    via_params = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "traits"]
    direct = table_lookups(tree)
    assert not direct, f"the workflow looks the box up by kind at {direct}"
    assert len(via_params) >= 5, "the workflow stopped asking its params about the box"


@pytest.mark.parametrize("lookup", [
    "box_traits(params.sandbox)",
    "installed_box_traits(params.sandbox).remote",     # the review's planted offender
    "registry.box_traits(params.sandbox).idempotent",
    "registry.installed_box_traits(kind)",
    "x = box_traits(params.sandbox).remote and 1",
])
def test_the_lookup_scanner_sees_a_table_call_at_the_head_of_any_chain(lookup):
    src = "def f(params, kind, registry):\n    " + lookup + "\n"
    assert table_lookups(ast.parse(src)) == [2], lookup


@pytest.mark.parametrize("not_a_lookup", [
    "params.traits().remote",
    "box_traits",                     # a name, not a call
    "traits = params.box_traits",     # an attribute read, not a call
])
def test_the_lookup_scanner_leaves_the_params_alone(not_a_lookup):
    src = "def f(params):\n    " + not_a_lookup + "\n"
    assert table_lookups(ast.parse(src)) == [], not_a_lookup


# ── 6. the deployment's box is declared, never inferred from a vendor's variable ────────────────

@pytest.mark.parametrize("env,expected", [
    ({}, "container"),
    ({"OPENFACTORY_FARGATE_CLUSTER": "openfactory-sandbox"}, "container"),
    ({"OPENFACTORY_SANDBOX": "fargate"}, "fargate"),
    ({"OPENFACTORY_SANDBOX": "worktree", "OPENFACTORY_FARGATE_CLUSTER": "c"}, "worktree"),
    ({"OPENFACTORY_SANDBOX": ""}, "container"),
])
def test_the_box_kind_is_declared_or_the_container(monkeypatch, env, expected):
    from openfactory.runtime.temporal.io import default_sandbox

    for k in ("OPENFACTORY_SANDBOX", "OPENFACTORY_FARGATE_CLUSTER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert default_sandbox() == expected


@pytest.mark.parametrize("kind,expected", [("container", False), ("worktree", False),
                                           ("fargate", True), ("nomad", True)])
def test_the_panel_asks_the_boxs_traits_whether_jobs_are_remote(nomad, monkeypatch, kind, expected):
    from openfactory.api import app

    monkeypatch.delenv("OPENFACTORY_FARGATE_CLUSTER", raising=False)
    monkeypatch.setenv("OPENFACTORY_SANDBOX", kind)
    assert app._boxes_are_remote() is expected


def test_an_unknown_box_reads_as_local_on_the_panel_and_says_so(monkeypatch, caplog):
    """Measured before choosing: raising here is a 500 on every job page of a mistyped deployment,
    and the worker already refuses the kind by name when it starts a job."""
    from openfactory.api import app

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "typo")
    with caplog.at_level("WARNING"):
        assert app._boxes_are_remote() is False
    assert "typo" in caplog.text and "unknown" in caplog.text


def test_the_panel_follows_a_remote_job_through_the_rows_own_tail(nomad, project, monkeypatch):
    from openfactory.api import app

    monkeypatch.setenv("OPENFACTORY_SANDBOX", "nomad")
    assert app._events("demo", "1") == [{"message": "from nomad demo#1"}]


def test_a_missing_add_on_is_a_warning_naming_the_entry_point_not_an_idle_feed(project, monkeypatch,
                                                                             caplog):
    """view.py swallowed the tail's ImportError into `arns = []`, so a remote deployment without
    its add-on rendered a quiet feed for ever — absence read as compliance."""
    from openfactory.api import app

    install(monkeypatch, declared_rows=False)
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    with caplog.at_level("WARNING"):
        assert app._events("demo", "1") == []
    assert "box_runner.fargate" in caplog.text


def _names_called_in(node: ast.AST) -> set[str]:
    """Every bare name a call reaches in `node` — called directly, or handed to
    `asyncio.to_thread(...)` (the stream does the latter), or reached as `Name.attr(...)`."""
    names = set()
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        for a in [c.func, *c.args]:
            if isinstance(a, ast.Name):
                names.add(a.id)
            elif isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name):
                names.add(a.value.id)
    return names


def test_the_stream_builds_the_tail_the_same_way_as_the_one_shot_reader():
    """Structural, so the two readers cannot disagree about where a remote job's events are or
    how a missing add-on is reported: `_events` calls `_remote_tail`; the stream reaches it
    through `_StreamTail` (once per stream, with the bounded retry the tests below drive)."""
    src = (ROOT / "openfactory/api/app.py").read_text()
    tree = ast.parse(src)
    defs = {n.name: n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef)}
    assert {"_remote_tail", "_boxes_are_remote"} <= _names_called_in(defs["_events"])
    assert {"_StreamTail", "_boxes_are_remote"} <= _names_called_in(defs["job_stream"])
    assert "_remote_tail" in _names_called_in(defs["_StreamTail"])


@pytest.fixture
def tail_that_cannot_be_built(monkeypatch):
    """The reviewer's case: a remote deployment whose add-on is absent. Counts the builds."""
    from openfactory.adapters.sandbox import registry

    install(monkeypatch, declared_rows=False)
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "fargate")
    builds: list[int] = []
    real = registry.remote_box

    def _counting(kind, **kw):
        builds.append(1)
        return real(kind, **kw)

    monkeypatch.setattr(registry, "remote_box", _counting)
    return builds


def test_the_stream_builds_the_tail_once_and_backs_off_with_one_warning(tail_that_cannot_be_built,
                                                                        caplog):
    """Measured on the shipped code: 5 builds and 5 WARNINGs in 5 ticks, i.e. ~28,800 a day per
    open card. The schedule is pinned in ticks so it can be read: doubling waits, capped."""
    from openfactory.api import app

    stream = app._StreamTail("demo", "1")
    built_at: list[int] = []
    with caplog.at_level("DEBUG", logger="openfactory.panel"):
        for tick in range(1000):
            before = len(tail_that_cannot_be_built)
            assert stream.get(tick) is None
            if len(tail_that_cannot_be_built) > before:
                built_at.append(tick)
    assert built_at == [0, 2, 6, 14, 30, 62, 126, 254, 510, 810], built_at
    assert len(tail_that_cannot_be_built) == 10
    warnings = [r for r in caplog.records if r.levelname == "WARNING"
                and "event tail cannot be built" in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert "box_runner.fargate" in warnings[0].getMessage()
    # the retries are not silent to a DEBUG reader — only to the one who pages on WARNING
    assert sum(1 for r in caplog.records if r.levelname == "DEBUG"
               and "event tail cannot be built" in r.getMessage()) == 9
    assert stream.MAX_WAIT == 300 and stream.next_try - 810 == stream.MAX_WAIT


def test_a_tail_that_comes_up_after_failing_is_kept_and_said_once(tail_that_cannot_be_built,
                                                                  monkeypatch, caplog):
    from openfactory.adapters.sandbox import registry
    from openfactory.api import app

    stream = app._StreamTail("demo", "1")
    assert stream.get(0) is None and stream.get(1) is None  # tick 1 is not due: no build
    assert len(tail_that_cannot_be_built) == 1
    # the add-on arrives (the image was rebuilt) — the next DUE tick builds, later ticks reuse
    runner = _NomadRunner()
    monkeypatch.setattr(registry, "remote_box", lambda kind, **kw: runner)
    with caplog.at_level("INFO", logger="openfactory.panel"):
        assert stream.get(2) is not None
        first = stream.get(3)
    assert first is stream.get(999) and first.fetch_new() == [{"message": "from nomad demo#1"}]
    assert "is up after 1 failed builds" in caplog.text


def test_the_stream_generator_reaches_the_bounded_tail(tail_that_cannot_be_built, project,
                                                       monkeypatch, caplog):
    """The reviewer's own measurement, on the real generator: five ticks with no journal on a
    remote deployment missing its add-on. Before: 5 builds, 5 warnings. The 86400-iteration loop
    is cut by making the tick sleep the stop."""
    import asyncio as _asyncio

    from openfactory.api import app

    class _Req:
        headers: dict = {}

    ticks: list[float] = []

    async def _sleep(seconds):
        ticks.append(seconds)
        if len(ticks) == 5:
            raise StopAsyncIteration  # ends the generator after five ticks

    monkeypatch.setattr(app.asyncio, "sleep", _sleep)

    async def _drive():
        response = await app.job_stream("demo", "1", _Req())
        frames = []
        try:
            async for frame in response.body_iterator:
                frames.append(frame)
        except (StopAsyncIteration, RuntimeError):  # the fifth sleep ends the generator
            pass
        return frames

    with caplog.at_level("DEBUG", logger="openfactory.panel"):
        frames = _asyncio.run(_drive())
    assert ticks == [3, 3, 3, 3, 3] and frames == [": hb\n\n"] * 5
    assert len(tail_that_cannot_be_built) == 2, "ticks 0 and 2 build; 1, 3 and 4 wait"
    assert sum(1 for r in caplog.records if r.levelname == "WARNING"
               and "event tail cannot be built" in r.getMessage()) == 1


def test_a_malformed_add_on_row_reads_as_local_on_the_panel_not_as_a_500(monkeypatch, caplog):
    """`_boxes_are_remote` caught ValueError only; an add-on whose row does not answer for itself
    is a TypeError from `_check_row` — the same configuration defect one layer in, and it was a
    500 on every job page while the unknown kind beside it was a warning."""
    from openfactory.api import app

    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("box.broken", lambda: (lambda **kw: None)),))
    monkeypatch.setenv("OPENFACTORY_SANDBOX", "broken")
    with caplog.at_level("WARNING"):
        assert app._boxes_are_remote() is False
    assert "'broken'" in caplog.text and "must be (traits, build)" in caplog.text


# ── 7. metrics: the read contract is on the port, and no reader falls through ───────────────────

class _RowsWithATableName:
    """A third-party sink that happens to have a `table_name` attribute — the duck the readers
    used to mistake for one vendor's client."""

    table_name = "not-a-dynamodb-table"

    def __init__(self):
        self.rows = [{"pk": "acme", "kind": "job", "ticket": "1", "ts": "2026-08-01T00:00:00",
                      "cost_usd": 1.0}]

    def record(self, rec):
        return True

    def scan(self):
        return list(self.rows)

    def records_of_kind(self, project, kind, *, limit=500):
        return [r for r in self.rows if r["pk"] == project and r["kind"] == kind][-limit:]


class _WritesOnly:
    def record(self, rec):
        return True


class _ScanOnly:
    """Half the port: `scan` and no `records_of_kind`. `hasattr(sink, "scan")` hands it back and
    the memory reader dies on AttributeError — the case that tells isinstance-on-the-Protocol from
    the attribute check the docstring says was removed (a mutation survivor, 2026-08-24)."""

    def record(self, rec):
        return True

    def scan(self):
        return []


@pytest.fixture
def no_boto(monkeypatch):
    import sys

    tried: list[str] = []

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("boto3", "botocore"):
                tried.append(name)
                raise ImportError(name)
            return None

    for cached in [m for m in sys.modules if m.split(".")[0] in ("boto3", "botocore")]:
        monkeypatch.delitem(sys.modules, cached, raising=False)
    blocker = _Block()
    sys.meta_path.insert(0, blocker)
    yield tried
    sys.meta_path.remove(blocker)


def test_the_read_contract_is_a_protocol_the_shipped_sinks_answer_honestly(tmp_path):
    from openfactory.observability.metrics import (
        InMemoryMetricsSink,
        NullMetricsSink,
        ReadableSink,
    )
    from openfactory.observability.sqlite_metrics import SqliteMetricsSink

    assert isinstance(SqliteMetricsSink(tmp_path / "m.db"), ReadableSink)
    assert isinstance(_RowsWithATableName(), ReadableSink)
    assert not isinstance(NullMetricsSink(), ReadableSink)
    assert not isinstance(InMemoryMetricsSink(), ReadableSink)
    assert not isinstance(_WritesOnly(), ReadableSink)
    assert not isinstance(_ScanOnly(), ReadableSink)


def test_a_sink_with_half_the_port_is_not_read_and_is_said_out_loud(monkeypatch, caplog):
    """Through `_configured_sink` itself: a sink with `scan` and no `records_of_kind` is not a
    `ReadableSink`, so it is reported as recording-but-unreadable and never handed to a reader
    that would die on the missing half."""
    from openfactory.api.metrics_view import _configured_sink, scan_all_or_raise
    from openfactory.observability.query import records_of_kind

    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("metrics.halfport", lambda **kw: _ScanOnly()),))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "halfport")
    with caplog.at_level("WARNING"):
        assert _configured_sink() is None
    assert "'halfport'" in caplog.text and "cannot be read back" in caplog.text
    assert scan_all_or_raise() == [] and records_of_kind("acme", "job") == []


def test_a_third_party_sink_with_a_table_name_is_read_and_no_vendor_client_is_reached(
        monkeypatch, no_boto):
    """Probes C and D: with `OPENFACTORY_METRICS_TABLE` set, one reader starved this sink to `[]`
    and the other routed it to a vendor's client, on the strength of an attribute NAME."""
    from openfactory.api.metrics_view import scan_all_or_raise
    from openfactory.observability.query import records_of_kind

    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("metrics.acme", lambda **kw: _RowsWithATableName()),))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "acme")
    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")

    assert [r["ticket"] for r in scan_all_or_raise()] == ["1"]
    assert [r["ticket"] for r in records_of_kind("acme", "job")] == ["1"]
    assert records_of_kind("globex", "job") == []
    assert not no_boto, no_boto


@pytest.mark.parametrize("kind", ["memory", "null"])
def test_a_sink_that_cannot_read_never_falls_through_to_a_vendors_table(monkeypatch, no_boto, kind):
    """Probes A and B: the registry said `memory`/`null`, the table variable was set, and both
    readers reached for boto3."""
    from openfactory.api.metrics_view import scan_all_or_raise
    from openfactory.observability.query import records_of_kind

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", kind)
    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")

    assert scan_all_or_raise() == [] and records_of_kind("acme", "job") == []
    assert not no_boto, no_boto


def test_a_sink_that_records_and_cannot_be_read_is_said_out_loud(monkeypatch, caplog):
    """`memory` keeps rows and cannot hand them back; that is the cost dashboard and the agents'
    memory silently blind, and it is logged as such. `null` kept nothing, so nothing is missing."""
    from openfactory.api.metrics_view import _configured_sink

    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "memory")
    with caplog.at_level("WARNING"):
        assert _configured_sink() is None
    assert "cannot be read back" in caplog.text

    caplog.clear()
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "null")
    with caplog.at_level("WARNING"):
        assert _configured_sink() is None
    assert "cannot be read back" not in caplog.text


def test_the_explicit_table_override_is_registry_shaped(monkeypatch):
    """`table_name=` is the operator's override. It builds the CONFIGURED sink's kind through the
    registry — here the vendor row the deployment's table variable implies — so where the add-on
    is absent it is refused by name, and where a row answers to that name it is the row that
    answers, never a class imported by the core."""
    from openfactory.memory import transcript
    from openfactory.observability.query import records_of_kind

    asked: list[dict] = []

    def _fake_dynamodb(**kw):
        asked.append(kw)
        return _RowsWithATableName()

    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "the-deployments-table")
    install(monkeypatch, declared_rows=False, extra=(_Synthetic("metrics.dynamodb", _fake_dynamodb),))
    assert [r["ticket"] for r in records_of_kind("acme", "job", table_name="t1", region="r1")] == ["1"]
    assert isinstance(transcript._sink_for(table_name="t2", region="r2"), _RowsWithATableName)
    assert asked == [{"table": "t1", "region": "r1"}, {"table": "t2", "region": "r2"}]

    install(monkeypatch, declared_rows=False)
    with pytest.raises(ValueError, match="unknown metrics sink 'dynamodb'"):
        records_of_kind("acme", "job", table_name="t1")


def test_the_table_override_points_the_CONFIGURED_sink_never_a_vendor_spelled_in_the_core(
        monkeypatch, no_boto):
    """The three readers spelled `"dynamodb"` by heart, so `table_name=` MEANT one vendor while
    the import-graph guard — blind to a string — stayed green. Now the override reaches whatever
    sink the deployment declares, with the table, and a deployment that declares none is refused
    by name rather than handed a null store that drops the override in silence."""
    from openfactory.api.metrics_view import scan_all_or_raise
    from openfactory.memory import transcript
    from openfactory.observability.query import records_of_kind

    asked: list[dict] = []

    def _acme(**kw):
        asked.append(kw)
        return _RowsWithATableName()

    install(monkeypatch, declared_rows=False, extra=(_Synthetic("metrics.acme", _acme),))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "acme")
    monkeypatch.setenv("OPENFACTORY_METRICS_TABLE", "openfactory-job-metrics")  # a vendor's hint, ignored
    assert [r["ticket"] for r in scan_all_or_raise(table_name="t1", region="r1")] == ["1"]
    assert [r["ticket"] for r in records_of_kind("acme", "job", table_name="t2")] == ["1"]
    assert isinstance(transcript._sink_for(table_name="t3"), _RowsWithATableName)
    assert asked == [{"table": "t1", "region": "r1"}, {"table": "t2", "region": None},
                     {"table": "t3", "region": None}]
    assert not no_boto, no_boto

    monkeypatch.delenv("OPENFACTORY_METRICS_SINK")
    monkeypatch.delenv("OPENFACTORY_METRICS_TABLE")
    with pytest.raises(ValueError, match="'t4' was named, but this deployment's metrics sink is "
                                         "'null', which holds no table"):
        records_of_kind("acme", "job", table_name="t4")


def _the_three_table_overrides():
    from openfactory.api.metrics_view import scan_all_or_raise
    from openfactory.memory import transcript
    from openfactory.observability.query import records_of_kind

    return (lambda t: scan_all_or_raise(table_name=t),
            lambda t: records_of_kind("acme", "job", table_name=t),
            lambda t: transcript._sink_for(table_name=t))


@pytest.mark.parametrize("kind", ["null", "sqlite", "memory"])
def test_a_table_named_on_a_shipped_sink_is_refused_by_name_at_all_three_doors(monkeypatch,
                                                                              tmp_path, kind):
    """Measured by the review (2026-08-26): with `sqlite` the override died on
    `KeyError: 'path'` in the builder, and with `memory` the readers died on AttributeError while
    the deleter was handed a fresh empty store as though it held the table — the vendor's-KeyError
    class the same branch condemns in `_run_promotion`. Now every shipped kind is refused by name,
    the configured kind in the sentence, at each of the three doors."""
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", kind)
    monkeypatch.setenv("OPENFACTORY_METRICS_DB", str(tmp_path / "m.db"))
    for door in _the_three_table_overrides():
        with pytest.raises(ValueError, match=f"'t' was named, but this deployment's metrics sink "
                                             f"is {kind!r}, which holds no table"):
            door("t")


def test_every_shipped_metrics_sink_says_what_it_is_addressed_by():
    """The twin: the refusal names each shipped kind because `TABLELESS_METRICS_SINKS` covers
    the shipped table exactly — a row added to one and not the other is caught here, not by the
    builder's own KeyError the moment an operator names a table."""
    from openfactory.observability.registry import METRICS_SINKS, TABLELESS_METRICS_SINKS

    assert set(TABLELESS_METRICS_SINKS) == set(METRICS_SINKS)
    assert all(isinstance(how, str) and how for how in TABLELESS_METRICS_SINKS.values())


def test_a_table_named_on_an_add_on_that_holds_one_reaches_it_with_the_table(monkeypatch):
    """The positive half of the refusal: a kind outside the shipped table is not refused — the
    override is handed to the add-on's builder, table and region intact."""
    from openfactory.observability.registry import configured_metrics_sink

    asked: list[dict] = []
    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("metrics.acme", lambda **kw: asked.append(kw) or _RowsWithATableName()),))
    monkeypatch.setenv("OPENFACTORY_METRICS_SINK", "acme")
    assert isinstance(configured_metrics_sink(table="t", region="r"), _RowsWithATableName)
    assert asked == [{"table": "t", "region": "r"}]


#: The core modules that reach a sink by an operator's table name.
READERS_WITH_A_TABLE_OVERRIDE = ("openfactory/api/metrics_view.py",
                                 "openfactory/observability/query.py",
                                 "openfactory/memory/transcript.py")


def vendor_kinds_spelled(tree: ast.AST, kind: str = "dynamodb") -> list[int]:
    """Lines where a string constant names the vendor's KIND — as an argument or a value, not as
    prose: docstrings and bare expression statements are skipped, a comparison to it is not."""
    prose = {id(n.value) for n in ast.walk(tree)
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == kind and id(n) not in prose]


@pytest.mark.parametrize("rel", READERS_WITH_A_TABLE_OVERRIDE)
def test_no_reader_spells_the_vendors_kind(rel):
    tree = ast.parse((ROOT / rel).read_text())
    assert vendor_kinds_spelled(tree) == [], f"{rel} names the vendor's kind by heart"


def test_the_kind_scanner_sees_a_spelled_kind_and_ignores_prose():
    """The twin: an argument, a comparison and a dict value are seen; a docstring is not."""
    seen = ast.parse(textwrap.dedent('''
        def f():
            """the dynamodb one stringifies"""
            build("dynamodb", table=t)
            if kind == "dynamodb":
                return {"kind": "dynamodb"}
    '''))
    assert vendor_kinds_spelled(seen) == [4, 5, 6]
    prose = ast.parse('"""only the dynamodb sink does this"""\nx = 1\n"dynamodb"\n')
    assert vendor_kinds_spelled(prose) == []


# ── 8. the token pool comes from a declared source with a free default ──────────────────────────

def test_the_token_pool_defaults_to_the_environment_and_is_not_inferred(monkeypatch):
    from openfactory.adapters.agent.token_pool import token_pool, token_pool_source_kind

    monkeypatch.delenv("OPENFACTORY_TOKEN_POOL_SOURCE", raising=False)
    monkeypatch.setenv("OPENFACTORY_FARGATE_CLUSTER", "c")
    monkeypatch.setenv("OPENFACTORY_SSM_PREFIX", "/acme")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    assert token_pool_source_kind() == "env"
    assert token_pool()["source"] in ("env", "n/a")


def test_an_unknown_token_pool_source_is_refused_naming_what_is_known(monkeypatch):
    from openfactory.adapters.agent.token_pool import token_pool

    install(monkeypatch, declared_rows=False, extra=(_Synthetic("token_pool.vault", lambda **kw: {}),))
    with pytest.raises(ValueError, match="vault") as e:
        token_pool("vaultt")
    assert "env" in str(e.value)


def test_a_strangers_token_pool_source_is_the_one_that_answers(monkeypatch):
    from openfactory.adapters.agent.token_pool import token_pool

    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("token_pool.vault", lambda **kw: {"count": 3, "source": "vault"}),))
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "vault")
    assert token_pool()["source"] == "vault"


def test_the_panel_reports_the_env_pool_when_the_declared_source_will_not_answer(monkeypatch,
                                                                                 caplog):
    from openfactory.api import app

    def _down(**kw):
        raise RuntimeError("vault is down")

    install(monkeypatch, declared_rows=False, extra=(_Synthetic("token_pool.vault", _down),))
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "vault")
    with caplog.at_level("INFO"):
        meta = app._token_pool_meta()
    assert meta["source"] in ("env", "n/a") and "vault" in caplog.text
    outage = [r for r in caplog.records if "vault" in r.getMessage()]
    assert [r.levelname for r in outage] == ["INFO"], "an outage is weather, not configuration"


def test_a_declared_token_pool_source_nobody_installed_is_a_WARNING_not_weather(monkeypatch,
                                                                                 caplog):
    """A typo, or the add-on that declares the row absent from the image: the panel folded it
    into the same INFO line as an outage, so a configuration defect read as a bad day."""
    from openfactory.api import app

    install(monkeypatch, declared_rows=False)
    monkeypatch.setenv("OPENFACTORY_TOKEN_POOL_SOURCE", "ssm")
    with caplog.at_level("INFO"):
        meta = app._token_pool_meta()
    assert meta["source"] in ("env", "n/a")
    said = [r for r in caplog.records if "'ssm'" in r.getMessage()]
    assert [r.levelname for r in said] == ["WARNING"], [r.getMessage() for r in caplog.records]
    assert "unknown" in said[0].getMessage() and "known: env" in said[0].getMessage()


# ── 9. the session store axis is open, and the vendor row registers like a stranger's ───────────

def test_a_strangers_session_store_is_the_one_that_is_built(monkeypatch):
    from openfactory.adapters.agent.session_store import build_session_store

    sentinel = object()
    install(monkeypatch, declared_rows=False,
            extra=(_Synthetic("session_store.minio", lambda **kw: sentinel),))
    assert build_session_store("minio") is sentinel
    with pytest.raises(ValueError, match="minio"):
        build_session_store("minioo")


# ── 10. the platform's own connector rows resolve through the door a stranger uses ──────────────

def test_every_declared_entry_point_resolves_to_a_callable():
    from vendor_addons import Point, declared, require

    require()
    rows = declared()
    assert {"box_runner.fargate", "metrics.dynamodb", "session_store.s3", "token_pool.ssm"} <= set(rows)
    for name, target in rows.items():
        assert callable(Point(name, target).load()), name


def test_a_declaration_that_names_nothing_is_caught():
    """The positive twin of the resolver: a `module:attr` that does not exist raises here rather
    than being read as a row nobody asked for."""
    from vendor_addons import Point

    # a module that STAYS in the public tree, so the wrong-attribute case is an AttributeError
    # there too (the vendor module it named until 2026-08-26 leaves with its package)
    with pytest.raises(AttributeError):
        Point("metrics.nope", "openfactory.observability.registry:no_such_builder").load()
    with pytest.raises(ModuleNotFoundError):
        Point("metrics.nope", "openfactory.observability.nope:build").load()


def test_the_declared_rows_build_what_their_axis_asks_for(monkeypatch, tmp_path):
    from openfactory.adapters.agent.session_store import SessionStore, build_session_store
    from openfactory.observability.metrics import ForgettingSink, MetricsSink, ReadableSink
    from openfactory.observability.registry import build_metrics_sink

    require("metrics.dynamodb", "session_store.s3")
    install(monkeypatch)
    sink = build_metrics_sink("dynamodb", table="t", path=None)
    assert isinstance(sink, MetricsSink) and isinstance(sink, ReadableSink)
    assert isinstance(sink, ForgettingSink), "the vendor row lost the right to be forgotten"
    assert sink.table_name == "t"
    assert isinstance(build_session_store("s3", bucket="b"), SessionStore)


def _rows_of(dist) -> dict[str, str]:
    """The group's rows as ONE distribution's own metadata declares them — never the union
    `entry_points(group=…)` serves, which holds every installed add-on's rows too."""
    from openfactory import plugins

    return {p.name: p.value for p in dist.entry_points if p.group == plugins.GROUP}


def test_the_metadata_guard_reads_ONE_distribution_and_not_the_group():
    """Verify the verifier: with an add-on's rows installed beside the core's, only the asked
    distribution's are read, a console script is not a row, and a core row that differs from
    the declaration is still seen."""
    from types import SimpleNamespace

    from openfactory import plugins

    def point(name, value, group=plugins.GROUP):
        return SimpleNamespace(name=name, value=value, group=group)

    core = SimpleNamespace(entry_points=[
        point("metrics.dynamodb", "openfactory.observability.dynamo:build"),
        point("openfactory", "openfactory.cli:app", group="console_scripts")])
    add_on = SimpleNamespace(entry_points=[
        point("metrics.dynamodb", "openfactory_aws.observability.dynamo:build"),
        point("box_runner.fargate", "openfactory_aws.runtime.fargate.box:runner")])
    assert _rows_of(core) == {"metrics.dynamodb": "openfactory.observability.dynamo:build"}, (
        "the console script leaked into the group's rows")
    assert _rows_of(add_on) == {
        "metrics.dynamodb": "openfactory_aws.observability.dynamo:build",
        "box_runner.fargate": "openfactory_aws.runtime.fargate.box:runner"}
    assert _rows_of(SimpleNamespace(entry_points=[])) == {}


def test_the_installed_metadata_agrees_with_the_declaration():
    """`importlib.metadata` serves what `pip install -e addons/<package>` wrote, not what that
    package's pyproject says now. Per PACKAGE, by distribution name: one not installed at all is
    SKIPPED with the remedy, never read as agreement; one installed from another checkout is
    skipped too (its rows are that tree's); one installed from THIS checkout must carry exactly
    the rows its pyproject declares — a fresh install (CI's `make install`, an image build)
    proves the wiring, a stale one is told to reinstall. And the CORE's own distribution must
    declare NO row: the four cloud rows lived in the core's metadata until 2026-08-26, which
    made the public wheel name modules it does not ship.

    THIS DISTRIBUTION'S ROWS, NOT THE GROUP'S. `entry_points(group=…)` is the union over every
    installed distribution, and an add-on installed beside the core — the production shape — puts
    ITS rows in that set: a guard reading the union compared a stranger's targets with our
    pyproject and went red while the core's own metadata was merely stale (3724056, 2026-08-26).
    `_rows_of` reads one distribution's own metadata; the twin below plants two."""
    import json
    from importlib.metadata import PackageNotFoundError, distribution

    from vendor_addons import declared_by, packages, require

    rows_of = _rows_of

    def source_of(dist) -> str:
        raw = dist.read_text("direct_url.json")
        return json.loads(raw).get("url", "") if raw else ""

    try:
        core = distribution("openfactory")
    except PackageNotFoundError:
        pytest.skip("the core is not installed — run `pip install -e .`")
    if rows_of(core):
        pytest.skip("the core's editable install predates the rows leaving its pyproject — run "
                    "`pip install -e .` to refresh its metadata")

    require()
    for name, package_dir in packages().items():
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            pytest.skip(f"{name} is not installed — run `pip install -e addons/{package_dir.name}`")
        source = source_of(dist)
        if source and source != package_dir.as_uri():
            pytest.skip(f"{name} is installed from {source}, not from this checkout")
        assert rows_of(dist) == declared_by(package_dir), (
            f"{name}'s installed metadata disagrees with addons/{package_dir.name}/pyproject.toml "
            f"— run `pip install -e addons/{package_dir.name}` to refresh it")


# ── 11. the reference deployment declares the box it runs on ────────────────────────────────────
#
# `infra/` stays in the private repository and leaves the public cut. These guards are about the
# reference deployment, which exists only where `infra/` does — so they SKIP by name when it is
# absent (`terraform_text.require`), and assert where it is present. The inference this branch
# removed (`fargate` from OPENFACTORY_FARGATE_CLUSTER, `ssm` from a cluster variable) was what
# kept that deployment working without saying so; nothing else guards it now.

#: (terraform file, the variables it must set to a literal, and to what).
REFERENCE_DEPLOYMENT_DECLARES = (
    ("worker_service.tf", {"OPENFACTORY_SANDBOX": "fargate"}),
    ("panel_service.tf", {"OPENFACTORY_SANDBOX": "fargate", "OPENFACTORY_TOKEN_POOL_SOURCE": "ssm"}),
    ("panel_apprunner.tf", {"OPENFACTORY_SANDBOX": "fargate", "OPENFACTORY_TOKEN_POOL_SOURCE": "ssm"}),
)


@pytest.mark.parametrize("tf_file,expected", REFERENCE_DEPLOYMENT_DECLARES,
                         ids=[row[0] for row in REFERENCE_DEPLOYMENT_DECLARES])
def test_the_reference_deployment_declares_its_box_and_its_token_pool_source(tf_file, expected):
    """After the merge `infra/deploy.sh` ships a worker that resolves `default_sandbox()` with no
    inference: without OPENFACTORY_SANDBOX every job runs in `container` on a task with no docker
    daemon, the panel reads local journals only, and the promotion tail refuses non-retryably.
    The guard that pinned the old inference was deleted with it; this is its replacement."""
    import terraform_text

    terraform_text.require()
    declared = terraform_text.literal_env(terraform_text.files()[tf_file])
    for name, value in expected.items():
        assert declared.get(name) == value, (
            f"infra/terraform/{tf_file} sets {name}={declared.get(name)!r}, not {value!r} — the "
            f"reference deployment no longer infers it")


def test_what_the_reference_deployment_declares_resolves_through_the_registries(monkeypatch):
    """The literal in the terraform must be a kind the code answers for, with the platform's own
    add-ons installed: a remote box for the worker, and a declared token-pool row for the panel."""
    import terraform_text
    from vendor_addons import declared

    from openfactory.adapters.agent import token_pool as pool

    terraform_text.require()
    install(monkeypatch)
    for tf_file, expected in REFERENCE_DEPLOYMENT_DECLARES:
        env = terraform_text.literal_env(terraform_text.files()[tf_file])
        assert installed_box_traits(env["OPENFACTORY_SANDBOX"]).remote is True, tf_file
        if "OPENFACTORY_TOKEN_POOL_SOURCE" in expected:
            source = env["OPENFACTORY_TOKEN_POOL_SOURCE"]
            assert f"{pool.AXIS}.{source}" in declared(), (tf_file, source)


def test_the_terraform_reader_sees_both_spellings_and_skips_expressions():
    """The twin, on the shared reader: an ECS row and an App Runner row are read, a comment is
    not, and a value that is a terraform expression is not a literal."""
    import terraform_text

    text = terraform_text.strip_comments(textwrap.dedent('''
        environment = [
          # { name = "OPENFACTORY_SANDBOX", value = "commented-out" },
          { name = "OPENFACTORY_SANDBOX", value = "fargate" },  # trailing
          { name = "OPENFACTORY_FARGATE_CLUSTER", value = aws_ecs_cluster.this.name },
        ]
        runtime_environment_variables = {
          OPENFACTORY_TOKEN_POOL_SOURCE = "ssm"
          OPENFACTORY_SSM_PREFIX        = var.ssm_prefix
        }
    '''))
    assert terraform_text.literal_env(text) == {"OPENFACTORY_SANDBOX": "fargate",
                                                "OPENFACTORY_TOKEN_POOL_SOURCE": "ssm"}

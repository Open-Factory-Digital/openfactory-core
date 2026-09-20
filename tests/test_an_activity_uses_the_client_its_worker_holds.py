"""An activity uses the engine client the worker that runs it already holds (#217).

Five activities — `available_slots` on EVERY poller tick, `start_jobs`, `notify_coordinator`,
`notify_coordinator_say`, `techlead_watch` — called `connection.connect()` each time they ran, on
the worker's one long-lived loop: a new gRPC channel (on Temporal Cloud a TLS handshake and an
API-key exchange as well), used for one or two calls and dropped, in a process that was already
holding a connected client built from the same three facts. The installed SDK has nothing to close
a client with, so a dropped one waits in a reference cycle for a collection nobody schedules.

THREE KINDS OF CASE, because each one can be green while the other two are broken:

  * COUNTED. Each of the five is executed N times as an activity whose worker holds a recording
    client, with `Client.connect` — the library, where a socket is actually opened, the same place
    `conftest` puts its barrier — replaced by a counter. ZERO opens, and the recording client is
    the one that was used. Counting `connection.connect` instead would have let the panel's pool
    (`view.connect`) or a direct `Client.connect` walk past.
  * THE REFUSALS. Outside an activity, in a `def` activity, and in an environment built with no
    client, the seam says which of the three it is and what to do — and never connects instead.
  * STRUCTURAL, parsed with `ast`. No module that defines an activity imports or calls a
    `connect`, and the SDK call is spelled in exactly one function. It is what stops the SIXTH
    activity bringing the habit back, which no counted case over five names can do — and it is
    proven able to fail on planted twins.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.testing import ActivityEnvironment

import openfactory.runtime.temporal.activities as acts
from openfactory.runtime.temporal.io import (
    CoordinatorItem,
    CoordinatorSayInput,
    StartJobsInput,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "openfactory"

#: How many executions each counted case drives. Six is what #209 measured the shape with
#: (`1, 2, 3, 4, 5, 6` established connections on one loop), so red reads as the same number.
N = 6


# ── the doubles: TWO engines, so "which one was used" has an answer ─────────────────────────────

class _Handle:
    async def query(self, _name):
        return None

    async def signal(self, _name, *, args=None):
        return None


class _Engine:
    """Just enough engine client for the five, and a record of every call made on it."""

    def __init__(self, role: str) -> None:
        self.role = role
        self.calls: list[str] = []

    async def list_workflows(self, _query: str):
        self.calls.append("list_workflows")
        for nothing in ():
            yield nothing

    async def start_workflow(self, name, *_args, **_kw):
        self.calls.append(f"start_workflow:{name}")

    def get_workflow_handle(self, wf_id: str):
        self.calls.append(f"get_workflow_handle:{wf_id}")
        return _Handle()


@pytest.fixture
def engines(monkeypatch):
    """`(held, opened)`: the client the worker holds, and every client the library was asked to
    open. THE ADDRESS IS DECLARED so the old shape reaches the library and is COUNTED there —
    without it `address()` refuses first and the red would be about the environment."""
    from temporalio.client import Client

    monkeypatch.setenv("TEMPORAL_ADDRESS", "engine.example:7233")
    monkeypatch.delenv("TEMPORAL_ENDPOINT", raising=False)
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    monkeypatch.delenv("TEMPORAL_TLS_CERT", raising=False)
    monkeypatch.delenv("TEMPORAL_TLS_KEY", raising=False)
    held = _Engine("held by the worker")
    opened: list[_Engine] = []

    async def _open(*_args, **_kwargs):
        opened.append(_Engine("opened by the activity"))
        return opened[-1]

    monkeypatch.setattr(Client, "connect", _open)
    return held, opened


@pytest.fixture
def a_quiet_floor(monkeypatch):
    """Everything the five reach for EXCEPT the engine, pinned — so the only door left is the one
    being counted."""
    from openfactory.contracts.project import Project, ProviderRef
    from openfactory.memory import store as loop_store

    project = Project(name="acme", repo_path="/tmp/acme",
                      tracker=ProviderRef(kind="github", repo="acme/acme"))
    monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self, name: project)
    monkeypatch.setattr(acts.ProjectRegistry, "list", lambda self: [project])
    monkeypatch.setattr(acts, "_land_product_proposals", lambda *a, **k: [])
    monkeypatch.setattr(acts, "_repoint_product_orphans", lambda *a, **k: [])
    monkeypatch.setattr(acts, "_queued_tickets", lambda p: [])
    monkeypatch.setattr(acts, "_recent_causes", lambda n: {})
    monkeypatch.setattr(acts, "_watch_history", lambda n: {})
    monkeypatch.setattr(acts, "_remember_watch", lambda n, said: None)
    monkeypatch.setattr(acts, "_finding_reminders", lambda n, ledger, lang="": [])
    monkeypatch.setattr(loop_store, "read", lambda name: [])
    monkeypatch.setattr(loop_store, "write", lambda name, loops, **kw: len(loops))

    async def _no_release(_project, _client):
        return ""

    monkeypatch.setattr(acts, "_offer_the_release_to_the_client", _no_release)


#: (the activity, its arguments, the call it must have made ON THE HELD CLIENT). The third column
#: is what makes "zero connects" mean "used the worker's" rather than "did nothing": two of the
#: five swallow every engine failure by design, and would report zero opens from a dead branch.
FIVE = [
    pytest.param(acts.available_slots, (), "list_workflows", id="available_slots"),
    pytest.param(acts.start_jobs,
                 (StartJobsInput(project="acme", issues=["12"], sandbox="container"),),
                 "start_workflow:JobWorkflow", id="start_jobs"),
    pytest.param(acts.notify_coordinator,
                 (CoordinatorItem(project="acme", issue="12", job_id="openfactory-acme-12"),),
                 "start_workflow:CoordinatorWorkflow", id="notify_coordinator"),
    pytest.param(acts.notify_coordinator_say,
                 (CoordinatorSayInput(project="acme", text="a sentence", kind="toast"),),
                 "start_workflow:CoordinatorWorkflow", id="notify_coordinator_say"),
    pytest.param(acts.techlead_watch, ("acme",), "list_workflows", id="techlead_watch"),
]


# ── 1. counted ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("fn", "args", "made"), FIVE)
async def test_N_executions_open_ZERO_engine_clients(fn, args, made, engines, a_quiet_floor):
    """THE DEFECT, by the number. On `main` this reads `6 opened` for each of the five."""
    held, opened = engines

    for _ in range(N):
        await ActivityEnvironment(client=held).run(fn, *args)

    assert len(opened) == 0, (
        f"{N} executions of `{fn.__name__}` opened {len(opened)} engine client(s) of their own, "
        f"in a worker that was already holding one")
    # …AND THE WORK WAS DONE ON THE HELD ONE. This is also what holds the five to `async def`, the
    # only kind the worker hands its client to: a `def` one refuses on the first execution above.
    assert held.calls.count(made) == N, (
        f"`{fn.__name__}` did not do its work on the client its worker holds: {N} executions "
        f"made {held.calls.count(made)} `{made}` call(s) there — {held.calls!r}")


# ── 2. the refusals ─────────────────────────────────────────────────────────────────────────────

def test_outside_an_activity_the_seam_refuses_BY_NAME_and_says_what_each_caller_does_instead(
        engines):
    """There is no worker here, so there is no client to hand over — and connecting instead would
    be the old habit behind a new name. The sentence names the three doors that DO exist."""
    _held, opened = engines

    with pytest.raises(acts.NoEngineClientHere) as refused:
        acts.engine_client()

    said = str(refused.value)
    assert "outside a running activity" in said, said
    assert "connection.connect" in said and "view.connect" in said, said
    assert "ActivityEnvironment(client=" in said, said
    assert opened == [], "the seam opened a client of its own rather than refuse"


@pytest.mark.parametrize(("fn", "args", "made"), FIVE)
async def test_each_of_the_five_called_BARE_refuses_rather_than_connect(
        fn, args, made, engines, a_quiet_floor):
    """The role these functions do NOT have: nothing in the package calls one as a plain helper
    (the poller and the workflows execute them as activities), so a bare call is a test or a
    mistake — and it hears so, including from the two that swallow every ENGINE failure: the
    seam is asked outside their `try`, because its refusal is never the engine's."""
    _held, opened = engines

    with pytest.raises(acts.NoEngineClientHere, match="outside a running activity"):
        await fn(*args)

    assert opened == []


async def test_a_DEF_activity_is_told_it_is_the_wrong_kind():
    """What `activity.client()` raises there is a bare `RuntimeError("No client available…")`.
    The seam says WHICH activity and what to change, and marks it non-retryable: the SDK's
    default policy would otherwise spend the whole retry budget re-asking a question about the
    function's own signature."""
    @activity.defn(name="a_def_activity")
    def a_def_activity() -> object:
        return acts.engine_client()

    with pytest.raises(acts.NoEngineClientHere) as refused:
        ActivityEnvironment(client=_Engine("held by the worker")).run(a_def_activity)

    said = str(refused.value)
    assert "async def" in said and "asyncio.to_thread" in said, said
    assert refused.value.non_retryable is True
    assert refused.value.type == "NoEngineClientHere"


async def test_an_environment_built_with_NO_client_is_told_how_to_pass_one():
    """The third way to have none, and the one a test author meets."""
    @activity.defn(name="an_async_activity")
    async def an_async_activity() -> object:
        return acts.engine_client()

    with pytest.raises(acts.NoEngineClientHere, match=r"ActivityEnvironment\(client="):
        await ActivityEnvironment().run(an_async_activity)


async def test_inside_an_async_activity_the_seam_IS_the_workers_client():
    held = _Engine("held by the worker")

    @activity.defn(name="an_async_activity")
    async def an_async_activity() -> object:
        return acts.engine_client()

    assert await ActivityEnvironment(client=held).run(an_async_activity) is held


# ── 3. structural: the sixth activity cannot bring the habit back ───────────────────────────────

def _is_activity_defn(decorator: ast.expr) -> bool:
    """`@activity.defn`, `@activity.defn(name=…)`, `@defn`."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr == "defn"
    return isinstance(target, ast.Name) and target.id == "defn"


def _activities_in(tree: ast.AST) -> list[str]:
    return [node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and any(_is_activity_defn(d) for d in node.decorator_list)]


def engine_doors_in(source: str) -> list[str]:
    """Every way a module that DEFINES AN ACTIVITY reaches for an engine client of its own.

    THE WHOLE MODULE, not only the decorated functions: `techlead_watch` hands its client to
    `_offer_the_release_to_the_client` and `_terminal_outcome`, and a helper one call away from an
    activity that connects for itself is the same defect with the decorator out of sight.

    BY NAME, AND ANY OWNER: `connect` imported from anywhere, `<anything>.connect(…)` called, and
    `Client` imported from the SDK. An alias defeats a check keyed on `connection.connect`, and
    this module has no other thing called `connect` to confuse it with — measured: zero hits in
    5,000 lines once the five are gone. A module with no activity in it is not this guard's
    business and answers `[]`."""
    tree = ast.parse(source)
    if not _activities_in(tree):
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "connect":
                    found.append(f"line {node.lineno}: imports `connect` from `{node.module}`")
                if alias.name == "Client" and (node.module or "").startswith("temporalio"):
                    found.append(f"line {node.lineno}: imports the SDK's `Client`")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "connect":
                found.append(f"line {node.lineno}: calls `{ast.unparse(func)}(…)`")
            elif isinstance(func, ast.Name) and func.id == "connect":
                found.append(f"line {node.lineno}: calls `connect(…)`")
    return found


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_module_that_defines_an_activity_opens_an_engine_client_of_its_own():
    with_activities = 0
    offenders: list[str] = []
    for path in _modules():
        source = path.read_text()
        if _activities_in(ast.parse(source)):
            with_activities += 1
        offenders += [f"{path.relative_to(ROOT)} {door}" for door in engine_doors_in(source)]

    assert with_activities >= 1, "the guard found no activity anywhere — it is reading nothing"
    assert not offenders, (
        "an activity module reaches for an engine client of its own; an activity asks "
        "`engine_client()`, which is the client its worker already holds (#217):\n  "
        + "\n  ".join(offenders))


_TWIN_HEAD = "from temporalio import activity\n\n"

TWINS = [
    pytest.param(
        "@activity.defn\nasync def sixth() -> None:\n"
        "    from openfactory.runtime.temporal.connection import connect\n\n"
        "    client = await connect()\n",
        2, id="the-old-habit-verbatim"),
    pytest.param(
        "from openfactory.runtime.temporal import connection\n\n"
        "@activity.defn(name='sixth')\nasync def sixth() -> None:\n"
        "    client = await connection.connect()\n",
        1, id="through-the-module"),
    pytest.param(
        "@activity.defn\nasync def sixth() -> None:\n"
        "    from openfactory.runtime.temporal import view as tv\n\n"
        "    client = await tv.connect()\n",
        1, id="through-the-panels-pool"),
    pytest.param(
        "@activity.defn\nasync def sixth() -> None:\n"
        "    from temporalio.client import Client\n\n"
        "    client = await Client.connect('engine:7233')\n",
        2, id="straight-to-the-library"),
    pytest.param(
        "async def _helper():\n"
        "    from openfactory.runtime.temporal.connection import connect as dial\n\n"
        "    return await dial()\n\n\n"
        "@activity.defn\nasync def sixth() -> None:\n    client = await _helper()\n",
        1, id="aliased-in-a-helper-one-call-away"),
]


@pytest.mark.parametrize(("twin", "doors"), TWINS)
def test_the_structural_guard_CAN_FAIL(twin, doors):
    """A planted sixth activity, five ways. A guard that answered `[]` to these would answer `[]`
    to anything."""
    assert len(engine_doors_in(_TWIN_HEAD + twin)) == doors, engine_doors_in(_TWIN_HEAD + twin)


def test_a_module_with_NO_activity_is_not_this_guards_business():
    """`worker.py`, `starter.py` and `schedule.py::main` are entry points that make one client per
    process or per command, deliberately. The guard must not read them as offenders."""
    entry_point = ("from openfactory.runtime.temporal.connection import connect\n\n"
                   "async def main():\n    client = await connect()\n")
    assert engine_doors_in(entry_point) == []


def _sdk_client_calls(tree: ast.AST) -> list[str]:
    """The functions in which `activity.client` is spelled — by reference, called or not."""
    sites: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute) and node.attr == "client"
                    and isinstance(node.value, ast.Name) and node.value.id == "activity"):
                sites.append(fn.name)
    return sites


def test_the_SDK_call_is_spelled_ONCE_in_the_package_and_the_five_ask_the_seam():
    """ONE seam, not five edits that each spell `activity.client()`: the next activity that needs
    the engine has to find the seam and its refusals, not an SDK call whose own errors are a bare
    `RuntimeError`."""
    spelled: list[str] = []
    for path in _modules():
        spelled += [f"{path.relative_to(ROOT)}::{name}"
                    for name in _sdk_client_calls(ast.parse(path.read_text()))]
    assert spelled == ["openfactory/runtime/temporal/activities.py::engine_client"], spelled

    tree = ast.parse((PACKAGE / "runtime/temporal/activities.py").read_text())
    asks = {fn.name for fn in ast.walk(tree)
            if isinstance(fn, ast.AsyncFunctionDef)
            and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "engine_client" for n in ast.walk(fn))}
    five = {"available_slots", "start_jobs", "notify_coordinator", "notify_coordinator_say",
            "techlead_watch"}
    assert five <= asks, f"these no longer ask the seam: {sorted(five - asks)}"

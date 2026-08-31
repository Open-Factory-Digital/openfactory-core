"""A `setup:` command that fails must stop the job and say which one (ADR-0037 D3).

Both call sites threw the result away:

    for cmd in self.manifest.setup:
        self.sandbox.run(workspace=ws, command=cmd, timeout=_SETUP_TIMEOUT)

`sandbox.run` returns `(exit_code, output)`. Neither `machine.py:358` nor `machine.py:733` looked at
it. A `pip install` that 404s, a `dotnet restore` that cannot reach a private feed, an `npm ci`
against a lockfile mismatch — none of them produce an event, a state change or a message. The agent
is then handed a broken environment, and the failure surfaces one layer later as a test failure or
an agent that flails, pointing at the wrong thing entirely.

THIS IS THE MOST IMPORTANT LINE IN THE SYSTEM FOR A NON-PYTHON CLIENT, and its result was
discarded. The box image is Python; ADR-0037 lets the client bring their own, but until they do —
and even after, for their app's dependencies — `setup:` is the only place a toolchain comes from.
Every C#/serverless onboarding failure lands here first.

WHY IT IS A HARD STOP AND NOT A WARNING. Running the agent anyway spends real money to produce a
diff written against an environment that does not work, and then validations fail for a reason that
has nothing to do with the diff. Parking with the command and its output is both cheaper and true.
`NEEDS_REFINEMENT` is the wrong park (the ticket is fine); this is an environment fault, which is
what `FAILED` with a diagnosis means here.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.contracts import AcceptanceCriterion, JobState, Manifest, Ticket

pytest_plugins = ["tests.test_walking_skeleton"]


class _SetupFails:
    """A sandbox whose second setup command fails, like a private feed refusing auth."""

    def __init__(self, inner, failing="dotnet restore"):
        self._inner, self._failing = inner, failing
        self.ran: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def run(self, *, workspace, command, timeout):
        self.ran.append(command)
        if command == self._failing:
            return 1, "error NU1301: Unable to load the service index for source\n  https://pkgs…"
        return self._inner.run(workspace=workspace, command=command, timeout=timeout)


def _ticket():
    return Ticket(id="#1", title="add feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


def test_a_failing_setup_stops_the_job(repo: Path, tmp_path: Path):
    """The whole point: no agent pass against a broken environment."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from tests.test_walking_skeleton import FakeAgent, FakeTracker, _runner

    class _CountingAgent(FakeAgent):
        calls = 0

        def execute(self, **kw):
            type(self).calls += 1
            return super().execute(**kw)

    tracker = FakeTracker(_ticket())
    manifest = Manifest(setup=["echo setup1", "dotnet restore"],
                        validate={"test": "true"})
    sandbox = _SetupFails(WorktreeSandbox(root=tmp_path / "wt"))
    runner = _runner(repo, tracker, manifest, tmp_path, agent=_CountingAgent(), sandbox=sandbox)

    result = runner.run("#1")

    assert _CountingAgent.calls == 0, "the agent ran against an environment that failed to build"
    assert result.state == JobState.FAILED, result.state


def test_the_failing_command_is_named(repo: Path, tmp_path: Path):
    """"setup failed" is as useless as silence when there are four setup commands."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from tests.test_walking_skeleton import FakeTracker, _runner

    tracker = FakeTracker(_ticket())
    manifest = Manifest(setup=["echo setup1", "dotnet restore"],
                        validate={"test": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path,
                     sandbox=_SetupFails(WorktreeSandbox(root=tmp_path / "wt")))

    result = runner.run("#1")

    assert "dotnet restore" in (result.note or ""), result.note


def test_the_output_reaches_the_human(repo: Path, tmp_path: Path):
    """The exit code says it broke; the output says why. A private-feed 401 is diagnosable in one
    read and unguessable without it."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from tests.test_walking_skeleton import FakeTracker, _runner

    tracker = FakeTracker(_ticket())
    manifest = Manifest(setup=["dotnet restore"], validate={"test": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path,
                     sandbox=_SetupFails(WorktreeSandbox(root=tmp_path / "wt")))

    runner.run("#1")

    said = " ".join(tracker.comments)
    assert "NU1301" in said, f"the output never reached the ticket: {tracker.comments}"


def test_setup_stops_at_the_first_failure(repo: Path, tmp_path: Path):
    """Later commands presuppose the earlier ones. Running them produces a second, misleading
    error on top of the real one."""
    from openfactory.adapters.sandbox import WorktreeSandbox
    from tests.test_walking_skeleton import FakeTracker, _runner

    tracker = FakeTracker(_ticket())
    manifest = Manifest(setup=["dotnet restore", "dotnet build"], validate={"test": "true"})
    sandbox = _SetupFails(WorktreeSandbox(root=tmp_path / "wt"))
    runner = _runner(repo, tracker, manifest, tmp_path, sandbox=sandbox)

    runner.run("#1")

    assert "dotnet build" not in sandbox.ran, sandbox.ran


def test_a_passing_setup_changes_nothing(repo: Path, tmp_path: Path):
    """The pilot runs `pip install` here every job. This must stay invisible when it works."""
    from tests.test_walking_skeleton import FakeForge, FakeTracker, _runner

    tracker = FakeTracker(_ticket())
    forge = FakeForge()
    manifest = Manifest(setup=["true", "true"], validate={"test": "true"})
    runner = _runner(repo, tracker, manifest, tmp_path, forge=forge)

    result = runner.run("#1")

    assert forge.opened is not None
    assert result.state in (JobState.PR_OPEN, JobState.DONE, JobState.MERGED), result.state


def test_the_repair_path_is_guarded_too(repo: Path, tmp_path: Path):
    """`repair_ci` has its own setup loop (machine.py:733) with the same discarded result. A CI
    repair against a broken environment produces a second failing CI run and a confused agent."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "openfactory/orchestrator/machine.py"
    bare: list[str] = []
    for node in ast.walk(ast.parse(src.read_text())):
        # a bare `self.sandbox.run(...)` as a statement — result thrown away
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        rendered = ast.unparse(node.value)
        if rendered.startswith("self.sandbox.run(") and "_SETUP_TIMEOUT" in rendered:
            bare.append(f"machine.py:{node.lineno} — {rendered[:80]}")
    assert not bare, (
        "a setup command's exit code is discarded, so a broken environment is invisible:\n  "
        + "\n  ".join(bare)
    )

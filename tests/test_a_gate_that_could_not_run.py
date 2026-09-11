"""A gate that could not RUN is not a diff that needs repairing.

FOUND FROM THE OTHER END. Two guards in `test_walking_skeleton.py` had been failing on one
developer machine for weeks, filed as an intermittent flake and caveated in every PR body since.
They are not intermittent: they declare components on `stack: python`, inherit the preset's
`ruff check .` / `bandit -r . -ll -q` / `mypy .`, and the walking skeleton runs its gates for real
on the HOST — so they resolve against the PATH of whoever started pytest. Measured on one commit,
minutes apart: 2 failed without `.venv/bin` on PATH, 2 passed with it. The failure log said
`/bin/sh: 1: ruff: not found`, and the run had gone into `agent.repair`.

WHICH IS THE PRODUCTION DEFECT, WEARING A TEST'S CLOTHES. `passed=(rc == 0)` makes a shell's
"command not found" indistinguishable from a linter's verdict on the code, so the platform spends
the project's whole repair budget — real model calls, real money — asking an agent to fix a diff
that is not what is wrong. No agent can install `ruff`. Three attempts later the job parks as
*"validations failed after 3 repair attempt(s)"*, and the operator who reads that goes and looks
at the diff.

It is reachable in production, `box_prove` notwithstanding: that proof covers the gates a
component declares when the image is built, and says nothing about a gate added to the manifest
since, a repo-wide role `component_gates` deliberately skips, or an image rebuilt without a tool.

`passed` STAYS FALSE THROUGHOUT. An unrun gate has proven nothing, and reading "could not run" as
"fine" is the one direction this codebase never takes. What changes is who is asked to act: a
failing gate is a diff to repair, and a gate that could not run is a box to fix.
"""

from __future__ import annotations

import pytest
import test_walking_skeleton as spine

from openfactory.contracts import (
    AcceptanceCriterion,
    AgentRunResult,
    JobState,
    Manifest,
    Ticket,
    ValidationResult,
)
from openfactory.observability import InMemoryEventSink
from openfactory.orchestrator.machine import _failure_log, _never_ran_reason
from openfactory.orchestrator.validation import could_not_run

#: the real-git harness — a bare origin and a repo with one commit — borrowed rather than rebuilt
repo = spine.repo

#: A command no PATH resolves. Long and specific on purpose: a name that could plausibly exist
#: would make this suite depend on what is installed, which is the defect under test.
MISSING = "openfactory-not-a-real-tool-9f3a"


class _NoRepairAgent:
    """Writes a file and refuses to be repaired — the cost proof. `repair` is a paid model call,
    and a missing binary is not something it can fix."""

    def __init__(self) -> None:
        self.repairs = 0

    def execute(self, *, sandbox, workspace, context) -> AgentRunResult:
        (workspace.path / "feature.py").write_text("VALUE = 42\n")
        return AgentRunResult(ok=True, summary="added feature.py", cost_usd=0.01,
                              actions=["Edit: feature.py"])

    def repair(self, *, sandbox, workspace, context, failure_log) -> AgentRunResult:
        self.repairs += 1
        raise AssertionError(
            f"repair ran on a gate that never executed — the failure log it was handed is "
            f"{failure_log!r}")


def _ticket() -> Ticket:
    return Ticket(id="#41", title="feature", objective="add a feature", repo="o/app",
                  acceptance_criteria=[AcceptanceCriterion(text="feature.py exists")])


# ── 1. the shell's verdict on the COMMAND, told apart from a gate's verdict on the code ──────────

def test_the_shells_not_found_line_is_what_comes_back():
    """The line, not a boolean: it names the tool, and naming the tool is the whole point — a
    person can act on `ruff: not found` and cannot act on `True`."""
    said = could_not_run(127, "/bin/sh: 1: ruff: not found")

    assert said == "/bin/sh: 1: ruff: not found"


def test_an_unexecutable_file_counts_too():
    """126 is the shell's other answer about the command itself: found, and not runnable."""
    assert could_not_run(126, "/bin/sh: 1: ./gates.sh: Permission denied")


def test_a_gate_that_exits_127_ON_ITS_OWN_is_still_a_failure():
    """THE CHEAP DIRECTION. A gate is an arbitrary command and may exit 127 for reasons of its
    own; treating that as 'could not run' would park a job that repair could have fixed. The code
    AND the shell's own words are both required."""
    assert could_not_run(127, "FAILED tests/test_x.py::test_y - assert 1 == 2") == ""


def test_a_failing_gate_that_merely_MENTIONS_not_found_is_not_one_either():
    """The twin from the other side: a test suite reporting a missing fixture says 'not found' in
    its own output all the time, and it ran."""
    assert could_not_run(1, "E  fixture 'db' not found") == ""


# ── 2. nobody is asked to fix a missing binary ───────────────────────────────────────────────────

def test_the_repair_brief_leaves_out_the_gate_that_never_ran():
    """The mixed case, which is the only one that reaches `_failure_log` at all: a real failure
    beside an ADVISORY gate whose tool is missing. `ruff: not found` in a repair brief is an
    instruction to fix code that is not broken, and the agent has no way to say so — it will edit
    something."""
    brief = _failure_log([
        ValidationResult(name="test", command="pytest", exit_code=1, passed=False,
                         output_tail="1 failed"),
        ValidationResult(name="security", command="bandit -r .", exit_code=127, passed=False,
                         advisory=True, output_tail="sh: bandit: not found",
                         unrunnable="sh: bandit: not found"),
    ])

    assert "pytest" in brief
    assert "bandit" not in brief


def test_the_hold_names_the_gate_and_the_tool():
    reason = _never_ran_reason([
        ValidationResult(name="lint", command="ruff check .", exit_code=127, passed=False,
                         unrunnable="/bin/sh: 1: ruff: not found"),
    ])

    assert "`lint`" in reason and "ruff" in reason
    assert "repair" in reason.lower(), "the reason does not say why nothing was attempted"


def test_an_advisory_gate_that_could_not_run_holds_NOTHING():
    """C-37's rule, unchanged by this: advisory gates report and never decide. A licence scanner
    missing from the box must not park a job."""
    assert _never_ran_reason([
        ValidationResult(name="security", command="bandit -r .", exit_code=127, passed=False,
                         advisory=True, unrunnable="sh: bandit: not found"),
    ]) == ""


# ── 3. end to end, against a real sandbox and a command that really is not there ─────────────────

def test_a_missing_tool_holds_the_job_without_spending_one_repair(repo, tmp_path):
    """THE MEASUREMENT THIS CHANGE IS FOR. Before: three paid repair attempts and a hold that
    blames the diff. After: zero attempts and a sentence naming what is missing."""
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "lint": f"{MISSING} check ."})
    agent = _NoRepairAgent()
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#41")

    assert agent.repairs == 0, "the repair budget was spent on a binary that is not installed"
    assert result.repair_attempts == 0
    assert result.state is JobState.ON_HOLD
    assert "`lint`" in (result.note or "") and MISSING in (result.note or ""), (
        f"the hold does not name what is missing: {result.note!r}")
    assert runner.forge.opened is None, "a diff nothing could validate reached a pull request"


def test_the_result_keeps_the_gate_UNPASSED(repo, tmp_path):
    """An unrun gate is never green. The distinction is about who acts, never about lowering the
    floor — `all_passed` must still refuse."""
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "lint": f"{MISSING} check ."})
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent())

    result = runner.run("#41")

    lint = next(v for v in result.validations if v.name == "lint")
    assert lint.passed is False and lint.unrunnable
    assert result.all_passed is False


def test_the_journal_says_it_could_not_run_rather_than_that_it_failed(repo, tmp_path):
    """What the operator reads on the panel. `lint: FAIL` sends them to the diff."""
    events = InMemoryEventSink()
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "lint": f"{MISSING} check ."})
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent(),
                           events=events)

    runner.run("#41")

    lines = [e.message for e in events.events if e.kind == "validation"]
    assert any("COULD NOT RUN" in line for line in lines), lines
    assert not any(line.startswith("lint: FAIL") for line in lines), lines


def test_an_advisory_tool_that_is_missing_does_not_stop_the_pull_request(repo, tmp_path):
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={
        "test": "true",
        "security": {"command": f"{MISSING} -r .", "advisory": True},
    })
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent(),
                           reviewer=spine.FakeReviewer())

    result = runner.run("#41")

    assert result.state is JobState.PR_OPEN, result.note


def test_the_pull_request_does_not_say_a_missing_tool_REPORTED_anything(repo, tmp_path):
    """The one surface an unrunnable gate can still reach a person through — the blocking case
    opens no pull request at all. The advisory summary said *"reported findings"* about every
    advisory gate that was not green, which about a tool that never ran is a claim describing a
    reading nobody made."""
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={
        "test": "true",
        "security": {"command": f"{MISSING} -r .", "advisory": True},
    })
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent(),
                           reviewer=spine.FakeReviewer())

    runner.run("#41")

    body = (runner.forge.opened or {}).get("body", "")
    assert "could not run" in body, f"the pull request hides that a gate never ran:\n{body}"
    assert "reported findings" not in body, (
        "the pull request tells the reader a missing tool found something")


# ── 4. the independent reviewer is not told the code broke something nobody checked ─────────────

def _review_input():
    from openfactory.adapters.reviewer.base import ReviewInput

    return ReviewInput(
        ticket=_ticket(), diff="diff --git a/f b/f",
        validations=[
            ValidationResult(name="test", command="pytest", exit_code=0, passed=True),
            ValidationResult(name="lint", command="ruff check .", exit_code=127, passed=False,
                             advisory=True, unrunnable="/bin/sh: 1: ruff: not found"),
        ])


@pytest.mark.parametrize("build", ["harness", "claude_code"])
def test_the_reviewers_prompt_says_a_gate_never_ran(build):
    """THE ONE READER WHOSE WHOLE JOB IS INDEPENDENCE. `- lint: FAIL (exit 127)` tells a reviewer
    the diff broke a check that was never performed, and its instructions are to hunt for evidence
    the change is wrong — so the platform would have handed it evidence that does not exist.

    Both reviewers, because the rendering is duplicated: `harness.build_review_prompt` says it is
    shared by every implementation and `claude_code._prompt` carries its own copy. The duplication
    is older than this change; what must not happen is one of them learning the distinction.
    """
    if build == "harness":
        from openfactory.adapters.reviewer.harness import build_review_prompt

        prompt = build_review_prompt(_review_input())
    else:
        from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

        prompt = ClaudeCodeReviewer._prompt(ClaudeCodeReviewer.__new__(ClaudeCodeReviewer),
                                            _review_input())

    assert "COULD NOT RUN" in prompt, prompt
    assert "ruff: not found" in prompt, "the reviewer is not told WHICH command was missing"
    assert "lint: FAIL" not in prompt, (
        "the reviewer is told the code failed a check that never ran")
    assert "test: PASS" in prompt, "the gates that did run stopped being reported"


# ── 5. and the factory files it against itself, on its own board ─────────────────────────────────

def _watch_impediments(monkeypatch) -> dict[str, list]:
    """The seam, recorded. `report`/`resolved` are guarded end to end in
    `test_factory_asks_for_help.py`; what is unproven here is the WIRE — that the job path reaches
    them at all, with the right cause, and closes what it opened."""
    from openfactory.ops import impediment

    seen: dict[str, list] = {"filed": [], "closed": []}
    monkeypatch.setattr(impediment, "report",
                        lambda project, cause, detail="", **kw: seen["filed"].append(
                            (getattr(project, "name", "?"), cause, detail)) or "PLAT-1")
    monkeypatch.setattr(impediment, "resolved",
                        lambda project, cause, evidence="", **kw: seen["closed"].append(
                            (getattr(project, "name", "?"), cause, evidence)) is None)
    return seen


class _Project:
    name = "acme"


def test_a_missing_tool_becomes_an_impediment_on_the_FACTORY_s_board(repo, tmp_path, monkeypatch):
    """A hold is the right sentence for this ticket and the wrong home for the problem. The image
    is missing a tool, so every ticket touching that component holds too — an outage arriving as a
    queue of individually reasonable holds, which is the shape this board exists to make countable
    and owned."""
    from openfactory.ops.impediment import GATE_CANNOT_RUN

    seen = _watch_impediments(monkeypatch)
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "lint": f"{MISSING} check ."})
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent())
    runner.project = _Project()

    runner.run("#41")

    assert [c for _, c, _ in seen["filed"]] == [GATE_CANNOT_RUN], seen
    assert MISSING in seen["filed"][0][2], "the impediment does not name the missing command"
    assert seen["closed"] == [], "it filed and closed the same trouble in one pass"


def test_gates_that_RUN_close_the_impediment_they_did_not_open(repo, tmp_path, monkeypatch):
    """ADR-0021: nobody marks it resolved. The gates running IS the evidence the box has the tool
    again, and the next job that gets them to run is what closes the ticket."""
    from openfactory.ops.impediment import GATE_CANNOT_RUN

    seen = _watch_impediments(monkeypatch)
    tracker = spine.FakeTracker(_ticket())
    runner = spine._runner(repo, tracker, Manifest(validate={"test": "true"}), tmp_path,
                           agent=_NoRepairAgent(), reviewer=spine.FakeReviewer())
    runner.project = _Project()

    runner.run("#41")

    assert [c for _, c, _ in seen["closed"]] == [GATE_CANNOT_RUN], seen
    assert seen["filed"] == []


def test_a_gate_that_RAN_AND_FAILED_files_nothing(repo, tmp_path, monkeypatch):
    """The client's code is not the platform's impediment. A failing suite belongs to the repair
    loop and to the client's own ticket, and putting it on the factory's board would turn a board
    that must stay countable into a copy of every job that ever went red."""
    seen = _watch_impediments(monkeypatch)
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "false"}, repair_max_attempts=1)
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=spine.FakeRepairAgent())
    runner.project = _Project()

    runner.run("#41")

    assert seen["filed"] == [], "a red suite was filed as a platform failure"


def test_a_runner_with_no_project_still_holds_and_simply_files_nothing(repo, tmp_path, monkeypatch):
    """`build_runner` passes a project and most constructions do not. Absent, the hold — which is
    what stops the money being spent — must be untouched; only the bookkeeping is lost."""
    seen = _watch_impediments(monkeypatch)
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "true", "lint": f"{MISSING} check ."})
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=_NoRepairAgent())

    result = runner.run("#41")

    assert result.state is JobState.ON_HOLD and result.repair_attempts == 0
    assert seen["filed"] == [] and seen["closed"] == []


def test_a_gate_that_RAN_and_failed_still_goes_to_repair(repo, tmp_path):
    """The twin that keeps this change honest. `false` exits 1 having run — that IS a verdict on
    the code, and the repair loop must still spend an attempt on it."""
    tracker = spine.FakeTracker(_ticket())
    manifest = Manifest(validate={"test": "false"}, repair_max_attempts=1)
    agent = spine.FakeRepairAgent()
    runner = spine._runner(repo, tracker, manifest, tmp_path, agent=agent)

    result = runner.run("#41")

    assert result.repair_attempts == 1, "a real gate failure stopped reaching the repair loop"
    assert result.state is JobState.ON_HOLD
    assert "repair attempt" in (result.note or "")

"""#205 — one author writes the close of a repair brief: whoever knows what the words ARE.

WHAT THE AGENT WAS TOLD. Every repair leaves the orchestrator through one door, the harness port's
`repair(failure_log=…)`, and six kinds of words go through it: a gate's output, a forge check's
failing log, a person's review comment, the reviewer's findings, the suppressions a diff added,
and an unfinished executor's last summary. Every shipped harness row said something of its own
over all six — the reference row closed with "The validations reported above FAILED. Fix the code
so they pass — do not change the tests to make them pass", the other three led with "The
project's own validation gates FAILED on your change … never silence a gate or delete a test",
and all four rendered the words under "What the project's gates reported / Failures from the last
run". So a reviewer who asked for a test to change was overruled in the same brief.

WHAT IS HELD HERE, by executing the REAL `repair` of every shipped row behind the REAL orchestrator
callers, and reading the prompt that reached the box:

    the words     are inside the brief's DATA fence, whoever wrote them
    the close     is the caller's, OUTSIDE every fence — a sentence inside one is, by the brief's
                  own first rule, a finding to report and not an order to follow
    the order     "do not change a test to make it pass" SURVIVES where a machine asked for the
                  repair, and is NOT said over a person's comment
    the harness   says nothing of its own that asserts a kind — no sentence, no heading

And the port is not widened: a harness that never heard of `instruction` is handed one text.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openfactory.adapters.agent.base import REPAIR_INSTRUCTION, takes_instruction
from openfactory.adapters.agent.registry import HARNESSES
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import (
    AgentRunResult,
    Finding,
    JobState,
    Manifest,
    ReviewResult,
    RunResult,
)
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import AdjustInput
from tests.test_the_repair_brief_states_the_failure_it_was_given import (
    LOG,
    PR,
    _an_open_pull_request,
)
from tests.test_walking_skeleton import (
    FakeForge,
    FakeTracker,
    _runner,
    _sizing_ticket_id,
    repo,  # noqa: F401 — the fixture: a real repository with a bare origin to push to
)

ROOT = Path(__file__).resolve().parents[1]
ROWS = sorted(HARNESSES)  # every shipped row, by the table that ships them: a fifth joins this


# ═══ the fixture: a real row's `repair`, a real orchestrator, and a box that writes it down ═════

class _Box(WorktreeSandbox):
    """A real worktree box, except that a harness CLI is written down instead of started.

    Everything else — git, the gates, the push — runs for real, so the prompt read below is the
    one the orchestrator's own caller produced, through the row's own `repair`."""

    def __init__(self, root: Path, *, heals) -> None:
        super().__init__(root=root)
        self.harness_commands: list[str] = []
        self._heals = heals

    def harness_path(self, name: str) -> str:
        return f"/the-box/{name}"

    def run(self, *, workspace, command: str, timeout: int, on_output=None):
        if "/the-box/" in command:
            self.harness_commands.append(command)
            self._heals(Path(workspace.path))  # what the agent "did", so the run can carry on
            return 0, ""
        return super().run(workspace=workspace, command=command, timeout=timeout,
                           on_output=on_output)


class _Row:
    """The REAL `repair` of one shipped row, behind an `execute` that needs no CLI.

    `repair` is the row's own bound method — its signature included, which is what the
    orchestrator reads — and `execute` is scripted because how the work got onto the branch is
    not the claim. No `recover`, no `continue_execute`: the recovery ladder falls through to
    `repair`, which is the sixth kind of words."""

    def __init__(self, kind: str, *, writes: str = "VALUE = 42\n", stops: str = "") -> None:
        self.repair = HARNESSES[kind](role="executor").repair
        self._writes, self._stops = writes, stops

    def execute(self, *, sandbox, workspace, context):
        (workspace.path / "feature.py").write_text(self._writes)
        if self._stops:
            return AgentRunResult(ok=False, summary=self._stops)
        return AgentRunResult(ok=True, summary="wrote feature.py", cost_usd=0.01, actions=[])


class _RejectsOnce:
    """A blocking reviewer that rejects with one finding, then approves."""

    def __init__(self) -> None:
        self.asked = 0

    def review(self, *, sandbox, workspace, review_input):
        self.asked += 1
        if self.asked == 1:
            return ReviewResult(decision="rejected", score=20, summary="the export is wrong",
                                findings=[Finding(severity="high", file="feature.py", line=1,
                                                  description=FINDING)])
        return ReviewResult(decision="approved", score=95, summary="fine now")


FINDING = "test_export asserts nothing — make it assert the row count"
COMMENT = "rename test_it to test_the_export_counts_rows and make it assert 4"
STOPPED = "ran out of turns while wiring the exporter"


def _prompt(box: _Box) -> str:
    """The first prompt a harness CLI was started with: the argument that carries the ticket."""
    assert box.harness_commands, "no harness was started — the caller under test never ran"
    return next(arg for arg in shlex.split(box.harness_commands[0]) if "# Ticket" in arg)


def _told(kind: str, words: str, repo: Path, tmp_path: Path) -> str:  # noqa: F811
    """Drive the REAL caller for one kind of words, with row `kind`, and return what it was told."""
    heal = lambda ws: (ws / "fixed.txt").write_text("fixed\n")  # noqa: E731
    row, manifest, reviewer = _Row(kind), Manifest(validate={"test": "true"}), None
    if words == "gates":
        manifest = Manifest(validate={"test": "test -f fixed.txt"})
    elif words == "suppression":
        row = _Row(kind, writes="VALUE = 42  # pragma: no cover\n")
        heal = lambda ws: (ws / "feature.py").write_text("VALUE = 42\n")  # noqa: E731
    elif words == "review":
        manifest = Manifest(validate={"test": "true"}, review_mode="blocking")
        reviewer = _RejectsOnce()
    elif words == "recovery":
        row = _Row(kind, stops=STOPPED)
    box = _Box(tmp_path / "wt", heals=heal)
    forge = FakeForge()
    forge.display_name = "Azure DevOps"
    runner = _runner(repo, FakeTracker(_sizing_ticket_id("#9")), manifest, tmp_path,
                     agent=row, forge=forge, sandbox=box, reviewer=reviewer)
    if words == "check":
        _an_open_pull_request(repo)
        runner.repair_ci("#9", LOG, pr_url=PR)
    elif words == "person":
        _an_open_pull_request(repo)
        runner.repair_ci("#9", COMMENT, pr_url=PR, human=True)
    else:
        runner.run("#9")
    return _prompt(box)


def _halves(prompt: str) -> tuple[str, str]:
    """`(what is outside every DATA fence, what is inside one)` — by the brief's own markers."""
    outside, inside, fenced = [], [], False
    for line in prompt.splitlines():
        if re.fullmatch(r"<<<data [0-9a-f]+>>>", line):
            fenced = True
        elif re.fullmatch(r"<<<end data [0-9a-f]+>>>", line):
            fenced = False
        else:
            (inside if fenced else outside).append(line)
    assert not fenced, "a DATA block never closed"
    return "\n".join(outside), "\n".join(inside)


#: The order that keeps a red gate from being turned green in the test file — in any of the
#: wordings this tree has carried, so this guard is red for what the agent is TOLD, not for prose.
KEEP_THE_TESTS = re.compile(r"(do not change|never silence)[^.]*\btests?\b", re.IGNORECASE)

#: kind of words → (a piece of the stranger's words, a piece of the caller's close).
WORDS = {
    "gates": ("test -f fixed.txt", "validation gates FAILED on your change"),
    "check": (LOG, "FAILING on Azure DevOps"),
    "person": (COMMENT, "it is a review comment"),
    "suppression": ("feature.py: VALUE = 42", "ADDED gate-suppression comment(s)"),
    "review": (FINDING, "The independent code review REJECTED this change"),
    "recovery": (STOPPED, "A previous executor stopped unfinished"),
}


# ═══ what each row tells the agent, for each kind of words ══════════════════════════════════════

@pytest.mark.parametrize("kind", ROWS)
@pytest.mark.parametrize("words", sorted(WORDS))
def test_the_words_are_fenced_and_the_close_is_the_callers_outside_the_fence(
        repo, tmp_path, kind, words):  # noqa: F811
    theirs, ours = WORDS[words]

    outside, inside = _halves(_told(kind, words, repo, tmp_path))

    assert theirs in inside and theirs not in outside, "a stranger's words are outside the fence"
    assert ours in outside, (
        "the platform's own sentence about this pass is missing, or is inside a DATA block — "
        "where the brief's first rule says it is a finding to report, not an order")
    assert ours not in inside


@pytest.mark.parametrize("kind", ROWS)
@pytest.mark.parametrize("words", ["gates", "check"])
def test_a_repair_a_machine_asked_for_still_says_not_to_fix_it_in_the_tests(
        repo, tmp_path, kind, words):  # noqa: F811
    outside, _ = _halves(_told(kind, words, repo, tmp_path))
    assert KEEP_THE_TESTS.search(outside), "the safety order did not survive the move"


@pytest.mark.parametrize("kind", ROWS)
def test_a_persons_comment_is_not_told_to_leave_the_tests_alone(repo, tmp_path, kind):  # noqa: F811
    """THE DEFECT. The comment here asks for a test to change, and the same brief forbade it."""
    outside, _ = _halves(_told(kind, "person", repo, tmp_path))

    assert not KEEP_THE_TESTS.search(outside), KEEP_THE_TESTS.search(outside).group(0)
    for said in ("FAILED", "FAILING"):
        assert said not in outside, f"a review comment is announced as something that {said}"


@pytest.mark.parametrize("kind", ROWS)
@pytest.mark.parametrize("words", sorted(set(WORDS) - {"gates"}))
def test_the_harness_says_nothing_of_its_own_about_what_the_words_are(
        repo, tmp_path, kind, words):  # noqa: F811
    """No sentence and no heading: only the gates' own output is what 'the gates reported'."""
    prompt = _told(kind, words, repo, tmp_path)

    for kind_of_words in ("validations reported above", "own validation gates FAILED",
                          "gates reported", "Failures from the last run"):
        assert kind_of_words not in prompt, f"{words!r} is announced as {kind_of_words!r}"
    assert REPAIR_INSTRUCTION not in prompt, "the row spoke although the caller had"


@pytest.mark.parametrize("kind", ROWS)
def test_a_row_asked_without_an_instruction_asserts_no_kind(tmp_path, kind):
    """The port's own shape, `repair(failure_log=…)`: what the row says unprompted is only what is
    true of every repair."""
    from openfactory.adapters.agent.base import AgentContext
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import Ticket

    box = _Box(tmp_path, heals=lambda ws: None)
    context = AgentContext(ticket=Ticket(id="#7", title="t", objective="o", repo="o/r"))
    HARNESSES[kind](role="executor").repair(
        sandbox=box, workspace=Workspace(path=tmp_path, branch="b", base_branch="main"),
        context=context, failure_log=COMMENT)

    outside, inside = _halves(_prompt(box))
    assert COMMENT in inside and REPAIR_INSTRUCTION in outside
    assert not KEEP_THE_TESTS.search(outside) and "FAILED" not in outside


# ═══ the port is not widened: who is handed the two halves apart ════════════════════════════════

class _Stranger:
    """An add-on written before the keyword existed — `tests/stranger_addon.py`'s shape."""

    def __init__(self) -> None:
        self.heard: list[str] = []

    def repair(self, *, sandbox, workspace, context, failure_log):
        self.heard.append(failure_log)
        (workspace.path / "ci_fix.py").write_text("FIXED = True\n")
        return AgentRunResult(ok=True, summary="fixed", cost_usd=0.01, actions=[])


class _Swallows(_Stranger):
    def repair(self, *, sandbox, workspace, context, failure_log, **_kw):
        return super().repair(sandbox=sandbox, workspace=workspace, context=context,
                              failure_log=failure_log)


@pytest.mark.parametrize("kind", ROWS)
def test_every_shipped_row_declares_the_keyword(kind):
    assert takes_instruction(HARNESSES[kind](role="executor"))


def test_only_a_named_parameter_is_a_declaration():
    assert not takes_instruction(_Stranger())
    assert not takes_instruction(_Swallows()), "**kwargs would drop the instruction on the floor"
    assert not takes_instruction(MagicMock()), "a test double is not a declaration"
    assert not takes_instruction(object())


@pytest.mark.parametrize("agent", [_Stranger, _Swallows])
def test_a_harness_that_never_heard_of_it_is_handed_one_text(repo, tmp_path, agent):  # noqa: F811
    _an_open_pull_request(repo)
    stranger = agent()
    runner = _runner(repo, FakeTracker(_sizing_ticket_id("#9")),
                     Manifest(validate={"test": "true"}), tmp_path, agent=stranger)

    got = runner.repair_ci("#9", COMMENT, pr_url=PR, human=True)

    (heard,) = stranger.heard
    assert got.state is not JobState.FAILED
    assert heard.startswith("A person reviewed this pull request") and heard.endswith(COMMENT)
    assert not KEEP_THE_TESTS.search(heard)


# ═══ the one door, and the worker that feeds it ═════════════════════════════════════════════════

def test_every_repair_leaves_the_machine_through_the_one_door():
    """Parsed, not grepped. A sixth caller that reaches `agent.repair` on its own writes no close
    at all — and the row, asked without one, no longer supplies the safety order for it."""
    tree = ast.parse((ROOT / "openfactory/orchestrator/machine.py").read_text())
    callers = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
               for call in ast.walk(fn)
               if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
               and call.func.attr == "repair"
               and isinstance(call.func.value, ast.Attribute) and call.func.value.attr == "agent"]
    assert callers and set(callers) == {"_repair"}, callers


@pytest.mark.parametrize(("typed", "handed"), [(COMMENT, COMMENT), ("  \n", "")])
def test_the_worker_hands_over_the_persons_words_and_nothing_around_them(
        monkeypatch, typed, handed):
    """The framing used to be glued on HERE, two layers above the harness — so it was fenced with
    the comment, and an empty comment was never empty by the time the machine's door read it."""
    ran: list[dict] = []
    project = SimpleNamespace(name="p")
    monkeypatch.setattr(acts, "ProjectRegistry", lambda: SimpleNamespace(get=lambda _n: project))
    monkeypatch.setattr(acts, "_ref_repo", lambda _p, _i: ("acme/x", ""))
    monkeypatch.setattr(acts, "_runner_view", lambda _p, _i: (project, ""))
    monkeypatch.setattr(acts, "_resolved_image", lambda _p, sandbox: "")
    monkeypatch.setattr(acts, "installed_box_traits", lambda _s: SimpleNamespace(remote=False))

    def runner(*a, **kw):
        def repair_ci(issue, ci_log, pr_url="", human=False):
            ran.append({"log": ci_log, "human": human})
            return RunResult(ticket_id=issue, state=JobState.PR_OPEN, pr_url=pr_url)
        return SimpleNamespace(repair_ci=repair_ci)

    monkeypatch.setattr(acts, "build_runner", runner)

    acts._run_adjust(AdjustInput(project="p", issue="12", pr_url=PR, sandbox="worktree",  # noqa: SLF001
                                 instruction=typed))

    assert ran == [{"log": handed, "human": True}]

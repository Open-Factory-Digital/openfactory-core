"""A large docs corpus must not kill the job with an OSError (#5, part 1/3 of #3).

THE DEFECT. Every command reaches a box as one shell string, so a harness's prompt reached it as
an argv element — and Linux caps a SINGLE argument at `MAX_ARG_STRLEN`, 32 pages, 128 KiB, whatever
`ARG_MAX` says. Measured on a real deployment with 51 ADRs inlined: a 367,315-byte prompt died with
`OSError: [Errno 7] Argument list too long: '/bin/sh'` out of Popen before the harness was a
process, and the sizer died first so the ticket also ran unsized on its way to failing.

THE FIX. #326 gave every box `stage_input` — a channel that writes the text into a file the box can
read and answers with a short in-box path. This routes every harness's prompt through it: the
command becomes `cat <path> | harness <flags>`, whose length is bounded and independent of the
prompt. A prompt that STILL cannot be delivered (a box with no channel, past the ceiling) is
refused BY NAME — never a raw OSError.
"""

from __future__ import annotations

import stat

import pytest

from openfactory.adapters.agent.base import (
    MAX_ARG_STRLEN,
    AgentContext,
    PromptTooLarge,
    prompt_too_large_result,
    stage_prompt,
)
from openfactory.adapters.agent.claude_code import ClaudeCodeAdapter
from openfactory.adapters.agent.codex import CodexAdapter
from openfactory.adapters.agent.kimi import KimiAdapter
from openfactory.adapters.agent.opencode import OpenCodeAdapter
from openfactory.adapters.sandbox.base import Workspace
from openfactory.adapters.sandbox.worktree import WorktreeSandbox
from openfactory.contracts import Ticket

#: Comfortably past the single-argument ceiling — the whole reason the channel exists.
_HUGE = "corpus-" + "x" * (MAX_ARG_STRLEN + 5000)


def _ctx(**kw) -> AgentContext:
    return AgentContext(
        ticket=Ticket(id="#7", title="add health check", objective="expose /health", repo="o/r"),
        **kw,
    )


# ── the shared seam ────────────────────────────────────────────────────────────────────────────


class _NoChannel:
    """A box with no `stage_input` — the pre-#326 shape, still a valid box."""

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        return 0, ""


class _StagesToNone(_NoChannel):
    """A box that HAS the channel but cannot use it right now (no container yet, a refused copy)."""

    def stage_input(self, *, workspace, text: str):  # noqa: ARG002
        return None


def test_a_box_without_the_channel_and_a_small_prompt_stays_on_argv():
    """`None` means "the prompt is small enough to travel as an argument" — the smoke probe and a
    box that never heard of the channel still work."""
    assert stage_prompt(_NoChannel(), None, "tiny", phase="size", project="o/r") is None


def test_a_box_without_the_channel_and_a_huge_prompt_is_refused_BY_NAME():
    """The impossible case: past the argv ceiling AND no way off the command line. The only honest
    outcome is a named refusal — project, role, byte count and a remedy — never a raw OSError."""
    with pytest.raises(PromptTooLarge) as raised:
        stage_prompt(_StagesToNone(), None, _HUGE, phase="size", project="o/r")
    finding = str(raised.value)
    assert "o/r" in finding                       # the project
    assert "size" in finding                      # the document role / phase
    assert f"{len(_HUGE.encode()):,}" in finding  # the byte count
    assert "remedy" in finding.lower()            # what to do about it


def test_the_refusal_result_is_a_failed_run_not_an_exception():
    exc = PromptTooLarge("the finding sentence")
    res = prompt_too_large_result(exc, model="opus", harness="claude_code")
    assert res.ok is False and res.summary == "the finding sentence"
    assert res.harness == "claude_code"


# ── the worktree box, end to end over a corpus past the ceiling ──────────────────────────────────

_STUB = """\
#!/usr/bin/env python3
import sys, json
data = sys.stdin.read()
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "result": "read %d bytes" % len(data), "num_turns": 1}))
"""


@pytest.fixture
def worktree_with_stub(tmp_path, monkeypatch):
    """A REAL worktree box, wired to a stub harness that reads its prompt from stdin — so the whole
    invocation path runs, `cat <path> | harness`, over a real subprocess."""
    stub = tmp_path / "stub-harness"
    stub.write_text(_STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    box = WorktreeSandbox(root=tmp_path / "worktrees")
    ws = Workspace(path=tmp_path / "worktrees" / "job", branch="openfactory/7", base_branch="main")
    ws.path.mkdir(parents=True)
    monkeypatch.setattr(box, "harness_path", lambda name: str(stub))
    return box, ws


def test_a_corpus_past_the_ceiling_runs_instead_of_raising(worktree_with_stub):
    """The measurement the ticket is about: a >128 KiB prompt drives the real invocation and the
    job RUNS — no `OSError: Argument list too long`."""
    box, ws = worktree_with_stub
    ctx = _ctx(knowledge_map=_HUGE)
    res = ClaudeCodeAdapter(model="opus").execute(sandbox=box, workspace=ws, context=ctx)
    assert res.ok, res.summary
    # the whole corpus reached the harness's stdin — the stub reports the byte count it read
    assert "read " in res.summary


# ── every harness routes its prompt off argv when the box offers the channel ─────────────────────


class _Recorder:
    """A box WITH the channel that records both what was staged and what reached the command."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.staged: list[str] = []

    def harness_path(self, name: str) -> str:
        return name

    def stage_input(self, *, workspace, text: str):  # noqa: ARG002
        self.staged.append(text)
        return f"/tmp/openfactory-input/prompt-{len(self.staged)}.txt"

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        self.commands.append(command)
        return 0, ""


def _ws_small():
    return Workspace(path="/work", branch="b", base_branch="main")


@pytest.mark.parametrize("adapter", [
    ClaudeCodeAdapter(model="opus"),
    CodexAdapter(model="gpt-5"),
    KimiAdapter(model="k3"),
    OpenCodeAdapter(model="anthropic/claude-opus-5"),
])
def test_the_executor_prompt_is_staged_not_interpolated(adapter):
    """Criterion 1: no adapter interpolates the prompt into the command string. The prompt is on
    the STAGED channel and the command carries only a short path."""
    box = _Recorder()
    ctx = _ctx(knowledge_map=_HUGE, allowed_tools=["Read", "Edit", "Bash"])
    adapter.execute(sandbox=box, workspace=_ws_small(), context=ctx)

    assert box.staged, "the prompt never reached the off-argv channel"
    assert _HUGE in box.staged[0]
    invoke = box.commands[0]
    assert _HUGE not in invoke, "the prompt is still on the command line"
    assert invoke.startswith("cat "), invoke
    assert len(invoke) < 4096, "the command line must stay short whatever the corpus is"


def test_the_reviewer_prompt_is_staged_not_interpolated():
    """Criterion 1 for the reviewer axis too (both the Claude reviewer and the harness reviewer)."""
    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

    box = _Recorder()
    ri = ReviewInput(
        ticket=Ticket(id="#7", title="t", objective="o", repo="o/r"),
        diff="+" + _HUGE, validations=[], constraints=[],
    )
    ClaudeCodeReviewer(model="opus").review(sandbox=box, workspace=_ws_small(), review_input=ri)

    assert box.staged and _HUGE in box.staged[0]
    assert box.commands and _HUGE not in box.commands[0]
    assert box.commands[0].startswith("cat ")


def test_the_reviewer_refuses_by_name_when_it_cannot_stage():
    """Criterion 3 for the reviewer: an impossible prompt is a rejection that NAMES the cause, not
    an OSError and not a silent approval."""
    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

    ri = ReviewInput(
        ticket=Ticket(id="#7", title="t", objective="o", repo="o/r"),
        diff="+" + _HUGE, validations=[], constraints=[],
    )
    verdict = ClaudeCodeReviewer(model="opus").review(
        sandbox=_StagesToNone(), workspace=_ws_small(), review_input=ri)
    assert verdict.decision == "rejected"
    assert "o/r" in verdict.summary and "review" in verdict.summary.lower()


def test_the_executor_refuses_by_name_when_it_cannot_stage():
    """Criterion 3 for the coding axis: the same named refusal, as a failed run."""
    ctx = _ctx(knowledge_map=_HUGE, allowed_tools=["Read", "Edit", "Bash"])
    res = ClaudeCodeAdapter(model="opus").execute(
        sandbox=_StagesToNone(), workspace=_ws_small(), context=ctx)
    assert res.ok is False
    assert "o/r" in res.summary and "bytes" in res.summary and "remedy" in res.summary.lower()

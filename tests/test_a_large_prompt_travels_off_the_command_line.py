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

import os
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
    OpenCodeAdapter(model="anthropic/claude-opus-5"),
])
def test_the_executor_prompt_is_staged_not_interpolated(adapter):
    """Criterion 1: these adapters do not interpolate the prompt into the command string. The
    prompt is on the STAGED channel and the command carries only a short path.

    Kimi is NOT here, and its own test below says why: its CLI cannot read a prompt it did not
    get as an argument."""
    box = _Recorder()
    ctx = _ctx(knowledge_map=_HUGE, allowed_tools=["Read", "Edit", "Bash"])
    adapter.execute(sandbox=box, workspace=_ws_small(), context=ctx)

    assert box.staged, "the prompt never reached the off-argv channel"
    assert _HUGE in box.staged[0]
    invoke = box.commands[0]
    assert _HUGE not in invoke, "the prompt is still on the command line"
    assert invoke.startswith("cat "), invoke
    assert len(invoke) < 4096, "the command line must stay short whatever the corpus is"


def test_a_staged_path_with_a_space_is_quoted(tmp_path):
    """Every builder quotes the staged path, and nothing pinned it because no test path had a space
    in it (review of #360). The worktree box stages under the operator's own root, and that path
    can carry one — `~/Library/Application Support/…` is where a Mac puts it."""
    class _Spaced(_Recorder):
        def stage_input(self, *, workspace, text: str):  # noqa: ARG002
            self.staged.append(text)
            return "/tmp/openfactory input/prompt 1.txt"

    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer

    quoted = "'/tmp/openfactory input/prompt 1.txt'"
    for adapter in (ClaudeCodeAdapter(model="opus"), CodexAdapter(model="gpt-5"),
                    OpenCodeAdapter(model="anthropic/claude-opus-5")):
        box = _Spaced()
        adapter.execute(sandbox=box, workspace=_ws_small(),
                        context=_ctx(knowledge_map=_HUGE, allowed_tools=["Read"]))
        invoke = box.commands[0]
        assert quoted in invoke, (
            f"{adapter.name}: an unquoted path with a space becomes two arguments and `cat` reads "
            f"neither — {invoke[:120]}")

    # THE REVIEWER IS THE FIFTH BUILDER, and its cut survived until this line existed: a review
    # handed an empty prompt still answers, and what it answers is about no diff at all.
    box = _Spaced()
    ClaudeCodeReviewer(model="opus").review(
        sandbox=box, workspace=_ws_small(),
        review_input=ReviewInput(ticket=Ticket(id="#7", title="t", objective="o", repo="o/r"),
                                 diff="+" + _HUGE, validations=[], constraints=[]))
    assert quoted in box.commands[0], box.commands[0][:120]


def test_the_ceiling_measures_the_QUOTED_prompt(tmp_path):
    """The limit applies to the `sh -c` argument, and `shlex.quote` turns each apostrophe into five
    bytes — so a prompt under the cap could still overflow it (review of #360: 131,000 bytes of ADR
    prose became a 131,886-byte argument, past the 131,072 limit, with no refusal). The check reads
    the quoted length and keeps a margin for the rest of the command."""
    from openfactory.adapters.agent.base import (
        MAX_ARG_STRLEN,
        PromptTooLarge,
        _argv_bytes,
        stage_prompt,
    )

    apostrophes = "it's " * 26_000              # 130,000 bytes raw, far more once quoted
    assert len(apostrophes.encode()) < MAX_ARG_STRLEN
    assert _argv_bytes(apostrophes) > MAX_ARG_STRLEN, "quoting is what the shell will carry"

    with pytest.raises(PromptTooLarge) as raised:
        stage_prompt(object(), _ws_small(), apostrophes, phase="execute", project="p",
                     channel=False)
    assert "once quoted" in str(raised.value)


def test_the_margin_for_the_REST_of_the_command_is_held_back():
    """The prompt is not the whole argument: the harness's absolute path, the flags, the model and a
    session id ride in the same `sh -c` string. A prompt that fits the cap exactly leaves nothing
    for them, so the check holds a margin back — and this is the guard that was missing when the
    margin's own cut survived."""
    from openfactory.adapters.agent.base import (
        _COMMAND_MARGIN,
        MAX_ARG_STRLEN,
        PromptTooLarge,
        _argv_bytes,
        stage_prompt,
    )

    # inside the cap, inside the margin: deliverable as an argument only if nothing else rides along
    prompt = "x" * (MAX_ARG_STRLEN - _COMMAND_MARGIN // 2)
    assert _argv_bytes(prompt) < MAX_ARG_STRLEN, "the fixture must fit the raw cap"

    with pytest.raises(PromptTooLarge):
        stage_prompt(object(), _ws_small(), prompt, phase="execute", project="p", channel=False)


def test_kimi_keeps_the_prompt_ON_argv_because_its_cli_cannot_read_it_anywhere_else():
    """The row that must NOT use the channel (review of #360).

    `-p -` was assumed to be a stdin sentinel. It is not one: `kimi-code` declares
    `-p, --prompt <prompt>` as an option that TAKES a value, `validateOptions` only checks the
    value is not blank, and `runNativeTurn` enqueues it verbatim — so `-p -` handed the model the
    one-character task `-`, on every staged run, small ones included. Read in the bundle of 0.31.1,
    the version `docker/worker.Dockerfile` pins, and of 0.32.0: no path reads stdin into the
    prompt. So this row keeps the argument form that was verified, and the box is never asked to
    stage for it.
    """
    box = _Recorder()
    ctx = _ctx(knowledge_map="a small map", allowed_tools=["Read", "Edit", "Bash"])
    KimiAdapter(model="k3").execute(sandbox=box, workspace=_ws_small(), context=ctx)

    invoke = box.commands[0]
    assert box.staged == [], "kimi must not stage: its CLI cannot read a staged prompt"
    assert not invoke.startswith("cat "), invoke
    assert " -p -" not in invoke, "`-p -` reaches the model as the one-character task `-`"
    assert "a small map" in invoke, "the prompt IS the argument for this row"


def test_kimi_refuses_BY_NAME_what_it_cannot_carry_on_argv():
    """And the ceiling is still asked of it. With no channel and a prompt past the per-argument
    limit, the honest outcome is the named refusal — not `OSError: Argument list too long` out of
    `Popen`, and not a silent truncation."""
    box = _Recorder()
    ctx = _ctx(knowledge_map="x" * (32 * 4096), allowed_tools=["Read", "Edit", "Bash"])

    result = KimiAdapter(model="k3").execute(sandbox=box, workspace=_ws_small(), context=ctx)

    assert not result.ok
    assert "per-argument limit" in result.summary and "kimi-code` cannot" in result.summary
    assert box.commands == [], "nothing may be sent when the prompt cannot be delivered"


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


# ── the box the JUDGING roles build (#380) ─────────────────────────────────────────────────────
#
# Every test above builds the box with a `Path`. The judging roles — product, tech-lead chat and
# diagnosis, sizer, extraction — build it through `judging_worktree` with whatever their caller
# holds, and most hold a `str` (a `TemporaryDirectory()`). `stage_input` divided that `str` and
# every one of their turns died on a TypeError before the harness started.

@pytest.mark.parametrize("spelling", [str, lambda p: p], ids=["str", "Path"])
def test_a_judging_box_stages_and_cleans_whatever_spelling_its_root_came_in(tmp_path, spelling):
    from openfactory.adapters.sandbox.registry import judging_worktree

    box = judging_worktree(None, root=spelling(tmp_path / "room"))
    ws = Workspace(path=str(tmp_path / "room"), branch="main", base_branch="main")

    staged = box.stage_input(workspace=ws, text="the prompt")

    assert staged is not None, "a judging box could not stage a prompt"
    with open(staged, encoding="utf-8") as fh:
        assert fh.read() == "the prompt"
    box.cleanup(workspace=ws)
    assert not os.path.exists(staged), "cleanup left the staged prompt behind"


def test_the_box_holds_the_type_it_declares():
    """The normalisation itself, so a later refactor cannot move it back to the callers."""
    from pathlib import Path

    assert isinstance(WorktreeSandbox(root="/tmp/somewhere").root, Path)

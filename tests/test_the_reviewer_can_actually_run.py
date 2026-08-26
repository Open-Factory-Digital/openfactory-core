"""The independent review is a product claim — so it must RUN on a client's image (ADR-0037).

FOUND LIVE on fx-dotnet (`mcr.microsoft.com/dotnet/sdk:8.0`, 2026-08-05), the first .NET box this
platform was ever pointed at. The executor went through `SandboxAdapter.harness_path` — the seam
that exists precisely because PATH cannot be relied on inside a CLIENT's image — and the reviewer,
holding the same sandbox, emitted a bare `claude`. It exited 127, its envelope would not parse,
and the review came back `rejected / score 0 / "reviewer output could not be parsed"`.

Two failures in one, and the second is worse than the first: the review silently does not happen
on any client image, and reports itself as a REJECTION rather than as absent — so a person goes
looking for what is wrong with a diff that nothing ever read.
"""

from __future__ import annotations

from openfactory.adapters.reviewer.base import ReviewInput
from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer
from openfactory.contracts import Ticket


class _Box:
    """A sandbox whose harness lives where a client image puts it: not on PATH."""

    def __init__(self, rc=0, out="{}"):
        self.commands: list[str] = []
        self._rc, self._out = rc, out

    def harness_path(self, name: str) -> str:
        return f"/opt/openfactory-toolbox/{name}"

    def run(self, *, workspace, command, timeout):
        self.commands.append(command)
        return self._rc, self._out


def _input() -> ReviewInput:
    return ReviewInput(ticket=Ticket(id="#1", title="t", objective="o", repo="a/b"), diff="diff", validations=[])


def test_the_reviewer_invokes_the_harness_the_BOX_names():
    box = _Box(out='{"result": "{\\"decision\\":\\"approved\\",\\"score\\":90,\\"summary\\":\\"ok\\"}"}')

    ClaudeCodeReviewer().review(sandbox=box, workspace=None, review_input=_input())

    assert box.commands and box.commands[0].startswith("/opt/openfactory-toolbox/claude "), (
        f"the reviewer emitted a bare binary name again: {box.commands[0][:60]!r}")


def test_a_review_that_never_RAN_says_so_instead_of_blaming_the_diff():
    """`rejected / could not be parsed` sends somebody to look for what is wrong with the code
    when nothing reviewed it at all. The two need opposite actions: fix the diff, or fix the box."""
    box = _Box(rc=127, out="sh: 1: claude: not found")

    result = ClaudeCodeReviewer().review(sandbox=box, workspace=None, review_input=_input())

    assert result.decision == "rejected", "refusing to proceed as if reviewed must not soften"
    assert "never ran" in result.summary
    assert "box prove" in result.summary, "the sentence must name the fix"
    assert "NOT been reviewed" in result.summary


def test_output_that_ran_and_will_not_parse_is_still_reported_as_that():
    """The other half must not be swallowed by the new branch — a harness that ran and produced
    nonsense is a different problem from one that was never there."""
    box = _Box(rc=0, out="this is not json")

    result = ClaudeCodeReviewer().review(sandbox=box, workspace=None, review_input=_input())

    assert "could not be parsed" in result.summary
    assert "never ran" not in result.summary

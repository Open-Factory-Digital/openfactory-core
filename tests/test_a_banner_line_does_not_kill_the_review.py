"""A harness CLI is a program, and programs talk. The parser has to survive that.

`claude -p --output-format json` prints its envelope on stdout — and above it, whatever it felt
like mentioning that day:

    Warning: Opus: Opus 5 not available — using Opus 4.5 for this session
    {"is_error":false,"num_turns":1,...}

A bare `json.loads` on that raises on character one. The reviewer did exactly that, so the
INDEPENDENT REVIEW — one of this platform's three product claims — reported
`rejected / score 0 / "reviewer output could not be parsed"` on a diff that was fine, with a valid
envelope sitting one line below it.

FOUND ON A REAL TICKET, TWICE, AND MISDIAGNOSED THE FIRST TIME. fx-ado PR #9 came back unreviewed
and the suspicion was the model (Haiku 4.5 not holding the JSON envelope). Switching to Sonnet 5
produced PR #10 — unreviewed, identically. Only then did reproducing the exact CLI call show a
banner line above perfectly good JSON. The model was never involved.

THE BANNER IS NOT AN EDGE CASE. An update notice, a login hint, a deprecation, a model
substitution, a proxy warning: every one is a line a CLI may print on any client's machine on any
day, and none of them says anything is wrong. A parser that assumes byte zero starts the document
is a parser that fails on the vendor's release schedule, in a way that reads as a verdict about the
client's code.
"""

from __future__ import annotations

import json

import pytest

from openfactory.adapters.agent.base import json_envelope

#: Verbatim from the live run that exposed this (fx-ado, 2026-08-06).
REAL_BANNER = "Warning: Opus: Opus 5 not available — using Opus 4.5 for this session"


def _envelope(result: str = '{"decision":"approved","score":90,"summary":"ok"}') -> str:
    return json.dumps({"is_error": False, "num_turns": 3, "total_cost_usd": 0.12,
                       "result": result, "usage": {"input_tokens": 10, "output_tokens": 20}})


@pytest.mark.parametrize("noise", [
    REAL_BANNER,
    "npm notice New minor version of npm available!",
    "Deprecation: --permission-mode plan will be renamed in a future release",
    "Note: your session used a fallback region",
    # two lines, because a CLI having one thing to say means it can have two
    REAL_BANNER + "\nNote: fast mode is unavailable in this region",
])
def test_a_line_above_the_envelope_does_not_lose_it(noise):
    got = json_envelope(f"{noise}\n{_envelope()}")

    assert got is not None, "the envelope was thrown away because the CLI said something first"
    assert got["num_turns"] == 3
    assert json.loads(got["result"])["score"] == 90


def test_a_line_BELOW_the_envelope_is_tolerated_too():
    """Same reasoning, other end. A CLI that appends an update notice has not failed."""
    got = json_envelope(f"{_envelope()}\nUpdate available: run `npm i -g @anthropic-ai/claude-code`")
    assert got is not None and got["num_turns"] == 3


def test_a_brace_INSIDE_the_prose_does_not_win():
    """The naive fix — find the first `{` — picks up a brace in the warning's own text.

    `Note: use {tool} carefully` starts a `{` that is not the envelope, and a parser anchored on
    the first one either fails or, worse, parses a fragment and reports it as a verdict.
    """
    got = json_envelope(f"Note: the {{plan}} mode is advisory\n{_envelope()}")
    assert got is not None and got["num_turns"] == 3


def test_output_with_no_envelope_at_all_is_None_not_a_guess():
    """`None` so the caller can still distinguish "said nothing parseable" from "gave a verdict".

    Returning `{}` here would let an empty dict flow on as a review, which is how "the reviewer
    never ran" became indistinguishable from "the reviewer approved" in the first place.
    """
    assert json_envelope("") is None
    assert json_envelope("command not found: claude") is None
    assert json_envelope("Traceback (most recent call last):\n  File ...") is None


def test_the_REVIEWER_uses_it(monkeypatch):
    """Reachability. The helper being right is worth nothing if the reviewer still calls
    `json.loads` — this codebase's signature defect, ~20 times over."""
    from openfactory.adapters.reviewer.base import ReviewInput
    from openfactory.adapters.reviewer.claude_code import ClaudeCodeReviewer
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.contracts import AcceptanceCriterion, Ticket

    class _Sandbox:
        def run(self, **kw):
            return 0, f"{REAL_BANNER}\n" + _envelope(
                '{"decision":"approved","score":88,"summary":"meets the criteria",'
                '"acceptance":[],"findings":[]}')

        def harness_path(self, name):
            return f"/toolbox/{name}"

    ticket = Ticket(id="1", title="t", objective="o", repo="o/r",
                    acceptance_criteria=[AcceptanceCriterion(text="c")])
    result = ClaudeCodeReviewer().review(
        sandbox=_Sandbox(),
        workspace=Workspace(path="/tmp/x", branch="b", base_branch="main"),
        review_input=ReviewInput(ticket=ticket, diff="- a\n+ b", validations=[]),
    )

    assert result.decision == "approved" and result.score == 88, (
        f"the reviewer still cannot read past a banner line: {result.summary!r}"
    )
    assert result.cost_usd == 0.12, "the envelope's cost was lost with it"

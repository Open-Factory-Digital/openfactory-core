"""The independent reviewer, for ANY harness.

The review was never Claude-shaped — only its plumbing was. What it needs is in `ReviewInput`:
the spec, the diff as TEXT, the validation results and the constraints. It deliberately never
sees how the change was made (ADR-0001 D-5), so it does not even need the workspace's contents,
only a place to run.

So the prompt and the verdict parsing live here, once, and the harness supplies nothing but
`ask()` — the same read-only primitive the tech-lead roles use (see agent/roles.py). A
Claude-free deployment gets a real independent review instead of losing review entirely.

ON INDEPENDENCE: the prompt opens with "you did NOT write this code", which is literally true when
the reviewer axis is a different harness from the executor — and is the reason those axes are
configured separately. When a project points both at the SAME harness, the sentence stops being
structurally true: the review is a fresh context on the same engine, which still catches plenty,
but it is no longer an independent second opinion. That is a real reduction, and the honest place
to say so is here rather than in a release note nobody reads.
"""

from __future__ import annotations

import json

from openfactory.adapters.reviewer.base import ReviewerAdapter, ReviewInput
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.contracts import ReviewResult

_SCHEMA = """\
Return ONLY a JSON object (no prose, no code fences) with this shape:
{
  "decision": "approved" | "approved_with_findings" | "rejected",
  "score": 0-100,
  "acceptance": [{"criterion": str, "status": "passed"|"failed"|"unknown", "evidence": str|null}],
  "findings": [{"severity": "low"|"medium"|"high"|"critical", "description": str,
                "file": str|null, "line": int|null, "criterion": str|null}],
  "summary": str
}"""

_INSTRUCTIONS = (
    "You are an INDEPENDENT reviewer. You did NOT write this code. You are given only the "
    "specification, the diff, and the platform's validation results. Do not modify anything. Your "
    "job is to find evidence the change is wrong or incomplete: map each acceptance criterion to "
    "concrete evidence, hunt for regressions and unrequested scope, and check the constraints are "
    "not violated."
)


def build_review_prompt(ri: ReviewInput) -> str:
    """The reviewer's prompt — harness-agnostic by construction (it contains no CLI, no flags,
    no vendor). Shared by every reviewer implementation so a verdict means the same thing
    whichever harness produced it."""
    t = ri.ticket
    crits = "\n".join(f"- {c.text}" for c in t.acceptance_criteria) or "(none stated)"
    # A GATE THAT COULD NOT RUN IS NOT A GATE THE CODE FAILED, and this line is where the
    # difference reaches an INDEPENDENT reviewer — which is the one reader that must not be told
    # the diff broke something when nothing was checked. It is `_prompt` in `claude_code.py` too;
    # the duplication is older than this change, and both are wrong in the same way until both say
    # it.
    vals = "\n".join(
        f"- {v.name}: "
        f"{'PASS' if v.passed else ('COULD NOT RUN' if v.unrunnable else 'FAIL')} "
        f"(exit {v.exit_code})"
        + (f" — {v.unrunnable}; nothing was checked" if v.unrunnable else "")
        for v in ri.validations
    ) or "(none)"
    parts = [
        _INSTRUCTIONS,
        f"\n# Ticket {t.id}: {t.title}\n## Objective\n{t.objective}",
        f"\n## Acceptance criteria\n{crits}",
        f"\n## Platform validation results\n{vals}",
    ]
    if ri.constraints:
        parts.append("\n## Constraints (ADRs)\n" + "\n\n".join(ri.constraints))
    parts.append("\n## Diff\n```diff\n" + ri.diff + "\n```")
    parts.append("\n" + _SCHEMA)
    return "\n".join(parts)


def extract_json(text: str) -> str:
    """The JSON object out of whatever prose or fencing a model wrapped it in."""
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


def with_telemetry(review: ReviewResult, res) -> ReviewResult:
    """Carry the agent run's cost onto the verdict. Every reviewer does this, or the review is
    free in the only number a client reads."""
    return review.model_copy(update={
        "cost_usd": getattr(res, "cost_usd", None),
        "num_turns": getattr(res, "num_turns", None),
        "input_tokens": getattr(res, "input_tokens", None),
        "output_tokens": getattr(res, "output_tokens", None),
        "model": getattr(res, "model", None),
        "harness": getattr(res, "harness", None),
    })


def parse_review(text: str, *, detail: str = "") -> ReviewResult:
    """A verdict, or an explicit REJECTION saying the verdict could not be read.

    Unparseable output rejects rather than approves. That asymmetry is deliberate: a review that
    silently became an approval because the model rambled is how an unreviewed change lands
    looking reviewed."""
    try:
        return ReviewResult(**json.loads(extract_json(text)))
    except (json.JSONDecodeError, ValueError, TypeError):
        return ReviewResult(
            decision="rejected", score=0,
            summary=f"reviewer output could not be parsed{f' ({detail})' if detail else ''}",
        )


class HarnessReviewer(ReviewerAdapter):
    """An independent review run through whichever harness the project configured for it."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.name = getattr(agent, "name", type(agent).__name__)

    def review(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, review_input: ReviewInput
    ) -> ReviewResult:
        res = self.agent.ask(
            sandbox=sandbox, workspace=workspace,
            prompt=build_review_prompt(review_input), phase="review",
        )
        # A REVIEW THAT NEVER RAN IS NOT A REVIEW THAT RAMBLED, and both used to read
        # "reviewer output could not be parsed". `ClaudeCodeReviewer` learned this distinction
        # earlier; this class — the one every non-Claude harness reviews through — did not, so an
        # auth failure, a rate limit or a silent empty run was reported as a rejection with a
        # score of 0, indistinguishable from a genuine one. A human reading "rejected" goes and
        # argues with the code; nobody goes and looks at the harness.
        if not getattr(res, "ok", True):
            why = getattr(res, "pause_reason", None) or "the harness reported a failure"
            tail = (getattr(res, "summary", "") or "")[:400].strip()
            return with_telemetry(ReviewResult(
                decision="rejected", score=0,
                summary=(f"THE REVIEW NEVER RAN ({self.name}): {why}. This diff has NOT been "
                         f"reviewed — it is not a rejection of the code."
                         + (f"\n{tail}" if tail else "")),
            ), res)
        # the FULL text: a review of a real diff — criteria, findings, evidence — is easily more
        # than the 1000-char summary cap, and truncated JSON does not read as truncated. It reads
        # as "reviewer output could not be parsed", and the job proceeds as if reviewed. This was
        # the one consumer that never learned to work around the cap.
        from openfactory.adapters.agent.base import final_text

        return with_telemetry(parse_review(final_text(res), detail=f"harness={self.name}"), res)

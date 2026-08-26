"""ClaudeCodeReviewer — the independent reviewer over `claude -p` (read-only).

Runs in plan mode (no mutations) with a prompt that contains ONLY spec + diff +
validation results, and is asked to emit a ReviewResult JSON. Same engine as the
executor, fresh context — so it does not defend the executor's original decision.
"""

from __future__ import annotations

import json
import shlex

from openfactory.adapters.agent.base import json_envelope
from openfactory.adapters.reviewer.base import ReviewerAdapter, ReviewInput
from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.contracts import ReviewResult

_TIMEOUT = 1200

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


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


class ClaudeCodeReviewer(ReviewerAdapter):
    #: which harness produced a verdict. Every reviewer carries this so a review can be ATTRIBUTED:
    #: with the harness configurable per project, "the reviewer rejected it" is only half an answer,
    #: and comparing harnesses honestly needs to know which one spoke.
    name = "claude_code"

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model

    def review(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, review_input: ReviewInput
    ) -> ReviewResult:
        rc, out = sandbox.run(
            workspace=workspace,
            # THROUGH THE BOX'S SEAM, like the executor. `harness_path` (ADR-0037 D2a) exists
            # because PATH cannot be relied on inside a CLIENT's image — and this reviewer had
            # the sandbox in its hand and asked it nothing, emitting a bare `claude`.
            #
            # FOUND LIVE on fx-dotnet (`mcr.microsoft.com/dotnet/sdk:8.0`, 2026-08-05): the CLI
            # exited 127, the envelope would not parse, and the review came back
            # `rejected / score 0 / "reviewer output could not be parsed"`. The INDEPENDENT
            # REVIEW — one of this platform's three product claims — silently does not run on
            # any client image, and reports itself as a rejection rather than as absent.
            command=self._cli(self._prompt(review_input),
                              harness=sandbox.harness_path("claude")),
            timeout=_TIMEOUT,
        )
        try:
            # THROUGH `json_envelope`, not `json.loads`. The CLI prints diagnostics above its
            # envelope — a model substitution, an update notice, a login hint — and a bare parse
            # dies on character one, reporting a fine diff as `rejected / score 0`.
            envelope = json_envelope(out)
            if envelope is None:
                raise ValueError("no JSON envelope in the reviewer's output")
            review = ReviewResult(**json.loads(_extract_json(str(envelope.get("result", "")))))
            # WHAT IT COST. `claude -p --output-format json` reports it in the same envelope this
            # already parses, and the value was thrown away — so the PR's `Cost:` line was the
            # executor alone while presenting itself as the ticket's cost, on every ticket, with
            # review on by default. `usage` is the CLI's own shape; absent keys stay None, because
            # unknown must not become zero (a free-looking harness wins every comparison).
            usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
            return review.model_copy(update={
                "cost_usd": envelope.get("total_cost_usd"),
                "num_turns": envelope.get("num_turns"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "model": self.model, "harness": "claude_code",
            })
        except (json.JSONDecodeError, ValueError, TypeError):
            # A REVIEW THAT COULD NOT RUN IS NOT A REJECTION, and the two used to read the same.
            # `rejected / score 0 / "could not be parsed"` sends somebody to look for what is
            # wrong with the code when nothing reviewed it at all. The DECISION stays rejected —
            # refusing to proceed as if reviewed is the safe default and must not soften — but
            # the sentence now names which of the two happened, because they need opposite
            # actions: fix the diff, or fix the box.
            never_ran = rc == 127 or "not found" in (out or "").lower()
            summary = (
                f"the reviewer never ran: its harness exited {rc} inside the box, so this diff "
                "has NOT been reviewed. Nothing here is a judgement about the code — check the "
                "box's toolbox mount (`openfactory box prove <project>`)."
                if never_ran else
                f"reviewer output could not be parsed (rc={rc})"
            )
            return ReviewResult(decision="rejected", score=0, summary=summary)

    def _prompt(self, ri: ReviewInput) -> str:
        t = ri.ticket
        crits = "\n".join(f"- {c.text}" for c in t.acceptance_criteria) or "(none stated)"
        vals = "\n".join(
            f"- {v.name}: {'PASS' if v.passed else 'FAIL'} (exit {v.exit_code})"
            for v in ri.validations
        ) or "(none)"
        parts = [
            "You are an INDEPENDENT reviewer. You did NOT write this code. You are given "
            "only the specification, the diff, and the platform's validation results. Do "
            "not modify anything. Your job is to find evidence the change is wrong or "
            "incomplete: map each acceptance criterion to concrete evidence, hunt for "
            "regressions and unrequested scope, and check the constraints are not violated.",
            f"\n# Ticket {t.id}: {t.title}\n## Objective\n{t.objective}",
            f"\n## Acceptance criteria\n{crits}",
            f"\n## Platform validation results\n{vals}",
        ]
        if ri.constraints:
            parts.append("\n## Constraints (ADRs)\n" + "\n\n".join(ri.constraints))
        parts.append("\n## Diff\n```diff\n" + ri.diff + "\n```")
        parts.append("\n" + _SCHEMA)
        return "\n".join(parts)

    def _cli(self, prompt: str, harness: str = "claude") -> str:
        cmd = [harness, "-p", shlex.quote(prompt), "--output-format", "json",
               "--permission-mode", "plan"]
        if self.model:
            cmd += ["--model", shlex.quote(self.model)]
        return " ".join(cmd)

"""ReviewerAdapter — the independent reviewer (ADR-0001 D-5).

A separate context whose value is *context independence*: it receives only the
spec, the diff, and the validation results — never the executor's conversation. Its
job is to find evidence the solution is wrong or incomplete and emit structured
findings, so the human reads a report instead of the raw diff. Same engine as the
executor (Claude), different role — so it is its own adapter, not a method on the
coding agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openfactory.adapters.sandbox.base import SandboxAdapter, Workspace
from openfactory.contracts import ReviewResult, Ticket, ValidationResult

#: HOW A CRITERION IS PASSED, said to every reviewer the same way (#447). The platform checks the
#: citation against the gates that ran (`review/evidence.py`) — so the rule the model is given and
#: the rule the code applies are one rule, and a verdict means the same whichever harness wrote it.
EVIDENCE_RULE = (
    "A criterion is `passed` only on evidence a gate listed under the platform's validation "
    "results EXECUTED: cite that gate in `evidence` as `gate:<name>` (for example `gate:test — "
    "tests/test_x.py::test_y covers it`). Reading the diff is not execution, and neither is a test "
    "that no listed gate runs — for those, the status is `unknown`, and if a test or command in "
    "the repository WOULD verify the criterion, name it in `would_verify` (for example `npm run "
    "test:e2e — frontend/e2e/home.spec.ts`). The platform confirms every `gate:` citation against "
    "the gates that actually ran; a criterion it cannot confirm is reported as not verified, "
    "whatever the decision says."
)

#: The acceptance entry every reviewer returns, with the field the rule above asks for.
ACCEPTANCE_SHAPE = ('  "acceptance": [{"criterion": str, "status": "passed"|"failed"|"unknown", '
                    '"evidence": str|null, "would_verify": str|null}],')


class ReviewInput(BaseModel):
    ticket: Ticket
    diff: str  # the code change, as text — the reviewer never sees how it was made
    validations: list[ValidationResult] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)  # ADRs it must check against


@runtime_checkable
class ReviewerAdapter(Protocol):
    def review(
        self, *, sandbox: SandboxAdapter, workspace: Workspace, review_input: ReviewInput
    ) -> ReviewResult:
        """Judge the change against the spec and emit a structured verdict."""
        ...

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

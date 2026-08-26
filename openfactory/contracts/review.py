"""The reviewer's structured output (ADR-0001 D-5).

The reviewer receives only spec + diff + validation results — never the executor's
conversation (context independence). Its job is to find evidence the solution is
wrong or incomplete, and emit this structure — so the human can read a *report*
instead of the raw diff, and dig in only when a flag is raised.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AcceptanceCheck(BaseModel):
    criterion: str
    status: Literal["passed", "failed", "unknown"]
    evidence: str | None = None  # e.g. a test name, a file:line


class Finding(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    description: str
    file: str | None = None
    line: int | None = None
    criterion: str | None = None  # which acceptance criterion this relates to, if any


class ReviewResult(BaseModel):
    decision: Literal["approved", "approved_with_findings", "rejected"]
    score: int = Field(ge=0, le=100)
    acceptance: list[AcceptanceCheck] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""

    # WHAT THE REVIEW COST. Not decoration: review is ON by default, and it is a whole independent
    # agent pass over the entire diff — frequently the same order of magnitude as writing the code.
    # This shape could not express it, so `machine.py` never counted it and the PR's own last line,
    # `Cost: $0.0626`, was the EXECUTOR alone while presenting itself as what the ticket cost. A
    # client comparing our price against another vendor's compares against a number we know is
    # short. No prompt and no model could have fixed that; the answer shape had no field for it.
    #
    # Optional and defaulting to None because "unknown" must stay distinct from "zero" — a harness
    # that reports tokens but no price (Codex) would otherwise look free and win every comparison,
    # which is the inverse of what the telemetry exists to do (`_reported_cost`).
    cost_usd: float | None = None
    num_turns: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    harness: str | None = None

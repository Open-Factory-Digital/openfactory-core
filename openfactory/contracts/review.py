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
    #: THE GATE THAT EXECUTED THIS CRITERION'S EVIDENCE — written by the platform, never read from
    #: the model (#447). The reviewer is asked to cite the gate as `gate:<name>` in `evidence`;
    #: `review/evidence.py::settle` keeps the name only when that gate ran and passed on this
    #: attempt. None is "nothing executed it": a criterion "passed" by reading the diff, or by a
    #: test no gate runs, which is exactly the case a person must not be told was verified.
    executed_by: str | None = None
    #: A check in the repository that WOULD verify this criterion but that no gate ran — the
    #: reviewer's pointer (#447), so "not verified" arrives with the one step that would fix it.
    would_verify: str | None = None


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
    #: WHETHER THE PLATFORM CHECKED THE EVIDENCE AGAINST THE GATES THAT RAN (#447). False on a
    #: verdict made before the check existed, or by a path that never settled it — and then the
    #: stance is read the old way, from `decision`, because a missing `executed_by` on such a
    #: verdict says nothing about what ran.
    evidence_checked: bool = False

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

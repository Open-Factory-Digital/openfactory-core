"""Pydantic contracts — the framework↔project interface, validated for free.

Everything the framework exchanges with projects, agents, and the board flows
through these models. See docs/adr/0001-foundational-conceptual-model.md.
"""

from openfactory.contracts.decision import (
    CoordinatorAdvice,
    DecisionOption,
    DecisionRequest,
    HandOff,
    canned,
    handoff_to_markdown,
    handoff_to_plain,
    parse_advice,
    parse_decision,
    parse_handoff,
)
from openfactory.contracts.manifest import (
    Component,
    ComponentDocs,
    DocRoles,
    Environment,
    Manifest,
)
from openfactory.contracts.review import AcceptanceCheck, Finding, ReviewResult
from openfactory.contracts.run import (
    AgentRunMetric,
    AgentRunResult,
    RunResult,
    Suppression,
    ValidationResult,
)
from openfactory.contracts.state import JobState, RiskLevel
from openfactory.contracts.ticket import AcceptanceCriterion, Ticket

__all__ = [
    "AcceptanceCheck",
    "AcceptanceCriterion",
    "AgentRunMetric",
    "AgentRunResult",
    "Component",
    "ComponentDocs",
    "CoordinatorAdvice",
    "DecisionOption",
    "DecisionRequest",
    "DocRoles",
    "Environment",
    "Finding",
    "HandOff",
    "canned",
    "handoff_to_markdown",
    "handoff_to_plain",
    "parse_advice",
    "parse_decision",
    "parse_handoff",
    "JobState",
    "Manifest",
    "ReviewResult",
    "RiskLevel",
    "RunResult",
    "Ticket",
    "Suppression",
    "ValidationResult",
]

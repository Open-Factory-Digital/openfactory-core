"""Answer a human gate the way the panel does: sealed (`openfactory.gate_seal`).

The workflow acts on a gate's answer only with the panel's seal over exactly the fields it will act
on, verified in the `verify_gate_seal` activity. A test that answers a gate therefore answers it
through here, and registers `SEAL_CHECK` with its worker — the REAL activity, so every gate test
also proves that a sealed answer passes. `tests/test_a_gate_answer_needs_the_panels_seal.py` proves
the other half: an answer sent straight to the engine does nothing.
"""

from __future__ import annotations

from openfactory import gate_seal
from openfactory.runtime.temporal.activities import verify_gate_seal
from openfactory.runtime.temporal.workflow import JobWorkflow

SEAL_CHECK = verify_gate_seal


async def answer_merge_gate(handle, answer: str, instruction: str = "", by: str = "") -> None:
    seal = gate_seal.seal(gate_seal.MERGE_GATE, handle.id, answer, instruction, by)
    await handle.signal(JobWorkflow.human_merge_gate, args=[answer, instruction, by, seal])


async def approve_prod(handle, version: str, approver: str, comment: str = "") -> None:
    seal = gate_seal.seal(gate_seal.APPROVE_PROD, handle.id, version, approver, comment)
    await handle.signal(JobWorkflow.approve_prod, args=[version, approver, comment, seal])


async def seal_checks_done(handle) -> int:
    """How many `verify_gate_seal` checks the workflow has COMPLETED — the only way to know an
    answer was consumed and judged before sending the next one, since a dropped answer changes
    no query the workflow answers."""
    from temporalio.api.enums.v1 import EventType

    checks: set[int] = set()
    done = 0
    async for event in handle.fetch_history_events():
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            if event.activity_task_scheduled_event_attributes.activity_type.name == \
                    "verify_gate_seal":
                checks.add(event.event_id)
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            if event.activity_task_completed_event_attributes.scheduled_event_id in checks:
                done += 1
    return done

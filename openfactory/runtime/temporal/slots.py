"""Which running JobWorkflows hold a floor slot.

A job parked on a person (an impediment, a rate-limit pause, the human merge gate, the prod
approval) is still a RUNNING workflow, but no agent is working it. Counting it against the floor
stalls every ticket behind a parked job, so the floor counts only jobs that are working.
A workflow that cannot be queried counts as working: the safe reading is fewer starts.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


async def is_parked(client, wf) -> bool:
    from openfactory.runtime.temporal.workflow import JobWorkflow

    try:
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)
        if await handle.query(JobWorkflow.awaiting_action):
            return True
        wait = await handle.query(JobWorkflow.awaiting_merge)
        if wait and not wait.get("working") and not wait.get("auto"):
            return True
        return bool(await handle.query(JobWorkflow.awaiting_approval))
    except Exception as exc:  # noqa: BLE001
        log.info("could not read whether %s is parked (%s), counting it as working", wf.id, exc)
        return False

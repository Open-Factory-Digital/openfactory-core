"""Start one JobWorkflow and wait for its result.

    python -m openfactory.runtime.temporal.starter <project> <issue> [--sandbox container]
    [--promote]

The workflow runs on the worker (start it separately); this just kicks it off,
prints the workflow id (find it in the Temporal UI), and blocks for the outcome.
"""

from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from openfactory.factory import resolve_box_image
from openfactory.registry import ProjectRegistry
from openfactory.runtime.temporal import TASK_QUEUE
from openfactory.runtime.temporal.connection import connect
from openfactory.runtime.temporal.io import JobParams
from openfactory.runtime.temporal.workflow import JobWorkflow


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("issue")
    ap.add_argument("--sandbox", default="container", choices=["worktree", "container", "fargate"])
    ap.add_argument("--promote", action="store_true")
    args = ap.parse_args()

    load_dotenv()
    client = await connect()  # dev-server or Temporal Cloud, per env

    wf_id = f"openfactory-{args.project}-{args.issue}"
    handle = await client.start_workflow(
        JobWorkflow.run,
        JobParams(
            project=args.project, issue=args.issue, sandbox=args.sandbox, promote=args.promote,
            # Resolved at launch like every other entry point, or this one quietly runs the
            # framework image for a project that declares its own (ADR-0037 D4).
            image=resolve_box_image(ProjectRegistry().get(args.project), sandbox=args.sandbox),
        ),
        id=wf_id,
        task_queue=TASK_QUEUE,
    )
    print(f"started workflow id={wf_id} (run {handle.result_run_id}) — awaiting…", flush=True)
    result = await handle.result()
    print("RESULT:", result.model_dump_json(indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

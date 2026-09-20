"""A review verdict nobody answers is said so inside the read deadline (2026-09-19).

A workflow query is answered by a WORKER. Made raw it waits the SDK's own 30 s, and `/api/inbox`
asked every listed job one after another: 116.0 s for four completed jobs and no worker, to answer
`[]`. The rows are the bound, the three ways the bound could be there and the page still not load
(per job, one after another, every listed job), the two readers going back to a raw query, and the
ways a job that did not answer could come out looking like a job nobody reviewed.
"""

TEST = "tests/test_a_verdict_nobody_answers_is_said_so_inside_the_deadline.py"
VIEW = "openfactory/runtime/temporal/view.py"
CONVERSATION = "openfactory/techlead/conversation.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    ("the verdict read has no deadline, so a job whose worker is gone holds whoever asked", VIEW,
     "        answered, _late = await asyncio.wait(reads, timeout=read_deadline())",
     "        answered, _late = await asyncio.wait(reads, timeout=None)"),

    ("a query still asking after the deadline is left running on the loop", VIEW,
     "            if not read.done():\n                read.cancel()",
     "            if not read.done():\n                pass"),

    ("the jobs are asked one after another, so the later ones spend a deadline already spent",
     VIEW,
     "    async def one(wf_id: str, job: dict) -> dict:\n"
     "        handle = client.get_workflow_handle(wf_id, run_id=job.get(\"run_id\") or None)\n"
     "        got = await handle.query(JobWorkflow.verdict)\n",
     "    queue = asyncio.Lock()\n\n"
     "    async def one(wf_id: str, job: dict) -> dict:\n"
     "        handle = client.get_workflow_handle(wf_id, run_id=job.get(\"run_id\") or None)\n"
     "        async with queue:\n"
     "            got = await handle.query(JobWorkflow.verdict)\n"),

    ("a worker that is gone is remembered as an engine that is silent, and every read is refused",
     VIEW,
     "        if read not in answered:\n            log.info(",
     "        if read not in answered:\n            _did_not_answer()\n            log.info("),

    ("an engine remembered as silent is asked for verdicts anyway", VIEW,
     "    if left:\n        log.info(\"the engine did not answer a moment ago, so %d review",
     "    if False:\n        log.info(\"the engine did not answer a moment ago, so %d review"),

    ("a job that did not answer comes back as an EMPTY verdict — 'no review' — not as unread", VIEW,
     "    out: dict[str, dict | None] = dict.fromkeys(asked)",
     "    out: dict[str, dict | None] = dict.fromkeys(asked, {})"),

    ("the tech-lead asks each workflow itself again, raw", CONVERSATION,
     "    read = await review_verdicts(client, wanted)",
     "    from openfactory.runtime.temporal.workflow import JobWorkflow\n\n"
     "    read = {str(j[\"workflow_id\"]): await client.get_workflow_handle(\n"
     "        j[\"workflow_id\"]).query(JobWorkflow.verdict) for j in wanted}"),

    ("the tech-lead's reader drops the UNREADABLE marker, so a silent job says nothing at all",
     CONVERSATION,
     "        out[ref] = got if got is not None else {\"__unread__\": True}",
     "        if got is not None:\n            out[ref] = got"),

    ("the inbox asks every listed job again, not only the ones that became an item", APP,
     "        if len(out) > items_before:\n            waiting.append((j, review))",
     "        if True:\n            waiting.append((j, review))"),

    ("a job that did not answer is 'No review' on its card at the merge gate", APP,
     "    if raw is None:\n        return verdict_read.headline(None, unread=True)",
     "    if raw is None:\n        return verdict_read.headline(None)"),

    ("the items go out with the review nobody filled in", APP,
     "        review.update(_verdict_of(read, j))",
     "        _verdict_of(read, j)"),
]

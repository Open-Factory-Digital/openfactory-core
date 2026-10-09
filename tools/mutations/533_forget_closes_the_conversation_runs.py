"""`project forget` and `project forget-conversations` close the runs that still hold what was
said, so the engine's retention reaches them (#533), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/533_forget_closes_the_conversation_runs.py

Measured on a deployment: after `project forget` reported every layer done, the product's eight
conversation runs were still `Running`, one holding 76 entries, and an open run's history is never
retained away. The claims, each a row:

  1. the forgetting has an engine layer, and it terminates the product's idle conversation runs and
     the project's tech-lead run — no other product's (rows 1-4);
  2. a run with a turn at work is left open and said (row 5);
  3. the report names the retention, and an engine that could not close them fails the layer
     (rows 6-7);
  4. `forget-conversations` closes the conversation runs too, and only those (rows 8-9);
  5. what it keeps no longer promises a retention an open run never reaches (row 10).
"""

TEST = "tests/test_a_project_is_forgotten_in_one_command.py"

FORGET = "openfactory/product/forget.py"
CLI = "openfactory/cli.py"
REAL = "tests/test_a_forgotten_conversation_s_run_is_closed.py"

MUTATIONS = [
    ("TODAY'S DEFECT: nothing closes the runs, and the words wait for a retention that never starts",
     FORGET,
     "LAYERS = (CONVERSATIONS, ENGINE, LOOPS, RECORDS, INTAKE, CLOSED_CARDS, CONTEXT, PROCESSES)",
     "LAYERS = (CONVERSATIONS, LOOPS, RECORDS, INTAKE, CLOSED_CARDS, CONTEXT, PROCESSES)"),
    ("a run is counted closed and left running", FORGET,
     "        await client.get_workflow_handle(wid).terminate(reason=CLOSED_BECAUSE)\n"
     "        closed.append(wid)\n",
     "        closed.append(wid)\n",
     REAL),
    ("another product's conversations are closed with this one's", FORGET,
     "                if str(wf.id).startswith(prefix)]\n",
     "                ]\n"),
    ("the project's tech-lead run is left open", FORGET,
     "        if coordinator:\n            async for wf in client.list_workflows(",
     "        if False:\n            async for wf in client.list_workflows("),

    ("a turn at work is ended mid-turn", FORGET,
     '        if any(presence.get(k) for k in ("running", "working", "fast", "waiting")):\n'
     "            at_work.append(wid)\n",
     "        if False:\n            at_work.append(wid)\n",
     REAL),

    ("the retention is not said", FORGET,
     "    return Closed(runs=tuple(closed), at_work=tuple(at_work), retention=await "
     "_retention(client))\n",
     '    return Closed(runs=tuple(closed), at_work=tuple(at_work), retention="")\n'),
    ("an engine that could not close them is reported done", FORGET,
     "    if closed.unread:\n        return Went(ENGINE, FAILED, counts,",
     "    if False:\n        return Went(ENGINE, FAILED, counts,"),

    ("the deletion-request command leaves the runs open", CLI,
     "    closed = asyncio.run(forget.close_runs(where))\n",
     "    closed = forget.Closed()\n"),
    ("the deletion-request command closes the tech-lead run, which holds no conversation", CLI,
     "    closed = asyncio.run(forget.close_runs(where))\n",
     "    closed = asyncio.run(forget.close_runs(where, coordinator=forget.coordinator_id(name)))\n"),

    ("what it keeps still promises a retention an open run never reaches", FORGET,
     '    "the durable engine\'s history of each run this closes, until the engine\'s retention "\n'
     '    "expires it — the run itself is closed, so that retention starts",\n',
     '    "the durable engine\'s own history of each conversation\'s workflow, for its retention",\n'),
]

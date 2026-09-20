"""#159, proven by breaking it — a read the panel waits on is bounded, and silence is remembered.

MEASURED ON THE REAL STACK, an orphaned panel with the engine killed under it:

    route                  before          after
    /api/floor             38.8 s          3.0 s, then 4 ms, then 3 ms
    /api/inbox             8.9 s (500)     1 ms (500)
    /api/temporal/jobs     6.3 s           0.8 ms
    /api/board             8 ms            7 ms
    (engine healthy)       9-22 ms         9-22 ms — unchanged

FOUR CLAIMS:

  1. **Every read somebody waits on is bounded**, including the connect, whose own docstring
     recorded an attempt "STILL HANGING AFTER 40 s" with nothing bounding it.
  2. **An engine that ran out of time is not asked again for a moment**, so a page that re-reads
     the floor on every frame does not pay the deadline on every request.
  3. **The memory is a window and nothing else.** A refusal is an answer and is not remembered, and
     a recovered engine is picked up when the window passes, without a restart.
  4. **A write is never cancelled by a read's deadline.** A cancelled write is a request whose
     outcome nobody knows.

The guard is `tests/test_the_engine_answers_or_says_so.py`.
"""

TEST = "tests/test_the_engine_answers_or_says_so.py"

VIEW = "openfactory/runtime/temporal/view.py"

MUTATIONS = [
    ("THE DEFECT ITSELF: a read waits on an engine that never answers, for as long as the client's "
     "retries take", VIEW,
     "        answer = await asyncio.wait_for(coro, read_deadline() if seconds is None else "
     "seconds)",
     "        answer = await coro"),

    ("the connect is unbounded again — the 40 s hang its own docstring records", VIEW,
     '                entry.client = await _within("a connection", _connect())',
     "                entry.client = await _connect()"),

    ("silence is not remembered, so every request pays the deadline again", VIEW,
     "        _did_not_answer()\n",
     "        pass\n"),

    # RE-PINNED 2026-09-19: `review_verdicts` consults the same memory the same way, so this
    # anchor matched twice. It carries `_within`'s own next line now, which is that function's
    # and nobody else's.
    ("the memory is never consulted, which is the same thing one layer up", VIEW,
     "    left = unreachable_for()\n    if left:\n        coro.close()",
     "    left = unreachable_for()\n    if False:\n        coro.close()"),

    ("a WRITE is cut short by the read deadline, so a job nobody knows the fate of is started "
     "again", VIEW,
     "async def start_job(client: Client, params: JobParams) -> str:",
     '@_bounded_read("a start")\nasync def start_job(client: Client, params: JobParams) -> str:'),

    ("the deadline is not the deployment's to set", VIEW,
     '    return _seconds("OPENFACTORY_ENGINE_DEADLINE", 3.0)',
     "    return 3.0"),
]

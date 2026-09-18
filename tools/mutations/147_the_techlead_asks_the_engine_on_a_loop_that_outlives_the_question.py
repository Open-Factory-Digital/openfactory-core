"""#147: a worker that answers N questions does not hold N engine clients.

The first row puts the defect back. The rest are the ways the standing loop could be there and be
the same defect again — a loop per call, a loop per first caller — or be there and be worse than
what it replaced: stalling a running loop, or refusing every question for the rest of the
process's life once it has ended.
"""

TEST = "tests/test_the_techlead_asks_the_engine_on_a_loop_that_outlives_the_question.py"
CONVERSATION = "openfactory/techlead/conversation.py"
STANDING = "openfactory/runtime/temporal/standing.py"

MUTATIONS = [
    ("the gatherer opens a loop per question again, so the pool hands it a client per question",
     CONVERSATION,
     "        jobs, verdicts = from_a_thread(_run)",
     "        import asyncio\n\n        jobs, verdicts = asyncio.run(_run())"),

    ("the standing loop is made on every call — the defect, moved one file over", STANDING,
     "        if _STANDING is None or not _STANDING.thread.is_alive():",
     "        if True:"),

    ("two first callers each make a standing loop", STANDING,
     "    with _MAKING:\n        # A LOOP THAT ENDED IS REPLACED",
     "    if True:\n        # A LOOP THAT ENDED IS REPLACED"),

    ("a standing loop that ended is asked for ever, and every later question is refused", STANDING,
     "        if _STANDING is None or not _STANDING.thread.is_alive():",
     "        if _STANDING is None:"),

    ("a caller running a loop of its own is blocked on the answer instead of refused", STANDING,
     "    else:\n        raise RuntimeError(",
     "    else:\n        RuntimeError("),

    ("the standing thread is not a daemon, and holds the worker open after its shutdown", STANDING,
     "            thread = threading.Thread(target=_serve, args=(loop,), daemon=True,",
     "            thread = threading.Thread(target=_serve, args=(loop,), daemon=False,"),
]

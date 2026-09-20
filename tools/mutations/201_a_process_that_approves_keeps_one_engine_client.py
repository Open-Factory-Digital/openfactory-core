"""#201: a process that delivers N production approvals does not hold N engine clients.

The first two rows put the defect back, whole and by halves. The third is the fix the issue
sketched and this pull request REJECTED — the pool's client, taken from the standing loop — which
is the same defect again in the one process that reads on a loop of its own. The rest are the ways
a kept client could be kept wrongly: past a rotated credential, past the loop that made it, twice
by two first callers, or from one test into the next.

The last two rows are the safety of the call, which this change had to leave exactly as it was:
the gate re-asked before the signal, and a failure that is a sentence and never a traceback.
"""

TEST = "tests/test_a_process_that_approves_keeps_one_engine_client.py"
RELEASE = "openfactory/product/release.py"

MUTATIONS = [
    ("an approval opens a loop of its own again, so a client per approval", RELEASE,
     "        return from_a_thread(_run)",
     "        return asyncio.run(_run())"),

    ("the loop stands, but the client is opened on every approval all the same", RELEASE,
     "        if kept.client is None:\n            kept.client = await connect()",
     "        if True:\n            kept.client = await connect()"),

    ("the approval takes the POOL's client from the standing loop — the rejected shape: in the "
     "panel the two loops take turns emptying the pool", RELEASE,
     "        client = await _client()",
     "        from openfactory.runtime.temporal.view import connect as _pooled\n\n"
     "        client = await _pooled()"),

    ("a rotated credential is approved with the client that holds the old one", RELEASE,
     "    if kept is None or kept.target != target or kept.loop is not loop:",
     "    if kept is None or kept.loop is not loop:"),

    ("a standing loop that was replaced is handed the dead loop's client", RELEASE,
     "    if kept is None or kept.target != target or kept.loop is not loop:",
     "    if kept is None or kept.target != target:"),

    ("two first approvals at once each open a client", RELEASE,
     "    async with kept.lock:\n        if kept.client is None:",
     "    if True:\n        if kept.client is None:"),

    ("the seam forgets nothing, so one test's fake engine is the next test's engine", RELEASE,
     "    global _KEPT\n    _KEPT = None",
     "    global _KEPT"),

    ("…or the suite stops calling it", "tests/conftest.py",
     "    _release.forget_the_client()",
     "    _ = _release.forget_the_client"),

    ("the gate is no longer re-asked here before the signal", RELEASE,
     "        if not await _awaiting(client, name, issue):",
     "        if False:"),

    ("a connect that failed, or a caller refused by the standing loop, reaches the person as a "
     "traceback", RELEASE,
     "    except Exception as exc:  # noqa: BLE001 — a chat listener must never see a traceback",
     "    except ZeroDivisionError as exc:  # a chat listener must never see a traceback"),
]

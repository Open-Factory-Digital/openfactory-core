"""The floor's budget read leaves the panel's loop, once for everybody waiting, bounded (2026-09-19).

`_budget()` spawns `gh api rate_limit` and ran on the thread of the loop that serves the panel:
measured, one floor read stopped everything else for 0.50 s with a healthy `gh`, 5.02 s with one
that hangs and fails — on every read, because an unread budget is never cached — and ten readers
arriving together for 50.21 s and ten subprocesses.

The rows are: the read put back on the loop; the three ways the cure could be there and be wrong
(no single flight, no bound, a bound that throws the read away); the ways a hung read could come
out looking like something other than unread; and the slot shared between two different reads.
"""

TEST = "tests/test_the_budget_read_leaves_the_panels_loop.py"
READING = "openfactory/floor/reading.py"

MUTATIONS = [
    ("the blocking read runs on the loop's own thread again — the defect", READING,
     "    got = await asyncio.to_thread(_budget)",
     "    got = _budget()"),

    ("nobody joins a budget read in flight — ten floor reads at the expiry are ten subprocesses",
     READING,
     "            _budget_read.shared(lambda flight: _read_budget(flight, stamp)), "
     "budget_deadline())",
     "            _read_budget(_Flight(loop=asyncio.get_running_loop()), stamp), "
     "budget_deadline())"),

    ("the wait is unbounded, so a `gh` that hangs holds the floor for the subprocess's own 60s",
     READING,
     "_budget_read.shared(lambda flight: _read_budget(flight, stamp)), budget_deadline())",
     "_budget_read.shared(lambda flight: _read_budget(flight, stamp)), None)"),

    # RETIRED 2026-09-19: the row cut a second `asyncio.shield` around this call, and it survived
    # — `shared` already shields every waiter from the task, so the outer one was dead code. It was
    # removed rather than re-pinned, and the docstring says why it is not needed.

    ("a budget that was never read is reported as a healthy one", READING,
     '                    "still running and will fill the window if it lands.", budget_deadline())'
     '\n        return {"state": "unread"}',
     '                    "still running and will fill the window if it lands.", budget_deadline())'
     '\n        return {"state": "ok"}'),

    ("the deadline is not the deployment's to set", READING,
     '        wanted = float(os.environ.get("OPENFACTORY_BUDGET_DEADLINE", "") or 5.0)',
     "        wanted = 5.0"),

    ("a read that lost the slot fills the window anyway", READING,
     '    if got.get("state") != "unread" and _budget_read.holds(flight):',
     '    if got.get("state") != "unread":'),

    ("one slot serves both memos, so a schedule read and a budget read take it from each other",
     READING,
     "_budget_read = _OneAtATime()",
     "_budget_read = _intake_read"),
]

"""A worker that answers N questions holds ONE engine client, not N — issue #147.

`techlead/conversation.py::gather_jobs` ran `asyncio.run(_run())` once per question, and `_run`
awaits `view.connect()`. The pool behind `connect()` is keyed by `(engine target, RUNNING LOOP)`
and holds one entry in total (#134/#145), so a loop per question is a key per question: one gRPC
client opened per question and dropped unreleased — temporalio 1.33.0 exposes no `close`,
`shutdown`, `__aexit__` or `__del__` on `Client`, `ServiceClient` or the bridge client under it
(re-checked against the INSTALLED version 2026-09-17). That is #134's leak in the worker process,
on a human's clock instead of a poll tick.

The fix is `view.read_sync()`: ONE lazily-started daemon loop per process, submitted to with
`run_coroutine_threadsafe`, blocking the calling thread for the result. Measured as connect counts
through the real `gather_jobs`, 2026-09-17 — five questions: **5 clients before, 1 after**. No
latency is claimed: there is no live engine in this container and the suite forbids reaching one,
which is the same number PR #145 and #152 claimed.

EIGHT CLAIMS, one row each:

  1. the helper is USED — `gather_jobs` does not open a loop of its own again, which is the defect
     itself and the only row that cuts outside `view.py`;
  2. the loop is REUSED across calls — a loop per read is a key per read in the pool, which is a
     client per read by another door;
  3. the thread is a DAEMON — `run_forever` never returns and nothing stops this loop in
     production, so a non-daemon one holds the process open after the last question;
  4. a caller whose thread already has a running loop is REFUSED BY NAME — `read_sync` blocks
     until the engine answers, and `actions/catalog.py::_ask` and `activities.py::techlead_ask`
     are both built around that refusal (`asyncio.to_thread`);
  5. what the coroutine RAISED reaches the sync caller — `gather_jobs`' own `except Exception` net
     is what turns an unreachable engine into `[]` rather than a traceback in a person's answer;
  6. the create is behind a LOCK — the worker answers questions on `asyncio.to_thread`, so two
     questions at once arrive on two threads at once and `Thread.start()` releases the GIL inside
     the window between the check and the assignment;
  7. the loop is started LAZILY — `openfactory doctor`, the CLI's fast paths and a worker that
     only executes jobs all import this module and never ask it anything;
  8. `reset_read_loop()` takes the POOL with it, because a client keyed to a loop that has been
     stopped can never be handed to anybody again — the one thing that must not be left to chance
     in a guard that counts connects.

Row 3 is why the guard's fixture calls `reset_read_loop()` on BOTH ends: a non-daemon thread
running `run_forever` would hold pytest open after the last test, and a hang reads nothing like the
red row it is.

Case 5 of the guard (`gather_jobs` still answers `[]` on an unreachable engine) is the one case no
row cuts: it is existing documented behaviour this change must not regress, rather than a claim
this change makes.

ROW 8 SURVIVED THE FIRST RUN, 2026-09-17, AND IT WAS THE GUARD'S FAULT RATHER THAN THE ROW'S. Case
9 stopped the read loop without ever having connected through it, so the pool it asserted empty was
empty before the reset ran — `tests/conftest.py` clears it before every test. The case now pools a
client first and asserts it is there before stopping the loop. The row was not reworded.

The guard under test is `tests/test_the_worker_holds_one_engine_client.py`. The pool's own loop
term is unchanged and stays proven by `tools/mutations/134_one_engine_client_per_panel.py` row 2.
"""

TEST = "tests/test_the_worker_holds_one_engine_client.py"

VIEW = "openfactory/runtime/temporal/view.py"
CONV = "openfactory/techlead/conversation.py"

MUTATIONS = [
    # ── 1. the defect itself, at the surface that had it ───────────────────────────────────────
    ("the gatherer opens a loop of its own again, so every question is a new key in the pool and "
     "a new engine client nothing can release",
     CONV,
     "    try:\n"
     "        from openfactory.runtime.temporal.view import read_sync\n"
     "\n"
     "        jobs, verdicts = read_sync(_run())",
     "    try:\n"
     "        import asyncio\n"
     "\n"
     "        jobs, verdicts = asyncio.run(_run())"),

    # ── 2. one loop per process, not per read ──────────────────────────────────────────────────
    ("a new read loop is started per call, so the pool is re-keyed per question exactly as "
     "`asyncio.run` re-keyed it",
     VIEW,
     "        if _READ_LOOP is None:",
     "        if True:  # a fresh loop every time"),

    # ── 3. the thread must not hold the process open ───────────────────────────────────────────
    ("the loop thread is not a daemon, so `run_forever` keeps the interpreter alive after the "
     "last question is answered",
     VIEW,
     "                                      daemon=True)",
     "                                      daemon=False)"),

    # ── 4. the refusal `_ask` is built around ──────────────────────────────────────────────────
    ("a caller that already has a running loop is no longer refused, so a read that blocks until "
     "the engine answers can be started on a loop that is serving something else",
     VIEW,
     "    if running is not None:",
     "    if False:  # nothing is refused"),

    # ── 5. the exception the caller's net is waiting for ───────────────────────────────────────
    ("what the read raised is swallowed instead of reaching the sync caller, so `gather_jobs`' "
     "net catches nothing and an unreachable engine answers with something that is not an answer",
     VIEW,
     "    return asyncio.run_coroutine_threadsafe(coro, _read_loop()).result()",
     "    fut = asyncio.run_coroutine_threadsafe(coro, _read_loop())\n"
     "    try:\n"
     "        return fut.result()\n"
     "    except Exception:  # noqa: BLE001\n"
     "        return None"),

    # ── 6. two questions at once are two threads at once ───────────────────────────────────────
    ("the create is not behind a lock, so a worker answering two questions at once starts two "
     "read loops — two pool keys, which is two engine clients",
     VIEW,
     "    with _READ_LOOP_LOCK:\n"
     "        if _READ_LOOP is None:",
     "    if True:  # the lock is gone\n"
     "        if _READ_LOOP is None:"),

    # ── 7. nothing starts until somebody asks ──────────────────────────────────────────────────
    ("the loop is started at IMPORT instead of on first use, so every process that so much as "
     "imports this module pays for a thread it may never ask anything of",
     VIEW,
     "",
     "\n\n_read_loop()  # started at import, not on first use\n"),

    # ── 8. the reset seam does not leave a client keyed to a stopped loop ──────────────────────
    ("`reset_read_loop()` leaves the pool behind, so a test that stops the loop starts from an "
     "entry keyed to a loop nothing can run on again",
     VIEW,
     "    if thread is not None:\n"
     "        thread.join(timeout=5.0)\n"
     "    reset_clients()",
     "    if thread is not None:\n"
     "        thread.join(timeout=5.0)"),
]

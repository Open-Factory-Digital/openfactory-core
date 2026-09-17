"""The panel holds one engine client per target, instead of opening one per request — issue #134.

`view.connect()` was three lines with no memory, and every read-side caller resolves through it —
`/api/floor` and `/api/floor/{project}` (one of the two per engine frame), `/api/inbox`,
`/api/coordinator/messages`, `/api/temporal/jobs`, `/api/decisions`, `actions/catalog.py::
_connected()`. The reporter measured, 2026-09-15, on a freshly restarted panel with no browser
attached: six sequential `/api/floor` requests took it from 20 to 32 open gRPC connections; 41
connections and 20-27 s per request overnight, against 0.18 s for the same gather in-process.

TEN CLAIMS, one row each:

  1. the pool is consulted at all;
  2. the running loop is part of the reuse condition — twelve `asyncio.run(` call sites in the
     package open a loop of their own (counted 2026-09-17; eight of them in `cli.py`), so a client
     from a closed loop is a BROKEN read in a path that works today. The named example was
     `techlead/conversation.py::gather_jobs`, once per question, until #147 moved it onto
     `view.read_sync`'s one read loop — the loop term is unchanged and the claim stands;
  3. …and a new entry EMPTIES the pool rather than joining it, so a re-keyed target (a moved
     address, a rotated key, a cert rewritten in place) leaves no client behind;
  4. the create is behind a lock, so a cold process racing itself opens one client and not N;
  5. a failed connect is never cached — a frozen panel is the same class of defect as the leak;
  6. …and a failure IS shared with the callers queued behind it, or an outage becomes a queue
     every read-side request joins: six concurrent callers against a 0.5 s refusal failed at
     0.5/1.0/1.5/2.0/2.5/3.0 s under the lock alone, against 0.5 s each before the pool existed;
  7. the retained failure is re-raised with its traceback CLEARED, or one module-level object
     grows a frame per waiter for as long as the engine is down (5 / 23 / 2003 frames after
     1 / 10 / 1000 re-raises, measured through the pool on 2026-09-15);
  8. the engine target is part of the key, so a moved engine is not read through the old client;
  9. the SECRET is not — a pool key reaches a log line, a `repr` and a test failure message;
 10. the key digests the TLS files' CONTENTS, so a cert rewritten in place at an unchanged path
     is picked up — the per-request re-read the pool would otherwise have silently dropped.

RE-PINNED 2026-09-15, in the PR that answered the review of #145: rows 2, 3 and 5 anchored on
lines that review replaced. Row 2's anchor also lost its `or entry.loop.is_closed()` term — a
mutation deleting that term SURVIVED the guard whole (`10 passed`), which in this repository means
the code was dead, so it was removed rather than guarded.

The guard under test is `tests/test_the_panel_holds_one_engine_client.py`.
"""

TEST = "tests/test_the_panel_holds_one_engine_client.py"

VIEW = "openfactory/runtime/temporal/view.py"
CONN = "openfactory/runtime/temporal/connection.py"

MUTATIONS = [
    # ── 1. the pool is never consulted ─────────────────────────────────────────────────────────
    ("the pool is never consulted, so every request opens a client again — the defect itself",
     VIEW,
     "    entry = _CLIENTS.get(key)",
     "    entry = None  # never a hit"),

    # ── 2-3. the loop half, which is the regression guard ──────────────────────────────────────
    ("the loop is not checked, so a closed loop's client is handed to the next `asyncio.run`",
     VIEW,
     "    if entry is not None and entry.loop is not loop:",
     "    if entry is not None and False:"),

    ("a new entry JOINS the pool instead of emptying it, so every re-keyed target — a moved "
     "address, a rotated API key, a cert rewritten in place — leaves its client behind for the "
     "life of the process",
     VIEW,
     "        _CLIENTS.clear()\n"
     "        entry = _CLIENTS[key] = _Pooled(loop=loop, lock=asyncio.Lock())",
     "        entry = _CLIENTS[key] = _Pooled(loop=loop, lock=asyncio.Lock())"),

    # ── 4. single flight ───────────────────────────────────────────────────────────────────────
    ("there is no single flight, so a cold process opens one client per concurrent request",
     VIEW,
     "    async with entry.lock:",
     "    if True:  # the lock is gone"),

    # ── 5-7. what happens when the connect FAILS ───────────────────────────────────────────────
    ("a failure is cached like a success, so one unreachable moment freezes the panel until "
     "somebody restarts it",
     VIEW,
     "        if entry.client is None and entry.failures != seen:",
     "        if entry.client is None and entry.error is not None:"),

    ("the failure is not shared, so every caller queued behind a failing attempt makes the same "
     "attempt again in turn and an engine outage becomes a queue",
     VIEW,
     "        if entry.client is None and entry.failures != seen:\n"
     "            # The attempt this caller queued behind has just failed;",
     "        if entry.client is None and entry.failures != seen and False:\n"
     "            # The attempt this caller queued behind has just failed;"),

    ("the retained failure is re-raised WITH its traceback, so one module-level exception object "
     "grows a frame per queued caller for as long as the engine is unreachable",
     VIEW,
     "            raise entry.error.with_traceback(None)",
     "            raise entry.error"),

    ("the failure the pool retained is never let go, so a recovered engine leaves an exception "
     "and its traceback frames held for the life of the process",
     VIEW,
     "            entry.error = None\n        return entry.client",
     "        return entry.client"),

    # ── 9-11. what is in the key, and what must never be ───────────────────────────────────────
    ("the engine target is not part of the key, so a moved engine is read through the old client",
     VIEW,
     "    key = fingerprint()",
     '    key = ("one-engine-per-process",)'),

    ("the raw TEMPORAL_API_KEY goes into the key instead of a digest, so the deployment's "
     "credential travels in every repr and log line the pool reaches",
     CONN,
     "    return address(), namespace(), digest",
     '    return address(), namespace(), os.environ.get("TEMPORAL_API_KEY") or ""'),

    ("the key digests the TLS PATHS instead of the files' contents, so a cert rewritten in place "
     "at an unchanged path is served by a client holding the superseded one",
     CONN,
     '        "tls_cert", cert, _contents(cert),\n        "tls_key", key, _contents(key),',
     '        "tls_cert", cert,\n        "tls_key", key,'),
]

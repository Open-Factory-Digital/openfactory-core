"""The panel holds one engine client per target, instead of opening one per request — issue #134.

`view.connect()` was three lines with no memory, and every read-side caller resolves through it —
`/api/floor` and `/api/floor/{project}` (one of the two per engine frame), `/api/inbox`,
`/api/coordinator/messages`, `/api/temporal/jobs`, `/api/decisions`, `actions/catalog.py::
_connected()`. The reporter measured, 2026-09-15, on a freshly restarted panel with no browser
attached: six sequential `/api/floor` requests took it from 20 to 32 open gRPC connections; 41
connections and 20-27 s per request overnight, against 0.18 s for the same gather in-process.

SEVEN CLAIMS, one row each:

  1. the pool is consulted at all;
  2. the running loop is part of the reuse condition — `techlead/conversation.py::gather_jobs`
     runs `asyncio.run` per question, so a client from a closed loop is a BROKEN read in a path
     that works today;
  3. …and a replaced entry is dropped rather than kept, because a pool holding one entry per dead
     loop is the same leak wearing a cache's name;
  4. the create is behind a lock, so a cold process racing itself opens one client and not N;
  5. a failed connect is never cached — a frozen panel is the same class of defect as the leak;
  6. the engine target is part of the key, so a moved engine is not read through the old client;
  7. the SECRET is not — a pool key reaches a log line, a `repr` and a test failure message.

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
     "    if entry is not None and (entry.loop is not loop or entry.loop.is_closed()):",
     "    if entry is not None and False:"),

    ("the replaced entry is kept beside the live one, so the pool grows a dead loop per call",
     VIEW,
     "    key = fingerprint()\n    loop = asyncio.get_running_loop()",
     "    loop = asyncio.get_running_loop()\n    key = (*fingerprint(), id(loop))"),

    # ── 4. single flight ───────────────────────────────────────────────────────────────────────
    ("there is no single flight, so a cold process opens one client per concurrent request",
     VIEW,
     "    async with entry.lock:",
     "    if True:  # the lock is gone"),

    # ── 5. a failure is never cached ───────────────────────────────────────────────────────────
    ("a failure is cached like a success, so one unreachable moment freezes the panel until "
     "somebody restarts it",
     VIEW,
     "        if entry.client is None:\n"
     "            entry.client = await _connect()  # dev-server or Temporal Cloud, per env\n"
     "        return entry.client",
     "        if entry.client is None:\n"
     "            try:\n"
     "                entry.client = await _connect()\n"
     "            except Exception as exc:\n"
     "                entry.client = exc\n"
     "        if isinstance(entry.client, Exception):\n"
     "            raise entry.client\n"
     "        return entry.client"),

    # ── 6-7. what is in the key, and what must never be ────────────────────────────────────────
    ("the engine target is not part of the key, so a moved engine is read through the old client",
     VIEW,
     "    key = fingerprint()",
     '    key = ("one-engine-per-process",)'),

    ("the raw TEMPORAL_API_KEY goes into the key instead of a digest, so the deployment's "
     "credential travels in every repr and log line the pool reaches",
     CONN,
     "    return address(), namespace(), digest",
     '    return address(), namespace(), os.environ.get("TEMPORAL_API_KEY") or ""'),
]

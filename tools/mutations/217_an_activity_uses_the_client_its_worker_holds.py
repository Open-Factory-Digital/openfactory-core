"""#217, proven by breaking it — an activity uses the engine client its worker already holds.

Five activities called `connection.connect()` on every execution, `available_slots` on every
poller tick, inside a worker that was already holding a connected client. Measured on a real
worker over a throwaway dev server: 60 ticks, 60 connects, a sawtooth of up to 23 established
connections; asking the seam instead, 0 connects and 1 connection.

FOUR CLAIMS:

  1. **Each of the five asks the seam and opens nothing.** One row per activity puts the old
     connect back; the counted case reads `6 opened` and the structural one names the line.
  2. **The seam is the only place the SDK call is spelled.** An activity that writes
     `activity.client()` itself is green on every count and red on the structural case — which is
     the case that exists for the sixth activity.
  3. **The refusals keep their names.** Outside an activity, in a `def` activity, in an environment
     with no client: each says which it is, is non-retryable and typed, and is NOT swallowed by
     the two activities that forgive every engine failure.
  4. **The tests that used to double `connection.connect` now run the activity as an activity**,
     so putting the connect back fails THEM too, by the suite's own live-engine barrier.

The guard is `tests/test_an_activity_uses_the_client_its_worker_holds.py`.
"""

TEST = "tests/test_an_activity_uses_the_client_its_worker_holds.py"

ACTS = "openfactory/runtime/temporal/activities.py"

_CONNECT = ("    from openfactory.runtime.temporal.connection import connect\n\n"
            "    client = await connect()\n")

MUTATIONS = [
    # ── 1. each of the five, back to a client of its own ─────────────────────────────────────────
    ("THE DEFECT ITSELF: `available_slots` opens a client on every poller tick again", ACTS,
     "    # list — see `engine_client`.\n    client = engine_client()\n",
     "    # list — see `engine_client`.\n" + _CONNECT),

    ("`start_jobs` opens a client of its own again", ACTS,
     "    client = engine_client()\n    # STAMPED HERE, at launch,",
     _CONNECT + "    # STAMPED HERE, at launch,"),

    ("`notify_coordinator` opens a client of its own again", ACTS,
     "    # reduced to \"notify_coordinator failed\" in a log nobody reads.\n"
     "    client = engine_client()\n",
     "    # reduced to \"notify_coordinator failed\" in a log nobody reads.\n" + _CONNECT),

    ("`notify_coordinator_say` opens a client of its own again", ACTS,
     "    client = engine_client()  # outside the `try`, for `notify_coordinator`'s reason\n",
     _CONNECT),

    ("`techlead_watch` opens a client of its own again", ACTS,
     "    await asyncio.to_thread(_repoint_product_orphans, project)\n\n"
     "    client = engine_client()\n",
     "    await asyncio.to_thread(_repoint_product_orphans, project)\n\n" + _CONNECT),

    ("an activity reaches for the PANEL'S POOL instead: one client, but not the worker's", ACTS,
     "    # list — see `engine_client`.\n    client = engine_client()\n",
     "    # list — see `engine_client`.\n"
     "    from openfactory.runtime.temporal import view as tv_pool\n\n"
     "    client = await tv_pool.connect()\n"),

    # ── 2. the seam is the one place the SDK call is spelled ─────────────────────────────────────
    ("an activity spells `activity.client()` itself and walks past the seam's refusals", ACTS,
     "    # list — see `engine_client`.\n    client = engine_client()\n",
     "    # list — see `engine_client`.\n    client = activity.client()\n"),

    # ── 3. the refusals ──────────────────────────────────────────────────────────────────────────
    ("outside an activity the seam stops refusing by name: the SDK's bare RuntimeError escapes",
     ACTS,
     "    if not activity.in_activity():\n        raise NoEngineClientHere(\n",
     "    if False:\n        raise NoEngineClientHere(\n"),

    ("the outside refusal stops saying which door a caller uses instead", ACTS,
     "a command connects \"\n            \"through `connection.connect()`, the panel through "
     "`view.connect()`, and a test runs \"\n",
     "and a test runs \"\n"),

    ("a `def` activity hears the SDK's bare `No client available` again", ACTS,
     "        return activity.client()\n    except RuntimeError as exc:\n",
     "        return activity.client()\n    except KeyError as exc:\n"),

    ("the `def` refusal loses its remedy", ACTS,
     "Declare it `async def` and move the blocking work into \"\n"
     "            \"`asyncio.to_thread`; in a test,",
     "In a test,"),

    ("the refusal becomes RETRYABLE: the whole budget spent re-asking about a signature", ACTS,
     '        super().__init__(why, type="NoEngineClientHere", non_retryable=True)\n',
     '        super().__init__(why, type="NoEngineClientHere")\n'),

    ("the refusal loses its TYPE, so the engine's history calls it an ApplicationError", ACTS,
     '        super().__init__(why, type="NoEngineClientHere", non_retryable=True)\n',
     '        super().__init__(why, non_retryable=True)\n'),

    ("`notify_coordinator` asks INSIDE its `try`: the refusal becomes 'notify_coordinator failed'",
     ACTS,
     "    # reduced to \"notify_coordinator failed\" in a log nobody reads.\n"
     "    client = engine_client()\n    try:\n",
     "    # reduced to \"notify_coordinator failed\" in a log nobody reads.\n"
     "    try:\n        client = engine_client()\n"),

    ("`notify_coordinator_say` asks INSIDE its `try` and swallows the refusal", ACTS,
     "    client = engine_client()  # outside the `try`, for `notify_coordinator`'s reason\n"
     "    try:\n",
     "    try:\n        client = engine_client()\n"),

    # ── 4. the moved tests are real: the old connect fails them too ──────────────────────────────
    ("`start_jobs` connects for itself: the stamp tests have no connect double left to lean on",
     ACTS,
     "    client = engine_client()\n    # STAMPED HERE, at launch,",
     _CONNECT + "    # STAMPED HERE, at launch,",
     "tests/test_the_cloud_is_a_directory_delete.py"),

    ("`start_jobs` connects for itself: the declared-image launch test fails", ACTS,
     "    client = engine_client()\n    # STAMPED HERE, at launch,",
     _CONNECT + "    # STAMPED HERE, at launch,",
     "tests/test_the_box_image_resolves_in_one_place.py"),

    ("`techlead_watch` connects for itself: the Jira floor is never read", ACTS,
     "    await asyncio.to_thread(_repoint_product_orphans, project)\n\n"
     "    client = engine_client()\n",
     "    await asyncio.to_thread(_repoint_product_orphans, project)\n\n" + _CONNECT,
     "tests/test_the_techlead_sees_a_jira_floor.py"),
]

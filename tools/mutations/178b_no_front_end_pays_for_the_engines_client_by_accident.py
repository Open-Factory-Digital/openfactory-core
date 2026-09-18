"""#178, second half, proven by breaking it — the attended half reaches the sink, and every other
reach for the engine from outside it is guarded or named.

The route-and-command sweep of #178 found a hole it could not itself see into: six sites of the
attended half imported `runtime.temporal.activities._metrics_sink` — a one-line wrapper over the
deployment's one sink door, in a module that imports `temporalio`. Four sat in an `except
Exception` and recorded nothing, silently; `identity/people.py` did not, so `openfactory people
invite` answered `could not people_invite: No module named 'temporalio'` on an install made without
the `runtime` extra.

FOUR CLAIMS:

  1. **The attended half calls the door itself** (`observability.registry.deployment_metrics_sink`)
     and records without the engine's client; the worker's name for the door still asks it at call
     time, so one patch reaches both.
  2. **A static sweep holds the class.** Every import of a module that costs `temporalio`, made
     from outside `openfactory/runtime/temporal/`, is inside a `try` that catches it, behind
     `host.the_client()`, in a nested function only called under such a `try`, in an action row's
     body, or on a named list held exactly. The sweep itself is cut below, so it is known to bite.
  3. **The action layer names the install.** `perform`'s catch-all is the one guard every engine
     row shares; it says `host.CLIENT_MISSING` when the import is what the row died of — and only
     then.
  4. **`poller status` says the same sentence** instead of asking whether the engine is reachable.

The guard is `tests/test_no_front_end_pays_for_the_engines_client_by_accident.py`.
"""

TEST = "tests/test_no_front_end_pays_for_the_engines_client_by_accident.py"
PANEL = "tests/test_the_panel_serves_without_the_engines_client.py"

ACTIONS = "openfactory/actions/__init__.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"
APP = "openfactory/api/app.py"
CLI = "openfactory/cli.py"
HOST = "openfactory/runtime/host.py"
MESSAGES = "openfactory/memory/messages.py"
PEOPLE = "openfactory/identity/people.py"
READING = "openfactory/floor/reading.py"
TECHLEAD = "openfactory/techlead/conversation.py"
TRANSCRIPT = "openfactory/memory/transcript.py"

_DOOR = "from openfactory.observability.registry import deployment_metrics_sink"
_WRAPPER = ("from openfactory.runtime.temporal.activities import _metrics_sink as "
            "deployment_metrics_sink")

MUTATIONS = [
    # ── 1. the six sites ────────────────────────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: the people store reaches across the runtime for the worker's wrapper",
     PEOPLE, f"    {_DOOR}\n", f"    {_WRAPPER}\n"),

    ("the transcript's reader-side sink comes from the worker's wrapper again", TRANSCRIPT,
     f"    {_DOOR}\n\n    return deployment_metrics_sink()",
     f"    {_WRAPPER}\n\n    return deployment_metrics_sink()"),

    ("the transcript's writer does — inside a `try`, so it records nothing and says nothing",
     TRANSCRIPT,
     f"        {_DOOR}\n\n        now = datetime.now(UTC)",
     f"        {_WRAPPER}\n\n        now = datetime.now(UTC)"),

    ("the messages do — inside a `try`, so what the factory said is silently not kept", MESSAGES,
     f"            {_DOOR}\n", f"            {_WRAPPER}\n"),

    ("the chat's spend does — inside a `try`, so the pass is silently unpriced", TECHLEAD,
     f"        {_DOOR}\n\n        deployment_metrics_sink().record(MetricRecord(\n"
     '            project=getattr(project, "name", "") or "", ticket="chat",',
     f"        {_WRAPPER}\n\n        deployment_metrics_sink().record(MetricRecord(\n"
     '            project=getattr(project, "name", "") or "", ticket="chat",'),

    ("the worker's name for the door stops asking the door, so a fake handed to it misses the "
     "worker", ACTIVITIES,
     "    return deployment_metrics_sink()\n",
     "    from openfactory.observability.registry import build_metrics_sink\n\n"
     '    return build_metrics_sink("null")\n'),

    # ── 2. the other reaches the sweep found ────────────────────────────────────────────────────
    ("the doctor imports the worker for one string again", CLI,
     "        from openfactory.runtime.temporal.vocabulary import WORKER_ROLE\n",
     "        from openfactory.runtime.temporal.worker import WORKER_ROLE\n"),

    ("the floor's job read imports the engine's reader above its `try` again", READING,
     "async def _jobs(client) -> list[dict] | None:\n    try:\n",
     "async def _jobs(client) -> list[dict] | None:\n"
     "    from openfactory.runtime.temporal import view as tv  # noqa: F401\n    try:\n"),

    ("the inbox's verdict read imports the workflow above its `try` again", APP,
     "    from openfactory.review import verdict as verdict_read\n\n"
     '    wf_id = job.get("workflow_id")\n',
     "    from openfactory.review import verdict as verdict_read\n"
     "    from openfactory.runtime.temporal.workflow import JobWorkflow  # noqa: F401\n\n"
     '    wf_id = job.get("workflow_id")\n'),

    # ── the sweep's own teeth ───────────────────────────────────────────────────────────────────
    ("THE SWEEP GOES BLIND AT ONE REMOVE: a module that imports a module that imports the library "
     "is no longer counted", TEST,
     "                and (any(m.split(\".\")[0] == LIBRARY for m in loaded) or loaded & costly)}",
     "                and any(m.split(\".\")[0] == LIBRARY for m in loaded)}"),

    ("any `try` counts as a guard, whatever it catches", TEST,
     "def _catches_import(handlers: list[ast.ExceptHandler]) -> bool:\n",
     "def _catches_import(handlers: list[ast.ExceptHandler]) -> bool:\n    return True\n"),

    ("a nested function is excused wherever it is called from", TEST,
     "            return bool(sites) and all(sites)\n",
     "            return True\n"),

    ("asking `the_client()` AFTER the import counts as asking first", TEST,
     "                       and node.lineno < line and function in where\n",
     "                       and function in where\n"),

    # ── 3. the action layer ─────────────────────────────────────────────────────────────────────
    ("an engine row that dies of the missing library says only `No module named …` again",
     ACTIONS,
     "        if the_client_is_what_is_missing(link):\n            return CLIENT_MISSING\n",
     "        if False:\n            return CLIENT_MISSING\n"),

    ("only the head of the chain is read, so a row that wraps its failure loses the remedy",
     ACTIONS,
     "        link = link.__cause__ or link.__context__\n",
     "        link = None\n"),

    ("…and the reverse: ANY failed import is blamed on the engine's client", HOST,
     "    return (isinstance(exc, ImportError)\n"
     '            and (getattr(exc, "name", "") or "").split(".")[0] == "temporalio")\n',
     "    return isinstance(exc, ImportError)\n"),

    # ── 4. poller status ────────────────────────────────────────────────────────────────────────
    ("`poller status` asks whether the engine is reachable on an install that cannot reach one",
     CLI,
     '    _refuse_without_the_client("the poller\'s schedule cannot be read", code=2)\n', ""),
]

"""The worked example: #127's `stop` row, re-proven through the shared runner.

A plan is a point-in-time proof. This one is committed as the template for the shape — one
sentence per cut naming the PROPERTY it breaks, the exact anchor, and what it becomes. Re-running
it later is optional; if the anchors rotted, the runner refuses loudly, which is the correct
answer for a proof about code that has since moved.
"""

TEST = "tests/test_a_wedged_job_has_an_exit.py"

MUTATIONS = [
    ("a job at a gate is terminated anyway",
     "openfactory/actions/catalog.py",
     "    waiting = await _what_it_is_waiting_on(handle)\n    if waiting:",
     "    if False:\n        waiting = None"),

    ("a job that is not running is terminated",
     "openfactory/actions/catalog.py",
     '    if str(tv.status_label(described.status)) != "running":',
     "    if False:"),

    ("a tracker that refused is reported as success",
     "openfactory/actions/catalog.py",
     "        return False\n    return True\n\n\n# ── ask —",
     "        return True\n    return True\n\n\n# ── ask —"),

    ("the browser decides what wedged means",
     "openfactory/runtime/temporal/view.py",
     '        row["wedged"] = is_wedged(row, live=live)',
     '        row["wedged"] = False'),

    ("the wedged rule stops excluding a gated job",
     "openfactory/runtime/temporal/view.py",
     '            and (row.get("action") or None) is None',
     "            and True"),

    ("an unreadable start time reads as for ever",
     "openfactory/runtime/temporal/view.py",
     "    if not when:\n        return 0.0",
     "    if not when:\n        return 9999.0"),

    ("the typed sentence stops reaching the row",
     "openfactory/actions/floor_intents.py",
     '    "stop": "stop",\n}',
     "}"),

    ("the tech-lead sends people back to the engine",
     "openfactory/techlead/voice.py",
     '"nothing else here reaches it. `stop #{ticket}` ends it and frees the queue — it "',
     '"nothing else here reaches it. Open Temporal and terminate the workflow — it "'),
]

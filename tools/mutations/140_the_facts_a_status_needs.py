"""#140: the three facts a status vocabulary cannot be honest without.

The cadence of the poller, the wake-up of a parked job, and the existence of a wedged one. Each cut
below restores a state where a screen would have to guess — and the whole point of the card is that
a screen that guesses is worse than one that says it does not know.

The last cuts go the other way: they make the platform CLAIM something. A cadence read that blows
up must not cost the switch answer; a ten-year decision park must not be rendered as a date; a
healthy running job must not ask for a human.
"""

TEST = "tests/test_a_poller_that_is_on_is_not_a_poller_that_ticks.py"
VIEW = "openfactory/runtime/temporal/view.py"
WF = "openfactory/runtime/temporal/workflow.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # ── the poller's cadence ────────────────────────────────────────────────────────────────────
    ("the schedule's own interval is dropped, so 'every 3 min' goes back to being a literal", VIEW,
     '        "every_s": None if every is None else every.total_seconds(),',
     '        "every_s": None,'),

    ("the last tick is dropped, so a stopped poller reads like a healthy one", VIEW,
     '        "fired_ago_s": _ago(fired),', '        "fired_ago_s": None,'),

    ("an overdue tick is clamped to zero, rendering a dead poller as about to fire", VIEW,
     '        "next_in_s": None if nxt is None else (nxt - now).total_seconds(),',
     '        "next_in_s": None if nxt is None else max(0.0, (nxt - now).total_seconds()),'),

    ("a disagreeing clock produces a tick that fired in the future", VIEW,
     "        return None if when is None else max(0.0, (now - when).total_seconds())",
     "        return None if when is None else (now - when).total_seconds()"),

    ("the moment a worker picked the tick up is reported as the tick itself", VIEW,
     "    fired = max((r.scheduled_at or r.started_at for r in recent\n"
     "                 if (r.scheduled_at or r.started_at)), default=None)",
     "    fired = max((r.started_at or r.scheduled_at for r in recent\n"
     "                 if (r.started_at or r.scheduled_at)), default=None)"),

    ("the first tick in the list is reported instead of the latest", VIEW,
     "    fired = max((r.scheduled_at or r.started_at for r in recent\n"
     "                 if (r.scheduled_at or r.started_at)), default=None)",
     "    fired = next((r.scheduled_at or r.started_at for r in recent\n"
     "                 if (r.scheduled_at or r.started_at)), None)"),

    ("a schedule that never fired is made indistinguishable from an unreadable one", VIEW,
     '        "num_actions": getattr(info, "num_actions", None),',
     '        "num_actions": None,'),

    ("nothing-was-said becomes zero, which is a claim", VIEW,
     "    if info is None and spec is None:\n        return dict(unread)",
     "    if info is None and spec is None:\n        return dict.fromkeys(unread, 0)"),

    # ── the other direction: an enrichment must never cost the answer ────────────────────────────
    ("a cadence read that blows up takes the switch answer down with it", VIEW,
     "        try:\n            cadence = _cadence(getattr(desc, \"info\", None), "
     "getattr(desc.schedule, \"spec\", None),\n                               unread)\n"
     "        except Exception as exc:  # noqa: BLE001 — an unreadable cadence is reported, "
     "not raised\n"
     "            log.warning(\"could not read the cadence of %s (%s) — the switch still "
     "answers\",\n"
     "                        schedule_id, str(exc)[:120])\n"
     "            cadence = dict(unread)",
     "        cadence = _cadence(getattr(desc, \"info\", None), "
     "getattr(desc.schedule, \"spec\", None),\n                           unread)"),
]

#: The park's wake-up and the wedged item are the same card, guarded by a different file — so each
#: carries its own pytest target (the runner's optional 5th element). Without it these would run
#: against the cadence guard, which does not cover them, and would survive for the wrong reason.
WAIT = "tests/test_a_wait_can_say_until_when.py"
SECOND = [
    ("the wake-up goes back to the vendor string the engine refuses to obey", WF,
     '                        "wakes_at": ((parked_at + timeout).isoformat()',
     '                        "wakes_at": (getattr(result, "retry_at", None)'),

    ("a ten-year decision park is rendered as a date in the next decade", WF,
     "                                     if timeout <= _HELD_UNTIL_ANSWERED else None),",
     "                                     if True else None),"),

    ("a wall clock replaces the replay-safe one", WF,
     "        parked_at = workflow.now()",
     "        import datetime as _dt; parked_at = _dt.datetime.now(_dt.UTC)"),

    ("the deadline stops at the workflow and reaches no channel", APP,
     '                "parked_at": act.get("parked_at"), "wakes_at": act.get("wakes_at"),',
     '                "parked_at": None, "wakes_at": None,'),

    ("a wedged job goes back to producing no item on the feed every channel reads", APP,
     '        elif j.get("wedged"):', '        elif False:'),

    ("the generic impediment branch shadows the wedged one", APP,
     '        elif j.get("wedged"):\n', ''),
]
MUTATIONS += [(name, path, old, new, WAIT) for name, path, old, new in SECOND]

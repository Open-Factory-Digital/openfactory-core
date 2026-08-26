"""#146: the tech-lead and the panel stop disagreeing about the same job.

The first cuts restore the divergence — the narrator deciding for itself, the field never
travelling, the rule inverted. The rest go the other way, and they are the ones that matter most
here: this change makes the tech-lead QUIETER, and a change that makes an alarm quieter fails by
silencing something real. A park past its deadline, a park that never had one, and a job younger
than the patience threshold must all behave exactly as before.

The voice and the dampening are guarded too. They are what a client reads.
"""

TEST = "tests/test_the_techlead_does_not_cry_wolf.py"
WATCH = "openfactory/techlead/watch.py"
LADDER = "openfactory/floor/ladder.py"
ACT = "openfactory/runtime/temporal/activities.py"
EXISTING = "tests/test_techlead_watch.py"

MUTATIONS = [
    # ── the divergence, restored ────────────────────────────────────────────────────────────────
    ("the tech-lead decides for itself again, and cries wolf on a self-clearing wait", WATCH,
     "        if not wait_is_over(job.wakes_at or None, job.kind, when):\n            continue\n",
     ""),

    ("the field never travels, so the rule is asked about nothing", ACT,
     '                             wakes_at=str(state.get("wakes_at") or "")))',
     '                             wakes_at=""))'),

    ("the park forgets it can carry a deadline at all", WATCH,
     "    wakes_at: str = \"\"", "    _unused_wakes_at: str = \"\""),

    ("the shared rule is inverted — a wait that is over goes quiet", LADDER,
     "        return (now - wake).total_seconds() > OVERDUE_S",
     "        return (now - wake).total_seconds() < OVERDUE_S"),

    ("the panel stops asking the shared rule, so the two drift apart again", LADDER,
     "    return wait_is_over(act.get(\"wakes_at\"), str(act.get(\"kind\") or \"\"), now)",
     "    wake = _parse(act.get(\"wakes_at\"))\n"
     "    return wake is not None and (now - wake).total_seconds() > OVERDUE_S"),

    # ── the other direction: a quieter alarm must not silence anything real ─────────────────────
    ("a park PAST its own deadline goes unannounced", WATCH,
     "        if not wait_is_over(job.wakes_at or None, job.kind, when):",
     "        if job.wakes_at:"),

    ("a park with NO deadline is treated as self-clearing and never announced", LADDER,
     "    return wakes_at is None and kind != \"rate_limit\"", "    return False"),

    ("a rate-limit park with no deadline becomes a person's problem immediately", LADDER,
     "    return wakes_at is None and kind != \"rate_limit\"", "    return wakes_at is None"),

    ("the grace after the deadline disappears, so a wait is late the instant it is due", LADDER,
     "OVERDUE_S = 600.0", "OVERDUE_S = 0.0"),

    # ── the voice and the dampening, which are what a client reads ──────────────────────────────
    ("a finding stops saying what happens next", WATCH,
     '                action=remedy.say or voice.say(voice.OUTCOME, "still-holding", language)))',
     '                action=""))'),

    ("the project's language is ignored and everybody gets English", WATCH,
     '            detail=voice.say(voice.FINDING, "wedged.detail", language, hours=hours),',
     '            detail=voice.say(voice.FINDING, "wedged.detail", "en", hours=hours),'),

    ("the dampening is removed and the tech-lead restates itself every round", WATCH,
     "REPEAT_AFTER = {STUCK: 6.0, IDLE: 60.0, RECURRING: 2.0, WAITING: 12.0}",
     "REPEAT_AFTER = {STUCK: 0.0, IDLE: 0.0, RECURRING: 0.0, WAITING: 0.0}"),

    # ── the patience and the gate rule, guarded by the file that already owned them ─────────────
    ("a park younger than the patience threshold is announced", WATCH,
     "        if job.hours < STUCK_PARK_HOURS:\n            continue\n", "", EXISTING),

    ("an armed auto-merge is chased after eight hours like a person", WATCH,
     "        if job.hours < (LONG_RUNNING_HOURS if job.gate == \"ci\" else GATE_WAIT_HOURS):\n"
     "            continue\n", ""),
]

"""#339: a run the engine closed asks nobody — not the inbox, not the floor, not the tech-lead."""

TEST = "tests/test_a_terminated_run_stops_asking_once_a_later_run_ended_it.py"
APP = "openfactory/api/app.py"
LADDER = "openfactory/floor/ladder.py"
VIEW = "openfactory/runtime/temporal/view.py"
CONV = "openfactory/techlead/conversation.py"

#: The state test the inbox made before #339, spelled out so a cut can put it back.
_BY_STATE = ('str(job.get("state")) in {"failed", "needs_refinement", "on_hold", "blocked", '
             '"paused", "awaiting_prod_approval", "awaiting_your_merge"}')

MUTATIONS = [
    # ── the inbox asks the engine's answer ──────────────────────────────────────────────────────
    ("the inbox lists every row again, whatever the engine said about it", APP,
     "        if not waits_on_a_person(j):\n            continue\n", ""),

    # ── the one predicate ───────────────────────────────────────────────────────────────────────
    ("the predicate re-derives from the state, as the inbox did", LADDER,
     '    return job.get("attention") is True or job.get("wedged") is True',
     f'    return job.get("wedged") is True or {_BY_STATE}'),

    ("the predicate forgets `wedged`, and the stuck run's `stop` vanishes", LADDER,
     '    return job.get("attention") is True or job.get("wedged") is True',
     '    return job.get("attention") is True'),

    ("the predicate forgets `attention`, and the live park vanishes", LADDER,
     '    return job.get("attention") is True or job.get("wedged") is True',
     '    return job.get("wedged") is True'),

    ("the floor's own road re-derives from the state, and parts from the inbox's", LADDER,
     "                 if waits_on_a_person(j)\n",
     f"                 if {_BY_STATE.replace('job.', 'j.')}\n"),

    # ── the engine answers `live` once ──────────────────────────────────────────────────────────
    ("the engine's row forgets `live`, so a closed run is flagged as needing a person", VIEW,
     '        row["attention"] = live and row["state"] in ATTENTION_STATES',
     '        row["attention"] = row["state"] in ATTENTION_STATES'),

    # ── the tech-lead says the same ─────────────────────────────────────────────────────────────
    ("the tech-lead tells somebody to skip a closed run again", CONV,
     '        if ticket == "closed" and j.get("attention") is True:',
     '        if ticket == "closed" and parked(j):'),

    ("…and the reverse: a live park on a closed ticket is no longer orphaned", CONV,
     '        if ticket == "closed" and j.get("attention") is True:',
     "        if False:"),
]

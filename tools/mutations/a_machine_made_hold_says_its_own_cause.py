"""Proven by breaking it — a machine-made hold says its own cause, instead of being re-read.

#184's merge watch parks on a check it has already typed and writes the check's NAME and the
vendor's remedy into the note; `techlead/classify.py` decided who acts by matching that prose. A
blocking check a team called "rate-limit tests" was read as throttling, and the real workflow spent
FOUR agent passes instead of one, announcing three self-healing naps at a required review
(measured 2026-09-19). The cause is data now — `RunResult.hold_cause` — and prose is what a hold
with nothing else to say is still read by.

THREE CLAIMS:

  1. **A declaration wins over prose, and only a real one**: a cause outside the taxonomy, or a
     test double's, is not a declaration and the rules still run.
  2. **Each of #184's paths says what it knows**: the repair gate's `ASK` is a gate, the spent
     repair passes are the change's problem, and the unreadable forge declares nothing.
  3. **It reaches the two readers that act on it**: the workflow (which naps and re-runs the agent
     on a `transient`) and the hourly round (which presses resume) — the workflow's behind
     `workflow.patched`, so a job parked on the prose reading replays on it.

The guard is `tests/test_a_machine_made_hold_says_its_own_cause.py`.
"""

TEST = "tests/test_a_machine_made_hold_says_its_own_cause.py"

CLASSIFY = "openfactory/techlead/classify.py"
REPAIRABLE = "openfactory/runtime/repairable.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
WATCH = "openfactory/techlead/watch.py"
ACTIVITIES = "openfactory/runtime/temporal/activities.py"

MUTATIONS = [
    # ── claim 1: a declaration, and only a real one ───────────────────────────────────────────
    ("THE DEFECT: the note's prose decides again, whatever the hold declared", CLASSIFY,
     '    declared = cause if isinstance(cause, str) and cause in _DECLARED else ""\n',
     '    declared = ""\n'),

    ("any word a caller passes becomes a cause — a mock's attribute included", CLASSIFY,
     '    declared = cause if isinstance(cause, str) and cause in _DECLARED else ""\n',
     "    declared = cause if cause else \"\"\n"),

    ("a string that is not a cause still short-circuits the rules", CLASSIFY,
     '    declared = cause if isinstance(cause, str) and cause in _DECLARED else ""\n',
     '    declared = cause if isinstance(cause, str) and cause else ""\n'),

    ("a gate is retried like anything else the factory waits out", CLASSIFY,
     "    if cause in (CODE, ENVIRONMENT, UNKNOWN, GATE):\n",
     "    if cause in (CODE, ENVIRONMENT, UNKNOWN):\n"),

    ("a declared hold loses the phrase its sentence is built from", CLASSIFY,
     "        return Verdict(cause=declared, stage=stage, detail=_DECLARED[declared],\n",
     '        return Verdict(cause=declared, stage=stage, detail="",\n'),

    ("the note the remedy reads for an exhausted attempt is dropped on a declared hold",
     CLASSIFY,
     "        return Verdict(cause=declared, stage=stage, detail=_DECLARED[declared],\n"
     "                       retry_after=retry_after, detail_source=text)\n",
     "        return Verdict(cause=declared, stage=stage, detail=_DECLARED[declared],\n"
     '                       retry_after=retry_after, detail_source="")\n'),

    # ── claim 2: what each path declares ──────────────────────────────────────────────────────
    ("the repair gate's hold declares nothing, as it did before", REPAIRABLE,
     "        note, hold_cause = decision.note, GATE\n",
     '        note, hold_cause = decision.note, ""\n'),

    ("a forge nobody could read is declared a gate — a guess made where it is caught",
     REPAIRABLE,
     '            f"was launched on a failure nobody saw — resume to read them again"), ""\n',
     '            f"was launched on a failure nobody saw — resume to read them again"), GATE\n'),

    ("the hold is built without the declaration it just made", REPAIRABLE,
     "                     hold_cause=hold_cause), \"\"\n",
     '                     hold_cause=""), ""\n'),

    ("the spent repair passes go back to being a mystery", WORKFLOW,
     "                        hold_cause=CAUSE_CODE,\n",
     '                        hold_cause="",\n'),

    # ── claim 3: it reaches the readers that act ──────────────────────────────────────────────
    ("the workflow reads the note and ignores what the hold said", WORKFLOW,
     '                                       cause=(getattr(parked, "hold_cause", "") or "")\n'
     '                                       if workflow.patched("a-hold-says-its-own-cause")'
     ' else "")\n',
     '                                       cause="")\n'),

    ("the declaration is not behind the marker, so a job parked on the prose reading "
     "replays a sequence it never recorded", WORKFLOW,
     '                                       cause=(getattr(parked, "hold_cause", "") or "")\n'
     '                                       if workflow.patched("a-hold-says-its-own-cause")'
     ' else "")\n',
     '                                       cause=(getattr(parked, "hold_cause", "") or ""))\n'),

    ("the message a person gets is built from the prose again", WORKFLOW,
     '                        cause=(getattr(parked, "hold_cause", "") or "")\n'
     '                        if workflow.patched("a-hold-says-its-own-cause") else "")\n',
     '                        cause="")\n'),

    ("the park payload drops the cause, so nothing downstream can read it", WORKFLOW,
     '                        "cause": str(getattr(result, "hold_cause", "") or ""),\n',
     '                        "cause": "",\n'),

    ("the hourly round goes back to reading the note", WATCH,
     "        verdict = classify(job.note, cause=job.cause)\n",
     "        verdict = classify(job.note)\n"),

    ("the round's floor state drops the declaration the park carried", ACTIVITIES,
     '                             cause=str(state.get("cause") or ""),\n',
     '                             cause="",\n'),
]

"""#133: the idle floor card must redraw when the answer it is built from arrives.

The floor card is keyed so it is NOT re-rendered on every engine frame — re-rendering would wipe
the live log feed of a running job. An idle floor has no jobs, so its key was `""` for ever, and
the card kept whatever sentence it was first painted with. The pilot enabled his project, the
server returned `pickup_enabled: true`, and the screen went on saying it could not read the pickup.

Each cut below restores that: the key stops moving with one of the inputs the idle copy is made of.
The last one goes the other way — it proves the guard still defends the ORIGINAL reason the key
exists, so a fix here cannot pay for itself by re-rendering a running card on every frame.

SUPERSEDED BY `141_the_floor_has_one_answer.py` (2026-08-19). The five separate status
computations these cuts attacked were replaced by one `floorState(scope, snap)` ladder, so
the anchors below no longer match — the runner refuses the plan rather than passing
quietly, which is the intended failure. Kept as the point-in-time proof it was: every
claim it made is now made against the ladder, and executed rather than read.
"""

TEST = "tests/test_a_disabled_project_does_not_look_armed.py"
PANEL = "openfactory/api/panel.html"

_KEY = ("    const key=active.length\n"
        "      ? active.map(j=>j.project+\"#\"+j.issue).join(\",\")\n"
        "      : `idle|${window._pickup}|${ik.on}|${ik.known}|${ik.note||\"\"}`;")

MUTATIONS = [
    ("the idle key goes back to the job set — it never moves, so it never redraws", PANEL,
     _KEY, '    const key=active.map(j=>j.project+"#"+j.issue).join(",");'),

    ("the key stops moving when this project's pickup arrives", PANEL,
     "      : `idle|${window._pickup}|${ik.on}|${ik.known}|${ik.note||\"\"}`;",
     "      : `idle|${ik.on}|${ik.known}|${ik.note||\"\"}`;"),

    ("the key stops moving when the schedule is paused or resumed", PANEL,
     "      : `idle|${window._pickup}|${ik.on}|${ik.known}|${ik.note||\"\"}`;",
     "      : `idle|${window._pickup}|${ik.known}|${ik.note||\"\"}`;"),

    ("the key stops moving when the schedule becomes readable", PANEL,
     "      : `idle|${window._pickup}|${ik.on}|${ik.known}|${ik.note||\"\"}`;",
     "      : `idle|${window._pickup}|${ik.on}|${ik.note||\"\"}`;"),

    ("a RUNNING floor re-renders on every frame — the live feed dies to fix the idle one", PANEL,
     _KEY,
     "    const key=`${active.length}|${window._pickup}|${ik.on}|${ik.known}`;"),
]

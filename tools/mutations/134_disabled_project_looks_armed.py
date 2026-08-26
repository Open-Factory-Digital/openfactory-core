"""#134: a disabled project must not look armed.

Each cut restores a way for the screen to promise work the platform will not do.

SUPERSEDED BY `141_the_floor_has_one_answer.py` (2026-08-19). The five separate status
computations these cuts attacked were replaced by one `floorState(scope, snap)` ladder, so
the anchors below no longer match — the runner refuses the plan rather than passing
quietly, which is the intended failure. Kept as the point-in-time proof it was: every
claim it made is now made against the ladder, and executed rather than read.
"""

TEST = "tests/test_a_disabled_project_does_not_look_armed.py"
PANEL = "openfactory/api/panel.html"
APP = "openfactory/api/app.py"

MUTATIONS = [
    ("the cockpit stops carrying this project's pickup", APP,
     '        "pickup_enabled": pickup,\n', ""),

    ("an unreadable registry reports the project as armed", APP,
     "    pickup: bool | None = None", "    pickup: bool | None = True"),

    ("the schedule is consulted before the project's own flag", PANEL,
     "        const idle = pk===false\n",
     "        const idle = ik.known===false ? `x`\n          : pk===false\n"),

    ("a disabled project goes back to being promised work", PANEL,
     '        const idle = pk===false\n          ? `<b style="color:var(--err)">Pickup for this '
     'project is OFF</b>',
     '        const idle = false\n          ? `<b style="color:var(--err)">Pickup for this '
     'project is OFF</b>'),

    ("an unknown pickup is treated as armed", PANEL,
     "          : pk===null\n", "          : false\n"),

    ("the glyph stops agreeing with the sentence", PANEL,
     "        const held=(pk===false||ik.on===false);", "        const held=(ik.on===false);"),

    ("the floor waits a whole tick to tell the truth", PANEL,
     "  refreshProject();   // the floor card is drawn from this; without it the truth waits 20s\n",
     ""),

    ("a failed cockpit read leaves the previous project's flag", PANEL,
     "  window._pickup=null;\n  let f; try{f=await api", "  let f; try{f=await api"),

    ("the socket pill goes back to the factory's word", PANEL,
     'const look={live:["ok","live"],polling:["warn","reconnecting"],off:["","…"]}',
     'const look={live:["ok","live"],polling:["warn","polling"],off:["","…"]}'),
]

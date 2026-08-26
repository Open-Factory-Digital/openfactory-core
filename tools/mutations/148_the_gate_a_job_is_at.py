"""#148: the floor names the gate a job is actually at, and an open PR has not shipped.

Both found by the pilot looking at his own screen during the first real run through the new panel.
The cuts restore each, then go the other way: a machine-owned wait must not become a person's
problem, and a merged job must still read as done.
"""

TEST = "tests/test_the_floor_is_a_platform_capability.py"
LADDER = "openfactory/floor/ladder.py"
PANEL = "openfactory/api/panel.html"
HOSTILE = "tests/test_a_hostile_value_stays_data.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"

MUTATIONS = [
    # ── the gate, named ─────────────────────────────────────────────────────────────────────────
    ("every gate flattens to `impediment` and the sentence falls through to the park's note",
     LADDER, '                  "kind": _need_kind(j),',
     '                  "kind": "wedged" if j.get("wedged") else "impediment",'),

    ("a pull request gate stops being recognised from the job's own state", LADDER,
     '    if state == "awaiting_your_merge" or (act.get("kind") == "merge_wait" '
     'and not act.get("auto")):\n        return "merge"',
     '    if False:\n        return "merge"'),

    ("a production approval loses its own sentence", LADDER,
     '    if state == "awaiting_prod_approval":\n        return "approval"',
     '    if False:\n        return "approval"'),

    ("a decision loses its own sentence", LADDER,
     '    if act.get("decision"):\n        return "decision"',
     '    if False:\n        return "decision"'),

    # ── the other way: a machine-owned wait is not a person's problem ────────────────────────────
    ("an armed auto-merge is announced as overdue — a build asked to explain itself", LADDER,
     '    return wakes_at is None and kind not in SELF_CLEARING',
     '    return wakes_at is None and kind != "rate_limit"'),

    ("…and the reverse: an impediment with no deadline stops being anybody's problem", LADDER,
     'SELF_CLEARING = frozenset({"rate_limit", "merge_wait"})',
     'SELF_CLEARING = frozenset({"rate_limit", "merge_wait", "impediment"})'),

    # ── an open PR has not shipped ──────────────────────────────────────────────────────────────
    ("`pr_open` goes back into the terminal-good set", PANEL,
     'const SHIPPED=new Set(["merged","done"]);',
     'const SHIPPED=new Set(["merged","done","pr_open"]);', HOSTILE),

    ("the badge painter keeps its own copy of the list again", PANEL,
     'function domBadge(s){if(SHIPPED_BADGE.has(s))return"b-ok";',
     'function domBadge(s){if(["merged","done","pr_open"].includes(s))return"b-ok";', HOSTILE),

    ("an open PR is painted green, the colour this page uses for done", PANEL,
     '  if(s=="pr_open")return"b-run";', "", HOSTILE),

    ("…and the reverse: a merged job stops reading as done", PANEL,
     'const SHIPPED=new Set(["merged","done"]);', 'const SHIPPED=new Set(["done"]);', HOSTILE),

    # ── the card beneath the header, blaming the other thing ────────────────────────────────────
    ("the engine tells the human path the machine's sentence — the original defect", WORKFLOW,
     '    return "waiting for CI / the merge" if auto else "waiting for your review and merge"',
     '    return "waiting for CI / the merge"'),

    ("…and the reverse: an armed auto-merge is blamed on the reader", WORKFLOW,
     '    return "waiting for CI / the merge" if auto else "waiting for your review and merge"',
     '    return "waiting for your review and merge"'),

    ("the loop hand-writes the sentence again instead of asking the one definition", WORKFLOW,
     '                                        "note": merge_wait_note(bool(result.auto_merge))}',
     '                                        "note": "waiting for CI / the merge"}'),

    ("the blame classifier goes blind, so every sentence agrees with every other", TEST,
     '    machine = bool(words & {"ci", "build", "checks", "pipeline"})',
     '    machine = bool(words & {"pipeline"})'),
]

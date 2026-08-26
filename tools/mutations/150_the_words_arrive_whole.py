"""#150/#151: the human's words arrive whole, and a pass in flight is not a gate.

Both measured on the pilot within minutes of each other, on the same job. The cuts restore each
defect and then go the other way — a platform that never asks anybody anything would satisfy half
of these guards without doing anything useful.
"""

TEST = "tests/test_a_pass_in_flight_is_not_a_gate.py"
PANEL = "openfactory/api/panel.html"
HOSTILE = "tests/test_a_hostile_value_stays_data.py"
CATALOG = "openfactory/actions/catalog.py"
LAYER = "tests/test_the_action_layer.py"
WORKFLOW = "openfactory/runtime/temporal/workflow.py"
VIEW = "openfactory/runtime/temporal/view.py"
LADDER = "openfactory/floor/ladder.py"

MUTATIONS = [
    # ── #150: a paragraph is not collected in a one-line box ────────────────────────────────────
    ("the instruction goes back to a single-line prompt() — the original defect", PANEL,
     '  if(answer=="adjust"&&!instruction.trim()){openAdjust(project,issue);return}',
     '  if(answer=="adjust"){instruction=prompt("What needs changing?")||"";'
     'if(!instruction.trim())return}', HOSTILE),

    ("the box becomes a one-line input again", PANEL,
     '    <textarea id="aj_text" rows="9"', '    <input id="aj_text"', HOSTILE),

    ("the count disappears, so a silent truncation is invisible again", PANEL,
     '    $("#aj_count").textContent=n+" character"+(n==1?"":"s")'
     '+" — all of it reaches the agent";',
     '    $("#aj_count").textContent="";', HOSTILE),

    ("the count stops reading the box and shows a constant", PANEL,
     '    const n=t.value.length;', '    const n=0;', HOSTILE),

    ("a blank box is sent, spending a pass on nothing", PANEL,
     '  if(!t.trim()){toast("Nothing to send","say what needs changing","err");return}',
     '  if(false){return}', HOSTILE),

    ("the page hard-codes the ceiling the action layer already enforces", PANEL,
     '    <div class="muted" id="aj_count" style="margin-top:6px">0 characters</div>',
     '    <div class="muted" id="aj_count" style="margin-top:6px">0 / 2000 characters</div>',
     HOSTILE),

    # ── #150, platform side: the confirmation says how much it received ─────────────────────────
    ("the echo stops saying how much arrived — a fragment reads like a short instruction",
     CATALOG,
     '        f"#{issue}: sent back for one pass — {by} asked for ({len(text)} characters): "',
     '        f"#{issue}: sent back for one pass — {by} asked for: "', LAYER),

    ("…and the reverse: a truncated echo stops admitting it is one", CATALOG,
     """{'…' if len(text) > 120 else ''}""", "", LAYER),

    # ── #151: a pass in flight is not a gate ────────────────────────────────────────────────────
    ("the merge wait stays a gate through the whole repair pass — the original defect", WORKFLOW,
     '        self._merge_wait = {"pr_url": pr_url, "auto": False, "working": True,',
     '        self._merge_wait = {"pr_url": pr_url, "auto": False,'),

    ("the view stops reading the flag, so the gate reopens over a moving branch", VIEW,
     '                if mw.get("working"):\n'
     '                    return JobState.REPAIRING.value, {"kind": MERGE_WAIT, **mw}, True',
     '                if False:\n'
     '                    return JobState.REPAIRING.value, {"kind": MERGE_WAIT, **mw}, True'),

    ("…and the reverse: EVERY merge wait becomes a pass in flight, so nobody is ever asked", VIEW,
     '                if mw.get("working"):', '                if True:'),

    ("a job carrying any action payload is excluded from Working again — the floor goes blank",
     LADDER,
     '               and not _is_asked_of_somebody(j.get("action") or {})]',
     '               and not j.get("action")]'),

    ("…and the reverse: a genuine park counts as Working, so a stopped floor reads busy", LADDER,
     '    return not (act.get("kind") == "merge_wait" and act.get("working"))',
     '    return False'),
]

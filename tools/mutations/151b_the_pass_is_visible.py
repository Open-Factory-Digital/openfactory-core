"""#151 (the half left standing): the panel says a pass is running, and the seam
refuses an answer while it does."""

TEST = "tests/test_the_panel_says_a_pass_is_running.py"
VIEW = "openfactory/runtime/temporal/view.py"
PANEL = "openfactory/api/panel.html"
YES = "tests/test_a_yes_is_an_answer.py"
ASSENT = "openfactory/language/assent.py"

MUTATIONS = [
    ("an answer is accepted over a branch being rewritten", VIEW,
     '    if gate.get("working"):', "    if False:"),

    ("…and the reverse: every gate is refused, so no PR can ever be answered", VIEW,
     '    if gate.get("working"):', "    if True:"),

    ("the busy refusal is the DEAF one — the operator is sent to the forge by hand", VIEW,
     '        return ("a repair pass is rewriting this pull request right now — the answer you '
     'give "\n                "would land on a diff nobody has read. It will ask again when the '
     'pass ends, and "\n                "the panel shows what it is doing meanwhile")',
     '        return ("this job started before the merge gate existed, so no answer can reach it '
     '— "\n                "merge or close the PR on the forge itself")'),

    ("the machine card reads `auto` before `working`", PANEL,
     '  if(mw&&mnow){mnow.innerHTML=mw.action.working\n'
     '    ?"✏️ a repair pass is rewriting this pull request — it will ask again when the pass '
     'ends"\n    :mw.action.auto',
     '  if(mw&&mnow){mnow.innerHTML=mw.action.auto'),

    ("the floor control stops naming the pass", PANEL,
     '      fc.innerHTML=(a.working\n'
     '        ?`<span class="badge b-run" style="margin-right:8px">✏️ #${esc(parked.issue)} '
     'repair pass running${on}</span>`\n        :a.auto',
     "      fc.innerHTML=(a.auto"),

    ("the three answers are painted while the pass runs", PANEL,
     '        (a.auto||a.working?"":', '        (a.auto?"":'),

    # ── #157: the accent is the whole discipline ─────────────────────────────────────────────────
    ("`tá` leaves the table again — the pilot's own yes stops being heard", ASSENT,
     '    "pt-br": ("sim", "tá", "isso"', '    "pt-br": ("sim", "isso"', YES),

    # NOT "drop `ta` from FILLER" — dropping it from one table does not put it in the other, so
    # the cut changed no answer. The claim that bites is the word ENTERING the assent table.
    ("…and the reverse: bare `ta` enters it, so a British thank-you presses merge", ASSENT,
     '    "pt-br": ("sim", "tá", "isso"', '    "pt-br": ("sim", "tá", "ta", "isso"', YES),
]

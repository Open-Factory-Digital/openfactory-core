"""An open question is an offer, not a toll — the cuts that put the first live bundle's three
readings back (2026-09-06).

ROW 1 IS THE PROMPT STOPPING AT THE FOLDER'S EDGE AGAIN.
ROWS 2-4 ARE THE GATE: a question holding regardless of grade; the module's questions never
reaching the files under it; a question graded high holding nothing.
ROWS 5-7 ARE THE PRESENTATION: "before merging" in the body; "YOUR STEP" under a run that
proposed nothing; the questions document without its "nothing waits" line.
"""

TEST = "tests/test_an_open_question_is_an_offer_not_a_toll.py"

MUTATIONS = [
    ("the prompt says THIS MODULE only again — the agent stops where a person opens the next file",
     "openfactory/onboarding/concepts.py",
     '        "3. FOLLOW THE REFERENCES. This module is where you start, not where you stop. '
     'When a",\n',
     '        "3. Describe THIS MODULE only; a rule decided elsewhere is a caveat. When a",\n'),

    ("an open question holds the file whatever its grade — the 2026-09-06 policy",
     "openfactory/knowledge/gate.py",
     '    if gap.kind == OPEN_QUESTION:\n        return severity == "high"\n',
     '    if gap.kind == OPEN_QUESTION:\n        return True\n'),

    ("the module's questions never reach the files under it — exact match again",
     "openfactory/knowledge/gate.py",
     '    prefixes = {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}\n',
     '    prefixes = {path}\n'),

    ("a question graded high holds nothing",
     "openfactory/knowledge/gate.py",
     '        return severity == "high"\n    return True\n',
     '        return False\n    return True\n'),

    ("the body says 'before merging' again",
     "openfactory/onboarding/onboard.py",
     '        lines.append("**What the factory could not derive from the code** — nothing waits '
     'on "\n',
     '        lines.append("**Only your team can answer these — before merging:** nothing waits '
     'on "\n'),

    ("the closing says YOUR STEP under a run that proposed nothing",
     "openfactory/cli.py",
     '    if not proposed:\n        return ["",\n',
     '    if False:\n        return ["",\n'),

    ("the questions document drops its 'nothing waits' line",
     "openfactory/onboarding/context.py",
     '''                 + [f"> {w['questions_note']}", ""])\n''',
     '''                 + [])\n'''),
]

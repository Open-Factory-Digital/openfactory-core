"""#150 slice 4 and #139, proven by breaking it — what counts as a criterion is decided once.

THREE CLAIMS:

  1. **One scenario is one criterion.** A `Scenario:` under the criteria heading parsed as none, and
     the same scenario written one `- ` per step parsed as three (measured on `506317a`, rows B and
     C of the issue). Gherkin is read, never required; a wrapped bullet keeps its tail (#139).
  2. **The queue, triage and the gate have one opinion.** The queue searched the body for `given `
     while the gate parsed it, so it proposed a card the gate refused — and the refusal told the
     author to rename `## Acceptance criteria` to itself.
  3. **A multi-line criterion is one item wherever it is rendered** — the agent's brief, both
     reviewer prompts and the sizer — and reads back as one.

The guard is `tests/test_a_scenario_is_one_criterion.py`, plus `tests/test_card_maintenance.py` for
the refine that must not write a second criteria section the parser would never read.
"""

TEST = "tests/test_a_scenario_is_one_criterion.py"

PARSE = "openfactory/adapters/tracker/parse.py"
TRIAGE = "openfactory/product/triage.py"
MACHINE = "openfactory/orchestrator/machine.py"
TICKET = "openfactory/contracts/ticket.py"
BRIEF = "openfactory/adapters/agent/base.py"
HARNESS_REVIEW = "openfactory/adapters/reviewer/harness.py"
CLAUDE_REVIEW = "openfactory/adapters/reviewer/claude_code.py"
SIZER = "openfactory/adapters/agent/techlead.py"
MODULE = "openfactory/product/module.py"

MUTATIONS = [
    # ── 1. one scenario is one criterion ───────────────────────────────────────────────────────
    ("THE DEFECT ITSELF: criteria are read one `- ` line at a time again, so a scenario on plain "
     "lines is no criterion and a bulleted one is three", PARSE,
     '            AcceptanceCriterion(text=t) for t in _criteria_items(s.get("acceptance '
     'criteria", ""))',
     '            AcceptanceCriterion(text=t) for t in _list_items(s.get("acceptance '
     'criteria", ""))'),

    ("a `Given` after a `Then` continues the scenario, so two headerless scenarios become one",
     PARSE,
     '        elif kind == "given" and not (in_scenario and state in ("scenario", "given")):',
     '        elif kind == "given" and not in_scenario:'),

    ("a step in the other style joins the scenario, so a plain `- When …` criterion after it "
     "disappears into the scenario", PARSE,
     "                       and (stepped is None or kind == \"table\" or bulleted == stepped))",
     "                       and True)"),

    ("a `Scenario:` sentence with nothing under it counts as a criterion, defanging the gate",
     PARSE,
     "            counted.append(bulleted)\n",
     "            counted.append(True)\n"),

    ("a blank line ends a scenario, so an outline loses its Examples table", PARSE,
     '            state = "" if state == "bullet" else state   # a scenario survives a blank line',
     '            state = ""'),

    ("an Examples table is prose, glued onto the last step as one run-on line", PARSE,
     '    if label in _EXAMPLES or bare.startswith("|"):',
     "    if False:"),

    ("Portuguese steps are not steps: `Então` and `E` fall out of the scenario", PARSE,
     '_STEP = ("When", "Then", "And", "But", "Quando", "Então", "Entao", "E", "Mas")',
     '_STEP = ("When", "Then", "And", "But", "Quando", "Entao", "Mas")'),

    ("`Cenário:` is not a scenario line, so a Portuguese scenario loses its name", PARSE,
     '             "cenario", "esquema do cenario", "delineacao do cenario", "exemplo")',
     '             "esquema do cenario", "delineacao do cenario", "exemplo")'),

    ("#139 ITSELF, in the criteria: a wrapped criterion keeps its first line only", PARSE,
     '        elif kind == "prose" and line[:1].isspace() and state:',
     "        elif False:"),

    ("#139 in the scope lists: a wrapped out-of-scope item keeps its first line only", PARSE,
     "        elif open_item and stripped and line[:1].isspace():",
     "        elif False:"),

    ("a blank line no longer ends a wrapped bullet, so the next paragraph is glued onto it", PARSE,
     "        else:\n            open_item = False\n    return items",
     "        elif stripped:\n            open_item = False\n    return items"),

    # ── 2. one opinion ─────────────────────────────────────────────────────────────────────────
    ("THE DRIFT BACK: triage and the queue search the body for substrings again, and call ready "
     "what the gate refuses", TRIAGE,
     '    return bool(criteria(t.body or ""))',
     '    return any(m in (t.body or "").lower() for m in ("- [ ]", "acceptance criteria", '
     '"definition of done", "given ", "dado que"))'),

    ("the refusal assumes no criteria means no criteria heading, and tells the author to rename "
     "the heading to its own name", MACHINE,
     "    if heading is not None:\n        raise SpecValidationError(",
     "    if False:\n        raise SpecValidationError("),

    ("the criteria heading is never found, so the refusal and refine both lose it", PARSE,
     '                 if _CANONICAL.get(norm) == "acceptance criteria"), None)',
     "                 if False), None)"),

    ("refine appends a second criteria section below one the parser reads first, and never reads "
     "it", MODULE,
     '        if criteria_heading(ticket.body or "") is not None:',
     "        if False:",
     "tests/test_card_maintenance.py"),

    # ── 3. one item wherever it is rendered ────────────────────────────────────────────────────
    ("a multi-line criterion is written as `- text`, so every line after the first falls out of "
     "its bullet", TICKET,
     '        return "\\n".join([f"- {first}", *(f"  {line}" for line in rest)])',
     '        return f"- {self.text}"'),

    ("the agent's brief renders criteria its own way again", BRIEF,
     "            nonce, *(c.bullet() for c in t.acceptance_criteria))",
     '            nonce, *(f"- {c}" for c in criteria))'),

    ("the harness-neutral reviewer renders criteria its own way again", HARNESS_REVIEW,
     '    crits = "\\n".join(c.bullet() for c in t.acceptance_criteria) or "(none stated)"',
     '    crits = "\\n".join(f"- {c.text}" for c in t.acceptance_criteria) or "(none stated)"'),

    ("the Claude Code reviewer renders criteria its own way again", CLAUDE_REVIEW,
     '        crits = "\\n".join(c.bullet() for c in t.acceptance_criteria) or "(none stated)"',
     '        crits = "\\n".join(f"- {c.text}" for c in t.acceptance_criteria) or "(none stated)"'),

    ("the sizer renders criteria its own way again", SIZER,
     '        parts += ["", "## Acceptance criteria"] + [c.bullet() for c in '
     't.acceptance_criteria]',
     '        parts += ["", "## Acceptance criteria"] + [f"- {c.text}" for c in '
     't.acceptance_criteria]'),
]

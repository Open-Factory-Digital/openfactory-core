"""#172: a verb says what to put in it, and when to choose it, from ONE home.

Two families of reverse. The vocabulary must be shared without becoming uneditable per row; and the
prose must travel to all three readers — the prompt, the endpoint, the page — without any of them
being allowed to invent one.
"""

TEST = "tests/test_a_verb_says_what_to_put_in_it.py"
BASE = "openfactory/actions/base.py"
CATALOG = "openfactory/actions/catalog.py"
CONV = "openfactory/techlead/conversation.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
WEDGED = "tests/test_a_wedged_job_has_an_exit.py"

MUTATIONS = [
    # ── the hole the card was filed for ─────────────────────────────────────────────────────────
    ("`instruction` goes back to being a bare name on a required parameter", BASE,
     '    "instruction": "WHAT TO CHANGE, in one or two concrete sentences the coding pass will '
     'work "', '    "_instruction_removed": "WHAT TO CHANGE, in one or two concrete sentences the '
     'coding pass will work "'),

    ("the verb it may propose stops saying WHEN to pick it", CATALOG,
     '            choose_when="when the work is nearly right',
     '            choose_when="" and "when the work is nearly right'),

    # ── the resolution order ────────────────────────────────────────────────────────────────────
    ("a row's own word stops winning over the shared one", BASE,
     "        return self.params.get(param) or PARAMS.get(param, \"\")",
     '        return PARAMS.get(param, "")'),

    ("…and the reverse: the shared vocabulary is never consulted at all", BASE,
     "        return self.params.get(param) or PARAMS.get(param, \"\")",
     '        return self.params.get(param, "")'),

    ("an undescribed parameter VANISHES instead of coming back empty", BASE,
     "        return {p: self.prose_for(p) for p in self.parameters}",
     "        return {p: self.prose_for(p) for p in self.parameters if self.prose_for(p)}"),

    ("`described` covers only what is required, so an optional one is unlabelled", BASE,
     "        return {p: self.prose_for(p) for p in self.parameters}",
     "        return {p: self.prose_for(p) for p in self.required}"),

    # ── the prompt reads the row ────────────────────────────────────────────────────────────────
    ("the prompt stops naming what a verb NEEDS — `adjust` is offered blind again", CONV,
     '        for param in spec.required:\n'
     '            if param in ("project", "issue"):\n'
     "                continue\n"
     '            out.append(f"        ‣ needs {param} — {spec.prose_for(param)}\\n")',
     "        pass"),

    ("…and the reverse: the two it already knows are listed, inviting a restatement", CONV,
     '            if param in ("project", "issue"):\n                continue\n', ""),

    ("the parameter is named and never explained", CONV,
     '            out.append(f"        ‣ needs {param} — {spec.prose_for(param)}\\n")',
     '            out.append(f"        ‣ needs {param}\\n")'),

    ("the judgment falls back to the summary even when the row HAS one", CONV,
     '        out.append(f"    · {verb}: {spec.choose_when or spec.summary}\\n")',
     '        out.append(f"    · {verb}: {spec.summary}\\n")', WEDGED),

    # ── served, so nothing downstream invents one ───────────────────────────────────────────────
    ("the catalogue endpoint stops serving what each parameter is", APP,
     '         "params": s.described, "choose_when": s.choose_when or None,',
     '         "choose_when": s.choose_when or None,'),

    ("…and a row nobody proposes serves an empty string a front end prints under a heading", APP,
     '"choose_when": s.choose_when or None,', '"choose_when": s.choose_when,'),

    ("the staged proposal arrives with no labels — the panel is back to bare keys", APP,
     '        "labels": _labels_for(proposal[0]),\n', ""),

    ("a verb this deployment does not have RAISES instead of answering nothing", APP,
     "    return spec.described if spec else {}", "    return actions.CATALOG[action].described"),

    # ── the page paints it ──────────────────────────────────────────────────────────────────────
    ("the label is fetched and never painted", PANEL,
     '          +`${lbl[k]?`<div class="sub">${esc(lbl[k])}</div>`:""}</div>`).join("");',
     '          +`</div>`).join("");'),

    # ── one home ────────────────────────────────────────────────────────────────────────────────
    ("the private map beside the prompt comes back", CONV,
     "def _verb_block(verbs) -> str:",
     '_WHAT_IT_DOES = {"resume": "re-run it"}\n\n\ndef _verb_block(verbs) -> str:'),

    ("a row copies the shared word instead of using it — the first of forty drifts", CATALOG,
     '            name="skip",',
     '            name="skip",\n            params={"project": "the project\'s name in this '
     'deployment\'s registry, e.g. `podbeam`"},'),

    # NOT "weaken the guidance guard in the other file" — a mutation that edits a TEST to assert
    # less can never be caught by a test, so it measured nothing. What it was reaching for is
    # covered behaviourally: `test_the_prompt_reads_the_ROW` changes the catalogue and reads the
    # prompt back.
]

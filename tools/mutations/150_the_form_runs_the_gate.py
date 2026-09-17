"""#150 slice 3, proven by breaking it — the page writes a card the gate accepts, and says so first.

THREE CLAIMS:

  1. **The page and the job ask one gate.** `spec_verdict` is what `JobRunner._spec_validation`
     answers, and `card_check` runs it on a draft without writing anything. A page that judged a
     card itself would be the second rule that made the queue call ready what pickup refuses.
  2. **A card saved as pickup would refuse it is saved, and says so.** `card_create` and `card_edit`
     read the card back and carry the verdict, so the refusal arrives while the card can still be
     fixed rather than after somebody queued it. The button used to send a title and nothing else.
  3. **The form never loses what is being typed.** A board tick rebuilt the drawer; a form rebuilt
     under the person writing it lost their text.

The guards are `tests/test_the_board_is_a_page_on_the_panel.py` and, for the page's behaviour in a
browser, the end-to-end bed's `tests/test_the_form_runs_the_gate.py`.
"""

TEST = "tests/test_the_board_is_a_page_on_the_panel.py"

MACHINE = "openfactory/orchestrator/machine.py"
CATALOG = "openfactory/actions/catalog.py"
PARSE = "openfactory/adapters/tracker/parse.py"
PANEL = "openfactory/api/panel.html"

MUTATIONS = [
    # ── 1. one gate ────────────────────────────────────────────────────────────────────────────
    ("THE SECOND RULE: the page's verdict passes everything, whatever the job's gate says",
     MACHINE,
     "        _spec_gate(ticket)\n    except SpecValidationError as refused:",
     "        pass\n    except SpecValidationError as refused:"),

    ("the job stops asking the shared gate, and the page's verdict is no longer the job's", MACHINE,
     '        resolved from the diff (D-6). An optional LLM score is a later second stage."""\n'
     "        _spec_gate(ticket)",
     '        resolved from the diff (D-6). An optional LLM score is a later second stage."""\n'
     "        return None"),

    ("a check says every draft would be taken", CATALOG,
     "    verdict = spec_verdict(draft)\n",
     '    verdict = ""\n'),

    ("a check writes the card it was only asked to judge", CATALOG,
     "    verdict = spec_verdict(draft)\n",
     "    verdict = spec_verdict(draft)\n"
     "    _board_pair(project)[1].create_ticket(title=title or 'checked', body=body or '')\n"),

    ("the page is handed a draft read with the old one-line-per-bullet rule, so a scenario is not "
     "one row", PARSE,
     '        "criteria": _criteria_items(sections.get("acceptance criteria", "")),',
     '        "criteria": _list_items(sections.get("acceptance criteria", "")),'),

    # ── 2. saved, and says so ──────────────────────────────────────────────────────────────────
    ("a card saved as pickup would refuse it says nothing about it — the old button's silence",
     CATALOG,
     '        return f"{message}. As written, pickup would refuse it: {verdict}", '
     '{"refusal": verdict}',
     '        return message, {"refusal": verdict}'),

    ("the verdict is judged on nothing, so a refused card is reported as taken", CATALOG,
     "        return spec_verdict(tracker.get_ticket(ref))",
     '        return ""'),

    ("a correction no longer carries the verdict on the corrected card", CATALOG,
     "                project=proj.name, issue=str(issue), changed=\",\".join(changed), **gate)",
     "                project=proj.name, issue=str(issue), changed=\",\".join(changed))"),

    ("the new-card button goes back to asking for a title only", PANEL,
     '  _bd.form = _blank("new");\n  paintForm();\n  _bgate();',
     '  const title = prompt("What is the card called?");\n'
     '  if(!title) return;\n'
     '  await act("card_create", {project:_bd.project, title});'),

    ("the form asks nobody, so it never learns what pickup would say", PANEL,
     '    const r = await act("card_check", {project:_bd.project, title:f.title, body:_bbody()});',
     '    const r = {ok:true, message:"", data:{refusal:"", criteria:[]}};'),

    # ── 3. nothing typed is lost ───────────────────────────────────────────────────────────────
    ("a board tick rebuilds the drawer over the card being written", PANEL,
     "  if(_bd.dragging || _bd.form || (_bd.sig !== null && sig === _bd.sig)){",
     "  if(_bd.dragging || (_bd.sig !== null && sig === _bd.sig)){"),
]

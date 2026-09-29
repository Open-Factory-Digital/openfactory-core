"""A card the product role opens is drafted from the conversation, checked by a floor no rubric can
switch off, judged against the rubric with the verdict computed in code, and shown whole before the
yes (#383).

Run:  .venv/bin/python tools/mutate.py tools/mutations/383_a_card_is_drafted_and_judged_before_the_yes.py

Row 1 is the defect as it shipped: the message that asked for the card is accepted as its body.
Rows 2-6 each switch off one line of the floor. Rows 7-9 let the judge decide what the code must
compute, or accept a scoring that is not one. Rows 10-11 unbound the loop or spend the judge on a
draft the floor already refused. Rows 12-16 are the engine and the pen: another conversation reaching
the card, the confirmation showing the title alone, the yes writing something other than what was
shown, a card that failed twice being staged, and the pen slicing a title again. Rows 17-18 are the
product's own files: a template that would lose every card accepted, and a rubric that cannot be read
used anyway.
"""

TEST = "tests/test_a_card_is_drafted_and_judged_before_the_yes.py"

CARDS = "openfactory/product/cards.py"
ENGINE = "openfactory/product/engine.py"
CONFIRM = "openfactory/product/confirm.py"
MODULE = "openfactory/product/module.py"

MUTATIONS = [
    ("TODAY'S DEFECT: the request to open the card is accepted as the card's body", CARDS,
     "    elif description == _said(request) or len(description) < 20:",
     "    elif False:"),

    ("a title over the bound clears the floor", CARDS,
     "    elif len(draft.title) > TITLE_LIMIT:",
     "    elif False:"),

    ("a card with nothing that says when it is done clears the floor", CARDS,
     "    if not draft.done_when:",
     "    if False:"),

    ("a quote nobody said clears the floor", CARDS,
     '    if draft.source_quote and _said(draft.source_quote) not in _said(f"{conversation}\\n{request}"):',
     "    if False:"),

    ("the pickup gate's own verdict is not asked", CARDS,
     "    refused = spec_verdict(parse_ticket_body(id=\"draft\", title=draft.title, body=body, repo=\"\"))\n"
     "    if refused:",
     "    refused = spec_verdict(parse_ticket_body(id=\"draft\", title=draft.title, body=body, repo=\"\"))\n"
     "    if False:"),

    ("a draft with no description clears the floor", CARDS,
     "    if not description:\n        problems.append(\"the card has no description of the work\")",
     "    if False:\n        problems.append(\"the card has no description of the work\")"),

    ("a critical failure the judge named does not fail the card", CARDS,
     "    if critical:\n        because.append",
     "    if False:\n        because.append"),

    ("a criterion below the floor passes when the mean is high", CARDS,
     "    low = sorted(k for k, v in scores.items() if v < rubric.lowest)",
     "    low = []"),

    ("a missing or malformed score is skipped rather than refusing the scoring", CARDS,
     "        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):\n"
     "            return None",
     "        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):\n"
     "            continue"),

    ("the loop drafts a third time", CARDS,
     "ATTEMPTS = 2", "ATTEMPTS = 3"),

    ("a draft the floor refused is still sent to the judge", CARDS,
     "            feedback = problems\n            continue",
     "            feedback = problems"),

    ("the card is drafted without the conversation", ENGINE,
     "    ex.conversation = said\n    said = _with_elsewhere(",
     '    ex.conversation = ""\n    said = _with_elsewhere('),

    ("the confirmation shows the title alone", ENGINE,
     "    ask = ticket_confirmation(title=title, card=composed.card, unjudged=composed.unjudged,",
     '    ask = ticket_confirmation(title=title, card="", unjudged=composed.unjudged,'),

    ("the yes writes a card other than the one shown", CONFIRM,
     '        **({"card": entry["card"]} if entry.get("card") and _takes_card(module) else {}),',
     "        **{},"),

    ("a card that failed twice is staged anyway", ENGINE,
     "    if not composed.ok:\n        if composed.draft is None and not composed.ask:",
     "    if False:\n        if composed.draft is None and not composed.ask:"),

    ("the pen slices an over-long title again", MODULE,
     "        if len(name) > TITLE_LIMIT:",
     "        if False:"),

    ("a product's template that would lose every card is used", CARDS,
     "        problem = template_problem(text, kind)",
     '        problem = ""'),

    ("an unreadable product rubric is used instead of refused", CARDS,
     '            return Rubric.parse(own.read_text(), source=f"{OVERRIDE_DIR}/{RUBRIC_FILE}")\n'
     "        except Exception as exc:",
     '            return Rubric.parse(own.read_text(), source=f"{OVERRIDE_DIR}/{RUBRIC_FILE}")\n'
     "        except ZeroDivisionError as exc:"),

    ("the verdict is left to a log line a warnings-only worker never writes", CARDS,
     "    _record_verdict(project_name, attempt, rubric, said=said, floor=floor)\n",
     ""),

    ("the draft stands in the role's workspace again, with every checkout to explore", MODULE,
     "        draft = cards.as_json(cards.in_a_room(self.project, harness, cards.DRAFT_PHASE))",
     "        sandbox, ws = self._workspace()\n        role = self._role()\n"
     "        draft = lambda p: role.ask_json(sandbox=sandbox, workspace=ws, prompt=p, "
     "phase=cards.DRAFT_PHASE)"),

    ("the judge may ask the person for a name", CARDS,
     "f\"it, in the person's language. Never for a name, a label or wording. Otherwise \\\"\\\".\\n\\n\"",
     "f\"it, in the person's language. Otherwise \\\"\\\".\\n\\n\""),

    ("the answer to the judge's question starts a whole new turn again", ENGINE,
     "    if not waiting:\n        resumed = resume_card(ex, arrival_ts=arrival_ts)",
     "    if False:\n        resumed = resume_card(ex, arrival_ts=arrival_ts)"),

    ("a blocked card holds no question, so its answer has nothing to resume", ENGINE,
     "        cards.hold_question(ex.key, composed, request, kind=kind, extra=extra)\n",
     ""),

    ("the answer runs the whole loop again instead of one redraft", CARDS,
     "        rounds = 1\n",
     ""),

    ("a card the judge still blocks after the answer is asked about again instead of shown", CARDS,
     "    if (answered is not None and last.draft is not None and last.ruling is not None",
     "    if (False and answered is not None and last.draft is not None and last.ruling is not None"),

    ("a declined question is still taken as its answer", ENGINE,
     "    if held is None or is_no(ex.text):",
     "    if held is None:"),

    ("a question older than a proposal is still an answer", CARDS,
     "    if held is None or time.time() - held.at > QUESTION_TTL_SECONDS:",
     "    if held is None:"),

    ("the judge is not told to be brief, and writes a minute of evidence per verdict", CARDS,
     '"- BE BRIEF: `evidence` is one short sentence per criterion, quoting at most a dozen "',
     '"- `evidence` is as long as it needs to be, quoting what it likes "'),

    ("TODAY'S DEFECT ON THE SIBLING PATH (#392): a report is staged as the person typed it", ENGINE,
     "        compose = getattr(module, \"compose_card\", None)\n        if callable(compose):\n"
     "            composed = compose(request=text, conversation=ex.conversation,\n"
     "                               reply=answer.text or \"\", intake=ex.intake, kind=\"defect\")",
     "        compose = None\n        if callable(compose):\n"
     "            composed = compose(request=text, conversation=ex.conversation,\n"
     "                               reply=answer.text or \"\", intake=ex.intake, kind=\"defect\")"),

    ("a defect card is staged as a requested card", ENGINE,
     "    if kind == \"defect\":\n        return _offer_defect(",
     "    if False:\n        return _offer_defect("),

    ("the yes writes a defect other than the one shown", CONFIRM,
     '        **({"card": entry["card"], "title": entry.get("title", "")}',
     '        **({}'),

    ("a defect's held question comes back as a requested card", ENGINE,
     "    return _offer_card(ex, composed, request=held.request, kind=held.kind,",
     "    return _offer_card(ex, composed, request=held.request, kind=\"ticket\","),
]

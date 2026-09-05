"""A typed Case per conversation — the cuts that make it a re-reading again.

ROW 1 IS THE FACTS NOT KEPT (every turn a first turn). ROW 2 IS THE QUESTION NOT KEPT (the role
asks again). ROW 3 IS THE STAGING NOT MOVING THE CASE. ROW 4 IS THE DISPLACED CASE LOST WITH ITS
FACTS. ROW 5 IS THE EXECUTOR NOT FILING IT. ROW 6 IS THE ROLE NOT HANDED THE INTAKE. ROW 7 IS A
DAY-OLD INTAKE STILL THIS ONE. ROW 8 IS THE ROW SHOWING A PRIVATE INTAKE TO EVERYBODY.
"""

TEST = "tests/test_an_intake_is_a_typed_case.py"

MUTATIONS = [
    ("the facts are not kept — every turn is a first turn",
     "openfactory/product/case.py",
     '        facts = [*case.facts, (text or "").strip()[:_FACT_MAX]] if (text or "").strip() \\\n            else list(case.facts)',
     '        facts = [(text or "").strip()[:_FACT_MAX]] if (text or "").strip() \\\n            else list(case.facts)'),

    ("the question the role asked is not kept",
     "openfactory/product/case.py",
     "            if last.endswith(\"?\"):\n                asked.append(last[:_ASKED_MAX])",
     "            if False:\n                asked.append(last[:_ASKED_MAX])"),

    ("the staging does not move the case",
     "openfactory/product/staging.py",
     '    _case.hook("proposed", project, thread, entry, displaced=displaced)',
     '    pass'),

    ("a displaced case is dropped with its facts",
     "openfactory/product/case.py",
     '''            _put(project, cases, old.model_copy(update={
                "state": COLLECTING, "draft": {},''',
     '''            _put(project, cases, old.model_copy(update={
                "state": DROPPED, "draft": {},'''),

    ("the executor does not file the case",
     "openfactory/product/confirm.py",
     '    _case.hook("filed", project, key, performed, said=said)',
     '    pass'),

    ("the role is not handed the intake",
     "openfactory/product/channel.py",
     "    intake = _case.block_for(project, thread, user)",
     '    intake = ""'),

    ("a day-old intake is still this one",
     "openfactory/product/case.py",
     "                if case.open and now - case.updated_ts > CASE_TTL_SECONDS]:",
     "                if False]:"),

    ("the row shows a private intake to everybody",
     "openfactory/actions/catalog.py",
     '''    key, bad_key = _conversation_key(thread, by)
    if bad_key:
        return bad_key
    from openfactory.product.case import open_cases, render_case''',
    '''    key, bad_key = _conversation_key(thread, by)
    from openfactory.product.case import open_cases, render_case'''),
]

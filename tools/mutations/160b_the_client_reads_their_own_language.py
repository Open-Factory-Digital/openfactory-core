"""#160 (the six composers): the product role speaks the client's language, not the pilot's."""

TEST = "tests/test_the_product_role_speaks_the_clients_language.py"
FOLLOWUP = "openfactory/product/followup.py"
ACT = "openfactory/runtime/temporal/activities.py"
EVENTS = "openfactory/product/events.py"
E2E = "tests/test_product_followup_e2e.py"

MUTATIONS = [
    ("the delivery announcement welds Portuguese again", FOLLOWUP,
     "    if (loop.context or {}).get(\"defect\"):\n"
     "        return _say(_DELIVERED_DEFECT, language).format(sig=sig)\n"
     "    return _say(_DELIVERED_REQ, language).format(sig=sig, subject=loop.subject)",
     '    if (loop.context or {}).get("defect"):\n'
     '        return f"{sig}o problema que foi reportado aqui está corrigido."\n'
     '    return f"{sig}o que foi pedido no requisito {loop.subject} está pronto."'),

    ("the acceptance question does", FOLLOWUP,
     "    return _say(_ACCEPTANCE_Q, language)",
     '    return "\\n\\nDeu para conferir?"'),

    ("the chase does", FOLLOWUP,
     "    return _say(_CHASE, language).format(sig=sig, who=who, about=about, days=days,\n"
     "                                        asked=loop.context.get(\"asked\", \"\"))",
     '    return f"{sig}{who}voltando no {about}, que perguntei há {days} dias."'),

    # THE WHOLE SENTENCE, `about` INCLUDED. A cut that welded only the body left `about` — itself
    # a table lookup — answering differently per language, so the two outputs still differed and
    # the guard passed over a message that is otherwise entirely Portuguese.
    ("the release question does", FOLLOWUP,
     '    about = _say(_RELEASE_ABOUT, language).format(requirement=requirement) '
     "if requirement else \"\"",
     '    about = f" do requisito {requirement}" if requirement else ""'),

    ("an untranslated language raises instead of reading English", FOLLOWUP,
     "    from openfactory.product.voice import _pick\n\n    return _pick(catalogue, language)",
     "    return catalogue[(language or 'en').strip()]"),

    ("…and the reverse: the default stops being the product's own", FOLLOWUP,
     "    from openfactory.product.voice import _pick\n\n    return _pick(catalogue, language)",
     '    return catalogue.get((language or "pt-BR").strip()) or catalogue["pt-BR"]'),

    # ── the round ───────────────────────────────────────────────────────────────────────────────
    ("the round stops handing the language to the ask batch", ACT,
     "                agent_name=name, language=lang)):",
     "                agent_name=name)):", E2E),

    # RE-PINNED 2026-09-24 (#267 slice 3): the delivery is told where it happens now
    # (`events.deliver`, the event's and the sweep's catch-all alike), so its sentence moved there
    ("…and to the delivery announcement", EVENTS,
     "                text = (followup.delivered_text(loop, agent_name=_agent(project),\n"
     "                                                language=_language(project))",
     "                text = (followup.delivered_text(loop, agent_name=_agent(project))",
     E2E),

    ("…and to the release question", ACT,
     "            where=where, agent_name=name,\n"
     '            language=getattr(project, "language", None))',
     "            where=where, agent_name=name)"),

    # ── the guard's own reach ───────────────────────────────────────────────────────────────────
    # RE-PINNED 2026-09-24 (#267 slice 3): the walk reads two files of the round now, one level in
    ("the call-site walk stops looking at the round", TEST,
     "            if getattr(getattr(node.func, \"value\", None), \"id\", \"\") != \"followup\":\n"
     "                continue", "            continue"),
]

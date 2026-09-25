"""#267 slice 2 (the briefing), proven by breaking it.

SEVEN CLAIMS, each cut here and each required to go red:

  1. **Every line carries its source and its age** — the source named, the age the fact's own
     where the platform recorded one.
  2. **It is bounded, and says what it left out** — in lines and in characters, a line cut to fit
     with its source and age kept, and the count of what did not fit, by kind.
  3. **A fact that could not be read is a line saying so** — from the model's gaps, with the
     source that failed, and never an idle floor over an unread one.
  4. **The three withholdings** — names, spend, credentials — each on its own, and all of them
     before the text is folded onto one line; people said by relation, a card question's included.
  5. **The register** — the tech-lead's diagnosis, the engine's reason and the question a parked
     job asks go to an engineer in private and to nobody else, from the rule to the module and
     the engine that hand it over.
  6. **It is always in an answer's prompt, in the board section's place** — and only in an
     answer, and rendered for the person it answers.
  7. **The switch** — off takes the briefing away and brings the board section back.

Each layer of the fixture is fed too: moving, in production, parked, waiting, and the factory's own
loops kept out. The guard is `tests/test_the_briefing.py`, on `tests/the_product_bed.py`.
"""

TEST = "tests/test_the_briefing.py"

BRIEFING = "openfactory/product/briefing.py"
MODEL = "openfactory/product/model.py"
ROLE = "openfactory/product/role.py"
MODULE = "openfactory/product/module.py"
ENGINE = "openfactory/product/engine.py"

MUTATIONS = [
    # ── 1. every line carries its source and its age ───────────────────────────────────────────
    ("a line leaves without its source and its age", BRIEFING,
     '    return f"{body} ({line.source} — {verb} {age(when, now)})"',
     "    return body"),

    ("a line keeps its age and loses its source", BRIEFING,
     '    return f"{body} ({line.source} — {verb} {age(when, now)})"',
     '    return f"{body} ({verb} {age(when, now)})"'),

    ("every line is aged by the reading, never by when the fact happened", BRIEFING,
     "    verb, when = (line.verb, line.when) if line.when else (",
     '    verb, when = ("read", read) if line.when else ('),

    # ── 2. bounded, and the cut is said ────────────────────────────────────────────────────────
    ("there is no bound — every line is said however many there are", BRIEFING,
     "    if len(texts) <= MAX_LINES and _size(texts) <= MAX_CHARS:\n        return texts, 0",
     "    if True:\n        return texts, 0"),

    ("the bound counts lines and never characters", BRIEFING,
     "        if len(trial) + 1 > MAX_LINES or _size([*trial, note]) > MAX_CHARS:",
     "        if len(trial) + 1 > MAX_LINES:"),

    ("a long line is never cut", BRIEFING,
     "    body = _cut(line.body, LINE_CHARS)",
     "    body = line.body"),

    ("what the bound left out is dropped in silence", BRIEFING,
     "    return [*kept, _left_out(dropped)], len(dropped)",
     "    return kept, len(dropped)"),

    ("the count of what was left out is one short", BRIEFING,
     "    n = len(dropped)",
     "    n = len(dropped) - 1"),

    ("what was left out is counted as one kind, whatever it was", BRIEFING,
     "        counts[kind] = counts.get(kind, 0) + 1",
     '        counts["waiting"] = counts.get("waiting", 0) + 1'),

    # ── 3. what could not be read is a line ────────────────────────────────────────────────────
    # re-pinned 2026-09-24 (#269): the documents' line follows the gaps
    ("the model's gaps never reach the briefing", BRIEFING,
     "    facts = [*_not_read(model, say), *_documents(model, say, audience),",
     "    facts = [*_documents(model, say, audience),"),

    ("a gap is said without the source that failed", BRIEFING,
     '        source = next((said for word, said in _GAP_SOURCES if word in lower), '
     '"the read model")',
     '        source = "the read model"'),

    ("an engine that did not answer is briefed as an idle floor", BRIEFING,
     "    if not read:\n        return\n    if not refs:",
     "    if False:\n        return\n    if not refs:"),

    # ── 4. the three withholdings ──────────────────────────────────────────────────────────────
    ("names: a person the turn does not answer is named where their id rides", BRIEFING,
     "    text = names.redact(text)",
     "    text = text"),

    ("spend: the factory's own sentences about spend reach the prompt", BRIEFING,
     "    text = scrub_spend(text)",
     "    text = text"),

    ("credentials: a token in a diagnosis or a failed read reaches the prompt", BRIEFING,
     "    text = scrub_credentials(text)",
     "    text = text"),

    ("the text is folded onto one line before it is withheld, so a spend line anchored to a line "
     "of its own is no longer one", BRIEFING,
     '        text = _withheld(str(text or ""), self.names)\n        text = _flat(text)',
     '        text = _flat(str(text or ""))\n        text = _withheld(text, self.names)'),

    ("a question asked on a card is said to wait on an operator, not on its requester", MODEL,
     '    if kind == "card_question":',
     '    if kind == "card_question-retired":'),

    # ── 5. the register ────────────────────────────────────────────────────────────────────────
    ("an engineer gets the raw diagnosis in a room, where everybody reads the reply", BRIEFING,
     '    return bool(private) and getattr(person, "role", "") == ENGINEER',
     '    return getattr(person, "role", "") == ENGINEER'),

    ("the tech-lead's diagnosis is quoted to a client", BRIEFING,
     "        if raw:\n            # THE STATE BY ITS NAME",
     "        if True:\n            # THE STATE BY ITS NAME"),

    ("the engine's own reason at a gate is said to a client", BRIEFING,
     "        if raw and why:",
     "        if why:"),

    ("the module reads every conversation as private", MODULE,
     "        self._raw_diagnosis = raw_for(speaker, private=private)",
     "        self._raw_diagnosis = raw_for(speaker, private=True)"),

    ("the engine says every conversation is the person's alone", ENGINE,
     '                           **({"private": is_direct(ex.message)}',
     '                           **({"private": True}'),

    ("the section tells the role it speaks privately to an engineer, whoever it speaks to", ROLE,
     "        if self.briefing.raw:",
     "        if True:"),

    # ── 6. always in an answer's prompt, in the board section's place ──────────────────────────
    ("the briefing never reaches the prompt", ROLE,
     "        parts += briefing\n        parts += [\"\", body]",
     "        parts += [\"\", body]"),

    ("an answer is not briefed", ROLE,
     "            briefed=True,",
     "            briefed=False,"),

    # RE-PINNED (#268 slice 1 rebased onto #267): the call now goes on with the product's mounts
    # re-pinned 2026-09-24 (#269 slice 2): the call gained the role's search after the briefing,
    # so the briefing's argument no longer closes it
    ("the module never hands the role its briefing", MODULE,
     "                           briefing=_the_briefing(self),",
     "                           briefing=None,"),

    ("the briefing is rendered for nobody — the person the turn answers is never \"you\"", MODULE,
     "            made = situation.render(model, speaker=module._facts_for,",
     '            made = situation.render(model, speaker="",'),

    ("the board section stays beside the briefing it was replaced by", ROLE,
     '        board_in_prompt = not (briefing and self.mounted.get("facts"))',
     "        board_in_prompt = True"),

    # ── 7. the switch ──────────────────────────────────────────────────────────────────────────
    ("the switch cannot turn it off", BRIEFING,
     '    return str(os.environ.get(SWITCH_ENV, "") or DEFAULT).strip().lower() not in _OFF',
     "    return True"),

    ("the module never reads the switch", MODULE,
     "    if not situation.enabled():",
     "    if False:"),

    ("with no briefing the board section is gone too, so the \"off\" arm is not the prompt as it "
     "was", ROLE,
     '        board_in_prompt = not (briefing and self.mounted.get("facts"))',
     "        board_in_prompt = False"),

    # ── each layer is fed ──────────────────────────────────────────────────────────────────────
    ("moving: the cards the factory is building are never said", BRIEFING,
     '    yield _Line("moving", body, "engine")',
     "    yield from ()"),

    ("in production: the version in production is never said", BRIEFING,
     '    if parts:\n        yield _Line("in production"',
     '    if False:\n        yield _Line("in production"'),

    ("parked: a job stopped on a person is never said", BRIEFING,
     "        if state not in PARKED:\n            continue",
     "        if True:\n            continue"),

    ("waiting: no open loop is said", BRIEFING,
     '            if loop.get("kind") not in FACTORY_LOOPS:',
     "            if False:"),

    ("waiting: the factory's own loops are said as the owner's", BRIEFING,
     '            if loop.get("kind") not in FACTORY_LOOPS:',
     "            if True:"),
    # FROM JOINING SLICES 1–3 (#267): the model's loops are the agenda of the conversation the turn
    # answers in, as `loops.md` is — else a private decision reaches another person's briefing
    ("the module builds the model with every loop, whoever's conversation it lives in",
     "openfactory/product/module.py",
     "                module.project, corpus=ctx.corpus if ctx.available else None,\n"
     "                loops_seen=lambda member: _loops_seen_in(member, conversation, member.name))",
     "                module.project, corpus=ctx.corpus if ctx.available else None)"),
    ("the model reads the whole ledger even when it is handed the conversation's agenda",
     "openfactory/product/model.py",
     "        rows = waiting(loops_seen(member) if loops_seen is not None\n"
     "                       else loop_store.read(member.name))",
     "        rows = waiting(loop_store.read(member.name))"),
]

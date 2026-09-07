"""The question reaches the person who asked (ADR-0048 §5-§7) — the cuts that would answer the
bot's own question, record nobody's word as somebody's, or leave a card waiting for ever."""

TEST = "tests/test_a_question_reaches_the_person_who_asked.py"

MUTATIONS = [
    ("with no requester recorded, an anonymous comment answers",
     "openfactory/knowledge/gather.py",
     "    if not who:\n        return None\n    for c in comments or ():\n",
     "    if False:\n        return None\n    for c in comments or ():\n"),

    ("the sweep accepts the platform's own comment as the answer",
     "openfactory/knowledge/gather.py",
     "        if author != who or (own and author == own):\n",
     "        if author != who:\n"),

    ("a comment older than the question counts as its answer",
     "openfactory/knowledge/gather.py",
     "        if asked_at and when and when <= asked_at:\n",
     "        if False:\n"),

    ("the answer is recorded in the bot's name",
     "openfactory/runtime/temporal/activities.py",
     "            answer=hit.body, said_by=hit.author, where=f\"card #{ref}\")\n",
     "            answer=hit.body, said_by=ctx.get(\"poster\", \"\"), where=f\"card #{ref}\")\n"),

    ("a term the context already holds is a failure",
     "openfactory/runtime/temporal/activities.py",
     "        recorded = bool(result.ok or result.existed)\n",
     "        recorded = bool(result.ok)\n"),

    ("the loop closes on a card that could not be returned",
     "openfactory/runtime/temporal/activities.py",
     "        if moved is False:\n",
     "        if False:\n"),

    ("the question is chased every round",
     "openfactory/runtime/temporal/activities.py",
     "                                after_hours=CARD_QUESTION_CHASE_AFTER_HOURS, ts=now)\n",
     "                                after_hours=0.0, ts=now)\n"),

    ("the people map is guessed between two logins",
     "openfactory/product/requester.py",
     '    return hits[0] if len(hits) == 1 else ""\n',
     '    return hits[0] if hits else ""\n'),

    ("the forge identity is written bare, and @login is not YAML",
     "openfactory/product/authoring.py",
     '        [f"requester_forge: {json.dumps(forge, ensure_ascii=False)}"] if forge else [])\n',
     '        [f"requester_forge: {forge}"] if forge else [])\n'),

    ("the prose line loses its parenthesis",
     "openfactory/product/authoring.py",
     '    return f"{who} ({forge})" if forge and forge != who else who\n',
     '    return who\n'),

    ("a person's answer is filed as a machine's",
     "openfactory/knowledge/gather.py",
     "        generated_by=f\"human:{(by or '').strip() or 'unknown'}\", generated_at=at,\n",
     "        generated_by=\"machine:card-question\", generated_at=at,\n"),
]

"""#129: the check that asks the agent, and the ways it would quietly stop asking.

ROW 1 IS THE DESIGN, RESTORED TO THE OBVIOUS VERSION. "Reply with OK" is what anybody writes first,
and it is satisfied by a harness that echoes its prompt, a stub, a cached transcript and a wrapper
that prints its own arguments. Every one of those is a green light over an unreachable agent, which
is the failure this whole issue is about — so the guard has to go red when the answer becomes
visible in the question.
"""

BASE = "openfactory/adapters/agent/base.py"
ANSWER = "openfactory/agent_answer.py"
TEST = "tests/test_something_finally_asks_the_agent.py"

MUTATIONS = [
    ("the question carries its own answer, so an echo passes", BASE,
     '    return (f"What is {a} plus {b}? Reply with the number alone, no words, no punctuation.",\n'
     '            str(a + b))',
     '    return (f"Reply with the single word {a + b}.", str(a + b))'),

    ("the operands stop being random, so the answer can be cached or hardcoded", BASE,
     "    a, b = rand.randint(11, 89), rand.randint(11, 89)",
     "    a, b = 78, 59"),

    # RETIRED: this row cut the digit-bounded `re.search` that used to BE the implementation.
    # Hermes showed the search itself was the defect — it read `"input_tokens":137` as a reply —
    # so the line it anchored is gone and the claim now lives in the two rows above, which cut
    # the reading instead.

    # THE DEFECT THIS BRANCH SHIPPED, restored: search the stream instead of reading the reply.
    ("the reply is searched for in the whole stream, so a token count answers the question",
     ANSWER,
     "    return any(text.strip() == expected for text in reply_texts(out))",
     "    import re\n"
     '    return bool(re.search(rf"(?<!\\d){re.escape(expected)}(?!\\d)", out or ""))'),

    # RETIRED 2026-09-14: THE CUT SURVIVES AND THE GUARDS ARE RIGHT TO STAY GREEN. What keeps
    # telemetry out of the reply is not this filter — it is that `walk` collects STRINGS only
    # (`"input_tokens":137` is an int) and that the comparison is whole-string (`"ses_0137…"`
    # is not `137`), and both of those have rows of their own. `_REPLY_KEYS` narrows the surface
    # further, and no envelope measured here demonstrates it doing so; a row forcing it red would
    # be enforcing a spelling. Kept as defence in depth, not as a proven claim.

    ("only the FIRST object in the stream is read, which is an init event", BASE,
     "    for obj in json_objects(out):\n        walk(obj)",
     "    first = json_envelope(out)\n    walk(first or {})"),

    ("the reply is matched as a substring again, so 1137 answers 137", ANSWER,
     "    return any(text.strip() == expected for text in reply_texts(out))",
     "    return any(expected in text for text in reply_texts(out))"),

    ("a call that was made is not recorded, so this spender keeps its own books", ANSWER,
     "    if p.on_pass:\n        p.on_pass()",
     "    if False:\n        p.on_pass()"),

    ("a question nobody asked reads as proven", ANSWER,
     '        return self.state == ANSWERED',
     '        return self.state != REFUSED'),

    ("the call is made even with no credential in the box — money spent on a certainty", ANSWER,
     '''    present = p.credential_in_box()
    if present is False:''',
     '''    present = p.credential_in_box()
    if False:'''),

    ("the harness's own words are dropped from the refusal, so the one message that names the "
     "cause never reaches a person", ANSWER,
     '        return Answer(REFUSED, f"the harness exited {rc} and never answered:\\n{_tail(out)}",',
     '        return Answer(REFUSED, f"the harness exited {rc} and never answered",'),

    # THE BUG THIS BRANCH SHIPPED ONCE, restored. Read the answer first and a wall reported as
    # `killed after 45s` answers a question whose sum is 45 — the check reading its own error
    # message as the agent's reply.
    ("the wall is read after the answer, so a timeout message can BE the answer", ANSWER,
     "    if timed_out(rc, out):",
     "    if _answer_in(out, expected):\n"
     "        return Answer(ANSWERED, f\"answered {expected}\")\n"
     "    if timed_out(rc, out):"),

    ("a hang is not recognised at all, so the shape the shipped defect actually takes is the one "
     "shape this cannot see", ANSWER,
     "    if timed_out(rc, out):",
     "    if False:"),

    ("one question inherits the wall a client's test suite needs", ANSWER,
     "SMOKE_SECONDS = 120",
     "SMOKE_SECONDS = 1800"),

    ("the smallest call is built here instead of by the adapter, so it exercises an invocation "
     "nothing issues", BASE,
     '    build = getattr(adapter, "smoke_command", None)\n'
     '    return build(harness=harness, prompt=prompt) if callable(build) else None',
     '    return f"{harness} -p {prompt!r}"'),
]

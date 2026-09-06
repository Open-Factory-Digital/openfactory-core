"""The factory asks before it spends (ADR-0048) — the cuts that would make the gather a toll, a
guess, or a silence."""

TEST = "tests/test_the_factory_asks_before_it_starts.py"

MUTATIONS = [
    ("gather defaults to true — a manifest break, and every un-onboarded project bounces",
     "openfactory/contracts/manifest.py",
     "    gather: bool = False\n",
     "    gather: bool = True\n"),

    ("the gather ignores okf_gate and runs under advise",
     "openfactory/runtime/temporal/activities.py",
     '    if mode != "enforce":\n',
     '    if False:\n'),

    ("an unreadable context repository is read as an absence",
     "openfactory/runtime/temporal/activities.py",
     "    if fetched.unreadable:\n",
     "    if False:\n"),

    ("a directory is handed to the gate as it is",
     "openfactory/knowledge/gather.py",
     "        if here.is_dir():\n",
     "        if False:\n"),

    ("an answer graded on its evidence's grade, not its verification",
     "openfactory/knowledge/gather.py",
     "    if not concepts and not requirements:\n        return False\n",
     "    if not concepts and not requirements:\n        return True\n"),

    ("a stale citation still establishes",
     "openfactory/knowledge/gather.py",
     '    return (all(v == "fresh" for v in concepts.values())\n',
     '    return (all(v in ("fresh", "stale", "missing") for v in concepts.values())\n'),

    ("a park that did not land is treated as a park",
     "openfactory/runtime/temporal/activities.py",
     "        if landed is False:\n",
     "        if False:\n"),

    ("the bot that opened the card is asked the question",
     "openfactory/contracts/ticket.py",
     '    if chat and chat.lower() not in NOBODY:\n        return ""\n',
     '    if chat and chat.lower() not in NOBODY:\n        pass\n'),

    ("the question is asked again while the first one is still waiting",
     "openfactory/runtime/temporal/activities.py",
     "        if already:\n",
     "        if False:\n"),

    ("the marker is not the first line",
     "openfactory/techlead/voice.py",
     '        "en": "{marker}\\n{mention} — to move on I need to know:\\n{questions}\\n\\nAnswer '
     'here, "\n'
     '              "on the card. I will record the answer in the product\'s context and pick the '
     'card "\n'
     '              "up again; nothing is being built until then.",\n',
     '        "en": "{mention} — to move on I need to know:\\n{questions}\\n\\nAnswer here, "\n'
     '              "on the card. I will record the answer in the product\'s context and pick the '
     'card "\n'
     '              "up again; nothing is being built until then.\\n{marker}",\n'),

    ("the fetched checkout leaks on the ask path",
     "openfactory/runtime/temporal/activities.py",
     "    finally:\n        discard_fetched_bundle(bundle)\n\n\n@activity.defn\n"
     "async def gather_context",
     "    finally:\n        pass\n\n\n@activity.defn\nasync def gather_context"),
]

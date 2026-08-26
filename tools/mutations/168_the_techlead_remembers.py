"""#168: the tech-lead reads the thread it has been writing all along.

The reverses guard the promise: an unbounded thread is a bill on every question, and a thread the
model cannot distinguish from an instruction is a prompt-injection surface.
"""

TEST = "tests/test_the_techlead_remembers_the_conversation.py"
CATALOG = "openfactory/actions/catalog.py"
CONV = "openfactory/techlead/conversation.py"
ACT = "openfactory/runtime/temporal/activities.py"
IO = "openfactory/runtime/temporal/io.py"
TRANSCRIPT = "openfactory/memory/transcript.py"

MUTATIONS = [
    ("the door stops reading the thread — every question is turn one again", CATALOG,
     "                                    thread=_thread_so_far(found.name, without=text)),",
     "                                    ),"),

    ("the activity drops it between the door and the worker", ACT,
     "                                     tuple(inp.can or ()), inp.thread or \"\")",
     "                                     tuple(inp.can or ()))"),

    ("the prompt is built without it, so it is carried and never read", CONV,
     'context = ((thread + "\\n\\n") if thread else "")', 'context = ("")'),

    # NOT "below the guidance" — that was a claim I could not justify: orders then history then
    # state is as defensible as history first. What IS a defect is the thread buried UNDER the
    # snapshot, where a stale fact outranks a correction issued two turns ago.
    ("the thread lands below the snapshot, where a stale fact outranks a correction", CONV,
     '    context = ((thread + "\\n\\n") if thread else "") + _guidance(can) + (',
     '    context = _guidance(can) + ('),

    ("the read stops being bounded — a long thread becomes a bill on every question", CATALOG,
     "budget=_THREAD_BUDGET)", "budget=999999)"),

    # ── the reader points at the store the tech-lead actually writes to (found LIVE) ─────────────
    ("the thread reads the OTHER store again — 64 rows in, an empty thread out", TRANSCRIPT,
     "    rows = [m for m in messages.read(project, scan=scan)\n"
     "            if m.kind in (messages.TOLD, messages.SAID)]",
     "    rows = []"),

    ("the machinery rows are rendered as conversation", TRANSCRIPT,
     "            if m.kind in (messages.TOLD, messages.SAID)]", "            ]"),

    ("who said what is lost — the client and the factory become one voice", TRANSCRIPT,
     '        [Turn(role="person" if m.kind == messages.TOLD else "agent",',
     '        [Turn(role="person",'),

    ("the budget trims the RECENT end instead of the opening", TRANSCRIPT,
     "    for turn in reversed(turns):", "    for turn in turns:"),

    ("a store that will not answer costs the ANSWER instead of the thread", CATALOG,
     "    except Exception as exc:  # noqa: BLE001 — a thread we cannot read must not cost "
     "the answer",
     "    except ZeroDivisionError as exc:"),

    ("the question just asked is read back as history and answered twice", CATALOG,
     "                 if not (without and t.text == without)]",
     "                 ]"),

    ("…and the reverse: an empty thread renders a heading with nothing under it", TRANSCRIPT,
     "    if not turns:\n        return \"\"", "    if False:\n        return \"\""),

    ("the transcript welds one client's language back into the neutral renderer", TRANSCRIPT,
     'heading or "## The conversation so far (oldest first)"',
     '"## Conversa até aqui (mais antigo primeiro)"'),

    ("an in-flight AskWorkflow stops deserialising into the behaviour it started with", IO,
     '    #: character budget, not a turn count.\n    thread: str = ""',
     '    #: character budget, not a turn count.\n    thread: str'),
]

"""#113: the remedy names the binary the SHELL could not find, not the command's head.

A gate is usually a wrapper. When `npm run test:e2e` exits 127 because `playwright` is absent,
naming `npm` is false about the image and sends the reader to build one they already have. The
reverses matter too: a direct command must NOT be offered the wrapper's `setup:` remedy, and a
silent output must fall back rather than invent a name — a confident wrong name is the whole
defect, and it can be reintroduced one level down.
"""

TEST = "tests/test_box_prove.py"
SRC = "openfactory/box_prove.py"

MUTATIONS = [
    ("the remedy goes back to naming the command's head, whatever the shell said", SRC,
     "    binary = _missing_binary(out) or head\n",
     "    binary = head\n"),

    ("the output is never read, so every wrapper is blamed for its dependency", SRC,
     '    for line in (out or "").splitlines():\n',
     '    for line in []:\n'),

    ("the marker set stops gating the search and the last segment is taken as a name", SRC,
     "            if parts[i].strip().lower() not in _NOT_FOUND_MARKERS:\n                continue\n",
     "            if False:\n                continue\n"),

    ("a shell's position is accepted as a binary name", SRC,
     "            if name and not name.isdigit() and not name.lower().startswith(\"line \"):\n",
     "            if name:\n"),

    ("…and the reverse: a direct command is offered the wrapper's install remedy", SRC,
     '                  f"finds nothing until its own install step has run)") if binary != head else ""',
     '                  f"finds nothing until its own install step has run)")'),

    ("the wrapper stops being named, so the reader cannot tell which command that was", SRC,
     '    through = f" — `{head}` ran and could not find it" if binary != head else ""\n',
     '    through = ""\n'),

    ("the validate station stops handing the output along, and guesses again", SRC,
     "            remedy = _missing_tool_remedy(cannot_run[0][0], image, cannot_run[0][1])",
     "            remedy = _missing_tool_remedy(cannot_run[0][0], image)"),

    ("the setup station stops handing the output along", SRC,
     "            remedy = (_missing_tool_remedy(cmd, image, out) if _cannot_run(rc, out) else",
     "            remedy = (_missing_tool_remedy(cmd, image) if _cannot_run(rc, out) else"),
]

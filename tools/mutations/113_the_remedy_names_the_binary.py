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

    # RE-PINNED 2026-09-14 (#130). `for line in (out or "").splitlines():` stopped being unique
    # when `_trust_files` in the same file learned to parse its probe's output the same way — the
    # backstop caught it as `matches 2x`. The claim is unchanged; the anchor now carries the line
    # above it, which belongs to this function alone.
    ("the output is never read, so every wrapper is blamed for its dependency", SRC,
     '    binary, because a confident wrong name is what this function exists to stop."""\n'
     '    for line in (out or "").splitlines():\n',
     '    binary, because a confident wrong name is what this function exists to stop."""\n'
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
     # RE-PINNED 2026-09-13 (#109 union): the call gained `honours_image` and wrapped.
     "            remedy = _missing_tool_remedy(cannot_run[0][0], image, cannot_run[0][1],\n"
     "                                          honours_image=p.honours_image)",
     "            remedy = _missing_tool_remedy(cannot_run[0][0], image,\n"
     "                                          honours_image=p.honours_image)"),

    ("the setup station stops handing the output along", SRC,
     # RE-PINNED 2026-09-13 (#109 union): same call, now carrying `honours_image`.
     "            remedy = (_missing_tool_remedy(cmd, image, out, honours_image=p.honours_image)",
     "            remedy = (_missing_tool_remedy(cmd, image, honours_image=p.honours_image)"),
]

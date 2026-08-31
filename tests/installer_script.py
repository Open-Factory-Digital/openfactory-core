"""Shared readers for `install.sh`, so three guard files judge the same script the same way.

WHY THIS IS A MODULE AND NOT THREE COPIES. `tests/add_ons.py` and `tests/demo_projects.py` are the
pattern: a fact several guards need is read in one place, so it cannot be read two different ways.
Two of the readers here exist because a guard got them WRONG first, and the wrongness is the
interesting part — both are written down where the next person will meet them:

`commands_only` — a `sudo` inside a quoted MESSAGE is the script telling somebody how to start
their own daemon, which is the house rule working. A scan that reads that as "the installer calls
sudo" reports correct behaviour as the defect (2026-08-31).

`expand` — the asset download is `curl "${base}/${asset}"`, and `base` is built out of `RELEASES`,
which is built out of `ORG` and `REPO`. A guard that pattern-matches the literal text has to be
taught every new variable name by hand, and the first `curl "$SOMETHING"` nobody taught it about is
exactly the one worth catching.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
SCRIPT = INSTALLER.read_text()

#: A double- or single-quoted span: a MESSAGE, which is the opposite of an invocation.
_STRING_LITERAL = re.compile(r'"[^"]*"|\'[^\']*\'')

#: `NAME="value"` / `name=value` at any indentation — the script's own assignments.
_ASSIGNMENT = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"]*)"|([^\s;|&]+))', re.M)


def code_lines() -> list[str]:
    """The lines that RUN, without the comments."""
    return [line for line in SCRIPT.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def commands_only(line: str) -> str:
    """`line` with its message strings taken out, so a scan sees commands and not prose."""
    return _STRING_LITERAL.sub("", line)


def expand(line: str) -> str:
    """`line` with the script's own variables substituted in, as far as they resolve."""
    values = {m.group(1): (m.group(2) if m.group(2) is not None else m.group(3))
              for m in _ASSIGNMENT.finditer(SCRIPT)}
    for _ in range(6):  # ORG -> RELEASES -> base; a cycle simply stops resolving
        expanded = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                          lambda m: values.get(m.group(1), m.group(0)), line)
        if expanded == line:
            break
        line = expanded
    return line

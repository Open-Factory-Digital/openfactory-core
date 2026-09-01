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


#: The assembly the release runs. It was eleven lines inside `.github/workflows/release.yml` until
#: 2026-09-01, when two version numbers had been spent on shell bugs nothing outside a real tag
#: could execute; it is `scripts/collect-release-assets.sh` now.
ASSEMBLY = ROOT / "scripts" / "collect-release-assets.sh"


def release_assets() -> set[str]:
    """The asset names the release attaches, read from the assembly script.

    READ IN ONE PLACE because three guards ask this, and they asked it of the WORKFLOW STEP until
    the assembly moved into a script — at which point all three silently started reading a `run:`
    line that says only `sh scripts/collect-release-assets.sh dist`. Two of them would then have
    been comparing against an empty set, which is the shape that passes while measuring nothing."""
    text = ASSEMBLY.read_text()
    instructions = [line.strip() for line in text.splitlines()
                    if not line.lstrip().startswith("#")]
    names: set[str] = set()

    for line in instructions:
        if not line.startswith("cp "):
            continue
        words = [w.strip('"') for w in line.split()[1:]]
        target = words[-1]
        if target.endswith("/"):                       # `cp <sources…> "$dist/"`
            names.update(w for w in words[:-1] if not w.startswith("$"))
        else:                                          # `cp <source> "$dist/<name>"`
            names.add(target.rsplit("/", 1)[-1])

    # THE `for optional in …` LOOP, which copies through a variable no `cp` line can name. Only the
    # ones the tree actually holds, which is what the script's own `if [ -f "$optional" ]` does:
    # claiming `install.md` before Phase 2 writes it would describe a release nobody can cut.
    for line in instructions:
        if match := re.match(r"for optional in (.+); do", line):
            names.update(name for name in match.group(1).split() if (ROOT / name).is_file())

    if "> SHA256SUMS" in text:
        names.add("SHA256SUMS")
    return names

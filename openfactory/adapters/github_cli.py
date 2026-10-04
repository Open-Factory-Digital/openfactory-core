"""The one rule every `gh` call this platform makes obeys: it names what it acts on.

`gh issue comment 12 --repo ""` DOES NOT FAIL. `gh` reads an empty `--repo` as no `--repo` at all,
and then resolves the repository from the git remote of the directory it runs in. A project whose
GitHub row carries no repository (a registry entry with no `repo`, a test's bare `Project`) was
therefore acted on in whatever checkout the process happened to start in.

MEASURED, NOT IMAGINED. From 2026-09-29 to 2026-10-01, the suite's two real-daemon preview tests
registered `Project(name="acme")`, which builds a GitHub tracker with `repo=""`, and the preview's
"Preview up" comment on card 12 went to `Open-Factory-Digital/openfactory-core` issue #12, the
repository the suite runs from, through the operator's own `gh` login: 31 comments in three days.
"""

from __future__ import annotations

import subprocess

#: The flags this platform passes from configuration whose EMPTY value `gh` fills in by guessing,
#: each with what it would guess from (review of #489). An empty `--head` on `pr create` is the
#: branch checked out in the working directory; an empty `--base` its default branch; an empty
#: `--owner` on a project board the authenticated account, whose projects are not the client's.
GUESSED = {
    "--repo": "the repository of the directory it runs in",
    "-R": "the repository of the directory it runs in",
    "--owner": "the account it is logged in as",
    "--head": "the branch checked out in the directory it runs in",
    "-H": "the branch checked out in the directory it runs in",
    "--base": "the repository's default branch",
    "-B": "the repository's default branch",
}


def nothing_named(args: list[str]) -> str:
    """Why this `gh` call must not run, or `""` when it may: it passes one of `GUESSED`'s flags
    with nothing in it, which `gh` would fill in by guessing rather than refuse."""
    for i, arg in enumerate(args):
        flag, inline = (arg.split("=", 1) + [None])[:2] if arg.startswith("--") else (arg, None)
        if flag not in GUESSED:
            continue
        value = inline if inline is not None else (args[i + 1] if i + 1 < len(args) else "")
        if not str(value or "").strip():
            return (f"`gh {' '.join(args[:2])}` passes `{flag}` with nothing in it: the setting "
                    f"behind it is empty, and `gh` would act on {GUESSED[flag]} instead. Set it.")
    return ""


def refused(args: list[str], why: str) -> subprocess.CompletedProcess[str]:
    """A `gh` call that was never run, answered the way a failed one is: every caller already
    reads a non-zero exit as "the forge did not do it", and a write raises on it."""
    return subprocess.CompletedProcess(["gh", *args], 2, "", why)

"""The one rule every `gh` call this platform makes obeys: it names the repository it acts on.

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


def no_repository_named(args: list[str]) -> str:
    """Why this `gh` call must not run, or `""` when it may: it passes `--repo`/`-R` with nothing in
    it, which `gh` would fill in from the working directory."""
    for i, arg in enumerate(args):
        if arg in ("--repo", "-R"):
            value = args[i + 1] if i + 1 < len(args) else ""
            if not str(value or "").strip():
                return (f"`gh {' '.join(args[:2])}` names no repository: this project's GitHub row "
                        f"carries none, and `gh` would act on the repository of the directory it "
                        f"runs in instead. Set the project's `repo`.")
        elif arg.startswith("--repo="):
            if not arg.split("=", 1)[1].strip():
                return (f"`gh {' '.join(args[:2])}` names no repository: this project's GitHub row "
                        f"carries none. Set the project's `repo`.")
    return ""


def refused(args: list[str], why: str) -> subprocess.CompletedProcess[str]:
    """A `gh` call that was never run, answered the way a failed one is: every caller already
    reads a non-zero exit as "the forge did not do it", and a write raises on it."""
    return subprocess.CompletedProcess(["gh", *args], 2, "", why)

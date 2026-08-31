"""The test census — the first thing this platform reads out of a command's STDOUT.

`docs/STATUS.md` states the ceiling plainly: *"The `setup:` and `validate:` commands are shell
strings and only the exit code is read."* That is what makes any stack work, and it is also the
limit on everything the factory can assert. Green means "the command exited 0" — and a suite that
exits 0 because forty tests stopped being collected exits 0 just as convincingly as one that exits
0 because forty tests passed.

`_SUPPRESSION_RE` already closes the small version of this hole: a `# noqa` added to silence a real
error is caught in the diff. The large version was open. Deleting a test file out of discovery,
renaming it out of the collector's glob, or breaking an import so a whole module stops being
collected are all invisible to an exit code, and all of them make the suite greener.

WHAT IS COMPARED, AND WHY IT IS A COUNT RATHER THAN A SET. The census runs the declared command
twice: once on the clean workspace before the agent touches it, once after. A SET difference would
flag every renamed test as a vanished one, and renaming tests is ordinary work — the guard would
human-gate refactors and be turned off within a week. So the GATE is a drop in the count, which a
rename leaves untouched (minus one, plus one), and the vanished identifiers are carried as the
REASON. A gate that refuses without naming what it refused is a gate nobody can argue with.

WHY THE COMMAND IS THE PROJECT'S AND THE PLATFORM SHIPS NONE. `floor.yaml` already answers this
about `test:` and the answer holds here word for word: there is no command that enumerates a
project's tests in every language, build system and repository layout, and a guessed one either
fails everywhere (noise) or succeeds having enumerated nothing — a census of the empty set, which
is a green light over exactly the hole this closes.

WHAT IS NOT HERE, stated so it is not mistaken for done. §3.2 asks for skip/xfail detection
alongside the census, and this is only the census. A test that is collected and skipped is still
collected, so it does not move this count — catching it is a DIFF-level guard of the same family as
`_SUPPRESSION_RE`, not a stdout reading, and it is its own piece of work. The other two gates the
inventory unlocks — red-before-green measured, and the AC → test map — are also not here.
"""

from __future__ import annotations

import logging

from openfactory.contracts.manifest import Manifest

log = logging.getLogger("openfactory.policy.census")

#: Carried into a pull request body a person reads, so a change that removed a whole package does
#: not print four hundred lines. `vanished_count` keeps the true number.
MAX_SHOWN = 12


def inventory_command(manifest: Manifest) -> str | None:
    """The project's declared enumerate-the-tests command, or None.

    Repo-wide and deliberately not per-component: a census is a statement about the whole suite,
    and a per-component one would answer a question nobody asked — whether the tests of the area
    this diff happened to touch got smaller, which is not the hole.
    """
    cmd = (getattr(manifest, "test_inventory", None) or "").strip()
    return cmd or None


def inventory_of(stdout: str | None) -> tuple[str, ...]:
    """The test identifiers in one run's output, in order, summary lines dropped.

    THE FILTER IS CONSERVATIVE AND IT EXISTS FOR ONE MEASURED REASON: `pytest --collect-only -q`
    ends with `120 tests collected in 0.52s`, and that line's DURATION changes between two runs of
    an unchanged suite. Compared naively it is a line that vanished and a line that appeared, on
    every job, for every project — a census that fires on nothing at all and is therefore switched
    off. So a line starting with a digit is a summary, never an identifier: test ids are paths,
    namespaces and function names, and they do not begin with one. A line ending in `:` is a header
    (`dotnet test -t` prints *"The following Tests are available:"*).

    Everything else is kept verbatim, because the platform does not know what a test id looks like
    in a language it has never heard of and guessing would be the same mistake as guessing the
    command.
    """
    out: list[str] = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if not line or line.endswith(":") or line[0].isdigit():
            continue
        out.append(line)
    return tuple(out)


def vanished(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[str, ...]:
    """Identifiers present before the change and absent after it — the census's REASON.

    Not the gate. A rename shows up here and does not move the count, which is the whole reason the
    two are separate: this list is what a person reads, and the count is what holds the merge.
    """
    later = set(after)
    return tuple(t for t in before if t not in later)[:MAX_SHOWN]


def reason(before_count: int, after_count: int, gone: tuple[str, ...]) -> str:
    """One line for the pull request body."""
    if after_count >= before_count:
        return ""
    line = (f"the test census fell from {before_count} to {after_count} collected — a suite that "
            f"stopped collecting tests exits 0 just as convincingly as one that passed them")
    if gone:
        line += ". No longer collected: " + ", ".join(f"`{t}`" for t in gone)
    return line

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

#: How many identifiers a reader is SHOWN, so a change that removed a whole package does not print
#: four hundred lines. THE TRUNCATION BELONGS TO THE READER AND NOT TO THE MEASUREMENT:
#: `vanished()` returns every one of them and `RunResult.test_census_gone_count` carries the true
#: number. The first revision's comment here promised a `vanished_count` that existed nowhere, and
#: the number was not recoverable from the count drop either — a rename is minus-one-plus-one by
#: this design's own argument. Same split as `undeclared_paths`/`undeclared_count`.
MAX_SHOWN = 12


def inventory_command(manifest: Manifest) -> str | None:
    """The project's declared enumerate-the-tests command, or None.

    Repo-wide and deliberately not per-component: a census is a statement about the whole suite,
    and a per-component one would answer a question nobody asked — whether the tests of the area
    this diff happened to touch got smaller, which is not the hole.
    """
    cmd = (manifest.test_inventory or "").strip()
    return cmd or None


def inventory_of(stdout: str | None) -> tuple[str, ...]:
    """The test identifiers in one run's output, in order, summary lines dropped.

    THE FILTER IS CONSERVATIVE AND IT EXISTS FOR ONE MEASURED REASON: `pytest --collect-only -q`
    ends with `120 tests collected in 0.52s`, and that line's DURATION changes between two runs of
    an unchanged suite. Compared naively it is a line that vanished and a line that appeared, on
    every job, for every project — a census that fires on nothing at all and is therefore switched
    off. So a line starting with an ASCII digit is a summary, never an identifier: test ids are
    paths, namespaces and function names, and they do not begin with one. A line ending in `:` is a
    header (`dotnet test -t` prints *"The following Tests are available:"*).

    Everything else is kept verbatim, because the platform does not know what a test id looks like
    in a language it has never heard of and guessing would be the same mistake as guessing the
    command.

    AND THIS FILTER CANNOT SAVE A NOISY COMMAND — measured, on this repository, with the example
    this module used to ship. `pytest --collect-only -q` also prints a warnings-summary block that
    `-q` does not suppress, and its five lines are kept:

        inventory_of() count: 8529        pytest says: 8524

    The direction that matters is UP. Delete three tests, have the change introduce four new
    deprecation warnings, and the census RISES while the suite shrank: the gate compares counts,
    the counts moved the wrong way, and the merge proceeds — the exact failure this module exists
    to prevent, reached through its own shipped example. Making the filter smarter is the same
    mistake as guessing the command, so the answer is elsewhere and it is threefold: the shipped
    examples are the quiet forms of each command, `_take_census` LOGS both counts so an adopter can
    compare them against what their runner reports on day one, and `reason()` prints the vanished
    identifiers WHENEVER THERE ARE ANY rather than only when the count fell — because `vanished()`
    named all three deleted tests correctly in the case above and both readers threw the answer
    away.
    """
    out: list[str] = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        # `.isdigit()` alone is true of `'٣'` and of superscripts; the intent is an ASCII number.
        if not line or line.endswith(":") or (line[0].isascii() and line[0].isdigit()):
            continue
        out.append(line)
    return tuple(out)


def vanished(before: tuple[str, ...], after: tuple[str, ...]) -> tuple[str, ...]:
    """Identifiers present before the change and absent after it — the census's REASON.

    Not the gate. A rename shows up here and does not move the count, which is the whole reason the
    two are separate: this list is what a person reads, and the count is what holds the merge.

    EVERY ONE OF THEM, in `before`'s order and untruncated — see `MAX_SHOWN`. The caller shows the
    first few and records the number; a list cut here is a number nobody can recover.
    """
    later = set(after)
    return tuple(t for t in before if t not in later)


def reason(before_count: int | None, after_count: int | None, gone: tuple[str, ...],
           gone_total: int | None = None) -> str:
    """One line for the pull request body — the same three states the gate reads.

    TYPED `int | None` BECAUSE THE FIELDS FEEDING IT ARE. `RunResult.test_census_before` is
    `int | None` by design and the whole three-state argument turns on that, so a signature saying
    `int` made `reason(None, 5, ())` raise `TypeError` on the comparison — at the moment a pull
    request body is being built, which is the worst possible place to discover it.

    IT DOES NOT SILENCE ITSELF WITH THE COMPARISON THAT LET THE MERGE THROUGH. The first revision
    early-returned `""` whenever `after >= before`, which is exactly the case where a person most
    needs to see the list: three tests deleted, four warning lines added, count up, gate open, and
    `vanished()` holding the right answer with nobody to tell. The identifiers print whenever there
    are any; only the COUNT decides the merge.
    """
    if before_count is None:
        # No census at all — the project declares no inventory command, or it could not be read on
        # the clean tree. Nothing to say, and nothing is gated.
        return ""
    if after_count is None:
        # A CENSUS EXISTED AND COULD NOT BE TAKEN AFTER THE CHANGE, which is one of the three
        # failures this gate holds for and had no sentence at all: the agent broke enumeration, so
        # the suite can no longer say what it contains.
        return (f"the test census could not be taken after this change — {before_count} tests were "
                f"collected before it and the inventory command no longer runs, so the suite can "
                f"no longer say what it contains")
    line = ""
    if after_count < before_count:
        line = (f"the test census fell from {before_count} to {after_count} collected — a suite "
                f"that stopped collecting tests exits 0 just as convincingly as one that passed "
                f"them")
    if gone:
        shown = ", ".join(f"`{t}`" for t in gone[:MAX_SHOWN])
        more = (gone_total or len(gone)) - len(gone[:MAX_SHOWN])
        if more > 0:
            shown += f", and {more} more"
        if line:
            line += ". No longer collected: " + shown
        else:
            # THE COUNT DID NOT FALL AND THESE STILL WENT AWAY. Either a rename — ordinary, and the
            # reason this is not the gate — or a noisy inventory command hiding a real deletion
            # behind lines that are not tests. Both are worth a sentence to the person deciding.
            line = ("the test census did not fall, and these identifiers are no longer collected "
                    "(a rename, or a count hiding a deletion behind non-test output): " + shown)
    return line

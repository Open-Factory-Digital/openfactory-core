"""`install.sh` knows two things about your machine. The package knows the rest.

THE DESIGN THIS HOLDS IN PLACE. The installer has two lanes and one truth: `openfactory preflight`
is the single home for "what is wrong with this machine", it emits `Finding`s with a remedy each,
and both the human report and the agent lane read the same document. That only stays true while the
shell stays thin — every check that migrates into `install.sh` is a diagnosis with no remedy field,
no test, no JSON, and no way for the agent lane to see it. Two homes for the same question is
exactly the defect `openfactory/onboarding/readiness.py` was written to close, and it closed it
after `doctor`, `gate_reason` and `conformance` had spent months disagreeing about the word
"ready".

THE ONE HONEST EXCEPTION, WRITTEN DOWN RATHER THAN HIDDEN. The shell cannot ask the package
anything before Docker works — the package runs IN a container. So the shell is allowed exactly two
facts: `docker` is on PATH, and the daemon answers. Each has its own remedy string, because at that
moment there is nothing else to give a person.

WHY A COUNT AND NOT A REVIEW. "Keep the shell thin" is a preference and preferences lose to the
next convenient check. Two is a number, and the sentinel block in `install.sh` is where it is
measured. If a third fact is genuinely needed, this guard is the conversation — the number moves
deliberately, in a commit that says why, which is the whole point of putting a number on it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
SCRIPT = INSTALLER.read_text()

#: The block the shell's own checks live in. `install.sh` carries the matching comment explaining
#: that nothing else may go between them.
BEGIN, END = "# openfactory:facts:begin", "# openfactory:facts:end"

#: The number the design allows. Moving it is a decision, not a fix.
ALLOWED_FACTS = 2


def _facts_block() -> str:
    assert BEGIN in SCRIPT and END in SCRIPT, (
        f"install.sh no longer marks its own check block with {BEGIN!r} / {END!r} — this guard "
        f"cannot see what it is counting, and a guard that cannot fail is worse than none")
    return SCRIPT[SCRIPT.index(BEGIN) + len(BEGIN):SCRIPT.index(END)]


def test_the_shell_checks_exactly_two_facts():
    """THE number. A third one here is a check with no remedy field, no test and no JSON."""
    functions = re.findall(r"^([a-z_][a-z0-9_]*)\s*\(\)\s*\{", _facts_block(), re.M)

    assert len(functions) == ALLOWED_FACTS, (
        f"install.sh checks {len(functions)} things about the machine ({functions}); the design "
        f"allows {ALLOWED_FACTS}. Everything else belongs to `openfactory preflight`, where it is "
        f"a Finding with a remedy that the agent lane can read.")


def test_the_two_facts_are_docker_on_path_and_a_daemon_that_answers():
    """WHICH two, not just how many. Swapping one for a different check would keep the count and
    lose the property — and these two are the only ones that must be answered before the package
    can be asked anything at all."""
    block = _facts_block()

    assert "command -v docker" in block, (
        "the shell no longer checks that `docker` is on PATH — the one thing that must be true "
        "before a container can run at all")
    assert "docker version" in block or "docker info" in block, (
        "the shell no longer checks that the daemon ANSWERS. `docker` being installed and the "
        "daemon being up are different facts with opposite remedies, and the compose worker once "
        "hit the second and was told the first")


@pytest.mark.parametrize("fact", ["command -v docker", "docker version"])
def test_each_fact_the_shell_knows_carries_its_own_remedy(fact):
    """A refusal at this point is the very first thing a stranger sees, and `set -e` alone gives
    them a line number. The house rule applies hardest here: one sentence, the cause AND the
    remedy."""
    block = _facts_block()
    start = block.index(fact)
    # the refusal belongs to the check that raised it — read to the end of that function
    body = block[start:block.index("\n}", start)]

    assert "die " in body, f"the `{fact}` check does not refuse by name"
    # `die` takes (cause, remedy); two quoted arguments is what makes the remedy exist at all.
    assert body.count('"') >= 4, (
        f"the `{fact}` check refuses with a cause and no remedy — a symptom handed to the one "
        f"person who does not yet know the system: {body!r}")


def test_everything_else_the_installer_learns_it_asks_the_package_for():
    """The positive twin, and the half that makes the count meaningful. A shell that checked two
    things and then quietly never consulted preflight would satisfy the number and lose the design.

    IT HAS TO BE INVOKED, not merely mentioned. The first version of this test asserted
    `"preflight" in SCRIPT`, and a mutation that replaced the actual call with `say "  (skipped)"`
    survived it green (2026-08-31) — the word still appeared in three comments and in the closing
    "what is left" line. A guard that a comment can satisfy is a guard about comments."""
    invocations = [line.strip() for line in SCRIPT.splitlines()
                   if not line.strip().startswith("#")
                   and re.search(r"in_the_cli\s+(-\S+\s+)*preflight", line)]

    assert invocations, (
        "install.sh never RUNS `openfactory preflight` in the cli image — the two-fact limit is "
        "only honest because everything else is asked of the package, and a mention in a comment "
        "asks it nothing")


@pytest.mark.parametrize("belongs_to_preflight, what", [
    (r"\bnproc\b|--cpus\b", "how many CPUs the machine has"),
    (r"\bfree\s+-[mgh]\b|MemTotal", "how much memory the machine has"),
    (r"\bdf\s+-[hk]\b|disk_usage", "how much disk is free"),
    (r"\blsof\b|\bnetstat\b|\bss\s+-[lnt]", "which ports are in use"),
    (r"python3?\s+--version|python3?\s+-V\b", "which Python the machine has"),
    (r"\buname\s+-m\b|\barch\b\s*$", "which architecture the machine is"),
])
def test_the_shell_does_not_diagnose_what_preflight_diagnoses(belongs_to_preflight, what):
    """The specific checks most likely to migrate here, each one already a `preflight` Finding with
    a remedy. Named individually because "the shell got fatter" is not something a count alone
    reports usefully — this says which check moved and where it belongs."""
    offenders = [line.strip() for line in SCRIPT.splitlines()
                 if not line.strip().startswith("#") and re.search(belongs_to_preflight, line)]

    assert not offenders, (
        f"install.sh works out {what} for itself: {offenders}. That is a `preflight` check — in "
        f"the shell it has no remedy field, no test, and the agent lane cannot see it.")


def test_the_installer_says_out_loud_which_two_facts_it_keeps_for_itself():
    """The exception is written down rather than hidden, because a reader piping a script into
    their shell is owed the shape of it. This is the sentence, and it has to survive."""
    header = SCRIPT[:SCRIPT.index("set -eu")]

    assert re.search(r"\bexactly two\b|\bEXACTLY TWO\b", header), (
        "install.sh's header no longer states that it knows exactly two things — the one honest "
        "exception to `the package knows about the machine` has to be legible to somebody reading "
        "the script before they run it")

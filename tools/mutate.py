"""Run a mutation plan: break the code a guard protects, one cut at a time, and require red.

WHY THIS FILE EXISTS. The house rule is that every new guard is mutation-tested — break the thing
it claims to protect and watch it go red, or the guard is decoration. For one whole session that
rule was honoured by hand-writing the same ~120-line runner six times in a tmp directory, and the
copies kept re-paying for the same two defects:

  - an ANCHOR that no longer matched was discovered mid-run, wasting the whole pass ("SKIP —
    anchor absent", four times in one day);
  - an anchor that matched TWICE mutated the wrong site silently, so the probe tested a change
    nobody meant to make.

So this runner refuses to start until every anchor in the plan matches EXACTLY ONCE, and the
plans themselves are committed under `tools/mutations/` — point-in-time proofs, kept as worked
examples, not run in CI (anchors rot as code moves, and a rotted anchor fails loudly here rather
than passing quietly).

A plan is a Python file defining:

    TEST = "tests/test_the_thing.py"          # default pytest target for every mutation
    MUTATIONS = [
        ("what this breaks, in one sentence", "openfactory/module.py",
         "the exact text to replace",          # "" means: append `new` to the file instead
         "what it becomes",
        ),                                     # optional 5th element: a per-mutation test target
    ]

Usage:
    .venv/bin/python tools/mutate.py tools/mutations/<plan>.py [--only <label substring>]

Exit 0 only when every baseline is green and EVERY mutation goes red. A mutation the suite
survives is printed as ``!!GREEN!!`` and fails the run — that is the whole point.

EVERY TARGET IS A BASELINE, not only the plan's default. A row that carries its own test file
runs against THAT file, and for one round the runner verified only `TEST`: eight rows aimed at a
guard file that was already two-red printed ``RED`` over it, and two of those rows' summaries were
byte-identical to the un-mutated run — a proof that had never seen its cut (review, 2026-08-26).
The baseline is run once per distinct target before anything is mutated, and one red target
refuses the whole plan.
"""

from __future__ import annotations

import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: Written BEFORE a file is mutated and removed after it is restored — so a run that is KILLED
#: leaves a note behind naming the wound.
#:
#: `finally` IS NOT ENOUGH AND THAT COST A NEAR-MISS. A run cut short by a harness timeout gets
#: SIGKILL, which no `finally` and no signal handler can catch; the mutated source simply stays on
#: disk. It happened on 2026-08-20 and the mutant — a fix reverted to the defect it repairs — sat
#: in the working tree through a full green suite, because the guard for that line lives in another
#: file. It was found by an unrelated grep, minutes from being committed.
IN_FLIGHT = ROOT / ".mutate-in-flight"
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly"]


def load_plan(path: str) -> tuple[str, list[tuple]]:
    ns = runpy.run_path(path)
    test = ns.get("TEST")
    mutations = ns.get("MUTATIONS")
    if not isinstance(test, str) or not isinstance(mutations, list) or not mutations:
        sys.exit(f"{path} must define TEST (str) and a non-empty MUTATIONS list")
    return test, mutations


def check_anchors(mutations: list[tuple]) -> list[str]:
    """Every anchor must match exactly once, BEFORE anything runs.

    Zero matches means the plan rotted; two means `replace(old, new, 1)` would mutate a site
    nobody chose. Both were live failure modes of the hand-rolled runners, and both are cheaper
    as a refusal than as a wasted or lying pass."""
    problems = []
    for row in mutations:
        label, rel, old = row[0], row[1], row[2]
        try:
            text = (ROOT / rel).read_text()
        except FileNotFoundError:
            # A PLAN IS A POINT-IN-TIME PROOF OF THE TREE IT WAS WRITTEN IN, and nine of them aim
            # at paths the public cut removes. Read blind, this raised a raw FileNotFoundError out
            # of a tool whose own contract (CONTRIBUTING.md, "failures speak by name") forbids
            # exactly that — the first thing a stranger who runs a plan in the export would see.
            problems.append(
                f"  [{label}] {rel} is not in this tree — the plan targets a path this checkout "
                f"does not carry; a plan proves the tree it was written in, and the paths the "
                f"public cut removes are listed in docs/STATUS.md's excluded-paths table")
            continue
        if old and (n := text.count(old)) != 1:
            problems.append(f"  [{label}] anchor matches {n}x in {rel} (must be exactly 1)")
    return problems


def _make_python_notice(path: pathlib.Path) -> None:
    """Guarantee the interpreter recompiles the file we just cut.

    THE HARNESS COULD REPORT A FALSE SURVIVOR WITHOUT THIS, and it did — caught the day it was
    written, by its own verification test, but only under `-n auto` where things happen fast
    enough. CPython validates a cached `.pyc` against the source's **(mtime in whole seconds,
    size)**. A mutation like `x * 2` → `x * 3` changes neither: same size, and written inside the
    same second as the baseline run that compiled it. So the child process imported the ORIGINAL
    bytecode, the test passed, and the runner printed `!!GREEN!!` about a cut that never happened
    — sending somebody to tighten a guard that was already watching.

    Two belts, because this one lies quietly: the mtime is pushed a second forward so any existing
    `.pyc` is invalid, and the child is told not to write new ones, so the NEXT mutation in the
    same plan starts from the same clean footing. `verify-the-verifier-first`, on the verifier."""
    stamp = path.stat().st_mtime + 2
    os.utime(path, (stamp, stamp))
    cache = path.parent / "__pycache__"
    for stale in cache.glob(f"{path.stem}.*.pyc") if cache.is_dir() else ():
        stale.unlink(missing_ok=True)


def targets_of(mutations: list[tuple], default_test: str) -> list[str]:
    """Every test file some row will run against, the default first, each once.

    A row's fifth element is its own target, and a target nobody verified is a baseline nobody
    saw: a red file reads ``RED`` for every cut aimed at it, cut or no cut."""
    own = sorted({row[4] for row in mutations if len(row) > 4 and row[4]} - {default_test})
    return [default_test, *own]


def run_one(row: tuple, default_test: str) -> bool:
    label, rel, old, new = row[0], row[1], row[2], row[3]
    test = row[4] if len(row) > 4 and row[4] else default_test
    path = ROOT / rel
    original = path.read_text()
    backup = pathlib.Path(tempfile.mkdtemp()) / path.name
    shutil.copy2(path, backup)
    IN_FLIGHT.write_text(json.dumps({"file": rel, "backup": str(backup), "label": label}))
    try:
        path.write_text(original + new if not old else original.replace(old, new, 1))
        _make_python_notice(path)
        proc = subprocess.run(PYTEST + [test], cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        red = proc.returncode != 0
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        print(f"{'RED  ' if red else '!!GREEN!!'} {label}\n         {tail}")
        return red
    finally:
        shutil.copy2(backup, path)
        if path.read_text() != original:
            sys.exit(f"RESTORE FAILED for {rel} — the tree is dirty, fix it before anything else")
        IN_FLIGHT.unlink(missing_ok=True)


def refuse_if_a_previous_run_was_killed() -> None:
    """Stop, loudly, if the last run died with a file still mutated.

    THE ONE THING THIS TOOL MUST NEVER DO is leave a defect in the tree wearing a fix's name. A
    kill signal beats every cleanup path in the process, so the protection cannot live in the
    process — it has to be a note on disk that the NEXT run reads. Restoring automatically is
    deliberately not offered: the backup may be stale or the operator may have edited the file
    since, and a tool that silently rewrites source is how a real change gets lost."""
    if not IN_FLIGHT.exists():
        return
    try:
        note = json.loads(IN_FLIGHT.read_text())
    except ValueError:
        note = {}
    hurt, backup = note.get("file", "?"), note.get("backup", "?")
    sys.exit(
        f"A PREVIOUS MUTATION RUN WAS KILLED and {hurt} may still hold the mutant "
        f'("{note.get("label", "?")}").\n'
        f"  Check it:   git diff {hurt}\n"
        f"  Restore it: cp {backup} {hurt}   (or `git checkout -- {hurt}` if it was committed)\n"
        f"  Then:       rm {IN_FLIGHT}\n"
        "Nothing was run. A green suite over a mutated tree is the one result this tool must "
        "never produce.")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    refuse_if_a_previous_run_was_killed()
    plan_path = argv[0]
    only = argv[argv.index("--only") + 1] if "--only" in argv else ""
    default_test, mutations = load_plan(plan_path)
    if only:
        mutations = [m for m in mutations if only.lower() in m[0].lower()]
        if not mutations:
            sys.exit(f"--only {only!r} matches no mutation label")

    if problems := check_anchors(mutations):
        print("PLAN REFUSED — fix these anchors first (nothing was run):")
        print("\n".join(problems))
        return 1

    for target in targets_of(mutations, default_test):
        baseline = subprocess.run(PYTEST + [target], cwd=ROOT, capture_output=True, text=True)
        if baseline.returncode != 0:
            print(f"baseline is RED ({target}) — the harness proves nothing until the guards "
                  f"pass unmutated; nothing was cut:")
            print(baseline.stdout[-2000:])
            return 1
        print(f"baseline: green ({target})")

    survived = sum(0 if run_one(row, default_test) else 1 for row in mutations)
    print(f"\n{len(mutations) - survived}/{len(mutations)} red"
          + (f" — {survived} SURVIVED: those guards are decoration until they can see the cut"
             if survived else ""))
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""The mutation runner itself is verified before anything trusts it.

`verify-the-verifier-first` is a paid-for rule in this repository: five probes in one day passed
for the wrong reason, so a harness is fed a case that MUST fail before its green means anything.
`tools/mutate.py` is the harness every new guard's proof now runs through — if IT lies, every
"N/N red" this repo reports is decoration wearing a number.

Driven end to end as a subprocess on a throwaway module + guard + plan, because the runner's
failure modes are process-shaped: exit codes, anchor refusal, and restoring the file it cut.

THE VICTIM LIVES IN `tmp_path`, OUTSIDE THE REPO, and the first cut of this file got that wrong
in a way the random-order run caught the same day. It scaffolded into `ROOT/tmp_mutation_victim_*`
on the belief that "the runner resolves plan paths against the repo root, so pointing it at
/var/folders would be testing a path it refuses" — which is simply false: `Path(root) / "/abs"`
is `/abs`, so the runner always accepted both.

What that mistake cost: the knowledge map is generated from the whole repo tree and verified by
checksum against it, and it happily indexed the victim. Under `-n auto` one worker removed its
arena while another was verifying a map that listed it, and
`test_the_generated_map_is_actually_INJECTED` failed — a test with no connection to this one,
broken by this one, exactly the cross-process pollution class the guard audit had named that
morning. A test that writes into the tree under test is a test that can fail its neighbours.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tools" / "mutate.py"


@pytest.fixture
def arena(tmp_path):
    """Outside the repo, so nothing this test writes can be indexed — or removed mid-read — by a
    neighbour scanning the tree."""
    return tmp_path


def _scaffold(arena: pathlib.Path, *, module_body: str | None = None) -> pathlib.Path:
    """A module, a guard that watches it, and a plan with one killable + one survivable cut."""
    (arena / "victim.py").write_text(module_body or "def double(x):\n    return x * 2\n")
    test = arena / "test_victim.py"
    test.write_text(
        f"import sys\nsys.path.insert(0, {str(arena)!r})\n"
        "from victim import double\n\n\n"
        "def test_doubles():\n    assert double(3) == 6\n")
    rel = str(arena / "victim.py")   # absolute: the runner joins it against ROOT and
                                 # pathlib keeps an absolute path as-is
    plan = arena / "plan.py"
    plan.write_text(
        f"TEST = {str(test)!r}\n"
        "MUTATIONS = [\n"
        f"    ('doubling becomes tripling', {rel!r}, 'x * 2', 'x * 3'),\n"
        f"    ('a rename the guard never imports by', {rel!r},\n"
        "     'def double(', 'def double(  # renamed in spirit\\n        *_ignored,'),\n"
        "]\n")
    return plan


def _run(plan: pathlib.Path) -> subprocess.CompletedProcess[str]:
    """The runner as it is on disk right now, copied into the plan's arena and run from there.

    A COPY, BECAUSE THE RUNNER'S ROOT IS WHERE ITS FILE LIVES. Run in place, its in-flight note
    is `<repo>/.mutate-in-flight` — and when THIS guard is the target of a mutation plan that
    cuts `tools/mutate.py`, the parent run's note is on disk for the whole child run, so the
    child refuses every plan as "a previous run was killed" and all six subprocess tests go red
    at once: red for the wrong reason, which `verify-the-verifier-first` exists to catch
    (measured 2026-08-26: `6 failed` from the plan, `2 failed` by hand). From the arena the
    copy's root is the arena, its note lives there, and nothing it does touches the tree."""
    runner = plan.parent / "tools" / "mutate.py"
    runner.parent.mkdir(exist_ok=True)
    runner.write_text(RUNNER.read_text())
    return subprocess.run([sys.executable, str(runner), str(plan)],
                          capture_output=True, text=True, cwd=plan.parent)


def test_a_killable_cut_reads_red_and_the_file_is_restored(arena):
    plan = _scaffold(arena)
    original = (arena / "victim.py").read_text()

    proc = _run(plan)

    assert "baseline: green" in proc.stdout
    assert "RED   doubling becomes tripling" in proc.stdout
    assert (arena / "victim.py").read_text() == original, (
        "the runner left the mutation in the tree")


def test_a_survivable_cut_FAILS_the_run(arena):
    """A plan with a decorative guard must never report success — the survivor is the finding."""
    plan = _scaffold(arena)
    # replace the second mutation with one the guard genuinely cannot see: appending a comment
    plan.write_text(plan.read_text().split("MUTATIONS")[0] + (
        "MUTATIONS = [\n"
        f"    ('doubling becomes tripling', {str(arena / 'victim.py')!r},"
        " 'x * 2', 'x * 3'),\n"
        f"    ('an appended comment nothing asserts on',"
        f" {str(arena / 'victim.py')!r}, '', '\\n# harmless\\n'),\n"
        "]\n"))

    proc = _run(plan)

    assert "!!GREEN!!" in proc.stdout, "a cut nothing can detect was reported as caught"
    assert proc.returncode == 1, "a survivor did not fail the run — decoration reads as proof"
    assert "SURVIVED" in proc.stdout


def test_an_anchor_that_matches_twice_is_REFUSED_before_anything_runs(arena):
    """`replace(old, new, 1)` on a twice-matching anchor mutates a site nobody chose, so the
    probe tests the wrong change — a live failure mode of the hand-rolled runners this replaced.
    Refused up front, before the baseline spends any time."""
    plan = _scaffold(arena, module_body="def double(x):\n    return x * 2\n# note: x * 2 here\n")

    proc = _run(plan)

    assert proc.returncode == 1
    assert "PLAN REFUSED" in proc.stdout and "matches 2x" in proc.stdout
    assert "baseline" not in proc.stdout, "it spent a baseline run on a plan it then refused"


def test_a_plan_aimed_at_a_path_this_tree_does_not_carry_is_REFUSED_BY_NAME(arena):
    """A plan proves the tree it was written in, and nine of the eighty in `tools/mutations/` aim
    at paths the public cut removes. Read blind, the anchor check raised a raw FileNotFoundError
    out of a tool whose own contract forbids one (CONTRIBUTING.md: "never a raw traceback") — the
    first thing a stranger who ran a plan in the export would have seen (pre-launch audit,
    2026-08-26). It refuses by name, before any baseline is spent, and says where the list of
    removed paths lives."""
    plan = _scaffold(arena)
    plan.write_text(plan.read_text().replace(
        str(arena / "victim.py"), str(arena / "a_module_that_left.py")))

    proc = _run(plan)

    assert proc.returncode == 1
    assert "PLAN REFUSED" in proc.stdout
    assert "a_module_that_left.py is not in this tree" in proc.stdout
    assert "docs/STATUS.md" in proc.stdout, "the refusal does not say where the removed paths are listed"
    assert "Traceback" not in proc.stdout + proc.stderr, "a raw traceback survived"
    assert "baseline" not in proc.stdout, "it spent a baseline run on a plan it then refused"


def test_a_plan_whose_paths_all_exist_is_NOT_refused(arena):
    """The positive twin: the missing-path refusal must not fire on a plan that is merely
    ordinary, or every plan in the repository would be refused and the guard above would pass
    over a runner that refuses everything."""
    proc = _run(_scaffold(arena))

    assert "is not in this tree" not in proc.stdout
    assert "baseline" in proc.stdout or "!!GREEN!!" in proc.stdout, proc.stdout[:400]


def test_this_file_writes_NOTHING_into_the_tree_under_test(arena):
    """THE CLASS, not the instance. Under `-n auto` every worker shares one working tree, so a
    test that plants files in it can fail a neighbour that is scanning — which is exactly what
    happened: the knowledge map indexed this file's victim, another worker removed it mid-verify,
    and an unrelated test went red. Asserted by RUNNING the scaffold and diffing the tree."""
    before = {p.name for p in ROOT.iterdir()}
    _scaffold(arena)
    _run(_scaffold(arena))
    assert {p.name for p in ROOT.iterdir()} == before, (
        "this test left something in the repo root — a neighbour scanning the tree can now fail "
        "because of it")
    assert ROOT not in (arena / "victim.py").parents, "the victim is inside the tree under test"


def _scaffold_with_own_target(arena: pathlib.Path, *, other_green: bool) -> pathlib.Path:
    """The default guard plus a SECOND guard file that one row names as its own target. The
    second guard watches `triple`, which the default guard never imports — so a cut on `triple`
    is visible only through the row's own target, and `other_green` decides whether that target
    passes before anything is cut."""
    plan = _scaffold(arena, module_body="def double(x):\n    return x * 2\n\n\n"
                                        "def triple(x):\n    return x * 3\n")
    other = arena / "test_other.py"
    other.write_text(
        f"import sys\nsys.path.insert(0, {str(arena)!r})\n"
        "from victim import triple\n\n\n"
        f"def test_triples():\n    assert triple(2) == {6 if other_green else 7}\n")
    victim = str(arena / "victim.py")
    plan.write_text(plan.read_text().split("MUTATIONS")[0] + (
        "MUTATIONS = [\n"
        f"    ('doubling becomes tripling', {victim!r}, 'x * 2', 'x * 3'),\n"
        f"    ('tripling becomes quadrupling', {victim!r}, 'x * 3', 'x * 4', {str(other)!r}),\n"
        "]\n"))
    return plan


def test_a_row_whose_OWN_target_is_red_at_baseline_is_REFUSED_before_any_cut(arena):
    """The mechanism of a false proof (review, 2026-08-26): the runner verified the plan's default
    TEST and nothing else, so eight rows aimed at a two-red guard file printed RED over it — two
    of them with the un-mutated file's own summary line. A target is a baseline: one red target
    refuses the plan, by name, and no cut is made against anything."""
    plan = _scaffold_with_own_target(arena, other_green=False)

    proc = _run(plan)

    assert proc.returncode == 1
    assert "baseline is RED" in proc.stdout and "test_other.py" in proc.stdout, proc.stdout
    assert "baseline: green" in proc.stdout, "the default target was not verified first"
    assert "!!GREEN!!" not in proc.stdout and "RED  " not in proc.stdout, (
        "it cut against a target that was already failing")


def test_a_row_with_its_OWN_green_target_is_verified_and_then_cut(arena):
    """The positive twin: the same plan with the second guard green runs BOTH baselines, then
    every row against its own target — the `triple` cut reads red through `test_other.py`, which
    the default guard could never have seen."""
    plan = _scaffold_with_own_target(arena, other_green=True)

    proc = _run(plan)

    assert proc.returncode == 0, proc.stdout
    assert proc.stdout.count("baseline: green") == 2, proc.stdout
    assert "baseline: green (" + str(arena / "test_other.py") + ")" in proc.stdout
    assert "RED   tripling becomes quadrupling" in proc.stdout
    assert "2/2 red" in proc.stdout


def test_a_red_baseline_refuses_rather_than_proving_nothing(arena):
    plan = _scaffold(arena, module_body="def double(x):\n    return x * 5\n")
    # keep the anchor present so only the baseline is at fault
    (arena / "victim.py").write_text("def double(x):\n    return x * 5  # x * 2 gone wrong\n")

    proc = _run(plan)

    assert proc.returncode == 1
    assert "baseline is RED" in proc.stdout
    assert "!!GREEN!!" not in proc.stdout and "RED  " not in proc.stdout, (
        "it ran mutations against guards that were already failing")

"""Two tests wrote real source files into the tree they are run from, and a third went red for it.

FOUND BY INSTRUMENTING, NOT BY READING. A poller over the working tree during a full `-n auto` run
recorded exactly two entries appearing and disappearing:

    39.11  +SRC  tests/test__live_engine_probe__.py          ← ~15 seconds
    53.77  -SRC  tests/test__live_engine_probe__.py
   100.00  +SRC  openfactory/_guard_mutation_probe.py        ← ~0.2s, several times a run
   100.17  -SRC  openfactory/_guard_mutation_probe.py

Both were deliberate and both had a stated reason. What neither reason accounted for is the READER:
`knowledge/staleness.py::is_stale` checksums every source file in the tree, so a neighbour that
generates a bundle and verifies it across one of those windows compares two different trees and
reports the map stale against itself. `.github/workflows/ci.yml` runs `pytest -q` — serial — so the
probe can never coexist with the scan there, and CI is structurally blind to it.

ROW 1 IS THE DEFECT AS IT WAS. Putting the probe back under `tests/` is the whole bug, and the
assertion that catches it is a static one — `ROOT not in scratch.resolve().parents` — rather than a
before/after snapshot of the tree, because a snapshot taken while neighbours run is itself racy:
`test_this_file_writes_NOTHING_into_the_tree_under_test` reads `ROOT.iterdir()` and can be failed by
anybody, which is how it went red on a fresh worktree for a reason that had nothing to do with the
file it guards.

ROW 2 IS THE TRAP THE FIRST FIX FELL INTO, and it is the reason the row exists rather than the
reason it is interesting. Moving the probe to a temp directory silently disarmed the guard: pytest
resolves its ini from the ARGUMENTS, so with the probe outside the repository `asyncio_mode = "auto"`
no longer applied, the `async def` probe was collected and never executed, and the child reported
"async def functions are not natively supported". A guard that passes because its subject never ran
is the exact failure this file's own module docstring exists to prevent, so `-c` is not a detail.

ROW 1 ALSO CHANGED THE SHAPE OF THE FIX, by running. The first version asserted the invariant
AFTER writing the probe, so the mutant refused and left the file behind — and the next full suite
collected the orphan and went red on it (measured 2026-09-04). The assertion now comes BEFORE the
write in both files: a guard that damages the tree while refusing to is not a guard, and a mutation
plan that dirties the checkout is a trap for whoever runs it next
(`mutate.py` restores the file it cut, never a file the mutant created).

ROW 4 IS WHY THE SECOND PROBE COULD MOVE AT ALL. The comment said the file had to live under
`openfactory/` because `_is_module` resolves imports against the tree — but `_is_module` resolves
against the module-level `PKG` and never looked at the probe's location. What actually tied it there
was `_offenders` deriving the dotted package from the path. Naming the package outright frees the
file; reverting that derivation puts `relative_to(PKG)` back and every scan raises.
"""

TEST = "tests/test_the_suite_cannot_reach_a_live_engine.py"

_OTHER = "tests/test_no_module_is_ever_called_like_a_function.py"

MUTATIONS = [
    ("the live-engine probe goes back into `tests/`, where it is a source file inside the tree "
     "for the fifteen seconds the subprocess takes",
     "tests/test_the_suite_cannot_reach_a_live_engine.py",
     '    scratch = tmp_path / "test__live_engine_probe__.py"',
     '    scratch = ROOT / "tests" / "test__live_engine_probe__.py"'),

    ("the ini stops being passed, so `asyncio_mode` does not apply, the `async def` probe is "
     "collected and never executed, and the barrier is never exercised",
     "tests/test_the_suite_cannot_reach_a_live_engine.py",
     '        [sys.executable, "-m", "pytest", str(scratch), "-c", str(ROOT / "pyproject.toml"),\n'
     '         "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--no-header"],',
     '        [sys.executable, "-m", "pytest", str(scratch),\n'
     '         "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "--no-header"],'),

    ("the conftest is not copied beside the probe, so the `autouse` barrier never reaches it and "
     "a test that opens a real connection would pass",
     "tests/test_the_suite_cannot_reach_a_live_engine.py",
     '    (tmp_path / "conftest.py").write_text(\n'
     '        (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")',
     '    pass'),

    ("the guard probe goes back inside the package, where it is a source file the knowledge scan "
     "walks",
     _OTHER,
     '        target = pathlib.Path(arena) / "_guard_mutation_probe.py"',
     '        target = PKG / "_guard_mutation_probe.py"',
     _OTHER),

    ("`_offenders` derives the package from the path again, which is what tied the probe to a "
     "location inside `openfactory/` in the first place",
     _OTHER,
     '    package = package or "openfactory." + ".".join(path.relative_to(PKG).with_suffix("").parts[:-1])',
     '    package = "openfactory." + ".".join(path.relative_to(PKG).with_suffix("").parts[:-1])',
     _OTHER),
]

"""An advisory gate that reports and does not halt — and the twelve ways it halts again.

#11's SECOND HALF. `floor.yaml` marks the credential scan advisory and spends a paragraph on why:
a first scan of a fifteen-year-old repository reports the debt of its whole history, *"blocking on
day one means the client turns the gate off, and a gate that gets turned off protects nothing."*

What the flag actually did was narrower than that paragraph: `_all_passed` never consults it, so it
cannot block a merge. `box prove`'s validate station demanded rc==0 from every repo-wide gate on
untouched main, `proof.ok` went False, and `gate_reason` held every card on the project. The word
`advisory` appeared in `box_prove.py` ZERO times. So the stated purpose was not achieved — and not
only for false positives: a legacy repository with one genuine committed credential, which is
precisely the case that paragraph is about, had every ticket blocked on day one.

ROW 4 IS THE ONE THAT DECIDES WHETHER THIS IS SAFE. An advisory failure must not cut the proof
short. The blocking path returns early on purpose — *"validating a broken environment stacks a
second, misleading error"* — and an advisory one taking that same exit would silently stop proving
the harness smoke test and everything after it, the moment a project carries any debt at all.

ROW 5 IS THE EXCEPTION THE FILE ALREADY DRAWS ONE STATION BELOW. `advisory: true` says a finding
should not stop the work; it cannot say the image has a tool the shell has just reported missing.
The per-component check makes exactly this distinction and explains it. Without the exception, the
flag becomes a way to prove a box that cannot run its own gates.

ROWS 9-11 CUT THE OTHER WAY: the version that ignores every red gate, the one that reports a green
count including the failure, and the one that hides the finding entirely — which is the objection
#11 raised against direction 4 and the thing this must not become.
"""

TEST = "tests/test_an_advisory_gate_cannot_hold_a_pickup.py"

MUTATIONS = [
    # ── the defect, restored ────────────────────────────────────────────────────────────────────
    ("`failures()` counts advisory findings again — #11 exactly as reported: a gate the client "
     "declared advisory makes the proof not-ok and `gate_reason` holds every card on the project",
     "openfactory/box_prove.py",
     "        return [f for f in self.findings if not f.ok and not f.advisory]",
     "        return [f for f in self.findings if not f.ok]"),

    ("the station stops separating them, so an advisory gate lands in the blocking list and the "
     "flag reaches `box prove` as nothing at all, which is where it was",
     "openfactory/box_prove.py",
     "        if name in advisory and not _cannot_run(rc, out):",
     "        if False:"),

    ("the flag is lost at the seam it was always lost at: `advisory_gates` reports none, so every "
     "project proves exactly as it did before and the fix is decoration",
     "openfactory/orchestrator/validation.py",
     "    return frozenset(name for name, g in (gates or {}).items() if as_gate(g).advisory)",
     "    return frozenset()"),

    # ── the proof must not be cut short ─────────────────────────────────────────────────────────
    ("an advisory failure takes the blocking path's early return, so the harness smoke test and "
     "every station after it silently stop being proven the moment a project carries any debt",
     "openfactory/box_prove.py",
     "            advisory_gates_failed.append(line)\n            continue",
     "            advisory_gates_failed.append(line)\n            return proof"),

    # ── the exception ───────────────────────────────────────────────────────────────────────────
    ("a command the box CANNOT RUN becomes advisory too, so `advisory: true` turns into a way to "
     "prove a box that cannot execute its own gates — the failure the whole proof exists to catch",
     "openfactory/box_prove.py",
     "        if name in advisory and not _cannot_run(rc, out):",
     "        if name in advisory:"),

    # ── what the reader is told ─────────────────────────────────────────────────────────────────
    ("the advisory finding carries no remedy, which this file's own contract forbids: a finding "
     "with no remedy is a symptom handed to the one person who does not yet know the system",
     "openfactory/box_prove.py",
     '            "declared `advisory: true`, so this does NOT hold pickup and does NOT block a '
     'merge — "',
     '            "" or "',),

    ("the three states collapse to two in the renderer, so `warn` prints as `FAIL` on the surface "
     "a client actually reads — the proof says blocked about something that blocked nothing",
     "openfactory/box_prove.py",
     '        return "ok" if self.ok else ("warn" if self.advisory else "FAIL")',
     '        return "ok" if self.ok else "FAIL"'),

    ("the green count includes the gate that failed, so \"2 gate(s) green\" is printed about a run "
     "where one of them was red — the sentence a reader trusts and should not",
     "openfactory/box_prove.py",
     "    green = len(validate) - len(advisory_gates_failed)",
     "    green = len(validate)"),

    # ── THE OTHER DIRECTION ─────────────────────────────────────────────────────────────────────
    ("OVER-LOOSENED — every red gate stops holding the pickup, advisory or not. The floor becomes "
     "decoration and a box that cannot build the project proves anyway, which is worse than the "
     "bug this fixes",
     "openfactory/box_prove.py",
     "        return [f for f in self.findings if not f.ok and not f.advisory]",
     "        return []"),

    ("OVER-LOOSENED — the advisory failure is not recorded at all, only skipped. This is the "
     "objection #11 raised against direction 4 — *a proof that ignores a red gate proves less* — "
     "and it is what this must not become: reported, never blocking",
     "openfactory/box_prove.py",
     "    if advisory_gates_failed:\n        # RECORDED BEFORE THE BLOCKING ONES",
     "    if False:\n        # RECORDED BEFORE THE BLOCKING ONES"),

    ("OVER-LOOSENED — `advisories()` returns nothing, so the finding exists and no caller can ask "
     "for it: reported to a list nobody reads is the same as not reported",
     "openfactory/box_prove.py",
     "        return [f for f in self.findings if not f.ok and f.advisory]",
     "        return []"),

    # ── the confusion that cost fourteen guards ─────────────────────────────────────────────────
    ("the three-state mark is given to the DOCTOR's Finding, which has two states and lives in "
     "another module. The two render loops in `cli.py` are byte-identical and about different "
     "objects; changing the wrong one raised AttributeError inside the CLI runner and printed a "
     "blank page where the doctor's whole report should be — fourteen guards, one line",
     "openfactory/doctor.py",
     "class Finding:",
     "class Finding:\n    mark = 'ok'"),
]

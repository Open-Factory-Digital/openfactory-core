"""The eight ways a knowledge bundle keeps working and quietly stops being trustworthy.

Not one row here is an error. Every one produces a factory that runs, writes a bundle, and hands
a role something it should not believe — which is the only failure mode this artifact has. A
concept that is wrong looks exactly like a concept that is right, unless the citation holds.

ROWS 1-2 ARE THE THESIS ITSELF. A sentence with no surviving citation becoming a concept anyway
(1), and the sources being taken from the model's own answer instead of earned from the citations
that resolved (2). Either one turns the bundle back into an opinion with provenance-shaped
decoration, and neither changes a single visible behaviour.

ROWS 3-4 ARE THE COST GOING UNBOUNDED. `propose_context` refuses a fan-out whose price depends on
the client's monolith, and a budget is what keeps that promise mechanical rather than stated. Row
3 ignores the declared number; row 4 removes the ceiling that stops a typo becoming a bill.

ROWS 5-6 ARE A FAILURE GOING SILENT — the difference between "nothing to say about this module"
and "we tried and could not", which is exactly what a reader cannot reconstruct afterwards.

ROWS 7-8 ARE THE FILE LAYOUT LOSING A FACT. The title collision that the first end-to-end run
found (7) — every unit test passed while it was live — and the index re-deriving a path instead of
using the writer's own assignment (8), which makes a link open a concept it does not name.
"""

TEST = "tests/test_a_concept_is_earned_not_declared.py"

MUTATIONS = [
    # ── the thesis: a claim is earned or it is not written ───────────────────────────────────────
    ("a rule whose citations all failed verification is written into the concept anyway, so the "
     "bundle carries a sentence nobody can check — provenance-shaped decoration, and the exact "
     "thing `_Anchorer` exists to make impossible",
     "openfactory/onboarding/concepts.py",
     "        if not kept:\n"
     "            continue  # a rule with no surviving citation is a gap, recorded by the caller",
     "        if not kept:\n            pass"),

    ("the concept's sources stop being derived from citations that resolved, so the fingerprints "
     "that will later invalidate it describe files its claims were never read from — staleness "
     "goes back to being a judgement instead of a mechanism",
     "openfactory/onboarding/concepts.py",
     "            if evidence.path not in seen:\n"
     "                seen[evidence.path] = ConceptSource(",
     "            if False:\n                seen[evidence.path] = ConceptSource("),

    # ── the cost stops being quotable ────────────────────────────────────────────────────────────
    ("the declared budget is ignored and every module is described, so an onboarding step's price "
     "depends on the size of the client's monolith — the one thing `propose_context`'s docstring "
     "refuses by name",
     "openfactory/onboarding/concepts.py",
     "    ranked = sorted(survey.modules, key=score, reverse=True)\n"
     "    return ranked[:min(budget, MAX_CONCEPT_BUDGET)]",
     "    ranked = sorted(survey.modules, key=score, reverse=True)\n    return ranked"),

    ("the hard ceiling goes, so a manifest typo of two extra zeros becomes a bill nobody approved",
     "openfactory/contracts/manifest.py",
     "    okf_concept_budget: int = Field(default=5, ge=0, le=50)",
     "    okf_concept_budget: int = Field(default=5, ge=0)"),

    # ── a failure goes silent ────────────────────────────────────────────────────────────────────
    ("a module whose agent pass raised is skipped without a word, so the bundle cannot tell a "
     "module nobody needed to describe from one the platform tried and failed on",
     "openfactory/onboarding/concepts.py",
     '            gaps.append(Gap(kind="not-described", path=module.path,\n'
     '                            detail=f"the agent pass failed for this module '
     '({str(exc)[:120]})"))\n'
     "            continue",
     "            continue"),

    ("an unreadable answer stops being recorded, which is the same silence one line earlier: the "
     "module was chosen, a model was paid, and nothing says so",
     "openfactory/onboarding/concepts.py",
     '            gaps.append(Gap(kind="not-described", path=module.path,\n'
     '                            detail="the agent\'s answer could not be read as the requested '
     'json"))\n'
     "            continue",
     "            continue"),

    # ── the layout loses a fact ──────────────────────────────────────────────────────────────────
    ("two concepts sharing a title collapse onto one file again, so the second silently overwrites "
     "the first and the bundle still reads as complete — found by the first end-to-end run while "
     "every unit test was green",
     "openfactory/knowledge/okf.py",
     "        candidate, n = base, 1\n"
     "        while candidate.as_posix() in taken:\n"
     "            n += 1\n"
     '            candidate = base.with_name(f"{base.stem}-{n}{base.suffix}")',
     "        candidate = base"),

    ("the index re-derives each concept's path instead of using the assignment the writer actually "
     "used, so a link opens a concept it does not name — the failure is a wrong answer to a "
     "reader's click, which nothing else in the bundle would contradict",
     "openfactory/knowledge/okf.py",
     "        placed = assign_paths(concepts)",
     "        placed = [(c, concept_path(c)) for c in concepts]"),
]

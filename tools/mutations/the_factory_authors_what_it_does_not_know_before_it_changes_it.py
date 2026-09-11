"""The factory authors what it does not know — the cuts that spend wrong or answer nothing.

ROW 1 IS THE DEFAULT SPENDING: `advise` authors too. ROW 2 IS `enforce` NEVER AUTHORING (the
gate as it was). ROW 3 IS THE STALE JUDGEMENT: authored, published, and the old report still
parks the job. ROW 4 IS THE CONCEPTS KEPT TO THIS JOB (never published). ROW 5 IS THE BUDGET
GOING TO THE RANKING instead of the dark modules. ROW 6 IS THE COVERING WRITING NOTHING.
ROW 7 IS "COVERED" CLAIMED FOR EVERY PATH.
"""

TEST = "tests/test_the_factory_authors_what_it_does_not_know_before_it_changes_it.py"

MUTATIONS = [
    ("`advise` authors too — the default spends",
     "openfactory/orchestrator/machine.py",
     '            if (mode == "enforce" and bundle is not None and report.stance() == "dark"',
     '            if (bundle is not None and report.stance() == "dark"'),

    ("`enforce` never authors — the gate as it was",
     "openfactory/orchestrator/machine.py",
     "                report, authored = self._author_first(ticket, bundle, report, paths)",
     "                pass"),

    ("the old report parks the job after the concepts were written",
     "openfactory/orchestrator/machine.py",
     "        return judge(bundle, self.repo_path, paths), covered.authored",
     "        return report, covered.authored"),

    ("the concepts stay with this job — never published",
     "openfactory/orchestrator/machine.py",
     "        if home is None or not publish_bundle(bundle, home[0], subpath=home[1],\n"
     "                                              source_commit=commit):",
     "        if home is None or not True:"),

    ("the budget goes to the ranking, not to the dark modules",
     "openfactory/onboarding/concepts.py",
     # re-pinned 2026-09-07: the call carries the answered gaps now (ADR-0048 §7, #82)
     "        survey, ask=ask_fn, budget=budget, modules=wanted, commit=commit,\n"
     "        generated_at=generated_at, language=getattr(project, \"language\", None),\n"
     "        fingerprints=fingerprints, answered=answered)\n    return Authored(concepts, gaps, mode)",
     "        survey, ask=ask_fn, budget=budget, commit=commit,\n"
     "        generated_at=generated_at, language=getattr(project, \"language\", None),\n"
     "        fingerprints=fingerprints, answered=answered)\n    return Authored(concepts, gaps, mode)"),

    ("the covering writes nothing",
     "openfactory/onboarding/cover.py",
     "    write_okf(bundle, manifest=manifest, concepts=authored.concepts)",
     "    write_okf(bundle, manifest=manifest, concepts=[])"),

    ("every path is claimed covered",
     "openfactory/onboarding/cover.py",
     "    covered = tuple(p for p in wanted if p in cited)",
     "    covered = tuple(wanted)"),
]

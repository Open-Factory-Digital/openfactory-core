"""A module is an area, and the eleven ways the survey stops saying which areas matter.

WHAT THIS PROTECTS. The survey knew everything about a module except the one fact that predicts
where the next change goes, and it ordered its own table by SIZE. That table is capped at 40, so on
a large repository the sort decides which forty modules a reader — and the one agent pass — ever
see, and by size the answer is routinely the forty nobody has opened in years.

ROWS 6 AND 7 ARE THE FINDING ITSELF. Churn sat on one side and `tests_inside` / `tested_by` on the
other, both correct, and nothing crossed them — so the most-changed undefended area of a codebase
rendered exactly like the quietest one. Measured on a real client bundle: the most-changed business
file in the repository had no live test, and its own test file existed with every line commented
out. Every fact recorded separately; the sentence nowhere.

ROW 9 IS THE ONE THAT LOOKS LIKE A NICETY AND IS NOT. Without a history every `file_changes` is 0,
so the finding is empty — and an empty finding rendered as "every area that changed is named by a
test" is a MEASUREMENT nobody took. `hot_risk_unknown` is the difference between a fact and a
silence, and this whole file exists because that distinction keeps getting lost one field at a
time.

ROW 3 IS A TRAP THIS FIXTURE WAS REBUILT TO REACH. The first version had `reporting` biggest AND
busiest, so a `busiest_modules` that had lost its sort returned the same order and passed. The
fixture now makes the two orderings disagree, by arithmetic stated in its docstring.
"""

TEST = "tests/test_the_areas_that_change_are_the_ones_that_matter.py"

MUTATIONS = [
    # ── the join ────────────────────────────────────────────────────────────────────────────────
    ("the history never reaches the module rows, so every module reports zero churn and the whole "
     "ordering silently falls back to size while still CLAIMING to be ordered by change",
     "openfactory/onboarding/context.py",
     "    rows = _module_rows(module_map.modules, files, history)",
     "    rows = _module_rows(module_map.modules, files, None)"),

    ("a changed path is attributed by its own directory instead of the module that OWNS it, so a "
     "repository that folds subfolders under one project (every .NET solution) loses its churn "
     "into modules that do not exist",
     "openfactory/onboarding/context.py",
     "        owner = owner_of(row.path)\n        if not owner:\n            continue",
     '        owner = row.path.rsplit("/", 1)[0] if "/" in row.path else None\n'
     "        if not owner:\n            continue"),

    ("the people are summed per FILE, so one maintainer who touched four files of a module is "
     "reported as a team of four — the opposite of the truth this number exists to carry",
     "openfactory/onboarding/context.py",
     '            author_count=len(churn.get(m.name, {}).get("authors", ())),',
     '            author_count=sum(len(f.authors) for f in (history.files if history else ())\n'
     "                             if f.path.startswith(m.path)),"),

    ("the module keeps only the FIRST date it sees rather than the most recent, so a module "
     "touched yesterday reports the day it entered the window",
     "openfactory/onboarding/context.py",
     '        seen["last"] = max(seen["last"], row.last_touched)',
     '        seen["last"] = seen["last"] or row.last_touched'),

    # ── the ordering, which decides which forty a reader sees ───────────────────────────────────
    ("the busiest ordering is the biggest ordering, so the forty modules a reader gets are the "
     "forty largest — routinely the forty nobody has opened in years",
     "openfactory/onboarding/context.py",
     "        return sorted(self.modules, key=lambda m: (-m.file_changes, -m.author_count, "
     "m.name))",
     "        return sorted(self.modules, key=lambda m: (-m.files, m.name))"),

    ("the table goes back to size order while the note above it still says it is ordered by "
     "change — a correct table under a caption that inverts it",
     "openfactory/onboarding/context.py",
     "    ordered = s.busiest_modules if (h and h.usable) else s.biggest_modules",
     "    ordered = s.biggest_modules"),

    ("the ordering is not stated, so a reader assumes the wrong one and draws exactly the wrong "
     "conclusion from a table that is right",
     "openfactory/onboarding/context.py",
     "    out.append(f\"_{w['t_order_churn'] if (h and h.usable) else w['t_order_size']}_\")",
     '    out.append("")'),

    ("a survey nobody handed a history returns nothing to order at all, so every caller that "
     "renders a module table gets an empty one where it used to get the map",
     "openfactory/onboarding/context.py",
     "        if not (self.history and self.history.usable):\n"
     "            return self.biggest_modules",
     "        if not (self.history and self.history.usable):\n"
     "            return []"),

    # ── the finding ─────────────────────────────────────────────────────────────────────────────
    ("the finding lists every changed module rather than the undefended ones, so the one area that "
     "matters is buried in a list of areas that do not — a finding turned into noise",
     "openfactory/onboarding/context.py",
     "        return [m for m in self.busiest_modules if m.changes_and_no_test_names_it]",
     "        return list(self.busiest_modules)"),

    ("a QUIET module nothing names becomes a finding, so an attic nobody has opened since 2019 "
     "ranks beside the file every change lands on",
     "openfactory/onboarding/context.py",
     "        return self.file_changes > 0 and self.named_by_no_test",
     "        return self.named_by_no_test"),

    ("a module a test file NAMES is reported as undefended, which is the finding claiming the "
     "opposite of what the repository shows",
     "openfactory/onboarding/context.py",
     "        return self.tests_inside == 0 and not self.tested_by",
     "        return self.tests_inside == 0"),

    # ── the state that is not a measurement ─────────────────────────────────────────────────────
    ("with no history read, the empty finding renders as \"every area that changed is named by a "
     "test\" — a measurement nobody took, in the one place a reader would trust it most",
     "openfactory/onboarding/context.py",
     "    if h is None or not h.usable:\n"
     "        # An empty list here would mean \"every changed area is named by a test\", which is a\n"
     "        # measurement. Without the history there is no measurement, only an absence.\n"
     "        out.append(f\"- {w['hot_risk_unknown']}\")",
     "    if False:\n"
     "        out.append(f\"- {w['hot_risk_none']}\")"),

    ("the finding stops claiming to be about naming and starts reading as coverage, which "
     "overclaims what name matching can possibly show and costs the reader's trust in the rest",
     "openfactory/onboarding/context.py",
     "            out.append(f\"> {w['hot_risk_note']}\")",
     '            out.append("")'),
]

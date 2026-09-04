"""The merge re-authors the concepts its change invalidated — and the manifests stop colliding.

ROW 1 IS THE COLLISION, PUT BACK. The OKF manifest returns to `manifest.yaml`, the map's filename,
and the guard that runs both writers on one directory must see one of them lose.

ROWS 2-4 ARE THE RENEWAL LYING BY OMISSION: nothing is ever broken; the rewritten concepts are not
written; the broken ones the budget did not reach are not recorded. Each is the state before this
slice wearing this slice's log line.

ROWS 5-6 ARE THE AUTHORING SEAM. `modules=` ignored means the renewal spends the budget on the
ranking instead of on the concepts known to be wrong; the shortest owner instead of the longest
sends a file in `core/sub` to `core`'s prompt.

ROW 7 IS THE POLLUTION, PUT BACK: the whole published bundle copied under the tree before the
build, so the map's own extension survey counts the OKF's files as the client's and a renewal that
writes `index.md` makes every next build differ — measured, it published forever.

ROWS 8-9 ARE THE WIRING IN THE ACTIVITY. A renewal that wrote and an activity that reports
"unchanged" publishes nothing; an activity that never calls the renewal is the previous state.
"""

TEST = "tests/test_the_merge_re_authors_what_it_invalidated.py"

MUTATIONS = [
    ("the OKF manifest goes back to the map's filename, and the two take turns destroying each "
     "other again",
     "openfactory/knowledge/okf.py",
     'OKF_MANIFEST_FILE = "okf.yaml"',
     'OKF_MANIFEST_FILE = "manifest.yaml"'),

    ("the renewal never sees a broken concept — the checker is called and its answer discarded",
     "openfactory/onboarding/renew.py",
     "    broken = list(report.broken)",
     "    broken = []"),

    ("the rewritten concepts are authored, paid for, and not written",
     "openfactory/onboarding/renew.py",
     "    write_okf(bundle_dir, manifest=manifest, concepts=rewritten)",
     "    write_okf(bundle_dir, manifest=manifest, concepts=[])"),

    ("a broken concept the round could not rewrite vanishes instead of becoming a named gap",
     "openfactory/onboarding/renew.py",
     "        for b in left",
     "        for b in []"),

    ("`modules=` is ignored and the budget goes to the ranking, not to the concepts known to be "
     "wrong",
     "openfactory/onboarding/concepts.py",
     "    chosen = (list(modules)[:min(budget, MAX_CONCEPT_BUDGET)] if modules is not None\n"
     "              else rank_modules(survey, budget=budget))",
     "    chosen = rank_modules(survey, budget=budget)"),

    ("the first matching module owns the file instead of the longest, so `core/sub/x.py` is "
     "re-authored as `core`",
     "openfactory/onboarding/concepts.py",
     "            if file_parts[:len(mod_parts)] == mod_parts and len(mod_parts) > best_len:",
     "            if file_parts[:len(mod_parts)] == mod_parts and best is None:"),

    ("the whole published bundle is copied in before the build again, so the map counts the "
     "OKF's own files as the client's and a renewal never converges",
     "openfactory/runtime/temporal/activities.py",
     "            for name in (MODULES_FILE, MANIFEST_FILE):\n"
     "                if (published / name).is_file():\n"
     "                    shutil.copy2(published / name, dest / name)",
     "            shutil.copytree(published, dest, dirs_exist_ok=True)"),

    ("the activity reports 'unchanged' whenever the map is unchanged, even when the renewal wrote",
     "openfactory/runtime/temporal/activities.py",
     "        if not map_changed and not renewal.wrote:",
     "        if not map_changed:"),

    ("the activity never calls the renewal — the previous state with a log line",
     "openfactory/runtime/temporal/activities.py",
     "        renewal = renew_concepts(project, dest, Path(repo_path), commit=commit, generated_at=now)",
     '        renewal = __import__("openfactory.onboarding.renew", fromlist=["Renewal"]).Renewal(0, 0, 0, 0, "skipped")'),
]

"""The module map is published beside the concepts — the cuts that put the first live onboarding
back the way it was (2026-09-06).

ROW 1 IS THE MEASURED SHAPE: the context box publishes concepts and no map, and every job reads
"no bundle" at a path holding five concepts.

ROW 2 IS THE ONE-LEVEL-DOWN DEFECT `write_bundle_dir` exists to prevent: the map written under
`knowledge/` inside the bundle folder, where `fetch_bundle` never looks.

ROW 3 IS THE MULTIREPO OVERWRITE: the bundle home at `.okf/` itself, so the job — reading at the
subpath — finds nothing and two sources would share one namespace.

ROW 4 IS THE BUDGET SWALLOWING THE MAP: a project that budgets 0 concepts loses the one artefact
that costs nothing.

ROW 5 IS THE WRITER APPENDING `knowledge/` ON ITS OWN.

ROWS 6-7 ARE THE SOURCE PULL REQUEST: staging the map again (D-2), and a body that still sends
the reviewer to `knowledge/`.
"""

TEST = "tests/test_the_map_is_published_beside_the_concepts.py"
SOURCE_PR = "tests/test_onboard_proposes_a_measured_setup.py"

MUTATIONS = [
    ("the context box publishes concepts and no map — the 2026-09-06 shape",
     "openfactory/onboarding/onboard.py",
     "        wrote += _write_map(project, source, docs_clone, commit=history.head)\n",
     "        wrote += []\n"),

    ("the map lands one level down, under `knowledge/`, where fetch_bundle never looks",
     "openfactory/onboarding/onboard.py",
     "        written = write_bundle_dir(bundle, home)\n",
     "        from openfactory.knowledge.bundle import write_bundle\n"
     "        written = write_bundle(bundle, home)\n"),

    ("the bundle home is `.okf/` itself — the job reads at the subpath and finds nothing",
     "openfactory/onboarding/onboard.py",
     "    here = Path(docs_clone) / okf_subpath(repo_of(project))\n",
     "    here = Path(docs_clone) / okf_subpath(repo_of(project)).parts[0]\n"),

    ("the map is gated by the concept budget — a budget of 0 publishes nothing",
     "openfactory/onboarding/onboard.py",
     "    from openfactory.knowledge.bundle import build_bundle, write_bundle_dir\n\n"
     "    try:\n"
     "        bundle = build_bundle(source, commit=commit, generated_at=_now_iso())\n",
     "    from openfactory.knowledge.bundle import build_bundle, write_bundle_dir\n\n"
     "    if _concept_budget(project, source) <= 0:\n"
     "        return []\n"
     "    try:\n"
     "        bundle = build_bundle(source, commit=commit, generated_at=_now_iso())\n"),

    ("write_bundle_dir appends `knowledge/` on its own",
     "openfactory/knowledge/bundle.py",
     "    dest = Path(dest)\n    if not force:\n",
     "    dest = Path(dest) / BUNDLE_DIRNAME\n    if not force:\n"),

    ("the source pull request stages the map again (D-2)",
     "openfactory/onboarding/onboard.py",
     '            branch="openfactory/onboard", extra_paths=extras,\n',
     '            branch="openfactory/onboard", extra_paths=[*extras, "knowledge"],\n',
     SOURCE_PR),

    ("the body still sends the reviewer to `knowledge/`",
     "openfactory/onboarding/onboard.py",
     '        lines.append(f"The module map ({out.modules} modules) is not in this pull request '
     'and "\n',
     '        lines.append(f"`knowledge/` is the module map ({out.modules} modules); it is not in '
     'this pull request and "\n',
     SOURCE_PR),
]
